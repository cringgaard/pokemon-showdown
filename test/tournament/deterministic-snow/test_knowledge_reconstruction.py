from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
POLICIES = ROOT / "tournament" / "policies"
sys.path.insert(0, str(POLICIES))

from deterministic_snow import KnowledgeState, build_knowledge_state
from deterministic_snow.knowledge import Certainty


def health(current=100, maximum=100, exact=True):
	return {"current": current, "max": maximum, "exact": exact, "percent": current / maximum * 100}


def boosts():
	return {"atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0, "accuracy": 0, "evasion": 0}


def own_pokemon(index, species, item, ability, moves):
	name = "Ninetales" if species == "Ninetales-Alola" else species
	return {
		"id": f"team_{index}", "species": species, "name": name, "health": health(160, 160),
		"status": None, "fainted": False, "level": 50, "item": item, "ability": ability,
		"types": ["Ice"], "transformation": None,
		"stats": {"atk": 80, "def": 100, "spa": 120, "spd": 110, "spe": 100}, "boosts": boosts(),
		"moves": [{"id": move, "name": move} for move in moves], "volatiles": [],
	}


def opponent_pokemon(index, species, moves):
	return {
		"id": f"opponent_{index}", "species": species, "name": species, "item": "leftovers",
		"ability": "intimidate" if species == "Incineroar" else "sandstream", "tera_type": "Water",
		"nature": "Careful", "gender": "M", "level": 50,
		"moves": [{"id": move, "name": move} for move in moves],
	}


def event(turn, event_type, args, *, kwargs=None):
	return {
		"turn": turn,
		"type": event_type,
		"data": {"args": args, "kwArgs": kwargs or {}},
		"raw": "|" + "|".join([event_type, *[str(arg) for arg in args]]),
	}


def state_fixture():
	history = [
		event(0, "showteam", ["p2", "synthetic"]),
		event(0, "switch", ["p1a: Ninetales", "Ninetales-Alola, L50", "160/160"]),
		event(0, "-weather", ["Snow"], kwargs={"from": "ability: Snow Warning", "of": "p1a: Ninetales"}),
		event(0, "switch", ["p2a: Incineroar", "Incineroar, L50", "100/100"]),
		event(0, "switch", ["p2b: Tyranitar", "Tyranitar, L50", "100/100"]),
		event(1, "move", ["p2a: Incineroar", "Fake Out", "p1a: Ninetales"]),
		event(1, "-damage", ["p1a: Ninetales", "120/160"]),
		event(1, "move", ["p1a: Ninetales", "Protect", "p1a: Ninetales"]),
		event(2, "switch", ["p2a: Pelipper", "Pelipper, L50", "100/100"]),
		event(2, "move", ["p2b: Tyranitar", "Protect", "p2b: Tyranitar"]),
		event(2, "move", ["p1a: Ninetales", "Freeze-Dry", "p2a: Pelipper"]),
		event(2, "move", ["p2a: Pelipper", "Hydro Pump", "p1a: Ninetales"]),
		event(2, "-damage", ["p1a: Ninetales", "80/160"]),
		event(3, "move", ["p2b: Tyranitar", "Protect", "p2b: Tyranitar"]),
		event(3, "switch", ["p2a: Incineroar", "Incineroar, L50", "100/100"]),
	]
	return {
		"schema_version": 2,
		"battle": {"format": "gen9championsvgc2026regmb", "mod": "champions", "turn": 4, "phase": "turn"},
		"runtime": {"decision_id": 11, "revision": 0, "attempt": 1, "previous_error": None, "deadline_ms": 4000},
		"self": {
			"name": "Snow",
			"team": [
				own_pokemon(0, "Ninetales-Alola", "icyrock", "snowwarning", ["freezedry", "protect"]),
				own_pokemon(1, "Glaceon", "brightpowder", "snowcloak", ["blizzard", "protect"]),
			],
			"active": {"left": "team_0", "right": "team_1"},
			"side_conditions": {"auroraveil": {"active": True, "started_turn": 2}},
		},
		"opponent": {
			"name": "Foe",
			"team": [
				opponent_pokemon(0, "Incineroar", ["fakeout", "protect"]),
				opponent_pokemon(1, "Tyranitar", ["rockslide", "protect"]),
				opponent_pokemon(2, "Pelipper", ["hydropump", "protect"]),
			],
			"active": {
				"left": {
					"position": "left", "apparent_species": "Incineroar", "team_id": "opponent_0",
					"health": health(), "status": None, "fainted": False, "item": "leftovers",
					"ability": "intimidate", "types": ["Fire", "Dark"], "transformation": None,
					"boosts": boosts(), "volatiles": [],
				},
				"right": {
					"position": "right", "apparent_species": "Tyranitar", "team_id": "opponent_1",
					"health": health(), "status": None, "fainted": False, "item": "leftovers",
					"ability": "sandstream", "types": ["Rock", "Dark"], "transformation": None,
					"boosts": boosts(), "volatiles": [],
				},
			},
			"side_conditions": {"tailwind": {"active": True, "started_turn": 3}},
		},
		"field": {"weather": "snow", "weather_started_turn": 0, "conditions": {}},
		"request": {"kind": "turn", "slots": {}, "legal_actions": []},
		"history": history,
	}


class FakeMechanics:
	priorities = {"fakeout": 3, "protect": 4, "freezedry": 0, "hydropump": 0}

	def move(self, value):
		key = "".join(character.lower() for character in value if character.isalnum())
		if key not in self.priorities:
			raise KeyError(key)
		return SimpleNamespace(priority=self.priorities[key])

	def semantic(self, category, value):
		key = "".join(character.lower() for character in value if character.isalnum())
		if category == "moves" and key == "protect":
			return {"protection_move": True}
		if category == "items" and key == "icyrock":
			return {"weather_extension_turns": {"snowscape": 8}}
		return {}


class KnowledgeReconstructionTests(unittest.TestCase):
	def test_reconstructs_protect_chains_switches_moves_and_targets(self):
		knowledge = build_knowledge_state(state_fixture(), FakeMechanics())
		self.assertEqual(knowledge.knowledge_schema_version, 2)
		chains = {chain.pokemon_identity: chain for chain in knowledge.history.protect_chains}
		self.assertEqual(chains["p2:Tyranitar"].last_used_turn, 3)
		self.assertEqual(chains["p2:Tyranitar"].consecutive_count, 2)

		chronology = {item.pokemon_identity: item for item in knowledge.history.switch_chronology}
		self.assertEqual(chronology["p2:Incineroar"].entry_turns, (0, 3))
		self.assertEqual(chronology["p2:Incineroar"].exit_turns, (2,))
		self.assertEqual(chronology["p2:Pelipper"].entry_turns, (2,))
		self.assertEqual(chronology["p2:Pelipper"].exit_turns, (3,))

		freeze_dry = next(move for move in knowledge.history.move_observations if move.move == "freezedry")
		self.assertEqual(freeze_dry.actor, "p1:Ninetales")
		self.assertEqual(freeze_dry.target, "p2:Pelipper")

	def test_reconstructs_damage_and_same_priority_speed_evidence(self):
		knowledge = build_knowledge_state(state_fixture(), FakeMechanics())
		damage = knowledge.history.damage_evidence[-1]
		self.assertEqual(damage.attacker, "p2:Pelipper")
		self.assertEqual(damage.move, "hydropump")
		self.assertEqual(damage.target, "p1:Ninetales")
		self.assertAlmostEqual(damage.hp_fraction_removed, 0.25)
		self.assertTrue(json.loads(damage.context)["direct_move"])

		speed = next(item for item in knowledge.history.speed_evidence if item.turn == 2)
		self.assertEqual(speed.faster_actor, "p1:Ninetales")
		self.assertEqual(speed.slower_actor, "p2:Pelipper")
		self.assertFalse(json.loads(speed.context)["trick_room"])

	def test_tracks_weather_provenance_and_only_derives_verified_duration(self):
		knowledge = build_knowledge_state(state_fixture(), FakeMechanics())
		self.assertEqual(len(knowledge.weather_history), 1)
		weather = knowledge.weather_history[0]
		self.assertEqual(weather.weather, "snow")
		self.assertEqual(weather.source_effect, "snowwarning")
		self.assertEqual(weather.source_pokemon, "p1:Ninetales")

		timers = {(item.scope, item.id): item for item in knowledge.timed_conditions}
		snow = timers[("field", "snow")]
		self.assertEqual(snow.expected_end_turn, 7)
		self.assertEqual(snow.remaining_turns, 4)
		self.assertEqual(snow.duration_certainty, Certainty.DERIVED)
		self.assertEqual(timers[("opponent_side", "tailwind")].duration_certainty, Certainty.UNKNOWN)

		without_mechanics = build_knowledge_state(copy.deepcopy(state_fixture()))
		unknown_snow = {(item.scope, item.id): item for item in without_mechanics.timed_conditions}[("field", "snow")]
		self.assertIsNone(unknown_snow.expected_end_turn)
		self.assertEqual(unknown_snow.duration_certainty, Certainty.UNKNOWN)
		self.assertEqual(without_mechanics.history.speed_evidence, ())

	def test_fake_out_eligibility_uses_latest_public_entry_not_process_memory(self):
		knowledge = build_knowledge_state(state_fixture(), FakeMechanics())
		eligibility = {item.pokemon_identity: item for item in knowledge.fake_out_eligibility}
		incineroar = eligibility["opponent_0"]
		self.assertTrue(incineroar.known_fake_out)
		self.assertTrue(incineroar.eligible)
		self.assertEqual(incineroar.certainty, Certainty.DERIVED)
		self.assertFalse(eligibility["opponent_1"].known_fake_out)
		self.assertFalse(eligibility["opponent_1"].eligible)

	def test_b3_state_round_trips_deterministically(self):
		first = build_knowledge_state(state_fixture(), FakeMechanics())
		second = build_knowledge_state(copy.deepcopy(state_fixture()), FakeMechanics())
		self.assertEqual(first, second)
		self.assertEqual(first.to_json(), second.to_json())
		self.assertEqual(KnowledgeState.from_json(first.to_json()), first)


if __name__ == "__main__":
	unittest.main()
