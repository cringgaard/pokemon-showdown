"""Stable numeric-feature metadata. Scoring weights live in configuration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FeatureFamily(str, Enum):
	OFFENSE = "offense"
	DEFENSE = "defense"
	STRATEGY = "strategy"
	POSITIONING = "positioning"
	CONTROL = "control"
	UNCERTAINTY_RISK = "uncertainty_risk"
	JOINT_ACTION_COORDINATION = "joint_action_coordination"


@dataclass(frozen=True)
class FeatureDefinition:
	id: str
	family: FeatureFamily
	description: str
	minimum: float
	maximum: float


FEATURE_REGISTRY = (
	FeatureDefinition("OPPONENT_DAMAGE", FeatureFamily.OFFENSE, "Fractional public HP removed from opponents.", 0, 2),
	FeatureDefinition("OPPONENT_KO", FeatureFamily.OFFENSE, "Strategically weighted opposing knockouts.", 0, 2),
	FeatureDefinition("FREE_TURN_CONVERSION", FeatureFamily.OFFENSE, "Concrete progress made during a denied turn.", 0, 1),
	FeatureDefinition("OWN_RESOURCE_SURVIVAL", FeatureFamily.DEFENSE, "Preservation of current strategic resources.", 0, 2),
	FeatureDefinition("DETERMINISTIC_PROTECTION", FeatureFamily.DEFENSE, "Known protection from a credible harmful effect.", 0, 2),
	FeatureDefinition("SPREAD_PREVENTION", FeatureFamily.DEFENSE, "Material spread damage or effects prevented.", 0, 2),
	FeatureDefinition("PRIMARY_WINCON_SURVIVAL", FeatureFamily.STRATEGY, "Survival of the current primary route to victory.", 0, 1),
	FeatureDefinition("WIN_CONDITION_PROGRESS", FeatureFamily.STRATEGY, "Progress toward a currently viable strategic plan.", -1, 1),
	FeatureDefinition("WEATHER_CONTROL_GAIN", FeatureFamily.STRATEGY, "Improvement in strategically useful weather control.", -1, 1),
	FeatureDefinition("SAFE_SWITCH", FeatureFamily.POSITIONING, "A switch that improves position without unacceptable exposure.", 0, 1),
	FeatureDefinition("SACRIFICIAL_PIVOT_VALUE", FeatureFamily.POSITIONING, "Value created by a deliberate low-resource sacrifice.", 0, 1),
	FeatureDefinition("CONTROL_GAIN", FeatureFamily.CONTROL, "Deterministic or probabilistic restriction of opposing options.", 0, 2),
	FeatureDefinition("OPPONENT_SETUP_ALLOWED", FeatureFamily.CONTROL, "Material setup conceded to an opponent.", 0, 2),
	FeatureDefinition("RNG_DEPENDENCE", FeatureFamily.UNCERTAINTY_RISK, "Dependence on favorable random outcomes for survival or progress.", 0, 1),
	FeatureDefinition("MECHANIC_UNCERTAINTY", FeatureFamily.UNCERTAINTY_RISK, "Reliance on incompletely modelled dynamic mechanics.", 0, 1),
	FeatureDefinition("FRAGILE_PREDICTION", FeatureFamily.UNCERTAINTY_RISK, "Sensitivity to one narrow opponent prediction.", 0, 1),
	FeatureDefinition("JOINT_ACTION_COORDINATION", FeatureFamily.JOINT_ACTION_COORDINATION, "Complementary value created by both allied actions.", -1, 1),
	FeatureDefinition("ROBUST_ACROSS_RESPONSES", FeatureFamily.JOINT_ACTION_COORDINATION, "Value retained across diverse credible responses.", 0, 1),
)


def feature_registry_by_id() -> dict[str, FeatureDefinition]:
	registry = {feature.id: feature for feature in FEATURE_REGISTRY}
	if len(registry) != len(FEATURE_REGISTRY):
		raise RuntimeError("Feature IDs must be unique")
	for feature in FEATURE_REGISTRY:
		if not feature.id or feature.id != feature.id.upper() or feature.minimum > feature.maximum:
			raise RuntimeError(f"Invalid feature metadata: {feature.id!r}")
	return registry


FEATURES_BY_ID = feature_registry_by_id()
