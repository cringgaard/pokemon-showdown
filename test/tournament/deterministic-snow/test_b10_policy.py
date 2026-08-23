from __future__ import annotations

import copy
from types import SimpleNamespace
import unittest

from test_b5_preview import FakeMechanics as PreviewMechanics, preview_state
from test_b6_responses import event, packed_sheet
from test_b7_projection import state_with
from test_b7_projection_hardening import HardenedProjectionMechanics

from deterministic_snow.policy import PolicyContractError, RuntimeMode, SnowPolicy
from deterministic_snow.preview import assess_team_preview
from deterministic_snow.reconstruction import build_knowledge_state
from deterministic_snow.trace import TraceLevel


class B10Mechanics(HardenedProjectionMechanics):
	format = SimpleNamespace(id="gen9championsvgc2026regmb", mod="champions")
	snapshot_hash = "sha256:b10-test-mechanics"

	def type_multiplier(self, attacking_type, defending_types):
		result = 1.0
		for defending in defending_types:
			result *= self._single(attacking_type, defending)
		return result


class B10PreviewMechanics(PreviewMechanics):
	format = SimpleNamespace(id="gen9championsvgc2026regmb", mod="champions")
	snapshot_hash = "sha256:b10-preview-test-mechanics"


class B10PolicyTests(unittest.TestCase):
	def setUp(self):
		self.mechanics = B10Mechanics()
		self.policy = SnowPolicy(self.mechanics, trace_level=TraceLevel.FULL)

	@staticmethod
	def _turn_state(actions, *, deadline_ms=4000):
		state = state_with("team_2", "team_3", 0, 1)
		state["runtime"]["deadline_ms"] = deadline_ms
		state["request"] = {
			"kind": "turn",
			"slots": {},
			"legal_actions": [{"actions": action} for action in actions],
		}
		return state

	def test_normal_turn_returns_exact_harness_legal_action_and_is_deterministic(self):
		state = self._turn_state([
			{
				"left": {"type": "move", "move": "followme"},
				"right": {"type": "move", "move": "bodypress", "target": "opponent_right", "transformation": "mega"},
			},
			{
				"left": {"type": "move", "move": "mudslap", "target": "opponent_left"},
				"right": {"type": "move", "move": "bodypress", "target": "opponent_right", "transformation": "mega"},
			},
		])
		first = self.policy.decide(copy.deepcopy(state))
		second = self.policy.decide(copy.deepcopy(state))
		self.assertEqual(first.response, second.response)
		self.assertEqual(first.action_id, second.action_id)
		self.assertIn(first.response, state["request"]["legal_actions"])
		self.assertEqual(first.phase, "turn")
		self.assertIs(first.runtime_mode, RuntimeMode.FULL)
		self.assertIsNotNone(first.trace)
		self.assertEqual(first.trace.selected_action_id, first.action_id)
		self.assertEqual(first.trace.runtime.candidate_count, 2)
		self.assertGreater(first.trace.runtime.response_count, 0)
		self.assertEqual(
			first.trace.runtime.evaluation_count,
			first.trace.runtime.candidate_count * first.trace.runtime.response_count,
		)

	def test_end_to_end_follow_me_rescue_beats_mud_slap_when_close_combat_focuses_aggron(self):
		state = self._turn_state([
			{
				"left": {"type": "move", "move": "followme"},
				"right": {"type": "move", "move": "bodypress", "target": "opponent_right", "transformation": "mega"},
			},
			{
				"left": {"type": "move", "move": "mudslap", "target": "opponent_left"},
				"right": {"type": "move", "move": "bodypress", "target": "opponent_right", "transformation": "mega"},
			},
		])
		# Isolate the Aggron-fortress route so FOLLOW_ME_RESCUE is expected to be
		# the primary-win-condition tactical adjustment rather than merely useful
		# generic redirection.
		state["self"]["team"][0]["health"] = {
			"current": 0, "max": 160, "exact": True, "percent": 0,
		}
		state["self"]["team"][0]["fainted"] = True
		state["opponent"]["team"][0]["moves"] = [{"id": "protect", "name": "Protect"}]
		state["opponent"]["team"][1]["moves"] = [{"id": "closecombat", "name": "Close Combat"}]
		state["history"][0] = event(0, "showteam", ["p2", packed_sheet(state["opponent"]["team"])])
		decision = self.policy.decide(state)
		self.assertEqual(decision.response["actions"]["left"]["move"], "followme")
		selected = next(item for item in decision.trace.candidates if item.action.action_id == decision.action_id)
		self.assertTrue(any(item.rule_id == "FOLLOW_ME_RESCUE" for item in selected.tactical_adjustments))

	def test_runtime_modes_reduce_response_budget_without_changing_legality(self):
		deadlines = (
			(1500, RuntimeMode.FULL, 8),
			(700, RuntimeMode.MEDIUM, 4),
			(300, RuntimeMode.LOW, 3),
			(100, RuntimeMode.EMERGENCY, 2),
		)
		for deadline, expected_mode, response_cap in deadlines:
			with self.subTest(deadline=deadline):
				state = self._turn_state([{
					"left": {"type": "move", "move": "followme"},
					"right": {"type": "move", "move": "protect", "transformation": "mega"},
				}], deadline_ms=deadline)
				decision = self.policy.decide(state)
				self.assertIs(decision.runtime_mode, expected_mode)
				self.assertIn(decision.response, state["request"]["legal_actions"])
				self.assertLessEqual(decision.trace.runtime.response_count, response_cap)

	def test_forced_switch_routes_outside_b6_and_prefers_weather_reset(self):
		state = state_with("team_0", "team_5", 0, 1)
		state["battle"]["phase"] = "forced_switch"
		state["field"]["weather"] = "raindance"
		state["self"]["team"][0]["health"] = {
			"current": 0, "max": 160, "exact": True, "percent": 0,
		}
		state["self"]["team"][0]["fainted"] = True
		# Remove matchup pressure from this regression: it is specifically about
		# the public weather-reset term, not Ninetales switching into Fire/Fighting.
		for index in (0, 1):
			state["opponent"]["team"][index]["moves"] = [{"id": "protect", "name": "Protect"}]
		state["history"][0] = event(0, "showteam", ["p2", packed_sheet(state["opponent"]["team"])])
		state["request"] = {
			"kind": "forced_switch",
			"slots": {},
			"legal_actions": [
				{"actions": {"left": {"type": "switch", "pokemon": "team_1"}}},
				{"actions": {"left": {"type": "switch", "pokemon": "team_4"}}},
			],
		}
		decision = self.policy.decide(state)
		self.assertEqual(decision.phase, "forced_switch")
		self.assertEqual(decision.response, {"actions": {"left": {"type": "switch", "pokemon": "team_1"}}})
		self.assertEqual(decision.trace.runtime.response_count, 0)
		self.assertEqual(decision.trace.selected_action_id, decision.action_id)

	def test_team_preview_routes_to_b5_and_returns_same_selected_order(self):
		state = preview_state()
		mechanics = B10PreviewMechanics()
		policy = SnowPolicy(mechanics, trace_level=TraceLevel.NONE)
		knowledge = build_knowledge_state(state, mechanics)
		expected = assess_team_preview(knowledge, mechanics).selected.action.payload["team"]
		decision = policy.decide(copy.deepcopy(state))
		self.assertEqual(decision.phase, "team_preview")
		self.assertEqual(decision.response, {"team": expected})
		self.assertIn(decision.response, state["request"]["legal_actions"])

	def test_invalid_schema_format_and_empty_legal_actions_fail_closed(self):
		state = self._turn_state([{
			"left": {"type": "move", "move": "protect"},
			"right": {"type": "move", "move": "protect", "transformation": "mega"},
		}])
		bad_schema = copy.deepcopy(state)
		bad_schema["schema_version"] = 1
		with self.assertRaises(PolicyContractError):
			self.policy.decide(bad_schema)
		bad_format = copy.deepcopy(state)
		bad_format["battle"]["format"] = "gen9doublesou"
		with self.assertRaises(PolicyContractError):
			self.policy.decide(bad_format)
		empty = copy.deepcopy(state)
		empty["request"]["legal_actions"] = []
		with self.assertRaises(PolicyContractError):
			self.policy.decide(empty)


if __name__ == "__main__":
	unittest.main()
