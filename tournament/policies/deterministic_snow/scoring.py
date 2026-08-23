"""B8 semantic outcome features and per-response utility.

B8 is deliberately split into two interfaces:

1. ``extract_outcome_features`` maps one B7 ``ProjectedOutcome`` plus public
   strategic context to a stable, bounded semantic feature vector.
2. ``score_feature_vector`` applies a versioned linear weight set.

This keeps mechanics/feature extraction separate from preferences. A future
learned scorer can consume the exact same raw feature vectors without changing
B3-B7 or introducing hidden-information access. Robust aggregation across
*different* B6 responses is intentionally deferred to B9.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

from .actions import CanonicalLegalAction
from .config import PolicyConfig, default_config
from .features import (
	FEATURE_REGISTRY,
	FEATURE_SCHEMA_VERSION,
	FEATURE_SET_VERSION,
	FEATURES_BY_ID,
)
from .mechanics import to_id
from .projection import (
	ProjectedActionRecord,
	ProjectedOutcome,
	ProjectionConfidence,
	ProjectionResult,
	ProjectionUncertainty,
)
from .reconstruction import KnowledgeState
from .responses import OpponentActionRole, OpponentIndividualAction, OpponentJointResponse
from .strategy import PlanLabel, ResourceValue, RuntimeStrategyAssessment, hp_utility
from .threats import ThreatCategory
from .trace import FeatureContribution


class ScoringContractError(ValueError):
	"""Raised when B8 receives mismatched B6/B7/strategy inputs."""


@dataclass(frozen=True)
class ScoringConfig:
	version: str
	feature_set_version: str
	weights: Mapping[str, float]

	def validate(self) -> None:
		if not isinstance(self.version, str) or not self.version.strip():
			raise ValueError("scoring version must be non-empty")
		if self.feature_set_version != FEATURE_SET_VERSION:
			raise ValueError(
			f"scoring feature_set_version must be {FEATURE_SET_VERSION!r}, got {self.feature_set_version!r}"
		)
		missing = set(FEATURES_BY_ID) - set(self.weights)
		unknown = set(self.weights) - set(FEATURES_BY_ID)
		if missing or unknown:
			raise ValueError(f"scoring weight IDs invalid; missing={sorted(missing)}, unknown={sorted(unknown)}")
		for feature_id, value in self.weights.items():
			if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
				raise ValueError(f"scoring.weights.{feature_id} must be a finite number")


@dataclass(frozen=True)
class FeatureValue:
	feature_id: str
	value: float


@dataclass(frozen=True)
class OutcomeFeatureVector:
	schema_version: int
	feature_set_version: str
	branch_id: str
	branch_weight: float
	values: tuple[FeatureValue, ...]

	def by_id(self) -> dict[str, float]:
		return {item.feature_id: item.value for item in self.values}

	def validate(self) -> None:
		if self.schema_version != FEATURE_SCHEMA_VERSION:
			raise ValueError("feature vector schema version mismatch")
		if self.feature_set_version != FEATURE_SET_VERSION:
			raise ValueError("feature vector set version mismatch")
		if not self.branch_id:
			raise ValueError("feature vector branch_id must be non-empty")
		if not _finite(self.branch_weight) or self.branch_weight < 0:
			raise ValueError("feature vector branch_weight must be finite and non-negative")
		ids = tuple(item.feature_id for item in self.values)
		expected = tuple(feature.id for feature in FEATURE_REGISTRY)
		if ids != expected:
			raise ValueError("feature vector IDs/order do not match FEATURE_REGISTRY")
		for item in self.values:
			definition = FEATURES_BY_ID[item.feature_id]
			if not _finite(item.value):
				raise ValueError(f"feature {item.feature_id} must be finite")
			if item.value < definition.minimum - 1e-9 or item.value > definition.maximum + 1e-9:
				raise ValueError(
				f"feature {item.feature_id}={item.value} outside [{definition.minimum}, {definition.maximum}]"
			)

	def to_dict(self) -> dict[str, object]:
		return {
			"schema_version": self.schema_version,
			"feature_set_version": self.feature_set_version,
			"branch_id": self.branch_id,
			"branch_weight": self.branch_weight,
			"values": {item.feature_id: item.value for item in self.values},
		}


@dataclass(frozen=True)
class BranchUtilityEvaluation:
	branch_id: str
	branch_weight: float
	utility: float
	confidence: str
	feature_vector: OutcomeFeatureVector
	feature_contributions: tuple[FeatureContribution, ...]


@dataclass(frozen=True)
class ResponseUtilityEvaluation:
	feature_schema_version: int
	feature_set_version: str
	scoring_version: str
	candidate_action_id: str
	response_id: str
	utility: float
	confidence: str
	feature_values: tuple[FeatureValue, ...]
	feature_contributions: tuple[FeatureContribution, ...]
	branch_evaluations: tuple[BranchUtilityEvaluation, ...]

	def features_by_id(self) -> dict[str, float]:
		return {item.feature_id: item.value for item in self.feature_values}


# First explicit hand-tuned linear utility. The two cross-response features are
# intentionally zero until B9 has enough information to compute them.
_B8_HAND_WEIGHTS = {
	"OPPONENT_DAMAGE": 40.0,
	"OPPONENT_KO": 90.0,
	"FREE_TURN_CONVERSION": 35.0,
	"OWN_RESOURCE_SURVIVAL": 55.0,
	"DETERMINISTIC_PROTECTION": 70.0,
	"SPREAD_PREVENTION": 35.0,
	"PRIMARY_WINCON_SURVIVAL": 90.0,
	"WIN_CONDITION_PROGRESS": 45.0,
	"WEATHER_CONTROL_GAIN": 30.0,
	"SAFE_SWITCH": 20.0,
	"SACRIFICIAL_PIVOT_VALUE": 35.0,
	"CONTROL_GAIN": 30.0,
	"OPPONENT_SETUP_ALLOWED": -40.0,
	"RNG_DEPENDENCE": -30.0,
	"MECHANIC_UNCERTAINTY": -25.0,
	"FRAGILE_PREDICTION": 0.0,
	"JOINT_ACTION_COORDINATION": 30.0,
	"ROBUST_ACROSS_RESPONSES": 0.0,
}


def default_scoring_config() -> ScoringConfig:
	config = ScoringConfig("b8-hand-linear-v1", FEATURE_SET_VERSION, dict(_B8_HAND_WEIGHTS))
	config.validate()
	return config


def extract_outcome_features(
	knowledge: KnowledgeState,
	strategy: RuntimeStrategyAssessment,
	candidate: CanonicalLegalAction,
	response: OpponentJointResponse,
	outcome: ProjectedOutcome,
	*,
	policy_config: PolicyConfig | None = None,
) -> OutcomeFeatureVector:
	"""Extract one stable semantic feature vector from one B7 branch."""
	policy_config = policy_config or default_config()
	policy_config.validate()
	_require_feature_contract(knowledge, strategy, candidate, response, outcome)

	resource_by_id = {resource.pokemon_id: resource for resource in strategy.resources}
	own_by_id = {pokemon.id: pokemon for pokemon in knowledge.own_team}
	max_resource = max((resource.value for resource in strategy.resources), default=1.0) or 1.0
	primary_id = _primary_resource_id(strategy)

	values = {feature.id: 0.0 for feature in FEATURE_REGISTRY}
	values["OPPONENT_DAMAGE"] = _opponent_damage(outcome)
	values["OPPONENT_KO"] = _opponent_ko(outcome, strategy)
	values["OWN_RESOURCE_SURVIVAL"] = _own_resource_survival(
		knowledge, strategy, outcome, policy_config,
	)
	values["PRIMARY_WINCON_SURVIVAL"] = _primary_survival(
		knowledge, strategy, outcome, primary_id, policy_config,
	)
	values["DETERMINISTIC_PROTECTION"] = _deterministic_protection(
		outcome, response, resource_by_id, max_resource,
	)
	values["SPREAD_PREVENTION"] = _spread_prevention(outcome, response)
	values["WIN_CONDITION_PROGRESS"] = _win_condition_progress(
		knowledge, strategy, candidate, outcome, primary_id,
	)
	values["WEATHER_CONTROL_GAIN"] = _weather_control_gain(knowledge, strategy, outcome)
	values["SAFE_SWITCH"] = _safe_switch(knowledge, candidate, outcome, policy_config)
	values["SACRIFICIAL_PIVOT_VALUE"] = _sacrificial_pivot(
		knowledge, candidate, outcome, resource_by_id, max_resource, primary_id, policy_config,
	)
	values["CONTROL_GAIN"] = _control_gain(outcome)
	values["OPPONENT_SETUP_ALLOWED"] = _opponent_setup_allowed(knowledge, outcome, response)
	values["RNG_DEPENDENCE"] = _rng_dependence(outcome, resource_by_id, max_resource, primary_id)
	values["MECHANIC_UNCERTAINTY"] = _mechanic_uncertainty(outcome)
	values["FREE_TURN_CONVERSION"] = _free_turn_conversion(outcome, values)
	values["JOINT_ACTION_COORDINATION"] = _joint_coordination(candidate, outcome, values)
	# B9-only cross-response features remain exactly zero at this layer.
	values["FRAGILE_PREDICTION"] = 0.0
	values["ROBUST_ACROSS_RESPONSES"] = 0.0

	vector = OutcomeFeatureVector(
		FEATURE_SCHEMA_VERSION,
		FEATURE_SET_VERSION,
		outcome.branch_id,
		outcome.branch_weight,
		tuple(FeatureValue(feature.id, _bounded(values[feature.id], feature.minimum, feature.maximum)) for feature in FEATURE_REGISTRY),
	)
	vector.validate()
	return vector


def score_feature_vector(
	vector: OutcomeFeatureVector,
	*,
	config: ScoringConfig | None = None,
) -> tuple[float, tuple[FeatureContribution, ...]]:
	"""Apply a swappable linear weight set to a raw semantic vector."""
	config = config or default_scoring_config()
	config.validate()
	vector.validate()
	if config.feature_set_version != vector.feature_set_version:
		raise ScoringContractError("scoring config and feature vector versions do not match")
	contributions = tuple(
		FeatureContribution(
			item.feature_id,
			item.value,
			float(config.weights[item.feature_id]),
			item.value * float(config.weights[item.feature_id]),
		)
		for item in vector.values
	)
	utility = sum(item.contribution for item in contributions)
	if not math.isfinite(utility):
		raise ScoringContractError("B8 utility must be finite")
	return utility, contributions


def evaluate_response_utility(
	knowledge: KnowledgeState,
	strategy: RuntimeStrategyAssessment,
	candidate: CanonicalLegalAction,
	response: OpponentJointResponse,
	projection: ProjectionResult,
	*,
	policy_config: PolicyConfig | None = None,
	scoring_config: ScoringConfig | None = None,
) -> ResponseUtilityEvaluation:
	"""Score B7 mechanics branches within one fixed B6 opponent response.

	This is *not* B9 aggregation. The only averaging here is over B7's bounded
	mechanical uncertainty branches for the same opponent response.
	"""
	policy_config = policy_config or default_config()
	scoring_config = scoring_config or default_scoring_config()
	policy_config.validate()
	scoring_config.validate()
	_require_response_contract(knowledge, candidate, response, projection)

	branch_evaluations: list[BranchUtilityEvaluation] = []
	weight_total = sum(outcome.branch_weight for outcome in projection.outcomes)
	if weight_total <= 0:
		raise ScoringContractError("B7 projection branch weights must sum to a positive value")

	for outcome in projection.outcomes:
		vector = extract_outcome_features(
			knowledge, strategy, candidate, response, outcome, policy_config=policy_config,
		)
		utility, contributions = score_feature_vector(vector, config=scoring_config)
		branch_evaluations.append(BranchUtilityEvaluation(
			outcome.branch_id,
			outcome.branch_weight / weight_total,
			utility,
			outcome.confidence.value,
			vector,
			contributions,
		))

	response_values: list[FeatureValue] = []
	for feature in FEATURE_REGISTRY:
		value = sum(
			branch.branch_weight * branch.feature_vector.by_id()[feature.id]
			for branch in branch_evaluations
		)
		response_values.append(FeatureValue(feature.id, _bounded(value, feature.minimum, feature.maximum)))
	response_vector = OutcomeFeatureVector(
		FEATURE_SCHEMA_VERSION,
		FEATURE_SET_VERSION,
		f"response:{response.canonical_key}",
		1.0,
		tuple(response_values),
	)
	response_vector.validate()
	utility, contributions = score_feature_vector(response_vector, config=scoring_config)
	confidence = _worst_confidence(tuple(outcome.confidence for outcome in projection.outcomes)).value
	return ResponseUtilityEvaluation(
		FEATURE_SCHEMA_VERSION,
		FEATURE_SET_VERSION,
		scoring_config.version,
		candidate.action_id,
		response.canonical_key,
		utility,
		confidence,
		response_vector.values,
		contributions,
		tuple(branch_evaluations),
	)


def _require_feature_contract(
	knowledge: KnowledgeState,
	strategy: RuntimeStrategyAssessment,
	candidate: CanonicalLegalAction,
	response: OpponentJointResponse,
	outcome: ProjectedOutcome,
) -> None:
	if knowledge.phase != "turn":
		raise ScoringContractError("B8 only supports turn phase")
	if candidate.payload.get("kind") != "turn":
		raise ScoringContractError("B8 requires a canonical turn action")
	legal_ids = {action.action_id for action in knowledge.legal_actions}
	if legal_ids and candidate.action_id not in legal_ids:
		raise ScoringContractError("B8 candidate must come from request.legal_actions")
	if not response.actions:
		raise ScoringContractError("B8 requires a non-empty B6 opponent response")
	if not strategy.resources:
		raise ScoringContractError("B8 requires B4 strategic resource values")
	if not outcome.branch_id:
		raise ScoringContractError("B8 requires a named B7 outcome branch")


def _require_response_contract(
	knowledge: KnowledgeState,
	candidate: CanonicalLegalAction,
	response: OpponentJointResponse,
	projection: ProjectionResult,
) -> None:
	if projection.candidate_action_id != candidate.action_id:
		raise ScoringContractError("projection candidate_action_id does not match candidate")
	if projection.response_key != response.canonical_key:
		raise ScoringContractError("projection response_key does not match B6 response")
	if not projection.outcomes:
		raise ScoringContractError("B8 requires at least one B7 projection outcome")
	if knowledge.phase != "turn":
		raise ScoringContractError("B8 only supports turn phase")


def _opponent_damage(outcome: ProjectedOutcome) -> float:
	return min(2.0, sum(max(0.0, change.mid_fraction) for change in outcome.opponent_hp_changes))


def _opponent_ko(outcome: ProjectedOutcome, strategy: RuntimeStrategyAssessment) -> float:
	importance = _opponent_importance(strategy)
	value = sum(importance.get(pokemon_id, 0.65) for pokemon_id in outcome.opponent_faints)
	value += 0.40 * sum(importance.get(pokemon_id, 0.65) for pokemon_id in outcome.possible_opponent_faints)
	return min(2.0, value)


def _opponent_importance(strategy: RuntimeStrategyAssessment) -> dict[str, float]:
	by_attacker: dict[str, set[ThreatCategory]] = {}
	for move in strategy.threats.move_threats:
		by_attacker.setdefault(move.attacker_identity, set()).update(move.tags)
	result: dict[str, float] = {}
	for attacker, tags in by_attacker.items():
		value = 0.55
		if ThreatCategory.LIKELY_KO in tags:
			value += 0.15
		if tags & {
			ThreatCategory.FAKE_OUT, ThreatCategory.ENCORE, ThreatCategory.REDIRECTION,
			ThreatCategory.SPEED_CONTROL, ThreatCategory.FIELD_CONTROL,
		}:
			value += 0.10
		if tags & {ThreatCategory.PHYSICAL_SETUP, ThreatCategory.SPECIAL_SETUP, ThreatCategory.SPEED_SETUP}:
			value += 0.10
		if ThreatCategory.WEATHER_CONTROL in tags:
			value += 0.10
		if ThreatCategory.SPREAD_DAMAGE in tags:
			value += 0.05
		result[attacker] = min(1.0, value)
	return result


def _own_resource_survival(
	knowledge: KnowledgeState,
	strategy: RuntimeStrategyAssessment,
	outcome: ProjectedOutcome,
	policy_config: PolicyConfig,
) -> float:
	own_by_id = {pokemon.id: pokemon for pokemon in knowledge.own_team}
	new_major_status = {
		change.pokemon_id
		for change in outcome.status_changes
		if change.side == "own" and change.kind == "status"
	}
	denominator = 0.0
	projected_total = 0.0
	for resource in strategy.resources:
		pokemon = own_by_id.get(resource.pokemon_id)
		if pokemon is None:
			continue
		context_value = max(0.0, resource.base_value * resource.role_multiplier * resource.remaining_utility)
		denominator += context_value
		if pokemon.fainted or resource.pokemon_id in outcome.own_faints:
			continue
		projected_hp = _projected_hp_fraction(pokemon, outcome)
		remaining = 0.80 if resource.pokemon_id in new_major_status and pokemon.status is None else 1.0
		projected_total += context_value * hp_utility(projected_hp, policy_config.strategy.hp_utility_curve) * remaining
	if denominator <= 0:
		return 0.0
	return min(2.0, 2.0 * projected_total / denominator)


def _primary_survival(
	knowledge: KnowledgeState,
	strategy: RuntimeStrategyAssessment,
	outcome: ProjectedOutcome,
	primary_id: str | None,
	policy_config: PolicyConfig,
) -> float:
	if primary_id is None:
		return 0.0
	pokemon = next((item for item in knowledge.own_team if item.id == primary_id), None)
	if pokemon is None or pokemon.fainted or primary_id in outcome.own_faints:
		return 0.0
	value = hp_utility(_projected_hp_fraction(pokemon, outcome), policy_config.strategy.hp_utility_curve)
	if primary_id in outcome.possible_own_faints:
		value *= 0.60
	if any(
		change.side == "own" and change.pokemon_id == primary_id and change.kind == "status"
		for change in outcome.status_changes
	):
		value *= 0.80
	return min(1.0, max(0.0, value))


def _projected_hp_fraction(pokemon, outcome: ProjectedOutcome) -> float:
	current = max(0.0, min(1.0, pokemon.health.percent / 100.0))
	damage = sum(
		max(0.0, change.mid_fraction)
		for change in outcome.own_hp_changes
		if change.pokemon_id == pokemon.id
	)
	return max(0.0, current - damage)


def _deterministic_protection(
	outcome: ProjectedOutcome,
	response: OpponentJointResponse,
	resource_by_id: Mapping[str, ResourceValue],
	max_resource: float,
) -> float:
	value = 0.0
	for record in outcome.action_records:
		if record.side != "opponent":
			continue
		action = _response_action_for(record, response)
		if action is None or not set(action.roles) & {
			OpponentActionRole.DAMAGE, OpponentActionRole.CONTROL, OpponentActionRole.SPREAD,
		}:
			continue
		original = record.original_target_id or action.target_id
		original_value = _resource_importance(original, resource_by_id, max_resource)
		if record.blocked_by in {"protect", "wideguard", "flinch"}:
			value += 0.50 + 0.50 * original_value
		if record.redirected and original and record.final_target_id and original != record.final_target_id:
			final_value = _resource_importance(record.final_target_id, resource_by_id, max_resource)
			gain = max(0.0, original_value - final_value)
			if _target_took_zero_damage(outcome, record.final_target_id):
				gain = max(gain, 0.60 * original_value)
			value += gain
	return min(2.0, value)


def _spread_prevention(outcome: ProjectedOutcome, response: OpponentJointResponse) -> float:
	value = 0.0
	for action in response.actions:
		if OpponentActionRole.SPREAD not in action.roles:
			continue
		records = [
			record for record in outcome.action_records
			if record.side == "opponent" and record.actor_id == action.actor_id and record.action == action.move
		]
		if not records:
			continue
		blocked = sum(record.blocked_by == "wideguard" for record in records)
		value += blocked / len(records)
	return min(2.0, value)


def _win_condition_progress(
	knowledge: KnowledgeState,
	strategy: RuntimeStrategyAssessment,
	candidate: CanonicalLegalAction,
	outcome: ProjectedOutcome,
	primary_id: str | None,
) -> float:
	plan = strategy.scores.primary_plan
	if plan == PlanLabel.TACTICAL_OFFENSE.value:
		return min(1.0, 0.25 * _opponent_damage(outcome) + 0.35 * _opponent_ko(outcome, strategy))
	if primary_id is None:
		# Flexible positions still receive small generic setup/recovery credit, but
		# do not pretend one Pokemon is the established win condition.
		positive = sum(
			max(0, change.stages) for change in outcome.boost_changes if change.side == "own"
		)
		heals = sum(change.side == "own" and change.kind == "heal" for change in outcome.status_changes)
		return min(1.0, 0.08 * positive + 0.15 * heals)

	own = next((pokemon for pokemon in knowledge.own_team if pokemon.id == primary_id), None)
	if own is None:
		return 0.0
	if primary_id in outcome.own_faints:
		return -1.0
	progress = 0.0
	boosts = dict(own.boosts)
	if plan == PlanLabel.GLACEON_FORTRESS.value:
		current = max(0, min(boosts.get("spa", 0), boosts.get("spd", 0)))
		spa_gain = sum(max(0, change.stages) for change in outcome.boost_changes if change.side == "own" and change.pokemon_id == primary_id and change.stat == "spa")
		spd_gain = sum(max(0, change.stages) for change in outcome.boost_changes if change.side == "own" and change.pokemon_id == primary_id and change.stat == "spd")
		progress += _setup_gain(current, min(spa_gain, spd_gain))
		current_veil = any(condition.id == "auroraveil" and condition.active for condition in knowledge.field.own_side_conditions)
		if not current_veil and "auroraveil" in {to_id(value) for value in outcome.projected_own_side_conditions}:
			progress += 0.30
	elif plan == PlanLabel.AGGRON_FORTRESS.value:
		current = max(0, boosts.get("def", 0))
		def_gain = sum(max(0, change.stages) for change in outcome.boost_changes if change.side == "own" and change.pokemon_id == primary_id and change.stat == "def")
		progress += _setup_gain(current, def_gain)
		if _candidate_transforms(candidate, knowledge, primary_id) and own.transformation.value is None:
			progress += 0.25

	if any(change.side == "own" and change.pokemon_id == primary_id and change.kind == "heal" for change in outcome.status_changes):
		progress += 0.20
	new_statuses = [
		change.status for change in outcome.status_changes
		if change.side == "own" and change.pokemon_id == primary_id and change.kind in {"status", "volatile"}
	]
	if new_statuses:
		progress -= 0.25
	if plan == PlanLabel.AGGRON_FORTRESS.value and any(to_id(status) == "brn" for status in new_statuses):
		progress -= 0.25
	if primary_id in outcome.possible_own_faints:
		progress -= 0.35
	return max(-1.0, min(1.0, progress))


def _setup_gain(current_stage: int, gained_stages: int) -> float:
	# Diminishing returns are semantic rather than move-specific: early setup
	# stages matter more than fourth/fifth/sixth stages.
	schedule = (0.35, 0.25, 0.15, 0.08, 0.04, 0.02)
	start = max(0, min(6, int(current_stage)))
	end = max(start, min(6, start + int(gained_stages)))
	return sum(schedule[stage - 1] for stage in range(start + 1, end + 1))


def _weather_control_gain(
	knowledge: KnowledgeState,
	strategy: RuntimeStrategyAssessment,
	outcome: ProjectedOutcome,
) -> float:
	# Weather value is generic in the emitted feature, while current strategic
	# interpretation comes from B4. This team presently exposes the strength of
	# its snow-dependent Glaceon route as the weather-control demand signal.
	importance = max(0.0, min(1.0, strategy.scores.glaceon_fortress / 100.0))
	before = _is_snow(knowledge.field.weather.value if isinstance(knowledge.field.weather.value, str) else None)
	after = _is_snow(outcome.projected_weather)
	if before == after:
		return 0.0
	return importance if after else -importance


def _safe_switch(
	knowledge: KnowledgeState,
	candidate: CanonicalLegalAction,
	outcome: ProjectedOutcome,
	policy_config: PolicyConfig,
) -> float:
	switches = _candidate_switches(candidate)
	if not switches:
		return 0.0
	values = []
	for _, pokemon_id in switches:
		if pokemon_id in outcome.own_faints:
			values.append(0.0)
			continue
		damage = sum(change.mid_fraction for change in outcome.own_hp_changes if change.pokemon_id == pokemon_id)
		if pokemon_id in outcome.possible_own_faints:
			values.append(0.25)
		elif damage <= policy_config.thresholds.low_hp_fraction:
			values.append(1.0)
		elif damage <= policy_config.thresholds.cleanup_hp_fraction:
			values.append(0.50)
		else:
			values.append(0.0)
	return sum(values) / len(values)


def _sacrificial_pivot(
	knowledge: KnowledgeState,
	candidate: CanonicalLegalAction,
	outcome: ProjectedOutcome,
	resource_by_id: Mapping[str, ResourceValue],
	max_resource: float,
	primary_id: str | None,
	policy_config: PolicyConfig,
) -> float:
	own_by_id = {pokemon.id: pokemon for pokemon in knowledge.own_team}
	active_by_position = dict(knowledge.own_active)
	best = 0.0
	for position, switch_id in _candidate_switches(candidate):
		pokemon = own_by_id.get(switch_id)
		outgoing_id = active_by_position.get(position)
		if pokemon is None or outgoing_id is None:
			continue
		if pokemon.health.percent / 100.0 > policy_config.thresholds.low_hp_fraction:
			continue
		if switch_id not in outcome.own_faints:
			continue
		outgoing_value = resource_by_id.get(outgoing_id).value if outgoing_id in resource_by_id else 0.0
		sacrifice_value = resource_by_id.get(switch_id).value if switch_id in resource_by_id else 0.0
		preserved = max(0.0, outgoing_value - sacrifice_value) / max_resource
		if primary_id == outgoing_id:
			preserved = max(preserved, 0.75)
		best = max(best, min(1.0, preserved))
	return best


def _control_gain(outcome: ProjectedOutcome) -> float:
	value = 0.0
	for change in outcome.status_changes:
		if change.side != "opponent":
			continue
		status = to_id(change.status)
		if status == "encore":
			value += 0.80
		elif status == "flinch":
			value += 0.35
		elif change.kind == "status":
			value += 0.60
		elif change.kind == "volatile":
			value += 0.40
	for change in outcome.boost_changes:
		if change.side != "opponent" or change.stages >= 0:
			continue
		per_stage = 0.35 if change.stat in {"accuracy", "spe"} else 0.20
		value += per_stage * abs(change.stages)
	return min(2.0, value)


def _opponent_setup_allowed(
	knowledge: KnowledgeState,
	outcome: ProjectedOutcome,
	response: OpponentJointResponse,
) -> float:
	value = 0.0
	for change in outcome.boost_changes:
		if change.side == "opponent" and change.stages > 0:
			value += 0.25 * change.stages
	current_conditions = {to_id(condition.id) for condition in knowledge.field.opponent_side_conditions if condition.active}
	projected_conditions = {to_id(value) for value in outcome.projected_opponent_side_conditions}
	value += 0.40 * len(projected_conditions - current_conditions)
	for action in response.actions:
		if OpponentActionRole.SETUP not in action.roles:
			continue
		record = next((
			record for record in outcome.action_records
			if record.side == "opponent" and record.actor_id == action.actor_id and record.action == action.move
		), None)
		if record is not None and record.blocked_by is None:
			value += 0.35
	return min(2.0, value)


def _rng_dependence(
	outcome: ProjectedOutcome,
	resource_by_id: Mapping[str, ResourceValue],
	max_resource: float,
	primary_id: str | None,
) -> float:
	value = 0.0
	for record in outcome.action_records:
		if record.hit_probability is None or record.hit_probability >= 1.0:
			continue
		miss = 1.0 - record.hit_probability
		if record.side == "own":
			value = max(value, miss)
		else:
			target = record.original_target_id
			importance = _resource_importance(target, resource_by_id, max_resource)
			if target == primary_id:
				importance = max(importance, 1.0)
			value = max(value, 0.50 * miss * importance)
	if ProjectionUncertainty.REPEATED_PROTECT in outcome.uncertain_interactions:
		value = max(value, 0.75)
	if ProjectionUncertainty.REPEATED_ALLY_SWITCH in outcome.uncertain_interactions:
		value = max(value, 0.75)
	if outcome.possible_own_faints:
		value = max(value, 0.40)
	return min(1.0, value)


def _mechanic_uncertainty(outcome: ProjectedOutcome) -> float:
	if ProjectionUncertainty.UNKNOWN_DYNAMIC_EFFECT in outcome.uncertain_interactions:
		return 1.0
	value = 0.0
	if outcome.confidence is ProjectionConfidence.LOW:
		value = max(value, 0.80)
	elif outcome.confidence is ProjectionConfidence.MEDIUM:
		value = max(value, 0.25)
	weights = {
		ProjectionUncertainty.SPEED_ORDER: 0.45,
		ProjectionUncertainty.OPPONENT_TRANSFORMATION: 0.35,
		ProjectionUncertainty.ENTRY_WEATHER_ORDER: 0.35,
		ProjectionUncertainty.UNKNOWN_BENCH_HP: 0.20,
	}
	for uncertainty, penalty in weights.items():
		if uncertainty in outcome.uncertain_interactions:
			value = max(value, penalty)
	return min(1.0, value)


def _free_turn_conversion(outcome: ProjectedOutcome, values: Mapping[str, float]) -> float:
	denied = any(
		record.side == "opponent" and record.blocked_by in {"protect", "wideguard", "flinch", "actor unavailable"}
		for record in outcome.action_records
	)
	if not denied:
		return 0.0
	progress = (
		0.25 * values["OPPONENT_DAMAGE"] +
		0.35 * values["OPPONENT_KO"] +
		0.35 * max(0.0, values["WIN_CONDITION_PROGRESS"]) +
		0.20 * values["CONTROL_GAIN"] +
		0.20 * max(0.0, values["WEATHER_CONTROL_GAIN"])
	)
	return min(1.0, progress)


def _joint_coordination(
	candidate: CanonicalLegalAction,
	outcome: ProjectedOutcome,
	values: Mapping[str, float],
) -> float:
	actions = [action for action in candidate.payload.get("actions", {}).values() if action]
	if len(actions) < 2:
		return 0.0
	own_records = [record for record in outcome.action_records if record.side == "own"]
	support = any(
		any(token in " ".join(record.notes).lower() for token in ("protection active", "wide guard active", "redirection active", "positions swapped"))
		for record in own_records
	)
	progress = (
		values["OPPONENT_DAMAGE"] > 0.10 or
		values["OPPONENT_KO"] > 0 or
		values["WIN_CONDITION_PROGRESS"] > 0.10 or
		values["CONTROL_GAIN"] > 0.10 or
		values["WEATHER_CONTROL_GAIN"] > 0.10
	)
	value = 0.0
	if support and progress:
		value += 0.55
	if values["DETERMINISTIC_PROTECTION"] > 0 or values["SPREAD_PREVENTION"] > 0:
		value += 0.35
	blocked_own = sum(record.blocked_by is not None for record in own_records)
	if own_records and blocked_own == len(own_records) and not progress:
		value -= 0.75
	if all(action.get("type") == "move" and to_id(str(action.get("move"))) == "protect" for action in actions):
		if values["OPPONENT_SETUP_ALLOWED"] > 0:
			value -= 0.40
	return max(-1.0, min(1.0, value))


def _primary_resource_id(strategy: RuntimeStrategyAssessment) -> str | None:
	plan = strategy.scores.primary_plan
	species = {
		PlanLabel.GLACEON_FORTRESS.value: "glaceon",
		PlanLabel.AGGRON_FORTRESS.value: "aggron",
	}.get(plan)
	if species is None:
		return None
	for resource in strategy.resources:
		if to_id(resource.species) == species:
			return resource.pokemon_id
	return None


def _candidate_transforms(candidate: CanonicalLegalAction, knowledge: KnowledgeState, pokemon_id: str) -> bool:
	active = dict(knowledge.own_active)
	for position, action in candidate.payload.get("actions", {}).items():
		if active.get(position) == pokemon_id and action and action.get("transformation"):
			return True
	return False


def _candidate_switches(candidate: CanonicalLegalAction) -> tuple[tuple[str, str], ...]:
	result = []
	for position, action in candidate.payload.get("actions", {}).items():
		if action and action.get("type") == "switch" and isinstance(action.get("pokemon"), str):
			result.append((position, action["pokemon"]))
	return tuple(result)


def _resource_importance(
	pokemon_id: str | None,
	resource_by_id: Mapping[str, ResourceValue],
	max_resource: float,
) -> float:
	if pokemon_id is None or pokemon_id not in resource_by_id:
		return 0.50 if pokemon_id is not None else 0.0
	return max(0.0, min(1.0, resource_by_id[pokemon_id].value / max_resource))


def _response_action_for(
	record: ProjectedActionRecord,
	response: OpponentJointResponse,
) -> OpponentIndividualAction | None:
	for action in response.actions:
		if action.actor_id == record.actor_id and action.move == record.action:
			return action
	return None


def _target_took_zero_damage(outcome: ProjectedOutcome, pokemon_id: str) -> bool:
	changes = [change for change in outcome.own_hp_changes if change.pokemon_id == pokemon_id]
	return bool(changes) and all(change.high_fraction <= 0 for change in changes)


def _is_snow(weather: str | None) -> bool:
	return bool(weather and to_id(weather) in {"snow", "snowscape", "hail"})


def _worst_confidence(values: tuple[ProjectionConfidence, ...]) -> ProjectionConfidence:
	rank = {ProjectionConfidence.HIGH: 0, ProjectionConfidence.MEDIUM: 1, ProjectionConfidence.LOW: 2}
	return max(values, key=lambda value: rank[value])


def _bounded(value: float, minimum: float, maximum: float) -> float:
	if not math.isfinite(value):
		raise ScoringContractError("B8 feature extraction produced a non-finite value")
	return max(minimum, min(maximum, float(value)))


def _finite(value: object) -> bool:
	return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
