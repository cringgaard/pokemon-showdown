"""B10 participant-facing orchestration for the deterministic Champions snow bot.

This module wires the already-separated B3-B9 policy layers into one legal
decision path. It deliberately does not modify the tournament worker/runtime:
``choose_action(state)`` is the participant contract consumed by worker.py.

Normal turns preserve the one-way dependency graph:

    public BotState
      -> B3 knowledge
      -> B4 threats / runtime strategy / resources
      -> B6 candidate-independent opponent responses
      -> B7 projection for every legal candidate x retained response
      -> B8 per-response utility
      -> B9 robust aggregation / tactical ranking

Team Preview routes to B5. Forced replacement requests are not simultaneous
move turns, so they use a small deterministic public-information replacement
selector instead of fabricating a B6 opponent move response.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping

from .actions import CanonicalLegalAction
from .aggregation import (
	CandidateEvaluationInput,
	CandidateResponseCase,
	CandidateRanking,
	rank_candidates,
)
from .config import PolicyConfig, default_config
from .mechanics import CHAMPIONS_FORMAT, MechanicsSnapshot, to_id
from .orchestration_config import OrchestrationConfig, default_orchestration_config, pair_synergy_key
from .preview import PreviewConfig, TeamPreviewAssessment, assess_team_preview, default_preview_config
from .projection import ProjectionConfig, default_projection_config, project_turn
from .reconstruction import KnowledgeState, build_knowledge_state
from .responses import (
	OpponentJointResponse,
	OpponentResponseSet,
	ResponseGenerationConfig,
	default_response_generation_config,
	generate_opponent_responses,
)
from .scoring import ScoringConfig, default_scoring_config, evaluate_response_utility
from .strategy import PlanLabel, RuntimeStrategyAssessment, assess_runtime_strategy
from .threats import ThreatModel, build_threat_model
from .trace import (
	CandidateActionTrace,
	DecisionTrace,
	OpponentResponseHypothesis,
	TraceLevel,
	TraceRuntime,
	TraceVersions,
)


POLICY_VERSION = "snow-policy-b10-v1"
DEFAULT_MECHANICS_FILENAME = "champions-mechanics.json"
MECHANICS_PATH_ENV = "DETERMINISTIC_SNOW_MECHANICS_PATH"
TRACE_STDERR_ENV = "DETERMINISTIC_SNOW_TRACE_STDERR"


class PolicyContractError(ValueError):
	"""Raised when B10 receives a state outside the deterministic policy contract."""


class RuntimeMode(str, Enum):
	FULL = "FULL"
	MEDIUM = "MEDIUM"
	LOW = "LOW"
	EMERGENCY = "EMERGENCY"


@dataclass(frozen=True)
class PolicyDecision:
	response: dict[str, Any]
	action_id: str
	phase: str
	runtime_mode: RuntimeMode
	trace: DecisionTrace | None


@dataclass(frozen=True)
class _ForcedSwitchScore:
	action: CanonicalLegalAction
	score: float


class SnowPolicy:
	"""Reusable B10 policy object; mechanics are immutable and cached per worker."""

	def __init__(
		self,
		mechanics: MechanicsSnapshot,
		*,
		policy_config: PolicyConfig | None = None,
		preview_config: PreviewConfig | None = None,
		response_config: ResponseGenerationConfig | None = None,
		projection_config: ProjectionConfig | None = None,
		scoring_config: ScoringConfig | None = None,
		orchestration_config: OrchestrationConfig | None = None,
		trace_level: TraceLevel = TraceLevel.TOP_CANDIDATES,
	):
		self.mechanics = mechanics.require_champions_format()
		self.policy_config = policy_config or default_config()
		self.preview_config = preview_config or default_preview_config()
		self.response_config = response_config or default_response_generation_config()
		self.projection_config = projection_config or default_projection_config()
		self.scoring_config = scoring_config or default_scoring_config()
		self.orchestration_config = orchestration_config or default_orchestration_config()
		self.trace_level = trace_level
		self.policy_config.validate()
		self.preview_config.validate()
		self.response_config.validate()
		self.projection_config.validate()
		self.scoring_config.validate()
		self.orchestration_config.validate()

	@classmethod
	def from_mechanics_path(cls, path: str | Path, **kwargs) -> "SnowPolicy":
		return cls(MechanicsSnapshot.load(path).require_champions_format(), **kwargs)

	def choose_action(self, state: Mapping[str, Any]) -> dict[str, Any]:
		return self.decide(state).response

	def decide(self, state: Mapping[str, Any]) -> PolicyDecision:
		started = time.monotonic()
		self._validate_state(state)
		knowledge = build_knowledge_state(state, self.mechanics)
		if not knowledge.legal_actions:
			raise PolicyContractError("request.legal_actions must contain at least one action")
		phase = knowledge.phase
		mode = self._runtime_mode(state, started)

		if phase == "team_preview":
			assessment = assess_team_preview(knowledge, self.mechanics, config=self.preview_config)
			selected = assessment.selected.action
			trace = self._preview_trace(state, assessment, started)
			return PolicyDecision(_bot_response(selected), selected.action_id, phase, mode, trace)

		if phase == "forced_switch":
			threats = build_threat_model(knowledge, self.mechanics)
			strategy = assess_runtime_strategy(
				knowledge, self.mechanics, threats=threats, config=self.policy_config,
			)
			ordered = self._rank_forced_switches(knowledge, strategy)
			selected = ordered[0].action
			trace = self._forced_switch_trace(state, strategy, threats, ordered, started)
			return PolicyDecision(_bot_response(selected), selected.action_id, phase, mode, trace)

		if phase != "turn":
			raise PolicyContractError(f"Unsupported battle phase: {phase!r}")
		return self._decide_turn(state, knowledge, started, mode)

	def _decide_turn(
		self,
		state: Mapping[str, Any],
		knowledge: KnowledgeState,
		started: float,
		mode: RuntimeMode,
	) -> PolicyDecision:
		threats = build_threat_model(knowledge, self.mechanics)
		strategy = assess_runtime_strategy(
			knowledge, self.mechanics, threats=threats, config=self.policy_config,
		)
		turn_policy_config = self._policy_config_for_mode(mode)
		response_set = generate_opponent_responses(
			knowledge,
			self.mechanics,
			strategy=strategy,
			threats=threats,
			policy_config=turn_policy_config,
			config=self.response_config,
		)

		candidate_inputs: list[CandidateEvaluationInput] = []
		for candidate in knowledge.legal_actions:
			cases: list[CandidateResponseCase] = []
			for response in response_set.responses:
				projection = project_turn(
					knowledge,
					self.mechanics,
					candidate,
					response,
					config=self.projection_config,
				)
				utility = evaluate_response_utility(
					knowledge,
					strategy,
					candidate,
					response,
					projection,
					policy_config=turn_policy_config,
					scoring_config=self.scoring_config,
				)
				cases.append(CandidateResponseCase(response, projection, utility))
			candidate_inputs.append(CandidateEvaluationInput(candidate, tuple(cases)))

		ranking = rank_candidates(
			knowledge,
			strategy,
			response_set,
			tuple(candidate_inputs),
			policy_config=turn_policy_config,
		)
		selected = next(
			item.candidate for item in ranking.candidates
			if item.candidate.action_id == ranking.selected_action_id
		)
		trace = self._turn_trace(state, strategy, threats, response_set, ranking, started)
		return PolicyDecision(_bot_response(selected), selected.action_id, "turn", mode, trace)

	def _policy_config_for_mode(self, mode: RuntimeMode) -> PolicyConfig:
		if mode is RuntimeMode.FULL:
			return self.policy_config
		base = self.policy_config.opponent_response
		individual_cap, joint_cap = self.orchestration_config.degraded_response_caps[mode.value]
		return replace(
			self.policy_config,
			opponent_response=replace(
				base,
				max_individual_actions_per_pokemon=min(base.max_individual_actions_per_pokemon, individual_cap),
				max_joint_responses=min(base.max_joint_responses, joint_cap),
			),
		)

	def _runtime_mode(self, state: Mapping[str, Any], started: float) -> RuntimeMode:
		runtime = state.get("runtime")
		deadline_ms = runtime.get("deadline_ms", 0) if isinstance(runtime, Mapping) else 0
		if isinstance(deadline_ms, bool) or not isinstance(deadline_ms, (int, float)):
			deadline_ms = 0
		elapsed_ms = (time.monotonic() - started) * 1000.0
		remaining = max(0.0, float(deadline_ms) - elapsed_ms)
		thresholds = self.policy_config.runtime
		if remaining >= thresholds.full_mode_minimum_ms:
			return RuntimeMode.FULL
		if remaining >= thresholds.medium_mode_minimum_ms:
			return RuntimeMode.MEDIUM
		if remaining >= thresholds.low_mode_minimum_ms:
			return RuntimeMode.LOW
		return RuntimeMode.EMERGENCY

	def _rank_forced_switches(
		self,
		knowledge: KnowledgeState,
		strategy: RuntimeStrategyAssessment,
	) -> tuple[_ForcedSwitchScore, ...]:
		own_by_id = {pokemon.id: pokemon for pokemon in knowledge.own_team}
		resources = {item.pokemon_id: item for item in strategy.resources}
		scores: list[_ForcedSwitchScore] = []
		config = self.orchestration_config
		for action in knowledge.legal_actions:
			if action.payload.get("kind") != "turn":
				raise PolicyContractError("forced_switch legal action must be a turn-shaped action")
			score = 0.0
			switched: list[str] = []
			for slot_action in action.payload.get("actions", {}).values():
				if not slot_action:
					continue
				if slot_action.get("type") not in {"switch", "revive"}:
					raise PolicyContractError("forced_switch action contains a non replacement action")
				pokemon_id = str(slot_action.get("pokemon", ""))
				pokemon = own_by_id.get(pokemon_id)
				if pokemon is None:
					raise PolicyContractError("forced_switch action references an unknown own Pokemon")
				switched.append(pokemon_id)
				resource = resources.get(pokemon_id)
				if resource is not None:
					score += config.replacement_resource_value_factor * resource.value
				score += self._replacement_role_bonus(pokemon.species, strategy)
				score += self._replacement_matchup_score(pokemon.types, knowledge)
				if to_id(pokemon.species) == "ninetalesalola":
					weather = knowledge.field.weather.value
					if not isinstance(weather, str) or to_id(weather) != "snow":
						score += config.replacement_weather_reset_bonus
			if len(switched) > 1:
				species = {to_id(own_by_id[pokemon_id].species) for pokemon_id in switched}
				for pair in pair_synergy_key(species):
					score += config.replacement_pair_synergies[pair]
			scores.append(_ForcedSwitchScore(action, score))
		return tuple(sorted(scores, key=lambda item: (-item.score, item.action.canonical_key)))

	def _replacement_role_bonus(self, species: str, strategy: RuntimeStrategyAssessment) -> float:
		primary = strategy.scores.primary_plan
		plan = primary if primary in {
			PlanLabel.GLACEON_FORTRESS.value, PlanLabel.AGGRON_FORTRESS.value,
		} else "DEFAULT"
		return float(self.orchestration_config.replacement_role_bonuses[plan].get(to_id(species), 0.0))

	def _replacement_matchup_score(self, defending_types: tuple[str, ...], knowledge: KnowledgeState) -> float:
		roster = {pokemon.id: pokemon for pokemon in knowledge.opponent_roster}
		multipliers: list[float] = []
		config = self.orchestration_config
		for active in knowledge.opponent_active:
			identity = active.established_identity.value
			if not isinstance(identity, str):
				continue
			pokemon = roster.get(identity)
			if pokemon is None:
				continue
			for known_move in pokemon.moves:
				try:
					move = self.mechanics.move(known_move.id)
				except KeyError:
					continue
				if move.base_power <= 0 or move.category == "Status":
					continue
				try:
					multiplier = self.mechanics.type_multiplier(move.type, defending_types)
				except (KeyError, ValueError):
					continue
				power_factor = move.base_power / config.matchup_move_power_reference
				power_factor = min(config.matchup_move_power_cap, max(config.matchup_move_power_floor, power_factor))
				multipliers.append(multiplier * power_factor)
		if not multipliers:
			return 0.0
		worst = max(multipliers)
		average = sum(multipliers) / len(multipliers)
		return (
			config.matchup_base_value -
			config.matchup_worst_multiplier_penalty * worst -
			config.matchup_average_multiplier_penalty * average
		)

	def _validate_state(self, state: Mapping[str, Any]) -> None:
		if not isinstance(state, Mapping):
			raise PolicyContractError("state must be an object")
		if state.get("schema_version") != 2:
			raise PolicyContractError("deterministic snow policy requires BotState.schema_version == 2")
		battle = state.get("battle")
		if not isinstance(battle, Mapping):
			raise PolicyContractError("state.battle must be an object")
		if to_id(str(battle.get("format", ""))) != CHAMPIONS_FORMAT:
			raise PolicyContractError(
				f"deterministic snow policy requires {CHAMPIONS_FORMAT}, got {battle.get('format')!r}"
			)
		request = state.get("request")
		if not isinstance(request, Mapping) or not isinstance(request.get("legal_actions"), list):
			raise PolicyContractError("state.request.legal_actions must be an array")

	def _versions(self) -> TraceVersions:
		return TraceVersions(
			POLICY_VERSION,
			f"{self.policy_config.versions.config}+{self.orchestration_config.version}",
			self.scoring_config.version,
			self.mechanics.snapshot_hash,
			self.policy_config.versions.team,
			self.mechanics.format.id,
			self.mechanics.format.mod,
		)

	def _preview_trace(
		self,
		state: Mapping[str, Any],
		assessment: TeamPreviewAssessment,
		started: float,
	) -> DecisionTrace | None:
		if self.trace_level is TraceLevel.NONE:
			return None
		candidates = tuple(
			CandidateActionTrace(item.action, None, None, None, item.final_score, (), (), ())
			for item in self._preview_candidates_for_trace(assessment)
		)
		responses = tuple(
			OpponentResponseHypothesis(
				f"preview:{'+'.join(item.members)}", item.weight, item.reasons, item.members,
			)
			for item in assessment.lead_hypotheses
		)
		trace = DecisionTrace(
			1,
			self.trace_level,
			_decision_id(state),
			_turn(state),
			self._versions(),
			None,
			(),
			responses,
			candidates,
			assessment.selected_action_id,
			TraceRuntime(_elapsed_ms(started), len(assessment.candidates), len(responses), len(assessment.candidates)),
		)
		trace.validate()
		return trace

	def _forced_switch_trace(
		self,
		state: Mapping[str, Any],
		strategy: RuntimeStrategyAssessment,
		threats: ThreatModel,
		ordered: tuple[_ForcedSwitchScore, ...],
		started: float,
	) -> DecisionTrace | None:
		if self.trace_level is TraceLevel.NONE:
			return None
		selected = ordered[0].action.action_id
		candidates = tuple(
			CandidateActionTrace(item.action, None, None, None, item.score, (), (), ())
			for item in self._ranked_for_trace(ordered)
		)
		trace = DecisionTrace(
			1,
			self.trace_level,
			_decision_id(state),
			_turn(state),
			self._versions(),
			strategy.scores,
			threats.major_threats,
			(),
			candidates,
			selected,
			TraceRuntime(_elapsed_ms(started), len(ordered), 0, len(ordered)),
		)
		trace.validate()
		return trace

	def _turn_trace(
		self,
		state: Mapping[str, Any],
		strategy: RuntimeStrategyAssessment,
		threats: ThreatModel,
		response_set: OpponentResponseSet,
		ranking: CandidateRanking,
		started: float,
	) -> DecisionTrace | None:
		if self.trace_level is TraceLevel.NONE:
			return None
		candidates = self._candidate_traces_for_level(ranking)
		responses = tuple(_response_hypothesis(item) for item in response_set.responses)
		trace = DecisionTrace(
			1,
			self.trace_level,
			_decision_id(state),
			_turn(state),
			self._versions(),
			strategy.scores,
			threats.major_threats,
			responses,
			candidates,
			ranking.selected_action_id,
			TraceRuntime(
				_elapsed_ms(started),
				len(ranking.candidates),
				len(response_set.responses),
				len(ranking.candidates) * len(response_set.responses),
			),
		)
		trace.validate()
		return trace

	def _candidate_traces_for_level(self, ranking: CandidateRanking) -> tuple[CandidateActionTrace, ...]:
		all_traces = ranking.candidate_traces()
		if self.trace_level is TraceLevel.FULL:
			return all_traces
		if self.trace_level is TraceLevel.TOP_CANDIDATES:
			return all_traces[:min(5, len(all_traces))]
		return all_traces[:1]

	def _preview_candidates_for_trace(self, assessment: TeamPreviewAssessment):
		if self.trace_level is TraceLevel.FULL:
			return assessment.candidates
		if self.trace_level is TraceLevel.TOP_CANDIDATES:
			return assessment.candidates[:min(5, len(assessment.candidates))]
		return assessment.candidates[:1]

	def _ranked_for_trace(self, ordered: tuple[_ForcedSwitchScore, ...]):
		if self.trace_level is TraceLevel.FULL:
			return ordered
		if self.trace_level is TraceLevel.TOP_CANDIDATES:
			return ordered[:min(5, len(ordered))]
		return ordered[:1]


_DEFAULT_POLICY: SnowPolicy | None = None


def default_mechanics_path() -> Path:
	environment = os.environ.get(MECHANICS_PATH_ENV)
	if environment:
		return Path(environment).expanduser().resolve()
	return Path(__file__).resolve().with_name(DEFAULT_MECHANICS_FILENAME)


def choose_action(state: Mapping[str, Any]) -> dict[str, Any]:
	"""Participant entrypoint used by the persistent tournament Python worker."""
	global _DEFAULT_POLICY
	if _DEFAULT_POLICY is None:
		_DEFAULT_POLICY = SnowPolicy.from_mechanics_path(default_mechanics_path(), trace_level=TraceLevel.TOP_CANDIDATES)
	decision = _DEFAULT_POLICY.decide(state)
	if decision.trace is not None and os.environ.get(TRACE_STDERR_ENV) == "1":
		sys.stderr.write(decision.trace.to_json() + "\n")
		sys.stderr.flush()
	return decision.response


def _bot_response(action: CanonicalLegalAction) -> dict[str, Any]:
	payload = action.payload
	if payload.get("kind") == "team_preview":
		return {"team": list(payload.get("team", []))}
	if payload.get("kind") == "turn":
		actions = {
			position: value
			for position, value in payload.get("actions", {}).items()
			if value is not None
		}
		return {"actions": actions}
	raise PolicyContractError("cannot convert unknown canonical action kind to BotResponse")


def _response_hypothesis(response: OpponentJointResponse) -> OpponentResponseHypothesis:
	return OpponentResponseHypothesis(
		response.canonical_key,
		response.weight,
		response.reasons,
		tuple(action.canonical_key for action in response.actions),
	)


def _decision_id(state: Mapping[str, Any]) -> int:
	runtime = state.get("runtime")
	value = runtime.get("decision_id", 0) if isinstance(runtime, Mapping) else 0
	return int(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _turn(state: Mapping[str, Any]) -> int:
	battle = state.get("battle")
	value = battle.get("turn", 0) if isinstance(battle, Mapping) else 0
	return int(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _elapsed_ms(started: float) -> float:
	return max(0.0, (time.monotonic() - started) * 1000.0)
