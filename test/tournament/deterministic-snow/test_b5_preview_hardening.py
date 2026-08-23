from __future__ import annotations

import copy
import unittest

from test_b5_preview import FakeMechanics, FakeMove, event, packed_sheet, preview_state

from deterministic_snow import build_knowledge_state
from deterministic_snow.preview import OpponentTag, PreviewContractError, assess_team_preview, build_opponent_roster_profile


class HardenedMechanics(FakeMechanics):
	MOVES = dict(FakeMechanics.MOVES)
	MOVES.update({
		"grassknot": FakeMove("grassknot", "Grass", "Special", 0),
		"heavyslam": FakeMove("heavyslam", "Steel", "Physical", 0),
		"ironhead": FakeMove("ironhead", "Steel", "Physical", 80),
	})

	def semantic(self, category, value):
		key = "".join(character.lower() for character in value if character.isalnum())
		if category == "moves" and key == "grassknot":
			return {"weight_based_power": True}
		if category == "moves" and key == "heavyslam":
			return {"weight_ratio_power": True}
		return super().semantic(category, value)

	def _single(self, move_id, attacking, defending):
		if attacking == "Steel" and defending in ("Ice", "Rock", "Fairy"):
			return 2.0
		return super()._single(move_id, attacking, defending)


class B5PreviewHardeningTests(unittest.TestCase):
	def setUp(self):
		self.mechanics = HardenedMechanics()

	def knowledge(self, state):
		return build_knowledge_state(state, self.mechanics)

	def test_explicit_showteam_event_is_required_for_ots_preview(self):
		state = preview_state()
		state["history"] = []
		with self.assertRaises(PreviewContractError):
			assess_team_preview(self.knowledge(state), self.mechanics)

	def test_weight_based_zero_base_power_moves_still_count_as_attacks(self):
		state = preview_state()
		# The real B2 snapshot exposes both of these with static base_power == 0
		# plus explicit weight-based semantic annotations.
		for pokemon in state["self"]["team"]:
			if pokemon["species"] == "Heliolisk":
				pokemon["moves"] = [{"id": "grassknot", "name": "Grass Knot"}]
			if pokemon["species"] == "Aggron":
				pokemon["moves"] = [{"id": "heavyslam", "name": "Heavy Slam"}]
		assessment = assess_team_preview(self.knowledge(state), self.mechanics)
		with_both = next(candidate for candidate in assessment.candidates if candidate.team == (
			"team_3", "team_5", "team_1", "team_2",
		))
		self.assertGreater(with_both.plans.tactical_offense, 0)
		# Grass Knot is super-effective into the submitted Water targets and must
		# participate in preview coverage despite having no static base power.
		self.assertGreater(with_both.coverage, 0)

	def test_steel_pressure_is_publicly_tagged_and_reduces_glaceon_viability(self):
		base_state = preview_state()
		base = assess_team_preview(self.knowledge(copy.deepcopy(base_state)), self.mechanics)

		steel_state = preview_state()
		# Amoonguss is not otherwise a Fire/Fighting/Rock/Steel pressure source in
		# the base fixture, so adding Iron Head creates one additional dangerous
		# Glaceon matchup instead of merely replacing one dangerous type with another.
		steel_state["opponent"]["team"][5]["moves"] = [
			{"id": "ragepowder", "name": "Rage Powder"},
			{"id": "spore", "name": "Spore"},
			{"id": "ironhead", "name": "Iron Head"},
			{"id": "protect", "name": "Protect"},
		]
		steel_state["history"] = [event("showteam", ["p2", packed_sheet(steel_state["opponent"]["team"])])]
		steel_knowledge = self.knowledge(steel_state)
		profile = build_opponent_roster_profile(steel_knowledge, self.mechanics)
		amoonguss = next(pokemon for pokemon in profile.pokemon if pokemon.species == "Amoonguss")
		self.assertIn(OpponentTag.STEEL_PRESSURE, amoonguss.tags)

		steel = assess_team_preview(steel_knowledge, self.mechanics)
		team = ("team_0", "team_1", "team_2", "team_4")
		base_candidate = next(candidate for candidate in base.candidates if candidate.team == team)
		steel_candidate = next(candidate for candidate in steel.candidates if candidate.team == team)
		self.assertGreater(base_candidate.plans.glaceon_fortress, steel_candidate.plans.glaceon_fortress)

	def test_lead_hypothesis_selection_is_repeatable(self):
		state = preview_state()
		first = assess_team_preview(self.knowledge(copy.deepcopy(state)), self.mechanics)
		second = assess_team_preview(self.knowledge(copy.deepcopy(state)), self.mechanics)
		self.assertEqual(first.lead_hypotheses, second.lead_hypotheses)


if __name__ == "__main__":
	unittest.main()
