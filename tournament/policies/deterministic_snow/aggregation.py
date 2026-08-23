"""B9 robust cross-response aggregation and tactical ranking.

B9 consumes already-computed B6/B7/B8 artifacts. It never regenerates opponent
responses, projects turns, or extracts per-response features. It aggregates one
candidate's utilities across the shared B6 response distribution, exposes the
cross-response features reserved by B8, applies post-projection tactical score
adjustments, and ranks the supplied legal candidates deterministically.

Participant-facing orchestration remains B10.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

from .actions import CanonicalLegalAction
from .config import PolicyConfig, default_config
from .mechanics import to_id
from .projection import ProjectedOutcome, ProjectionResult, ProjectionUncertainty
from .reconstruction import KnowledgeState
from .responses import OpponentJointResponse, OpponentResponseSet
from .scoring import ResponseUtilityEvaluation
from .strategy import PlanLabel, RuntimeStrategyAssessment
from .trace import (
	CandidateActionTrace,
	FeatureContribution,
	ResponseEvaluationTrace,
	TacticalRuleAdjustment,
)


class AggregationContractError(ValueError):
	"""Raised when B9 inputs do not describe the same legal decision problem."""


TACTICAL_RULE_IDS = frozenset({
	"FOLLOW_ME_RESCUE",
	"OBVIOUS_LETHAL_GLACEON",
	"CASH_OUT",
	"FAILED_WEATHER_DEPENDENT_MOVE",
	"ABILITY_PUNISHMENT",
	"ZERO_EFFECT",
	"BASE_AGGRON_DANGER",
})

_CROSS_RESPONSE_FEATURE_IDS = frozenset({"FRAGILE_PREDICTION", "ROBUST_ACROSS_RESPONSES"})
_TEAM_DAMAGING_MOVES = frozenset({
	"blizzard", "freezedry", "mudslap", "bodypress", "heavyslam",
	"armorcannon", "psychic", "thunderbolt", "grassknot",
})
_ABILITY_PUNISHMENT_IDS = frozenset({"defiant", "competitive", "contrary"})


@dataclass(frozen=True)
class AggregationConfig:
	version: str
	expected_utility_weight: float
	credible_bad_case_weight: float
	utility_spread_scale: float
	robust_across_responses_weight: float
	fragile_prediction_weight: float
	tactical_rule_weights: Mapping[str, float]

	def validate(self) -> None:
		if not isinstance(self.version, str) or not self.version.strip():
			raise ValueError("aggregation version must be non-empty")
		for name in (
			"expected_utility_weight", "credible_bad_case_weight", "utility_spread_scale",
			"robust_across_responses_weight", "fragile_prediction_weight",
		):
			value = getattr(self, name)
			if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
				raise ValueError(f"aggregation.{name} must be a finite number")
		if self.expected_utility_weight < 0 or self.credible_bad_case_weight < 0:
			raise ValueError("aggregation expected/bad-case weights must be non-negative")
		if not math.isclose(
			self.expected_utility_weight + self.credible_bad_case_weight, 1.0,
			rel_tol=0.0, abs_tol=1e-9,
		):
			raise ValueError("aggregation expected/bad-case weights must sum to one")
		if self.utility_spread_scale <= 0:
			raise ValueError("aggregation.utility_spread_scale must be positive")
		missing = TACTICAL_RULE_IDS - set(self.tactical_rule_weights)
		unknown = set(self.tactical_rule_weights) - TACTICAL_RULE_IDS
		if missing or unknown:
			raise ValueError(f"tactical rule IDs invalid; missing={sorted(missing)}, unknown={sorted(unknown)}")
		for rule_id, value in self.tactical_rule_weights.items():
			if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
				raise ValueError(f"aggregation.tactical_rule_weights.{rule_id} must be finite")


@dataclass(frozen=True)
class CandidateResponseCase:
	response: OpponentJointResponse
	projection: ProjectionResult
	utility: ResponseUtilityEvaluation


@dataclass(frozen=True)
class CandidateEvaluationInput:
	candidate: CanonicalLegalAction
	cases: tuple[CandidateResponseCase, ...]


@dataclass(frozen=True)
class CandidateAggregateEvaluation:
	candidate: CanonicalLegalAction
	expected_utility: float
	credible_bad_case_utility: float
	best_case_utility: float
	variance: float
	standard_deviation: float
	robust_across_responses: float
	fragile_prediction: float
	base_score: float
	feature_contributions: tuple[FeatureContribution, ...]
	tactical_adjustments: tuple[TacticalRuleAdjustment, ...]
	final_score: float
	credible_response_ids: tuple[str, ...]
	response_evaluations: tuple[ResponseEvaluationTrace, ...]

	def to_trace(self) -> CandidateActionTrace:
		return CandidateActionTrace(
			self.candidate,
			self.expected_utility,
			self.credible_bad_case_utility,
			self.best_case_utility,
			self.final_score,
			self.response_evaluations,
			self.feature_contributions,
			self.tactical_adjustments,
		)


@dataclass(frozen=True)
class CandidateRanking:
	config_version: str
	candidates: tuple[CandidateAggregateEvaluation, ...]
	selected_action_id: str

	def candidate_traces(self) -> tuple[CandidateActionTrace, ...]:
		return tuple(candidate.to_trace() for candidate in self.candidates)


def default_aggregation_config() -> AggregationConfig:
	config = AggregationConfig(
		version="b9-robust-aggregation-v1",
		expected_utility_weight=0.65,
		credible_bad_case_weight=0.35,
		utility_spread_scale=150.0,
		robust_across_responses_weight=18.0,
		fragile_prediction_weight=-25.0,
		tactical_rule_weights={
			"FOLLOW_ME_RESCUE": 55.0,
			"OBVIOUS_LETHAL_GLACEON": 25.0,
			"CASH_OUT": 25.0,
			"FAILED_WEATHER_DEPENDENT_MOVE": -60.0,
			"ABILITY_PUNISHMENT": -65.0,
			"ZERO_EFFECT": -35.0,
			"BASE_AGGRON_DANGER": -55.0,
		},
	)
	config.validate()
	return config


def rank_candidates(
	knowledge: KnowledgeState,
	strategy: RuntimeStrategyAssessment,
	response_set: OpponentResponseSet,
	candidates: tuple[CandidateEvaluationInput, ...],
	*,
	policy_config: PolicyConfig | None = None,
	config: AggregationConfig | None = None,
) -> CandidateRanking:
	"""Aggregate and deterministically rank already-evaluated legal candidates."""
	policy_config = policy_config or default_config()
	config = config or default_aggregation_config()
	policy_config.validate()
	config.validate()
	_validate_ranking_contract(knowledge, response_set, candidates)

	evaluated = tuple(
		_aggregate_candidate(
			knowledge, strategy, response_set, candidate_input,
			policy_config=policy_config, config=config,
		)
		for candidate_input in candidates
	)
	ordered = tuple(sorted(
		evaluated,
		key=lambda item: (
			-item.final_score,
			-item.credible_bad_case_utility,
			-item.expected_utility,
			item.candidate.action_id,
		),
	))
	return CandidateRanking(config.version, ordered, ordered[0].candidate.action_id)


def _validate_ranking_contract(
	knowledge: KnowledgeState,
	response_set: OpponentResponseSet,
	candidates: tuple[CandidateEvaluationInput, ...],
) -> None:
	if knowledge.phase != "turn":
		raise AggregationContractError("B9 only supports turn phase")
	if not response_set.responses:
		raise AggregationContractError("B9 requires at least one B6 opponent response")
	if not candidates:
		raise AggregationContractError("B9 requires at least one candidate")
	response_keys = tuple(response.canonical_key for response in response_set.responses)
	if len(set(response_keys)) != len(response_keys):
		raise AggregationContractError("B6 response keys must be unique")
	if any(not _finite(response.weight) or response.weight < 0 for response in response_set.responses):
		raise AggregationContractError("B6 response weights must be finite and non-negative")
	if sum(response.weight for response in response_set.responses) <= 0:
		raise AggregationContractError("B6 response weights must sum to a positive value")

	legal_ids = {action.action_id for action in knowledge.legal_actions}
	candidate_ids = [item.candidate.action_id for item in candidates]
	if len(set(candidate_ids)) != len(candidate_ids):
		raise AggregationContractError("B9 candidate action IDs must be unique")
	if legal_ids and any(action_id not in legal_ids for action_id in candidate_ids):
		raise AggregationContractError("B9 candidates must come from request.legal_actions")

	for item in candidates:
		if item.candidate.payload.get("kind") != "turn":
			raise AggregationContractError("B9 requires canonical turn actions")
		case_keys = tuple(case.response.canonical_key for case in item.cases)
		if set(case_keys) != set(response_keys) or len(case_keys) != len(response_keys):
			raise AggregationContractError("every B9 candidate must cover exactly the B6 response set")
		if len(set(case_keys)) != len(case_keys):
			raise AggregationContractError("candidate response cases must be unique")
		for case in item.cases:
			if case.projection.candidate_action_id != item.candidate.action_id:
				raise AggregationContractError("B7 projection candidate does not match B9 candidate")
			if case.projection.response_key != case.response.canonical_key:
				raise AggregationContractError("B7 projection response does not match B6 case")
			if case.utility.candidate_action_id != item.candidate.action_id:
				raise AggregationContractError("B8 utility candidate does not match B9 candidate")
			if case.utility.response_id != case.response.canonical_key:
				raise AggregationContractError("B8 utility response does not match B6 case")


def _aggregate_candidate(
	knowledge: KnowledgeState,
	strategy: RuntimeStrategyAssessment,
	response_set: OpponentResponseSet,
	candidate_input: CandidateEvaluationInput,
	*,
	policy_config: PolicyConfig,
	config: AggregationConfig,
) -> CandidateAggregateEvaluation:
	candidate = candidate_input.candidate
	case_by_key = {case.response.canonical_key: case for case in candidate_input.cases}
	cases = tuple(case_by_key[response.canonical_key] for response in response_set.responses)
	weights = _normalized_response_weights(response_set.responses)
	utilities = tuple(case.utility.utility for case in cases)
	if any(not _finite(value) for value in utilities):
		raise AggregationContractError("B8 response utilities must be finite")

	expected = sum(weight * utility for weight, utility in zip(weights, utilities))
	credible = _credible_indices(weights, policy_config.thresholds.credible_response_relative_weight)
	bad_index = min(credible, key=lambda index: (utilities[index], cases[index].response.canonical_key))
	bad_case = utilities[bad_index]
	best_case = max(utilities)
	variance = max(0.0, sum(
		weight * (utility - expected) ** 2
		for weight, utility in zip(weights, utilities)
	))
	stddev = math.sqrt(variance)
	fragility = _clamp01(stddev / config.utility_spread_scale)
	credible_values = [utilities[index] for index in credible]
	robustness = _clamp01(1.0 - (max(credible_values) - min(credible_values)) / config.utility_spread_scale)

	feature_contributions = _aggregate_feature_contributions(
		cases, weights, bad_index, robustness, fragility, config,
	)
	base_score = sum(item.contribution for item in feature_contributions)
	expected_formula = (
		config.expected_utility_weight * expected +
		config.credible_bad_case_weight * bad_case +
		config.robust_across_responses_weight * robustness +
		config.fragile_prediction_weight * fragility
	)
	if not math.isclose(base_score, expected_formula, rel_tol=1e-9, abs_tol=1e-7):
		raise AggregationContractError("B9 feature contributions do not reproduce the aggregate score")

	adjustments = _tactical_adjustments(
		knowledge, strategy, candidate, cases, weights, credible, config,
	)
	final_score = base_score + sum(item.adjustment for item in adjustments)
	if not _finite(final_score):
		raise AggregationContractError("B9 final candidate score must be finite")

	return CandidateAggregateEvaluation(
		candidate=candidate,
		expected_utility=expected,
		credible_bad_case_utility=bad_case,
		best_case_utility=best_case,
		variance=variance,
		standard_deviation=stddev,
		robust_across_responses=robustness,
		fragile_prediction=fragility,
		base_score=base_score,
		feature_contributions=feature_contributions,
		tactical_adjustments=adjustments,
		final_score=final_score,
		credible_response_ids=tuple(cases[index].response.canonical_key for index in credible),
		response_evaluations=tuple(
			ResponseEvaluationTrace(
				case.response.canonical_key,
				case.utility.utility,
				case.utility.confidence,
				case.utility.feature_contributions,
			)
			for case in cases
		),
	)


def _normalized_response_weights(responses: tuple[OpponentJointResponse, ...]) -> tuple[float, ...]:
	total = sum(response.weight for response in responses)
	if total <= 0:
		raise AggregationContractError("B6 response weights must sum to a positive value")
	return tuple(response.weight / total for response in responses)


def _credible_indices(weights: tuple[float, ...], relative_threshold: float) -> tuple[int, ...]:
	if not weights:
		raise AggregationContractError("cannot choose credible responses from an empty distribution")
	threshold = max(weights) * relative_threshold
	indices = tuple(index for index, weight in enumerate(weights) if weight >= threshold - 1e-12)
	return indices or (max(range(len(weights)), key=lambda index: weights[index]),)


def _aggregate_feature_contributions(
	cases: tuple[CandidateResponseCase, ...],
	weights: tuple[float, ...],
	bad_index: int,
	robustness: float,
	fragility: float,
	config: AggregationConfig,
) -> tuple[FeatureContribution, ...]:
	by_case = [
		{item.feature_id: item for item in case.utility.feature_contributions}
		for case in cases
	]
	feature_order = tuple(item.feature_id for item in cases[0].utility.feature_contributions)
	if any(set(items) != set(feature_order) for items in by_case):
		raise AggregationContractError("B8 feature contribution IDs differ across responses")

	result: list[FeatureContribution] = []
	for feature_id in feature_order:
		if feature_id in _CROSS_RESPONSE_FEATURE_IDS:
			continue
		entries = [items[feature_id] for items in by_case]
		weight_values = {round(float(item.weight), 12) for item in entries}
		if len(weight_values) != 1:
			raise AggregationContractError("B8 scoring weights must be identical across B9 response cases")
		feature_weight = float(entries[0].weight)
		expected_value = sum(response_weight * item.value for response_weight, item in zip(weights, entries))
		bad_value = entries[bad_index].value
		blended_value = (
			config.expected_utility_weight * expected_value +
			config.credible_bad_case_weight * bad_value
		)
		blended_contribution = (
			config.expected_utility_weight * sum(
				response_weight * item.contribution
				for response_weight, item in zip(weights, entries)
			) +
			config.credible_bad_case_weight * entries[bad_index].contribution
		)
		result.append(FeatureContribution(feature_id, blended_value, feature_weight, blended_contribution))

	result.append(FeatureContribution(
		"FRAGILE_PREDICTION", fragility, config.fragile_prediction_weight,
		fragility * config.fragile_prediction_weight,
	))
	result.append(FeatureContribution(
		"ROBUST_ACROSS_RESPONSES", robustness, config.robust_across_responses_weight,
		robustness * config.robust_across_responses_weight,
	))
	return tuple(result)


def _tactical_adjustments(
	knowledge: KnowledgeState,
	strategy: RuntimeStrategyAssessment,
	candidate: CanonicalLegalAction,
	cases: tuple[CandidateResponseCase, ...],
	weights: tuple[float, ...],
	credible: tuple[int, ...],
	config: AggregationConfig,
) -> tuple[TacticalRuleAdjustment, ...]:
	result: list[TacticalRuleAdjustment] = []
	credible_weights = _renormalized_subset_weights(weights, credible)
	primary_id = _primary_resource_id(strategy)

	if primary_id and _candidate_uses_move(candidate, "followme"):
		probability = _credible_branch_probability(
			cases, credible, credible_weights,
			lambda outcome: _redirects_attack_away_from_primary(outcome, primary_id),
		)
		_add_adjustment(
			result, "FOLLOW_ME_RESCUE", probability, config,
			"Follow Me redirects credible pressure away from the surviving primary win condition",
		)

	glaceon_id = _own_id_for_species(strategy, "glaceon")
	if glaceon_id and _pokemon_uses_damaging_move(candidate, knowledge, glaceon_id):
		probability = _credible_case_probability(
			cases, credible, credible_weights,
			lambda case: (
				case.utility.features_by_id().get("OPPONENT_KO", 0.0) >= 0.55 and
				case.utility.features_by_id().get("PRIMARY_WINCON_SURVIVAL", 0.0) >= 0.45
			),
		)
		_add_adjustment(
			result, "OBVIOUS_LETHAL_GLACEON", probability, config,
			"Glaceon converts credible lines into a KO while remaining strategically viable",
		)

	if primary_id and _current_setup_stage(knowledge, strategy, primary_id) > 0 and _pokemon_uses_damaging_move(
		candidate, knowledge, primary_id,
	):
		probability = _credible_case_probability(
			cases, credible, credible_weights,
			lambda case: (
				case.utility.features_by_id().get("FREE_TURN_CONVERSION", 0.0) >= 0.35 and
				case.utility.features_by_id().get("PRIMARY_WINCON_SURVIVAL", 0.0) >= 0.40
			),
		)
		_add_adjustment(
			result, "CASH_OUT", probability, config,
			"An already-developed primary win condition converts the turn into concrete progress",
		)

	if _candidate_uses_move(candidate, "auroraveil") and not _own_side_condition_active(knowledge, "auroraveil"):
		probability = _credible_branch_probability(
			cases, credible, credible_weights,
			lambda outcome: (
				"auroraveil" not in {to_id(value) for value in outcome.projected_own_side_conditions} and
				not _weather_allows_aurora_veil(outcome.projected_weather)
			),
		)
		_add_adjustment(
			result, "FAILED_WEATHER_DEPENDENT_MOVE", probability, config,
			"Aurora Veil fails specifically because credible projected weather is incompatible",
		)

	if _candidate_uses_move(candidate, "mudslap"):
		probability = _credible_branch_probability(
			cases, credible, credible_weights,
			lambda outcome: _mud_slap_punishes_into_known_ability(knowledge, outcome),
		)
		_add_adjustment(
			result, "ABILITY_PUNISHMENT", probability, config,
			"Mud-Slap feeds a publicly known stat-drop-punishing ability in a credible branch",
		)

	if _candidate_has_damaging_move(candidate):
		probability = _credible_branch_probability(
			cases, credible, credible_weights,
			_zero_effect_unblocked_damage,
		)
		_add_adjustment(
			result, "ZERO_EFFECT", probability, config,
			"An unblocked damaging action resolves for essentially zero value in a credible branch",
		)

	aggron_id = _own_id_for_species(strategy, "aggron")
	if (
		strategy.scores.primary_plan == PlanLabel.AGGRON_FORTRESS.value and
		aggron_id and _is_currently_active(knowledge, aggron_id) and
		_current_transformation(knowledge, aggron_id) is None and
		_mega_available_for(knowledge, aggron_id) and
		not _candidate_transforms_pokemon(candidate, knowledge, aggron_id)
	):
		probability = _credible_branch_probability(
			cases, credible, credible_weights,
			lambda outcome: aggron_id in outcome.own_faints or aggron_id in outcome.possible_own_faints,
		)
		_add_adjustment(
			result, "BASE_AGGRON_DANGER", probability, config,
			"Base Aggron remains exposed to a credible KO line despite a legal Mega option",
		)

	return tuple(result)


def _redirects_attack_away_from_primary(outcome: ProjectedOutcome, primary_id: str) -> bool:
	if primary_id in outcome.own_faints or primary_id in outcome.possible_own_faints:
		return False
	return any(
		record.side == "opponent" and
		record.redirected and
		record.original_target_id == primary_id and
		record.final_target_id is not None and
		record.final_target_id != primary_id
		for record in outcome.action_records
	)


def _weather_allows_aurora_veil(weather: str | None) -> bool:
	return to_id(weather or "") in {"snow", "snowscape", "hail"}


def _zero_effect_unblocked_damage(outcome: ProjectedOutcome) -> bool:
	if ProjectionUncertainty.UNKNOWN_DYNAMIC_EFFECT in outcome.uncertain_interactions:
		return False
	damaging_records = [
		record for record in outcome.action_records
		if record.side == "own" and to_id(record.action) in _TEAM_DAMAGING_MOVES
	]
	if not damaging_records or all(record.blocked_by is not None for record in damaging_records):
		return False
	return not any(change.high_fraction > 0.01 for change in outcome.opponent_hp_changes)


def _add_adjustment(
	result: list[TacticalRuleAdjustment],
	rule_id: str,
	probability: float,
	config: AggregationConfig,
	reason: str,
) -> None:
	if probability <= 1e-9:
		return
	adjustment = float(config.tactical_rule_weights[rule_id]) * _clamp01(probability)
	if abs(adjustment) > 1e-9:
		result.append(TacticalRuleAdjustment(rule_id, adjustment, reason))


def _renormalized_subset_weights(weights: tuple[float, ...], indices: tuple[int, ...]) -> tuple[float, ...]:
	total = sum(weights[index] for index in indices)
	if total <= 0:
		return tuple(1.0 / len(indices) for _ in indices)
	return tuple(weights[index] / total for index in indices)


def _credible_case_probability(cases, indices, subset_weights, predicate) -> float:
	return sum(
		weight for index, weight in zip(indices, subset_weights)
		if predicate(cases[index])
	)


def _credible_branch_probability(cases, indices, subset_weights, predicate) -> float:
	result = 0.0
	for index, response_weight in zip(indices, subset_weights):
		outcomes = cases[index].projection.outcomes
		total = sum(outcome.branch_weight for outcome in outcomes)
		if total <= 0:
			continue
		branch_probability = sum(
			outcome.branch_weight / total
			for outcome in outcomes
			if predicate(outcome)
		)
		result += response_weight * branch_probability
	return _clamp01(result)


def _candidate_uses_move(candidate: CanonicalLegalAction, move_id: str) -> bool:
	needle = to_id(move_id)
	return any(
		action and action.get("type") == "move" and to_id(action.get("move", "")) == needle
		for action in candidate.payload.get("actions", {}).values()
	)


def _candidate_has_damaging_move(candidate: CanonicalLegalAction) -> bool:
	return any(
		action and action.get("type") == "move" and to_id(action.get("move", "")) in _TEAM_DAMAGING_MOVES
		for action in candidate.payload.get("actions", {}).values()
	)


def _pokemon_uses_damaging_move(candidate: CanonicalLegalAction, knowledge: KnowledgeState, pokemon_id: str) -> bool:
	position = next((position for position, active_id in knowledge.own_active if active_id == pokemon_id), None)
	if position is None:
		return False
	action = candidate.payload.get("actions", {}).get(position)
	return bool(
		action and action.get("type") == "move" and to_id(action.get("move", "")) in _TEAM_DAMAGING_MOVES
	)


def _primary_resource_id(strategy: RuntimeStrategyAssessment) -> str | None:
	if strategy.scores.primary_plan == PlanLabel.GLACEON_FORTRESS.value:
		return _own_id_for_species(strategy, "glaceon")
	if strategy.scores.primary_plan == PlanLabel.AGGRON_FORTRESS.value:
		return _own_id_for_species(strategy, "aggron")
	return None


def _own_id_for_species(strategy: RuntimeStrategyAssessment, species_id: str) -> str | None:
	needle = to_id(species_id)
	return next((resource.pokemon_id for resource in strategy.resources if to_id(resource.species) == needle), None)


def _current_setup_stage(knowledge: KnowledgeState, strategy: RuntimeStrategyAssessment, pokemon_id: str) -> int:
	pokemon = next((item for item in knowledge.own_team if item.id == pokemon_id), None)
	if pokemon is None:
		return 0
	boosts = dict(pokemon.boosts)
	if strategy.scores.primary_plan == PlanLabel.GLACEON_FORTRESS.value:
		return max(0, min(boosts.get("spa", 0), boosts.get("spd", 0)))
	if strategy.scores.primary_plan == PlanLabel.AGGRON_FORTRESS.value:
		return max(0, boosts.get("def", 0))
	return 0


def _own_side_condition_active(knowledge: KnowledgeState, condition_id: str) -> bool:
	needle = to_id(condition_id)
	return any(to_id(condition.id) == needle and condition.active for condition in knowledge.field.own_side_conditions)


def _mud_slap_punishes_into_known_ability(knowledge: KnowledgeState, outcome: ProjectedOutcome) -> bool:
	if ProjectionUncertainty.OPPONENT_TRANSFORMATION in outcome.uncertain_interactions:
		return False
	ability_by_id = {item.id: to_id(item.ability or "") for item in knowledge.opponent_roster}
	for active in knowledge.opponent_active:
		identity = active.established_identity.value
		if isinstance(identity, str) and active.ability.value is not None:
			ability_by_id[identity] = to_id(str(active.ability.value))
	for record in outcome.action_records:
		if record.side != "own" or to_id(record.action) != "mudslap" or not record.final_target_id:
			continue
		if record.final_target_id in outcome.opponent_faints:
			continue
		if ability_by_id.get(record.final_target_id) in _ABILITY_PUNISHMENT_IDS:
			return True
	return False


def _is_currently_active(knowledge: KnowledgeState, pokemon_id: str) -> bool:
	return any(active_id == pokemon_id for _, active_id in knowledge.own_active)


def _current_transformation(knowledge: KnowledgeState, pokemon_id: str):
	pokemon = next((item for item in knowledge.own_team if item.id == pokemon_id), None)
	return None if pokemon is None else pokemon.transformation.value


def _mega_available_for(knowledge: KnowledgeState, pokemon_id: str) -> bool:
	return any(_candidate_transforms_pokemon(legal, knowledge, pokemon_id) for legal in knowledge.legal_actions)


def _candidate_transforms_pokemon(
	candidate: CanonicalLegalAction,
	knowledge: KnowledgeState,
	pokemon_id: str,
) -> bool:
	position = next((position for position, active_id in knowledge.own_active if active_id == pokemon_id), None)
	if position is None:
		return False
	action = candidate.payload.get("actions", {}).get(position)
	return bool(action and to_id(str(action.get("transformation") or "")) == "mega")


def _clamp01(value: float) -> float:
	return max(0.0, min(1.0, float(value)))


def _finite(value: object) -> bool:
	return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))
