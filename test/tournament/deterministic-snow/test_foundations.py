from __future__ import annotations

import ast
import copy
import json
import math
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
POLICIES = ROOT / "tournament" / "policies"
sys.path.insert(0, str(POLICIES))

from deterministic_snow.actions import canonicalize_legal_action, canonicalize_legal_actions
from deterministic_snow.config import PolicyConfig, default_config
from deterministic_snow.features import FEATURE_REGISTRY, FeatureFamily
from deterministic_snow.knowledge import (
	Certainty,
	KnowledgeSource,
	KnowledgeState,
	SelectedFourStatus,
	build_knowledge_state,
	selected_four_statuses,
)
from deterministic_snow.trace import (
	CandidateActionTrace,
	DecisionTrace,
	FeatureContribution,
	RuntimeStrategyScores,
	TacticalRuleAdjustment,
	TraceLevel,
	TraceRuntime,
	TraceVersions,
)


def health(current=100, maximum=100, exact=True):
	return {"current": current, "max": maximum, "exact": exact, "percent": current / maximum * 100}


def boosts():
	return {"atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0, "accuracy": 0, "evasion": 0}


def own_pokemon(index, species):
	return {
		"id": f"team_{index}", "species": species, "name": species, "health": health(160, 160),
		"status": None, "fainted": False, "level": 50, "item": "leftovers", "ability": "snowcloak",
		"types": ["Ice"], "transformation": None,
		"stats": {"atk": 80, "def": 100, "spa": 130, "spd": 120, "spe": 90}, "boosts": boosts(),
		"moves": [{"id": "protect", "name": "Protect"}], "volatiles": [],
	}


def opponent_pokemon(index, species, ability="pressure"):
	return {
		"id": f"opponent_{index}", "species": species, "name": species, "item": "leftovers",
		"ability": ability, "tera_type": "Water", "nature": "Calm", "gender": "M", "level": 50,
		"moves": [{"id": "protect", "name": "Protect"}, {"id": "tackle", "name": "Tackle"}],
	}


def state_fixture():
	legal_actions = [
		{"actions": {
			"left": {"type": "move", "move": "freezedry", "target": "opponent_left"},
			"right": {"type": "move", "move": "protect"},
		}},
		{"actions": {
			"left": {"type": "move", "move": "freezedry", "target": "opponent_right"},
			"right": {"type": "move", "move": "protect", "transformation": "mega"},
		}},
	]
	return {
		"schema_version": 2,
		"battle": {"format": "gen9championsvgc2026regmb", "mod": "champions", "turn": 3, "phase": "turn"},
		"runtime": {"decision_id": 7, "revision": 0, "attempt": 1, "previous_error": None, "deadline_ms": 4200},
		"self": {
			"name": "Snow", "team": [own_pokemon(0, "Glaceon"), own_pokemon(1, "Aggron")],
			"active": {"left": "team_0", "right": "team_1"},
			"side_conditions": {"auroraveil": {"active": True, "started_turn": 2}},
		},
		"opponent": {
			"name": "Foe",
			"team": [
				opponent_pokemon(0, "Zoroark-Hisui", "illusion"),
				opponent_pokemon(1, "Pelipper", "drizzle"),
				opponent_pokemon(2, "Sneasler", "unburden"),
				opponent_pokemon(3, "Tyranitar", "sandstream"),
				opponent_pokemon(4, "Gourgeist", "frisk"),
				opponent_pokemon(5, "Raichu-Mega-Y", "noguard"),
			],
			"active": {
				"left": {
					"position": "left", "apparent_species": "Pelipper", "team_id": None,
					"health": health(73, 100, False), "status": None, "fainted": False,
					"item": None, "ability": None, "types": None, "transformation": None,
					"boosts": boosts(), "volatiles": [],
				},
				"right": {
					"position": "right", "apparent_species": "Tyranitar", "team_id": "opponent_3",
					"health": health(50, 100, False), "status": "brn", "fainted": False,
					"item": "leftovers", "ability": "sandstream", "types": ["Rock", "Dark"],
					"transformation": None, "boosts": boosts(), "volatiles": ["protect"],
				},
			},
			"side_conditions": {"tailwind": {"active": True, "started_turn": 1}},
		},
		"field": {"weather": "snow", "weather_started_turn": 2, "conditions": {}},
		"request": {
			"kind": "turn", "slots": {}, "legal_actions": legal_actions,
		},
		"history": [{
			"turn": 2, "type": "move",
			"data": {"args": ["p2a: Tyranitar", "Protect", "p2a: Tyranitar"], "kwArgs": {}},
			"raw": "|move|p2a: Tyranitar|Protect|p2a: Tyranitar",
		}],
	}


class KnowledgeStateTests(unittest.TestCase):
	def test_same_schema_v2_state_produces_identical_knowledge(self):
		state = state_fixture()
		first = build_knowledge_state(state)
		second = build_knowledge_state(copy.deepcopy(state))
		self.assertEqual(first, second)
		self.assertEqual(first.to_json(), second.to_json())
		self.assertEqual(first.bot_state_schema_version, 2)

	def test_serialization_reconstruction_is_deterministic(self):
		knowledge = build_knowledge_state(state_fixture())
		reconstructed = KnowledgeState.from_json(knowledge.to_json())
		self.assertEqual(reconstructed, knowledge)
		self.assertEqual(reconstructed.to_json(), knowledge.to_json())

	def test_unknown_illusion_identity_form_and_type_remain_unknown(self):
		active = build_knowledge_state(state_fixture()).opponent_active[0]
		self.assertEqual(active.apparent_identity.value, "Pelipper")
		self.assertEqual(active.apparent_identity.certainty, Certainty.OBSERVED)
		self.assertIsNone(active.established_identity.value)
		self.assertEqual(active.established_identity.certainty, Certainty.UNKNOWN)
		self.assertEqual(active.current_form.certainty, Certainty.UNKNOWN)
		self.assertEqual(active.types.certainty, Certainty.UNKNOWN)

	def test_observed_information_is_not_promoted(self):
		knowledge = build_knowledge_state(state_fixture())
		known = knowledge.opponent_active[1]
		self.assertEqual(known.types.certainty, Certainty.OBSERVED)
		self.assertEqual(known.types.sources, (KnowledgeSource.PUBLIC_SNAPSHOT,))
		self.assertEqual(knowledge.opponent_roster[3].moves[0].sources, (KnowledgeSource.OPEN_TEAM_SHEET,))
		self.assertEqual(len(knowledge.history.move_observations), 1)
		self.assertEqual(knowledge.history.protect_chains, ())

	def test_selected_four_model_expresses_all_states(self):
		roster = [f"opponent_{index}" for index in range(6)]
		possible = selected_four_statuses(roster, ["opponent_0"])
		self.assertEqual(possible["opponent_0"], SelectedFourStatus.CONFIRMED_SELECTED)
		self.assertEqual(possible["opponent_1"], SelectedFourStatus.POSSIBLE_SELECTED)
		complete = selected_four_statuses(roster, roster[:4])
		self.assertEqual(complete["opponent_4"], SelectedFourStatus.CONFIRMED_NOT_SELECTED)


class ConfigurationAndFeatureTests(unittest.TestCase):
	def test_default_config_round_trips_and_rejects_malformed_values(self):
		config = default_config()
		self.assertEqual(PolicyConfig.from_json(config.to_json()), config)

		unknown = config.to_dict()
		unknown["weights"]["NOT_A_FEATURE"] = 1
		with self.assertRaisesRegex(ValueError, "Feature weight IDs"):
			PolicyConfig.from_dict(unknown)

		missing = config.to_dict()
		del missing["weights"]["OPPONENT_DAMAGE"]
		with self.assertRaisesRegex(ValueError, "Feature weight IDs"):
			PolicyConfig.from_dict(missing)

		invalid_number = config.to_dict()
		invalid_number["weights"]["OPPONENT_DAMAGE"] = math.nan
		with self.assertRaisesRegex(ValueError, "finite"):
			PolicyConfig.from_dict(invalid_number)

		invalid_runtime = config.to_dict()
		invalid_runtime["runtime"]["medium_mode_minimum_ms"] = 2000
		with self.assertRaisesRegex(ValueError, "descend"):
			PolicyConfig.from_dict(invalid_runtime)

		invalid_role = config.to_dict()
		invalid_role["team_roles"][0]["species"] = 123
		with self.assertRaisesRegex(ValueError, "species"):
			PolicyConfig.from_dict(invalid_role)

	def test_feature_ids_are_stable_unique_and_cover_required_families(self):
		expected_ids = [
			"OPPONENT_DAMAGE", "OPPONENT_KO", "FREE_TURN_CONVERSION", "OWN_RESOURCE_SURVIVAL",
			"DETERMINISTIC_PROTECTION", "SPREAD_PREVENTION", "PRIMARY_WINCON_SURVIVAL",
			"WIN_CONDITION_PROGRESS", "WEATHER_CONTROL_GAIN", "SAFE_SWITCH",
			"SACRIFICIAL_PIVOT_VALUE", "CONTROL_GAIN", "OPPONENT_SETUP_ALLOWED", "RNG_DEPENDENCE",
			"MECHANIC_UNCERTAINTY", "FRAGILE_PREDICTION", "JOINT_ACTION_COORDINATION",
			"ROBUST_ACROSS_RESPONSES",
		]
		self.assertEqual([feature.id for feature in FEATURE_REGISTRY], expected_ids)
		self.assertEqual(len(expected_ids), len(set(expected_ids)))
		self.assertEqual({feature.family for feature in FEATURE_REGISTRY}, set(FeatureFamily))


class CanonicalActionAndTraceTests(unittest.TestCase):
	def test_action_ids_are_stable_and_distinguish_target_and_mega(self):
		state = state_fixture()
		first = canonicalize_legal_actions(state)
		second = canonicalize_legal_actions(copy.deepcopy(state))
		self.assertEqual(first, second)
		self.assertNotEqual(first[0].action_id, first[1].action_id)

		base = {"actions": {"left": {"type": "move", "move": "bodypress", "target": "opponent_left"}}}
		mega = copy.deepcopy(base)
		mega["actions"]["left"]["transformation"] = "mega"
		right_target = copy.deepcopy(base)
		right_target["actions"]["left"]["target"] = "opponent_right"
		self.assertEqual(canonicalize_legal_action(base), canonicalize_legal_action(copy.deepcopy(base)))
		self.assertEqual(len({
			canonicalize_legal_action(base).action_id,
			canonicalize_legal_action(mega).action_id,
			canonicalize_legal_action(right_target).action_id,
		}), 3)

		preview_a = canonicalize_legal_action({"team": ["team_0", "team_1", "team_2", "team_3"]})
		preview_b = canonicalize_legal_action({"team": ["team_1", "team_0", "team_2", "team_3"]})
		self.assertNotEqual(preview_a.action_id, preview_b.action_id)

	def test_decision_trace_serializes_cleanly(self):
		action = canonicalize_legal_actions(state_fixture())[0]
		contribution = FeatureContribution("DETERMINISTIC_PROTECTION", 1, 50, 50)
		candidate = CandidateActionTrace(
			action, 20, -5, 50, 24, (), (contribution,),
			(TacticalRuleAdjustment("FOLLOW_ME_RESCUE", 4, "Preserves a critical ally"),),
		)
		trace = DecisionTrace(
			1, TraceLevel.TOP_CANDIDATES, 7, 3,
			TraceVersions("snow-policy-b1", "b1-defaults-v1", "untrained-v1", "schema-v2", "champions-snow-v1", "gen9championsvgc2026regmb", "champions"),
			RuntimeStrategyScores(80, 40, 30, "GLACEON_FORTRESS"), (), (), (candidate,), action.action_id,
			TraceRuntime(1.5, 1, 0, 0),
		)
		serialized = trace.to_json()
		self.assertEqual(json.loads(serialized)["selected_action_id"], action.action_id)
		self.assertEqual(DecisionTrace.from_json(serialized), trace)
		self.assertEqual(DecisionTrace.from_json(serialized).to_json(), serialized)


class InformationBoundaryTests(unittest.TestCase):
	def test_policy_package_has_no_simulator_or_omniscient_imports(self):
		policy_root = POLICIES / "deterministic_snow"
		for source_path in policy_root.glob("*.py"):
			tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
			for node in ast.walk(tree):
				if isinstance(node, ast.Import):
					modules = [alias.name for alias in node.names]
				elif isinstance(node, ast.ImportFrom):
					modules = [node.module or ""]
				else:
					continue
				for module in modules:
					self.assertFalse(module == "sim" or module.startswith("sim."), f"Simulator import in {source_path}")
			source = source_path.read_text(encoding="utf-8")
			self.assertNotIn("BattleStream", source)
			self.assertNotIn("liveBattle", source)


if __name__ == "__main__":
	unittest.main()
