from __future__ import annotations

from dataclasses import replace
import unittest

from test_b7_projection import ProjectionMechanics, joint, make_candidate, move_response, state_with

from deterministic_snow.projection import ProjectionUncertainty, project_turn


class HardenedProjectionMechanics(ProjectionMechanics):
	MOVES = dict(ProjectionMechanics.MOVES)
	MOVES["blizzard"] = replace(ProjectionMechanics.MOVES["blizzard"], accuracy=70)
	# Make the submitted Close Combat unambiguously lethal in the synthetic
	# projection fixture so this regression tests survival, not damage calibration.
	MOVES["closecombat"] = replace(ProjectionMechanics.MOVES["closecombat"], base_power=1000)

	def semantic(self, category, value):
		result = dict(super().semantic(category, value))
		key = self._id(str(value))
		if category == "abilities" and key == "lightningrod":
			result["spa_boost_on_redirect"] = 1
		if category == "abilities" and key == "sturdy":
			result["survive_full_hp_lethal_hit"] = True
		return result


class B7ProjectionHardeningTests(unittest.TestCase):
	def setUp(self):
		self.mechanics = HardenedProjectionMechanics()

	def test_lightning_rod_redirects_absorbs_and_boosts(self):
		state = state_with("team_5", "team_2", 3, 4)
		knowledge, candidate = make_candidate(state, {
			"left": {"type": "move", "move": "thunderbolt", "target": "opponent_left"},
			"right": {"type": "move", "move": "protect"},
		}, self.mechanics)
		result = project_turn(knowledge, self.mechanics, candidate, joint(
			move_response("left", "opponent_3", "heatwave")
		))
		for outcome in result.outcomes:
			record = next(record for record in outcome.action_records if record.action == "thunderbolt")
			self.assertEqual(record.original_target_id, "opponent_3")
			self.assertEqual(record.final_target_id, "opponent_4")
			self.assertTrue(record.redirected)
			damage = [change for change in outcome.opponent_hp_changes if change.pokemon_id == "opponent_4"]
			self.assertTrue(damage)
			self.assertEqual(damage[0].high_fraction, 0.0)
			self.assertTrue(any(
				change.pokemon_id == "opponent_4" and change.stat == "spa" and change.stages == 1
				for change in outcome.boost_changes
			))

	def test_public_snow_alias_grants_blizzard_perfect_accuracy(self):
		state = state_with("team_0", "team_2", 0, 1)
		state["field"]["weather"] = "snow"
		knowledge, candidate = make_candidate(state, {
			"left": {"type": "move", "move": "blizzard"},
			"right": {"type": "move", "move": "protect"},
		}, self.mechanics)
		result = project_turn(knowledge, self.mechanics, candidate, joint(
			move_response("right", "opponent_1", "protect")
		))
		for outcome in result.outcomes:
			blizzards = [record for record in outcome.action_records if record.action == "blizzard"]
			self.assertTrue(blizzards)
			self.assertTrue(all(record.hit_probability == 1.0 for record in blizzards))

	def test_full_hp_base_aggron_sturdy_survives_projected_lethal_move(self):
		state = state_with("team_3", "team_5", 0, 1)
		knowledge, candidate = make_candidate(state, {
			"left": {"type": "move", "move": "bodypress", "target": "opponent_right"},
			"right": {"type": "move", "move": "protect"},
		}, self.mechanics)
		result = project_turn(knowledge, self.mechanics, candidate, joint(
			move_response("right", "opponent_1", "closecombat", "left", "team_3")
		))
		for outcome in result.outcomes:
			self.assertNotIn("team_3", outcome.own_faints)
			self.assertIn(ProjectionUncertainty.SURVIVAL, outcome.uncertain_interactions)
			self.assertTrue(any("sturdy" in effect.lower() for effect in outcome.unresolved_random_effects))


if __name__ == "__main__":
	unittest.main()
