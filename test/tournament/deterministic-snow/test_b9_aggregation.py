from __future__ import annotations

import copy
from dataclasses import replace
import unittest

from test_b7_projection import (
	move_response,
	state_with,
	switch_response,
)
from test_b7_projection_hardening import HardenedProjectionMechanics
from test_b8_scoring import response, response_action, strategy_for

from deterministic_snow import build_knowledge_state
from deterministic_snow.aggregation import (
	AggregationContractError,
	CandidateEvaluationInput,
	CandidateResponseCase,
	default_aggregation_config,
	rank_candidates,
)
from deterministic_snow.projection import project_turn
from deterministic_snow.responses import (
	OpponentActionRole,
	OpponentResponseSet,
)
from deterministic_snow.scoring import evaluate_response_utility
from deterministic_snow.strategy import PlanLabel


class B9AggregationTests(unittest.TestCase):
	def setUp(self):
		self.mechanics = HardenedProjectionMechanics()

	def _problem(self, state, action_payloads, responses, primary=PlanLabel.FLEXIBLE):
		state = copy.deepcopy(state)
		state["request"] = {
			"kind": "turn",
			"slots": {},
			"legal_actions": [{"actions": actions} for actions in action_payloads],
		}
		knowledge = build_knowledge_state(state, self.mechanics)
		strategy = strategy_for(knowledge, primary)
		response_set = OpponentResponseSet("b9-test-responses", (), tuple(responses))
		candidate_inputs = []
		for candidate in knowledge.legal_actions:
			cases = []
			for opponent_response in responses:
				projection = project_turn(knowledge, self.mechanics, candidate, opponent_response)
				utility = evaluate_response_utility(
					knowledge, strategy, candidate, opponent_response, projection,
				)
				cases.append(CandidateResponseCase(opponent_response, projection, utility))
			candidate_inputs.append(CandidateEvaluationInput(candidate, tuple(cases)))
		return knowledge, strategy, response_set, tuple(candidate_inputs)

	@staticmethod
	def _candidate_with_move(ranking, move):
		for candidate in ranking.candidates:
			if any(
				action and action.get("type") == "move" and action.get("move") == move
				for action in candidate.candidate.payload["actions"].values()
			):
				return candidate
		raise AssertionError(f"candidate using {move!r} not found")

	def test_expected_bad_case_variance_and_cross_response_features_are_exact(self):
		state = state_with("team_0", "team_5", 0, 1)
		common = replace(response(response_action(
			"right", "opponent_1", "protect", (OpponentActionRole.PROTECT,),
		)), weight=0.90)
		rare_lethal = replace(response(response_action(
			"right", "opponent_1", "closecombat", (OpponentActionRole.DAMAGE,), "left", "team_0",
		)), weight=0.10)
		knowledge, strategy, response_set, candidates = self._problem(
			state,
			[{
				"left": {"type": "move", "move": "calmmind"},
				"right": {"type": "move", "move": "protect"},
			}],
			(common, rare_lethal),
			PlanLabel.GLACEON_FORTRESS,
		)
		config = default_aggregation_config()
		ranking = rank_candidates(knowledge, strategy, response_set, candidates, config=config)
		result = ranking.candidates[0]
		utilities = [case.utility.utility for case in candidates[0].cases]
		expected = 0.90 * utilities[0] + 0.10 * utilities[1]
		variance = 0.90 * (utilities[0] - expected) ** 2 + 0.10 * (utilities[1] - expected) ** 2
		self.assertAlmostEqual(result.expected_utility, expected, places=7)
		self.assertAlmostEqual(result.variance, variance, places=7)
		self.assertAlmostEqual(result.standard_deviation, variance ** 0.5, places=7)
		# 0.10 / 0.90 < the central 0.15 relative credibility threshold.
		self.assertEqual(result.credible_response_ids, (common.canonical_key,))
		self.assertAlmostEqual(result.credible_bad_case_utility, utilities[0], places=7)
		self.assertAlmostEqual(
			result.fragile_prediction,
			min(1.0, (variance ** 0.5) / config.utility_spread_scale),
			places=7,
		)
		self.assertEqual(result.robust_across_responses, 1.0)
		by_id = {item.feature_id: item for item in result.feature_contributions}
		self.assertIn("FRAGILE_PREDICTION", by_id)
		self.assertIn("ROBUST_ACROSS_RESPONSES", by_id)
		self.assertAlmostEqual(sum(item.contribution for item in result.feature_contributions), result.base_score, places=7)

	def test_follow_me_rescue_gets_post_projection_adjustment_and_ranks_first(self):
		state = state_with("team_2", "team_3", 0, 1)
		focus = response(response_action(
			"right", "opponent_1", "closecombat", (OpponentActionRole.DAMAGE,), "right", "team_3",
		))
		common_right = {
			"type": "move", "move": "bodypress", "target": "opponent_right", "transformation": "mega",
		}
		knowledge, strategy, response_set, candidates = self._problem(
			state,
			[
				{"left": {"type": "move", "move": "followme"}, "right": common_right},
				{
					"left": {"type": "move", "move": "mudslap", "target": "opponent_left"},
					"right": common_right,
				},
			],
			(focus,),
			PlanLabel.AGGRON_FORTRESS,
		)
		ranking = rank_candidates(knowledge, strategy, response_set, candidates)
		rescue = self._candidate_with_move(ranking, "followme")
		self.assertTrue(any(item.rule_id == "FOLLOW_ME_RESCUE" and item.adjustment > 0 for item in rescue.tactical_adjustments))
		self.assertEqual(ranking.selected_action_id, rescue.candidate.action_id)

	def test_weather_reset_penalizes_failed_aurora_veil_after_projection(self):
		state = state_with("team_1", "team_0", 1, 0)
		weather_reset = response(
			switch_response("left", "opponent_1", "opponent_3"),
			response_action("right", "opponent_0", "protect", (OpponentActionRole.PROTECT,)),
		)
		knowledge, strategy, response_set, candidates = self._problem(
			state,
			[
				{
					"left": {"type": "move", "move": "auroraveil"},
					"right": {"type": "move", "move": "protect"},
				},
				{
					"left": {"type": "move", "move": "freezedry", "target": "opponent_left"},
					"right": {"type": "move", "move": "protect"},
				},
			],
			(weather_reset,),
			PlanLabel.GLACEON_FORTRESS,
		)
		ranking = rank_candidates(knowledge, strategy, response_set, candidates)
		veil = self._candidate_with_move(ranking, "auroraveil")
		self.assertTrue(any(
			item.rule_id == "FAILED_WEATHER_DEPENDENT_MOVE" and item.adjustment < 0
			for item in veil.tactical_adjustments
		))

	def test_mud_slap_into_public_defiant_receives_ability_punishment(self):
		state = state_with("team_2", "team_3", 0, 1)
		state["opponent"]["team"][0]["ability"] = "defiant"
		state["opponent"]["active"]["left"]["ability"] = "defiant"
		passive = response(response_action(
			"right", "opponent_1", "protect", (OpponentActionRole.PROTECT,),
		))
		knowledge, strategy, response_set, candidates = self._problem(
			state,
			[{
				"left": {"type": "move", "move": "mudslap", "target": "opponent_left"},
				"right": {"type": "move", "move": "protect", "transformation": "mega"},
			}],
			(passive,),
			PlanLabel.AGGRON_FORTRESS,
		)
		ranking = rank_candidates(knowledge, strategy, response_set, candidates)
		self.assertTrue(any(
			item.rule_id == "ABILITY_PUNISHMENT" and item.adjustment < 0
			for item in ranking.candidates[0].tactical_adjustments
		))

	def test_base_aggron_danger_only_applies_when_mega_is_a_legal_alternative(self):
		state = state_with("team_3", "team_5", 0, 1)
		state["self"]["team"][3]["health"] = {
			"current": 80, "max": 100, "exact": True, "percent": 80,
		}
		lethal = response(response_action(
			"right", "opponent_1", "closecombat", (OpponentActionRole.DAMAGE,), "left", "team_3",
		))
		base_action = {
			"left": {"type": "move", "move": "bodypress", "target": "opponent_right"},
			"right": {"type": "move", "move": "protect"},
		}
		mega_action = copy.deepcopy(base_action)
		mega_action["left"]["transformation"] = "mega"
		knowledge, strategy, response_set, candidates = self._problem(
			state, (base_action, mega_action), (lethal,), PlanLabel.AGGRON_FORTRESS,
		)
		ranking = rank_candidates(knowledge, strategy, response_set, candidates)
		base = next(
			item for item in ranking.candidates
			if item.candidate.payload["actions"]["left"].get("transformation") is None
		)
		self.assertTrue(any(
			item.rule_id == "BASE_AGGRON_DANGER" and item.adjustment < 0
			for item in base.tactical_adjustments
		))

	def test_all_candidates_must_cover_the_same_response_set(self):
		state = state_with("team_0", "team_5", 0, 1)
		first = replace(response(response_action(
			"right", "opponent_1", "protect", (OpponentActionRole.PROTECT,),
		)), weight=0.7)
		second = replace(response(response_action(
			"right", "opponent_1", "closecombat", (OpponentActionRole.DAMAGE,), "left", "team_0",
		)), weight=0.3)
		knowledge, strategy, response_set, candidates = self._problem(
			state,
			[{
				"left": {"type": "move", "move": "protect"},
				"right": {"type": "move", "move": "protect"},
			}],
			(first, second),
			PlanLabel.GLACEON_FORTRESS,
		)
		broken = (CandidateEvaluationInput(candidates[0].candidate, candidates[0].cases[:1]),)
		with self.assertRaisesRegex(AggregationContractError, "exactly the B6 response set"):
			rank_candidates(knowledge, strategy, response_set, broken)

	def test_ranking_and_trace_conversion_are_deterministic(self):
		state = state_with("team_4", "team_5", 0, 3)
		spread = response(response_action(
			"left", "opponent_0", "heatwave", (OpponentActionRole.DAMAGE, OpponentActionRole.SPREAD),
		))
		knowledge, strategy, response_set, candidates = self._problem(
			state,
			[
				{
					"left": {"type": "move", "move": "wideguard"},
					"right": {"type": "move", "move": "thunderbolt", "target": "opponent_right"},
				},
				{
					"left": {"type": "move", "move": "allyswitch"},
					"right": {"type": "move", "move": "thunderbolt", "target": "opponent_right"},
				},
			],
			(spread,),
		)
		first = rank_candidates(knowledge, strategy, response_set, candidates)
		second = rank_candidates(knowledge, strategy, response_set, candidates)
		self.assertEqual(first, second)
		self.assertEqual(first.selected_action_id, first.candidates[0].candidate.action_id)
		traces = first.candidate_traces()
		self.assertEqual([trace.action.action_id for trace in traces], [item.candidate.action_id for item in first.candidates])
		self.assertEqual(traces[0].final_score, first.candidates[0].final_score)


if __name__ == "__main__":
	unittest.main()
