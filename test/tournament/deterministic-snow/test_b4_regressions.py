from __future__ import annotations

import unittest

from test_b4_strategy import FakeMechanics, active, event, health, state_fixture
from deterministic_snow import build_knowledge_state
from deterministic_snow.strategy import PlanLabel, assess_runtime_strategy
from deterministic_snow.threats import build_threat_model


class AnnotatedMechanics(FakeMechanics):
	def semantic(self, category, value):
		key = "".join(character.lower() for character in value if character.isalnum())
		if category == "moves" and key == "protect":
			return {"protection_move": True}
		if category == "abilities" and key == "filter":
			return {"super_effective_damage_multiplier": 0.75}
		if category == "abilities" and key == "friendguard":
			return {"ally_damage_multiplier": 0.75}
		if category == "abilities" and key == "flashfire":
			return {"fire_immunity": True}
		if category == "abilities" and key == "dryskin":
			return {"water_immunity_and_heal_fraction": 0.25, "fire_damage_multiplier": 1.25}
		if category == "items" and key == "chopleberry":
			return {"super_effective_type_damage_multiplier": {"Fighting": 0.5}}
		if category == "items" and key == "colburberry":
			return {"super_effective_type_damage_multiplier": {"Dark": 0.5}}
		return {}


class B4MechanicsRegressionTests(unittest.TestCase):
	def test_filter_annotation_reduces_super_effective_aggron_threat(self):
		state = state_fixture()
		plain = FakeMechanics()
		annotated = AnnotatedMechanics()
		plain_model = build_threat_model(build_knowledge_state(state, plain), plain)
		annotated_model = build_threat_model(build_knowledge_state(state, annotated), annotated)

		def aggron_close_combat(model):
			threat = next(item for item in model.move_threats if item.move == "closecombat")
			return next(item for item in threat.targets if item.target_id == "team_1")

		plain_target = aggron_close_combat(plain_model)
		annotated_target = aggron_close_combat(annotated_model)
		self.assertLess(annotated_target.estimated_fraction_mid, plain_target.estimated_fraction_mid)
		self.assertIn("ability_super_effective_modifier", annotated_target.estimate_source)

	def test_friend_guard_and_chople_compose_from_public_current_state(self):
		state = state_fixture()
		state["self"]["active"] = {"left": "team_3", "right": "team_1"}
		state["self"]["team"][1]["item"] = "chopleberry"
		mechanics = AnnotatedMechanics()
		model = build_threat_model(build_knowledge_state(state, mechanics), mechanics)
		close_combat = next(item for item in model.move_threats if item.move == "closecombat")
		aggron = next(item for item in close_combat.targets if item.target_id == "team_1")
		self.assertIn("ability_super_effective_modifier", aggron.estimate_source)
		self.assertIn("held_item_type_modifier", aggron.estimate_source)
		self.assertIn("ally_damage_modifier", aggron.estimate_source)

	def test_stale_fake_out_stays_known_but_is_not_current_pressure(self):
		state = state_fixture()
		state["battle"]["turn"] = 2
		state["history"].insert(0, event(0, "showteam", ["p2", "synthetic"]))
		state["history"].append(event(1, "turn", ["2"]))
		mechanics = AnnotatedMechanics()
		knowledge = build_knowledge_state(state, mechanics)
		model = build_threat_model(knowledge, mechanics)
		fake_out = next(item for item in model.move_threats if item.move == "fakeout")
		self.assertFalse(fake_out.currently_available)
		self.assertTrue(all(move != "fakeout" for slot in model.slot_threats for move in slot.likely_moves))

	def test_fainted_active_cannot_supply_tactical_spread_cleanup(self):
		state = state_fixture()
		state["opponent"]["active"]["left"]["health"] = health(30, 100, False)
		state["opponent"]["active"]["right"]["health"] = health(25, 100, False)
		state["self"]["team"][0]["health"] = health(0, 160)
		state["self"]["team"][0]["fainted"] = True
		mechanics = AnnotatedMechanics()
		assessment = assess_runtime_strategy(build_knowledge_state(state, mechanics), mechanics)
		tactical = next(plan for plan in assessment.plans if plan.plan is PlanLabel.TACTICAL_OFFENSE)
		self.assertNotIn("spread cleanup can cash out the position", tactical.positive_reasons)


if __name__ == "__main__":
	unittest.main()
