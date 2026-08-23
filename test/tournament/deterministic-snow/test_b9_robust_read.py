from __future__ import annotations

from dataclasses import replace
import unittest

from test_b7_projection import state_with
from test_b7_projection_hardening import HardenedProjectionMechanics
from test_b8_scoring import response, response_action, strategy_for

from deterministic_snow import build_knowledge_state
from deterministic_snow.aggregation import CandidateEvaluationInput, CandidateResponseCase, rank_candidates
from deterministic_snow.features import FEATURE_SCHEMA_VERSION, FEATURE_SET_VERSION
from deterministic_snow.projection import ProjectionResult
from deterministic_snow.responses import OpponentActionRole, OpponentResponseSet
from deterministic_snow.scoring import FeatureValue, ResponseUtilityEvaluation
from deterministic_snow.strategy import PlanLabel
from deterministic_snow.trace import FeatureContribution


class B9RobustReadTests(unittest.TestCase):
	def test_robust_read_beats_higher_upside_fragile_read(self):
		state = state_with("team_4", "team_5", 0, 1)
		state["request"] = {
			"kind": "turn",
			"slots": {},
			"legal_actions": [
				{"actions": {
					"left": {"type": "move", "move": "wideguard"},
					"right": {"type": "move", "move": "protect"},
				}},
				{"actions": {
					"left": {"type": "move", "move": "allyswitch"},
					"right": {"type": "move", "move": "protect"},
				}},
			],
		}
		knowledge = build_knowledge_state(state, HardenedProjectionMechanics())
		strategy = strategy_for(knowledge, PlanLabel.FLEXIBLE)
		first_response = replace(response(response_action(
			"left", "opponent_0", "protect", (OpponentActionRole.PROTECT,),
		)), weight=0.5)
		second_response = replace(response(response_action(
			"right", "opponent_1", "protect", (OpponentActionRole.PROTECT,),
		)), weight=0.5)
		response_set = OpponentResponseSet("b9-robust-read-test", (), (first_response, second_response))

		# This deliberately isolates B9's scalar aggregation from B8 feature
		# semantics. Both candidates use identical synthetic contribution structure;
		# only their response utility distributions differ.
		def utility(candidate_id, opponent_response, value):
			feature = FeatureValue("OPPONENT_DAMAGE", value)
			contribution = FeatureContribution("OPPONENT_DAMAGE", value, 1.0, value)
			return ResponseUtilityEvaluation(
				FEATURE_SCHEMA_VERSION,
				FEATURE_SET_VERSION,
				"b9-synthetic-utility",
				candidate_id,
				opponent_response.canonical_key,
				value,
				"HIGH",
				(feature,),
				(contribution,),
				(),
			)

		def candidate_input(candidate, values):
			cases = []
			for opponent_response, value in zip(response_set.responses, values):
				projection = ProjectionResult(
					"b9-synthetic-projection",
					candidate.action_id,
					opponent_response.canonical_key,
					(),
				)
				cases.append(CandidateResponseCase(
					opponent_response,
					projection,
					utility(candidate.action_id, opponent_response, value),
				))
			return CandidateEvaluationInput(candidate, tuple(cases))

		robust_candidate, fragile_candidate = knowledge.legal_actions
		ranking = rank_candidates(
			knowledge,
			strategy,
			response_set,
			(
				candidate_input(robust_candidate, (100.0, 40.0)),
				candidate_input(fragile_candidate, (150.0, -120.0)),
			),
		)
		robust = next(item for item in ranking.candidates if item.candidate.action_id == robust_candidate.action_id)
		fragile = next(item for item in ranking.candidates if item.candidate.action_id == fragile_candidate.action_id)

		self.assertLess(robust.best_case_utility, fragile.best_case_utility)
		self.assertGreater(robust.credible_bad_case_utility, fragile.credible_bad_case_utility)
		self.assertLess(robust.fragile_prediction, fragile.fragile_prediction)
		self.assertGreater(robust.robust_across_responses, fragile.robust_across_responses)
		self.assertGreater(robust.final_score, fragile.final_score)
		self.assertEqual(ranking.selected_action_id, robust_candidate.action_id)


if __name__ == "__main__":
	unittest.main()
