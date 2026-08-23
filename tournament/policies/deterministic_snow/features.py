"""Stable numeric-feature metadata. Scoring weights live in configuration.

The feature set is a public policy interface: B8 emits the same ordered, bounded
semantic vector for every projected action/response outcome. Future learned
scorers may replace the hand-tuned linear weights without changing mechanics or
feature extraction. Changing the meaning/range/order of a feature requires a new
feature-set version.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


FEATURE_SCHEMA_VERSION = 1
FEATURE_SET_VERSION = "b8-outcome-features-v1"


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
	FeatureDefinition("OPPONENT_DAMAGE", FeatureFamily.OFFENSE, "Expected fractional public HP removed from opponents in this response.", 0, 2),
	FeatureDefinition("OPPONENT_KO", FeatureFamily.OFFENSE, "Threat-weighted definite and possible opposing knockouts.", 0, 2),
	FeatureDefinition("FREE_TURN_CONVERSION", FeatureFamily.OFFENSE, "Concrete progress made while an opposing action is deterministically denied.", 0, 1),
	FeatureDefinition("OWN_RESOURCE_SURVIVAL", FeatureFamily.DEFENSE, "Projected preservation of current strategically weighted own resources.", 0, 2),
	FeatureDefinition("DETERMINISTIC_PROTECTION", FeatureFamily.DEFENSE, "Known protection/redirection of a credible harmful effect from a valuable resource.", 0, 2),
	FeatureDefinition("SPREAD_PREVENTION", FeatureFamily.DEFENSE, "Material spread actions prevented by deterministic spread protection.", 0, 2),
	FeatureDefinition("PRIMARY_WINCON_SURVIVAL", FeatureFamily.STRATEGY, "Projected survival utility of the current clear primary route to victory.", 0, 1),
	FeatureDefinition("WIN_CONDITION_PROGRESS", FeatureFamily.STRATEGY, "Marginal setup/recovery/position progress toward the current strategic plan.", -1, 1),
	FeatureDefinition("WEATHER_CONTROL_GAIN", FeatureFamily.STRATEGY, "Change in weather control weighted by current weather-dependent plan value.", -1, 1),
	FeatureDefinition("SAFE_SWITCH", FeatureFamily.POSITIONING, "A voluntary switch that improves/preserves position without unacceptable exposure.", 0, 1),
	FeatureDefinition("SACRIFICIAL_PIVOT_VALUE", FeatureFamily.POSITIONING, "Value created by deliberately trading a low-resource switch-in to preserve a more important resource.", 0, 1),
	FeatureDefinition("CONTROL_GAIN", FeatureFamily.CONTROL, "Deterministic restriction of opposing options through status, volatile control, or stat suppression.", 0, 2),
	FeatureDefinition("OPPONENT_SETUP_ALLOWED", FeatureFamily.CONTROL, "Material setup/progress actually conceded to the opponent in this response.", 0, 2),
	FeatureDefinition("RNG_DEPENDENCE", FeatureFamily.UNCERTAINTY_RISK, "Dependence on favorable accuracy, survival rolls, or repeated probabilistic protection.", 0, 1),
	FeatureDefinition("MECHANIC_UNCERTAINTY", FeatureFamily.UNCERTAINTY_RISK, "Reliance on incompletely resolved or branch-sensitive mechanics.", 0, 1),
	FeatureDefinition("FRAGILE_PREDICTION", FeatureFamily.UNCERTAINTY_RISK, "Reserved for B9: sensitivity to one narrow opponent response prediction.", 0, 1),
	FeatureDefinition("JOINT_ACTION_COORDINATION", FeatureFamily.JOINT_ACTION_COORDINATION, "Complementary value created by the two allied actions within this response.", -1, 1),
	FeatureDefinition("ROBUST_ACROSS_RESPONSES", FeatureFamily.JOINT_ACTION_COORDINATION, "Reserved for B9: value retained across diverse credible opponent responses.", 0, 1),
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
