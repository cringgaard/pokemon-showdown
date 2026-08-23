from __future__ import annotations

import unittest

from test_b4_strategy import FakeMechanics, state_fixture
from deterministic_snow import build_knowledge_state
from deterministic_snow.config import PolicyConfig, default_config
from deterministic_snow.strategy import assess_runtime_strategy


class B4ConfigurationTests(unittest.TestCase):
	def test_strategy_weights_and_hp_curve_round_trip_strictly(self):
		config = default_config()
		self.assertEqual(PolicyConfig.from_json(config.to_json()), config)

		missing = config.to_dict()
		del missing["strategy"]["weights"]["GLACEON_SNOW"]
		with self.assertRaisesRegex(ValueError, "strategy.weights IDs"):
			PolicyConfig.from_dict(missing)

		bad_curve = config.to_dict()
		bad_curve["strategy"]["hp_utility_curve"] = [[0.0, 0.0], [0.5, 0.8], [0.4, 0.9], [1.0, 1.0]]
		with self.assertRaisesRegex(ValueError, "strictly increase"):
			PolicyConfig.from_dict(bad_curve)

	def test_runtime_plan_score_uses_configured_weight(self):
		mechanics = FakeMechanics()
		knowledge = build_knowledge_state(state_fixture(), mechanics)
		baseline_config = default_config()
		baseline = assess_runtime_strategy(knowledge, mechanics, config=baseline_config)

		modified = baseline_config.to_dict()
		modified["strategy"]["weights"]["GLACEON_SNOW"] = 0.0
		without_snow_bonus = assess_runtime_strategy(
			knowledge,
			mechanics,
			config=PolicyConfig.from_dict(modified),
		)
		self.assertGreater(baseline.scores.glaceon_fortress, without_snow_bonus.scores.glaceon_fortress)


if __name__ == "__main__":
	unittest.main()
