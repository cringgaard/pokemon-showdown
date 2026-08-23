from __future__ import annotations

import copy
from dataclasses import replace
import unittest

from test_b4_strategy import FakeMechanics, FakeMove, active, event, opponent, state_fixture

from deterministic_snow import build_knowledge_state
from deterministic_snow.config import default_config
from deterministic_snow.responses import (
	OpponentActionKind,
	OpponentActionRole,
	ResponseArchetype,
	ResponseContractError,
	generate_opponent_responses,
)
from deterministic_snow.strategy import PlanLabel, assess_runtime_strategy
from deterministic_snow.trace import RuntimeStrategyScores


def packed_sheet(roster):
	return "]".join(
		f'{pokemon["species"]}|||{pokemon["ability"]}|{",".join(move["id"] for move in pokemon["moves"])}|Serious||||||'
		for pokemon in roster
	)


class B6Mechanics(FakeMechanics):
	SPECIES = dict(FakeMechanics.SPECIES)
	SPECIES.update({
		"Raichu": {"types": ["Electric"], "atk": 90, "spa": 90, "def": 55, "spd": 80},
		"Amoonguss": {"types": ["Grass", "Poison"], "atk": 85, "spa": 85, "def": 70, "spd": 80},
		"Heliolisk": {"types": ["Electric", "Normal"], "atk": 55, "spa": 109, "def": 52, "spd": 94},
	})
	MOVES = dict(FakeMechanics.MOVES)
	MOVES.update({
		"thunderbolt": FakeMove("thunderbolt", "Electric", "Special", 90),
		"voltswitch": FakeMove("voltswitch", "Electric", "Special", 70, self_switch=True),
		"ragepowder": FakeMove("ragepowder", "Bug", "Status", 0, priority=2),
		"spore": FakeMove("spore", "Grass", "Status", 0, status="slp"),
		"gigadrain": FakeMove("gigadrain", "Grass", "Special", 75, drain=(1, 2)),
	})

	def semantic(self, category, value):
		key = "".join(character.lower() for character in value if character.isalnum())
		if category == "abilities":
			if key == "drizzle":
				return {"entry_weather": "raindance"}
			if key == "lightningrod":
				return {"electric_redirection": True}
		return super().semantic(category, value)

	def _single_multiplier(self, attack, defense, move_id):
		if attack == "Electric" and defense in ("Water", "Flying"):
			return 2.0
		if attack == "Electric" and defense == "Ground":
			return 0.0
		if attack == "Grass" and defense in ("Water", "Ground", "Rock"):
			return 2.0
		return super()._single_multiplier(attack, defense, move_id)


def b6_state():
	state = state_fixture()
	foes = state["opponent"]["team"]
	foes.extend([
		opponent(4, "Raichu", "lightningrod", ["thunderbolt", "voltswitch", "protect"]),
		opponent(5, "Amoonguss", "regenerator", ["ragepowder", "spore", "gigadrain", "protect"]),
	])
	state["history"].insert(0, event(0, "showteam", ["p2", packed_sheet(foes)]))
	# The inherited snapshot is already at battle turn 3. Preserve the public
	# numbered-turn boundaries so B3 can correctly derive that lead Fake Out is stale.
	state["history"].extend([
		event(1, "turn", ["2"]),
		event(2, "turn", ["3"]),
	])
	return state


def heliolisk_lead_state():
	state = b6_state()
	heliolisk = copy.deepcopy(state["self"]["team"][0])
	heliolisk.update({
		"species": "Heliolisk", "name": "Heliolisk", "item": "focussash", "ability": "dryskin",
		"types": ["Electric", "Normal"],
		"stats": {"atk": 55, "def": 52, "spa": 109, "spd": 94, "spe": 109},
		"moves": [{"id": move, "name": move} for move in ("thunderbolt", "protect")],
		"boosts": {"atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0, "accuracy": 0, "evasion": 0},
	})
	state["self"]["team"][0] = heliolisk
	return state


class B6ResponseGenerationTests(unittest.TestCase):
	def setUp(self):
		self.mechanics = B6Mechanics()

	def knowledge(self, state):
		return build_knowledge_state(state, self.mechanics)

	def test_ots_contract_requires_explicit_showteam(self):
		state = b6_state()
		state["history"] = [item for item in state["history"] if item["type"] != "showteam"]
		with self.assertRaises(ResponseContractError):
			generate_opponent_responses(self.knowledge(state), self.mechanics)

	def test_actual_ots_moves_only_and_stale_fake_out_is_removed(self):
		state = b6_state()
		state["opponent"]["team"][1]["moves"] = [{"id": "closecombat", "name": "Close Combat"}]
		state["history"][0] = event(0, "showteam", ["p2", packed_sheet(state["opponent"]["team"])])
		responses = generate_opponent_responses(self.knowledge(state), self.mechanics)
		left_moves = {action.move for action in responses.actions_for("left") if action.kind is OpponentActionKind.MOVE}
		right_moves = {action.move for action in responses.actions_for("right") if action.kind is OpponentActionKind.MOVE}
		self.assertNotIn("fakeout", left_moves)
		self.assertEqual(right_moves, {"closecombat"})
		self.assertNotIn("protect", right_moves)

	def test_keeps_diverse_actions_and_bounded_joint_responses(self):
		responses = generate_opponent_responses(self.knowledge(b6_state()), self.mechanics)
		self.assertTrue(all(1 <= len(actions) <= 4 for _, actions in responses.individual_actions))
		self.assertTrue(1 <= len(responses.responses) <= 8)
		roles = {role for _, actions in responses.individual_actions for action in actions for role in action.roles}
		self.assertIn(OpponentActionRole.DAMAGE, roles)
		self.assertIn(OpponentActionRole.PROTECT, roles)
		self.assertIn(OpponentActionRole.SWITCH, roles)
		archetypes = {kind for response in responses.responses for kind in response.archetypes}
		self.assertIn(ResponseArchetype.PIVOT_AND_ACT, archetypes)
		self.assertIn(ResponseArchetype.PROTECT_AND_PROGRESS, archetypes)
		self.assertIn(ResponseArchetype.SPREAD_PRESSURE, archetypes)

	def test_double_target_primary_win_condition_is_preserved(self):
		state = b6_state()
		# Heat Wave is spread and intentionally targetless in B6, so use two OTS
		# attackers whose submitted moves can genuinely choose Glaceon as a target.
		gengar = state["opponent"]["team"][2]
		state["opponent"]["active"]["left"] = active("left", gengar)
		state["history"].append(event(3, "switch", ["p2a: Gengar", "Gengar, L50", "100/100"]))
		knowledge = self.knowledge(state)
		strategy = assess_runtime_strategy(knowledge, self.mechanics)
		strategy = replace(strategy, scores=RuntimeStrategyScores(
			strategy.scores.glaceon_fortress,
			strategy.scores.aggron_fortress,
			strategy.scores.tactical_offense,
			PlanLabel.GLACEON_FORTRESS.value,
		))
		responses = generate_opponent_responses(knowledge, self.mechanics, strategy=strategy)
		focused = [response for response in responses.responses if ResponseArchetype.FOCUS_PRIMARY_WINCON in response.archetypes]
		self.assertTrue(focused)
		self.assertTrue(any(sum(action.target_id == "team_0" for action in response.actions) == 2 for response in focused))

	def test_switch_hypotheses_capture_ghost_weather_and_lightning_rod_pivots(self):
		policy = default_config()
		policy = replace(policy, opponent_response=replace(
			policy.opponent_response, max_individual_actions_per_pokemon=5,
		))
		responses = generate_opponent_responses(
			self.knowledge(heliolisk_lead_state()), self.mechanics, policy_config=policy,
		)
		switches = [
			action for _, actions in responses.individual_actions for action in actions
			if action.kind is OpponentActionKind.SWITCH
		]
		by_target = {action.switch_to: action for action in switches}
		self.assertIn("opponent_2", by_target)
		self.assertIn("opponent_3", by_target)
		self.assertIn("opponent_4", by_target)
		self.assertIn("Body Press immunity pivot", by_target["opponent_2"].reasons)
		self.assertIn("weather reset pivot", by_target["opponent_3"].reasons)
		self.assertIn("Lightning Rod pivot", by_target["opponent_4"].reasons)

	def test_confirmed_not_selected_never_becomes_switch_candidate(self):
		state = b6_state()
		state["history"].extend([
			event(3, "switch", ["p2a: Gengar", "Gengar, L50", "100/100"]),
			event(3, "switch", ["p2b: Pelipper", "Pelipper, L50", "100/100"]),
		])
		knowledge = self.knowledge(state)
		statuses = {pokemon.id: pokemon.selected_four.value for pokemon in knowledge.opponent_roster}
		self.assertEqual(statuses["opponent_4"], "CONFIRMED_NOT_SELECTED")
		self.assertEqual(statuses["opponent_5"], "CONFIRMED_NOT_SELECTED")
		responses = generate_opponent_responses(knowledge, self.mechanics)
		switch_targets = {
			action.switch_to for _, actions in responses.individual_actions for action in actions
			if action.kind is OpponentActionKind.SWITCH
		}
		self.assertNotIn("opponent_4", switch_targets)
		self.assertNotIn("opponent_5", switch_targets)

	def test_recent_move_and_target_history_only_modestly_raise_plausibility(self):
		base_state = b6_state()
		base = generate_opponent_responses(self.knowledge(copy.deepcopy(base_state)), self.mechanics)
		base_cc = next(action for action in base.actions_for("right") if action.move == "closecombat" and action.target_id == "team_0")

		history_state = b6_state()
		history_state["history"].append(
			event(3, "move", ["p2b: Sneasler", "Close Combat", "p1a: Glaceon"]),
		)
		history = generate_opponent_responses(self.knowledge(history_state), self.mechanics)
		history_cc = next(action for action in history.actions_for("right") if action.move == "closecombat" and action.target_id == "team_0")
		self.assertGreater(history_cc.plausibility, base_cc.plausibility)
		self.assertLessEqual(history_cc.plausibility / base_cc.plausibility, 1.25 + 1e-9)
		self.assertIn("recent pattern x1.21", history_cc.reasons)

	def test_response_generation_is_deterministic(self):
		knowledge = self.knowledge(b6_state())
		first = generate_opponent_responses(knowledge, self.mechanics)
		second = generate_opponent_responses(knowledge, self.mechanics)
		self.assertEqual(first, second)


if __name__ == "__main__":
	unittest.main()
