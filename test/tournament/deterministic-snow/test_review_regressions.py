from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POLICIES = ROOT / "tournament" / "policies"
sys.path.insert(0, str(POLICIES))

from deterministic_snow.knowledge import KnowledgeSource, SelectedFourStatus, build_knowledge_state


def health():
	return {"current": 100, "max": 100, "exact": False, "percent": 100}


def boosts():
	return {"atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0, "accuracy": 0, "evasion": 0}


def own_pokemon():
	return {
		"id": "team_0", "species": "Glaceon", "name": "Glaceon", "health": {**health(), "exact": True},
		"status": None, "fainted": False, "level": 50, "item": "brightpowder", "ability": "snowcloak",
		"types": ["Ice"], "transformation": None,
		"stats": {"atk": 1, "def": 1, "spa": 1, "spd": 1, "spe": 1}, "boosts": boosts(),
		"moves": [{"id": "protect", "name": "Protect"}], "volatiles": [],
	}


def opponent_pokemon(index: int, species: str, ability: str = "pressure"):
	return {
		"id": f"opponent_{index}", "species": species, "name": species, "item": "leftovers",
		"ability": ability, "tera_type": "Normal", "nature": "Serious", "gender": None, "level": 50,
		"moves": [{"id": "protect", "name": "Protect"}, {"id": "tackle", "name": "Tackle"}],
	}


def packed_sheet(roster):
	# Fields relevant to Teams.pack: name|species|item|ability|moves|...
	return "]".join(
		f'{pokemon["species"]}|||{pokemon["ability"]}|protect,tackle|Serious||||||'
		for pokemon in roster
	)


def event(turn, kind, args):
	return {
		"turn": turn,
		"type": kind,
		"data": {"args": args, "kwArgs": {}},
		"raw": "|" + "|".join([kind, *args]),
	}


def state_with(roster, active, history):
	return {
		"schema_version": 2,
		"battle": {"format": "gen9championsvgc2026regmb", "mod": "champions", "turn": 4, "phase": "turn"},
		"runtime": {"decision_id": 9, "revision": 0, "attempt": 1, "deadline_ms": 4000},
		"self": {
			"name": "Snow", "team": [own_pokemon()], "active": {"left": "team_0"}, "side_conditions": {},
		},
		"opponent": {"name": "Foe", "team": roster, "active": active, "side_conditions": {}},
		"field": {"weather": None, "weather_started_turn": None, "conditions": {}},
		"request": {"kind": "turn", "slots": {}, "legal_actions": []},
		"history": history,
	}


def active_state(position, pokemon):
	return {
		"position": position, "apparent_species": pokemon["species"], "team_id": pokemon["id"],
		"health": health(), "status": None, "fainted": False, "item": pokemon["item"],
		"ability": pokemon["ability"], "types": ["Normal"], "transformation": None,
		"boosts": boosts(), "volatiles": [],
	}


class ReviewRegressionTests(unittest.TestCase):
	def test_selected_four_persists_revealed_bench_from_public_history(self):
		species = ["Pelipper", "Sneasler", "Tyranitar", "Gourgeist", "Armarouge", "Heliolisk"]
		roster = [opponent_pokemon(index, name) for index, name in enumerate(species)]
		history = [event(0, "showteam", ["p2", packed_sheet(roster)])]
		history += [
			event(0, "switch", ["p2a: Pelipper", "Pelipper, L50", "100/100"]),
			event(0, "switch", ["p2b: Sneasler", "Sneasler, L50", "100/100"]),
			event(2, "switch", ["p2a: Tyranitar", "Tyranitar, L50", "100/100"]),
			event(3, "switch", ["p2b: Gourgeist", "Gourgeist, L50", "100/100"]),
		]
		active = {
			"left": active_state("left", roster[2]),
			"right": active_state("right", roster[3]),
		}
		knowledge = build_knowledge_state(state_with(roster, active, history))
		statuses = {pokemon.id: pokemon.selected_four for pokemon in knowledge.opponent_roster}
		for index in range(4):
			self.assertEqual(statuses[f"opponent_{index}"], SelectedFourStatus.CONFIRMED_SELECTED)
		for index in (4, 5):
			self.assertEqual(statuses[f"opponent_{index}"], SelectedFourStatus.CONFIRMED_NOT_SELECTED)

		# A worker restart must derive the same persistent knowledge from state/history alone.
		rebuilt = build_knowledge_state(copy.deepcopy(state_with(roster, active, history)))
		self.assertEqual(rebuilt.opponent_roster, knowledge.opponent_roster)

	def test_non_sheet_observed_move_is_not_promoted_to_ots_knowledge(self):
		species = ["Pelipper", "Sneasler", "Tyranitar", "Gourgeist", "Armarouge", "Heliolisk"]
		roster = [opponent_pokemon(index, name) for index, name in enumerate(species)]
		# Models StateTracker.applyMove(): a public non-sheet move is appended to opponent.team.
		roster[0]["moves"].append({"id": "surf", "name": "Surf"})
		history = [
			event(0, "showteam", ["p2", packed_sheet(roster)]),
			event(0, "switch", ["p2a: Pelipper", "Pelipper, L50", "100/100"]),
			event(1, "move", ["p2a: Pelipper", "Surf", "p1a: Glaceon"]),
		]
		# packed_sheet intentionally contains only Protect/Tackle, so Surf is observed, not submitted.
		knowledge = build_knowledge_state(
			state_with(roster, {"left": active_state("left", roster[0])}, history)
		)
		moves = {move.id: move for move in knowledge.opponent_roster[0].moves}
		self.assertEqual(moves["protect"].sources, (KnowledgeSource.OPEN_TEAM_SHEET,))
		self.assertEqual(moves["surf"].sources, (KnowledgeSource.BATTLE_HISTORY,))
		self.assertEqual(knowledge.history.move_observations[-1].move, "Surf")

	def test_illusion_switch_appearance_does_not_confirm_selected_identity(self):
		roster = [
			opponent_pokemon(0, "Zoroark-Hisui", "illusion"),
			opponent_pokemon(1, "Pelipper", "drizzle"),
			*[
				opponent_pokemon(index, name)
				for index, name in enumerate(["Sneasler", "Tyranitar", "Gourgeist", "Armarouge"], 2)
			],
		]
		history = [
			event(0, "showteam", ["p2", packed_sheet(roster)]),
			event(0, "switch", ["p2a: Pelipper", "Pelipper, L50", "100/100"]),
		]
		knowledge = build_knowledge_state(state_with(roster, {}, history))
		self.assertEqual(
			knowledge.opponent_roster[1].selected_four, SelectedFourStatus.POSSIBLE_SELECTED
		)

		history.append(event(1, "replace", ["p2a: Zoroark-Hisui", "Zoroark-Hisui, L50", "100/100"]))
		knowledge = build_knowledge_state(state_with(roster, {}, history))
		self.assertEqual(
			knowledge.opponent_roster[0].selected_four, SelectedFourStatus.CONFIRMED_SELECTED
		)
		self.assertEqual(
			knowledge.opponent_roster[1].selected_four, SelectedFourStatus.POSSIBLE_SELECTED
		)


if __name__ == "__main__":
	unittest.main()
