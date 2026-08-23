"""B7 shallow turn projection for the deterministic Champions snow policy.

The projector consumes one harness-provided canonical candidate action and one
candidate-independent B6 opponent response. It models only strategically relevant
ordering/effects and deliberately remains smaller than Pokemon Showdown's simulator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import copy
import math
from typing import Iterable, Mapping

from .actions import CanonicalLegalAction
from .mechanics import MechanicsSnapshot, MoveMechanics, UnresolvedMechanicError, to_id
from .reconstruction import KnowledgeState
from .responses import OpponentActionKind, OpponentJointResponse


class ProjectionContractError(ValueError):
	"""Raised when B7 receives an unsupported or internally inconsistent input."""


class ProjectionConfidence(str, Enum):
	HIGH = "HIGH"
	MEDIUM = "MEDIUM"
	LOW = "LOW"


class ProjectionUncertainty(str, Enum):
	SPEED_ORDER = "SPEED_ORDER"
	OPPONENT_TRANSFORMATION = "OPPONENT_TRANSFORMATION"
	ENTRY_WEATHER_ORDER = "ENTRY_WEATHER_ORDER"
	REPEATED_PROTECT = "REPEATED_PROTECT"
	REPEATED_ALLY_SWITCH = "REPEATED_ALLY_SWITCH"
	UNKNOWN_DYNAMIC_EFFECT = "UNKNOWN_DYNAMIC_EFFECT"
	ACCURACY = "ACCURACY"
	SECONDARY_EFFECT = "SECONDARY_EFFECT"
	SURVIVAL = "SURVIVAL"
	UNKNOWN_BENCH_HP = "UNKNOWN_BENCH_HP"


@dataclass(frozen=True)
class ProjectionConfig:
	version: str = "b7-projection-v1"
	opponent_speed_uncertainty_fraction: float = 0.20
	doubles_screen_multiplier: float = 2.0 / 3.0
	snow_ice_defense_multiplier: float = 1.5
	burn_physical_multiplier: float = 0.5
	spread_damage_multiplier: float = 0.75
	damage_random_low: float = 0.85
	damage_random_mid: float = 0.925
	damage_random_high: float = 1.0
	max_projection_branches: int = 4

	def validate(self) -> None:
		if not isinstance(self.version, str) or not self.version.strip():
			raise ValueError("projection version must be non-empty")
		for name in (
			"opponent_speed_uncertainty_fraction", "doubles_screen_multiplier",
			"snow_ice_defense_multiplier", "burn_physical_multiplier",
			"spread_damage_multiplier", "damage_random_low", "damage_random_mid",
			"damage_random_high",
		):
			value = getattr(self, name)
			if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
				raise ValueError(f"projection.{name} must be a finite non-negative number")
		if not 0 <= self.opponent_speed_uncertainty_fraction <= 1:
			raise ValueError("projection.opponent_speed_uncertainty_fraction must be between zero and one")
		if not (0 < self.damage_random_low <= self.damage_random_mid <= self.damage_random_high):
			raise ValueError("projection damage random multipliers must be positive and ordered")
		if not isinstance(self.max_projection_branches, int) or isinstance(self.max_projection_branches, bool):
			raise ValueError("projection.max_projection_branches must be an integer")
		if self.max_projection_branches < 1:
			raise ValueError("projection.max_projection_branches must be positive")


@dataclass(frozen=True)
class ProjectedHPChange:
	side: str
	pokemon_id: str
	low_fraction: float
	mid_fraction: float
	high_fraction: float
	hit_probability: float
	source: str


@dataclass(frozen=True)
class ProjectedBoostChange:
	side: str
	pokemon_id: str
	stat: str
	stages: int
	source: str


@dataclass(frozen=True)
class ProjectedStatusChange:
	side: str
	pokemon_id: str
	status: str
	kind: str
	source: str


@dataclass(frozen=True)
class ProjectedActionRecord:
	side: str
	actor_id: str
	action: str
	original_target_id: str | None
	final_target_id: str | None
	blocked_by: str | None
	redirected: bool
	hit_probability: float | None
	notes: tuple[str, ...]


@dataclass(frozen=True)
class ProjectedOutcome:
	branch_id: str
	branch_weight: float
	confidence: ProjectionConfidence
	own_hp_changes: tuple[ProjectedHPChange, ...]
	opponent_hp_changes: tuple[ProjectedHPChange, ...]
	own_faints: tuple[str, ...]
	opponent_faints: tuple[str, ...]
	possible_own_faints: tuple[str, ...]
	possible_opponent_faints: tuple[str, ...]
	boost_changes: tuple[ProjectedBoostChange, ...]
	status_changes: tuple[ProjectedStatusChange, ...]
	projected_weather: str | None
	projected_field_conditions: tuple[str, ...]
	projected_own_side_conditions: tuple[str, ...]
	projected_opponent_side_conditions: tuple[str, ...]
	projected_own_positions: tuple[tuple[str, str], ...]
	projected_opponent_positions: tuple[tuple[str, str], ...]
	protected_pokemon: tuple[str, ...]
	wide_guard_sides: tuple[str, ...]
	blocked_actions: tuple[str, ...]
	redirected_actions: tuple[str, ...]
	action_records: tuple[ProjectedActionRecord, ...]
	unresolved_random_effects: tuple[str, ...]
	uncertain_interactions: tuple[ProjectionUncertainty, ...]


@dataclass(frozen=True)
class ProjectionResult:
	config_version: str
	candidate_action_id: str
	response_key: str
	outcomes: tuple[ProjectedOutcome, ...]


@dataclass
class _PokemonState:
	side: str
	position: str
	pokemon_id: str
	species: str
	level: int
	item: str | None
	ability: str | None
	types: tuple[str, ...]
	stats: dict[str, float]
	boosts: dict[str, int]
	status: str | None
	hp_fraction: float
	hp_exact: bool
	max_hp: float | None
	weight_kg: float
	fainted: bool = False

	def speed(self) -> float:
		value = self.stats.get("spe", 1.0) * _stat_stage_multiplier(self.boosts.get("spe", 0))
		if self.status == "par":
			value *= 0.5
		return max(1.0, value)


@dataclass
class _MoveIntent:
	side: str
	actor_id: str
	actor_position: str
	move: MoveMechanics
	target_token: str | None
	target_position: str | None


@dataclass
class _Branch:
	label: str
	weight: float
	weather: str | None
	field_conditions: set[str]
	side_conditions: dict[str, set[str]]
	positions: dict[str, dict[str, _PokemonState]]
	protected: set[str] = field(default_factory=set)
	wide_guard: set[str] = field(default_factory=set)
	redirection: dict[str, str] = field(default_factory=dict)
	flinched: set[str] = field(default_factory=set)
	hp_changes: list[ProjectedHPChange] = field(default_factory=list)
	boost_changes: list[ProjectedBoostChange] = field(default_factory=list)
	status_changes: list[ProjectedStatusChange] = field(default_factory=list)
	action_records: list[ProjectedActionRecord] = field(default_factory=list)
	blocked_actions: list[str] = field(default_factory=list)
	redirected_actions: list[str] = field(default_factory=list)
	random_effects: list[str] = field(default_factory=list)
	uncertainties: set[ProjectionUncertainty] = field(default_factory=set)
	possible_faints: dict[str, set[str]] = field(default_factory=lambda: {"own": set(), "opponent": set()})
	definite_faints: dict[str, set[str]] = field(default_factory=lambda: {"own": set(), "opponent": set()})


def default_projection_config() -> ProjectionConfig:
	config = ProjectionConfig()
	config.validate()
	return config


def project_turn(
	knowledge: KnowledgeState,
	mechanics: MechanicsSnapshot,
	candidate: CanonicalLegalAction,
	response: OpponentJointResponse,
	*,
	config: ProjectionConfig | None = None,
) -> ProjectionResult:
	"""Project one candidate against one B6 response without scoring the result."""
	config = config or default_projection_config()
	config.validate()
	_require_turn_contract(knowledge, candidate, response)
	if hasattr(mechanics, "require_champions_format"):
		mechanics.require_champions_format()

	initial = _build_initial_branch(knowledge, mechanics)
	branches = _apply_voluntary_switches(initial, knowledge, candidate, response, mechanics, config)
	branches = _apply_transformations(branches, knowledge, candidate, response, mechanics, config)
	projected: list[_Branch] = []
	for branch in branches:
		intents = _move_intents(branch, candidate, response, mechanics)
		for ordered, order_uncertain in _move_orders(branch, intents, knowledge, config):
			clone = copy.deepcopy(branch)
			if order_uncertain:
				clone.uncertainties.add(ProjectionUncertainty.SPEED_ORDER)
			for intent in ordered:
				_execute_intent(clone, intent, knowledge, mechanics, config)
			_apply_end_of_turn(clone, knowledge, mechanics)
			projected.append(clone)
			if len(projected) >= config.max_projection_branches:
				break
		if len(projected) >= config.max_projection_branches:
			break

	if not projected:
		raise ProjectionContractError("B7 produced no projection outcomes")
	weight_total = sum(branch.weight for branch in projected) or 1.0
	outcomes = tuple(
		_finalize(branch, index, branch.weight / weight_total)
		for index, branch in enumerate(projected)
	)
	return ProjectionResult(config.version, candidate.action_id, response.canonical_key, outcomes)


def _require_turn_contract(
	knowledge: KnowledgeState,
	candidate: CanonicalLegalAction,
	response: OpponentJointResponse,
) -> None:
	if knowledge.phase != "turn":
		raise ProjectionContractError(f"B7 only supports turn phase, got {knowledge.phase!r}")
	payload = candidate.payload
	if payload.get("kind") != "turn":
		raise ProjectionContractError("B7 candidate must be a canonical turn action")
	legal_ids = {action.action_id for action in knowledge.legal_actions}
	if legal_ids and candidate.action_id not in legal_ids:
		raise ProjectionContractError("B7 candidate must come from request.legal_actions")
	if not response.actions:
		raise ProjectionContractError("B7 requires a non-empty B6 opponent response")


def _build_initial_branch(knowledge: KnowledgeState, mechanics: MechanicsSnapshot) -> _Branch:
	own_by_id = {pokemon.id: pokemon for pokemon in knowledge.own_team}
	roster_by_id = {pokemon.id: pokemon for pokemon in knowledge.opponent_roster}
	own_positions: dict[str, _PokemonState] = {}
	for position, pokemon_id in knowledge.own_active:
		pokemon = own_by_id[pokemon_id]
		own_positions[position] = _own_state(position, pokemon, mechanics)
	opponent_positions: dict[str, _PokemonState] = {}
	for active in knowledge.opponent_active:
		identity = active.established_identity.value
		if not isinstance(identity, str) or identity not in roster_by_id:
			raise ProjectionContractError(f"B7 requires established opponent identity at {active.position}")
		opponent_positions[active.position] = _opponent_active_state(active, roster_by_id[identity], mechanics)
	field_conditions = {condition.id for condition in knowledge.field.conditions if condition.active}
	side_conditions = {
		"own": {condition.id for condition in knowledge.field.own_side_conditions if condition.active},
		"opponent": {condition.id for condition in knowledge.field.opponent_side_conditions if condition.active},
	}
	weather = knowledge.field.weather.value if isinstance(knowledge.field.weather.value, str) else None
	return _Branch(
		"base", 1.0, weather, field_conditions, side_conditions,
		{"own": own_positions, "opponent": opponent_positions},
	)


def _own_state(position, pokemon, mechanics: MechanicsSnapshot) -> _PokemonState:
	species = mechanics.species(pokemon.species)
	return _PokemonState(
		"own", position, pokemon.id, pokemon.species, pokemon.level, pokemon.item, pokemon.ability,
		tuple(pokemon.types), {key: float(value) for key, value in pokemon.stats},
		{key: int(value) for key, value in pokemon.boosts}, pokemon.status,
		max(0.0, pokemon.health.percent / 100.0), bool(pokemon.health.exact), float(pokemon.health.maximum),
		species.weight_kg, bool(pokemon.fainted),
	)


def _opponent_active_state(active, roster, mechanics: MechanicsSnapshot) -> _PokemonState:
	form = active.current_form.value if isinstance(active.current_form.value, str) else roster.species
	try:
		species = mechanics.species(form)
	except KeyError:
		species = mechanics.species(roster.species)
	types = active.types.value
	if not isinstance(types, list) or not all(isinstance(value, str) for value in types):
		types = list(species.types)
	ability = active.ability.value if isinstance(active.ability.value, str) else roster.ability
	item = active.item.value if isinstance(active.item.value, str) else roster.item
	status = active.status.value if isinstance(active.status.value, str) else None
	return _PokemonState(
		"opponent", active.position, roster.id, species.name, roster.level or 50, item, ability,
		tuple(types), {key: float(value + 20) for key, value in species.stats.items()},
		{key: int(value) for key, value in active.boosts}, status,
		max(0.0, active.health.percent / 100.0), bool(active.health.exact),
		float(active.health.maximum) if active.health.maximum > 0 else None, species.weight_kg, bool(active.fainted),
	)


def _opponent_bench_state(position: str, roster, mechanics: MechanicsSnapshot) -> _PokemonState:
	species = mechanics.species(roster.species)
	return _PokemonState(
		"opponent", position, roster.id, roster.species, roster.level or 50, roster.item, roster.ability,
		tuple(species.types), {key: float(value + 20) for key, value in species.stats.items()},
		{}, None, 1.0, False, None, species.weight_kg, False,
	)


def _apply_voluntary_switches(
	branch: _Branch,
	knowledge: KnowledgeState,
	candidate: CanonicalLegalAction,
	response: OpponentJointResponse,
	mechanics: MechanicsSnapshot,
	config: ProjectionConfig,
) -> list[_Branch]:
	branch = copy.deepcopy(branch)
	own_by_id = {pokemon.id: pokemon for pokemon in knowledge.own_team}
	roster_by_id = {pokemon.id: pokemon for pokemon in knowledge.opponent_roster}
	switch_entries: list[_PokemonState] = []

	for position, action in candidate.payload["actions"].items():
		if not action or action.get("type") != "switch":
			continue
		pokemon_id = action["pokemon"]
		if pokemon_id not in own_by_id:
			raise ProjectionContractError(f"Unknown own switch target {pokemon_id}")
		entry = _own_state(position, own_by_id[pokemon_id], mechanics)
		branch.positions["own"][position] = entry
		switch_entries.append(entry)

	for action in response.actions:
		if action.kind is not OpponentActionKind.SWITCH:
			continue
		if not action.switch_to or action.switch_to not in roster_by_id:
			raise ProjectionContractError(f"Unknown opponent switch target {action.switch_to!r}")
		entry = _opponent_bench_state(action.actor_position, roster_by_id[action.switch_to], mechanics)
		branch.positions["opponent"][action.actor_position] = entry
		switch_entries.append(entry)
		branch.uncertainties.add(ProjectionUncertainty.UNKNOWN_BENCH_HP)

	weather_effects: list[str] = []
	for entry in switch_entries:
		semantics = _safe_semantic(mechanics, "abilities", entry.ability)
		weather = semantics.get("entry_weather")
		if isinstance(weather, str) and weather:
			weather_effects.append(weather)
	if not weather_effects:
		return [branch]
	unique = list(dict.fromkeys(weather_effects))
	if len(unique) == 1:
		branch.weather = unique[0]
		return [branch]

	output = []
	for weather in unique[:config.max_projection_branches]:
		clone = copy.deepcopy(branch)
		clone.weather = weather
		clone.weight /= len(unique)
		clone.uncertainties.add(ProjectionUncertainty.ENTRY_WEATHER_ORDER)
		output.append(clone)
	return output


def _apply_transformations(
	branches: list[_Branch],
	knowledge: KnowledgeState,
	candidate: CanonicalLegalAction,
	response: OpponentJointResponse,
	mechanics: MechanicsSnapshot,
	config: ProjectionConfig,
) -> list[_Branch]:
	# Our declared transformation is exact because candidate comes from legal_actions.
	for branch in branches:
		for position, action in candidate.payload["actions"].items():
			if not action or action.get("type") != "move" or not action.get("transformation"):
				continue
			actor = branch.positions["own"].get(position)
			if actor is None:
				continue
			_transform(actor, mechanics)

	# The opponent's B6 response predates B7 and intentionally has no hidden
	# transformation choice. Branch over publicly possible item transformations.
	output: list[_Branch] = []
	for branch in branches:
		if _opponent_already_transformed(knowledge, branch, mechanics):
			output.append(branch)
			continue
		eligible: list[str] = []
		for action in response.actions:
			if action.kind is not OpponentActionKind.MOVE:
				continue
			actor = branch.positions["opponent"].get(action.actor_position)
			if actor is None or not actor.item:
				continue
			try:
				if mechanics.form_after_item_transformation(actor.species, actor.item) is not None:
					eligible.append(action.actor_position)
			except (KeyError, ValueError):
				continue
		if not eligible:
			output.append(branch)
			continue
		variants = [None, *dict.fromkeys(eligible)]
		for selected in variants:
			clone = copy.deepcopy(branch)
			clone.weight /= len(variants)
			clone.uncertainties.add(ProjectionUncertainty.OPPONENT_TRANSFORMATION)
			if selected is not None:
				_transform(clone.positions["opponent"][selected], mechanics)
			output.append(clone)
			if len(output) >= config.max_projection_branches:
				break
		if len(output) >= config.max_projection_branches:
			break
	return output


def _opponent_already_transformed(knowledge: KnowledgeState, branch: _Branch, mechanics: MechanicsSnapshot) -> bool:
	for active in knowledge.opponent_active:
		if active.transformation.value is not None:
			return True
		state = branch.positions["opponent"].get(active.position)
		if state is None:
			continue
		try:
			if mechanics.species(state.species).is_mega:
				return True
		except KeyError:
			continue
	return False


def _transform(actor: _PokemonState, mechanics: MechanicsSnapshot) -> None:
	if not actor.item:
		raise ProjectionContractError(f"{actor.pokemon_id} declared transformation without an item")
	form = mechanics.form_after_item_transformation(actor.species, actor.item)
	if form is None:
		raise ProjectionContractError(f"No item transformation for {actor.species}/{actor.item}")
	try:
		base = mechanics.species(actor.species)
	except KeyError:
		base = form
	for stat in ("atk", "def", "spa", "spd", "spe"):
		current = actor.stats.get(stat)
		old_base = base.stats.get(stat)
		new_base = form.stats.get(stat)
		if current is not None and old_base is not None and new_base is not None:
			actor.stats[stat] = current * (new_base + 20.0) / max(1.0, old_base + 20.0)
	actor.species = form.name
	actor.types = tuple(form.types)
	actor.weight_kg = form.weight_kg
	abilities = dict(form.abilities)
	actor.ability = abilities.get("0") or next(iter(abilities.values()), actor.ability)


def _move_intents(
	branch: _Branch,
	candidate: CanonicalLegalAction,
	response: OpponentJointResponse,
	mechanics: MechanicsSnapshot,
) -> tuple[_MoveIntent, ...]:
	intents: list[_MoveIntent] = []
	for position, action in candidate.payload["actions"].items():
		if not action or action.get("type") != "move":
			continue
		actor = branch.positions["own"].get(position)
		if actor is None or actor.fainted:
			continue
		move = mechanics.move(action["move"])
		target = action.get("target")
		target_position = _own_target_position(position, target)
		intents.append(_MoveIntent("own", actor.pokemon_id, position, move, target, target_position))
	for action in response.actions:
		if action.kind is not OpponentActionKind.MOVE or not action.move:
			continue
		actor = branch.positions["opponent"].get(action.actor_position)
		if actor is None or actor.fainted:
			continue
		move = mechanics.move(action.move)
		intents.append(_MoveIntent(
			"opponent", actor.pokemon_id, action.actor_position, move, None, action.target_position,
		))
	return tuple(intents)


def _own_target_position(actor_position: str, target: str | None) -> str | None:
	if target == "opponent_left":
		return "left"
	if target == "opponent_right":
		return "right"
	if target == "self":
		return actor_position
	if target == "ally":
		return "right" if actor_position == "left" else "left"
	return None


def _move_orders(
	branch: _Branch,
	intents: tuple[_MoveIntent, ...],
	knowledge: KnowledgeState,
	config: ProjectionConfig,
) -> tuple[tuple[tuple[_MoveIntent, ...], bool], ...]:
	if not intents:
		return (((), False),)
	by_priority: dict[int, list[_MoveIntent]] = {}
	for intent in intents:
		by_priority.setdefault(intent.move.priority, []).append(intent)
	orders: list[list[_MoveIntent]] = [[]]
	uncertain_any = False
	trick_room = any(to_id(value) == "trickroom" for value in branch.field_conditions)
	for priority in sorted(by_priority, reverse=True):
		group = by_priority[priority]
		ranked = sorted(group, key=lambda item: (
			_speed_proxy(branch, item, config),
			item.side == "own",
			item.actor_position,
		), reverse=not trick_room)
		ambiguous = _group_has_speed_overlap(branch, ranked, config)
		variants = [ranked]
		if ambiguous and len(ranked) > 1:
			variants.append(list(reversed(ranked)))
			uncertain_any = True
		new_orders = []
		for prefix in orders:
			for variant in variants:
				new_orders.append(prefix + variant)
				if len(new_orders) >= config.max_projection_branches:
					break
			if len(new_orders) >= config.max_projection_branches:
				break
		orders = new_orders
	return tuple((tuple(order), uncertain_any) for order in orders)


def _speed_proxy(branch: _Branch, intent: _MoveIntent, config: ProjectionConfig) -> float:
	actor = _find_actor(branch, intent.side, intent.actor_id)
	if actor is None:
		return 0.0
	value = actor.speed()
	if "tailwind" in {to_id(item) for item in branch.side_conditions[intent.side]}:
		value *= 2.0
	return value


def _speed_interval(branch: _Branch, intent: _MoveIntent, config: ProjectionConfig) -> tuple[float, float]:
	value = _speed_proxy(branch, intent, config)
	if intent.side == "own":
		return value, value
	fraction = config.opponent_speed_uncertainty_fraction
	return value * (1.0 - fraction), value * (1.0 + fraction)


def _group_has_speed_overlap(branch: _Branch, group: list[_MoveIntent], config: ProjectionConfig) -> bool:
	for index, left in enumerate(group):
		left_low, left_high = _speed_interval(branch, left, config)
		for right in group[index + 1:]:
			right_low, right_high = _speed_interval(branch, right, config)
			if max(left_low, right_low) <= min(left_high, right_high):
				return True
	return False


def _execute_intent(
	branch: _Branch,
	intent: _MoveIntent,
	knowledge: KnowledgeState,
	mechanics: MechanicsSnapshot,
	config: ProjectionConfig,
) -> None:
	actor = _find_actor(branch, intent.side, intent.actor_id)
	if actor is None or actor.fainted:
		_record(branch, intent, None, None, "actor unavailable", False, None, ("actor fainted or left field",))
		return
	if actor.pokemon_id in branch.flinched:
		_record(branch, intent, None, None, "flinch", False, None, ("action denied by earlier flinch",))
		branch.blocked_actions.append(f"{intent.side}:{intent.actor_id}:{intent.move.id}:flinch")
		return
	move = intent.move
	semantics = _safe_semantic(mechanics, "moves", move.id)

	if semantics.get("protection_move") is True:
		branch.protected.add(actor.pokemon_id)
		if _protect_chain(actor, knowledge) > 0:
			branch.uncertainties.add(ProjectionUncertainty.REPEATED_PROTECT)
			branch.random_effects.append(f"{actor.pokemon_id}:{move.id}:repeated protection may fail")
		_record(branch, intent, actor.pokemon_id, actor.pokemon_id, None, False, 1.0, ("protection active",))
		return
	if semantics.get("spread_protection") is True:
		branch.wide_guard.add(intent.side)
		_record(branch, intent, actor.pokemon_id, actor.pokemon_id, None, False, 1.0, ("Wide Guard active",))
		return
	if semantics.get("single_target_redirection") is True:
		branch.redirection[intent.side] = actor.pokemon_id
		_record(branch, intent, actor.pokemon_id, actor.pokemon_id, None, False, 1.0, ("redirection active",))
		return
	if semantics.get("swaps_active_positions") is True:
		_swap_positions(branch, intent.side)
		if _last_move_was(actor, move.id, knowledge):
			branch.uncertainties.add(ProjectionUncertainty.REPEATED_ALLY_SWITCH)
			branch.random_effects.append(f"{actor.pokemon_id}:allyswitch:repeated use may fail")
		_record(branch, intent, actor.pokemon_id, actor.pokemon_id, None, False, 1.0, ("active positions swapped",))
		return

	targets = _resolve_targets(branch, intent, mechanics)
	if not targets:
		_apply_non_targeted_effects(branch, intent, actor, semantics, mechanics)
		_record(branch, intent, None, None, None, False, 1.0, ("field/self effect",))
		return

	for target, original_target_id, redirected in targets:
		if target is None or target.fainted:
			continue
		blocked_by = _blocked_by(branch, intent, target, mechanics)
		if blocked_by:
			key = f"{intent.side}:{intent.actor_id}:{move.id}->{target.pokemon_id}"
			branch.blocked_actions.append(key)
			_record(branch, intent, original_target_id, target.pokemon_id, blocked_by, redirected, 1.0, ())
			continue

		hit_probability = _hit_probability(branch, actor, target, move, mechanics)
		if hit_probability < 1.0:
			branch.uncertainties.add(ProjectionUncertainty.ACCURACY)
			branch.random_effects.append(
				f"{intent.side}:{intent.actor_id}:{move.id}->{target.pokemon_id}:hit_probability={hit_probability:.4f}"
			)
		damage = _damage_fraction(branch, actor, target, move, mechanics, config)
		if damage is not None:
			low, mid, high, source = damage
			expected_low = low if hit_probability >= 1.0 else 0.0
			expected_mid = mid * hit_probability
			expected_high = high
			branch.hp_changes.append(ProjectedHPChange(
				target.side, target.pokemon_id, expected_low, expected_mid, expected_high,
				hit_probability, source,
			))
			_apply_hp(branch, target, expected_low, expected_mid, expected_high, hit_probability, move, mechanics)
		elif _is_damaging(move, mechanics):
			branch.uncertainties.add(ProjectionUncertainty.UNKNOWN_DYNAMIC_EFFECT)
			branch.random_effects.append(f"{move.id}:damage unresolved")

		if hit_probability >= 1.0:
			_apply_target_effects(branch, intent, actor, target, move, semantics)
		else:
			if move.status or move.volatile_status or move.boosts:
				branch.uncertainties.add(ProjectionUncertainty.SECONDARY_EFFECT)
		_record(branch, intent, original_target_id, target.pokemon_id, None, redirected, hit_probability, ())

	_apply_self_effects(branch, intent, actor, move)
	_apply_non_targeted_effects(branch, intent, actor, semantics, mechanics, after_targeted=True)


def _resolve_targets(
	branch: _Branch,
	intent: _MoveIntent,
	mechanics: MechanicsSnapshot,
) -> list[tuple[_PokemonState | None, str | None, bool]]:
	move = intent.move
	if move.is_spread:
		target_side = _other_side(intent.side)
		return [
			(target, target.pokemon_id, False)
			for _, target in sorted(branch.positions[target_side].items())
			if not target.fainted
		]
	target_side = _other_side(intent.side)
	if to_id(move.target) in {"self", "adjacentally", "adjacentallyorself"}:
		target_side = intent.side
	original = branch.positions[target_side].get(intent.target_position) if intent.target_position else None
	if original is None:
		return []

	# Follow Me / equivalent active move redirection applies to eligible single-target
	# attacks before ability redirection. B2 can add redirection immunity semantics later.
	if target_side != intent.side and _single_target_redirection_eligible(move):
		redirect_id = branch.redirection.get(target_side)
		if redirect_id:
			redirect = _find_actor(branch, target_side, redirect_id)
			if redirect is not None and not redirect.fainted:
				return [(redirect, original.pokemon_id, redirect.pokemon_id != original.pokemon_id)]
		electric = to_id(move.type) == "electric"
		if electric:
			for target in branch.positions[target_side].values():
				ability = _safe_semantic(mechanics, "abilities", target.ability)
				if ability.get("electric_redirection") is True and not target.fainted:
					return [(target, original.pokemon_id, target.pokemon_id != original.pokemon_id)]
	return [(original, original.pokemon_id, False)]


def _single_target_redirection_eligible(move: MoveMechanics) -> bool:
	return not move.is_spread and to_id(move.target) in {"normal", "any", "adjacentfoe"}


def _blocked_by(
	branch: _Branch,
	intent: _MoveIntent,
	target: _PokemonState,
	mechanics: MechanicsSnapshot,
) -> str | None:
	move = intent.move
	if move.is_spread and target.side in branch.wide_guard:
		try:
			if mechanics.wide_guard_blocks(move):
				return "wideguard"
		except (KeyError, ValueError, UnresolvedMechanicError):
			branch.uncertainties.add(ProjectionUncertainty.UNKNOWN_DYNAMIC_EFFECT)
	if target.pokemon_id in branch.protected and not move.breaks_protect and "protect" in move.flags:
		return "protect"
	return None


def _apply_non_targeted_effects(
	branch: _Branch,
	intent: _MoveIntent,
	actor: _PokemonState,
	semantics: Mapping[str, object],
	mechanics: MechanicsSnapshot,
	after_targeted: bool = False,
) -> None:
	move = intent.move
	if move.weather:
		branch.weather = move.weather
	if move.terrain:
		branch.field_conditions.add(move.terrain)
	if move.pseudo_weather:
		branch.field_conditions.add(move.pseudo_weather)
	if move.side_condition:
		requires = semantics.get("requires_weather")
		if isinstance(requires, list) and not _weather_requirement_met(branch.weather, requires):
			return
		branch.side_conditions[intent.side].add(move.side_condition)
		branch.status_changes.append(ProjectedStatusChange(
			intent.side, actor.pokemon_id, move.side_condition, "side_condition", move.id,
		))
	if semantics.get("delayed_heal_fraction") is not None:
		branch.field_conditions.add(f"wish:{intent.side}:{actor.position}:pending")
	if move.heal and not after_targeted:
		numerator, denominator = move.heal[:2]
		actor.hp_fraction = min(1.0, actor.hp_fraction + numerator / denominator)
	if not after_targeted:
		_apply_self_effects(branch, intent, actor, move)
	if move.force_switch or move.self_switch:
		branch.uncertainties.add(ProjectionUncertainty.UNKNOWN_DYNAMIC_EFFECT)
		branch.random_effects.append(f"{intent.side}:{actor.pokemon_id}:{move.id}:switching effect not projected")


def _apply_target_effects(
	branch: _Branch,
	intent: _MoveIntent,
	actor: _PokemonState,
	target: _PokemonState,
	move: MoveMechanics,
	semantics: Mapping[str, object],
) -> None:
	for stat, stages in move.boosts:
		_change_boost(branch, target, stat, stages, move.id)
	if move.status and target.status is None:
		target.status = move.status
		branch.status_changes.append(ProjectedStatusChange(target.side, target.pokemon_id, move.status, "status", move.id))
	if move.volatile_status:
		branch.status_changes.append(ProjectedStatusChange(
			target.side, target.pokemon_id, move.volatile_status, "volatile", move.id,
		))
	if semantics.get("locks_last_move") is True:
		branch.status_changes.append(ProjectedStatusChange(target.side, target.pokemon_id, "encore", "volatile", move.id))
	if semantics.get("causes_flinch") is True and not target.fainted:
		branch.flinched.add(target.pokemon_id)
		branch.status_changes.append(ProjectedStatusChange(target.side, target.pokemon_id, "flinch", "volatile", move.id))


def _apply_self_effects(branch: _Branch, intent: _MoveIntent, actor: _PokemonState, move: MoveMechanics) -> None:
	for stat, stages in move.self_boosts:
		_change_boost(branch, actor, stat, stages, move.id)


def _change_boost(branch: _Branch, target: _PokemonState, stat: str, stages: int, source: str) -> None:
	before = target.boosts.get(stat, 0)
	after = max(-6, min(6, before + int(stages)))
	actual = after - before
	if actual:
		target.boosts[stat] = after
		branch.boost_changes.append(ProjectedBoostChange(target.side, target.pokemon_id, stat, actual, source))


def _apply_hp(
	branch: _Branch,
	target: _PokemonState,
	low: float,
	mid: float,
	high: float,
	hit_probability: float,
	move: MoveMechanics,
	mechanics: MechanicsSnapshot,
) -> None:
	current = target.hp_fraction
	if current <= 0:
		return
	conditional_lethal = high >= current
	definite_lethal = hit_probability >= 1.0 and low >= current
	if conditional_lethal:
		branch.possible_faints[target.side].add(target.pokemon_id)

	if definite_lethal and _focus_sash_saves(target, mechanics):
		target.hp_fraction = _sash_fraction(target)
		target.item = None
		branch.uncertainties.add(ProjectionUncertainty.SURVIVAL)
		branch.random_effects.append(f"{target.pokemon_id}:Focus Sash survival")
		return
	target.hp_fraction = max(0.0, current - mid)
	if definite_lethal:
		target.hp_fraction = 0.0
		target.fainted = True
		branch.definite_faints[target.side].add(target.pokemon_id)
	elif conditional_lethal:
		branch.uncertainties.add(ProjectionUncertainty.SURVIVAL)


def _focus_sash_saves(target: _PokemonState, mechanics: MechanicsSnapshot) -> bool:
	if not target.item or target.hp_fraction < 0.999:
		return False
	semantics = _safe_semantic(mechanics, "items", target.item)
	return semantics.get("survive_full_hp_lethal_hit") is True


def _sash_fraction(target: _PokemonState) -> float:
	if target.max_hp and target.max_hp > 0:
		return min(1.0, 1.0 / target.max_hp)
	return 0.01


def _damage_fraction(
	branch: _Branch,
	attacker: _PokemonState,
	target: _PokemonState,
	move: MoveMechanics,
	mechanics: MechanicsSnapshot,
	config: ProjectionConfig,
) -> tuple[float, float, float, str] | None:
	base_power = _effective_base_power(attacker, target, move, mechanics)
	if base_power <= 0:
		return None
	try:
		effectiveness = _effectiveness(branch, move, target, mechanics)
	except (KeyError, ValueError, UnresolvedMechanicError):
		return None
	if effectiveness <= 0:
		return 0.0, 0.0, 0.0, "type_or_ability_immunity"

	offensive_stat = move.override_offensive_stat or ("atk" if move.category == "Physical" else "spa")
	defensive_stat = move.override_defensive_stat or ("def" if move.category == "Physical" else "spd")
	offense = attacker.stats.get(offensive_stat)
	defense = target.stats.get(defensive_stat)
	if offense is None or defense is None or defense <= 0:
		return None
	offense *= _stat_stage_multiplier(attacker.boosts.get(offensive_stat, 0))
	defense *= _stat_stage_multiplier(target.boosts.get(defensive_stat, 0))
	if move.category == "Physical" and _is_snow(branch.weather) and any(to_id(value) == "ice" for value in target.types):
		defense *= config.snow_ice_defense_multiplier
	if move.category == "Physical" and attacker.status == "brn":
		offense *= config.burn_physical_multiplier

	stab = 1.5 if any(to_id(value) == to_id(move.type) for value in attacker.types) else 1.0
	spread = config.spread_damage_multiplier if move.is_spread else 1.0
	defensive = _defensive_multiplier(branch, target, move, effectiveness, mechanics, config)
	if defensive == 0:
		return 0.0, 0.0, 0.0, "ability_immunity"
	level = max(1, attacker.level)
	base_damage = (((2 * level / 5 + 2) * base_power * offense / defense) / 50 + 2)
	# Opponent max HP is hidden. Use a neutral base-stat proxy if exact HP is unavailable.
	if target.max_hp and target.max_hp > 0:
		hp_scale = target.max_hp
	else:
		try:
			hp_scale = float(mechanics.species(target.species).stats.get("hp", 80) + 75)
		except KeyError:
			hp_scale = 155.0
	common = base_damage * stab * effectiveness * spread * defensive / hp_scale
	return (
		max(0.0, common * config.damage_random_low),
		max(0.0, common * config.damage_random_mid),
		max(0.0, common * config.damage_random_high),
		"coarse_public_projection",
	)


def _effective_base_power(
	attacker: _PokemonState,
	target: _PokemonState,
	move: MoveMechanics,
	mechanics: MechanicsSnapshot,
) -> int:
	if move.base_power > 0:
		return move.base_power
	semantics = _safe_semantic(mechanics, "moves", move.id)
	if semantics.get("weight_based_power") is True:
		weight = target.weight_kg
		if weight < 10:
			return 20
		if weight < 25:
			return 40
		if weight < 50:
			return 60
		if weight < 100:
			return 80
		if weight < 200:
			return 100
		return 120
	if semantics.get("weight_ratio_power") is True:
		ratio = attacker.weight_kg / max(0.1, target.weight_kg)
		if ratio >= 5:
			return 120
		if ratio >= 4:
			return 100
		if ratio >= 3:
			return 80
		if ratio >= 2:
			return 60
		return 40
	if any(name in move.callback_names for name in ("basePowerCallback", "damageCallback", "onBasePower")):
		return 0
	return 0


def _effectiveness(
	branch: _Branch,
	move: MoveMechanics,
	target: _PokemonState,
	mechanics: MechanicsSnapshot,
) -> float:
	types = tuple(target.types)
	if to_id(move.type) == "ground" and "gravity" in {to_id(value) for value in branch.field_conditions}:
		result = 1.0
		for defending in types:
			if to_id(defending) == "flying":
				continue
			result *= mechanics.move_multiplier(move, (defending,))
		return result
	return mechanics.move_multiplier(move, types)


def _defensive_multiplier(
	branch: _Branch,
	target: _PokemonState,
	move: MoveMechanics,
	effectiveness: float,
	mechanics: MechanicsSnapshot,
	config: ProjectionConfig,
) -> float:
	multiplier = 1.0
	ability = _safe_semantic(mechanics, "abilities", target.ability)
	move_type = to_id(move.type)
	if move_type == "fire" and ability.get("fire_immunity") is True:
		return 0.0
	if move_type == "water" and "water_immunity_and_heal_fraction" in ability:
		return 0.0
	if move_type == "fire" and _number(ability.get("fire_damage_multiplier")) is not None:
		multiplier *= float(ability["fire_damage_multiplier"])
	if effectiveness > 1 and _number(ability.get("super_effective_damage_multiplier")) is not None:
		multiplier *= float(ability["super_effective_damage_multiplier"])
	if target.item:
		item = _safe_semantic(mechanics, "items", target.item)
		type_map = item.get("super_effective_type_damage_multiplier")
		if effectiveness > 1 and isinstance(type_map, Mapping):
			for type_name, value in type_map.items():
				if to_id(str(type_name)) == move_type and _number(value) is not None:
					multiplier *= float(value)
					break
	for ally in branch.positions[target.side].values():
		if ally.pokemon_id == target.pokemon_id or ally.fainted:
			continue
		ally_semantics = _safe_semantic(mechanics, "abilities", ally.ability)
		value = _number(ally_semantics.get("ally_damage_multiplier"))
		if value is not None:
			multiplier *= value
	conditions = {to_id(value) for value in branch.side_conditions[target.side]}
	if "auroraveil" in conditions:
		multiplier *= config.doubles_screen_multiplier
	elif move.category == "Physical" and "reflect" in conditions:
		multiplier *= config.doubles_screen_multiplier
	elif move.category == "Special" and "lightscreen" in conditions:
		multiplier *= config.doubles_screen_multiplier
	return multiplier


def _hit_probability(
	branch: _Branch,
	attacker: _PokemonState,
	target: _PokemonState,
	move: MoveMechanics,
	mechanics: MechanicsSnapshot,
) -> float:
	if move.accuracy is True:
		return 1.0
	attacker_ability = _safe_semantic(mechanics, "abilities", attacker.ability)
	target_ability = _safe_semantic(mechanics, "abilities", target.ability)
	if attacker_ability.get("accuracy_bypass") is True or target_ability.get("accuracy_bypass") is True:
		return 1.0
	try:
		if mechanics.weather_grants_perfect_accuracy(move, branch.weather):
			return 1.0
	except (KeyError, ValueError, UnresolvedMechanicError):
		pass
	base = float(move.accuracy) / 100.0
	if not move.ignore_accuracy:
		base *= _accuracy_stage_multiplier(attacker.boosts.get("accuracy", 0))
	if not move.ignore_evasion:
		base /= _accuracy_stage_multiplier(target.boosts.get("evasion", 0))
	gravity = "gravity" in {to_id(value) for value in branch.field_conditions}
	if gravity:
		base *= 6840.0 / 4096.0
	incoming_weather = target_ability.get("incoming_accuracy_modifier_in_weather")
	if isinstance(incoming_weather, Mapping) and branch.weather:
		for weather, ratio in incoming_weather.items():
			if to_id(str(weather)) == to_id(branch.weather):
				value = _ratio(ratio)
				if value is not None:
					base *= value
	item = _safe_semantic(mechanics, "items", target.item)
	value = _ratio(item.get("incoming_accuracy_modifier"))
	if value is not None:
		base *= value
	return max(0.0, min(1.0, base))


def _stat_stage_multiplier(stage: int) -> float:
	stage = max(-6, min(6, int(stage)))
	return (2 + stage) / 2 if stage >= 0 else 2 / (2 - stage)


def _weather_requirement_met(weather: str | None, required: Iterable[object]) -> bool:
	if not weather:
		return False
	current = to_id(weather)
	allowed = {to_id(str(value)) for value in required}
	if current == "snow":
		current = "snowscape"
	if current == "hail" and "snowscape" in allowed:
		return True
	return current in allowed


def _accuracy_stage_multiplier(stage: int) -> float:
	stage = max(-6, min(6, int(stage)))
	if stage >= 0:
		return (3 + stage) / 3
	return 3 / (3 - stage)


def _apply_end_of_turn(branch: _Branch, knowledge: KnowledgeState, mechanics: MechanicsSnapshot) -> None:
	for position, heal_fraction in _pending_wishes(knowledge).items():
		target = branch.positions["own"].get(position)
		if target is None or target.fainted:
			continue
		target.hp_fraction = min(1.0, target.hp_fraction + heal_fraction)
		branch.status_changes.append(ProjectedStatusChange("own", target.pokemon_id, "wish_heal", "heal", "wish"))
	for side in ("own", "opponent"):
		for target in branch.positions[side].values():
			if target.fainted:
				continue
			if target.status == "brn":
				damage = min(target.hp_fraction, 1.0 / 16.0)
				target.hp_fraction -= damage
				branch.hp_changes.append(ProjectedHPChange(side, target.pokemon_id, damage, damage, damage, 1.0, "burn_residual"))
				if target.hp_fraction <= 0:
					target.fainted = True
					branch.definite_faints[side].add(target.pokemon_id)
			if target.item and to_id(target.item) == "leftovers":
				target.hp_fraction = min(1.0, target.hp_fraction + 1.0 / 16.0)


def _pending_wishes(knowledge: KnowledgeState) -> dict[str, float]:
	# Wish heals the same active slot at the end of the next turn. Own HP is exact;
	# use a half-maximum-health fraction for the current occupant as a strategic proxy.
	result = {}
	for observation in knowledge.history.move_observations:
		if observation.turn != knowledge.turn - 1 or to_id(observation.move) != "wish":
			continue
		actor = observation.actor.split(":", 1)[0].strip()
		if actor.endswith("a"):
			result["left"] = 0.5
		elif actor.endswith("b"):
			result["right"] = 0.5
	return result


def _swap_positions(branch: _Branch, side: str) -> None:
	left = branch.positions[side].get("left")
	right = branch.positions[side].get("right")
	if left is None or right is None:
		return
	branch.positions[side]["left"], branch.positions[side]["right"] = right, left
	right.position = "left"
	left.position = "right"


def _record(
	branch: _Branch,
	intent: _MoveIntent,
	original_target_id: str | None,
	final_target_id: str | None,
	blocked_by: str | None,
	redirected: bool,
	hit_probability: float | None,
	notes: tuple[str, ...],
) -> None:
	if redirected:
		branch.redirected_actions.append(f"{intent.side}:{intent.actor_id}:{intent.move.id}")
	branch.action_records.append(ProjectedActionRecord(
		intent.side, intent.actor_id, intent.move.id, original_target_id, final_target_id,
		blocked_by, redirected, hit_probability, notes,
	))


def _protect_chain(actor: _PokemonState, knowledge: KnowledgeState) -> int:
	for chain in knowledge.history.protect_chains:
		name = to_id(chain.pokemon_identity.split(":", 1)[-1])
		if name in {to_id(actor.pokemon_id), to_id(actor.species)}:
			return chain.consecutive_count
	return 0


def _last_move_was(actor: _PokemonState, move_id: str, knowledge: KnowledgeState) -> bool:
	observations = [
		value for value in knowledge.history.move_observations
		if to_id(value.actor.split(":", 1)[-1]) in {to_id(actor.species), to_id(actor.pokemon_id)}
	]
	if not observations:
		return False
	last = max(observations, key=lambda value: (value.turn, value.event_index))
	return to_id(last.move) == to_id(move_id)


def _is_damaging(move: MoveMechanics, mechanics: MechanicsSnapshot) -> bool:
	if move.base_power > 0:
		return True
	semantics = _safe_semantic(mechanics, "moves", move.id)
	if semantics.get("weight_based_power") is True or semantics.get("weight_ratio_power") is True:
		return True
	return any(name in move.callback_names for name in ("basePowerCallback", "damageCallback", "onBasePower"))


def _find_actor(branch: _Branch, side: str, pokemon_id: str) -> _PokemonState | None:
	for actor in branch.positions[side].values():
		if actor.pokemon_id == pokemon_id:
			return actor
	return None


def _other_side(side: str) -> str:
	return "opponent" if side == "own" else "own"


def _is_snow(weather: str | None) -> bool:
	return bool(weather and to_id(weather) in {"snow", "snowscape", "hail"})


def _safe_semantic(mechanics: MechanicsSnapshot, category: str, value: str | None) -> dict[str, object]:
	if not value:
		return {}
	try:
		return mechanics.semantic(category, value)
	except (KeyError, ValueError):
		return {}


def _number(value: object) -> float | None:
	if isinstance(value, bool) or not isinstance(value, (int, float)):
		return None
	return float(value)


def _ratio(value: object) -> float | None:
	if not isinstance(value, (list, tuple)) or len(value) != 2:
		return None
	left, right = value
	if isinstance(left, bool) or isinstance(right, bool):
		return None
	if not isinstance(left, (int, float)) or not isinstance(right, (int, float)) or right == 0:
		return None
	return float(left) / float(right)


def _confidence(branch: _Branch) -> ProjectionConfidence:
	if ProjectionUncertainty.UNKNOWN_DYNAMIC_EFFECT in branch.uncertainties:
		return ProjectionConfidence.LOW
	if branch.uncertainties & {
		ProjectionUncertainty.SPEED_ORDER,
		ProjectionUncertainty.OPPONENT_TRANSFORMATION,
		ProjectionUncertainty.ENTRY_WEATHER_ORDER,
		ProjectionUncertainty.SURVIVAL,
	}:
		return ProjectionConfidence.MEDIUM
	return ProjectionConfidence.HIGH


def _finalize(branch: _Branch, index: int, normalized_weight: float) -> ProjectedOutcome:
	own_positions = tuple(sorted((position, actor.pokemon_id) for position, actor in branch.positions["own"].items() if not actor.fainted))
	opponent_positions = tuple(sorted(
		(position, actor.pokemon_id) for position, actor in branch.positions["opponent"].items() if not actor.fainted
	))
	return ProjectedOutcome(
		branch_id=f"projection-{index}:{branch.label}",
		branch_weight=round(normalized_weight, 8),
		confidence=_confidence(branch),
		own_hp_changes=tuple(change for change in branch.hp_changes if change.side == "own"),
		opponent_hp_changes=tuple(change for change in branch.hp_changes if change.side == "opponent"),
		own_faints=tuple(sorted(branch.definite_faints["own"])),
		opponent_faints=tuple(sorted(branch.definite_faints["opponent"])),
		possible_own_faints=tuple(sorted(branch.possible_faints["own"] - branch.definite_faints["own"])),
		possible_opponent_faints=tuple(sorted(branch.possible_faints["opponent"] - branch.definite_faints["opponent"])),
		boost_changes=tuple(branch.boost_changes),
		status_changes=tuple(branch.status_changes),
		projected_weather=branch.weather,
		projected_field_conditions=tuple(sorted(branch.field_conditions)),
		projected_own_side_conditions=tuple(sorted(branch.side_conditions["own"])),
		projected_opponent_side_conditions=tuple(sorted(branch.side_conditions["opponent"])),
		projected_own_positions=own_positions,
		projected_opponent_positions=opponent_positions,
		protected_pokemon=tuple(sorted(branch.protected)),
		wide_guard_sides=tuple(sorted(branch.wide_guard)),
		blocked_actions=tuple(branch.blocked_actions),
		redirected_actions=tuple(branch.redirected_actions),
		action_records=tuple(branch.action_records),
		unresolved_random_effects=tuple(dict.fromkeys(branch.random_effects)),
		uncertain_interactions=tuple(sorted(branch.uncertainties, key=lambda value: value.value)),
	)
