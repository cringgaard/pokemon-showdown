from __future__ import annotations

import copy
from dataclasses import replace
import unittest

from test_b10_policy import B10Mechanics
from test_b6_responses import event, packed_sheet
from test_b7_projection import ProjectionMove, hp, state_with, switch_response
from test_b8_scoring import response, response_action

from deterministic_snow import build_knowledge_state
from deterministic_snow.aggregation import (
	CandidateEvaluationInput,
	CandidateResponseCase,
	rank_candidates,
)
from deterministic_snow.projection import project_turn
from deterministic_snow.responses import OpponentActionRole, OpponentResponseSet
from deterministic_snow.scoring import evaluate_response_utility
from deterministic_snow.strategy import assess_runtime_strategy
from deterministic_snow.threats import build_threat_model


HISTORICAL_REGRESSION_VERSION = "b11-historical-v1"


class B11Mechanics(B10Mechanics):
	"""Synthetic mechanics broad enough for the historical current-team positions.

	The lower B2/B7 suites pin the actual Showdown mechanics. These additions only
	let the historical policy regressions express current-team moves that were not
	needed by the older projection fixture.
	"""

	MOVES = dict(B10Mechanics.MOVES)
	MOVES.update({
		"closecombat": replace(B10Mechanics.MOVES["closecombat"], base_power=120),
		"freezedry": ProjectionMove("freezedry", "Ice", "Special", 70),
		"hydropump": ProjectionMove("hydropump", "Water", "Special", 110, accuracy=80),
		"tailwind": ProjectionMove("tailwind", "Flying", "Status", 0, target="allySide", side_condition="tailwind"),
		"armorcannon": ProjectionMove(
			"armorcannon", "Fire", "Special", 120, target="normal",
			self_boosts=(("def", -1), ("spd", -1)),
		),
		"psychic": ProjectionMove("psychic", "Psychic", "Special", 90),
	})

	def move_multiplier(self, move, defending_types):
		move = self.move(move) if isinstance(move, str) else move
		if move.id != "freezedry":
			return super().move_multiplier(move, defending_types)
		result = 1.0
		for defending in defending_types:
			if self._id(defending) == "water":
				result *= 2.0
			else:
				result *= self._single(move.type, defending)
		return result


def current_team_state(own_left, own_right, opponent_left=0, opponent_right=1):
	"""Return the established B7 state with the checked-in current-six moves."""
	state = state_with(own_left, own_right, opponent_left, opponent_right)
	state["self"]["team"][1]["moves"] = [
		{"id": move, "name": move}
		for move in ("auroraveil", "freezedry", "encore", "protect")
	]
	state["self"]["team"][4]["moves"] = [
		{"id": move, "name": move}
		for move in ("wideguard", "allyswitch", "armorcannon", "psychic")
	]
	return state


def with_fresh_incineroar(state):
	"""Give the inherited turn-3 fixture a real public Incineroar re-entry.

	The base fixture starts Incineroar on the field and therefore correctly marks
	its Fake Out stale by turn 3. Historical forks that require fresh Fake Out
	must show it leaving on turn 1 and re-entering on turn 2 before the public
	`|turn|3` boundary; manually supplying an impossible Fake Out response would
	make a false-green policy regression.
	"""
	state = copy.deepcopy(state)
	history = state["history"]
	turn_two = next(
		index for index, item in enumerate(history)
		if item["type"] == "turn" and item["data"]["args"] == ["2"]
	)
	history.insert(turn_two, event(1, "switch", ["p2a: Gengar", "Gengar, L50", "100/100"]))
	turn_three = next(
		index for index, item in enumerate(history)
		if item["type"] == "turn" and item["data"]["args"] == ["3"]
	)
	history.insert(turn_three, event(2, "switch", ["p2a: Incineroar", "Incineroar, L50", "100/100"]))
	return state


def historical_ranking(state, legal_actions, opponent_responses, mechanics):
	"""Run the real B3/B4/B7/B8/B9 stack over one historical decision fork."""
	state = copy.deepcopy(state)
	state["request"] = {
		"kind": "turn",
		"slots": {},
		"legal_actions": [{"actions": actions} for actions in legal_actions],
	}
	knowledge = build_knowledge_state(state, mechanics)
	threats = build_threat_model(knowledge, mechanics)
	strategy = assess_runtime_strategy(knowledge, mechanics, threats=threats)
	response_set = OpponentResponseSet(
		HISTORICAL_REGRESSION_VERSION,
		(),
		tuple(opponent_responses),
	)
	candidate_inputs = []
	for candidate in knowledge.legal_actions:
		cases = []
		for opponent_response in response_set.responses:
			projection = project_turn(knowledge, mechanics, candidate, opponent_response)
			utility = evaluate_response_utility(
				knowledge,
				strategy,
				candidate,
				opponent_response,
				projection,
			)
			cases.append(CandidateResponseCase(opponent_response, projection, utility))
		candidate_inputs.append(CandidateEvaluationInput(candidate, tuple(cases)))
	return knowledge, strategy, rank_candidates(
		knowledge,
		strategy,
		response_set,
		tuple(candidate_inputs),
	)


def candidate_with_move(ranking, position, move):
	for candidate in ranking.candidates:
		action = candidate.candidate.payload["actions"].get(position)
		if action and action.get("type") == "move" and action.get("move") == move:
			return candidate
	raise AssertionError(f"candidate with {position} {move!r} not found")


def candidate_with_switch(ranking, position, pokemon_id):
	for candidate in ranking.candidates:
		action = candidate.candidate.payload["actions"].get(position)
		if action and action.get("type") == "switch" and action.get("pokemon") == pokemon_id:
			return candidate
	raise AssertionError(f"candidate switching {position} to {pokemon_id!r} not found")


def feature_value(candidate, feature_id):
	return next(item.value for item in candidate.feature_contributions if item.feature_id == feature_id)


def fake_out_is_fresh(knowledge, position="left"):
	entry = next(item for item in knowledge.fake_out_eligibility if item.position == position)
	return entry.known_fake_out is True and entry.eligible is True


class B11HistoricalRegressionTests(unittest.TestCase):
	def setUp(self):
		self.mechanics = B11Mechanics()

	def test_p0_03_fake_out_before_follow_me_makes_double_protect_safer(self):
		state = with_fresh_incineroar(current_team_state("team_2", "team_3", 0, 1))
		follow_body_press = {
			"left": {"type": "move", "move": "followme"},
			"right": {
				"type": "move", "move": "bodypress", "target": "opponent_right",
				"transformation": "mega",
			},
		}
		double_protect = {
			"left": {"type": "move", "move": "protect"},
			"right": {"type": "move", "move": "protect", "transformation": "mega"},
		}
		fresh_fake_out_focus = response(
			response_action(
				"left", "opponent_0", "fakeout", (OpponentActionRole.DAMAGE,), "left", "team_2",
			),
			response_action(
				"right", "opponent_1", "closecombat", (OpponentActionRole.DAMAGE,), "right", "team_3",
			),
		)
		knowledge, _, ranking = historical_ranking(
			state, (follow_body_press, double_protect), (fresh_fake_out_focus,), self.mechanics,
		)
		self.assertTrue(fake_out_is_fresh(knowledge))
		protected = candidate_with_move(ranking, "left", "protect")
		follow = candidate_with_move(ranking, "left", "followme")
		self.assertGreater(protected.final_score, follow.final_score)
		self.assertEqual(ranking.selected_action_id, protected.candidate.action_id)

	def test_p0_04_established_glaceon_protects_instead_of_over_setting_up(self):
		state = current_team_state("team_0", "team_5", 0, 1)
		state["self"]["team"][0]["boosts"]["spa"] = 2
		state["self"]["team"][0]["boosts"]["spd"] = 2
		state["self"]["team"][0]["health"] = hp(80, 160)
		state["self"]["team"][3]["health"] = hp(0, 160)
		state["self"]["team"][3]["fainted"] = True
		partner = {"type": "move", "move": "thunderbolt", "target": "opponent_left"}
		protect = {"left": {"type": "move", "move": "protect"}, "right": partner}
		greedy_setup = {"left": {"type": "move", "move": "calmmind"}, "right": partner}
		lethal_focus = response(response_action(
			"right", "opponent_1", "closecombat", (OpponentActionRole.DAMAGE,), "left", "team_0",
		))
		_, _, ranking = historical_ranking(
			state, (protect, greedy_setup), (lethal_focus,), self.mechanics,
		)
		protected = candidate_with_move(ranking, "left", "protect")
		greedy = candidate_with_move(ranking, "left", "calmmind")
		self.assertGreater(protected.final_score, greedy.final_score)
		self.assertEqual(ranking.selected_action_id, protected.candidate.action_id)

	def test_p0_05_boosted_glaceon_cashes_out_blizzard_on_two_low_targets(self):
		state = with_fresh_incineroar(current_team_state("team_0", "team_2", 0, 1))
		state["self"]["team"][0]["boosts"]["spa"] = 2
		state["self"]["team"][0]["boosts"]["spd"] = 2
		state["self"]["team"][3]["health"] = hp(0, 160)
		state["self"]["team"][3]["fainted"] = True
		for position in ("left", "right"):
			state["opponent"]["active"][position]["health"] = hp(10, 100)
		partner_protect = {"type": "move", "move": "protect"}
		blizzard = {"left": {"type": "move", "move": "blizzard"}, "right": partner_protect}
		calm_mind = {"left": {"type": "move", "move": "calmmind"}, "right": partner_protect}
		wish = {"left": {"type": "move", "move": "wish"}, "right": partner_protect}
		free_turn = response(
			response_action(
				"left", "opponent_0", "fakeout", (OpponentActionRole.DAMAGE,), "right", "team_2",
			),
			response_action(
				"right", "opponent_1", "closecombat", (OpponentActionRole.DAMAGE,), "right", "team_2",
			),
		)
		knowledge, _, ranking = historical_ranking(
			state, (blizzard, calm_mind, wish), (free_turn,), self.mechanics,
		)
		self.assertTrue(fake_out_is_fresh(knowledge))
		cash_out = candidate_with_move(ranking, "left", "blizzard")
		setup = candidate_with_move(ranking, "left", "calmmind")
		self.assertGreater(feature_value(cash_out, "OPPONENT_KO"), feature_value(setup, "OPPONENT_KO"))
		self.assertGreater(cash_out.final_score, setup.final_score)
		self.assertEqual(ranking.selected_action_id, cash_out.candidate.action_id)

	def test_p0_07_freeze_dry_punishes_pelipper_weather_reset_instead_of_failed_veil(self):
		state = current_team_state("team_1", "team_3", 1, 0)
		common_right = {"type": "move", "move": "protect", "transformation": "mega"}
		freeze_dry = {
			"left": {"type": "move", "move": "freezedry", "target": "opponent_left"},
			"right": common_right,
		}
		veil = {"left": {"type": "move", "move": "auroraveil"}, "right": common_right}
		weather_reset = response(
			switch_response("left", "opponent_1", "opponent_3"),
			response_action("right", "opponent_0", "protect", (OpponentActionRole.PROTECT,)),
		)
		_, _, ranking = historical_ranking(
			state, (freeze_dry, veil), (weather_reset,), self.mechanics,
		)
		coverage = candidate_with_move(ranking, "left", "freezedry")
		failed_veil = candidate_with_move(ranking, "left", "auroraveil")
		self.assertGreater(coverage.final_score, failed_veil.final_score)
		self.assertEqual(ranking.selected_action_id, coverage.candidate.action_id)
		self.assertTrue(any(
			item.rule_id == "FAILED_WEATHER_DEPENDENT_MOVE" and item.adjustment < 0
			for item in failed_veil.tactical_adjustments
		))

	def test_p0_10_known_stat_drop_punishing_abilities_make_mud_slap_lose(self):
		for ability in ("defiant", "competitive", "contrary"):
			with self.subTest(ability=ability):
				state = current_team_state("team_2", "team_3", 0, 1)
				state["opponent"]["team"][0]["ability"] = ability
				state["opponent"]["active"]["left"]["ability"] = ability
				state["history"][0] = event(
					0, "showteam", ["p2", packed_sheet(state["opponent"]["team"])],
				)
				common_right = {
					"type": "move", "move": "bodypress", "target": "opponent_right",
					"transformation": "mega",
				}
				mud_slap = {
					"left": {"type": "move", "move": "mudslap", "target": "opponent_left"},
					"right": common_right,
				}
				conservative = {"left": {"type": "move", "move": "protect"}, "right": common_right}
				passive = response(response_action(
					"right", "opponent_1", "protect", (OpponentActionRole.PROTECT,),
				))
				_, _, ranking = historical_ranking(
					state, (mud_slap, conservative), (passive,), self.mechanics,
				)
				punished = candidate_with_move(ranking, "left", "mudslap")
				safe = candidate_with_move(ranking, "left", "protect")
				self.assertTrue(any(
					item.rule_id == "ABILITY_PUNISHMENT" and item.adjustment < 0
					for item in punished.tactical_adjustments
				))
				self.assertGreater(safe.final_score, punished.final_score)
				self.assertEqual(ranking.selected_action_id, safe.candidate.action_id)

	def test_p1_05_one_hp_heliolisk_is_worth_protecting_as_a_future_pivot(self):
		state = with_fresh_incineroar(current_team_state("team_5", "team_3", 0, 1))
		state["self"]["team"][5]["health"] = hp(1, 160)
		state["self"]["team"][5]["item"] = None
		state["opponent"]["active"]["right"]["health"] = hp(15, 100)
		common_right = {
			"type": "move", "move": "bodypress", "target": "opponent_right",
			"transformation": "mega",
		}
		preserve = {"left": {"type": "move", "move": "protect"}, "right": common_right}
		throw_away = {
			"left": {"type": "move", "move": "thunderbolt", "target": "opponent_left"},
			"right": common_right,
		}
		double_target = response(
			response_action(
				"left", "opponent_0", "fakeout", (OpponentActionRole.DAMAGE,), "left", "team_5",
			),
			response_action(
				"right", "opponent_1", "closecombat", (OpponentActionRole.DAMAGE,), "left", "team_5",
			),
		)
		knowledge, strategy, ranking = historical_ranking(
			state, (preserve, throw_away), (double_target,), self.mechanics,
		)
		self.assertTrue(fake_out_is_fresh(knowledge))
		heliolisk = next(item for item in strategy.resources if item.pokemon_id == "team_5")
		self.assertGreater(heliolisk.value, 0.0)
		protected = candidate_with_move(ranking, "left", "protect")
		exposed = candidate_with_move(ranking, "left", "thunderbolt")
		self.assertGreater(
			feature_value(protected, "OWN_RESOURCE_SURVIVAL"),
			feature_value(exposed, "OWN_RESOURCE_SURVIVAL"),
		)
		self.assertEqual(ranking.selected_action_id, protected.candidate.action_id)

	def test_p1_08_ninetales_reset_plus_aggron_protect_improves_position_in_rain(self):
		state = current_team_state("team_2", "team_3", 3, 1)
		state["field"]["weather"] = "raindance"
		state["field"]["weather_started_turn"] = 2
		common_right = {"type": "move", "move": "protect", "transformation": "mega"}
		reset = {
			"left": {"type": "switch", "pokemon": "team_1"},
			"right": common_right,
		}
		hold = {"left": {"type": "move", "move": "protect"}, "right": common_right}
		hydro_into_aggron = response(response_action(
			"left", "opponent_3", "hydropump", (OpponentActionRole.DAMAGE,), "right", "team_3",
		))
		_, _, ranking = historical_ranking(
			state, (reset, hold), (hydro_into_aggron,), self.mechanics,
		)
		weather_reset = candidate_with_switch(ranking, "left", "team_1")
		stay = candidate_with_move(ranking, "left", "protect")
		self.assertGreater(feature_value(weather_reset, "WEATHER_CONTROL_GAIN"), 0.0)
		self.assertGreater(feature_value(weather_reset, "SAFE_SWITCH"), 0.0)
		self.assertGreater(weather_reset.final_score, stay.final_score)
		self.assertEqual(ranking.selected_action_id, weather_reset.candidate.action_id)

	def test_p1_16_wide_guard_plus_partner_protect_hedges_single_target_adaptation(self):
		state = current_team_state("team_4", "team_5", 0, 1)
		state["self"]["team"][5]["health"] = hp(80, 160)
		state["self"]["team"][5]["item"] = None
		safe = {
			"left": {"type": "move", "move": "wideguard"},
			"right": {"type": "move", "move": "protect"},
		}
		greedy = {
			"left": {"type": "move", "move": "wideguard"},
			"right": {"type": "move", "move": "thunderbolt", "target": "opponent_right"},
		}
		spread = replace(response(response_action(
			"left", "opponent_0", "heatwave",
			(OpponentActionRole.DAMAGE, OpponentActionRole.SPREAD),
		)), weight=0.55)
		single_target = replace(response(response_action(
			"right", "opponent_1", "closecombat", (OpponentActionRole.DAMAGE,), "right", "team_5",
		)), weight=0.45)
		_, _, ranking = historical_ranking(
			state, (safe, greedy), (spread, single_target), self.mechanics,
		)
		hedged = candidate_with_move(ranking, "right", "protect")
		exposed = candidate_with_move(ranking, "right", "thunderbolt")
		self.assertGreater(hedged.credible_bad_case_utility, exposed.credible_bad_case_utility)
		self.assertGreater(hedged.final_score, exposed.final_score)
		self.assertEqual(ranking.selected_action_id, hedged.candidate.action_id)


if __name__ == "__main__":
	unittest.main()
