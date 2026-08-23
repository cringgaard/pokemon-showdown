"""B6 OTS-only opponent response generation for the deterministic snow policy.

This layer builds a small, diverse set of plausible opponent joint actions from
public current state, complete Open Team Sheets, B3 history, B4 threats, and the
current runtime strategy. It deliberately does not inspect one of our candidate
actions and does not resolve projected turn outcomes; B7 owns projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import product
import math
from typing import Iterable, Mapping

from .config import PolicyConfig, default_config
from .knowledge import KnowledgeSource, OpponentActiveKnowledge, OpponentRosterKnowledge, SelectedFourStatus
from .mechanics import MechanicsSnapshot, MoveMechanics, UnresolvedMechanicError, to_id
from .reconstruction import KnowledgeState
from .strategy import PlanLabel, RuntimeStrategyAssessment, assess_runtime_strategy
from .threats import BaselineMoveThreat, KOConfidence, TargetThreat, ThreatCategory, ThreatModel, build_threat_model


class ResponseContractError(ValueError):
	"""Raised when B6 is asked to reason outside its OTS turn-response contract."""


class OpponentActionKind(str, Enum):
	MOVE = "MOVE"
	SWITCH = "SWITCH"


class OpponentActionRole(str, Enum):
	DAMAGE = "DAMAGE"
	PROTECT = "PROTECT"
	SETUP = "SETUP"
	CONTROL = "CONTROL"
	SWITCH = "SWITCH"
	SPREAD = "SPREAD"


class ResponseArchetype(str, Enum):
	MAX_DAMAGE = "MAX_DAMAGE"
	FOCUS_PRIMARY_WINCON = "FOCUS_PRIMARY_WINCON"
	PROTECT_AND_PROGRESS = "PROTECT_AND_PROGRESS"
	DISRUPT_AND_SETUP = "DISRUPT_AND_SETUP"
	PIVOT_AND_ACT = "PIVOT_AND_ACT"
	SPREAD_PRESSURE = "SPREAD_PRESSURE"
	BALANCED = "BALANCED"


RESPONSE_WEIGHT_IDS = frozenset({
	"ACTION_BASE",
	"DAMAGE_FRACTION_FACTOR",
	"DYNAMIC_DAMAGE_VALUE",
	"KO_POSSIBLE",
	"KO_VERY_LIKELY",
	"KO_CERTAIN",
	"SUPER_EFFECTIVE",
	"PRIMARY_TARGET",
	"RESOURCE_TARGET_FACTOR",
	"SETUP_VALUE",
	"CONTROL_VALUE",
	"SPEED_CONTROL_VALUE",
	"WEATHER_CONTROL_VALUE",
	"PROTECT_BASE",
	"PROTECT_WHEN_THREATENED",
	"PROTECT_REPEAT_PENALTY",
	"IMMUNITY_PENALTY",
	"SWITCH_BASE",
	"SWITCH_LOW_HP_FACTOR",
	"SWITCH_GHOST_BODY_PRESS",
	"SWITCH_LIGHTNING_ROD",
	"SWITCH_WEATHER_RESET",
	"SWITCH_FLASH_FIRE",
	"SWITCH_RESISTANCE",
	"SWITCH_OFFENSIVE_POSITION",
	"JOINT_MAX_DAMAGE",
	"JOINT_FOCUS_PRIMARY",
	"JOINT_PROTECT_PROGRESS",
	"JOINT_DISRUPT_SETUP",
	"JOINT_PIVOT_ACT",
	"JOINT_SPREAD",
})

_PIVOT_REASON_ORDER = (
	"Body Press immunity pivot",
	"Lightning Rod pivot",
	"weather reset pivot",
	"Flash Fire pivot",
)


@dataclass(frozen=True)
class ResponseGenerationConfig:
	version: str
	weights: Mapping[str, float]
	threatened_hp_fraction: float = 0.50

	def validate(self) -> None:
		if not isinstance(self.version, str) or not self.version.strip():
			raise ValueError("response generation version must be non-empty")
		missing = RESPONSE_WEIGHT_IDS - set(self.weights)
		unknown = set(self.weights) - RESPONSE_WEIGHT_IDS
		if missing or unknown:
			raise ValueError(f"response weight IDs invalid; missing={sorted(missing)}, unknown={sorted(unknown)}")
		for key, value in self.weights.items():
			if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
				raise ValueError(f"response.weights.{key} must be a finite number")
		if not isinstance(self.threatened_hp_fraction, (int, float)) or isinstance(self.threatened_hp_fraction, bool):
			raise ValueError("threatened_hp_fraction must be numeric")
		if not math.isfinite(float(self.threatened_hp_fraction)) or not 0 <= self.threatened_hp_fraction <= 1:
			raise ValueError("threatened_hp_fraction must be between zero and one")


def default_response_generation_config() -> ResponseGenerationConfig:
	config = ResponseGenerationConfig(
		version="b6-ots-responses-v1",
		weights={
			"ACTION_BASE": 10.0,
			"DAMAGE_FRACTION_FACTOR": 55.0,
			"DYNAMIC_DAMAGE_VALUE": 18.0,
			"KO_POSSIBLE": 8.0,
			"KO_VERY_LIKELY": 18.0,
			"KO_CERTAIN": 28.0,
			"SUPER_EFFECTIVE": 10.0,
			"PRIMARY_TARGET": 18.0,
			"RESOURCE_TARGET_FACTOR": 18.0,
			"SETUP_VALUE": 13.0,
			"CONTROL_VALUE": 11.0,
			"SPEED_CONTROL_VALUE": 9.0,
			"WEATHER_CONTROL_VALUE": 9.0,
			"PROTECT_BASE": 7.0,
			"PROTECT_WHEN_THREATENED": 18.0,
			"PROTECT_REPEAT_PENALTY": 12.0,
			"IMMUNITY_PENALTY": 40.0,
			"SWITCH_BASE": 6.0,
			"SWITCH_LOW_HP_FACTOR": 18.0,
			"SWITCH_GHOST_BODY_PRESS": 26.0,
			"SWITCH_LIGHTNING_ROD": 24.0,
			"SWITCH_WEATHER_RESET": 22.0,
			"SWITCH_FLASH_FIRE": 22.0,
			"SWITCH_RESISTANCE": 12.0,
			"SWITCH_OFFENSIVE_POSITION": 10.0,
			"JOINT_MAX_DAMAGE": 8.0,
			"JOINT_FOCUS_PRIMARY": 14.0,
			"JOINT_PROTECT_PROGRESS": 10.0,
			"JOINT_DISRUPT_SETUP": 10.0,
			"JOINT_PIVOT_ACT": 10.0,
			"JOINT_SPREAD": 9.0,
		},
	)
	config.validate()
	return config


@dataclass(frozen=True)
class OpponentIndividualAction:
	actor_position: str
	actor_id: str
	kind: OpponentActionKind
	move: str | None
	switch_to: str | None
	target_position: str | None
	target_id: str | None
	roles: tuple[OpponentActionRole, ...]
	plausibility: float
	reasons: tuple[str, ...]

	@property
	def canonical_key(self) -> str:
		return "|".join((
			self.actor_position,
			self.actor_id,
			self.kind.value,
			self.move or "",
			self.switch_to or "",
			self.target_position or "",
			self.target_id or "",
		))


@dataclass(frozen=True)
class OpponentJointResponse:
	archetypes: tuple[ResponseArchetype, ...]
	actions: tuple[OpponentIndividualAction, ...]
	raw_score: float
	weight: float
	reasons: tuple[str, ...]

	@property
	def canonical_key(self) -> str:
		return ";".join(action.canonical_key for action in self.actions)


@dataclass(frozen=True)
class OpponentResponseSet:
	config_version: str
	individual_actions: tuple[tuple[str, tuple[OpponentIndividualAction, ...]], ...]
	responses: tuple[OpponentJointResponse, ...]

	def actions_for(self, position: str) -> tuple[OpponentIndividualAction, ...]:
		for item_position, actions in self.individual_actions:
			if item_position == position:
				return actions
		return ()


def generate_opponent_responses(
	knowledge: KnowledgeState,
	mechanics: MechanicsSnapshot,
	*,
	strategy: RuntimeStrategyAssessment | None = None,
	threats: ThreatModel | None = None,
	policy_config: PolicyConfig | None = None,
	config: ResponseGenerationConfig | None = None,
) -> OpponentResponseSet:
	"""Generate plausible opponent responses without seeing our candidate action."""
	policy_config = policy_config or default_config()
	policy_config.validate()
	config = config or default_response_generation_config()
	config.validate()
	_require_ots_turn(knowledge)
	if hasattr(mechanics, "require_champions_format"):
		mechanics.require_champions_format()
	threats = threats or build_threat_model(knowledge, mechanics)
	strategy = strategy or assess_runtime_strategy(knowledge, mechanics, threats=threats, config=policy_config)

	roster_by_id = {pokemon.id: pokemon for pokemon in knowledge.opponent_roster}
	threat_by_move = {(item.attacker_position, item.move): item for item in threats.move_threats}
	fainted_ids = _public_fainted_roster_ids(knowledge)
	individual: list[tuple[str, tuple[OpponentIndividualAction, ...]]] = []
	for active in sorted((item for item in knowledge.opponent_active if not item.fainted), key=lambda item: item.position):
		identity = active.established_identity.value
		if not isinstance(identity, str) or identity not in roster_by_id:
			raise ResponseContractError(f"B6 requires established OTS identity for active slot {active.position}")
		roster = roster_by_id[identity]
		actions = _individual_actions(
			active, roster, knowledge, mechanics, threat_by_move, strategy,
			fainted_ids, policy_config, config,
		)
		if not actions:
			raise ResponseContractError(f"No plausible public actions generated for opponent slot {active.position}")
		individual.append((active.position, actions))
	if not individual:
		raise ResponseContractError("B6 requires at least one live opponent active Pokemon")

	responses = _joint_responses(tuple(individual), knowledge, strategy, policy_config, config)
	if not responses:
		raise ResponseContractError("No plausible opponent joint responses could be generated")
	return OpponentResponseSet(config.version, tuple(individual), responses)


def _require_ots_turn(knowledge: KnowledgeState) -> None:
	if knowledge.phase != "turn":
		raise ResponseContractError(f"B6 response generation only supports turn phase, got {knowledge.phase!r}")
	if len(knowledge.opponent_roster) != 6:
		raise ResponseContractError("B6 OTS response generation requires all six opponent roster entries")
	if not any(event.type == "showteam" for event in knowledge.history.events):
		raise ResponseContractError("B6 OTS response generation requires an explicit public showteam event")
	for pokemon in knowledge.opponent_roster:
		if pokemon.source is not KnowledgeSource.OPEN_TEAM_SHEET:
			raise ResponseContractError(f"Opponent {pokemon.id} is not OTS-backed")
		if pokemon.ability is None:
			raise ResponseContractError(f"Opponent {pokemon.id} has no OTS ability")
		if not pokemon.moves:
			raise ResponseContractError(f"Opponent {pokemon.id} has no OTS moves")
		for move in pokemon.moves:
			if KnowledgeSource.OPEN_TEAM_SHEET not in move.sources:
				raise ResponseContractError(
					f"Opponent {pokemon.id} move {move.id} is not OTS-backed; non-OTS inference is out of scope"
				)


def _individual_actions(
	active: OpponentActiveKnowledge,
	roster: OpponentRosterKnowledge,
	knowledge: KnowledgeState,
	mechanics: MechanicsSnapshot,
	threat_by_move: Mapping[tuple[str, str], BaselineMoveThreat],
	strategy: RuntimeStrategyAssessment,
	fainted_ids: set[str],
	policy_config: PolicyConfig,
	config: ResponseGenerationConfig,
) -> tuple[OpponentIndividualAction, ...]:
	generated: list[OpponentIndividualAction] = []
	for known_move in roster.moves:
		try:
			move = mechanics.move(known_move.id)
		except KeyError:
			continue
		threat = threat_by_move.get((active.position, move.id))
		if not _move_currently_available(active, roster, move.id, threat, knowledge):
			continue
		for target_position, target_id in _move_targets(move, threat, active, knowledge, mechanics):
			generated.append(_score_move_action(
				active, roster, move, threat, target_position, target_id,
				knowledge, mechanics, strategy, policy_config, config,
			))

	generated.extend(_switch_actions(
		active, roster, knowledge, mechanics, fainted_ids, policy_config, config,
	))
	return _retain_diverse_actions(generated, policy_config.opponent_response.max_individual_actions_per_pokemon)


def _move_currently_available(
	active: OpponentActiveKnowledge,
	roster: OpponentRosterKnowledge,
	move_id: str,
	threat: BaselineMoveThreat | None,
	knowledge: KnowledgeState,
) -> bool:
	if to_id(move_id) == "fakeout":
		for item in knowledge.fake_out_eligibility:
			if item.position == active.position and item.pokemon_identity == roster.id:
				return item.eligible is not False
	return threat is None or threat.currently_available is not False


def _move_targets(
	move: MoveMechanics,
	threat: BaselineMoveThreat | None,
	active: OpponentActiveKnowledge,
	knowledge: KnowledgeState,
	mechanics: MechanicsSnapshot,
) -> tuple[tuple[str | None, str | None], ...]:
	tags = set(threat.tags) if threat is not None else set()
	if move.is_spread or _is_self_or_field_move(move, tags, mechanics):
		return ((None, None),)
	target_kind = to_id(move.target)
	if target_kind in ("adjacentally", "adjacentallyorself"):
		results = []
		for other in knowledge.opponent_active:
			if other.fainted:
				continue
			if other.position != active.position or target_kind == "adjacentallyorself":
				identity = other.established_identity.value
				results.append((other.position, identity if isinstance(identity, str) else None))
		return tuple(results) or ((None, None),)
	if target_kind in ("normal", "any", "adjacentfoe"):
		own_by_id = {pokemon.id: pokemon for pokemon in knowledge.own_team}
		return tuple(
			(position, pokemon_id)
			for position, pokemon_id in knowledge.own_active
			if pokemon_id in own_by_id and not own_by_id[pokemon_id].fainted
		) or ((None, None),)
	return ((None, None),)


def _is_self_or_field_move(move: MoveMechanics, tags: set[ThreatCategory], mechanics: MechanicsSnapshot) -> bool:
	if to_id(move.target) in {
		"self", "allyside", "foeside", "all", "field", "scripted", "randomnormal", "allies",
	}:
		return True
	if tags & {
		ThreatCategory.PROTECT, ThreatCategory.REDIRECTION, ThreatCategory.WIDE_GUARD,
		ThreatCategory.WEATHER_CONTROL, ThreatCategory.FIELD_CONTROL,
		ThreatCategory.PHYSICAL_SETUP, ThreatCategory.SPECIAL_SETUP, ThreatCategory.SPEED_SETUP,
	}:
		return True
	return _is_protection_move(move, mechanics)


def _score_move_action(
	active: OpponentActiveKnowledge,
	roster: OpponentRosterKnowledge,
	move: MoveMechanics,
	threat: BaselineMoveThreat | None,
	target_position: str | None,
	target_id: str | None,
	knowledge: KnowledgeState,
	mechanics: MechanicsSnapshot,
	strategy: RuntimeStrategyAssessment,
	policy_config: PolicyConfig,
	config: ResponseGenerationConfig,
) -> OpponentIndividualAction:
	w = config.weights
	score = w["ACTION_BASE"]
	reasons: list[str] = []
	roles: set[OpponentActionRole] = set()
	tags = set(threat.tags) if threat is not None else set()
	target_threat = _target_threat(threat, target_id)
	damaging = _is_damaging_move(move, mechanics)

	if damaging:
		roles.add(OpponentActionRole.DAMAGE)
		if move.is_spread:
			roles.add(OpponentActionRole.SPREAD)
		if target_threat is not None:
			if target_threat.effectiveness == 0:
				score -= w["IMMUNITY_PENALTY"]
				reasons.append("known immunity")
			elif target_threat.estimated_fraction_mid is not None:
				score += w["DAMAGE_FRACTION_FACTOR"] * min(1.5, target_threat.estimated_fraction_mid)
				reasons.append("credible damage")
			else:
				score += w["DYNAMIC_DAMAGE_VALUE"]
				reasons.append("dynamic damage pressure")
			if target_threat.effectiveness is not None and target_threat.effectiveness > 1:
				score += w["SUPER_EFFECTIVE"]
				reasons.append("super-effective pressure")
			score += _ko_bonus(target_threat.ko_confidence, w)
		elif move.is_spread and threat is not None:
			known = [item.estimated_fraction_mid for item in threat.targets if item.estimated_fraction_mid is not None]
			if known:
				score += w["DAMAGE_FRACTION_FACTOR"] * min(1.5, sum(known))
				reasons.append("spread damage pressure")
			else:
				score += w["DYNAMIC_DAMAGE_VALUE"]

	# Strategic target importance applies to any targeted action, not only direct
	# damage. Burning or disabling the primary win condition can be more important
	# than applying the same control effect to a secondary resource.
	if target_id is not None:
		bonus, target_reasons = _target_importance(target_id, knowledge, strategy, w)
		score += bonus
		reasons.extend(target_reasons)

	if tags & {ThreatCategory.PHYSICAL_SETUP, ThreatCategory.SPECIAL_SETUP, ThreatCategory.SPEED_SETUP}:
		roles.add(OpponentActionRole.SETUP)
		score += w["SETUP_VALUE"]
		reasons.append("setup opportunity")
	control_tags = tags & {
		ThreatCategory.FAKE_OUT, ThreatCategory.REDIRECTION, ThreatCategory.ENCORE, ThreatCategory.STATUS,
		ThreatCategory.SPEED_CONTROL, ThreatCategory.WEATHER_CONTROL, ThreatCategory.FIELD_CONTROL,
	}
	if control_tags:
		roles.add(OpponentActionRole.CONTROL)
		score += w["CONTROL_VALUE"]
		reasons.append("control value")
		if ThreatCategory.SPEED_CONTROL in control_tags:
			score += w["SPEED_CONTROL_VALUE"]
			reasons.append("speed control")
		if ThreatCategory.WEATHER_CONTROL in control_tags:
			score += w["WEATHER_CONTROL_VALUE"]
			reasons.append("weather control")
	if ThreatCategory.PROTECT in tags or _is_protection_move(move, mechanics):
		roles.add(OpponentActionRole.PROTECT)
		score += w["PROTECT_BASE"]
		if _opponent_is_threatened(active, roster, knowledge, mechanics, config):
			score += w["PROTECT_WHEN_THREATENED"]
			reasons.append("protects threatened active")
		chain = _protect_chain_count(roster, knowledge)
		if chain:
			score -= w["PROTECT_REPEAT_PENALTY"] * chain
			reasons.append(f"repeated Protect chain {chain}")

	history_multiplier = _history_multiplier(roster, move.id, target_id, knowledge, policy_config)
	if history_multiplier > 1.0:
		score *= history_multiplier
		reasons.append(f"recent pattern x{history_multiplier:.2f}")
	return OpponentIndividualAction(
		active.position, roster.id, OpponentActionKind.MOVE, move.id, None,
		target_position, target_id, tuple(sorted(roles, key=lambda item: item.value)),
		max(0.1, score), tuple(reasons),
	)


def _switch_actions(
	active: OpponentActiveKnowledge,
	roster: OpponentRosterKnowledge,
	knowledge: KnowledgeState,
	mechanics: MechanicsSnapshot,
	fainted_ids: set[str],
	policy_config: PolicyConfig,
	config: ResponseGenerationConfig,
) -> list[OpponentIndividualAction]:
	active_ids = {
		item.established_identity.value
		for item in knowledge.opponent_active
		if isinstance(item.established_identity.value, str) and not item.fainted
	}
	result = []
	for candidate in knowledge.opponent_roster:
		if candidate.id in active_ids or candidate.id in fainted_ids:
			continue
		if candidate.selected_four is SelectedFourStatus.CONFIRMED_NOT_SELECTED:
			continue
		score, reasons = _switch_score(active, candidate, knowledge, mechanics, config)
		selection_multiplier = (
			policy_config.opponent_response.confirmed_selected_multiplier
			if candidate.selected_four is SelectedFourStatus.CONFIRMED_SELECTED else
			policy_config.opponent_response.possible_selected_multiplier
		)
		score *= selection_multiplier
		if candidate.selected_four is SelectedFourStatus.POSSIBLE_SELECTED:
			reasons.append("unrevealed selected-four possibility")
		result.append(OpponentIndividualAction(
			active.position, roster.id, OpponentActionKind.SWITCH, None, candidate.id,
			None, None, (OpponentActionRole.SWITCH,), max(0.1, score), tuple(reasons),
		))
	return result


def _switch_score(
	active: OpponentActiveKnowledge,
	candidate: OpponentRosterKnowledge,
	knowledge: KnowledgeState,
	mechanics: MechanicsSnapshot,
	config: ResponseGenerationConfig,
) -> tuple[float, list[str]]:
	w = config.weights
	score = w["SWITCH_BASE"]
	reasons: list[str] = []
	hp_fraction = max(0.0, min(1.0, active.health.percent / 100.0))
	if hp_fraction < config.threatened_hp_fraction:
		score += w["SWITCH_LOW_HP_FACTOR"] * (1.0 - hp_fraction)
		reasons.append("preserves low-HP active")
	try:
		candidate_types = tuple(mechanics.species(candidate.species).types)
	except KeyError:
		candidate_types = ()
	ability_semantics = _safe_semantic(mechanics, "abilities", candidate.ability or "")
	own_actives = _live_own_actives(knowledge)

	if candidate_types and any(to_id(pokemon.species).startswith("aggron") and _has_move(pokemon, "bodypress") for pokemon in own_actives):
		try:
			if mechanics.move_multiplier("bodypress", candidate_types) == 0:
				score += w["SWITCH_GHOST_BODY_PRESS"]
				reasons.append("Body Press immunity pivot")
		except (KeyError, ValueError, UnresolvedMechanicError):
			pass
	if any(_has_move(pokemon, "thunderbolt") for pokemon in own_actives) and ability_semantics.get("electric_redirection") is True:
		score += w["SWITCH_LIGHTNING_ROD"]
		reasons.append("Lightning Rod pivot")
	entry_weather = ability_semantics.get("entry_weather")
	current_weather = knowledge.field.weather.value
	if entry_weather and (not isinstance(current_weather, str) or to_id(current_weather) != to_id(str(entry_weather))):
		score += w["SWITCH_WEATHER_RESET"]
		reasons.append("weather reset pivot")
	if any(_has_fire_attack(pokemon, mechanics) for pokemon in own_actives) and ability_semantics.get("fire_immunity") is True:
		score += w["SWITCH_FLASH_FIRE"]
		reasons.append("Flash Fire pivot")
	if candidate_types and _resists_current_own_pressure(candidate_types, own_actives, mechanics):
		score += w["SWITCH_RESISTANCE"]
		reasons.append("resists current pressure")
	if _candidate_has_offensive_position(candidate, own_actives, mechanics):
		score += w["SWITCH_OFFENSIVE_POSITION"]
		reasons.append("improves offensive positioning")
	return score, reasons


def _retain_diverse_actions(
	actions: Iterable[OpponentIndividualAction], limit: int
) -> tuple[OpponentIndividualAction, ...]:
	"""Keep tactical categories before filling duplicate target variants."""
	ordered = sorted(actions, key=lambda item: (-item.plausibility, item.canonical_key))
	selected: list[OpponentIndividualAction] = []
	seen_keys: set[str] = set()

	def add(candidate: OpponentIndividualAction | None) -> None:
		if candidate is None or len(selected) >= limit or candidate.canonical_key in seen_keys:
			return
		selected.append(candidate)
		seen_keys.add(candidate.canonical_key)

	for role in (
		OpponentActionRole.DAMAGE,
		OpponentActionRole.PROTECT,
		OpponentActionRole.SETUP,
		OpponentActionRole.CONTROL,
		OpponentActionRole.SPREAD,
		OpponentActionRole.SWITCH,
	):
		add(next((item for item in ordered if role in item.roles and item.canonical_key not in seen_keys), None))

	represented_pivots = {reason for item in selected for reason in item.reasons if reason in _PIVOT_REASON_ORDER}
	for reason in _PIVOT_REASON_ORDER:
		if len(selected) >= limit:
			break
		if reason in represented_pivots:
			continue
		candidate = next((
			item for item in ordered
			if item.kind is OpponentActionKind.SWITCH and reason in item.reasons and item.canonical_key not in seen_keys
		), None)
		add(candidate)
		if candidate is not None:
			represented_pivots.add(reason)

	for candidate in ordered:
		if len(selected) >= limit:
			break
		add(candidate)
	return tuple(sorted(selected, key=lambda item: (-item.plausibility, item.canonical_key)))


def _joint_responses(
	individual_actions: tuple[tuple[str, tuple[OpponentIndividualAction, ...]], ...],
	knowledge: KnowledgeState,
	strategy: RuntimeStrategyAssessment,
	policy_config: PolicyConfig,
	config: ResponseGenerationConfig,
) -> tuple[OpponentJointResponse, ...]:
	pools = [actions for _, actions in individual_actions]
	candidates = []
	for combination in product(*pools):
		actions = tuple(sorted(combination, key=lambda item: item.actor_position))
		if not _valid_joint_switches(actions):
			continue
		archetypes, bonus, reasons = _joint_archetypes(actions, knowledge, strategy, config)
		score = sum(action.plausibility for action in actions) + bonus
		candidates.append((actions, archetypes, score, reasons))
	if not candidates:
		return ()
	candidates.sort(key=lambda item: (-item[2], _joint_key(item[0])))

	selected = []
	seen_keys: set[str] = set()
	for archetype in (
		ResponseArchetype.MAX_DAMAGE,
		ResponseArchetype.FOCUS_PRIMARY_WINCON,
		ResponseArchetype.PROTECT_AND_PROGRESS,
		ResponseArchetype.DISRUPT_AND_SETUP,
		ResponseArchetype.PIVOT_AND_ACT,
		ResponseArchetype.SPREAD_PRESSURE,
	):
		candidate = next((item for item in candidates if archetype in item[1] and _joint_key(item[0]) not in seen_keys), None)
		if candidate is not None:
			selected.append(candidate)
			seen_keys.add(_joint_key(candidate[0]))
		if len(selected) >= policy_config.opponent_response.max_joint_responses:
			break
	for candidate in candidates:
		if len(selected) >= policy_config.opponent_response.max_joint_responses:
			break
		key = _joint_key(candidate[0])
		if key in seen_keys:
			continue
		selected.append(candidate)
		seen_keys.add(key)

	total = sum(max(0.1, item[2]) for item in selected) or 1.0
	return tuple(
		OpponentJointResponse(archetypes, actions, round(score, 6), max(0.1, score) / total, reasons)
		for actions, archetypes, score, reasons in selected
	)


def _joint_key(actions: tuple[OpponentIndividualAction, ...]) -> str:
	return ";".join(action.canonical_key for action in actions)


def _joint_archetypes(
	actions: tuple[OpponentIndividualAction, ...],
	knowledge: KnowledgeState,
	strategy: RuntimeStrategyAssessment,
	config: ResponseGenerationConfig,
) -> tuple[tuple[ResponseArchetype, ...], float, tuple[str, ...]]:
	w = config.weights
	roles = [set(action.roles) for action in actions]
	primary_target = _primary_target_id(knowledge, strategy)
	archetypes: list[ResponseArchetype] = []
	reasons: list[str] = []
	bonus = 0.0
	if actions and all(OpponentActionRole.DAMAGE in item for item in roles):
		archetypes.append(ResponseArchetype.MAX_DAMAGE)
		bonus += w["JOINT_MAX_DAMAGE"]
		reasons.append("maximum direct pressure")
	if primary_target is not None and sum(action.target_id == primary_target for action in actions) >= 2:
		archetypes.append(ResponseArchetype.FOCUS_PRIMARY_WINCON)
		bonus += w["JOINT_FOCUS_PRIMARY"]
		reasons.append("double-targets primary win condition")
	if any(OpponentActionRole.PROTECT in item for item in roles) and any(
		item & {OpponentActionRole.DAMAGE, OpponentActionRole.SETUP, OpponentActionRole.CONTROL}
		for item in roles
	):
		archetypes.append(ResponseArchetype.PROTECT_AND_PROGRESS)
		bonus += w["JOINT_PROTECT_PROGRESS"]
		reasons.append("Protect plus partner progress")
	if any(OpponentActionRole.SETUP in item for item in roles) and any(OpponentActionRole.CONTROL in item for item in roles):
		archetypes.append(ResponseArchetype.DISRUPT_AND_SETUP)
		bonus += w["JOINT_DISRUPT_SETUP"]
		reasons.append("disruption plus setup")
	if any(OpponentActionRole.SWITCH in item for item in roles) and any(OpponentActionRole.SWITCH not in item for item in roles):
		archetypes.append(ResponseArchetype.PIVOT_AND_ACT)
		bonus += w["JOINT_PIVOT_ACT"]
		reasons.append("pivot plus active partner")
	if any(OpponentActionRole.SPREAD in item for item in roles):
		archetypes.append(ResponseArchetype.SPREAD_PRESSURE)
		bonus += w["JOINT_SPREAD"]
		reasons.append("spread pressure")
	if not archetypes:
		archetypes.append(ResponseArchetype.BALANCED)
	return tuple(archetypes), bonus, tuple(reasons)


def _valid_joint_switches(actions: tuple[OpponentIndividualAction, ...]) -> bool:
	switches = [action.switch_to for action in actions if action.kind is OpponentActionKind.SWITCH]
	return len(switches) == len(set(switches))


def _target_threat(threat: BaselineMoveThreat | None, target_id: str | None) -> TargetThreat | None:
	if threat is None or target_id is None:
		return None
	return next((item for item in threat.targets if item.target_id == target_id), None)


def _ko_bonus(confidence: KOConfidence, weights: Mapping[str, float]) -> float:
	if confidence is KOConfidence.CERTAIN:
		return weights["KO_CERTAIN"]
	if confidence is KOConfidence.VERY_LIKELY:
		return weights["KO_VERY_LIKELY"]
	if confidence is KOConfidence.POSSIBLE:
		return weights["KO_POSSIBLE"]
	return 0.0


def _target_importance(
	target_id: str,
	knowledge: KnowledgeState,
	strategy: RuntimeStrategyAssessment,
	weights: Mapping[str, float],
) -> tuple[float, list[str]]:
	score = 0.0
	reasons: list[str] = []
	primary = _primary_target_id(knowledge, strategy)
	if primary == target_id:
		score += weights["PRIMARY_TARGET"]
		reasons.append("targets primary win condition")
	resources = {item.pokemon_id: item.value for item in strategy.resources}
	if resources:
		maximum = max(resources.values()) or 1.0
		value = resources.get(target_id, 0.0)
		if value > 0:
			score += weights["RESOURCE_TARGET_FACTOR"] * value / maximum
			reasons.append("targets strategic resource")
	return score, reasons


def _primary_target_id(knowledge: KnowledgeState, strategy: RuntimeStrategyAssessment) -> str | None:
	primary = strategy.scores.primary_plan
	wanted = (
		"glaceon" if primary == PlanLabel.GLACEON_FORTRESS.value else
		"aggron" if primary == PlanLabel.AGGRON_FORTRESS.value else None
	)
	if wanted is None:
		return None
	own_by_id = {pokemon.id: pokemon for pokemon in knowledge.own_team}
	for _, pokemon_id in knowledge.own_active:
		pokemon = own_by_id.get(pokemon_id)
		if pokemon is not None and to_id(pokemon.species).startswith(wanted) and not pokemon.fainted:
			return pokemon.id
	return None


def _is_damaging_move(move: MoveMechanics, mechanics: MechanicsSnapshot) -> bool:
	if move.base_power > 0:
		return True
	try:
		semantics = mechanics.semantic("moves", move.id)
		if semantics.get("weight_based_power") is True or semantics.get("weight_ratio_power") is True:
			return True
	except (KeyError, ValueError):
		pass
	return any(name in move.callback_names for name in ("basePowerCallback", "damageCallback", "onBasePower"))


def _is_protection_move(move: MoveMechanics, mechanics: MechanicsSnapshot) -> bool:
	try:
		if mechanics.semantic("moves", move.id).get("protection_move") is True:
			return True
	except (KeyError, ValueError):
		pass
	return move.id in ("protect", "detect", "spikyshield", "kingsshield", "banefulbunker")


def _opponent_is_threatened(
	active: OpponentActiveKnowledge,
	roster: OpponentRosterKnowledge,
	knowledge: KnowledgeState,
	mechanics: MechanicsSnapshot,
	config: ResponseGenerationConfig,
) -> bool:
	if active.health.percent / 100.0 <= config.threatened_hp_fraction:
		return True
	defending_types = active.types.value
	if not isinstance(defending_types, list):
		try:
			defending_types = list(mechanics.species(roster.species).types)
		except KeyError:
			return False
	for pokemon in _live_own_actives(knowledge):
		for known_move in pokemon.moves:
			try:
				move = mechanics.move(known_move.id)
				if _is_damaging_move(move, mechanics) and mechanics.move_multiplier(move, defending_types) > 1:
					return True
			except (KeyError, ValueError, UnresolvedMechanicError):
				continue
	return False


def _protect_chain_count(roster: OpponentRosterKnowledge, knowledge: KnowledgeState) -> int:
	for chain in knowledge.history.protect_chains:
		if _history_actor_matches(chain.pokemon_identity, roster):
			return chain.consecutive_count
	return 0


def _history_multiplier(
	roster: OpponentRosterKnowledge,
	move_id: str,
	target_id: str | None,
	knowledge: KnowledgeState,
	config: PolicyConfig,
) -> float:
	observations = [item for item in knowledge.history.move_observations if _history_actor_matches(item.actor, roster)]
	if not observations:
		return 1.0
	last = max(observations, key=lambda item: (item.turn, item.event_index))
	multiplier = 1.0
	if to_id(last.move) == to_id(move_id):
		multiplier *= config.opponent_response.same_move_multiplier
	if target_id is not None and last.target is not None and _history_target_matches(last.target, target_id, knowledge):
		multiplier *= config.opponent_response.same_target_multiplier
	return min(config.opponent_response.repeated_pattern_cap, multiplier)


def _history_actor_matches(actor: str, roster: OpponentRosterKnowledge) -> bool:
	actor_id = to_id(actor.split(":", 1)[-1])
	return actor_id in {to_id(roster.name), to_id(roster.species)}


def _history_target_matches(target: str, target_id: str, knowledge: KnowledgeState) -> bool:
	pokemon = next((item for item in knowledge.own_team if item.id == target_id), None)
	if pokemon is None:
		return False
	target_name = to_id(target.split(":", 1)[-1])
	return target_name in {to_id(pokemon.name), to_id(pokemon.species)}


def _public_fainted_roster_ids(knowledge: KnowledgeState) -> set[str]:
	result = set()
	for event in knowledge.history.events:
		if event.type != "faint":
			continue
		args = event.data.get("args", [])
		if not isinstance(args, list) or not args:
			continue
		ident = str(args[0])
		matches = [pokemon.id for pokemon in knowledge.opponent_roster if _history_actor_matches(ident, pokemon)]
		if len(matches) == 1:
			result.add(matches[0])
	return result


def _live_own_actives(knowledge: KnowledgeState):
	own_by_id = {pokemon.id: pokemon for pokemon in knowledge.own_team}
	return tuple(
		own_by_id[pokemon_id]
		for _, pokemon_id in knowledge.own_active
		if pokemon_id in own_by_id and not own_by_id[pokemon_id].fainted
	)


def _has_move(pokemon, move_id: str) -> bool:
	wanted = to_id(move_id)
	return any(to_id(move.id) == wanted for move in pokemon.moves)


def _has_fire_attack(pokemon, mechanics: MechanicsSnapshot) -> bool:
	for known_move in pokemon.moves:
		try:
			move = mechanics.move(known_move.id)
			if _is_damaging_move(move, mechanics) and to_id(move.type) == "fire":
				return True
		except KeyError:
			continue
	return False


def _resists_current_own_pressure(
	candidate_types: tuple[str, ...], own_actives: Iterable[object], mechanics: MechanicsSnapshot
) -> bool:
	seen_damage = False
	for pokemon in own_actives:
		for known_move in pokemon.moves:
			try:
				move = mechanics.move(known_move.id)
				if not _is_damaging_move(move, mechanics):
					continue
				seen_damage = True
				if mechanics.move_multiplier(move, candidate_types) > 0.5:
					return False
			except (KeyError, ValueError, UnresolvedMechanicError):
				return False
	return seen_damage


def _candidate_has_offensive_position(
	candidate: OpponentRosterKnowledge, own_actives: Iterable[object], mechanics: MechanicsSnapshot
) -> bool:
	for known_move in candidate.moves:
		try:
			move = mechanics.move(known_move.id)
			if not _is_damaging_move(move, mechanics):
				continue
			for pokemon in own_actives:
				if mechanics.move_multiplier(move, pokemon.types) > 1:
					return True
		except (KeyError, ValueError, UnresolvedMechanicError):
			continue
	return False


def _safe_semantic(mechanics: MechanicsSnapshot, category: str, value: str) -> dict[str, object]:
	if not value:
		return {}
	try:
		return mechanics.semantic(category, value)
	except (KeyError, ValueError):
		return {}
