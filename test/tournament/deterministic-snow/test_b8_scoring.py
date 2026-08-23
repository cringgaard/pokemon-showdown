from __future__ import annotations

import copy
import unittest

from test_b7_projection import (
	joint,
	make_candidate,
	move_response,
	state_with,
)
from test_b7_projection_hardening import HardenedProjectionMechanics

from deterministic_snow.features import FEATURE_REGISTRY, FEATURE_SCHEMA_VERSION, FEATURE_SET_VERSION
from deterministic_snow.projection import project_turn
from deterministic_snow.responses import (
	OpponentActionKind,
	OpponentActionRole,
	OpponentIndividualAction,
	OpponentJointResponse,
	ResponseArchetype,
)
from deterministic_snow.scoring import (
	ScoringConfig,
	ScoringContractError,
	default_scoring_config,
	evaluate_response_utility,
	extract_outcome_features,
)
from deterministic_snow.strategy import (
	PlanAssessment,
	PlanLabel,
	ResourceValue,
	RuntimeStrategyAssessment,
	hp_utility,
)
from deterministic_snow.threats import ThreatModel
from deterministic_snow.trace import RuntimeStrategyScores


BASE_VALUES = {
	"Glaceon": 100.0,
	"Ninetales-Alola": 90.0,
	"Maushold": 80.0,
	"Aggron": 100.0,
	"Armarouge": 85.0,
	"Heliolisk": 80.0,
}


def strategy_for(knowledge, primary=PlanLabel.FLEXIBLE):
	if primary is PlanLabel.GLACEON_FORTRESS:
		scores = RuntimeStrategyScores(85.0, 45.0, 30.0, primary.value)
	elif primary is PlanLabel.AGGRON_FORTRESS:
		scores = RuntimeStrategyScores(45.0, 85.0, 30.0, primary.value)
	elif primary is PlanLabel.TACTICAL_OFFENSE:
		scores = RuntimeStrategyScores(35.0, 35.0, 80.0, primary.value)
	else:
		scores = RuntimeStrategyScores(60.0, 58.0, 35.0, primary.value)
	resources = []
	for pokemon in knowledge.own_team:
		base = BASE_VALUES.get(pokemon.species, 75.0)
		hp = hp_utility(pokemon.health.percent / 100.0)
		remaining = 0.0 if pokemon.fainted else 1.0
		resources.append(ResourceValue(
			pokemon.id, pokemon.species, base, hp, 1.0, remaining, base * hp * remaining, (),
		))
	plans = (
		PlanAssessment(PlanLabel.GLACEON_FORTRESS, scores.glaceon_fortress, (), ()),
		PlanAssessment(PlanLabel.AGGRON_FORTRESS, scores.aggron_fortress, (), ()),
		PlanAssessment(PlanLabel.TACTICAL_OFFENSE, scores.tactical_offense, (), ()),
	)
	threats = ThreatModel((), (), (), 0.5, 0.5, 0.0, 0.0)
	return RuntimeStrategyAssessment(scores, plans, tuple(resources), threats)


def response_action(position, actor_id, move, roles, target_position=None, target_id=None):
	return OpponentIndividualAction(
		position, actor_id, OpponentActionKind.MOVE, move, None,
		target_position, target_id, tuple(roles), 1.0, (),
	)


def response(*actions):
	return OpponentJointResponse((ResponseArchetype.BALANCED,), tuple(actions), 1.0, 1.0, ())


def evaluate(state, actions, opponent_response, mechanics, primary=PlanLabel.FLEXIBLE, scoring_config=None):
	knowledge, candidate = make_candidate(state, actions, mechanics)
	strategy = strategy_for(knowledge, primary)
	projection = project_turn(knowledge, mechanics, candidate, opponent_response)
	return knowledge, candidate, strategy, projection, evaluate_response_utility(
		knowledge,
		strategy,
		candidate,
		opponent_response,
		projection,
		scoring_config=scoring_config,
	)


class B8ScoringTests(unittest.TestCase):
	def setUp(self):
		self.mechanics = HardenedProjectionMechanics()

	def test_feature_vector_is_versioned_complete_ordered_and_b9_features_are_reserved(self):
		state = state_with("team_0", "team_5")
		knowledge, candidate = make_candidate(state, {
			"left": {"type": "move", "move": "blizzard"},
			"right": {"type": "move", "move": "protect"},
		}, self.mechanics)
		strategy = strategy_for(knowledge, PlanLabel.GLACEON_FORTRESS)
		opponent_response = joint(move_response("right", "opponent_1", "protect"))
		projection = project_turn(knowledge, self.mechanics, candidate, opponent_response)
		vector = extract_outcome_features(knowledge, strategy, candidate, opponent_response, projection.outcomes[0])
		self.assertEqual(vector.schema_version, FEATURE_SCHEMA_VERSION)
		self.assertEqual(vector.feature_set_version, FEATURE_SET_VERSION)
		self.assertEqual([item.feature_id for item in vector.values], [item.id for item in FEATURE_REGISTRY])
		self.assertEqual(vector.by_id()["FRAGILE_PREDICTION"], 0.0)
		self.assertEqual(vector.by_id()["ROBUST_ACROSS_RESPONSES"], 0.0)
		self.assertEqual(list(vector.to_dict()["values"]), [item.id for item in FEATURE_REGISTRY])

	def test_follow_me_rescue_beats_exposing_primary_mega_aggron(self):
		state = state_with("team_2", "team_3", 0, 1)
		opponent_response = joint(
			move_response("right", "opponent_1", "closecombat", "right", "team_3"),
		)
		common_right = {
			"type": "move", "move": "bodypress", "target": "opponent_right", "transformation": "mega",
		}
		_, _, _, _, rescue = evaluate(
			state,
			{
				"left": {"type": "move", "move": "followme"},
				"right": common_right,
			},
			opponent_response,
			self.mechanics,
			PlanLabel.AGGRON_FORTRESS,
		)
		_, _, _, _, exposed = evaluate(
			state,
			{
				"left": {"type": "move", "move": "mudslap", "target": "opponent_left"},
				"right": common_right,
			},
			opponent_response,
			self.mechanics,
			PlanLabel.AGGRON_FORTRESS,
		)
		self.assertGreater(rescue.features_by_id()["DETERMINISTIC_PROTECTION"], exposed.features_by_id()["DETERMINISTIC_PROTECTION"])
		self.assertGreater(rescue.features_by_id()["PRIMARY_WINCON_SURVIVAL"], exposed.features_by_id()["PRIMARY_WINCON_SURVIVAL"])
		self.assertGreater(rescue.utility, exposed.utility)

	def test_protecting_glaceon_from_lethal_focus_beats_extra_setup(self):
		state = state_with("team_0", "team_5", 0, 1)
		opponent_response = joint(
			move_response("right", "opponent_1", "closecombat", "left", "team_0"),
		)
		partner = {"type": "move", "move": "thunderbolt", "target": "opponent_left"}
		_, _, _, _, protected = evaluate(
			state,
			{"left": {"type": "move", "move": "protect"}, "right": partner},
			opponent_response,
			self.mechanics,
			PlanLabel.GLACEON_FORTRESS,
		)
		_, _, _, _, greedy = evaluate(
			state,
			{"left": {"type": "move", "move": "calmmind"}, "right": partner},
			opponent_response,
			self.mechanics,
			PlanLabel.GLACEON_FORTRESS,
		)
		self.assertGreater(protected.features_by_id()["PRIMARY_WINCON_SURVIVAL"], greedy.features_by_id()["PRIMARY_WINCON_SURVIVAL"])
		self.assertGreater(protected.features_by_id()["DETERMINISTIC_PROTECTION"], 0.0)
		self.assertGreater(protected.utility, greedy.utility)

	def test_setup_progress_has_diminishing_returns(self):
		base_state = state_with("team_0", "team_5")
		opponent_response = joint(move_response("right", "opponent_1", "protect"))
		actions = {
			"left": {"type": "move", "move": "calmmind"},
			"right": {"type": "move", "move": "protect"},
		}
		_, _, _, _, first = evaluate(
			base_state, actions, opponent_response, self.mechanics, PlanLabel.GLACEON_FORTRESS,
		)
		boosted = copy.deepcopy(base_state)
		boosted["self"]["team"][0]["boosts"]["spa"] = 3
		boosted["self"]["team"][0]["boosts"]["spd"] = 3
		_, _, _, _, fourth = evaluate(
			boosted, actions, opponent_response, self.mechanics, PlanLabel.GLACEON_FORTRESS,
		)
		self.assertGreater(first.features_by_id()["WIN_CONDITION_PROGRESS"], fourth.features_by_id()["WIN_CONDITION_PROGRESS"])

	def test_wide_guard_scores_only_when_spread_is_actually_prevented(self):
		state = state_with("team_4", "team_5", 0, 3)
		opponent_response = response(response_action(
			"left", "opponent_0", "heatwave", (OpponentActionRole.DAMAGE, OpponentActionRole.SPREAD),
		))
		partner = {"type": "move", "move": "thunderbolt", "target": "opponent_right"}
		_, _, _, _, guarded = evaluate(
			state,
			{"left": {"type": "move", "move": "wideguard"}, "right": partner},
			opponent_response,
			self.mechanics,
		)
		_, _, _, _, unguarded = evaluate(
			state,
			{"left": {"type": "move", "move": "allyswitch"}, "right": partner},
			opponent_response,
			self.mechanics,
		)
		self.assertGreater(guarded.features_by_id()["SPREAD_PREVENTION"], 0.0)
		self.assertEqual(unguarded.features_by_id()["SPREAD_PREVENTION"], 0.0)
		self.assertGreater(guarded.utility, unguarded.utility)

	def test_opponent_setup_is_a_negative_feature_when_it_resolves(self):
		state = state_with("team_0", "team_5", 0, 1)
		opponent_response = response(response_action(
			"left", "opponent_0", "calmmind", (OpponentActionRole.SETUP,),
		))
		_, _, _, _, evaluation = evaluate(
			state,
			{
				"left": {"type": "move", "move": "protect"},
				"right": {"type": "move", "move": "protect"},
			},
			opponent_response,
			self.mechanics,
		)
		features = evaluation.features_by_id()
		self.assertGreater(features["OPPONENT_SETUP_ALLOWED"], 0.0)
		contribution = next(item for item in evaluation.feature_contributions if item.feature_id == "OPPONENT_SETUP_ALLOWED")
		self.assertLess(contribution.contribution, 0.0)

	def test_blizzard_outside_snow_exposes_rng_dependence(self):
		rain_state = state_with("team_0", "team_5")
		rain_state["field"]["weather"] = "raindance"
		actions = {
			"left": {"type": "move", "move": "blizzard"},
			"right": {"type": "move", "move": "protect"},
		}
		opponent_response = joint(move_response("right", "opponent_1", "protect"))
		_, _, _, _, rain = evaluate(rain_state, actions, opponent_response, self.mechanics)
		snow_state = copy.deepcopy(rain_state)
		snow_state["field"]["weather"] = "snow"
		_, _, _, _, snow = evaluate(snow_state, actions, opponent_response, self.mechanics)
		self.assertGreater(rain.features_by_id()["RNG_DEPENDENCE"], snow.features_by_id()["RNG_DEPENDENCE"])

	def test_feature_extraction_is_independent_of_linear_weights(self):
		state = state_with("team_5", "team_2", 3, 1)
		actions = {
			"left": {"type": "move", "move": "thunderbolt", "target": "opponent_left"},
			"right": {"type": "move", "move": "protect"},
		}
		opponent_response = joint(move_response("right", "opponent_1", "protect"))
		_, _, _, _, baseline = evaluate(state, actions, opponent_response, self.mechanics)
		config = default_scoring_config()
		weights = dict(config.weights)
		weights["OPPONENT_DAMAGE"] += 10.0
		modified_config = ScoringConfig("b8-damage-weight-test", config.feature_set_version, weights)
		_, _, _, _, modified = evaluate(
			state, actions, opponent_response, self.mechanics, scoring_config=modified_config,
		)
		self.assertEqual(baseline.feature_values, modified.feature_values)
		damage = baseline.features_by_id()["OPPONENT_DAMAGE"]
		self.assertAlmostEqual(modified.utility - baseline.utility, 10.0 * damage, places=7)

	def test_response_utility_is_branch_weighted_only_within_same_response(self):
		state = state_with("team_0", "team_2", 2, 1)
		state["opponent"]["team"][2]["item"] = "gengarite"
		state["opponent"]["active"]["left"]["item"] = "gengarite"
		# Existing showteam provenance is sufficient for the synthetic projection;
		# the important contract here is the public current item enables branching.
		opponent_response = joint(move_response("left", "opponent_2", "shadowball", "left", "team_0"))
		knowledge, candidate, strategy, projection, evaluation = evaluate(
			state,
			{
				"left": {"type": "move", "move": "protect"},
				"right": {"type": "move", "move": "protect"},
			},
			opponent_response,
			self.mechanics,
			PlanLabel.GLACEON_FORTRESS,
		)
		self.assertGreaterEqual(len(projection.outcomes), 2)
		for feature in FEATURE_REGISTRY:
			expected = sum(
				branch.branch_weight * branch.feature_vector.by_id()[feature.id]
				for branch in evaluation.branch_evaluations
			)
			self.assertAlmostEqual(evaluation.features_by_id()[feature.id], expected, places=7)
		self.assertAlmostEqual(
			evaluation.utility,
			sum(branch.branch_weight * branch.utility for branch in evaluation.branch_evaluations),
			places=7,
		)

	def test_projection_candidate_mismatch_fails_closed(self):
		state = state_with("team_0", "team_5")
		opponent_response = joint(move_response("right", "opponent_1", "protect"))
		knowledge, first = make_candidate(state, {
			"left": {"type": "move", "move": "protect"},
			"right": {"type": "move", "move": "protect"},
		}, self.mechanics)
		strategy = strategy_for(knowledge)
		projection = project_turn(knowledge, self.mechanics, first, opponent_response)
		other_knowledge, other = make_candidate(state, {
			"left": {"type": "move", "move": "calmmind"},
			"right": {"type": "move", "move": "protect"},
		}, self.mechanics)
		with self.assertRaises(ScoringContractError):
			evaluate_response_utility(other_knowledge, strategy, other, opponent_response, projection)


if __name__ == "__main__":
	unittest.main()
