"""Named B10 runtime and forced-replacement policy parameters."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping


RUNTIME_DEGRADED_MODES = frozenset({"MEDIUM", "LOW", "EMERGENCY"})
REPLACEMENT_PLAN_KEYS = frozenset({"GLACEON_FORTRESS", "AGGRON_FORTRESS", "DEFAULT"})
PAIR_SYNERGY_KEYS = frozenset({
	"aggron+maushold",
	"glaceon+maushold",
	"glaceon+ninetalesalola",
})


@dataclass(frozen=True)
class OrchestrationConfig:
	version: str
	degraded_response_caps: Mapping[str, tuple[int, int]]
	replacement_resource_value_factor: float
	replacement_role_bonuses: Mapping[str, Mapping[str, float]]
	replacement_weather_reset_bonus: float
	replacement_pair_synergies: Mapping[str, float]
	matchup_base_value: float
	matchup_worst_multiplier_penalty: float
	matchup_average_multiplier_penalty: float
	matchup_move_power_reference: float
	matchup_move_power_floor: float
	matchup_move_power_cap: float

	def validate(self) -> None:
		if not isinstance(self.version, str) or not self.version.strip():
			raise ValueError("orchestration.version must be a non-empty string")
		if set(self.degraded_response_caps) != RUNTIME_DEGRADED_MODES:
			raise ValueError("orchestration degraded response modes must be MEDIUM/LOW/EMERGENCY")
		for mode, caps in self.degraded_response_caps.items():
			if not isinstance(caps, tuple) or len(caps) != 2:
				raise ValueError(f"orchestration response caps for {mode} must be a 2-tuple")
			individual, joint = caps
			if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in caps):
				raise ValueError(f"orchestration response caps for {mode} must be positive integers")
			if joint < 1 or individual < 1:
				raise ValueError(f"orchestration response caps for {mode} must be positive")

		if set(self.replacement_role_bonuses) != REPLACEMENT_PLAN_KEYS:
			raise ValueError("replacement_role_bonuses must contain GLACEON_FORTRESS/AGGRON_FORTRESS/DEFAULT")
		for plan, values in self.replacement_role_bonuses.items():
			if not isinstance(values, Mapping):
				raise ValueError(f"replacement role bonuses for {plan} must be a mapping")
			for species, value in values.items():
				if not isinstance(species, str) or not species:
					raise ValueError("replacement role bonus species IDs must be non-empty strings")
				_finite(value, f"replacement_role_bonuses.{plan}.{species}")
		if set(self.replacement_pair_synergies) != PAIR_SYNERGY_KEYS:
			raise ValueError("replacement_pair_synergies must contain the exact named pair keys")
		for pair, value in self.replacement_pair_synergies.items():
			_finite(value, f"replacement_pair_synergies.{pair}")

		for name in (
			"replacement_resource_value_factor",
			"replacement_weather_reset_bonus",
			"matchup_base_value",
			"matchup_worst_multiplier_penalty",
			"matchup_average_multiplier_penalty",
			"matchup_move_power_reference",
			"matchup_move_power_floor",
			"matchup_move_power_cap",
		):
			_finite(getattr(self, name), f"orchestration.{name}")
		if self.replacement_resource_value_factor < 0:
			raise ValueError("replacement_resource_value_factor must be non-negative")
		if self.matchup_move_power_reference <= 0:
			raise ValueError("matchup_move_power_reference must be positive")
		if self.matchup_move_power_floor <= 0 or self.matchup_move_power_floor > self.matchup_move_power_cap:
			raise ValueError("matchup move-power floor/cap must satisfy 0 < floor <= cap")


def default_orchestration_config() -> OrchestrationConfig:
	config = OrchestrationConfig(
		version="b10-orchestration-v1",
		degraded_response_caps={
			"MEDIUM": (3, 4),
			"LOW": (2, 3),
			"EMERGENCY": (1, 2),
		},
		replacement_resource_value_factor=0.20,
		replacement_role_bonuses={
			"GLACEON_FORTRESS": {
				"ninetalesalola": 24.0,
				"maushold": 18.0,
				"glaceon": 14.0,
				"armarouge": 8.0,
			},
			"AGGRON_FORTRESS": {
				"maushold": 24.0,
				"aggron": 14.0,
				"armarouge": 10.0,
			},
			"DEFAULT": {
				"heliolisk": 10.0,
				"armarouge": 9.0,
				"ninetalesalola": 8.0,
			},
		},
		replacement_weather_reset_bonus=18.0,
		replacement_pair_synergies={
			"aggron+maushold": 12.0,
			"glaceon+maushold": 12.0,
			"glaceon+ninetalesalola": 15.0,
		},
		matchup_base_value=14.0,
		matchup_worst_multiplier_penalty=10.0,
		matchup_average_multiplier_penalty=4.0,
		matchup_move_power_reference=100.0,
		matchup_move_power_floor=0.25,
		matchup_move_power_cap=1.5,
	)
	config.validate()
	return config


def pair_synergy_key(species: set[str]) -> tuple[str, ...]:
	"""Return configured pair keys contained in one multi-replacement action."""
	result: list[str] = []
	for pair in sorted(PAIR_SYNERGY_KEYS):
		left, right = pair.split("+", 1)
		if left in species and right in species:
			result.append(pair)
	return tuple(result)


def _finite(value: object, label: str) -> float:
	if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
		raise ValueError(f"{label} must be a finite number")
	return float(value)
