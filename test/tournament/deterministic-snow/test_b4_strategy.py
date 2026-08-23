from __future__ import annotations

import copy
from dataclasses import dataclass
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
POLICIES = ROOT / "tournament" / "policies"
sys.path.insert(0, str(POLICIES))

from deterministic_snow import build_knowledge_state
from deterministic_snow.strategy import PlanLabel, assess_runtime_strategy, hp_utility
from deterministic_snow.threats import (
	DamageBand,
	KOConfidence,
	ThreatCategory,
	build_threat_model,
)


def health(current=160, maximum=160, exact=True):
	return {"current": current, "max": maximum, "exact": exact, "percent": current / maximum * 100}


def boosts(**values):
	result = {"atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0, "accuracy": 0, "evasion": 0}
	result.update(values)
	return result


def own(index, species, *, hp=160, maximum=160, status=None, transformation=None, stat_boosts=None, moves=()):
	stats = {
		"Glaceon": {"atk": 70, "def": 110, "spa": 150, "spd": 120, "spe": 90},
		"Aggron-Mega": {"atk": 120, "def": 220, "spa": 60, "spd": 100, "spe": 70},
		"Ninetales-Alola": {"atk": 60, "def": 90, "spa": 110, "spd": 120, "spe": 130},
		"Maushold": {"atk": 90, "def": 90, "spa": 60, "spd": 90, "spe": 130},
	}[species]
	name = "Ninetales" if species == "Ninetales-Alola" else species.replace("-Mega", "")
	return {
		"id": f"team_{index}", "species": species, "name": name, "health": health(hp, maximum),
		"status": status, "fainted": hp == 0, "level": 50,
		"item": {"Glaceon": "brightpowder", "Aggron-Mega": "aggronite", "Ninetales-Alola": "icyrock", "Maushold": "sitrusberry"}[species],
		"ability": {"Glaceon": "snowcloak", "Aggron-Mega": "filter", "Ninetales-Alola": "snowwarning", "Maushold": "friendguard"}[species],
		"types": {"Glaceon": ["Ice"], "Aggron-Mega": ["Steel"], "Ninetales-Alola": ["Ice", "Fairy"], "Maushold": ["Normal"]}[species],
		"transformation": transformation,
		"stats": stats,
		"boosts": boosts(**(stat_boosts or {})),
		"moves": [{"id": move, "name": move} for move in moves],
		"volatiles": [],
	}


def opponent(index, species, ability, moves, item="leftovers"):
	return {
		"id": f"opponent_{index}", "species": species, "name": species, "item": item,
		"ability": ability, "tera_type": "Normal", "nature": "Serious", "gender": None, "level": 50,
		"moves": [{"id": move, "name": move} for move in moves],
	}


def active(position, pokemon, *, hp=100, ability=None, types=None, stat_boosts=None):
	return {
		"position": position, "apparent_species": pokemon["species"], "team_id": pokemon["id"],
		"health": health(hp, 100, False), "status": None, "fainted": hp == 0,
		"item": pokemon["item"], "ability": ability or pokemon["ability"],
		"types": types or FakeMechanics.SPECIES[pokemon["species"]]["types"], "transformation": None,
		"boosts": boosts(**(stat_boosts or {})), "volatiles": [],
	}


def event(turn, kind, args, *, kwargs=None):
	return {
		"turn": turn, "type": kind,
		"data": {"args": args, "kwArgs": kwargs or {}},
		"raw": "|" + "|".join([kind, *[str(value) for value in args]]),
	}


def state_fixture():
	foes = [
		opponent(0, "Incineroar", "intimidate", ["heatwave", "fakeout", "protect"]),
		opponent(1, "Sneasler", "unburden", ["closecombat", "protect"]),
		opponent(2, "Gengar", "cursedbody", ["shadowball", "willowisp", "protect"]),
		opponent(3, "Pelipper", "drizzle", ["hydropump", "tailwind", "protect"]),
	]
	return {
		"schema_version": 2,
		"battle": {"format": "gen9championsvgc2026regmb", "mod": "champions", "turn": 3, "phase": "turn"},
		"runtime": {"decision_id": 12, "revision": 0, "attempt": 1, "deadline_ms": 4000},
		"self": {
			"name": "Snow",
			"team": [
				own(0, "Glaceon", stat_boosts={"spa": 1, "spd": 1}, moves=("blizzard", "freezedry", "calmmind", "protect")),
				own(1, "Aggron-Mega", transformation={"kind": "mega"}, moves=("bodypress", "irondefense", "protect")),
				own(2, "Ninetales-Alola", moves=("auroraveil", "freezedry", "protect")),
				own(3, "Maushold", moves=("followme", "encore", "protect")),
			],
			"active": {"left": "team_0", "right": "team_1"},
			"side_conditions": {"auroraveil": {"active": True, "started_turn": 1}},
		},
		"opponent": {
			"name": "Foe", "team": foes,
			"active": {
				"left": active("left", foes[0]),
				"right": active("right", foes[1]),
			},
			"side_conditions": {},
		},
		"field": {"weather": "snow", "weather_started_turn": 0, "conditions": {}},
		"request": {"kind": "turn", "slots": {}, "legal_actions": []},
		"history": [
			event(0, "switch", ["p1a: Glaceon", "Glaceon, L50", "160/160"]),
			event(0, "switch", ["p1b: Aggron", "Aggron-Mega, L50", "160/160"]),
			event(0, "switch", ["p2a: Incineroar", "Incineroar, L50", "100/100"]),
			event(0, "switch", ["p2b: Sneasler", "Sneasler, L50", "100/100"]),
			event(0, "turn", ["1"]),
		],
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
	terrain: str | None = None
	pseudo_weather: str | None = None
	side_condition: str | None = None
	boosts: tuple[tuple[str, int], ...] = ()
	self_boosts: tuple[tuple[str, int], ...] = ()
	heal: tuple[int, ...] | None = None
	drain: tuple[int, ...] | None = None
	force_switch: bool = False
	self_switch: str | bool | None = None
	ignore_accuracy: bool = False
	ignore_evasion: bool = False
	override_offensive_stat: str | None = None
	override_defensive_stat: str | None = None
	callback_names: tuple[str, ...] = ()

	@property
	def is_spread(self):
		return self.target in ("allAdjacent", "allAdjacentFoes")


class FakeMechanics:
	SPECIES = {
		"Incineroar": {"types": ["Fire", "Dark"], "atk": 115, "spa": 80, "def": 90, "spd": 90},
		"Sneasler": {"types": ["Fighting", "Poison"], "atk": 130, "spa": 40, "def": 60, "spd": 80},
		"Gengar": {"types": ["Ghost", "Poison"], "atk": 65, "spa": 130, "def": 60, "spd": 80},
		"Pelipper": {"types": ["Water", "Flying"], "atk": 50, "spa": 95, "def": 100, "spd": 70},
	}
	MOVES = {
		"heatwave": FakeMove("heatwave", "Fire", "Special", 95, target="allAdjacentFoes"),
		"fakeout": FakeMove("fakeout", "Normal", "Physical", 40, priority=3),
		"closecombat": FakeMove("closecombat", "Fighting", "Physical", 120),
		"shadowball": FakeMove("shadowball", "Ghost", "Special", 80),
		"willowisp": FakeMove("willowisp", "Fire", "Status", 0, status="brn"),
		"hydropump": FakeMove("hydropump", "Water", "Special", 110),
		"tailwind": FakeMove("tailwind", "Flying", "Status", 0, side_condition="tailwind"),
		"protect": FakeMove("protect", "Normal", "Status", 0),
		"blizzard": FakeMove("blizzard", "Ice", "Special", 110, target="allAdjacentFoes"),
		"freezedry": FakeMove("freezedry", "Ice", "Special", 70),
		"calmmind": FakeMove("calmmind", "Psychic", "Status", 0, self_boosts=(("spa", 1), ("spd", 1))),
		"bodypress": FakeMove("bodypress", "Fighting", "Physical", 80, override_offensive_stat="def"),
		"irondefense": FakeMove("irondefense", "Steel", "Status", 0, self_boosts=(("def", 2),)),
		"auroraveil": FakeMove("auroraveil", "Ice", "Status", 0, side_condition="auroraveil"),
		"followme": FakeMove("followme", "Normal", "Status", 0, priority=2),
		"encore": FakeMove("encore", "Normal", "Status", 0),
	}

	def require_champions_format(self):
		return self

	def move(self, value):
		key = "".join(character.lower() for character in value if character.isalnum())
		if key not in self.MOVES:
			raise KeyError(key)
		return self.MOVES[key]

	def species(self, value):
		if value not in self.SPECIES:
			raise KeyError(value)
		data = self.SPECIES[value]
		return SimpleNamespace(types=tuple(data["types"]), stats={key: data[key] for key in ("atk", "spa", "def", "spd")})

	def ability_bypasses_accuracy(self, value):
		return value == "noguard"

	def semantic(self, category, value):
		key = "".join(character.lower() for character in value if character.isalnum())
		if category == "moves" and key == "protect":
			return {"protection_move": True}
		return {}

	def move_multiplier(self, move, defending_types):
		move = self.move(move) if isinstance(move, str) else move
		result = 1.0
		for defending in defending_types:
			result *= self._single_multiplier(move.type, defending, move.id)
		return result

	def _single_multiplier(self, attack, defense, move_id):
		if move_id == "freezedry" and defense == "Water":
			return 2.0
		if attack == "Fighting" and defense in ("Ice", "Steel", "Dark", "Normal"):
			return 2.0
		if attack == "Fighting" and defense == "Ghost":
			return 0.0
		if attack == "Fire" and defense in ("Ice", "Steel"):
			return 2.0
		if attack == "Ghost" and defense == "Ghost":
			return 2.0
		if attack == "Ice" and defense in ("Flying", "Ground", "Grass", "Dragon"):
			return 2.0
		if attack == "Ice" and defense in ("Fire", "Steel"):
			return 0.5
		if attack == "Water" and defense == "Fire":
			return 2.0
		return 1.0


class ThreatModelTests(unittest.TestCase):
	def test_baseline_threats_are_mechanical_and_capture_spread_priority_and_ko_bands(self):
		mechanics = FakeMechanics()
		knowledge = build_knowledge_state(state_fixture(), mechanics)
		model = build_threat_model(knowledge, mechanics)
		by_move = {threat.move: threat for threat in model.move_threats}

		heat_wave = by_move["heatwave"]
		self.assertTrue(heat_wave.spread)
		self.assertIn(ThreatCategory.SPREAD_DAMAGE, heat_wave.tags)
		self.assertEqual(len(heat_wave.targets), 2)
		self.assertTrue(all(target.damage_band is not DamageBand.UNKNOWN for target in heat_wave.targets))

		fake_out = by_move["fakeout"]
		self.assertIn(ThreatCategory.FAKE_OUT, fake_out.tags)
		self.assertIn(ThreatCategory.PRIORITY_DAMAGE, fake_out.tags)

		close_combat = by_move["closecombat"]
		glaceon_target = next(target for target in close_combat.targets if target.target_id == "team_0")
		self.assertEqual(glaceon_target.effectiveness, 2.0)
		self.assertIn(glaceon_target.ko_confidence, set(KOConfidence))
		self.assertGreater(glaceon_target.estimated_fraction_high, glaceon_target.estimated_fraction_low)

	def test_empirical_public_damage_precedes_coarse_stat_proxy(self):
		state = state_fixture()
		state["history"] += [
			event(1, "move", ["p2b: Sneasler", "Close Combat", "p1a: Glaceon"]),
			event(1, "-damage", ["p1a: Glaceon", "80/160"]),
		]
		mechanics = FakeMechanics()
		knowledge = build_knowledge_state(state, mechanics)
		model = build_threat_model(knowledge, mechanics)
		close_combat = next(threat for threat in model.move_threats if threat.move == "closecombat")
		glaceon_target = next(target for target in close_combat.targets if target.target_id == "team_0")
		self.assertEqual(glaceon_target.estimate_source, "empirical_public_damage")
		self.assertAlmostEqual(glaceon_target.estimated_fraction_mid, 0.5)


class RuntimeStrategyTests(unittest.TestCase):
	def test_glaceon_viability_reacts_to_public_support_and_accuracy_bypass(self):
		mechanics = FakeMechanics()
		strong = assess_runtime_strategy(build_knowledge_state(state_fixture(), mechanics), mechanics)

		weaker_state = state_fixture()
		weaker_state["field"]["weather"] = None
		weaker_state["self"]["side_conditions"] = {}
		weaker_state["opponent"]["team"][0]["ability"] = "noguard"
		weaker_state["opponent"]["active"]["left"]["ability"] = "noguard"
		weak = assess_runtime_strategy(build_knowledge_state(weaker_state, mechanics), mechanics)
		self.assertGreater(strong.scores.glaceon_fortress, weak.scores.glaceon_fortress)

	def test_aggron_burn_and_ghost_pressure_reduce_fortress_viability(self):
		mechanics = FakeMechanics()
		base = assess_runtime_strategy(build_knowledge_state(state_fixture(), mechanics), mechanics)
		state = state_fixture()
		state["self"]["team"][1]["status"] = "brn"
		state["opponent"]["active"]["right"] = active("right", state["opponent"]["team"][2], types=["Ghost", "Poison"])
		state["opponent"]["team"][1] = copy.deepcopy(state["opponent"]["team"][2])
		state["opponent"]["team"][1]["id"] = "opponent_1"
		state["opponent"]["active"]["right"]["team_id"] = "opponent_1"
		weaker = assess_runtime_strategy(build_knowledge_state(state, mechanics), mechanics)
		self.assertGreater(base.scores.aggron_fortress, weaker.scores.aggron_fortress)

	def test_tactical_offense_rises_when_both_opponents_are_in_cleanup_range(self):
		mechanics = FakeMechanics()
		base = assess_runtime_strategy(build_knowledge_state(state_fixture(), mechanics), mechanics)
		state = state_fixture()
		state["opponent"]["active"]["left"]["health"] = health(30, 100, False)
		state["opponent"]["active"]["right"]["health"] = health(25, 100, False)
		cash_out = assess_runtime_strategy(build_knowledge_state(state, mechanics), mechanics)
		self.assertGreater(cash_out.scores.tactical_offense, base.scores.tactical_offense)

	def test_resource_values_are_downstream_and_low_hp_is_not_zero_value(self):
		mechanics = FakeMechanics()
		state = state_fixture()
		state["self"]["team"][2]["health"] = health(1, 100)
		assessment = assess_runtime_strategy(build_knowledge_state(state, mechanics), mechanics)
		resources = {resource.species: resource for resource in assessment.resources}
		self.assertAlmostEqual(hp_utility(0.01), 0.20)
		self.assertGreater(resources["Ninetales-Alola"].value, 0)

		fainted = state_fixture()
		fainted["self"]["team"][2]["health"] = health(0, 100)
		fainted["self"]["team"][2]["fainted"] = True
		assessment = assess_runtime_strategy(build_knowledge_state(fainted, mechanics), mechanics)
		resources = {resource.species: resource for resource in assessment.resources}
		self.assertEqual(resources["Ninetales-Alola"].value, 0)

	def test_clear_primary_plan_uses_configured_margin(self):
		mechanics = FakeMechanics()
		state = state_fixture()
		state["self"]["team"][1]["health"] = health(0, 160)
		state["self"]["team"][1]["fainted"] = True
		assessment = assess_runtime_strategy(build_knowledge_state(state, mechanics), mechanics)
		self.assertEqual(assessment.scores.primary_plan, PlanLabel.GLACEON_FORTRESS.value)


if __name__ == "__main__":
	unittest.main()
