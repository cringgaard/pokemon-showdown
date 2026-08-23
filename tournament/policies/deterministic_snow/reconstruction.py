"""B3 temporal knowledge reconstruction from public BotState history.

This layer deliberately builds on the immutable B1 public-information model. It
reconstructs temporal facts that are not reliably present in one current-state
snapshot while preserving the same fairness boundary: only BotState, public
history, and optional static mechanics are consumed.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import re
from typing import Any, Mapping

from .knowledge import (
	Certainty,
	DamageEvidence,
	HistoryKnowledge,
	KnowledgeState as FoundationKnowledgeState,
	MoveObservation,
	ProtectChain,
	PublicHistoryEvent,
	SpeedEvidence,
	SwitchChronology,
	build_knowledge_state as build_foundation_knowledge_state,
)
from .mechanics import MechanicsSnapshot
from .serialization import canonical_json, parse_json, to_primitive


@dataclass(frozen=True)
class WeatherObservation:
	turn: int
	event_index: int
	weather: str | None
	active: bool
	upkeep: bool
	source_effect: str | None
	source_pokemon: str | None


@dataclass(frozen=True)
class TimedConditionKnowledge:
	scope: str
	id: str
	active: bool
	started_turn: int | None
	expected_end_turn: int | None
	remaining_turns: int | None
	duration_certainty: Certainty


@dataclass(frozen=True)
class FakeOutEligibility:
	position: str
	pokemon_identity: str
	known_fake_out: bool | None
	eligible: bool | None
	certainty: Certainty
	reason: str


@dataclass(frozen=True)
class KnowledgeState(FoundationKnowledgeState):
	"""B3 policy state: B1 snapshot plus reconstructable temporal knowledge."""

	weather_history: tuple[WeatherObservation, ...]
	timed_conditions: tuple[TimedConditionKnowledge, ...]
	fake_out_eligibility: tuple[FakeOutEligibility, ...]

	def to_dict(self) -> dict[str, Any]:
		return {name: to_primitive(getattr(self, name)) for name in self.__dataclass_fields__}

	@classmethod
	def from_json(cls, value: str) -> "KnowledgeState":
		parsed = parse_json(value)
		if not isinstance(parsed, Mapping):
			raise ValueError("KnowledgeState must be an object")
		return cls.from_dict(parsed)

	@classmethod
	def from_dict(cls, value: Mapping[str, Any]) -> "KnowledgeState":
		if value.get("knowledge_schema_version") != 2 or value.get("bot_state_schema_version") != 2:
			raise ValueError("B3 KnowledgeState requires knowledge schema 2 and BotState schema 2")
		foundation_value = dict(value)
		foundation_value["knowledge_schema_version"] = 1
		for key in ("weather_history", "timed_conditions", "fake_out_eligibility"):
			foundation_value.pop(key, None)
		foundation = FoundationKnowledgeState.from_dict(foundation_value)
		base = {field.name: getattr(foundation, field.name) for field in fields(FoundationKnowledgeState)}
		base["knowledge_schema_version"] = 2
		return cls(
			**base,
			weather_history=tuple(WeatherObservation(**item) for item in value.get("weather_history", [])),
			timed_conditions=tuple(
				TimedConditionKnowledge(
					item["scope"], item["id"], bool(item["active"]), item.get("started_turn"),
					item.get("expected_end_turn"), item.get("remaining_turns"),
					Certainty(item["duration_certainty"]),
				)
				for item in value.get("timed_conditions", [])
			),
			fake_out_eligibility=tuple(
				FakeOutEligibility(
					item["position"], item["pokemon_identity"], item.get("known_fake_out"),
					item.get("eligible"), Certainty(item["certainty"]), item["reason"],
				)
				for item in value.get("fake_out_eligibility", [])
			),
		)


def build_knowledge_state(
	state: Mapping[str, Any], mechanics: MechanicsSnapshot | None = None
) -> KnowledgeState:
	"""Reconstruct the deterministic B3 state from public state/history.

	``mechanics`` is optional so history reconstruction remains usable in isolated
	tests. Mechanics-dependent deductions (currently speed-order evidence and
	known item-backed weather duration) are simply omitted when it is absent.
	"""
	foundation = build_foundation_knowledge_state(state)
	events = foundation.history.events
	moves = _move_observations(events)
	switches = _switch_chronology(events)
	protects = _protect_chains(events, mechanics)
	damage = _damage_evidence(events, moves)
	speed = _speed_evidence(events, moves, mechanics)
	history = HistoryKnowledge(events, moves, protects, switches, speed, damage)
	weather = _weather_history(events)
	timed = _timed_conditions(foundation, weather, mechanics)
	fake_out = _fake_out_eligibility(foundation, events, moves)

	base = {field.name: getattr(foundation, field.name) for field in fields(FoundationKnowledgeState)}
	base["knowledge_schema_version"] = 2
	base["history"] = history
	return KnowledgeState(
		**base,
		weather_history=weather,
		timed_conditions=timed,
		fake_out_eligibility=fake_out,
	)


def _event_args(event: PublicHistoryEvent) -> list[Any]:
	args = event.data.get("args", [])
	return args if isinstance(args, list) else []


def _event_kwargs(event: PublicHistoryEvent) -> Mapping[str, Any]:
	kwargs = event.data.get("kwArgs", {})
	return kwargs if isinstance(kwargs, Mapping) else {}


def _to_id(value: Any) -> str:
	if not isinstance(value, str):
		return ""
	return "".join(character.lower() for character in value if character.isalnum())


def _effect_id(value: Any) -> str:
	if not isinstance(value, str):
		return ""
	return _to_id(value.split(":", 1)[-1])


def _parse_ident(value: Any) -> tuple[str, str | None, str] | None:
	if not isinstance(value, str):
		return None
	match = re.match(r"^(p[1-4])([a-d])?: (.*)$", value)
	if not match:
		return None
	return match.group(1), match.group(2), match.group(3)


def _canonical_actor(value: Any) -> str | None:
	parsed = _parse_ident(value)
	if not parsed:
		return None
	return f"{parsed[0]}:{parsed[2]}"


def _slot_key(value: Any) -> str | None:
	parsed = _parse_ident(value)
	if not parsed or not parsed[1]:
		return None
	return f"{parsed[0]}{parsed[1]}"


def _move_observations(events: tuple[PublicHistoryEvent, ...]) -> tuple[MoveObservation, ...]:
	result: list[MoveObservation] = []
	for event in events:
		if event.type != "move":
			continue
		args = _event_args(event)
		if len(args) < 2:
			continue
		actor = _canonical_actor(args[0])
		if not actor:
			continue
		target = _canonical_actor(args[2]) if len(args) > 2 else None
		result.append(MoveObservation(event.turn, event.index, actor, _to_id(str(args[1])), target))
	return tuple(result)


def _is_protection_move(move_id: str, mechanics: MechanicsSnapshot | None) -> bool:
	if mechanics is not None:
		try:
			if mechanics.semantic("moves", move_id).get("protection_move") is True:
				return True
		except (KeyError, ValueError):
			pass
	return move_id == "protect"


def _protect_chains(
	events: tuple[PublicHistoryEvent, ...], mechanics: MechanicsSnapshot | None
) -> tuple[ProtectChain, ...]:
	state: dict[str, dict[str, Any]] = {}
	for event in events:
		args = _event_args(event)
		if event.type in ("switch", "drag") and args:
			actor = _canonical_actor(args[0])
			if actor:
				entry = state.setdefault(actor, {"last_used": None, "count": 0, "last_action_turn": None, "last_was": False})
				entry["count"] = 0
				entry["last_was"] = False
				entry["last_action_turn"] = None
		elif event.type == "move" and len(args) >= 2:
			actor = _canonical_actor(args[0])
			if not actor:
				continue
			entry = state.setdefault(actor, {"last_used": None, "count": 0, "last_action_turn": None, "last_was": False})
			move_id = _to_id(str(args[1]))
			if _is_protection_move(move_id, mechanics):
				consecutive = bool(entry["last_was"]) and entry["last_action_turn"] == event.turn - 1
				entry["count"] = int(entry["count"]) + 1 if consecutive else 1
				entry["last_used"] = event.turn
				entry["last_was"] = True
			else:
				entry["count"] = 0
				entry["last_was"] = False
			entry["last_action_turn"] = event.turn
	return tuple(
		ProtectChain(actor, int(value["last_used"]), int(value["count"]))
		for actor, value in sorted(state.items()) if value["last_used"] is not None
	)


def _switch_chronology(events: tuple[PublicHistoryEvent, ...]) -> tuple[SwitchChronology, ...]:
	active_by_slot: dict[str, str] = {}
	entries: dict[str, list[int]] = {}
	exits: dict[str, list[int]] = {}
	for event in events:
		if event.type not in ("switch", "drag"):
			continue
		args = _event_args(event)
		if not args:
			continue
		slot = _slot_key(args[0])
		actor = _canonical_actor(args[0])
		if not slot or not actor:
			continue
		previous = active_by_slot.get(slot)
		if previous and previous != actor:
			exits.setdefault(previous, []).append(event.turn)
		if previous != actor:
			entries.setdefault(actor, []).append(event.turn)
		active_by_slot[slot] = actor
	actors = sorted(set(entries) | set(exits))
	return tuple(
		SwitchChronology(actor, tuple(entries.get(actor, ())), tuple(exits.get(actor, ())))
		for actor in actors
	)


def _health_fraction(condition: Any) -> float | None:
	if not isinstance(condition, str):
		return None
	if condition.strip().startswith("0") and "fnt" in condition:
		return 0.0
	match = re.search(r"(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)", condition)
	if match:
		maximum = float(match.group(2))
		return float(match.group(1)) / maximum if maximum > 0 else None
	percent = re.search(r"(\d+(?:\.\d+)?)%", condition)
	if percent:
		return float(percent.group(1)) / 100.0
	return None


def _damage_evidence(
	events: tuple[PublicHistoryEvent, ...], moves: tuple[MoveObservation, ...]
) -> tuple[DamageEvidence, ...]:
	move_by_index = {move.event_index: move for move in moves}
	last_move: MoveObservation | None = None
	current_health: dict[str, float] = {}
	critical: set[tuple[int, str]] = set()
	result: list[DamageEvidence] = []
	for event in events:
		args = _event_args(event)
		kwargs = _event_kwargs(event)
		if event.type == "move":
			last_move = move_by_index.get(event.index)
			continue
		if event.type in ("switch", "drag") and len(args) >= 3:
			actor = _canonical_actor(args[0])
			fraction = _health_fraction(args[2])
			if actor and fraction is not None:
				current_health[actor] = fraction
			continue
		if event.type == "-crit" and args:
			target = _canonical_actor(args[0])
			if target:
				critical.add((event.turn, target))
			continue
		if event.type == "-damage" and len(args) >= 2:
			target = _canonical_actor(args[0])
			if not target:
				continue
			new_fraction = _health_fraction(args[1])
			old_fraction = current_health.get(target)
			removed = None if old_fraction is None or new_fraction is None else max(0.0, old_fraction - new_fraction)
			if new_fraction is not None:
				current_health[target] = new_fraction
			source = kwargs.get("from")
			source_actor = _canonical_actor(kwargs.get("of"))
			direct = source is None and last_move is not None and last_move.turn == event.turn
			attacker = last_move.actor if direct else source_actor
			move = last_move.move if direct else None
			context = canonical_json({
				"critical": (event.turn, target) in critical,
				"direct_move": direct,
				"source": source,
			})
			result.append(DamageEvidence(attacker, move, target, event.turn, removed, context))
			continue
		if event.type == "-heal" and len(args) >= 2:
			target = _canonical_actor(args[0])
			fraction = _health_fraction(args[1])
			if target and fraction is not None:
				current_health[target] = fraction
			continue
		if event.type == "-sethp":
			for index in range(0, len(args) - 1, 2):
				target = _canonical_actor(args[index])
				fraction = _health_fraction(args[index + 1])
				if target and fraction is not None:
					current_health[target] = fraction
	return tuple(result)


def _speed_evidence(
	events: tuple[PublicHistoryEvent, ...], moves: tuple[MoveObservation, ...], mechanics: MechanicsSnapshot | None
) -> tuple[SpeedEvidence, ...]:
	if mechanics is None:
		return ()
	trick_room = False
	trick_room_by_index: dict[int, bool] = {}
	for event in events:
		args = _event_args(event)
		if event.type == "-fieldstart" and args and _effect_id(args[0]) == "trickroom":
			trick_room = True
		elif event.type == "-fieldend" and args and _effect_id(args[0]) == "trickroom":
			trick_room = False
		trick_room_by_index[event.index] = trick_room

	by_turn: dict[int, list[MoveObservation]] = {}
	for move in moves:
		by_turn.setdefault(move.turn, []).append(move)
	result: list[SpeedEvidence] = []
	for turn, ordered in sorted(by_turn.items()):
		for first, second in zip(ordered, ordered[1:]):
			if first.actor == second.actor:
				continue
			try:
				first_priority = mechanics.move(first.move).priority
				second_priority = mechanics.move(second.move).priority
			except (KeyError, ValueError):
				continue
			if first_priority != second_priority:
				continue
			under_trick_room = trick_room_by_index.get(first.event_index, False)
			faster, slower = (second.actor, first.actor) if under_trick_room else (first.actor, second.actor)
			context = canonical_json({
				"base_priority": first_priority,
				"first_event_index": first.event_index,
				"second_event_index": second.event_index,
				"trick_room": under_trick_room,
			})
			result.append(SpeedEvidence(faster, slower, turn, context))
	return tuple(result)


def _weather_history(events: tuple[PublicHistoryEvent, ...]) -> tuple[WeatherObservation, ...]:
	result: list[WeatherObservation] = []
	for event in events:
		if event.type != "-weather":
			continue
		args = _event_args(event)
		if not args:
			continue
		kwargs = _event_kwargs(event)
		weather_id = _effect_id(args[0])
		active = bool(weather_id and weather_id != "none")
		result.append(WeatherObservation(
			event.turn,
			event.index,
			weather_id if active else None,
			active,
			bool(kwargs.get("upkeep", False)),
			_effect_id(kwargs.get("from")) or None,
			_canonical_actor(kwargs.get("of")),
		))
	return tuple(result)


def _weather_aliases(weather: str) -> tuple[str, ...]:
	weather_id = _to_id(weather)
	if weather_id == "snow":
		return ("snow", "snowscape")
	return (weather_id,)


def _item_for_public_actor(foundation: FoundationKnowledgeState, actor: str | None) -> str | None:
	if actor is None or ":" not in actor:
		return None
	name = actor.split(":", 1)[1]
	name_id = _to_id(name)
	own = [pokemon for pokemon in foundation.own_team if name_id in (_to_id(pokemon.name), _to_id(pokemon.species))]
	if len(own) == 1:
		return own[0].item
	opponent = [
		pokemon for pokemon in foundation.opponent_roster
		if name_id in (_to_id(pokemon.name), _to_id(pokemon.species))
	]
	if len(opponent) == 1:
		return opponent[0].item
	return None


def _weather_duration(
	foundation: FoundationKnowledgeState,
	weather: str,
	weather_history: tuple[WeatherObservation, ...],
	mechanics: MechanicsSnapshot | None,
) -> int | None:
	if mechanics is None:
		return None
	latest = next((item for item in reversed(weather_history) if item.active and not item.upkeep and item.weather in _weather_aliases(weather)), None)
	item = _item_for_public_actor(foundation, latest.source_pokemon if latest else None)
	if not item:
		return None
	try:
		extension = mechanics.semantic("items", item).get("weather_extension_turns")
	except (KeyError, ValueError):
		return None
	if not isinstance(extension, Mapping):
		return None
	for alias in _weather_aliases(weather):
		for key, value in extension.items():
			if _to_id(str(key)) == alias and isinstance(value, int) and not isinstance(value, bool) and value > 0:
				return value
	return None


def _timed_conditions(
	foundation: FoundationKnowledgeState,
	weather_history: tuple[WeatherObservation, ...],
	mechanics: MechanicsSnapshot | None,
) -> tuple[TimedConditionKnowledge, ...]:
	result: list[TimedConditionKnowledge] = []
	weather = foundation.field.weather.value
	weather_started = foundation.field.weather_started_turn.value
	if isinstance(weather, str) and weather:
		duration = _weather_duration(foundation, weather, weather_history, mechanics)
		expected = None
		remaining = None
		certainty = Certainty.UNKNOWN
		if duration is not None and isinstance(weather_started, int):
			# The tracker records lead-entry weather at turn 0, before the first
			# numbered turn. No residual duration tick occurs for a fictitious turn 0.
			first_counted_turn = max(1, weather_started)
			expected = first_counted_turn + duration - 1
			remaining = max(0, expected - foundation.turn + 1)
			certainty = Certainty.DERIVED
		result.append(TimedConditionKnowledge(
			"field", _to_id(weather), True, weather_started if isinstance(weather_started, int) else None,
			expected, remaining, certainty,
		))
	for scope, conditions in (
		("field", foundation.field.conditions),
		("self_side", foundation.field.own_side_conditions),
		("opponent_side", foundation.field.opponent_side_conditions),
	):
		for condition in conditions:
			result.append(TimedConditionKnowledge(
				scope, condition.id, condition.active, condition.started_turn, None, None, Certainty.UNKNOWN,
			))
	return tuple(sorted(result, key=lambda item: (item.scope, item.id)))


def _opponent_side(events: tuple[PublicHistoryEvent, ...]) -> str | None:
	for event in events:
		if event.type != "showteam":
			continue
		args = _event_args(event)
		if args and isinstance(args[0], str) and args[0].startswith("p"):
			return args[0]
	return None


def _entry_event_indices(events: tuple[PublicHistoryEvent, ...]) -> dict[str, list[int]]:
	result: dict[str, list[int]] = {}
	for event in events:
		if event.type not in ("switch", "drag"):
			continue
		args = _event_args(event)
		if not args:
			continue
		actor = _canonical_actor(args[0])
		if actor:
			result.setdefault(actor, []).append(event.index)
	return result


def _actor_for_roster_entry(side: str | None, name: str, species: str, entries: Mapping[str, list[int]]) -> str | None:
	if side is None:
		return None
	candidates = [f"{side}:{name}", f"{side}:{species}"]
	present = [candidate for candidate in candidates if candidate in entries]
	if not present:
		return None
	return max(present, key=lambda candidate: entries[candidate][-1])


def _fake_out_eligibility(
	foundation: FoundationKnowledgeState,
	events: tuple[PublicHistoryEvent, ...],
	moves: tuple[MoveObservation, ...],
) -> tuple[FakeOutEligibility, ...]:
	side = _opponent_side(events)
	entries = _entry_event_indices(events)
	roster_by_id = {pokemon.id: pokemon for pokemon in foundation.opponent_roster}
	result: list[FakeOutEligibility] = []
	for active in foundation.opponent_active:
		team_id = active.established_identity.value
		if not isinstance(team_id, str):
			result.append(FakeOutEligibility(
				active.position, str(active.apparent_identity.value), None, None, Certainty.UNKNOWN,
				"active identity is unresolved",
			))
			continue
		roster = roster_by_id.get(team_id)
		if roster is None:
			continue
		known_fake_out = any(_to_id(move.id) == "fakeout" for move in roster.moves)
		if not known_fake_out:
			result.append(FakeOutEligibility(
				active.position, team_id, False, False, Certainty.OBSERVED,
				"public moveset does not contain Fake Out",
			))
			continue
		actor = _actor_for_roster_entry(side, roster.name, roster.species, entries)
		if actor is None or not entries.get(actor):
			result.append(FakeOutEligibility(
				active.position, team_id, True, None, Certainty.UNKNOWN,
				"latest public entry event is unavailable",
			))
			continue
		entry_index = entries[actor][-1]
		acted_since_entry = any(move.actor == actor and move.event_index > entry_index for move in moves)
		result.append(FakeOutEligibility(
			active.position, team_id, True, not acted_since_entry, Certainty.DERIVED,
			"fresh public entry with no action since" if not acted_since_entry else "Pokemon has acted since its latest entry",
		))
	return tuple(sorted(result, key=lambda item: item.position))
