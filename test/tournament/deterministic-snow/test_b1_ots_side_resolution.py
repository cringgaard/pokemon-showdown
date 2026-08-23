from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
POLICIES = ROOT / "tournament" / "policies"
sys.path.insert(0, str(POLICIES))

from deterministic_snow.knowledge import SelectedFourStatus, build_knowledge_state


SPECIES = ("Pelipper", "Sneasler", "Tyranitar", "Gourgeist", "Raichu", "Glaceon")


def _health(current=100, maximum=100, exact=True):
	return {"current": current, "max": maximum, "exact": exact, "percent": current / maximum * 100}


def _boosts():
	return {"atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0, "accuracy": 0, "evasion": 0}


def _own_pokemon():
	return {
		"id": "team_0", "species": "Glaceon", "name": "Glaceon", "health": _health(160, 160),
		"status": None, "fainted": False, "level": 50, "item": "leftovers", "ability": "snowcloak",
		"types": ["Ice"], "transformation": None,
		"stats": {"atk": 80, "def": 100, "spa": 130, "spd": 120, "spe": 90}, "boosts": _boosts(),
		"moves": [{"id": "protect", "name": "Protect"}], "volatiles": [],
	}


def _opponent_pokemon(index: int, species: str):
	return {
		"id": f"opponent_{index}", "species": species, "name": species, "item": "leftovers",
		"ability": "pressure", "tera_type": "Water", "nature": "Calm", "gender": "M", "level": 50,
		"moves": [{"id": "protect", "name": "Protect"}, {"id": "tackle", "name": "Tackle"}],
	}


def _packed_team() -> str:
	return "]".join(f"{species}|{species}|||protect,tackle" for species in SPECIES)


def _event(event_type: str, *args: str):
	return {
		"turn": 0,
		"type": event_type,
		"data": {"args": list(args), "kwArgs": {}},
		"raw": "|" + event_type + "|" + "|".join(args),
	}


def _switch(side: str, slot: str, species: str):
	return _event("switch", f"{side}{slot}: {species}", f"{species}, L50, M", "100/100")


def _state(history):
	return {
		"schema_version": 2,
		"battle": {"format": "gen9championsvgc2026regmb", "mod": "champions", "turn": 3, "phase": "turn"},
		"runtime": {"decision_id": 7, "revision": 0, "attempt": 1, "previous_error": None, "deadline_ms": 4200},
		"self": {
			"name": "Snow", "team": [_own_pokemon()], "active": {}, "side_conditions": {},
		},
		"opponent": {
			"name": "Foe",
			"team": [_opponent_pokemon(index, species) for index, species in enumerate(SPECIES)],
			"active": {}, "side_conditions": {},
		},
		"field": {"weather": None, "weather_started_turn": None, "conditions": {}},
		"request": {"kind": "turn", "slots": {}, "legal_actions": []},
		"history": history,
	}


class OpenTeamSheetSideResolutionTests(unittest.TestCase):
	def test_identical_rosters_use_player_identity_before_showteam_order(self):
		packed = _packed_team()
		history = [
			_event("player", "p1", "Snow", "avatar"),
			_event("player", "p2", "Foe", "avatar"),
			# The old implementation picked this first matching sheet and therefore
			# misclassified the five p1 switches below as opponent selections.
			_event("showteam", "p1", packed),
			_event("showteam", "p2", packed),
			*[_switch("p1", "a", species) for species in SPECIES[:5]],
			_switch("p2", "a", SPECIES[0]),
			_switch("p2", "b", SPECIES[2]),
		]

		knowledge = build_knowledge_state(_state(history))
		statuses = {pokemon.id: pokemon.selected_four for pokemon in knowledge.opponent_roster}
		self.assertEqual(statuses["opponent_0"], SelectedFourStatus.CONFIRMED_SELECTED)
		self.assertEqual(statuses["opponent_2"], SelectedFourStatus.CONFIRMED_SELECTED)
		self.assertTrue(all(
			statuses[f"opponent_{index}"] is SelectedFourStatus.POSSIBLE_SELECTED
			for index in (1, 3, 4, 5)
		))

	def test_identical_rosters_without_side_signal_do_not_guess(self):
		packed = _packed_team()
		history = [
			_event("showteam", "p1", packed),
			_event("showteam", "p2", packed),
			*[_switch("p1", "a", species) for species in SPECIES[:5]],
		]

		knowledge = build_knowledge_state(_state(history))
		self.assertTrue(all(
			pokemon.selected_four is SelectedFourStatus.POSSIBLE_SELECTED
			for pokemon in knowledge.opponent_roster
		))


if __name__ == "__main__":
	unittest.main()
