"""B4 runtime win-condition and strategic resource valuation.

This layer is intentionally downstream from baseline threats. Preferred plans
may change how much we value our own resources, but they never change the
mechanical threat facts produced by :mod:`threats`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .config import PolicyConfig, TeamRole, default_config
from .knowledge import OwnPokemonKnowledge, SelectedFourStatus
from .mechanics import MechanicsSnapshot, UnresolvedMechanicError, to_id
from .reconstruction import KnowledgeState
from .threats import DamageBand, KOConfidence, ThreatCategory, ThreatModel, build_threat_model
from .trace import RuntimeStrategyScores


class PlanLabel(str, Enum):
	GLACEON_FORTRESS = "GLACEON_FORTRESS"
	AGGRON_FORTRESS = "AGGRON_FORTRESS"
	TACTICAL_OFFENSE = "TACTICAL_OFFENSE"
	FLEXIBLE = "FLEXIBLE"


DEFAULT_HP_UTILITY_CURVE: tuple[tuple[float, float], ...] = (
	(0.0, 0.0),
	(0.01, 0.20),
	(0.25, 0.45),
	(0.50, 0.70),
	(0.75, 0.90),
	(1.00, 1.00),
)


@dataclass(frozen=True)
class PlanAssessment:
	plan: PlanLabel
	score: float
	positive_reasons: tuple[str, ...]
	negative_reasons: tuple[str, ...]


@dataclass(frozen=True)
class ResourceValue:
	pokemon_id: str
	species: str
	base_value: float
	hp_utility: float
	role_multiplier: float
	remaining_utility: float
	value: float
	reasons: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeStrategyAssessment:
	scores: RuntimeStrategyScores
	plans: tuple[PlanAssessment, ...]
	resources: tuple[ResourceValue, ...]
	threats: ThreatModel


@dataclass(frozen=True)
class _Context:
	weather_contested: bool
	no_guard_active: bool
	gravity_active: bool
	ghost_fraction: float
	body_press_target_quality: float
	glaceon_offensive_matchups: int
	dangerous_glaceon_pressure: int
	spread_fire_relevance: float
	water_pressure: float
	opponent_fainted: int
	super_effective_pairs: int
	spread_cleanup: bool


def assess_runtime_strategy(
	knowledge: KnowledgeState,
	mechanics: MechanicsSnapshot,
	*,
	threats: ThreatModel | None = None,
	config: PolicyConfig | None = None,
	hp_curve: tuple[tuple[float, float], ...] = DEFAULT_HP_UTILITY_CURVE,
) -> RuntimeStrategyAssessment:
	"""Recompute the continuous B4 plan vector entirely from public state."""
	config = config or default_config()
	threats = threats or build_threat_model(knowledge, mechanics)
	context = _strategy_context(knowledge, mechanics, threats)
	glaceon = _find_own(knowledge, "glaceon")
	aggron = _find_own(knowledge, "aggron")
	ninetales = _find_own(knowledge, "ninetalesalola")
	maushold = _find_own(knowledge, "maushold")

	glaceon_plan = _score_glaceon(knowledge, threats, context, glaceon, ninetales, hp_curve)
	aggron_plan = _score_aggron(knowledge, threats, context, aggron, maushold, hp_curve)
	tactical_plan = _score_tactical(knowledge, threats, context, glaceon_plan.score, aggron_plan.score)
	plans = (glaceon_plan, aggron_plan, tactical_plan)
	ordered = sorted(plans, key=lambda item: (-item.score, item.plan.value))
	margin = ordered[0].score - ordered[1].score
	primary = ordered[0].plan if margin >= config.thresholds.clear_primary_plan_margin else PlanLabel.FLEXIBLE
	scores = RuntimeStrategyScores(
		glaceon_plan.score,
		aggron_plan.score,
		tactical_plan.score,
		primary.value,
	)
	return RuntimeStrategyAssessment(
		scores,
		plans,
		_resource_values(knowledge, config, scores, context, hp_curve),
		threats,
	)


def hp_utility(
	health_fraction: float,
	curve: tuple[tuple[float, float], ...] = DEFAULT_HP_UTILITY_CURVE,
) -> float:
	"""Piecewise-linear HP utility; any nonzero HP retains meaningful value."""
	if not curve or curve[0][0] != 0 or curve[-1][0] != 1:
		raise ValueError("HP utility curve must span 0..1")
	if not 0 <= curve[-1][1] <= 1 or not 0 <= curve[0][1] <= 1:
		raise ValueError("HP utilities must be between zero and one")
	for point, next_point in zip(curve, curve[1:]):
		if next_point[0] <= point[0] or not 0 <= next_point[1] <= 1:
			raise ValueError("HP utility curve fractions must increase and utilities must be 0..1")
	fraction = max(0.0, min(1.0, float(health_fraction)))
	for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
		if fraction <= x1:
			weight = (fraction - x0) / (x1 - x0)
			return y0 + (y1 - y0) * weight
	return curve[-1][1]


def _score_glaceon(
	knowledge: KnowledgeState,
	threats: ThreatModel,
	context: _Context,
	glaceon: OwnPokemonKnowledge | None,
	ninetales: OwnPokemonKnowledge | None,
	hp_curve: tuple[tuple[float, float], ...],
) -> PlanAssessment:
	if glaceon is None or glaceon.fainted:
		return PlanAssessment(PlanLabel.GLACEON_FORTRESS, 0.0, (), ("Glaceon unavailable",))
	positive: list[str] = []
	negative: list[str] = []
	score = 35.0
	hp = hp_utility(glaceon.health.percent / 100.0, hp_curve)
	score += 25 * hp
	positive.append(f"Glaceon HP utility {hp:.2f}")
	weather = knowledge.field.weather.value
	if isinstance(weather, str) and to_id(weather) == "snow":
		score += 12
		positive.append("snow active")
	if _own_condition_active(knowledge, "auroraveil"):
		score += 10
		positive.append("Aurora Veil active")
	boosts = dict(glaceon.boosts)
	calm_mind_progress = max(0, min(boosts.get("spa", 0), boosts.get("spd", 0)))
	if calm_mind_progress:
		score += min(12.0, calm_mind_progress * 6.0)
		positive.append(f"Calm Mind-like progress +{calm_mind_progress}")
	if ninetales is not None and not ninetales.fainted and context.weather_contested:
		score += 6
		positive.append("Ninetales preserves weather reset")
	if context.glaceon_offensive_matchups:
		score += min(12.0, context.glaceon_offensive_matchups * 6.0)
		positive.append(f"{context.glaceon_offensive_matchups} favorable Ice matchup(s)")
	if threats.physical_pressure >= 0.60:
		score += 4
		positive.append("opponent pressure is primarily physical")

	if context.no_guard_active:
		score -= 22
		negative.append("active No Guard bypasses evasion plan")
	if context.gravity_active:
		score -= 12
		negative.append("Gravity substantially increases opposing accuracy")
	if threats.accuracy_bypass_pressure:
		score -= min(15.0, 15.0 * threats.accuracy_bypass_pressure)
		negative.append("accuracy/evasion bypass pressure")
	if context.dangerous_glaceon_pressure:
		score -= min(20.0, 4.0 * context.dangerous_glaceon_pressure)
		negative.append("Fire/Fighting/Rock/Steel pressure remains")
	if (not isinstance(weather, str) or to_id(weather) != "snow") and (ninetales is None or ninetales.fainted):
		score -= 15
		negative.append("snow absent with no Ninetales reset available")
	_slot_pressure_penalty(knowledge, threats, glaceon, score_parts=(20.0, 10.0), negative=negative)
	# The helper returns its penalty through the reason list; calculate it deterministically here.
	score -= _active_pressure_penalty(knowledge, threats, glaceon, 20.0, 10.0)
	return PlanAssessment(PlanLabel.GLACEON_FORTRESS, _clamp_score(score), tuple(positive), tuple(negative))


def _score_aggron(
	knowledge: KnowledgeState,
	threats: ThreatModel,
	context: _Context,
	aggron: OwnPokemonKnowledge | None,
	maushold: OwnPokemonKnowledge | None,
	hp_curve: tuple[tuple[float, float], ...],
) -> PlanAssessment:
	if aggron is None or aggron.fainted:
		return PlanAssessment(PlanLabel.AGGRON_FORTRESS, 0.0, (), ("Aggron unavailable",))
	positive: list[str] = []
	negative: list[str] = []
	score = 35.0
	hp = hp_utility(aggron.health.percent / 100.0, hp_curve)
	score += 25 * hp
	positive.append(f"Aggron HP utility {hp:.2f}")
	if _is_mega(aggron):
		score += 15
		positive.append("Mega Aggron state established")
	defense_boost = max(0, dict(aggron.boosts).get("def", 0))
	if defense_boost:
		score += min(12.0, defense_boost * 6.0)
		positive.append(f"Defense boost +{defense_boost}")
	if threats.physical_pressure:
		score += 12 * threats.physical_pressure
		positive.append("physical opponent pressure favors Aggron")
	if context.body_press_target_quality:
		score += 12 * context.body_press_target_quality
		positive.append("useful Body Press targets remain")
	if maushold is not None and not maushold.fainted:
		score += 6
		positive.append("Maushold support available")

	if to_id(aggron.status or "") == "brn":
		score -= 22
		negative.append("burn damages Body Press endgame quality")
	if context.ghost_fraction:
		score -= 18 * context.ghost_fraction
		negative.append("Ghost-heavy remaining roster")
	if threats.special_pressure:
		score -= 16 * threats.special_pressure
		negative.append("special pressure bypasses physical fortress strength")
	if aggron.health.percent <= 25:
		score -= 8
		negative.append("Aggron is at low HP")
	if _active_position(knowledge, aggron.id) is not None and not _is_mega(aggron):
		penalty = _active_pressure_penalty(knowledge, threats, aggron, 15.0, 7.0)
		if penalty:
			score -= penalty
			negative.append("base Aggron faces dangerous pre-Mega pressure")
	return PlanAssessment(PlanLabel.AGGRON_FORTRESS, _clamp_score(score), tuple(positive), tuple(negative))


def _score_tactical(
	knowledge: KnowledgeState,
	threats: ThreatModel,
	context: _Context,
	glaceon_score: float,
	aggron_score: float,
) -> PlanAssessment:
	positive: list[str] = []
	negative: list[str] = []
	score = 10.0
	low_hp = sum(1 for active in knowledge.opponent_active if active.health.percent <= 50 and not active.fainted)
	critical_hp = sum(1 for active in knowledge.opponent_active if active.health.percent <= 25 and not active.fainted)
	if low_hp:
		score += low_hp * 14
		positive.append(f"{low_hp} active opponent(s) in cleanup range")
	if critical_hp:
		score += critical_hp * 6
		positive.append(f"{critical_hp} active opponent(s) critically low")
	if context.opponent_fainted:
		score += min(18.0, context.opponent_fainted * 6.0)
		positive.append("opponent resources already removed")
	if context.super_effective_pairs:
		score += min(18.0, context.super_effective_pairs * 6.0)
		positive.append("direct super-effective coverage is available")
	if context.spread_cleanup:
		score += 15
		positive.append("spread cleanup can cash out the position")
	fortress_best = max(glaceon_score, aggron_score)
	if fortress_best < 60:
		score += min(12.0, (60 - fortress_best) * 0.30)
		positive.append("fortress plans are currently weak")
	if any(slot.ko_confidence in (KOConfidence.CERTAIN, KOConfidence.VERY_LIKELY) for slot in threats.slot_threats):
		score += 6
		positive.append("immediate pressure rewards converting the turn")
	if not knowledge.opponent_active:
		negative.append("no active opponent pressure to cash out")
	return PlanAssessment(PlanLabel.TACTICAL_OFFENSE, _clamp_score(score), tuple(positive), tuple(negative))


def _strategy_context(knowledge: KnowledgeState, mechanics: MechanicsSnapshot, threats: ThreatModel) -> _Context:
	remaining_roster = [
		pokemon for pokemon in knowledge.opponent_roster
		if pokemon.selected_four is not SelectedFourStatus.CONFIRMED_NOT_SELECTED
	]
	weather_contested = False
	ghosts = body_press_total = body_press_good = 0
	for pokemon in remaining_roster:
		if to_id(pokemon.ability or "") in ("drizzle", "drought", "sandstream", "snowwarning"):
			weather_contested = True
		try:
			species = mechanics.species(pokemon.species)
		except KeyError:
			continue
		if any(to_id(type_name) == "ghost" for type_name in species.types):
			ghosts += 1
		body_press_total += 1
		try:
			multiplier = mechanics.move_multiplier("bodypress", species.types)
		except (KeyError, ValueError, UnresolvedMechanicError):
			multiplier = 1.0
		if multiplier >= 1:
			body_press_good += 1
		for move in pokemon.moves:
			try:
				weather_contested = weather_contested or bool(mechanics.move(move.id).weather)
			except KeyError:
				pass

	no_guard = False
	for active in knowledge.opponent_active:
		ability = active.ability.value
		if isinstance(ability, str):
			try:
				no_guard = no_guard or mechanics.ability_bypasses_accuracy(ability)
			except (KeyError, ValueError):
				pass
	gravity = any(condition.id == "gravity" and condition.active for condition in knowledge.field.conditions)
	current_threats = tuple(threat for threat in threats.move_threats if threat.currently_available is not False)
	dangerous = sum(
		1 for threat in current_threats
		if to_id(threat.move_type) in ("fire", "fighting", "rock", "steel")
		and any(target.damage_band not in (DamageBand.NONE, DamageBand.UNKNOWN) for target in threat.targets)
	)
	spread_fire = min(1.0, sum(
		1 for threat in current_threats
		if threat.spread and to_id(threat.move_type) == "fire" and ThreatCategory.SPREAD_DAMAGE in threat.tags
	) / 2.0)
	water_pressure = min(1.0, sum(
		1 for threat in current_threats if to_id(threat.move_type) == "water"
	) / 2.0)
	weather = knowledge.field.weather.value
	if isinstance(weather, str) and to_id(weather) == "rain":
		water_pressure = max(water_pressure, 0.75)
	return _Context(
		weather_contested,
		no_guard,
		gravity,
		ghosts / len(remaining_roster) if remaining_roster else 0.0,
		body_press_good / body_press_total if body_press_total else 0.0,
		_own_favorable_matchups(knowledge, mechanics, "glaceon"),
		dangerous,
		spread_fire,
		water_pressure,
		_opponent_fainted_count(knowledge),
		_own_super_effective_pairs(knowledge, mechanics),
		_spread_cleanup_available(knowledge, mechanics),
	)


def _resource_values(
	knowledge: KnowledgeState,
	config: PolicyConfig,
	scores: RuntimeStrategyScores,
	context: _Context,
	hp_curve: tuple[tuple[float, float], ...],
) -> tuple[ResourceValue, ...]:
	roles = tuple(config.team_roles)
	result: list[ResourceValue] = []
	weather = knowledge.field.weather.value
	for pokemon in knowledge.own_team:
		role = _team_role_for(pokemon, roles)
		base = role.base_resource_value if role is not None else 75.0
		if pokemon.fainted:
			result.append(ResourceValue(pokemon.id, pokemon.species, base, 0.0, 0.0, 0.0, 0.0, ("fainted",)))
			continue
		hp = hp_utility(pokemon.health.percent / 100.0, hp_curve)
		species = to_id(pokemon.species)
		reasons: list[str] = []
		if species == "glaceon":
			role_multiplier = 0.65 + 0.70 * scores.glaceon_fortress / 100.0
			reasons.append("scales with Glaceon fortress viability")
		elif species.startswith("aggron"):
			role_multiplier = 0.65 + 0.70 * scores.aggron_fortress / 100.0
			reasons.append("scales with Aggron fortress viability")
		elif species == "ninetalesalola":
			role_multiplier = 0.75 + 0.50 * scores.glaceon_fortress / 100.0
			if context.weather_contested:
				role_multiplier += 0.15
				reasons.append("weather war keeps reset value high")
			reasons.append("supports Glaceon fortress")
		elif species == "maushold":
			role_multiplier = 0.75 + 0.45 * max(scores.glaceon_fortress, scores.aggron_fortress) / 100.0
			reasons.append("redirection/Friend Guard supports either fortress")
		elif species == "armarouge":
			role_multiplier = 0.75 + 0.25 * max(scores.glaceon_fortress, scores.aggron_fortress) / 100.0
			role_multiplier += 0.20 * context.spread_fire_relevance
			reasons.append("spread/Fire protection relevance")
		elif species == "heliolisk":
			role_multiplier = 0.80 + 0.35 * scores.tactical_offense / 100.0 + 0.15 * context.water_pressure
			reasons.append("tactical offense and anti-Water pressure")
		else:
			role_multiplier = 1.0
		remaining = 1.0
		if species.startswith("aggron") and to_id(pokemon.status or "") == "brn":
			remaining *= 0.75
			reasons.append("burn reduces remaining endgame utility")
		if species == "glaceon" and (not isinstance(weather, str) or to_id(weather) != "snow"):
			ninetales = _find_own(knowledge, "ninetalesalola")
			if ninetales is None or ninetales.fainted:
				remaining *= 0.85
				reasons.append("snow cannot currently be restored by Ninetales")
		if to_id(pokemon.status or "") in ("slp", "frz"):
			remaining *= 0.80
			reasons.append("major status reduces immediate utility")
		role_multiplier = max(0.25, min(1.50, role_multiplier))
		result.append(ResourceValue(
			pokemon.id,
			pokemon.species,
			base,
			hp,
			role_multiplier,
			remaining,
			base * hp * role_multiplier * remaining,
			tuple(reasons),
		))
	return tuple(result)


def _team_role_for(pokemon: OwnPokemonKnowledge, roles: Iterable[TeamRole]) -> TeamRole | None:
	species = to_id(pokemon.species)
	for role in roles:
		role_id = to_id(role.species)
		if species == role_id or species.startswith(role_id):
			return role
	return None


def _find_own(knowledge: KnowledgeState, species_id: str) -> OwnPokemonKnowledge | None:
	wanted = to_id(species_id)
	for pokemon in knowledge.own_team:
		current = to_id(pokemon.species)
		if current == wanted or current.startswith(wanted):
			return pokemon
	return None


def _active_position(knowledge: KnowledgeState, pokemon_id: str) -> str | None:
	return next((position for position, active_id in knowledge.own_active if active_id == pokemon_id), None)


def _own_condition_active(knowledge: KnowledgeState, condition_id: str) -> bool:
	wanted = to_id(condition_id)
	return any(to_id(condition.id) == wanted and condition.active for condition in knowledge.field.own_side_conditions)


def _is_mega(pokemon: OwnPokemonKnowledge) -> bool:
	if "mega" in to_id(pokemon.species):
		return True
	value = pokemon.transformation.value
	return isinstance(value, dict) and value.get("kind") == "mega"


def _active_pressure_penalty(
	knowledge: KnowledgeState,
	threats: ThreatModel,
	pokemon: OwnPokemonKnowledge,
	lethal_penalty: float,
	heavy_penalty: float,
) -> float:
	position = _active_position(knowledge, pokemon.id)
	if position is None:
		return 0.0
	slot = next((item for item in threats.slot_threats if item.position == position), None)
	if slot is None or slot.worst_credible_damage is None:
		return 0.0
	current = pokemon.health.percent / 100.0
	if slot.worst_credible_damage >= current:
		return lethal_penalty
	if slot.worst_credible_damage >= current * 0.60:
		return heavy_penalty
	return 0.0


def _slot_pressure_penalty(
	knowledge: KnowledgeState,
	threats: ThreatModel,
	pokemon: OwnPokemonKnowledge,
	*,
	score_parts: tuple[float, float],
	negative: list[str],
) -> None:
	penalty = _active_pressure_penalty(knowledge, threats, pokemon, *score_parts)
	if penalty == score_parts[0]:
		negative.append("credible incoming line can remove Glaceon")
	elif penalty:
		negative.append("heavy immediate pressure on Glaceon")


def _own_favorable_matchups(knowledge: KnowledgeState, mechanics: MechanicsSnapshot, species_id: str) -> int:
	pokemon = _find_own(knowledge, species_id)
	if pokemon is None or pokemon.fainted:
		return 0
	count = 0
	for active in knowledge.opponent_active:
		if active.fainted:
			continue
		types = active.types.value
		if not isinstance(types, list) or not types:
			continue
		best = 0.0
		for move in pokemon.moves:
			try:
				move_data = mechanics.move(move.id)
				if move_data.base_power > 0:
					best = max(best, mechanics.move_multiplier(move_data, types))
			except (KeyError, ValueError, UnresolvedMechanicError):
				continue
		if best > 1:
			count += 1
	return count


def _live_own_actives(knowledge: KnowledgeState) -> tuple[OwnPokemonKnowledge, ...]:
	own_by_id = {pokemon.id: pokemon for pokemon in knowledge.own_team}
	return tuple(
		pokemon for _, pokemon_id in knowledge.own_active
		if (pokemon := own_by_id.get(pokemon_id)) is not None and not pokemon.fainted
	)


def _own_super_effective_pairs(knowledge: KnowledgeState, mechanics: MechanicsSnapshot) -> int:
	count = 0
	for own in _live_own_actives(knowledge):
		for opponent in knowledge.opponent_active:
			if opponent.fainted:
				continue
			types = opponent.types.value
			if not isinstance(types, list) or not types:
				continue
			if any(_is_super_effective(move.id, types, mechanics) for move in own.moves):
				count += 1
	return count


def _is_super_effective(move_id: str, types: list[str], mechanics: MechanicsSnapshot) -> bool:
	try:
		move = mechanics.move(move_id)
		return move.base_power > 0 and mechanics.move_multiplier(move, types) > 1
	except (KeyError, ValueError, UnresolvedMechanicError):
		return False


def _spread_cleanup_available(knowledge: KnowledgeState, mechanics: MechanicsSnapshot) -> bool:
	live_opponents = [active for active in knowledge.opponent_active if not active.fainted]
	if len(live_opponents) < 2 or any(active.health.percent > 40 for active in live_opponents):
		return False
	for pokemon in _live_own_actives(knowledge):
		for move in pokemon.moves:
			try:
				move_data = mechanics.move(move.id)
			except KeyError:
				continue
			if move_data.base_power > 0 and move_data.is_spread:
				return True
	return False


def _opponent_fainted_count(knowledge: KnowledgeState) -> int:
	own_names = {to_id(pokemon.name) for pokemon in knowledge.own_team}
	fainted: set[str] = set()
	for event in knowledge.history.events:
		if event.type != "faint":
			continue
		args = event.data.get("args", [])
		if not isinstance(args, list) or not args or not isinstance(args[0], str):
			continue
		name = to_id(args[0].split(":", 1)[-1])
		if name and name not in own_names:
			fainted.add(name)
	return len(fainted)


def _clamp_score(value: float) -> float:
	return max(0.0, min(100.0, round(value, 6)))
