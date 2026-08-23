from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from types import SimpleNamespace
import unittest

from test_b6_responses import b6_state, event, packed_sheet

from deterministic_snow import build_knowledge_state
from deterministic_snow.actions import canonicalize_legal_action
from deterministic_snow.projection import (
	ProjectionConfig,
	ProjectionContractError,
	ProjectionUncertainty,
	project_turn,
)
from deterministic_snow.responses import (
	OpponentActionKind,
	OpponentActionRole,
	OpponentIndividualAction,
	OpponentJointResponse,
	ResponseArchetype,
)


@dataclass(frozen=True)
class ProjectionMove:
	id: str
	type: str
	category: str
	base_power: int
	accuracy: int | bool = 100
	priority: int = 0
	target: str = "normal"
	flags: tuple[str, ...] = ("protect",)
	boosts: tuple[tuple[str, int], ...] = ()
	self_boosts: tuple[tuple[str, int], ...] = ()
	status: str | None = None
	volatile_status: str | None = None
	side_condition: str | None = None
	weather: str | None = None
	terrain: str | None = None
	pseudo_weather: str | None = None
	heal: tuple[int, ...] | None = None
	drain: tuple[int, ...] | None = None
	recoil: tuple[int, ...] | None = None
	force_switch: bool = False
	self_switch: str | bool | None = None
	breaks_protect: bool = False
	override_offensive_stat: str | None = None
	override_defensive_stat: str | None = None
	ignore_accuracy: bool = False
	ignore_evasion: bool = False
	callback_names: tuple[str, ...] = ()

	@property
	def is_spread(self):
		return self.target in ("allAdjacent", "allAdjacentFoes")


@dataclass(frozen=True)
class ProjectionSpecies:
	name: str
	base_species: str
	types: tuple[str, ...]
	stats: dict[str, int]
	abilities: tuple[tuple[str, str], ...]
	weight_kg: float
	is_mega: bool = False


class ProjectionMechanics:
	SPECIES = {
		"Glaceon": ProjectionSpecies("Glaceon", "Glaceon", ("Ice",), {"hp": 65, "atk": 60, "def": 110, "spa": 130, "spd": 95, "spe": 65}, (("0", "snowcloak"),), 25.9),
		"Ninetales-Alola": ProjectionSpecies("Ninetales-Alola", "Ninetales", ("Ice", "Fairy"), {"hp": 73, "atk": 67, "def": 75, "spa": 81, "spd": 100, "spe": 109}, (("0", "snowwarning"),), 19.9),
		"Maushold": ProjectionSpecies("Maushold", "Maushold", ("Normal",), {"hp": 74, "atk": 75, "def": 70, "spa": 65, "spd": 75, "spe": 111}, (("0", "friendguard"),), 2.3),
		"Aggron": ProjectionSpecies("Aggron", "Aggron", ("Steel", "Rock"), {"hp": 70, "atk": 110, "def": 180, "spa": 60, "spd": 60, "spe": 50}, (("0", "sturdy"),), 360.0),
		"Aggron-Mega": ProjectionSpecies("Aggron-Mega", "Aggron", ("Steel",), {"hp": 70, "atk": 140, "def": 230, "spa": 60, "spd": 80, "spe": 50}, (("0", "filter"),), 395.0, True),
		"Armarouge": ProjectionSpecies("Armarouge", "Armarouge", ("Fire", "Psychic"), {"hp": 85, "atk": 60, "def": 100, "spa": 125, "spd": 80, "spe": 75}, (("0", "flashfire"),), 85.0),
		"Heliolisk": ProjectionSpecies("Heliolisk", "Heliolisk", ("Electric", "Normal"), {"hp": 62, "atk": 55, "def": 52, "spa": 109, "spd": 94, "spe": 109}, (("0", "dryskin"),), 21.0),
		"Incineroar": ProjectionSpecies("Incineroar", "Incineroar", ("Fire", "Dark"), {"hp": 95, "atk": 115, "def": 90, "spa": 80, "spd": 90, "spe": 60}, (("0", "intimidate"),), 83.0),
		"Sneasler": ProjectionSpecies("Sneasler", "Sneasler", ("Fighting", "Poison"), {"hp": 80, "atk": 130, "def": 60, "spa": 40, "spd": 80, "spe": 120}, (("0", "unburden"),), 43.0),
		"Gengar": ProjectionSpecies("Gengar", "Gengar", ("Ghost", "Poison"), {"hp": 60, "atk": 65, "def": 60, "spa": 130, "spd": 75, "spe": 110}, (("0", "cursedbody"),), 40.5),
		"Gengar-Mega": ProjectionSpecies("Gengar-Mega", "Gengar", ("Ghost", "Poison"), {"hp": 60, "atk": 65, "def": 80, "spa": 170, "spd": 95, "spe": 130}, (("0", "shadowtag"),), 40.5, True),
		"Pelipper": ProjectionSpecies("Pelipper", "Pelipper", ("Water", "Flying"), {"hp": 60, "atk": 50, "def": 100, "spa": 95, "spd": 70, "spe": 65}, (("0", "drizzle"),), 28.0),
		"Raichu": ProjectionSpecies("Raichu", "Raichu", ("Electric",), {"hp": 60, "atk": 90, "def": 55, "spa": 90, "spd": 80, "spe": 110}, (("0", "lightningrod"),), 30.0),
		"Amoonguss": ProjectionSpecies("Amoonguss", "Amoonguss", ("Grass", "Poison"), {"hp": 114, "atk": 85, "def": 70, "spa": 85, "spd": 80, "spe": 30}, (("0", "regenerator"),), 10.5),
	}

	MOVES = {
		"followme": ProjectionMove("followme", "Normal", "Status", 0, priority=2, target="self"),
		"fakeout": ProjectionMove("fakeout", "Normal", "Physical", 40, priority=3),
		"closecombat": ProjectionMove("closecombat", "Fighting", "Physical", 120),
		"bodypress": ProjectionMove("bodypress", "Fighting", "Physical", 80, override_offensive_stat="def"),
		"protect": ProjectionMove("protect", "Normal", "Status", 0, priority=4, target="self"),
		"wideguard": ProjectionMove("wideguard", "Rock", "Status", 0, priority=3, target="allies"),
		"heatwave": ProjectionMove("heatwave", "Fire", "Special", 95, target="allAdjacentFoes"),
		"weatherball": ProjectionMove("weatherball", "Normal", "Special", 50, callback_names=("onModifyType", "onBasePower")),
		"calmmind": ProjectionMove("calmmind", "Psychic", "Status", 0, target="self", self_boosts=(("spa", 1), ("spd", 1))),
		"allyswitch": ProjectionMove("allyswitch", "Psychic", "Status", 0, priority=2, target="self"),
		"shadowball": ProjectionMove("shadowball", "Ghost", "Special", 80),
		"thunderbolt": ProjectionMove("thunderbolt", "Electric", "Special", 90),
		"auroraveil": ProjectionMove("auroraveil", "Ice", "Status", 0, target="allySide", side_condition="auroraveil"),
		"blizzard": ProjectionMove("blizzard", "Ice", "Special", 110, target="allAdjacentFoes"),
		"wish": ProjectionMove("wish", "Normal", "Status", 0, target="self"),
		"encore": ProjectionMove("encore", "Normal", "Status", 0),
		"mudslap": ProjectionMove("mudslap", "Ground", "Special", 20, boosts=(("accuracy", -1),)),
		"grassknot": ProjectionMove("grassknot", "Grass", "Special", 0, callback_names=("basePowerCallback",)),
		"heavyslam": ProjectionMove("heavyslam", "Steel", "Physical", 0, callback_names=("basePowerCallback",)),
		"irondefense": ProjectionMove("irondefense", "Steel", "Status", 0, target="self", self_boosts=(("def", 2),)),
	}

	def require_champions_format(self):
		return self

	def species(self, value):
		key = str(value)
		if key in self.SPECIES:
			return self.SPECIES[key]
		for species in self.SPECIES.values():
			if self._id(species.name) == self._id(key):
				return species
		raise KeyError(value)

	def move(self, value):
		key = self._id(str(value))
		if key not in self.MOVES:
			raise KeyError(value)
		return self.MOVES[key]

	def semantic(self, category, value):
		key = self._id(str(value))
		if category == "moves":
			return {
				"followme": {"single_target_redirection": True},
				"fakeout": {"first_turn_only": True, "causes_flinch": True},
				"protect": {"protection_move": True},
				"wideguard": {"spread_protection": True},
				"allyswitch": {"swaps_active_positions": True, "repeated_use_can_fail": True},
				"auroraveil": {"requires_weather": ["hail", "snowscape"], "side_condition": "auroraveil"},
				"wish": {"delayed_heal_fraction": 0.5, "delay_turns": 1},
				"encore": {"locks_last_move": True},
				"mudslap": {"target_accuracy_change": -1},
				"grassknot": {"weight_based_power": True},
				"heavyslam": {"weight_ratio_power": True},
				"blizzard": {"accuracy_by_weather": {"snowscape": True, "hail": True}, "weather_accuracy_fully_modeled": True},
			}.get(key, {})
		if category == "abilities":
			return {
				"snowcloak": {"incoming_accuracy_modifier_in_weather": {"snowscape": [3277, 4096]}},
				"friendguard": {"ally_damage_multiplier": 0.75},
				"filter": {"super_effective_damage_multiplier": 0.75},
				"flashfire": {"fire_immunity": True},
				"dryskin": {"water_immunity_and_heal_fraction": 0.25, "fire_damage_multiplier": 1.25},
				"drizzle": {"entry_weather": "raindance"},
				"snowwarning": {"entry_weather": "snowscape"},
				"lightningrod": {"electric_redirection": True, "electric_immunity": True},
				"noguard": {"accuracy_bypass": True},
			}.get(key, {})
		if category == "items":
			return {
				"brightpowder": {"incoming_accuracy_modifier": [3686, 4096]},
				"focussash": {"survive_full_hp_lethal_hit": True, "consumable": True},
				"chopleberry": {"super_effective_type_damage_multiplier": {"Fighting": 0.5}},
				"colburberry": {"super_effective_type_damage_multiplier": {"Dark": 0.5}},
			}.get(key, {})
		if category == "field" and key == "gravity":
			return {"accuracy_multiplier_ratio": [6840, 4096], "grounds_flying": True}
		return {}

	def form_after_item_transformation(self, species, item):
		key = (self._id(species), self._id(item))
		if key == ("aggron", "aggronite"):
			return self.SPECIES["Aggron-Mega"]
		if key == ("gengar", "gengarite"):
			return self.SPECIES["Gengar-Mega"]
		return None

	def move_multiplier(self, move, defending_types):
		move = self.move(move) if isinstance(move, str) else move
		result = 1.0
		for defending in defending_types:
			result *= self._single(move.type, defending)
		return result

	def wide_guard_blocks(self, move):
		move = self.move(move) if isinstance(move, str) else move
		return bool(move.is_spread and not move.breaks_protect and "protect" in move.flags)

	def weather_grants_perfect_accuracy(self, move, weather):
		move = self.move(move) if isinstance(move, str) else move
		if not weather:
			return False
		mapping = self.semantic("moves", move.id).get("accuracy_by_weather", {})
		return any(self._id(name) == self._id(weather) and value is True for name, value in mapping.items())

	def ability_bypasses_accuracy(self, ability):
		return self.semantic("abilities", ability).get("accuracy_bypass") is True

	@staticmethod
	def _id(value):
		return "".join(character.lower() for character in value if character.isalnum())

	def _single(self, attack, defense):
		attack = self._id(attack)
		defense = self._id(defense)
		if (attack, defense) in {("ghost", "normal"), ("fighting", "ghost"), ("electric", "ground")}:
			return 0.0
		if (attack, defense) in {
			("fighting", "ice"), ("fighting", "steel"), ("fighting", "rock"), ("fighting", "dark"), ("fighting", "normal"),
			("fire", "ice"), ("fire", "steel"), ("steel", "rock"), ("steel", "ice"), ("steel", "fairy"),
			("grass", "water"), ("grass", "ground"), ("grass", "rock"), ("electric", "water"), ("electric", "flying"),
			("ghost", "ghost"), ("ghost", "psychic"), ("psychic", "poison"), ("psychic", "fighting"),
		}:
			return 2.0
		if (attack, defense) in {
			("fire", "fire"), ("fire", "water"), ("fire", "rock"), ("steel", "fire"), ("steel", "water"),
			("grass", "fire"), ("grass", "grass"), ("grass", "poison"), ("grass", "flying"),
		}:
			return 0.5
		return 1.0


def hp(current=160, maximum=160):
	return {"current": current, "max": maximum, "exact": True, "percent": current / maximum * 100}


def boosts(**changes):
	value = {"atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0, "accuracy": 0, "evasion": 0}
	value.update(changes)
	return value


def own(index, species, item, ability, types, moves, *, current=160, maximum=160, stats=None):
	base = ProjectionMechanics.SPECIES[species].stats
	stats = stats or {
		"atk": base["atk"] + 40, "def": base["def"] + 40, "spa": base["spa"] + 40,
		"spd": base["spd"] + 40, "spe": base["spe"] + 40,
	}
	return {
		"id": f"team_{index}", "species": species, "name": species.split("-")[0],
		"health": hp(current, maximum), "status": None, "fainted": current <= 0, "level": 50,
		"item": item, "ability": ability, "types": types, "transformation": None,
		"stats": stats, "boosts": boosts(),
		"moves": [{"id": move, "name": move} for move in moves], "volatiles": [],
	}


def own_six():
	return [
		own(0, "Glaceon", "brightpowder", "snowcloak", ["Ice"], ["calmmind", "blizzard", "wish", "protect"]),
		own(1, "Ninetales-Alola", "icyrock", "snowwarning", ["Ice", "Fairy"], ["auroraveil", "blizzard", "encore", "protect"]),
		own(2, "Maushold", "chopleberry", "friendguard", ["Normal"], ["followme", "mudslap", "encore", "protect"]),
		own(3, "Aggron", "aggronite", "sturdy", ["Steel", "Rock"], ["irondefense", "bodypress", "heavyslam", "protect"], stats={"atk": 120, "def": 220, "spa": 60, "spd": 100, "spe": 70}),
		own(4, "Armarouge", "colburberry", "flashfire", ["Fire", "Psychic"], ["wideguard", "allyswitch", "calmmind", "protect"]),
		own(5, "Heliolisk", "focussash", "dryskin", ["Electric", "Normal"], ["thunderbolt", "grassknot", "allyswitch", "protect"]),
	]


def opponent_active(position, pokemon, *, current=100, maximum=100):
	species = ProjectionMechanics.SPECIES[pokemon["species"]]
	return {
		"position": position, "apparent_species": pokemon["species"], "team_id": pokemon["id"],
		"health": hp(current, maximum), "status": None, "fainted": current <= 0,
		"item": pokemon["item"], "ability": pokemon["ability"], "types": list(species.types),
		"transformation": None, "boosts": boosts(), "volatiles": [],
	}


def state_with(own_left, own_right, opponent_left=0, opponent_right=1):
	state = b6_state()
	state["self"]["team"] = own_six()
	state["self"]["active"] = {"left": own_left, "right": own_right}
	foes = state["opponent"]["team"]
	state["opponent"]["active"] = {
		"left": opponent_active("left", foes[opponent_left]),
		"right": opponent_active("right", foes[opponent_right]),
	}
	state["field"] = {"weather": "snowscape", "weather_started_turn": 1, "conditions": {}}
	state["self"]["side_conditions"] = {}
	state["opponent"]["side_conditions"] = {}
	state["request"] = {"kind": "turn", "slots": {}, "legal_actions": []}
	return state


def make_candidate(state, actions, mechanics):
	state = copy.deepcopy(state)
	state["request"] = {"kind": "turn", "slots": {}, "legal_actions": [{"actions": actions}]}
	knowledge = build_knowledge_state(state, mechanics)
	return knowledge, knowledge.legal_actions[0]


def move_response(actor_position, actor_id, move, target_position=None, target_id=None):
	return OpponentIndividualAction(
		actor_position, actor_id, OpponentActionKind.MOVE, move, None,
		target_position, target_id, (OpponentActionRole.DAMAGE,), 1.0, (),
	)


def switch_response(actor_position, actor_id, switch_to):
	return OpponentIndividualAction(
		actor_position, actor_id, OpponentActionKind.SWITCH, None, switch_to,
		None, None, (OpponentActionRole.SWITCH,), 1.0, (),
	)


def joint(*actions):
	return OpponentJointResponse((ResponseArchetype.BALANCED,), tuple(actions), 1.0, 1.0, ())


class B7ProjectionTests(unittest.TestCase):
	def setUp(self):
		self.mechanics = ProjectionMechanics()

	def test_projection_config_validates_branch_limit(self):
		with self.assertRaises(ValueError):
			replace(ProjectionConfig(), max_projection_branches=0).validate()

	def test_candidate_must_be_harness_legal(self):
		state = state_with("team_2", "team_3")
		knowledge, _ = make_candidate(state, {
			"left": {"type": "move", "move": "followme"},
			"right": {"type": "move", "move": "protect"},
		}, self.mechanics)
		other = canonicalize_legal_action({"actions": {
			"left": {"type": "move", "move": "protect"},
			"right": {"type": "move", "move": "protect"},
		}})
		with self.assertRaises(ProjectionContractError):
			project_turn(knowledge, self.mechanics, other, joint(
				move_response("right", "opponent_1", "closecombat", "right", "team_3")
			))

	def test_fake_out_before_follow_me_denies_redirection(self):
		state = state_with("team_2", "team_3")
		knowledge, candidate = make_candidate(state, {
			"left": {"type": "move", "move": "followme"},
			"right": {"type": "move", "move": "bodypress", "target": "opponent_right"},
		}, self.mechanics)
		result = project_turn(knowledge, self.mechanics, candidate, joint(
			move_response("left", "opponent_0", "fakeout", "left", "team_2"),
			move_response("right", "opponent_1", "closecombat", "right", "team_3"),
		))
		for outcome in result.outcomes:
			follow = next(record for record in outcome.action_records if record.actor_id == "team_2" and record.action == "followme")
			close_combat = next(record for record in outcome.action_records if record.action == "closecombat")
			self.assertEqual(follow.blocked_by, "flinch")
			self.assertEqual(close_combat.final_target_id, "team_3")

	def test_follow_me_redirects_close_combat_from_aggron(self):
		state = state_with("team_2", "team_3")
		knowledge, candidate = make_candidate(state, {
			"left": {"type": "move", "move": "followme"},
			"right": {"type": "move", "move": "protect"},
		}, self.mechanics)
		result = project_turn(knowledge, self.mechanics, candidate, joint(
			move_response("right", "opponent_1", "closecombat", "right", "team_3")
		))
		for outcome in result.outcomes:
			record = next(record for record in outcome.action_records if record.action == "closecombat")
			self.assertEqual(record.original_target_id, "team_3")
			self.assertEqual(record.final_target_id, "team_2")
			self.assertTrue(record.redirected)

	def test_ghost_switch_blanks_body_press(self):
		state = state_with("team_3", "team_2")
		knowledge, candidate = make_candidate(state, {
			"left": {"type": "move", "move": "bodypress", "target": "opponent_left"},
			"right": {"type": "move", "move": "protect"},
		}, self.mechanics)
		result = project_turn(knowledge, self.mechanics, candidate, joint(
			switch_response("left", "opponent_0", "opponent_2")
		))
		for outcome in result.outcomes:
			damage = [change for change in outcome.opponent_hp_changes if change.pokemon_id == "opponent_2"]
			self.assertTrue(damage)
			self.assertEqual(damage[0].high_fraction, 0.0)

	def test_wide_guard_blocks_spread_but_not_single_target(self):
		state = state_with("team_4", "team_5", 0, 3)
		knowledge, candidate = make_candidate(state, {
			"left": {"type": "move", "move": "wideguard"},
			"right": {"type": "move", "move": "thunderbolt", "target": "opponent_right"},
		}, self.mechanics)
		result = project_turn(knowledge, self.mechanics, candidate, joint(
			move_response("left", "opponent_0", "heatwave"),
			move_response("right", "opponent_3", "weatherball", "left", "team_4"),
		))
		for outcome in result.outcomes:
			heat = [record for record in outcome.action_records if record.action == "heatwave"]
			weather = next(record for record in outcome.action_records if record.action == "weatherball")
			self.assertTrue(heat)
			self.assertTrue(all(record.blocked_by == "wideguard" for record in heat))
			self.assertNotEqual(weather.blocked_by, "wideguard")

	def test_weather_switch_happens_before_aurora_veil(self):
		state = state_with("team_1", "team_0", 1, 0)
		knowledge, candidate = make_candidate(state, {
			"left": {"type": "move", "move": "auroraveil"},
			"right": {"type": "move", "move": "protect"},
		}, self.mechanics)
		result = project_turn(knowledge, self.mechanics, candidate, joint(
			switch_response("left", "opponent_1", "opponent_3"),
			move_response("right", "opponent_0", "protect"),
		))
		for outcome in result.outcomes:
			self.assertEqual(outcome.projected_weather, "raindance")
			self.assertNotIn("auroraveil", outcome.projected_own_side_conditions)

	def test_mega_aggron_transforms_before_incoming_close_combat(self):
		state = state_with("team_2", "team_3")
		knowledge_base, base = make_candidate(state, {
			"left": {"type": "move", "move": "protect"},
			"right": {"type": "move", "move": "bodypress", "target": "opponent_right"},
		}, self.mechanics)
		knowledge_mega, mega = make_candidate(state, {
			"left": {"type": "move", "move": "protect"},
			"right": {"type": "move", "move": "bodypress", "target": "opponent_right", "transformation": "mega"},
		}, self.mechanics)
		response = joint(move_response("right", "opponent_1", "closecombat", "right", "team_3"))
		base_result = project_turn(knowledge_base, self.mechanics, base, response)
		mega_result = project_turn(knowledge_mega, self.mechanics, mega, response)
		base_damage = max(change.mid_fraction for outcome in base_result.outcomes for change in outcome.own_hp_changes if change.pokemon_id == "team_3")
		mega_damage = max(change.mid_fraction for outcome in mega_result.outcomes for change in outcome.own_hp_changes if change.pokemon_id == "team_3")
		self.assertLess(mega_damage, base_damage)

	def test_ally_switch_changes_slot_target_into_ghost_immunity(self):
		state = state_with("team_4", "team_5", 2, 1)
		knowledge, candidate = make_candidate(state, {
			"left": {"type": "move", "move": "allyswitch"},
			"right": {"type": "move", "move": "thunderbolt", "target": "opponent_right"},
		}, self.mechanics)
		result = project_turn(knowledge, self.mechanics, candidate, joint(
			move_response("left", "opponent_2", "shadowball", "left", "team_4")
		))
		for outcome in result.outcomes:
			record = next(record for record in outcome.action_records if record.action == "shadowball")
			self.assertEqual(record.original_target_id, "team_4")
			self.assertEqual(record.final_target_id, "team_5")
			self.assertTrue(record.redirected)
			damage = [change for change in outcome.own_hp_changes if change.pokemon_id == "team_5"]
			self.assertTrue(damage)
			self.assertEqual(damage[0].high_fraction, 0.0)

	def test_weight_based_moves_have_projected_damage(self):
		state = state_with("team_3", "team_5", 0, 3)
		knowledge, candidate = make_candidate(state, {
			"left": {"type": "move", "move": "heavyslam", "target": "opponent_left"},
			"right": {"type": "move", "move": "grassknot", "target": "opponent_right"},
		}, self.mechanics)
		result = project_turn(knowledge, self.mechanics, candidate, joint(
			move_response("left", "opponent_0", "heatwave")
		))
		changes = [change for outcome in result.outcomes for change in outcome.opponent_hp_changes]
		self.assertTrue(any(change.pokemon_id == "opponent_0" and change.mid_fraction > 0 for change in changes))
		self.assertTrue(any(change.pokemon_id == "opponent_3" and change.mid_fraction > 0 for change in changes))

	def test_previous_turn_wish_resolves_at_end_of_turn(self):
		state = state_with("team_0", "team_2")
		state["self"]["team"][0]["health"] = hp(80, 160)
		state["history"].append(event(2, "move", ["p1a: Glaceon", "Wish", "p1a: Glaceon"]))
		knowledge, candidate = make_candidate(state, {
			"left": {"type": "move", "move": "protect"},
			"right": {"type": "move", "move": "protect"},
		}, self.mechanics)
		result = project_turn(knowledge, self.mechanics, candidate, joint(
			move_response("right", "opponent_1", "protect")
		))
		self.assertTrue(all(any(change.status == "wish_heal" for change in outcome.status_changes) for outcome in result.outcomes))

	def test_publicly_possible_opponent_mega_branches_projection(self):
		state = state_with("team_0", "team_2", 2, 1)
		state["opponent"]["team"][2]["item"] = "gengarite"
		state["opponent"]["active"]["left"]["item"] = "gengarite"
		state["history"][0] = event(0, "showteam", ["p2", packed_sheet(state["opponent"]["team"])])
		knowledge, candidate = make_candidate(state, {
			"left": {"type": "move", "move": "protect"},
			"right": {"type": "move", "move": "protect"},
		}, self.mechanics)
		result = project_turn(knowledge, self.mechanics, candidate, joint(
			move_response("left", "opponent_2", "shadowball", "left", "team_0")
		))
		self.assertGreaterEqual(len(result.outcomes), 2)
		self.assertTrue(all(ProjectionUncertainty.OPPONENT_TRANSFORMATION in outcome.uncertain_interactions for outcome in result.outcomes))


if __name__ == "__main__":
	unittest.main()
