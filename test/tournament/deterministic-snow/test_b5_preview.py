from __future__ import annotations

import copy
from dataclasses import dataclass
from itertools import permutations
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
POLICIES = ROOT / "tournament" / "policies"
sys.path.insert(0, str(POLICIES))

from deterministic_snow import build_knowledge_state
from deterministic_snow.preview import (
	OpponentTag,
	PreviewContractError,
	assess_team_preview,
	build_opponent_roster_profile,
	generate_opponent_lead_hypotheses,
)


def health():
	return {"current": 100, "max": 100, "exact": True, "percent": 100}


def boosts():
	return {"atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0, "accuracy": 0, "evasion": 0}


def own(index, species, ability, item, types, moves):
	return {
		"id": f"team_{index}", "species": species, "name": species.split("-")[0],
		"health": health(), "status": None, "fainted": False, "level": 50,
		"item": item, "ability": ability, "types": types, "transformation": None,
		"stats": {"atk": 100, "def": 100, "spa": 100, "spd": 100, "spe": 100},
		"boosts": boosts(), "moves": [{"id": move, "name": move} for move in moves], "volatiles": [],
	}


def opponent(index, species, ability, moves, item="leftovers"):
	return {
		"id": f"opponent_{index}", "species": species, "name": species, "item": item,
		"ability": ability, "tera_type": "Normal", "nature": "Serious", "gender": None, "level": 50,
		"moves": [{"id": move, "name": move} for move in moves],
	}


def packed_sheet(roster):
	return "]".join(
		f'{pokemon["species"]}|||{pokemon["ability"]}|{",".join(move["id"] for move in pokemon["moves"])}|Serious||||||'
		for pokemon in roster
	)


def event(kind, args):
	return {"turn": 0, "type": kind, "data": {"args": args, "kwArgs": {}}, "raw": "|" + "|".join([kind, *args])}


def preview_state(*, no_guard=False):
	own_team = [
		own(0, "Glaceon", "snowcloak", "brightpowder", ["Ice"], ["calmmind", "blizzard", "wish", "protect"]),
		own(1, "Ninetales-Alola", "snowwarning", "icyrock", ["Ice", "Fairy"], ["auroraveil", "freezedry", "encore", "protect"]),
		own(2, "Maushold", "friendguard", "chopleberry", ["Normal"], ["followme", "mudslap", "encore", "protect"]),
		own(3, "Aggron", "sturdy", "aggronite", ["Steel", "Rock"], ["irondefense", "bodypress", "heavyslam", "protect"]),
		own(4, "Armarouge", "flashfire", "colburberry", ["Fire", "Psychic"], ["wideguard", "allyswitch", "armorcannon", "psychic"]),
		own(5, "Heliolisk", "dryskin", "focussash", ["Electric", "Normal"], ["thunderbolt", "grassknot", "allyswitch", "protect"]),
	]
	foes = [
		opponent(0, "Pelipper", "drizzle", ["hydropump", "hurricane", "tailwind", "protect"]),
		opponent(1, "Basculegion", "adaptability", ["wavecrash", "aquajet", "crunch", "protect"]),
		opponent(2, "Incineroar", "intimidate", ["heatwave", "fakeout", "knockoff", "protect"]),
		opponent(3, "Sneasler", "unburden", ["closecombat", "swordsdance", "poisonjab", "protect"]),
		opponent(4, "Machamp", "noguard" if no_guard else "guts", ["dynamicpunch", "rockslide", "protect", "bulkup"]),
		opponent(5, "Amoonguss", "regenerator", ["ragepowder", "spore", "gigadrain", "protect"]),
	]
	legal = [{"team": list(team)} for team in permutations([pokemon["id"] for pokemon in own_team], 4)]
	return {
		"schema_version": 2,
		"battle": {"format": "gen9championsvgc2026regmb", "mod": "champions", "turn": 0, "phase": "team_preview"},
		"runtime": {"decision_id": 1, "revision": 0, "attempt": 1, "deadline_ms": 5000},
		"self": {"name": "Snow", "team": own_team, "active": {}, "side_conditions": {}},
		"opponent": {"name": "Foe", "team": foes, "active": {}, "side_conditions": {}},
		"field": {"weather": None, "weather_started_turn": None, "conditions": {}},
		"request": {"kind": "team_preview", "team_size": 4, "legal_actions": legal},
		"history": [event("showteam", ["p2", packed_sheet(foes)])],
	}


@dataclass(frozen=True)
class FakeMove:
	id: str
	type: str
	category: str
	base_power: int
	priority: int = 0
	target: str = "normal"
	status: str | None = None
	volatile_status: str | None = None
	weather: str | None = None
	boosts: tuple[tuple[str, int], ...] = ()
	self_boosts: tuple[tuple[str, int], ...] = ()
	ignore_accuracy: bool = False
	ignore_evasion: bool = False

	@property
	def is_spread(self):
		return self.target in ("allAdjacent", "allAdjacentFoes")


class FakeMechanics:
	SPECIES = {
		"Glaceon": (["Ice"], "snowcloak"),
		"Ninetales-Alola": (["Ice", "Fairy"], "snowwarning"),
		"Maushold": (["Normal"], "friendguard"),
		"Aggron": (["Steel", "Rock"], "sturdy"),
		"Armarouge": (["Fire", "Psychic"], "flashfire"),
		"Heliolisk": (["Electric", "Normal"], "dryskin"),
		"Pelipper": (["Water", "Flying"], "drizzle"),
		"Basculegion": (["Water", "Ghost"], "adaptability"),
		"Incineroar": (["Fire", "Dark"], "intimidate"),
		"Sneasler": (["Fighting", "Poison"], "unburden"),
		"Machamp": (["Fighting"], "guts"),
		"Amoonguss": (["Grass", "Poison"], "regenerator"),
	}
	MOVES = {
		"calmmind": FakeMove("calmmind", "Psychic", "Status", 0, self_boosts=(("spa", 1), ("spd", 1))),
		"blizzard": FakeMove("blizzard", "Ice", "Special", 110, target="allAdjacentFoes"),
		"wish": FakeMove("wish", "Normal", "Status", 0),
		"protect": FakeMove("protect", "Normal", "Status", 0),
		"auroraveil": FakeMove("auroraveil", "Ice", "Status", 0),
		"freezedry": FakeMove("freezedry", "Ice", "Special", 70),
		"encore": FakeMove("encore", "Normal", "Status", 0),
		"followme": FakeMove("followme", "Normal", "Status", 0, priority=2),
		"mudslap": FakeMove("mudslap", "Ground", "Special", 20),
		"irondefense": FakeMove("irondefense", "Steel", "Status", 0, self_boosts=(("def", 2),)),
		"bodypress": FakeMove("bodypress", "Fighting", "Physical", 80),
		"heavyslam": FakeMove("heavyslam", "Steel", "Physical", 80),
		"wideguard": FakeMove("wideguard", "Rock", "Status", 0),
		"allyswitch": FakeMove("allyswitch", "Psychic", "Status", 0),
		"armorcannon": FakeMove("armorcannon", "Fire", "Special", 120),
		"psychic": FakeMove("psychic", "Psychic", "Special", 90),
		"thunderbolt": FakeMove("thunderbolt", "Electric", "Special", 90),
		"grassknot": FakeMove("grassknot", "Grass", "Special", 80),
		"hydropump": FakeMove("hydropump", "Water", "Special", 110),
		"hurricane": FakeMove("hurricane", "Flying", "Special", 110),
		"tailwind": FakeMove("tailwind", "Flying", "Status", 0),
		"wavecrash": FakeMove("wavecrash", "Water", "Physical", 120),
		"aquajet": FakeMove("aquajet", "Water", "Physical", 40, priority=1),
		"crunch": FakeMove("crunch", "Dark", "Physical", 80),
		"heatwave": FakeMove("heatwave", "Fire", "Special", 95, target="allAdjacentFoes"),
		"fakeout": FakeMove("fakeout", "Normal", "Physical", 40, priority=3),
		"knockoff": FakeMove("knockoff", "Dark", "Physical", 65),
		"closecombat": FakeMove("closecombat", "Fighting", "Physical", 120),
		"poisonjab": FakeMove("poisonjab", "Poison", "Physical", 80),
		"swordsdance": FakeMove("swordsdance", "Normal", "Status", 0, self_boosts=(("atk", 2),)),
		"dynamicpunch": FakeMove("dynamicpunch", "Fighting", "Physical", 100),
		"rockslide": FakeMove("rockslide", "Rock", "Physical", 75, target="allAdjacentFoes"),
		"bulkup": FakeMove("bulkup", "Fighting", "Status", 0, self_boosts=(("atk", 1), ("def", 1))),
		"ragepowder": FakeMove("ragepowder", "Bug", "Status", 0, priority=2),
		"spore": FakeMove("spore", "Grass", "Status", 0, status="slp"),
		"gigadrain": FakeMove("gigadrain", "Grass", "Special", 75),
	}

	def require_champions_format(self):
		return self

	def species(self, value):
		types, ability = self.SPECIES[value]
		return SimpleNamespace(name=value, types=tuple(types), abilities=(("0", ability),))

	def move(self, value):
		key = "".join(character.lower() for character in value if character.isalnum())
		if key not in self.MOVES:
			raise KeyError(key)
		return self.MOVES[key]

	def form_after_item_transformation(self, species, item):
		return None

	def semantic(self, category, value):
		key = "".join(character.lower() for character in value if character.isalnum())
		if category == "abilities":
			return {
				"drizzle": {"entry_weather": "raindance"},
				"snowwarning": {"entry_weather": "snowscape"},
				"noguard": {"accuracy_bypass": True},
				"flashfire": {"fire_immunity": True},
				"dryskin": {"water_immunity_and_heal_fraction": 0.25},
			}.get(key, {})
		if category == "moves":
			return {
				"followme": {"single_target_redirection": True},
				"freezedry": {"effectiveness_override": {"Water": 2}},
				"blizzard": {"accuracy_by_weather": {"snowscape": True}},
				"hurricane": {"accuracy_by_weather": {"raindance": True}},
			}.get(key, {})
		return {}

	def move_multiplier(self, move, defending_types):
		move = self.move(move) if isinstance(move, str) else move
		result = 1.0
		for defending in defending_types:
			result *= self._single(move.id, move.type, defending)
		return result

	def _single(self, move_id, attacking, defending):
		if move_id == "freezedry" and defending == "Water":
			return 2.0
		chart = {
			("Ice", "Flying"): 2.0, ("Ice", "Grass"): 2.0, ("Ice", "Ground"): 2.0,
			("Ice", "Fire"): 0.5, ("Ice", "Steel"): 0.5, ("Ice", "Water"): 0.5,
			("Fighting", "Ice"): 2.0, ("Fighting", "Steel"): 2.0, ("Fighting", "Rock"): 2.0,
			("Fighting", "Normal"): 2.0, ("Fighting", "Dark"): 2.0, ("Fighting", "Ghost"): 0.0,
			("Fire", "Ice"): 2.0, ("Fire", "Steel"): 2.0, ("Fire", "Grass"): 2.0,
			("Fire", "Water"): 0.5, ("Fire", "Fire"): 0.5, ("Fire", "Rock"): 0.5,
			("Psychic", "Fighting"): 2.0, ("Psychic", "Poison"): 2.0, ("Psychic", "Dark"): 0.0,
			("Electric", "Water"): 2.0, ("Electric", "Flying"): 2.0, ("Electric", "Ground"): 0.0,
			("Grass", "Water"): 2.0, ("Grass", "Ground"): 2.0, ("Grass", "Rock"): 2.0,
			("Grass", "Fire"): 0.5, ("Grass", "Flying"): 0.5, ("Grass", "Poison"): 0.5,
			("Steel", "Rock"): 2.0, ("Steel", "Ice"): 2.0, ("Steel", "Fairy"): 2.0,
			("Ghost", "Ghost"): 2.0, ("Ghost", "Normal"): 0.0,
			("Water", "Fire"): 2.0, ("Water", "Rock"): 2.0, ("Water", "Ground"): 2.0,
			("Water", "Water"): 0.5, ("Water", "Grass"): 0.5,
			("Rock", "Fire"): 2.0, ("Rock", "Ice"): 2.0, ("Rock", "Flying"): 2.0,
			("Normal", "Ghost"): 0.0,
		}
		return chart.get((attacking, defending), 1.0)


class B5PreviewTests(unittest.TestCase):
	def setUp(self):
		self.mechanics = FakeMechanics()

	def knowledge(self, state=None):
		return build_knowledge_state(state or preview_state(), self.mechanics)

	def candidate(self, assessment, team):
		wanted = tuple(team)
		return next(candidate for candidate in assessment.candidates if candidate.team == wanted)

	def test_ots_tags_come_from_actual_submitted_moves(self):
		knowledge = self.knowledge()
		profile = build_opponent_roster_profile(knowledge, self.mechanics)
		by_species = {pokemon.species: pokemon for pokemon in profile.pokemon}
		self.assertIn(OpponentTag.FAKE_OUT, by_species["Incineroar"].tags)
		self.assertNotIn(OpponentTag.FAKE_OUT, by_species["Sneasler"].tags)
		self.assertIn(OpponentTag.SPREAD_FIRE, by_species["Incineroar"].tags)

	def test_non_ots_or_observed_only_move_fails_closed(self):
		state = preview_state()
		packed = packed_sheet(state["opponent"]["team"])
		state["opponent"]["team"][3]["moves"].append({"id": "fakeout", "name": "Fake Out"})
		state["history"] = [event("showteam", ["p2", packed])]
		knowledge = self.knowledge(state)
		with self.assertRaises(PreviewContractError):
			assess_team_preview(knowledge, self.mechanics)

	def test_rain_setter_and_water_attacker_is_retained_as_lead_hypothesis(self):
		knowledge = self.knowledge()
		roster = build_opponent_roster_profile(knowledge, self.mechanics)
		hypotheses = generate_opponent_lead_hypotheses(roster, self.mechanics)
		by_species = {pokemon.pokemon_id: pokemon.species for pokemon in roster.pokemon}
		pairs = [{by_species[pokemon_id] for pokemon_id in hypothesis.members} for hypothesis in hypotheses]
		self.assertIn({"Pelipper", "Basculegion"}, pairs)

	def test_every_legal_order_is_scored_once_and_selection_is_deterministic(self):
		knowledge = self.knowledge()
		first = assess_team_preview(knowledge, self.mechanics)
		second = assess_team_preview(self.knowledge(copy.deepcopy(preview_state())), self.mechanics)
		self.assertEqual(len(first.candidates), 360)
		self.assertEqual(len({candidate.action.action_id for candidate in first.candidates}), 360)
		self.assertEqual(first.selected_action_id, second.selected_action_id)
		self.assertIn(first.selected_action_id, {action.action_id for action in knowledge.legal_actions})

	def test_armarouge_lead_beats_same_four_with_armarouge_hidden_against_spread_fire(self):
		assessment = assess_team_preview(self.knowledge(), self.mechanics)
		armarouge_lead = self.candidate(assessment, ("team_4", "team_5", "team_0", "team_2"))
		armarouge_back = self.candidate(assessment, ("team_0", "team_5", "team_4", "team_2"))
		self.assertGreater(armarouge_lead.lead_robustness, armarouge_back.lead_robustness)
		self.assertGreater(armarouge_lead.final_score, armarouge_back.final_score)

	def test_ninetales_backline_value_rises_in_weather_war(self):
		assessment = assess_team_preview(self.knowledge(), self.mechanics)
		ninetales_back = self.candidate(assessment, ("team_2", "team_3", "team_1", "team_0"))
		ninetales_lead = self.candidate(assessment, ("team_1", "team_3", "team_2", "team_0"))
		self.assertGreater(ninetales_back.backline_quality, ninetales_lead.backline_quality)
		self.assertGreater(ninetales_back.final_score, ninetales_lead.final_score)

	def test_maushold_improves_aggron_preview_plan_against_physical_roster(self):
		assessment = assess_team_preview(self.knowledge(), self.mechanics)
		with_maushold = self.candidate(assessment, ("team_3", "team_4", "team_2", "team_1"))
		without_maushold = self.candidate(assessment, ("team_3", "team_4", "team_5", "team_1"))
		self.assertGreater(with_maushold.plans.aggron_fortress, without_maushold.plans.aggron_fortress)

	def test_no_guard_reduces_glaceon_preview_viability(self):
		base = assess_team_preview(self.knowledge(preview_state(no_guard=False)), self.mechanics)
		no_guard = assess_team_preview(self.knowledge(preview_state(no_guard=True)), self.mechanics)
		team = ("team_0", "team_1", "team_2", "team_4")
		self.assertGreater(
			self.candidate(base, team).plans.glaceon_fortress,
			self.candidate(no_guard, team).plans.glaceon_fortress,
		)


if __name__ == "__main__":
	unittest.main()
