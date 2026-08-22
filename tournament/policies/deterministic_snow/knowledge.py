"""Public-information-only KnowledgeState construction for B1."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from .actions import CanonicalLegalAction, canonicalize_legal_actions
from .serialization import canonical_json, parse_json, to_primitive


class Certainty(str, Enum):
	OBSERVED = "OBSERVED"
	DERIVED = "DERIVED"
	INFERRED = "INFERRED"
	UNKNOWN = "UNKNOWN"


class KnowledgeSource(str, Enum):
	PUBLIC_SNAPSHOT = "PUBLIC_SNAPSHOT"
	OPEN_TEAM_SHEET = "OPEN_TEAM_SHEET"
	BATTLE_HISTORY = "BATTLE_HISTORY"
	DETERMINISTIC_DERIVATION = "DETERMINISTIC_DERIVATION"
	HEURISTIC_INFERENCE = "HEURISTIC_INFERENCE"


class SelectedFourStatus(str, Enum):
	POSSIBLE_SELECTED = "POSSIBLE_SELECTED"
	CONFIRMED_SELECTED = "CONFIRMED_SELECTED"
	CONFIRMED_NOT_SELECTED = "CONFIRMED_NOT_SELECTED"


@dataclass(frozen=True)
class KnowledgeFact:
	"""A value paired with explicit certainty and public provenance."""

	value_json: str
	certainty: Certainty
	sources: tuple[KnowledgeSource, ...]

	@property
	def value(self) -> Any:
		return parse_json(self.value_json)

	def to_dict(self) -> dict[str, Any]:
		return {
			"value": self.value,
			"certainty": self.certainty.value,
			"sources": [source.value for source in self.sources],
		}

	@classmethod
	def create(cls, value: Any, certainty: Certainty, *sources: KnowledgeSource) -> "KnowledgeFact":
		if certainty is Certainty.UNKNOWN and value is not None:
			raise ValueError("UNKNOWN facts cannot contain a value")
		if certainty is not Certainty.UNKNOWN and not sources:
			raise ValueError("Known facts require provenance")
		return cls(canonical_json(value), certainty, tuple(dict.fromkeys(sources)))

	@classmethod
	def observed(cls, value: Any, source: KnowledgeSource = KnowledgeSource.PUBLIC_SNAPSHOT) -> "KnowledgeFact":
		return cls.create(value, Certainty.OBSERVED, source)

	@classmethod
	def unknown(cls) -> "KnowledgeFact":
		return cls.create(None, Certainty.UNKNOWN)

	@classmethod
	def from_dict(cls, value: Mapping[str, Any]) -> "KnowledgeFact":
		return cls.create(
			value.get("value"),
			Certainty(value["certainty"]),
			*(KnowledgeSource(source) for source in value.get("sources", [])),
		)


@dataclass(frozen=True)
class HealthKnowledge:
	current: float
	maximum: float
	exact: bool
	percent: float

	@classmethod
	def from_dict(cls, value: Mapping[str, Any]) -> "HealthKnowledge":
		return cls(value["current"], value["max"], value["exact"], value["percent"])

	def to_dict(self) -> dict[str, Any]:
		return {"current": self.current, "max": self.maximum, "exact": self.exact, "percent": self.percent}


@dataclass(frozen=True)
class MoveKnowledge:
	id: str
	name: str
	sources: tuple[KnowledgeSource, ...]

	@classmethod
	def from_dict(cls, value: Mapping[str, Any]) -> "MoveKnowledge":
		return cls(value["id"], value["name"], tuple(KnowledgeSource(source) for source in value["sources"]))


@dataclass(frozen=True)
class ConditionKnowledge:
	id: str
	active: bool
	started_turn: int

	@classmethod
	def from_pair(cls, condition_id: str, value: Mapping[str, Any]) -> "ConditionKnowledge":
		return cls(condition_id, bool(value["active"]), int(value["started_turn"]))


@dataclass(frozen=True)
class OwnPokemonKnowledge:
	id: str
	species: str
	name: str
	health: HealthKnowledge
	status: str | None
	fainted: bool
	level: int
	item: str | None
	ability: str
	types: tuple[str, ...]
	transformation: KnowledgeFact
	stats: tuple[tuple[str, int], ...]
	boosts: tuple[tuple[str, int], ...]
	moves: tuple[MoveKnowledge, ...]
	volatiles: tuple[str, ...]

	def to_dict(self) -> dict[str, Any]:
		return {
			"id": self.id, "species": self.species, "name": self.name, "health": self.health,
			"status": self.status, "fainted": self.fainted, "level": self.level, "item": self.item,
			"ability": self.ability, "types": self.types, "transformation": self.transformation,
			"stats": dict(self.stats), "boosts": dict(self.boosts), "moves": self.moves,
			"volatiles": self.volatiles,
		}

	@classmethod
	def from_dict(cls, value: Mapping[str, Any]) -> "OwnPokemonKnowledge":
		return cls(
			value["id"], value["species"], value["name"], HealthKnowledge.from_dict(value["health"]),
			value["status"], value["fainted"], value["level"], value["item"], value["ability"],
			tuple(value["types"]), KnowledgeFact.from_dict(value["transformation"]),
			_sorted_number_pairs(value["stats"]), _sorted_number_pairs(value["boosts"]),
			tuple(MoveKnowledge.from_dict(move) for move in value["moves"]), tuple(value["volatiles"]),
		)


@dataclass(frozen=True)
class OpponentRosterKnowledge:
	id: str
	species: str
	name: str
	item: str | None
	ability: str | None
	tera_type_metadata: str | None
	nature: str | None
	gender: str | None
	level: int | None
	moves: tuple[MoveKnowledge, ...]
	selected_four: SelectedFourStatus
	source: KnowledgeSource

	@classmethod
	def from_dict(cls, value: Mapping[str, Any]) -> "OpponentRosterKnowledge":
		return cls(
			value["id"], value["species"], value["name"], value["item"], value["ability"],
			value["tera_type_metadata"], value["nature"], value["gender"], value["level"],
			tuple(MoveKnowledge.from_dict(move) for move in value["moves"]),
			SelectedFourStatus(value["selected_four"]), KnowledgeSource(value["source"]),
		)


@dataclass(frozen=True)
class OpponentActiveKnowledge:
	position: str
	apparent_identity: KnowledgeFact
	established_identity: KnowledgeFact
	current_form: KnowledgeFact
	health: HealthKnowledge
	status: KnowledgeFact
	fainted: bool
	item: KnowledgeFact
	ability: KnowledgeFact
	types: KnowledgeFact
	transformation: KnowledgeFact
	boosts: tuple[tuple[str, int], ...]
	volatiles: tuple[str, ...]

	def to_dict(self) -> dict[str, Any]:
		return {
			"position": self.position, "apparent_identity": self.apparent_identity,
			"established_identity": self.established_identity, "current_form": self.current_form,
			"health": self.health, "status": self.status, "fainted": self.fainted,
			"item": self.item, "ability": self.ability, "types": self.types,
			"transformation": self.transformation, "boosts": dict(self.boosts),
			"volatiles": self.volatiles,
		}

	@classmethod
	def from_dict(cls, value: Mapping[str, Any]) -> "OpponentActiveKnowledge":
		return cls(
			value["position"], KnowledgeFact.from_dict(value["apparent_identity"]),
			KnowledgeFact.from_dict(value["established_identity"]), KnowledgeFact.from_dict(value["current_form"]),
			HealthKnowledge.from_dict(value["health"]), KnowledgeFact.from_dict(value["status"]), value["fainted"],
			KnowledgeFact.from_dict(value["item"]), KnowledgeFact.from_dict(value["ability"]),
			KnowledgeFact.from_dict(value["types"]), KnowledgeFact.from_dict(value["transformation"]),
			_sorted_number_pairs(value["boosts"]), tuple(value["volatiles"]),
		)


@dataclass(frozen=True)
class FieldKnowledge:
	weather: KnowledgeFact
	weather_started_turn: KnowledgeFact
	conditions: tuple[ConditionKnowledge, ...]
	own_side_conditions: tuple[ConditionKnowledge, ...]
	opponent_side_conditions: tuple[ConditionKnowledge, ...]

	@classmethod
	def from_dict(cls, value: Mapping[str, Any]) -> "FieldKnowledge":
		return cls(
			KnowledgeFact.from_dict(value["weather"]), KnowledgeFact.from_dict(value["weather_started_turn"]),
			tuple(ConditionKnowledge(**condition) for condition in value["conditions"]),
			tuple(ConditionKnowledge(**condition) for condition in value["own_side_conditions"]),
			tuple(ConditionKnowledge(**condition) for condition in value["opponent_side_conditions"]),
		)


@dataclass(frozen=True)
class PublicHistoryEvent:
	index: int
	turn: int
	type: str
	data_json: str
	raw: str

	@property
	def data(self) -> dict[str, Any]:
		return parse_json(self.data_json)

	def to_dict(self) -> dict[str, Any]:
		return {"index": self.index, "turn": self.turn, "type": self.type, "data": self.data, "raw": self.raw}

	@classmethod
	def from_dict(cls, value: Mapping[str, Any]) -> "PublicHistoryEvent":
		return cls(value["index"], value["turn"], value["type"], canonical_json(value["data"]), value["raw"])


@dataclass(frozen=True)
class MoveObservation:
	turn: int
	event_index: int
	actor: str
	move: str
	target: str | None


@dataclass(frozen=True)
class ProtectChain:
	pokemon_identity: str
	last_used_turn: int
	consecutive_count: int


@dataclass(frozen=True)
class SwitchChronology:
	pokemon_identity: str
	entry_turns: tuple[int, ...]
	exit_turns: tuple[int, ...]


@dataclass(frozen=True)
class SpeedEvidence:
	faster_actor: str
	slower_actor: str
	turn: int
	context: str


@dataclass(frozen=True)
class DamageEvidence:
	attacker: str | None
	move: str | None
	target: str
	turn: int
	hp_fraction_removed: float | None
	context: str


@dataclass(frozen=True)
class HistoryKnowledge:
	events: tuple[PublicHistoryEvent, ...]
	move_observations: tuple[MoveObservation, ...]
	protect_chains: tuple[ProtectChain, ...]
	switch_chronology: tuple[SwitchChronology, ...]
	speed_evidence: tuple[SpeedEvidence, ...]
	damage_evidence: tuple[DamageEvidence, ...]

	@classmethod
	def from_dict(cls, value: Mapping[str, Any]) -> "HistoryKnowledge":
		return cls(
			tuple(PublicHistoryEvent.from_dict(event) for event in value["events"]),
			tuple(MoveObservation(**item) for item in value["move_observations"]),
			tuple(ProtectChain(**item) for item in value["protect_chains"]),
			tuple(SwitchChronology(item["pokemon_identity"], tuple(item["entry_turns"]), tuple(item["exit_turns"])) for item in value["switch_chronology"]),
			tuple(SpeedEvidence(**item) for item in value["speed_evidence"]),
			tuple(DamageEvidence(**item) for item in value["damage_evidence"]),
		)


@dataclass(frozen=True)
class KnowledgeState:
	knowledge_schema_version: int
	bot_state_schema_version: int
	format: str
	mod: str
	turn: int
	phase: str
	decision_id: int
	revision: int
	attempt: int
	deadline_ms: int
	own_team: tuple[OwnPokemonKnowledge, ...]
	own_active: tuple[tuple[str, str], ...]
	own_selected_four: tuple[str, ...]
	opponent_roster: tuple[OpponentRosterKnowledge, ...]
	opponent_active: tuple[OpponentActiveKnowledge, ...]
	field: FieldKnowledge
	history: HistoryKnowledge
	legal_actions: tuple[CanonicalLegalAction, ...]

	def to_dict(self) -> dict[str, Any]:
		return {name: to_primitive(getattr(self, name)) for name in self.__dataclass_fields__}

	def to_json(self) -> str:
		return canonical_json(self)

	@classmethod
	def from_json(cls, value: str) -> "KnowledgeState":
		return cls.from_dict(_mapping(parse_json(value), "KnowledgeState"))

	@classmethod
	def from_dict(cls, value: Mapping[str, Any]) -> "KnowledgeState":
		if value.get("knowledge_schema_version") != 1 or value.get("bot_state_schema_version") != 2:
			raise ValueError("KnowledgeState requires knowledge schema 1 and BotState schema 2")
		return cls(
			value["knowledge_schema_version"], value["bot_state_schema_version"],
			value["format"], value["mod"], value["turn"], value["phase"],
			value["decision_id"], value["revision"], value["attempt"], value["deadline_ms"],
			tuple(OwnPokemonKnowledge.from_dict(item) for item in value["own_team"]),
			tuple((item[0], item[1]) for item in value["own_active"]), tuple(value["own_selected_four"]),
			tuple(OpponentRosterKnowledge.from_dict(item) for item in value["opponent_roster"]),
			tuple(OpponentActiveKnowledge.from_dict(item) for item in value["opponent_active"]),
			FieldKnowledge.from_dict(value["field"]), HistoryKnowledge.from_dict(value["history"]),
			tuple(CanonicalLegalAction.from_dict(item) for item in value["legal_actions"]),
		)


def selected_four_statuses(roster_ids: Iterable[str], confirmed_ids: Iterable[str]) -> dict[str, SelectedFourStatus]:
	"""Build a conservative selected-four model without guessing unrevealed identities."""
	roster = tuple(roster_ids)
	confirmed = set(confirmed_ids)
	if not confirmed <= set(roster):
		raise ValueError("Confirmed selected IDs must belong to the public opponent roster")
	if len(confirmed) > 4:
		raise ValueError("At most four opponent Pokemon can be confirmed selected")
	complete = len(confirmed) == 4
	return {
		pokemon_id: (
			SelectedFourStatus.CONFIRMED_SELECTED if pokemon_id in confirmed else
			SelectedFourStatus.CONFIRMED_NOT_SELECTED if complete else
			SelectedFourStatus.POSSIBLE_SELECTED
		)
		for pokemon_id in roster
	}


def build_knowledge_state(state: Mapping[str, Any]) -> KnowledgeState:
	"""Purely reconstruct the B1 policy view from one public schema-v2 state."""
	if state.get("schema_version") != 2:
		raise ValueError("Deterministic snow policy requires BotState.schema_version == 2")
	battle = _required_mapping(state, "battle")
	runtime = _required_mapping(state, "runtime")
	self_state = _required_mapping(state, "self")
	opponent = _required_mapping(state, "opponent")
	field_state = _required_mapping(state, "field")
	request = _required_mapping(state, "request")

	own_team = tuple(_build_own_pokemon(_mapping(item, "self.team item")) for item in _array(self_state, "team"))
	own_active_mapping = _required_mapping(self_state, "active")
	own_active = tuple((position, own_active_mapping[position]) for position in ("left", "right") if position in own_active_mapping)
	own_selected = () if request.get("kind") == "team_preview" else tuple(pokemon.id for pokemon in own_team)

	history_events = tuple(
		PublicHistoryEvent(index, event["turn"], event["type"], canonical_json(event.get("data", {})), event["raw"])
		for index, event_value in enumerate(_array(state, "history"))
		for event in (_mapping(event_value, "history event"),)
	)
	history = HistoryKnowledge(history_events, _move_observations(history_events), (), (), (), ())

	roster_values = [_mapping(item, "opponent.team item") for item in _array(opponent, "team")]
	opponent_active_mapping = _required_mapping(opponent, "active")
	unknown_positions = set(opponent_active_mapping) - {"left", "right"}
	if unknown_positions:
		raise ValueError(f"Unknown opponent active positions: {sorted(unknown_positions)}")
	active_values = [
		_mapping(opponent_active_mapping[position], f"opponent.active.{position}")
		for position in ("left", "right") if position in opponent_active_mapping
	]

	opponent_side, ots_moves = _open_team_sheet_metadata(history_events, roster_values)
	confirmed = {active["team_id"] for active in active_values if active.get("team_id") is not None}
	confirmed.update(_confirmed_selected_from_history(history_events, roster_values, opponent_side))
	selection = selected_four_statuses((item["id"] for item in roster_values), confirmed)
	opponent_roster = tuple(
		_build_opponent_roster(item, selection[item["id"]], ots_moves.get(item["id"]))
		for item in roster_values
	)
	opponent_active = tuple(_build_opponent_active(item) for item in active_values)

	field = FieldKnowledge(
		KnowledgeFact.observed(field_state.get("weather")),
		KnowledgeFact.observed(field_state.get("weather_started_turn")),
		_conditions(field_state.get("conditions", {})),
		_conditions(self_state.get("side_conditions", {})),
		_conditions(opponent.get("side_conditions", {})),
	)
	return KnowledgeState(
		1, 2, battle["format"], battle["mod"], battle["turn"], battle["phase"],
		runtime["decision_id"], runtime["revision"], runtime["attempt"], runtime["deadline_ms"],
		own_team, own_active, own_selected, opponent_roster, opponent_active, field, history,
		canonicalize_legal_actions(request),
	)


def _build_own_pokemon(value: Mapping[str, Any]) -> OwnPokemonKnowledge:
	return OwnPokemonKnowledge(
		value["id"], value["species"], value["name"], HealthKnowledge.from_dict(value["health"]),
		value.get("status"), bool(value["fainted"]), int(value["level"]), value.get("item"), value["ability"],
		tuple(value["types"]), KnowledgeFact.observed(value.get("transformation")),
		_sorted_number_pairs(value["stats"]), _sorted_number_pairs(value["boosts"]),
		tuple(MoveKnowledge(move["id"], move["name"], (KnowledgeSource.PUBLIC_SNAPSHOT,)) for move in value["moves"]),
		tuple(sorted(value.get("volatiles", []))),
	)


def _build_opponent_roster(
	value: Mapping[str, Any], selected: SelectedFourStatus, ots_move_ids: set[str] | None
) -> OpponentRosterKnowledge:
	moves = []
	for move in value.get("moves", []):
		move_id = _normalize_id(move["id"])
		if ots_move_ids is None:
			# In schema-v2 Champions states opponent.team originates from OTS. A valid
			# full history also contains showteam; this fallback preserves that contract
			# for synthetic/minimized fixtures that omit the handshake event.
			sources = (KnowledgeSource.OPEN_TEAM_SHEET,)
		elif move_id in ots_move_ids:
			sources = (KnowledgeSource.OPEN_TEAM_SHEET,)
		else:
			# The harness appends only publicly observed moves to the immutable OTS roster.
			# Absence from the original showteam payload therefore means observed-in-battle,
			# not submitted-set knowledge.
			sources = (KnowledgeSource.BATTLE_HISTORY,)
		moves.append(MoveKnowledge(move["id"], move["name"], sources))
	return OpponentRosterKnowledge(
		value["id"], value["species"], value["name"], value.get("item"), value.get("ability"),
		value.get("tera_type"), value.get("nature"), value.get("gender"), value.get("level"),
		tuple(moves), selected, KnowledgeSource.OPEN_TEAM_SHEET,
	)


def _build_opponent_active(value: Mapping[str, Any]) -> OpponentActiveKnowledge:
	established = value.get("team_id")
	identity_known = established is not None
	return OpponentActiveKnowledge(
		value["position"], KnowledgeFact.observed(value["apparent_species"]),
		KnowledgeFact.observed(established) if identity_known else KnowledgeFact.unknown(),
		KnowledgeFact.observed(value["apparent_species"]) if identity_known else KnowledgeFact.unknown(),
		HealthKnowledge.from_dict(value["health"]), KnowledgeFact.observed(value.get("status")), bool(value["fainted"]),
		_fact_if_public(value.get("item"), identity_known), _fact_if_public(value.get("ability"), identity_known),
		_fact_if_public(value.get("types"), identity_known),
		KnowledgeFact.observed(value.get("transformation")) if identity_known or value.get("transformation") is not None else KnowledgeFact.unknown(),
		_sorted_number_pairs(value["boosts"]), tuple(sorted(value.get("volatiles", []))),
	)


def _fact_if_public(value: Any, identity_known: bool) -> KnowledgeFact:
	return KnowledgeFact.observed(value) if value is not None or identity_known else KnowledgeFact.unknown()


def _conditions(value: Any) -> tuple[ConditionKnowledge, ...]:
	conditions = _mapping(value, "conditions")
	return tuple(ConditionKnowledge.from_pair(condition_id, _mapping(condition, condition_id)) for condition_id, condition in sorted(conditions.items()))


def _move_observations(events: tuple[PublicHistoryEvent, ...]) -> tuple[MoveObservation, ...]:
	result = []
	for event in events:
		if event.type != "move":
			continue
		args = event.data.get("args", [])
		if not isinstance(args, list) or len(args) < 2:
			continue
		result.append(MoveObservation(event.turn, event.index, str(args[0]), str(args[1]), str(args[2]) if len(args) > 2 else None))
	return tuple(result)


def _open_team_sheet_metadata(
	events: tuple[PublicHistoryEvent, ...], roster: list[Mapping[str, Any]]
) -> tuple[str | None, dict[str, set[str]]]:
	"""Recover immutable OTS move membership and the opponent side from public showteam history."""
	for event in events:
		if event.type != "showteam":
			continue
		args = event.data.get("args", [])
		if not isinstance(args, list) or len(args) < 2 or not isinstance(args[0], str):
			continue
		packed = "|".join(str(part) for part in args[1:])
		sets = _parse_packed_team_summary(packed)
		if len(sets) != len(roster):
			continue
		if any(_normalize_id(species) != _normalize_id(item.get("species")) for (species, _), item in zip(sets, roster)):
			continue
		return args[0], {
			item["id"]: move_ids
			for item, (_, move_ids) in zip(roster, sets)
		}
	return None, {}


def _parse_packed_team_summary(packed: str) -> list[tuple[str, set[str]]]:
	"""Parse only public species and move IDs from Showdown's packed-team wire format."""
	result = []
	if not packed:
		return result
	for packed_set in packed.split("]"):
		fields = packed_set.split("|")
		if len(fields) < 5:
			return []
		species = fields[1] or fields[0]
		moves = {_normalize_id(move) for move in fields[4].split(",") if move}
		result.append((species, moves))
	return result


def _confirmed_selected_from_history(
	events: tuple[PublicHistoryEvent, ...], roster: list[Mapping[str, Any]], opponent_side: str | None
) -> set[str]:
	"""Reconstruct selected-four confirmations from the public timeline without persistent process memory."""
	if opponent_side is None:
		return set()
	confirmed: set[str] = set()
	has_illusion = any(_normalize_id(item.get("ability")) == "illusion" for item in roster)
	for event in events:
		if event.type not in ("switch", "drag", "replace"):
			continue
		args = event.data.get("args", [])
		if not isinstance(args, list) or len(args) < 2 or not isinstance(args[0], str):
			continue
		if not args[0].startswith(f"{opponent_side}"):
			continue
		# While an Illusion user remains possible, ordinary switch/drag appearances do
		# not prove roster identity. A public replace event is the explicit reveal.
		if has_illusion and event.type != "replace":
			continue
		matched = _match_roster_from_public_identity(args[0], str(args[1]), roster)
		if matched is not None:
			confirmed.add(matched)
	return confirmed


def _match_roster_from_public_identity(
	ident: str, details: str, roster: list[Mapping[str, Any]]
) -> str | None:
	name = ident.split(":", 1)[1].strip() if ":" in ident else ""
	species = details.split(",", 1)[0].strip()
	name_id = _normalize_id(name)
	species_id = _normalize_id(species)
	matches = {
		item["id"]
		for item in roster
		if (name_id and _normalize_id(item.get("name")) == name_id) or
		(species_id and _normalize_id(item.get("species")) == species_id)
	}
	return next(iter(matches)) if len(matches) == 1 else None


def _normalize_id(value: Any) -> str:
	if not isinstance(value, str):
		return ""
	return "".join(character.lower() for character in value if character.isalnum())


def _sorted_number_pairs(value: Mapping[str, Any]) -> tuple[tuple[str, int], ...]:
	return tuple((str(key), int(item)) for key, item in sorted(_mapping(value, "numeric state").items()))


def _array(value: Mapping[str, Any], key: str) -> list[Any]:
	item = value.get(key)
	if not isinstance(item, list):
		raise ValueError(f"{key} must be an array")
	return item


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
	if not isinstance(value, Mapping):
		raise ValueError(f"{label} must be an object")
	return value


def _required_mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
	return _mapping(value.get(key), key)
