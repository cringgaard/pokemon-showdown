"""B4 runtime win-condition and strategic resource valuation.

This layer is intentionally downstream from baseline threats. Preferred plans
may change how much we value our own resources, but they never change the
mechanical threat facts produced by :mod:`threats`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .config import DEFAULT_HP_UTILITY_CURVE, PolicyConfig, TeamRole, default_config
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
) -> RuntimeStrategyAssessment:
	"""Recompute the continuous B4 plan vector entirely from public state."""
	config = config or default_config()
	config.validate()
	threats = threats or build_threat_model(knowledge, mechanics)
	context = _strategy_context(knowledge, mechanics, threats, config)
	curve = config.strategy.hp_utility_curve
	glaceon = _find_own(knowledge, "glaceon")
	aggron = _find_own(knowledge, "aggron")
	ninetales = _find_own(knowledge, "ninetalesalola")
	maushold = _find_own(knowledge, "maushold")

	glaceon_plan = _score_glaceon(knowledge, threats, context, glaceon, ninetales, config, curve)
	aggron_plan = _score_aggron(knowledge, threats, context, aggron, maushold, config, curve)
	tactical_plan = _score_tactical(knowledge, threats, context, glaceon_plan.score, aggron_plan.score, config)
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
		_resource_values(knowledge, config, scores, context, curve),
		threats,
	)


def hp_utility(
	health_fraction: float,
	curve: tuple[tuple[float, float], ...] = DEFAULT_HP_UTILITY_CURVE,
) -> float:
	"""Piecewise-linear HP utility; any nonzero HP retains meaningful value."""
	if not curve or curve[0][0] != 0 or curve[-1][0] != 1:
		raise ValueError("HP utility curve must span 0..1")
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
	config: PolicyConfig,
	curve: tuple[tuple[float, float], ...],
) -> PlanAssessment:
	if glaceon is None or glaceon.fainted:
		return PlanAssessment(PlanLabel.GLACEON_FORTRESS, 0.0, (), ("Glaceon unavailable",))
	w = config.strategy.weights
	positive: list[str] = []
	negative: list[str] = []
	hp = hp_utility(glaceon.health.percent / 100.0, curve)
	score = w["GLACEON_BASE"] + w["GLACEON_HP"] * hp
	positive.append(f"Glaceon HP utility {hp:.2f}")
	weather = knowledge.field.weather.value
	if isinstance(weather, str) and to_id(weather) == "snow":
		score += w["GLACEON_SNOW"]
		positive.append("snow active")
	if _own_condition_active(knowledge, "auroraveil"):
		score += w["GLACEON_VEIL"]
		positive.append("Aurora Veil active")
	boosts = dict(glaceon.boosts)
	setup = max(0, min(boosts.get("spa", 0), boosts.get("spd", 0)))
	if setup:
		score += min(w["GLACEON_SETUP_CAP"], setup * w["GLACEON_SETUP_PER_STAGE"])
		positive.append(f"Calm Mind-like progress +{setup}")
	if ninetales is not None and not ninetales.fainted and context.weather_contested:
		score += w["GLACEON_WEATHER_RESET"]
		positive.append("Ninetales preserves weather reset")
	if context.glaceon_offensive_matchups:
		score += min(
			w["GLACEON_FAVORABLE_MATCHUP_CAP"],
			context.glaceon_offensive_matchups * w["GLACEON_FAVORABLE_MATCHUP"],
		)
		positive.append(f"{context.glaceon_offensive_matchups} favorable Ice matchup(s)")
	if threats.physical_pressure >= config.thresholds.physical_pressure_preference_fraction:
		score += w["GLACEON_PHYSICAL_PRESSURE"]
		positive.append("opponent pressure is primarily physical")

	if context.no_guard_active:
		score -= w["GLACEON_NO_GUARD_PENALTY"]
		negative.append("active No Guard bypasses evasion plan")
	if context.gravity_active:
		score -= w["GLACEON_GRAVITY_PENALTY"]
		negative.append("Gravity substantially increases opposing accuracy")
	if threats.accuracy_bypass_pressure:
		score -= w["GLACEON_ACCURACY_BYPASS_PENALTY"] * threats.accuracy_bypass_pressure
		negative.append("accuracy/evasion bypass pressure")
	if context.dangerous_glaceon_pressure:
		score -= min(
			w["GLACEON_DANGEROUS_MOVE_PENALTY_CAP"],
			w["GLACEON_DANGEROUS_MOVE_PENALTY"] * context.dangerous_glaceon_pressure,
		)
		negative.append("Fire/Fighting/Rock/Steel pressure remains")
	if (not isinstance(weather, str) or to_id(weather) != "snow") and (ninetales is None or ninetales.fainted):
		score -= w["GLACEON_NO_SNOW_PENALTY"]
		negative.append("snow absent with no Ninetales reset available")
	pressure = _active_pressure_kind(knowledge, threats, glaceon, config.thresholds.heavy_pressure_fraction)
	if pressure == "lethal":
		score -= w["GLACEON_LETHAL_PRESSURE_PENALTY"]
		negative.append("credible incoming line can remove Glaceon")
	elif pressure == "heavy":
		score -= w["GLACEON_HEAVY_PRESSURE_PENALTY"]
		negative.append("heavy immediate pressure on Glaceon")
	return PlanAssessment(PlanLabel.GLACEON_FORTRESS, _clamp_score(score), tuple(positive), tuple(negative))


def _score_aggron(
	knowledge: KnowledgeState,
	threats: ThreatModel,
	context: _Context,
	aggron: OwnPokemonKnowledge | None,
	maushold: OwnPokemonKnowledge | None,
	config: PolicyConfig,
	curve: tuple[tuple[float, float], ...],
) -> PlanAssessment:
	if aggron is None or aggron.fainted:
		return PlanAssessment(PlanLabel.AGGRON_FORTRESS, 0.0, (), ("Aggron unavailable",))
	w = config.strategy.weights
	positive: list[str] = []
	negative: list[str] = []
	hp = hp_utility(aggron.health.percent / 100.0, curve)
	score = w["AGGRON_BASE"] + w["AGGRON_HP"] * hp
	positive.append(f"Aggron HP utility {hp:.2f}")
	if _is_mega(aggron):
		score += w["AGGRON_MEGA"]
		positive.append("Mega Aggron state established")
	defense_boost = max(0, dict(aggron.boosts).get("def", 0))
	if defense_boost:
		score += min(w["AGGRON_DEFENSE_CAP"], defense_boost * w["AGGRON_DEFENSE_PER_STAGE"])
		positive.append(f"Defense boost +{defense_boost}")
	if threats.physical_pressure:
		score += w["AGGRON_PHYSICAL_PRESSURE"] * threats.physical_pressure
		positive.append("physical opponent pressure favors Aggron")
	if context.body_press_target_quality:
		score += w["AGGRON_BODY_PRESS_QUALITY"] * context.body_press_target_quality
		positive.append("useful Body Press targets remain")
	if maushold is not None and not maushold.fainted:
		score += w["AGGRON_MAUSHOLD_SUPPORT"]
		positive.append("Maushold support available")

	if to_id(aggron.status or "") == "brn":
		score -= w["AGGRON_BURN_PENALTY"]
		negative.append("burn damages Body Press endgame quality")
	if context.ghost_fraction:
		score -= w["AGGRON_GHOST_PRESSURE_PENALTY"] * context.ghost_fraction
		negative.append("Ghost-heavy remaining roster")
	if threats.special_pressure:
		score -= w["AGGRON_SPECIAL_PRESSURE_PENALTY"] * threats.special_pressure
		negative.append("special pressure bypasses physical fortress strength")
	if aggron.health.percent / 100.0 <= config.thresholds.low_hp_fraction:
		score -= w["AGGRON_LOW_HP_PENALTY"]
		negative.append("Aggron is at low HP")
	if _active_position(knowledge, aggron.id) is not None and not _is_mega(aggron):
		pressure = _active_pressure_kind(knowledge, threats, aggron, config.thresholds.heavy_pressure_fraction)
		if pressure == "lethal":
			score -= w["AGGRON_BASE_LETHAL_PRESSURE_PENALTY"]
			negative.append("base Aggron faces lethal pre-Mega pressure")
		elif pressure == "heavy":
			score -= w["AGGRON_BASE_HEAVY_PRESSURE_PENALTY"]
			negative.append("base Aggron faces heavy pre-Mega pressure")
	return PlanAssessment(PlanLabel.AGGRON_FORTRESS, _clamp_score(score), tuple(positive), tuple(negative))


def _score_tactical(
	knowledge: KnowledgeState,
	threats: ThreatModel,
	context: _Context,
	glaceon_score: float,
	aggron_score: float,
	config: PolicyConfig,
) -> PlanAssessment:
	w = config.strategy.weights
	positive: list[str] = []
	negative: list[str] = []
	score = w["TACTICAL_BASE"]
	cleanup = sum(
		1 for active in knowledge.opponent_active
		if not active.fainted and active.health.percent / 100.0 <= config.thresholds.cleanup_hp_fraction
	)
	low = sum(
		1 for active in knowledge.opponent_active
		if not active.fainted and active.health.percent / 100.0 <= config.thresholds.low_hp_fraction
	)
	if cleanup:
		score += cleanup * w["TACTICAL_CLEANUP_TARGET"]
		positive.append(f"{cleanup} active opponent(s) in cleanup range")
	if low:
		score += low * w["TACTICAL_LOW_TARGET"]
		positive.append(f"{low} active opponent(s) very low")
	if context.opponent_fainted:
		score += min(
			w["TACTICAL_FAINTED_OPPONENT_CAP"],
			context.opponent_fainted * w["TACTICAL_FAINTED_OPPONENT"],
		)
		positive.append("opponent resources already removed")
	if context.super_effective_pairs:
		score += min(
			w["TACTICAL_SUPER_EFFECTIVE_CAP"],
			context.super_effective_pairs * w["TACTICAL_SUPER_EFFECTIVE_PAIR"],
		)
		positive.append("direct super-effective coverage is available")
	if context.spread_cleanup:
		score += w["TACTICAL_SPREAD_CLEANUP"]
		positive.append("spread cleanup can cash out the position")
	fortress_best = max(glaceon_score, aggron_score)
	if fortress_best < config.thresholds.fortress_weak_score:
		score += min(
			w["TACTICAL_WEAK_FORTRESS_CAP"],
			(config.thresholds.fortress_weak_score - fortress_best) * w["TACTICAL_WEAK_FORTRESS_FACTOR"],
		)
		positive.append("fortress plans are currently weak")
	if any(slot.ko_confidence in (KOConfidence.CERTAIN, KOConfidence.VERY_LIKELY) for slot in threats.slot_threats):
		score += w["TACTICAL_IMMEDIATE_PRESSURE"]
		positive.append("immediate pressure rewards converting the turn")
	if not any(not active.fainted for active in knowledge.opponent_active):
		negative.append("no active opponent pressure to cash out")
	return PlanAssessment(PlanLabel.TACTICAL_OFFENSE, _clamp_score(score), tuple(positive), tuple(negative))


def _strategy_context(
	knowledge: KnowledgeState,
	mechanics: MechanicsSnapshot,
	threats: ThreatModel,
	config: PolicyConfig,
) -> _Context:
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
		if active.fainted:
			continue
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
	saturation = config.thresholds.pressure_saturation_move_count
	spread_fire_count = sum(
		1 for threat in current_threats
		if (threat.spread or to_id(threat.move_type) == "fire")
		and (ThreatCategory.SPREAD_DAMAGE in threat.tags or ThreatCategory.SINGLE_TARGET_DAMAGE in threat.tags)
	)
	water_count = sum(1 for threat in current_threats if to_id(threat.move_type) == "water")
	spread_fire = min(1.0, spread_fire_count / saturation)
	water_pressure = min(1.0, water_count / saturation)
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
		_spread_cleanup_available(knowledge, mechanics, config.thresholds.spread_cleanup_hp_fraction),
	)


def _resource_values(
	knowledge: KnowledgeState,
	config: PolicyConfig,
	scores: RuntimeStrategyScores,
	context: _Context,
	curve: tuple[tuple[float, float], ...],
) -> tuple[ResourceValue, ...]:
	w = config.strategy.weights
	roles = tuple(config.team_roles)
	result: list[ResourceValue] = []
	weather = knowledge.field.weather.value
	for pokemon in knowledge.own_team:
		role = _team_role_for(pokemon, roles)
		base = role.base_resource_value if role is not None else 75.0
		if pokemon.fainted:
			result.append(ResourceValue(pokemon.id, pokemon.species, base, 0.0, 0.0, 0.0, 0.0, ("fainted",)))
			continue
		hp = hp_utility(pokemon.health.percent / 100.0, curve)
		species = to_id(pokemon.species)
		reasons: list[str] = []
		if species == "glaceon":
			role_multiplier = w["GLACEON_ROLE_BASE"] + w["GLACEON_ROLE_PLAN"] * scores.glaceon_fortress / 100.0
			reasons.append("scales with Glaceon fortress viability")
		elif species.startswith("aggron"):
			role_multiplier = w["AGGRON_ROLE_BASE"] + w["AGGRON_ROLE_PLAN"] * scores.aggron_fortress / 100.0
			reasons.append("scales with Aggron fortress viability")
		elif species == "ninetalesalola":
			role_multiplier = w["NINETALES_ROLE_BASE"] + w["NINETALES_ROLE_GLACEON"] * scores.glaceon_fortress / 100.0
			if context.weather_contested:
				role_multiplier += w["NINETALES_WEATHER_WAR"]
				reasons.append("weather war keeps reset value high")
			reasons.append("supports Glaceon fortress")
		elif species == "maushold":
			role_multiplier = w["MAUSHOLD_ROLE_BASE"] + w["MAUSHOLD_ROLE_FORTRESS"] * max(
				scores.glaceon_fortress, scores.aggron_fortress
			) / 100.0
			reasons.append("redirection/Friend Guard supports either fortress")
		elif species == "armarouge":
			role_multiplier = w["ARMAROUGE_ROLE_BASE"] + w["ARMAROUGE_ROLE_FORTRESS"] * max(
				scores.glaceon_fortress, scores.aggron_fortress
			) / 100.0
			role_multiplier += w["ARMAROUGE_SPREAD_PRESSURE"] * context.spread_fire_relevance
			reasons.append("spread/Fire protection relevance")
		elif species == "heliolisk":
			role_multiplier = w["HELIOLISK_ROLE_BASE"] + w["HELIOLISK_TACTICAL"] * scores.tactical_offense / 100.0
			role_multiplier += w["HELIOLISK_WATER_PRESSURE"] * context.water_pressure
			reasons.append("tactical offense and anti-Water pressure")
		else:
			role_multiplier = 1.0
		remaining = 1.0
		if species.startswith("aggron") and to_id(pokemon.status or "") == "brn":
			remaining *= w["AGGRON_BURN_REMAINING"]
			reasons.append("burn reduces remaining endgame utility")
		if species == "glaceon" and (not isinstance(weather, str) or to_id(weather) != "snow"):
			ninetales = _find_own(knowledge, "ninetalesalola")
			if ninetales is None or ninetales.fainted:
				remaining *= w["GLACEON_NO_SNOW_REMAINING"]
				reasons.append("snow cannot currently be restored by Ninetales")
		if to_id(pokemon.status or "") in ("slp", "frz"):
			remaining *= w["MAJOR_STATUS_REMAINING"]
			reasons.append("major status reduces immediate utility")
		role_multiplier = max(w["RESOURCE_ROLE_MIN"], min(w["RESOURCE_ROLE_MAX"], role_multiplier))
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


def _active_pressure_kind(
	knowledge: KnowledgeState,
	threats: ThreatModel,
	pokemon: OwnPokemonKnowledge,
	heavy_fraction: float,
) -> str | None:
	position = _active_position(knowledge, pokemon.id)
	if position is None:
		return None
	slot = next((item for item in threats.slot_threats if item.position == position), None)
	if slot is None or slot.worst_credible_damage is None:
		return None
	current = pokemon.health.percent / 100.0
	if slot.worst_credible_damage >= current:
		return "lethal"
	if slot.worst_credible_damage >= current * heavy_fraction:
		return "heavy"
	return None


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


def _spread_cleanup_available(
	knowledge: KnowledgeState,
	mechanics: MechanicsSnapshot,
	hp_fraction: float,
) -> bool:
	live_opponents = [active for active in knowledge.opponent_active if not active.fainted]
	if len(live_opponents) < 2 or any(active.health.percent / 100.0 > hp_fraction for active in live_opponents):
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
