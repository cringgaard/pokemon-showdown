from __future__ import annotations

import copy
import unittest

from test_b7_projection import state_with
from test_b7_projection_hardening import HardenedProjectionMechanics
from test_b8_scoring import response, response_action, strategy_for

from deterministic_snow import build_knowledge_state
from deterministic_snow.aggregation import CandidateEvaluationInput, CandidateResponseCase, rank_candidates
from deterministic_snow.projection import project_turn
from deterministic_snow.responses import OpponentActionRole, OpponentResponseSet
from deterministic_snow.scoring import evaluate_response_utility
from deterministic_snow.strategy import PlanLabel


class B9RuleHardeningTests(unittest.TestCase):
	def setUp(self):
		self.mechanics = HardenedProjectionMechanics()

	def _evaluate(self, state, actions, opponent_response, primary=PlanLabel.FLEXIBLE):
		state = copy.deepcopy(state)
		state["request"] = {
			"kind": "turn",
			"slots": {},
			"legal_actions": [{"actions": actions}],
		}
		knowledge = build_knowledge_state(state, self.mechanics)
		strategy = strategy_for(knowledge, primary)
		candidate = knowledge.legal_actions[0]
		projection = project_turn(knowledge, self.mechanics, candidate, opponent_response)
		utility = evaluate_response_utility(
			knowledge, strategy, candidate, opponent_response, projection,
		)
		response_set = OpponentResponseSet("b9-rule-hardening", (), (opponent_response,))
		return rank_candidates(
			knowledge,
			strategy,
			response_set,
			(CandidateEvaluationInput(candidate, (
				CandidateResponseCase(opponent_response, projection, utility),
			)),),
		).candidates[0]

	def test_zero_effect_does_not_penalize_attack_that_is_only_blocked_by_protect(self):
		state = state_with("team_3", "team_5", 0, 1)
		opponent_response = response(response_action(
			"right", "opponent_1", "protect", (OpponentActionRole.PROTECT,),
		))
		result = self._evaluate(state, {
			"left": {"type": "move", "move": "bodypress", "target": "opponent_right"},
			"right": {"type": "move", "move": "protect"},
		}, opponent_response)
		self.assertFalse(any(item.rule_id == "ZERO_EFFECT" for item in result.tactical_adjustments))

	def test_failed_weather_rule_does_not_mislabel_fake_out_failure_while_snow_remains(self):
		state = state_with("team_1", "team_0", 0, 1)
		opponent_response = response(response_action(
			"right", "opponent_1", "fakeout", (OpponentActionRole.DAMAGE,), "left", "team_1",
		))
		result = self._evaluate(state, {
			"left": {"type": "move", "move": "auroraveil"},
			"right": {"type": "move", "move": "protect"},
		}, opponent_response, PlanLabel.GLACEON_FORTRESS)
		self.assertFalse(any(
			item.rule_id == "FAILED_WEATHER_DEPENDENT_MOVE"
			for item in result.tactical_adjustments
		))


if __name__ == "__main__":
	unittest.main()
