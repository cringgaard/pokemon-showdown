"""Strict configuration schema for deterministic snow-policy experiments."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from .features import FEATURES_BY_ID
from .serialization import canonical_json, parse_json, to_primitive


STRATEGY_WEIGHT_IDS = frozenset({
	"GLACEON_BASE",
	"GLACEON_HP",
	"GLACEON_SNOW",
	"GLACEON_VEIL",
	"GLACEON_SETUP_PER_STAGE",
	"GLACEON_SETUP_CAP",
	"GLACEON_WEATHER_RESET",
	"GLACEON_FAVORABLE_MATCHUP",
	"GLACEON_FAVORABLE_MATCHUP_CAP",
	"GLACEON_PHYSICAL_PRESSURE",
	"GLACEON_NO_GUARD_PENALTY",
	"GLACEON_GRAVITY_PENALTY",
	"GLACEON_ACCURACY_BYPASS_PENALTY",
	"GLACEON_DANGEROUS_MOVE_PENALTY",
	"GLACEON_DANGEROUS_MOVE_PENALTY_CAP",
	"GLACEON_NO_SNOW_PENALTY",
	"GLACEON_LETHAL_PRESSURE_PENALTY",
	"GLACEON_HEAVY_PRESSURE_PENALTY",
	"AGGRON_BASE",
	"AGGRON_HP",
	"AGGRON_MEGA",
	"AGGRON_DEFENSE_PER_STAGE",
	"AGGRON_DEFENSE_CAP",
	"AGGRON_PHYSICAL_PRESSURE",
	"AGGRON_BODY_PRESS_QUALITY",
	"AGGRON_MAUSHOLD_SUPPORT",
	"AGGRON_BURN_PENALTY",
	"AGGRON_GHOST_PRESSURE_PENALTY",
	"AGGRON_SPECIAL_PRESSURE_PENALTY",
	"AGGRON_LOW_HP_PENALTY",
	"AGGRON_BASE_LETHAL_PRESSURE_PENALTY",
	"AGGRON_BASE_HEAVY_PRESSURE_PENALTY",
	"TACTICAL_BASE",
	"TACTICAL_CLEANUP_TARGET",
	"TACTICAL_LOW_TARGET",
	"TACTICAL_FAINTED_OPPONENT",
	"TACTICAL_FAINTED_OPPONENT_CAP",
	"TACTICAL_SUPER_EFFECTIVE_PAIR",
	"TACTICAL_SUPER_EFFECTIVE_CAP",
	"TACTICAL_SPREAD_CLEANUP",
	"TACTICAL_WEAK_FORTRESS_FACTOR",
	"TACTICAL_WEAK_FORTRESS_CAP",
	"TACTICAL_IMMEDIATE_PRESSURE",
	"GLACEON_ROLE_BASE",
	"GLACEON_ROLE_PLAN",
	"AGGRON_ROLE_BASE",
	"AGGRON_ROLE_PLAN",
	"NINETALES_ROLE_BASE",
	"NINETALES_ROLE_GLACEON",
	"NINETALES_WEATHER_WAR",
	"MAUSHOLD_ROLE_BASE",
	"MAUSHOLD_ROLE_FORTRESS",
	"ARMAROUGE_ROLE_BASE",
	"ARMAROUGE_ROLE_FORTRESS",
	"ARMAROUGE_SPREAD_PRESSURE",
	"HELIOLISK_ROLE_BASE",
	"HELIOLISK_TACTICAL",
	"HELIOLISK_WATER_PRESSURE",
	"RESOURCE_ROLE_MIN",
	"RESOURCE_ROLE_MAX",
	"AGGRON_BURN_REMAINING",
	"GLACEON_NO_SNOW_REMAINING",
	"MAJOR_STATUS_REMAINING",
})

DEFAULT_HP_UTILITY_CURVE: tuple[tuple[float, float], ...] = (
	(0.0, 0.0),
	(0.01, 0.20),
	(0.25, 0.45),
	(0.50, 0.70),
	(0.75, 0.90),
	(1.00, 1.00),
)


@dataclass(frozen=True)
class VersionConfig:
	policy: str
	config: str
	weights: str
	mechanics: str
	team: str


@dataclass(frozen=True)
class ThresholdConfig:
	clear_primary_plan_margin: float
	credible_response_relative_weight: float
	low_hp_fraction: float
	critical_hp_fraction: float
	cleanup_hp_fraction: float
	spread_cleanup_hp_fraction: float
	physical_pressure_preference_fraction: float
	heavy_pressure_fraction: float
	fortress_weak_score: float
	pressure_saturation_move_count: float


@dataclass(frozen=True)
class StrategyConfig:
	weights: dict[str, float]
	hp_utility_curve: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class OpponentResponseConfig:
	max_individual_actions_per_pokemon: int
	max_joint_responses: int
	same_move_multiplier: float
	same_target_multiplier: float
	repeated_pattern_cap: float
	confirmed_selected_multiplier: float
	possible_selected_multiplier: float


@dataclass(frozen=True)
class RuntimeConfig:
	full_mode_minimum_ms: int
	medium_mode_minimum_ms: int
	low_mode_minimum_ms: int
	emergency_reserve_ms: int


@dataclass(frozen=True)
class TeamRole:
	species: str
	roles: tuple[str, ...]
	base_resource_value: float


@dataclass(frozen=True)
class PolicyConfig:
	versions: VersionConfig
	weights: dict[str, float]
	thresholds: ThresholdConfig
	strategy: StrategyConfig
	opponent_response: OpponentResponseConfig
	runtime: RuntimeConfig
	team_roles: tuple[TeamRole, ...]

	def validate(self) -> None:
		for label, version in vars(self.versions).items():
			if not isinstance(version, str) or not version.strip():
				raise ValueError(f"versions.{label} must be a non-empty string")
		_validate_exact_numeric_weights(self.weights, set(FEATURES_BY_ID), "weights")
		_validate_exact_numeric_weights(self.strategy.weights, set(STRATEGY_WEIGHT_IDS), "strategy.weights")
		_validate_hp_curve(self.strategy.hp_utility_curve)

		thresholds = self.thresholds
		margin = _finite_number(thresholds.clear_primary_plan_margin, "thresholds.clear_primary_plan_margin")
		if margin < 0:
			raise ValueError("clear_primary_plan_margin must be non-negative")
		credible = _fraction(thresholds.credible_response_relative_weight, "thresholds.credible_response_relative_weight")
		if credible <= 0:
			raise ValueError("credible_response_relative_weight must be greater than zero")
		low = _fraction(thresholds.low_hp_fraction, "thresholds.low_hp_fraction")
		critical = _fraction(thresholds.critical_hp_fraction, "thresholds.critical_hp_fraction")
		cleanup = _fraction(thresholds.cleanup_hp_fraction, "thresholds.cleanup_hp_fraction")
		spread_cleanup = _fraction(thresholds.spread_cleanup_hp_fraction, "thresholds.spread_cleanup_hp_fraction")
		physical = _fraction(thresholds.physical_pressure_preference_fraction, "thresholds.physical_pressure_preference_fraction")
		heavy = _fraction(thresholds.heavy_pressure_fraction, "thresholds.heavy_pressure_fraction")
		if critical > low or low > cleanup:
			raise ValueError("HP thresholds must satisfy critical <= low <= cleanup")
		if spread_cleanup > cleanup:
			raise ValueError("spread_cleanup_hp_fraction must not exceed cleanup_hp_fraction")
		if physical <= 0 or heavy <= 0:
			raise ValueError("physical/heavy pressure thresholds must be greater than zero")
		fortress = _finite_number(thresholds.fortress_weak_score, "thresholds.fortress_weak_score")
		if not 0 <= fortress <= 100:
			raise ValueError("fortress_weak_score must be between zero and 100")
		if _finite_number(thresholds.pressure_saturation_move_count, "thresholds.pressure_saturation_move_count") <= 0:
			raise ValueError("pressure_saturation_move_count must be greater than zero")

		response = self.opponent_response
		_positive_int(response.max_individual_actions_per_pokemon, "max_individual_actions_per_pokemon")
		_positive_int(response.max_joint_responses, "max_joint_responses")
		for name in (
			"same_move_multiplier", "same_target_multiplier", "repeated_pattern_cap",
			"confirmed_selected_multiplier", "possible_selected_multiplier",
		):
			if _finite_number(getattr(response, name), f"opponent_response.{name}") < 0:
				raise ValueError(f"opponent_response.{name} must be non-negative")

		runtime_values = [
			self.runtime.full_mode_minimum_ms,
			self.runtime.medium_mode_minimum_ms,
			self.runtime.low_mode_minimum_ms,
			self.runtime.emergency_reserve_ms,
		]
		for name, value in zip(vars(self.runtime), runtime_values):
			_non_negative_int(value, f"runtime.{name}")
		if runtime_values != sorted(runtime_values, reverse=True):
			raise ValueError("runtime thresholds must descend from full mode to emergency reserve")

		seen_species: set[str] = set()
		for role in self.team_roles:
			if not isinstance(role.species, str) or not role.species.strip() or role.species in seen_species:
				raise ValueError("team role species must be non-empty and unique")
			seen_species.add(role.species)
			if not role.roles or any(not isinstance(item, str) or not item.strip() for item in role.roles):
				raise ValueError(f"team role {role.species} must contain non-empty roles")
			if _finite_number(role.base_resource_value, f"team_roles.{role.species}.base_resource_value") <= 0:
				raise ValueError("base_resource_value must be greater than zero")

		minimum = self.strategy.weights["RESOURCE_ROLE_MIN"]
		maximum = self.strategy.weights["RESOURCE_ROLE_MAX"]
		if minimum < 0 or maximum < minimum:
			raise ValueError("resource role multiplier bounds are invalid")
		for key in ("AGGRON_BURN_REMAINING", "GLACEON_NO_SNOW_REMAINING", "MAJOR_STATUS_REMAINING"):
			_fraction(self.strategy.weights[key], f"strategy.weights.{key}")

	def to_dict(self) -> dict[str, Any]:
		return {name: to_primitive(getattr(self, name)) for name in self.__dataclass_fields__}

	def to_json(self) -> str:
		return canonical_json(self)

	@classmethod
	def from_json(cls, value: str) -> "PolicyConfig":
		return cls.from_dict(_mapping(parse_json(value), "configuration"))

	@classmethod
	def from_dict(cls, value: Mapping[str, Any]) -> "PolicyConfig":
		_exact_keys(
			value,
			{"versions", "weights", "thresholds", "strategy", "opponent_response", "runtime", "team_roles"},
			"configuration",
		)
		versions = _mapping(value["versions"], "versions")
		_exact_keys(versions, {"policy", "config", "weights", "mechanics", "team"}, "versions")
		thresholds = _mapping(value["thresholds"], "thresholds")
		_exact_keys(thresholds, {
			"clear_primary_plan_margin", "credible_response_relative_weight", "low_hp_fraction",
			"critical_hp_fraction", "cleanup_hp_fraction", "spread_cleanup_hp_fraction",
			"physical_pressure_preference_fraction", "heavy_pressure_fraction", "fortress_weak_score",
			"pressure_saturation_move_count",
		}, "thresholds")
		strategy = _mapping(value["strategy"], "strategy")
		_exact_keys(strategy, {"weights", "hp_utility_curve"}, "strategy")
		strategy_weights = _mapping(strategy["weights"], "strategy.weights")
		curve_value = strategy["hp_utility_curve"]
		if not isinstance(curve_value, list):
			raise ValueError("strategy.hp_utility_curve must be an array")
		curve: list[tuple[float, float]] = []
		for index, point_value in enumerate(curve_value):
			if not isinstance(point_value, list) or len(point_value) != 2:
				raise ValueError(f"strategy.hp_utility_curve[{index}] must be a two-value array")
			curve.append((point_value[0], point_value[1]))

		response = _mapping(value["opponent_response"], "opponent_response")
		_exact_keys(response, {
			"max_individual_actions_per_pokemon", "max_joint_responses", "same_move_multiplier",
			"same_target_multiplier", "repeated_pattern_cap", "confirmed_selected_multiplier",
			"possible_selected_multiplier",
		}, "opponent_response")
		runtime = _mapping(value["runtime"], "runtime")
		_exact_keys(runtime, {"full_mode_minimum_ms", "medium_mode_minimum_ms", "low_mode_minimum_ms", "emergency_reserve_ms"}, "runtime")
		weights = _mapping(value["weights"], "weights")
		roles_value = value["team_roles"]
		if not isinstance(roles_value, list):
			raise ValueError("team_roles must be an array")
		roles = []
		for index, item in enumerate(roles_value):
			role = _mapping(item, f"team_roles[{index}]")
			_exact_keys(role, {"species", "roles", "base_resource_value"}, f"team_roles[{index}]")
			if not isinstance(role["roles"], list):
				raise ValueError(f"team_roles[{index}].roles must be an array")
			roles.append(TeamRole(role["species"], tuple(role["roles"]), role["base_resource_value"]))
		config = cls(
			versions=VersionConfig(**versions),
			weights=dict(weights),
			thresholds=ThresholdConfig(**thresholds),
			strategy=StrategyConfig(dict(strategy_weights), tuple(curve)),
			opponent_response=OpponentResponseConfig(**response),
			runtime=RuntimeConfig(**runtime),
			team_roles=tuple(roles),
		)
		config.validate()
		return config


def default_config() -> PolicyConfig:
	strategy_weights = {
		"GLACEON_BASE": 35.0,
		"GLACEON_HP": 25.0,
		"GLACEON_SNOW": 12.0,
		"GLACEON_VEIL": 10.0,
		"GLACEON_SETUP_PER_STAGE": 6.0,
		"GLACEON_SETUP_CAP": 12.0,
		"GLACEON_WEATHER_RESET": 6.0,
		"GLACEON_FAVORABLE_MATCHUP": 6.0,
		"GLACEON_FAVORABLE_MATCHUP_CAP": 12.0,
		"GLACEON_PHYSICAL_PRESSURE": 4.0,
		"GLACEON_NO_GUARD_PENALTY": 22.0,
		"GLACEON_GRAVITY_PENALTY": 12.0,
		"GLACEON_ACCURACY_BYPASS_PENALTY": 15.0,
		"GLACEON_DANGEROUS_MOVE_PENALTY": 4.0,
		"GLACEON_DANGEROUS_MOVE_PENALTY_CAP": 20.0,
		"GLACEON_NO_SNOW_PENALTY": 15.0,
		"GLACEON_LETHAL_PRESSURE_PENALTY": 20.0,
		"GLACEON_HEAVY_PRESSURE_PENALTY": 10.0,
		"AGGRON_BASE": 35.0,
		"AGGRON_HP": 25.0,
		"AGGRON_MEGA": 15.0,
		"AGGRON_DEFENSE_PER_STAGE": 6.0,
		"AGGRON_DEFENSE_CAP": 12.0,
		"AGGRON_PHYSICAL_PRESSURE": 12.0,
		"AGGRON_BODY_PRESS_QUALITY": 12.0,
		"AGGRON_MAUSHOLD_SUPPORT": 6.0,
		"AGGRON_BURN_PENALTY": 22.0,
		"AGGRON_GHOST_PRESSURE_PENALTY": 18.0,
		"AGGRON_SPECIAL_PRESSURE_PENALTY": 16.0,
		"AGGRON_LOW_HP_PENALTY": 8.0,
		"AGGRON_BASE_LETHAL_PRESSURE_PENALTY": 15.0,
		"AGGRON_BASE_HEAVY_PRESSURE_PENALTY": 7.0,
		"TACTICAL_BASE": 10.0,
		"TACTICAL_CLEANUP_TARGET": 14.0,
		"TACTICAL_LOW_TARGET": 6.0,
		"TACTICAL_FAINTED_OPPONENT": 6.0,
		"TACTICAL_FAINTED_OPPONENT_CAP": 18.0,
		"TACTICAL_SUPER_EFFECTIVE_PAIR": 6.0,
		"TACTICAL_SUPER_EFFECTIVE_CAP": 18.0,
		"TACTICAL_SPREAD_CLEANUP": 15.0,
		"TACTICAL_WEAK_FORTRESS_FACTOR": 0.30,
		"TACTICAL_WEAK_FORTRESS_CAP": 12.0,
		"TACTICAL_IMMEDIATE_PRESSURE": 6.0,
		"GLACEON_ROLE_BASE": 0.65,
		"GLACEON_ROLE_PLAN": 0.70,
		"AGGRON_ROLE_BASE": 0.65,
		"AGGRON_ROLE_PLAN": 0.70,
		"NINETALES_ROLE_BASE": 0.75,
		"NINETALES_ROLE_GLACEON": 0.50,
		"NINETALES_WEATHER_WAR": 0.15,
		"MAUSHOLD_ROLE_BASE": 0.75,
		"MAUSHOLD_ROLE_FORTRESS": 0.45,
		"ARMAROUGE_ROLE_BASE": 0.75,
		"ARMAROUGE_ROLE_FORTRESS": 0.25,
		"ARMAROUGE_SPREAD_PRESSURE": 0.20,
		"HELIOLISK_ROLE_BASE": 0.80,
		"HELIOLISK_TACTICAL": 0.35,
		"HELIOLISK_WATER_PRESSURE": 0.15,
		"RESOURCE_ROLE_MIN": 0.25,
		"RESOURCE_ROLE_MAX": 1.50,
		"AGGRON_BURN_REMAINING": 0.75,
		"GLACEON_NO_SNOW_REMAINING": 0.85,
		"MAJOR_STATUS_REMAINING": 0.80,
	}
	config = PolicyConfig(
		versions=VersionConfig("snow-policy-b4", "b4-defaults-v1", "untrained-v1", "schema-v2", "champions-snow-v1"),
		weights={feature_id: 0.0 for feature_id in FEATURES_BY_ID},
		thresholds=ThresholdConfig(15.0, 0.15, 0.25, 0.10, 0.50, 0.40, 0.60, 0.60, 60.0, 2.0),
		strategy=StrategyConfig(strategy_weights, DEFAULT_HP_UTILITY_CURVE),
		opponent_response=OpponentResponseConfig(4, 8, 1.10, 1.10, 1.25, 1.0, 0.5),
		runtime=RuntimeConfig(1000, 500, 200, 50),
		team_roles=(
			TeamRole("Glaceon", ("fortress_win_condition", "spread_special_attacker"), 100),
			TeamRole("Ninetales-Alola", ("weather_control", "veil_support", "water_pressure"), 90),
			TeamRole("Maushold", ("redirection", "friend_guard_support", "accuracy_control"), 80),
			TeamRole("Aggron", ("fortress_win_condition", "physical_wall"), 100),
			TeamRole("Armarouge", ("spread_defense", "fire_immunity_pivot"), 85),
			TeamRole("Heliolisk", ("water_pressure", "sash_pivot"), 80),
		),
	)
	config.validate()
	return config


def _validate_exact_numeric_weights(value: Mapping[str, Any], expected: set[str], label: str) -> None:
	missing = expected - set(value)
	unknown = set(value) - expected
	if missing or unknown:
		display = "Feature weight" if label == "weights" else label
		raise ValueError(f"{display} IDs invalid; missing={sorted(missing)}, unknown={sorted(unknown)}")
	for key, weight in value.items():
		_finite_number(weight, f"{label}.{key}")


def _validate_hp_curve(curve: tuple[tuple[float, float], ...]) -> None:
	if len(curve) < 2:
		raise ValueError("strategy.hp_utility_curve requires at least two points")
	previous_fraction = -1.0
	for index, point in enumerate(curve):
		if not isinstance(point, tuple) or len(point) != 2:
			raise ValueError(f"strategy.hp_utility_curve[{index}] must be a pair")
		fraction = _fraction(point[0], f"strategy.hp_utility_curve[{index}][0]")
		_fraction(point[1], f"strategy.hp_utility_curve[{index}][1]")
		if fraction <= previous_fraction:
			raise ValueError("strategy.hp_utility_curve fractions must strictly increase")
		previous_fraction = fraction
	if curve[0][0] != 0 or curve[-1][0] != 1:
		raise ValueError("strategy.hp_utility_curve must span 0..1")
	if curve[0][1] != 0:
		raise ValueError("strategy.hp_utility_curve must value zero HP at zero")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
	if not isinstance(value, Mapping):
		raise ValueError(f"{label} must be an object")
	return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
	missing = expected - set(value)
	unknown = set(value) - expected
	if missing or unknown:
		raise ValueError(f"{label} keys invalid; missing={sorted(missing)}, unknown={sorted(unknown)}")


def _finite_number(value: Any, label: str) -> float:
	if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
		raise ValueError(f"{label} must be a finite number")
	return float(value)


def _fraction(value: Any, label: str) -> float:
	result = _finite_number(value, label)
	if result < 0 or result > 1:
		raise ValueError(f"{label} must be between zero and one")
	return result


def _positive_int(value: Any, label: str) -> None:
	if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
		raise ValueError(f"{label} must be a positive integer")


def _non_negative_int(value: Any, label: str) -> None:
	if isinstance(value, bool) or not isinstance(value, int) or value < 0:
		raise ValueError(f"{label} must be a non-negative integer")
