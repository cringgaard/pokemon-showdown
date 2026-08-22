"""Strict B1 configuration schema for deterministic policy experiments."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from .features import FEATURES_BY_ID
from .serialization import canonical_json, parse_json, to_primitive


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
	opponent_response: OpponentResponseConfig
	runtime: RuntimeConfig
	team_roles: tuple[TeamRole, ...]

	def validate(self) -> None:
		for label, version in vars(self.versions).items():
			if not isinstance(version, str) or not version.strip():
				raise ValueError(f"versions.{label} must be a non-empty string")
		missing_features = set(FEATURES_BY_ID) - set(self.weights)
		unknown_features = set(self.weights) - set(FEATURES_BY_ID)
		if missing_features or unknown_features:
			raise ValueError(
				f"Feature weight IDs invalid; missing={sorted(missing_features)}, unknown={sorted(unknown_features)}"
			)
		for feature_id, weight in self.weights.items():
			_finite_number(weight, f"weights.{feature_id}")
		margin = _finite_number(self.thresholds.clear_primary_plan_margin, "thresholds.clear_primary_plan_margin")
		credible = _fraction(self.thresholds.credible_response_relative_weight, "thresholds.credible_response_relative_weight")
		low = _fraction(self.thresholds.low_hp_fraction, "thresholds.low_hp_fraction")
		critical = _fraction(self.thresholds.critical_hp_fraction, "thresholds.critical_hp_fraction")
		if margin < 0:
			raise ValueError("clear_primary_plan_margin must be non-negative")
		if credible <= 0:
			raise ValueError("credible_response_relative_weight must be greater than zero")
		if critical > low:
			raise ValueError("critical_hp_fraction must not exceed low_hp_fraction")
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

	def to_dict(self) -> dict[str, Any]:
		return {name: to_primitive(getattr(self, name)) for name in self.__dataclass_fields__}

	def to_json(self) -> str:
		return canonical_json(self)

	@classmethod
	def from_json(cls, value: str) -> "PolicyConfig":
		return cls.from_dict(_mapping(parse_json(value), "configuration"))

	@classmethod
	def from_dict(cls, value: Mapping[str, Any]) -> "PolicyConfig":
		_exact_keys(value, {"versions", "weights", "thresholds", "opponent_response", "runtime", "team_roles"}, "configuration")
		versions = _mapping(value["versions"], "versions")
		_exact_keys(versions, {"policy", "config", "weights", "mechanics", "team"}, "versions")
		thresholds = _mapping(value["thresholds"], "thresholds")
		_exact_keys(thresholds, {"clear_primary_plan_margin", "credible_response_relative_weight", "low_hp_fraction", "critical_hp_fraction"}, "thresholds")
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
			opponent_response=OpponentResponseConfig(**response),
			runtime=RuntimeConfig(**runtime),
			team_roles=tuple(roles),
		)
		config.validate()
		return config


def default_config() -> PolicyConfig:
	config = PolicyConfig(
		versions=VersionConfig("snow-policy-b1", "b1-defaults-v1", "untrained-v1", "schema-v2", "champions-snow-v1"),
		weights={feature_id: 0.0 for feature_id in FEATURES_BY_ID},
		thresholds=ThresholdConfig(15.0, 0.15, 0.25, 0.10),
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
