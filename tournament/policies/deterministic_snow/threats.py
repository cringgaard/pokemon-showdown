"""B4 baseline threat modelling for the deterministic snow-team policy.

The threat layer is descriptive rather than strategic: it answers what each
publicly known opponent move can mechanically do to each of our active slots.
It never consumes preferred-plan or resource importance.

Damage values are deliberately coarse. Champions OTS does not expose opponent
Stat Points, so the fallback estimator combines B2 format-aware move/type facts,
a neutral public base-stat proxy, exact own defensive state, wide uncertainty
bounds, and only those defensive ability/item modifiers explicitly annotated by
B2. Comparable non-critical public damage observations take precedence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from typing import Iterable, Mapping

from .knowledge import OwnPokemonKnowledge, OpponentActiveKnowledge, OpponentRosterKnowledge
from .mechanics import MechanicsSnapshot, MoveMechanics, UnresolvedMechanicError, to_id
from .reconstruction import KnowledgeState


class DamageBand(str, Enum):
	UNKNOWN = "UNKNOWN"
	NONE = "NONE"
	CHIP = "CHIP"
	MODERATE = "MODERATE"
	HEAVY = "HEAVY"
	SEVERE = "SEVERE"
	LETHAL = "LETHAL"


class KOConfidence(str, Enum):
	IMPOSSIBLE = "IMPOSSIBLE"
	UNLIKELY = "UNLIKELY"
	POSSIBLE = "POSSIBLE"
	VERY_LIKELY = "VERY_LIKELY"
	CERTAIN = "CERTAIN"


class ThreatCategory(str, Enum):
	SINGLE_TARGET_DAMAGE = "SINGLE_TARGET_DAMAGE"
	SPREAD_DAMAGE = "SPREAD_DAMAGE"
	PRIORITY_DAMAGE = "PRIORITY_DAMAGE"
	LIKELY_KO = "LIKELY_KO"
	DOUBLE_TARGET_KO = "DOUBLE_TARGET_KO"
	FAKE_OUT = "FAKE_OUT"
	REDIRECTION = "REDIRECTION"
	ENCORE = "ENCORE"
	STATUS = "STATUS"
	SPEED_CONTROL = "SPEED_CONTROL"
	WEATHER_CONTROL = "WEATHER_CONTROL"
	FIELD_CONTROL = "FIELD_CONTROL"
	PHYSICAL_SETUP = "PHYSICAL_SETUP"
	SPECIAL_SETUP = "SPECIAL_SETUP"
	SPEED_SETUP = "SPEED_SETUP"
	PROTECT = "PROTECT"
	WIDE_GUARD = "WIDE_GUARD"
	RECOVERY = "RECOVERY"
	SWITCH = "SWITCH"
	IMMUNITY_PIVOT = "IMMUNITY_PIVOT"
	WEATHER_PIVOT = "WEATHER_PIVOT"
	ABILITY_PIVOT = "ABILITY_PIVOT"


@dataclass(frozen=True)
class TargetThreat:
	position: str
	target_id: str
	damage_band: DamageBand
	ko_confidence: KOConfidence
	estimated_fraction_low: float | None
	estimated_fraction_mid: float | None
	estimated_fraction_high: float | None
	effectiveness: float | None
	estimate_source: str
	mechanic_uncertain: bool


@dataclass(frozen=True)
class BaselineMoveThreat:
	attacker_position: str
	attacker_identity: str
	attacker_species: str | None
	move: str
	move_type: str
	category: str
	priority: int
	spread: bool
	currently_available: bool | None
	tags: tuple[ThreatCategory, ...]
	targets: tuple[TargetThreat, ...]


@dataclass(frozen=True)
class SlotThreat:
	position: str
	target_id: str
	expected_incoming_damage: float | None
	worst_credible_damage: float | None
	likely_attackers: tuple[str, ...]
	likely_moves: tuple[str, ...]
	double_target_risk: bool
	ko_confidence: KOConfidence
	status_risk: float
	control_risk: float


@dataclass(frozen=True)
class ThreatModel:
	move_threats: tuple[BaselineMoveThreat, ...]
	slot_threats: tuple[SlotThreat, ...]
	major_threats: tuple[str, ...]
	physical_pressure: float
	special_pressure: float
	accuracy_bypass_pressure: float
	weather_control_pressure: float


_CONTROL_TAGS = frozenset({
	ThreatCategory.FAKE_OUT,
	ThreatCategory.REDIRECTION,
	ThreatCategory.ENCORE,
	ThreatCategory.SPEED_CONTROL,
	ThreatCategory.WEATHER_CONTROL,
	ThreatCategory.FIELD_CONTROL,
})
_STATUS_TAGS = frozenset({ThreatCategory.STATUS, ThreatCategory.FAKE_OUT})
_KO_RANK = {
	KOConfidence.IMPOSSIBLE: 0,
	KOConfidence.UNLIKELY: 1,
	KOConfidence.POSSIBLE: 2,
	KOConfidence.VERY_LIKELY: 3,
	KOConfidence.CERTAIN: 4,
}


def build_threat_model(knowledge: KnowledgeState, mechanics: MechanicsSnapshot) -> ThreatModel:
	"""Build a deterministic, strategic-importance-free current threat model."""
	if hasattr(mechanics, "require_champions_format"):
		mechanics.require_champions_format()
	own_by_id = {pokemon.id: pokemon for pokemon in knowledge.own_team}
	own_active = [
		(position, own_by_id[pokemon_id])
		for position, pokemon_id in knowledge.own_active
		if pokemon_id in own_by_id
	]
	roster_by_id = {pokemon.id: pokemon for pokemon in knowledge.opponent_roster}
	move_threats: list[BaselineMoveThreat] = []
	physical = special = accuracy_bypass = weather_control = available_moves = 0

	for active in knowledge.opponent_active:
		roster = _active_roster(active, roster_by_id)
		attacker_species = _active_species(active, roster)
		attacker_types = _active_types(active)
		attacker_ability = _active_ability(active, roster)
		ability_bypass = _ability_bypasses_accuracy(mechanics, attacker_ability)
		for move_id in _known_active_moves(active, roster, knowledge):
			try:
				move = mechanics.move(move_id)
			except KeyError:
				continue
			availability = _current_availability(knowledge, active, roster, move.id)
			tags = _move_tags(move, mechanics)
			targets = tuple(
				_target_threat(
					knowledge, mechanics, active, roster, attacker_species, attacker_types, move, position, target
				)
				for position, target in own_active
			)
			if availability is not False:
				if any(item.ko_confidence in (KOConfidence.CERTAIN, KOConfidence.VERY_LIKELY) for item in targets):
					tags.add(ThreatCategory.LIKELY_KO)
				if move.is_spread and len(targets) >= 2 and all(
					item.ko_confidence in (KOConfidence.CERTAIN, KOConfidence.VERY_LIKELY) for item in targets
				):
					tags.add(ThreatCategory.DOUBLE_TARGET_KO)
				available_moves += 1
				if move.base_power > 0:
					physical += int(move.category == "Physical")
					special += int(move.category == "Special")
				if ability_bypass or move.ignore_accuracy or move.ignore_evasion:
					accuracy_bypass += 1
				if ThreatCategory.WEATHER_CONTROL in tags:
					weather_control += 1
			move_threats.append(BaselineMoveThreat(
				active.position,
				_active_identity(active, roster),
				attacker_species,
				move.id,
				move.type,
				move.category,
				move.priority,
				move.is_spread,
				availability,
				tuple(sorted(tags, key=lambda item: item.value)),
				targets,
			))

	move_tuple = tuple(sorted(move_threats, key=lambda item: (item.attacker_position, item.move)))
	slots = tuple(_slot_threat(position, target, move_tuple) for position, target in own_active)
	damaging_total = physical + special
	denominator = max(1, available_moves)
	return ThreatModel(
		move_tuple,
		slots,
		_major_threats(move_tuple, slots),
		physical / damaging_total if damaging_total else 0.0,
		special / damaging_total if damaging_total else 0.0,
		min(1.0, accuracy_bypass / denominator),
		min(1.0, weather_control / denominator),
	)


def _active_roster(
	active: OpponentActiveKnowledge, roster_by_id: Mapping[str, OpponentRosterKnowledge]
) -> OpponentRosterKnowledge | None:
	identity = active.established_identity.value
	return roster_by_id.get(identity) if isinstance(identity, str) else None


def _known_active_moves(
	active: OpponentActiveKnowledge, roster: OpponentRosterKnowledge | None, knowledge: KnowledgeState
) -> tuple[str, ...]:
	if roster is not None:
		return tuple(sorted({move.id for move in roster.moves}))
	apparent = active.apparent_identity.value
	wanted = to_id(apparent) if isinstance(apparent, str) else ""
	return tuple(sorted({
		move.move for move in knowledge.history.move_observations if _actor_name_id(move.actor) == wanted
	}))


def _active_identity(active: OpponentActiveKnowledge, roster: OpponentRosterKnowledge | None) -> str:
	if roster is not None:
		return roster.id
	apparent = active.apparent_identity.value
	return f"apparent:{apparent}" if isinstance(apparent, str) else f"unknown:{active.position}"


def _active_species(active: OpponentActiveKnowledge, roster: OpponentRosterKnowledge | None) -> str | None:
	current = active.current_form.value
	if isinstance(current, str):
		return current
	return roster.species if roster is not None else None


def _active_types(active: OpponentActiveKnowledge) -> tuple[str, ...] | None:
	value = active.types.value
	if isinstance(value, list) and all(isinstance(item, str) for item in value):
		return tuple(value)
	return None


def _active_ability(active: OpponentActiveKnowledge, roster: OpponentRosterKnowledge | None) -> str | None:
	value = active.ability.value
	if isinstance(value, str):
		return value
	return roster.ability if roster is not None else None


def _ability_bypasses_accuracy(mechanics: MechanicsSnapshot, ability: str | None) -> bool:
	if not ability:
		return False
	try:
		return mechanics.ability_bypasses_accuracy(ability)
	except (KeyError, ValueError):
		return False


def _current_availability(
	knowledge: KnowledgeState,
	active: OpponentActiveKnowledge,
	roster: OpponentRosterKnowledge | None,
	move_id: str,
) -> bool | None:
	if move_id != "fakeout":
		return True
	identity = roster.id if roster is not None else None
	for item in knowledge.fake_out_eligibility:
		if item.position != active.position:
			continue
		if identity is not None and item.pokemon_identity != identity:
			continue
		return item.eligible
	return None


def _move_tags(move: MoveMechanics, mechanics: MechanicsSnapshot) -> set[ThreatCategory]:
	tags: set[ThreatCategory] = set()
	if move.base_power > 0:
		tags.add(ThreatCategory.SPREAD_DAMAGE if move.is_spread else ThreatCategory.SINGLE_TARGET_DAMAGE)
		if move.priority > 0:
			tags.add(ThreatCategory.PRIORITY_DAMAGE)
	if move.id == "fakeout":
		tags.add(ThreatCategory.FAKE_OUT)
	if move.id in ("followme", "ragepowder", "spotlight"):
		tags.add(ThreatCategory.REDIRECTION)
	if move.id == "encore":
		tags.add(ThreatCategory.ENCORE)
	if move.status or move.volatile_status:
		tags.add(ThreatCategory.STATUS)
	boosts = dict(move.boosts)
	self_boosts = dict(move.self_boosts)
	if boosts.get("spe", 0) < 0 or move.id in ("tailwind", "trickroom", "electroweb", "icywind"):
		tags.add(ThreatCategory.SPEED_CONTROL)
	if move.weather:
		tags.add(ThreatCategory.WEATHER_CONTROL)
	if move.terrain or move.pseudo_weather or move.side_condition:
		tags.add(ThreatCategory.FIELD_CONTROL)
	if self_boosts.get("atk", 0) > 0 or self_boosts.get("def", 0) > 0:
		tags.add(ThreatCategory.PHYSICAL_SETUP)
	if self_boosts.get("spa", 0) > 0 or self_boosts.get("spd", 0) > 0:
		tags.add(ThreatCategory.SPECIAL_SETUP)
	if self_boosts.get("spe", 0) > 0:
		tags.add(ThreatCategory.SPEED_SETUP)
	try:
		if mechanics.semantic("moves", move.id).get("protection_move") is True:
			tags.add(ThreatCategory.PROTECT)
	except (KeyError, ValueError):
		if move.id in ("protect", "detect", "spikyshield", "kingsshield", "banefulbunker"):
			tags.add(ThreatCategory.PROTECT)
	if move.id == "wideguard":
		tags.add(ThreatCategory.WIDE_GUARD)
	if move.heal or move.drain:
		tags.add(ThreatCategory.RECOVERY)
	if move.force_switch or move.self_switch:
		tags.add(ThreatCategory.SWITCH)
	return tags


def _target_threat(
	knowledge: KnowledgeState,
	mechanics: MechanicsSnapshot,
	active: OpponentActiveKnowledge,
	roster: OpponentRosterKnowledge | None,
	attacker_species: str | None,
	attacker_types: tuple[str, ...] | None,
	move: MoveMechanics,
	position: str,
	target: OwnPokemonKnowledge,
) -> TargetThreat:
	if move.base_power <= 0:
		uncertain = any(name in move.callback_names for name in ("basePowerCallback", "damageCallback", "onBasePower"))
		return TargetThreat(
			position, target.id, DamageBand.UNKNOWN if uncertain else DamageBand.NONE,
			KOConfidence.POSSIBLE if uncertain else KOConfidence.IMPOSSIBLE,
			None, None, None, None, "unresolved_dynamic_damage" if uncertain else "non_damaging", uncertain,
		)
	try:
		effectiveness = mechanics.move_multiplier(move, target.types)
	except (KeyError, ValueError, UnresolvedMechanicError):
		return TargetThreat(
			position, target.id, DamageBand.UNKNOWN, KOConfidence.POSSIBLE,
			None, None, None, None, "unresolved_effectiveness", True,
		)
	if effectiveness == 0:
		return _zero_threat(position, target.id, effectiveness, "type_immunity")

	empirical = _comparable_empirical_damage(knowledge, active, move.id, target)
	if empirical is not None:
		low, mid, high = max(0.0, empirical * 0.75), empirical, min(2.0, empirical * 1.25)
		return TargetThreat(
			position, target.id, _damage_band(mid), _ko_confidence(low, mid, high, target.health.percent / 100.0),
			low, mid, high, effectiveness, "empirical_public_damage", True,
		)
	if attacker_species is None:
		return TargetThreat(
			position, target.id, DamageBand.UNKNOWN, KOConfidence.POSSIBLE,
			None, None, None, effectiveness, "unknown_attacker_identity", True,
		)
	try:
		species = mechanics.species(attacker_species)
	except KeyError:
		return TargetThreat(
			position, target.id, DamageBand.UNKNOWN, KOConfidence.POSSIBLE,
			None, None, None, effectiveness, "unknown_attacker_form", True,
		)

	offensive_stat = move.override_offensive_stat or ("atk" if move.category == "Physical" else "spa")
	defensive_stat = move.override_defensive_stat or ("def" if move.category == "Physical" else "spd")
	base_offense = species.stats.get(offensive_stat)
	defense = dict(target.stats).get(defensive_stat)
	if base_offense is None or defense is None or defense <= 0 or target.health.maximum <= 0:
		return TargetThreat(
			position, target.id, DamageBand.UNKNOWN, KOConfidence.POSSIBLE,
			None, None, None, effectiveness, "missing_stat_proxy", True,
		)

	defensive_multiplier, defensive_source = _defensive_modifier(
		knowledge, mechanics, target, move, effectiveness
	)
	if defensive_multiplier == 0:
		return _zero_threat(position, target.id, effectiveness, defensive_source or "ability_immunity")
	level = roster.level if roster and roster.level else 50
	offense = _neutral_stat_proxy(base_offense) * _boost_multiplier(dict(active.boosts).get(offensive_stat, 0))
	defense_value = float(defense) * _boost_multiplier(dict(target.boosts).get(defensive_stat, 0))
	stab = 1.5 if attacker_types and any(to_id(type_name) == to_id(move.type) for type_name in attacker_types) else 1.0
	spread = 0.75 if move.is_spread else 1.0
	base_damage = (((2 * level / 5 + 2) * move.base_power * offense / defense_value) / 50 + 2)
	mid = base_damage * stab * effectiveness * spread * defensive_multiplier * 0.925 / target.health.maximum
	uncertain = attacker_types is None or any(
		name in move.callback_names for name in ("basePowerCallback", "damageCallback", "onBasePower", "onModifyMove", "onModifyType")
	)
	low, high = max(0.0, mid * 0.72), min(2.0, mid * 1.35)
	source = "coarse_format_proxy" + (f"+{defensive_source}" if defensive_source else "")
	return TargetThreat(
		position, target.id, _damage_band(mid), _ko_confidence(low, mid, high, target.health.percent / 100.0),
		low, mid, high, effectiveness, source, uncertain,
	)


def _defensive_modifier(
	knowledge: KnowledgeState,
	mechanics: MechanicsSnapshot,
	target: OwnPokemonKnowledge,
	move: MoveMechanics,
	effectiveness: float,
) -> tuple[float, str]:
	multiplier = 1.0
	sources: list[str] = []
	try:
		ability = mechanics.semantic("abilities", target.ability)
	except (KeyError, ValueError):
		ability = {}
	move_type = to_id(move.type)
	if move_type == "fire" and ability.get("fire_immunity") is True:
		return 0.0, "ability_fire_immunity"
	if move_type == "water" and "water_immunity_and_heal_fraction" in ability:
		return 0.0, "ability_water_immunity"
	if move_type == "fire" and _number(ability.get("fire_damage_multiplier")) is not None:
		multiplier *= float(ability["fire_damage_multiplier"])
		sources.append("ability_fire_modifier")
	if effectiveness > 1 and _number(ability.get("super_effective_damage_multiplier")) is not None:
		multiplier *= float(ability["super_effective_damage_multiplier"])
		sources.append("ability_super_effective_modifier")

	if target.item:
		try:
			item = mechanics.semantic("items", target.item)
		except (KeyError, ValueError):
			item = {}
		type_map = item.get("super_effective_type_damage_multiplier")
		if effectiveness > 1 and isinstance(type_map, Mapping):
			for type_name, value in type_map.items():
				if to_id(str(type_name)) == move_type and _number(value) is not None:
					multiplier *= float(value)
					sources.append("held_item_type_modifier")
					break

	own_by_id = {pokemon.id: pokemon for pokemon in knowledge.own_team}
	active_ids = [pokemon_id for _, pokemon_id in knowledge.own_active]
	for pokemon_id in active_ids:
		if pokemon_id == target.id:
			continue
		ally = own_by_id.get(pokemon_id)
		if ally is None or ally.fainted:
			continue
		try:
			ally_semantics = mechanics.semantic("abilities", ally.ability)
		except (KeyError, ValueError):
			continue
		ally_multiplier = _number(ally_semantics.get("ally_damage_multiplier"))
		if ally_multiplier is not None:
			multiplier *= ally_multiplier
			sources.append("ally_damage_modifier")
	return multiplier, "+".join(sources)


def _number(value: object) -> float | None:
	if isinstance(value, bool) or not isinstance(value, (int, float)):
		return None
	return float(value)


def _zero_threat(position: str, target_id: str, effectiveness: float, source: str) -> TargetThreat:
	return TargetThreat(
		position, target_id, DamageBand.NONE, KOConfidence.IMPOSSIBLE,
		0.0, 0.0, 0.0, effectiveness, source, False,
	)


def _neutral_stat_proxy(base_stat: int) -> float:
	return float(base_stat + 20)


def _boost_multiplier(stage: int) -> float:
	stage = max(-6, min(6, int(stage)))
	return (2 + stage) / 2 if stage >= 0 else 2 / (2 - stage)


def _damage_band(fraction: float) -> DamageBand:
	if fraction <= 0:
		return DamageBand.NONE
	if fraction < 0.15:
		return DamageBand.CHIP
	if fraction < 0.35:
		return DamageBand.MODERATE
	if fraction < 0.65:
		return DamageBand.HEAVY
	if fraction < 1.0:
		return DamageBand.SEVERE
	return DamageBand.LETHAL


def _ko_confidence(low: float, mid: float, high: float, current_hp_fraction: float) -> KOConfidence:
	if current_hp_fraction <= 0 or low >= current_hp_fraction:
		return KOConfidence.CERTAIN
	if mid >= current_hp_fraction:
		return KOConfidence.VERY_LIKELY
	if high >= current_hp_fraction:
		return KOConfidence.POSSIBLE
	return KOConfidence.UNLIKELY


def _comparable_empirical_damage(
	knowledge: KnowledgeState, active: OpponentActiveKnowledge, move_id: str, target: OwnPokemonKnowledge
) -> float | None:
	apparent = active.apparent_identity.value
	attacker_names = {to_id(apparent)} if isinstance(apparent, str) else set()
	identity = active.established_identity.value
	if isinstance(identity, str):
		roster = next((item for item in knowledge.opponent_roster if item.id == identity), None)
		if roster is not None:
			attacker_names.update((to_id(roster.name), to_id(roster.species)))
	for evidence in reversed(knowledge.history.damage_evidence):
		if evidence.move != move_id or evidence.hp_fraction_removed is None or evidence.attacker is None:
			continue
		if _actor_name_id(evidence.attacker) not in attacker_names or _actor_name_id(evidence.target) != to_id(target.name):
			continue
		try:
			context = json.loads(evidence.context)
		except json.JSONDecodeError:
			continue
		if context.get("critical") or not context.get("direct_move"):
			continue
		return float(evidence.hp_fraction_removed)
	return None


def _actor_name_id(actor: str) -> str:
	return to_id(actor.split(":", 1)[-1])


def _slot_threat(position: str, target: OwnPokemonKnowledge, threats: tuple[BaselineMoveThreat, ...]) -> SlotThreat:
	relevant = [
		(threat, target_threat)
		for threat in threats if threat.currently_available is not False
		for target_threat in threat.targets if target_threat.position == position
	]
	by_attacker: dict[str, tuple[BaselineMoveThreat, TargetThreat]] = {}
	for pair in relevant:
		current = by_attacker.get(pair[0].attacker_identity)
		if current is None or _target_sort_key(pair[1]) > _target_sort_key(current[1]):
			by_attacker[pair[0].attacker_identity] = pair
	credible = sorted(by_attacker.values(), key=lambda pair: _target_sort_key(pair[1]), reverse=True)
	known_mid = [pair[1].estimated_fraction_mid for pair in credible if pair[1].estimated_fraction_mid is not None]
	known_high = [pair[1].estimated_fraction_high for pair in credible if pair[1].estimated_fraction_high is not None]
	expected = min(2.0, sum(float(value) for value in known_mid)) if known_mid else None
	worst = min(2.0, sum(float(value) for value in known_high)) if known_high else None
	current_hp = target.health.percent / 100.0
	if credible and all(pair[1].estimated_fraction_low is not None for pair in credible):
		low = sum(float(pair[1].estimated_fraction_low) for pair in credible)
		mid = sum(float(pair[1].estimated_fraction_mid) for pair in credible)
		high = sum(float(pair[1].estimated_fraction_high) for pair in credible)
		ko = _ko_confidence(low, mid, high, current_hp)
	else:
		ko = max(
			(pair[1].ko_confidence for pair in credible),
			key=lambda value: _KO_RANK[value],
			default=KOConfidence.IMPOSSIBLE,
		)
	double_target = len(credible) >= 2 and (worst is None or worst >= max(0.25, current_hp * 0.75))
	return SlotThreat(
		position,
		target.id,
		expected,
		worst,
		tuple(pair[0].attacker_identity for pair in credible[:4]),
		tuple(pair[0].move for pair in credible[:4]),
		double_target,
		ko,
		_risk_fraction(relevant, _STATUS_TAGS),
		_risk_fraction(relevant, _CONTROL_TAGS),
	)


def _target_sort_key(target: TargetThreat) -> tuple[int, float]:
	return _KO_RANK[target.ko_confidence], target.estimated_fraction_mid or 0.0


def _risk_fraction(
	relevant: Iterable[tuple[BaselineMoveThreat, TargetThreat]], categories: frozenset[ThreatCategory]
) -> float:
	items = list(relevant)
	if not items:
		return 0.0
	hits = sum(1 for threat, _ in items if categories.intersection(threat.tags))
	return min(1.0, hits / len(items))


def _major_threats(
	moves: tuple[BaselineMoveThreat, ...], slots: tuple[SlotThreat, ...]
) -> tuple[str, ...]:
	candidates: list[tuple[int, float, str]] = []
	for threat in moves:
		if threat.currently_available is False:
			continue
		for target in threat.targets:
			if target.ko_confidence in (KOConfidence.CERTAIN, KOConfidence.VERY_LIKELY, KOConfidence.POSSIBLE):
				candidates.append((
					_KO_RANK[target.ko_confidence],
					target.estimated_fraction_mid or 0.0,
					f"{threat.attacker_identity}:{threat.move}->{target.position}:{target.ko_confidence.value}",
				))
	for slot in slots:
		if slot.double_target_risk:
			candidates.append((3, slot.worst_credible_damage or 0.0, f"double-target->{slot.position}:{slot.ko_confidence.value}"))
	return tuple(item[2] for item in sorted(candidates, key=lambda item: (-item[0], -item[1], item[2]))[:8])
