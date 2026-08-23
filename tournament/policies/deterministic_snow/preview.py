"""B5 Open-Team-Sheets Team Preview policy for the deterministic snow team.

This module deliberately supports the tournament's OTS path only. It consumes
all six submitted opponent sets from public KnowledgeState, profiles those sets
from actual moves/items/abilities plus B2 mechanics, retains several plausible
opponent lead pairs, and scores every ordered Bring-4 action already supplied by
``request.legal_actions``.

It does not infer missing non-OTS moves, generate hidden team choices, predict
turn actions, or implement ``choose_action``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import combinations
import math
from typing import Iterable, Mapping

from .actions import CanonicalLegalAction
from .knowledge import KnowledgeSource, OpponentRosterKnowledge, OwnPokemonKnowledge
from .mechanics import MechanicsSnapshot, UnresolvedMechanicError, to_id
from .reconstruction import KnowledgeState
from .strategy import PlanLabel


class PreviewContractError(ValueError):
	"""Raised when B5 is asked to reason outside its OTS Team Preview contract."""


class OpponentTag(str, Enum):
	PHYSICAL_PRESSURE = "PHYSICAL_PRESSURE"
	SPECIAL_PRESSURE = "SPECIAL_PRESSURE"
	FIGHTING_PRESSURE = "FIGHTING_PRESSURE"
	FIRE_PRESSURE = "FIRE_PRESSURE"
	ROCK_PRESSURE = "ROCK_PRESSURE"
	GROUND_PRESSURE = "GROUND_PRESSURE"
	WATER_PRESSURE = "WATER_PRESSURE"
	ELECTRIC_PRESSURE = "ELECTRIC_PRESSURE"
	ICE_PRESSURE = "ICE_PRESSURE"
	SPREAD_DAMAGE = "SPREAD_DAMAGE"
	SPREAD_FIRE = "SPREAD_FIRE"
	SPREAD_WATER = "SPREAD_WATER"
	WEATHER_SETTER = "WEATHER_SETTER"
	WEATHER_ABUSER = "WEATHER_ABUSER"
	FAKE_OUT = "FAKE_OUT"
	REDIRECTION = "REDIRECTION"
	SPEED_CONTROL = "SPEED_CONTROL"
	SETUP_SWEEPER = "SETUP_SWEEPER"
	STATUS_CONTROL = "STATUS_CONTROL"
	BURN_PRESSURE = "BURN_PRESSURE"
	GHOST = "GHOST"
	BODY_PRESS_IMMUNE = "BODY_PRESS_IMMUNE"
	STAT_DROP_PUNISHER = "STAT_DROP_PUNISHER"
	NO_GUARD = "NO_GUARD"
	ACCURACY_BYPASS = "ACCURACY_BYPASS"
	GRAVITY = "GRAVITY"
	LIGHTNING_ROD = "LIGHTNING_ROD"
	FLASH_FIRE = "FLASH_FIRE"
	WATER_IMMUNITY = "WATER_IMMUNITY"


PREVIEW_WEIGHT_IDS = frozenset({
	"LEAD_HYPOTHESIS_BASE",
	"LEAD_HYPOTHESIS_FAKE_OUT_SETUP",
	"LEAD_HYPOTHESIS_SPEED_ATTACKER",
	"LEAD_HYPOTHESIS_WEATHER_SYNERGY",
	"LEAD_HYPOTHESIS_REDIRECTION_SETUP",
	"LEAD_HYPOTHESIS_SPREAD_SUPPORT",
	"LEAD_HYPOTHESIS_COMPLEMENTARY_PRESSURE",
	"LEAD_HYPOTHESIS_PASSIVE_PAIR_PENALTY",
	"LEAD_DIVERSITY_NEW_MEMBER",
	"GLACEON_SELECTED",
	"GLACEON_NINETALES",
	"GLACEON_MAUSHOLD",
	"GLACEON_ARMAROUGE_SPREAD_FIRE",
	"GLACEON_PHYSICAL_FRACTION",
	"GLACEON_ICE_MATCHUP",
	"GLACEON_ICE_MATCHUP_CAP",
	"GLACEON_NO_GUARD_PENALTY",
	"GLACEON_ACCURACY_BYPASS_PENALTY",
	"GLACEON_GRAVITY_PENALTY",
	"GLACEON_WEATHER_SETTER_PENALTY",
	"GLACEON_WEATHER_SETTER_PENALTY_CAP",
	"GLACEON_DANGEROUS_PRESSURE_PENALTY",
	"GLACEON_DANGEROUS_PRESSURE_PENALTY_CAP",
	"GLACEON_NO_NINETALES_WEATHER_PENALTY",
	"AGGRON_SELECTED",
	"AGGRON_MAUSHOLD",
	"AGGRON_PHYSICAL_FRACTION",
	"AGGRON_BODY_PRESS_QUALITY",
	"AGGRON_GHOST_PENALTY",
	"AGGRON_SPECIAL_FRACTION_PENALTY",
	"AGGRON_BURN_PRESSURE_PENALTY",
	"AGGRON_LEAD_MEGA_SAFETY",
	"AGGRON_BACKLINE_DANGER_PENALTY",
	"TACTICAL_BASE",
	"TACTICAL_ATTACKER_SELECTED",
	"TACTICAL_COVERAGE_FACTOR",
	"TACTICAL_SUPER_EFFECTIVE_PAIR",
	"TACTICAL_SUPER_EFFECTIVE_CAP",
	"TACTICAL_WEAK_FORTRESS_FACTOR",
	"TACTICAL_WEAK_FORTRESS_CAP",
	"COVERAGE_IMPORTANCE_BASE",
	"COVERAGE_IMPORTANCE_SETUP",
	"COVERAGE_IMPORTANCE_WEATHER",
	"COVERAGE_IMPORTANCE_NO_GUARD",
	"COVERAGE_IMPORTANCE_SPREAD",
	"COVERAGE_IMPORTANCE_SPEED_CONTROL",
	"COVERAGE_IMPORTANCE_FAKE_OUT",
	"COVERAGE_OFFENSIVE_ANSWER",
	"COVERAGE_DEFENSIVE_ANSWER",
	"COVERAGE_SPECIALIST_ANSWER",
	"STRUCTURAL_UNANSWERED_MAJOR",
	"STRUCTURAL_NO_FORTRESS",
	"LEAD_BASE",
	"LEAD_IMMEDIATE_PRESSURE",
	"LEAD_SUPER_EFFECTIVE_DANGER_PENALTY",
	"LEAD_NINETALES_GLACEON",
	"LEAD_MAUSHOLD_FORTRESS",
	"LEAD_ARMAROUGE_SPREAD",
	"LEAD_HELIOLISK_WATER",
	"LEAD_FAKE_OUT_SUPPORT_PENALTY",
	"LEAD_NINETALES_WEATHER_CONFLICT_PENALTY",
	"LEAD_AGGRON_MEGA_SAFETY",
	"LEAD_GLACEON_DANGEROUS_PENALTY",
	"LEAD_GLACEON_NO_GUARD_PENALTY",
	"BACKLINE_BASE",
	"BACKLINE_NINETALES_WEATHER_WAR",
	"BACKLINE_GLACEON_SHELTER",
	"BACKLINE_AGGRON_DANGER_PENALTY",
	"BACKLINE_ARMAROUGE_LATE_SPREAD_PENALTY",
	"BACKLINE_HELIOLISK_WATER",
	"SYNERGY_NINETALES_GLACEON",
	"SYNERGY_MAUSHOLD_GLACEON",
	"SYNERGY_MAUSHOLD_AGGRON",
	"SYNERGY_ARMAROUGE_GLACEON",
	"SYNERGY_ARMAROUGE_MAUSHOLD",
	"SYNERGY_HELIOLISK_NINETALES",
	"SPECIALIST_ARMAROUGE_SPREAD_FIRE",
	"SPECIALIST_HELIOLISK_WATER",
})


@dataclass(frozen=True)
class PreviewConfig:
	version: str
	max_lead_hypotheses: int
	lead_expected_weight: float
	lead_bad_case_weight: float
	lead_component_weight: float
	primary_plan_component_weight: float
	secondary_plan_component_weight: float
	coverage_component_weight: float
	backline_component_weight: float
	synergy_component_weight: float
	major_threat_importance_threshold: float
	fortress_weak_score: float
	tactical_no_fortress_threshold: float
	synergy_cap: float
	weights: Mapping[str, float]

	def validate(self) -> None:
		if not self.version:
			raise ValueError("preview version must be non-empty")
		if not 1 <= self.max_lead_hypotheses <= 15:
			raise ValueError("max_lead_hypotheses must be between 1 and 15")
		for name in ("lead_expected_weight", "lead_bad_case_weight"):
			value = getattr(self, name)
			if not 0 <= value <= 1:
				raise ValueError(f"{name} must be between 0 and 1")
		if not math.isclose(self.lead_expected_weight + self.lead_bad_case_weight, 1.0, abs_tol=1e-9):
			raise ValueError("lead aggregation weights must sum to 1")
		components = (
			self.lead_component_weight,
			self.primary_plan_component_weight,
			self.secondary_plan_component_weight,
			self.coverage_component_weight,
			self.backline_component_weight,
			self.synergy_component_weight,
		)
		if any(value < 0 for value in components) or not math.isclose(sum(components), 1.0, abs_tol=1e-9):
			raise ValueError("preview component weights must be non-negative and sum to 1")
		if self.major_threat_importance_threshold <= 0 or not 0 <= self.fortress_weak_score <= 100:
			raise ValueError("preview thresholds are invalid")
		if not 0 <= self.tactical_no_fortress_threshold <= 100 or self.synergy_cap <= 0:
			raise ValueError("preview tactical/synergy thresholds are invalid")
		missing = PREVIEW_WEIGHT_IDS - set(self.weights)
		unknown = set(self.weights) - PREVIEW_WEIGHT_IDS
		if missing or unknown:
			raise ValueError(f"preview weight IDs invalid; missing={sorted(missing)}, unknown={sorted(unknown)}")
		for key, value in self.weights.items():
			if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
				raise ValueError(f"preview.weights.{key} must be a finite number")


def default_preview_config() -> PreviewConfig:
	weights = {
		"LEAD_HYPOTHESIS_BASE": 10.0,
		"LEAD_HYPOTHESIS_FAKE_OUT_SETUP": 18.0,
		"LEAD_HYPOTHESIS_SPEED_ATTACKER": 15.0,
		"LEAD_HYPOTHESIS_WEATHER_SYNERGY": 14.0,
		"LEAD_HYPOTHESIS_REDIRECTION_SETUP": 16.0,
		"LEAD_HYPOTHESIS_SPREAD_SUPPORT": 12.0,
		"LEAD_HYPOTHESIS_COMPLEMENTARY_PRESSURE": 8.0,
		"LEAD_HYPOTHESIS_PASSIVE_PAIR_PENALTY": 10.0,
		"LEAD_DIVERSITY_NEW_MEMBER": 2.0,
		"GLACEON_SELECTED": 30.0,
		"GLACEON_NINETALES": 20.0,
		"GLACEON_MAUSHOLD": 10.0,
		"GLACEON_ARMAROUGE_SPREAD_FIRE": 8.0,
		"GLACEON_PHYSICAL_FRACTION": 15.0,
		"GLACEON_ICE_MATCHUP": 5.0,
		"GLACEON_ICE_MATCHUP_CAP": 15.0,
		"GLACEON_NO_GUARD_PENALTY": 20.0,
		"GLACEON_ACCURACY_BYPASS_PENALTY": 10.0,
		"GLACEON_GRAVITY_PENALTY": 12.0,
		"GLACEON_WEATHER_SETTER_PENALTY": 6.0,
		"GLACEON_WEATHER_SETTER_PENALTY_CAP": 18.0,
		"GLACEON_DANGEROUS_PRESSURE_PENALTY": 4.0,
		"GLACEON_DANGEROUS_PRESSURE_PENALTY_CAP": 20.0,
		"GLACEON_NO_NINETALES_WEATHER_PENALTY": 12.0,
		"AGGRON_SELECTED": 30.0,
		"AGGRON_MAUSHOLD": 15.0,
		"AGGRON_PHYSICAL_FRACTION": 20.0,
		"AGGRON_BODY_PRESS_QUALITY": 20.0,
		"AGGRON_GHOST_PENALTY": 22.0,
		"AGGRON_SPECIAL_FRACTION_PENALTY": 18.0,
		"AGGRON_BURN_PRESSURE_PENALTY": 12.0,
		"AGGRON_LEAD_MEGA_SAFETY": 10.0,
		"AGGRON_BACKLINE_DANGER_PENALTY": 10.0,
		"TACTICAL_BASE": 10.0,
		"TACTICAL_ATTACKER_SELECTED": 7.0,
		"TACTICAL_COVERAGE_FACTOR": 0.35,
		"TACTICAL_SUPER_EFFECTIVE_PAIR": 3.0,
		"TACTICAL_SUPER_EFFECTIVE_CAP": 18.0,
		"TACTICAL_WEAK_FORTRESS_FACTOR": 0.30,
		"TACTICAL_WEAK_FORTRESS_CAP": 15.0,
		"COVERAGE_IMPORTANCE_BASE": 1.0,
		"COVERAGE_IMPORTANCE_SETUP": 0.45,
		"COVERAGE_IMPORTANCE_WEATHER": 0.45,
		"COVERAGE_IMPORTANCE_NO_GUARD": 0.50,
		"COVERAGE_IMPORTANCE_SPREAD": 0.30,
		"COVERAGE_IMPORTANCE_SPEED_CONTROL": 0.20,
		"COVERAGE_IMPORTANCE_FAKE_OUT": 0.15,
		"COVERAGE_OFFENSIVE_ANSWER": 1.0,
		"COVERAGE_DEFENSIVE_ANSWER": 0.80,
		"COVERAGE_SPECIALIST_ANSWER": 0.70,
		"STRUCTURAL_UNANSWERED_MAJOR": 12.0,
		"STRUCTURAL_NO_FORTRESS": 25.0,
		"LEAD_BASE": 50.0,
		"LEAD_IMMEDIATE_PRESSURE": 8.0,
		"LEAD_SUPER_EFFECTIVE_DANGER_PENALTY": 9.0,
		"LEAD_NINETALES_GLACEON": 12.0,
		"LEAD_MAUSHOLD_FORTRESS": 10.0,
		"LEAD_ARMAROUGE_SPREAD": 14.0,
		"LEAD_HELIOLISK_WATER": 12.0,
		"LEAD_FAKE_OUT_SUPPORT_PENALTY": 12.0,
		"LEAD_NINETALES_WEATHER_CONFLICT_PENALTY": 10.0,
		"LEAD_AGGRON_MEGA_SAFETY": 10.0,
		"LEAD_GLACEON_DANGEROUS_PENALTY": 6.0,
		"LEAD_GLACEON_NO_GUARD_PENALTY": 16.0,
		"BACKLINE_BASE": 50.0,
		"BACKLINE_NINETALES_WEATHER_WAR": 18.0,
		"BACKLINE_GLACEON_SHELTER": 10.0,
		"BACKLINE_AGGRON_DANGER_PENALTY": 12.0,
		"BACKLINE_ARMAROUGE_LATE_SPREAD_PENALTY": 10.0,
		"BACKLINE_HELIOLISK_WATER": 8.0,
		"SYNERGY_NINETALES_GLACEON": 25.0,
		"SYNERGY_MAUSHOLD_GLACEON": 15.0,
		"SYNERGY_MAUSHOLD_AGGRON": 20.0,
		"SYNERGY_ARMAROUGE_GLACEON": 10.0,
		"SYNERGY_ARMAROUGE_MAUSHOLD": 8.0,
		"SYNERGY_HELIOLISK_NINETALES": 8.0,
		"SPECIALIST_ARMAROUGE_SPREAD_FIRE": 15.0,
		"SPECIALIST_HELIOLISK_WATER": 15.0,
	}
	config = PreviewConfig(
		version="b5-ots-preview-v1",
		max_lead_hypotheses=8,
		lead_expected_weight=0.70,
		lead_bad_case_weight=0.30,
		lead_component_weight=0.30,
		primary_plan_component_weight=0.25,
		secondary_plan_component_weight=0.10,
		coverage_component_weight=0.15,
		backline_component_weight=0.10,
		synergy_component_weight=0.10,
		major_threat_importance_threshold=1.60,
		fortress_weak_score=55.0,
		tactical_no_fortress_threshold=65.0,
		synergy_cap=100.0,
		weights=weights,
	)
	config.validate()
	return config


@dataclass(frozen=True)
class OpponentPokemonProfile:
	pokemon_id: str
	species: str
	item: str | None
	ability: str | None
	transformed_species: str | None
	transformed_ability: str | None
	base_types: tuple[str, ...]
	transformed_types: tuple[str, ...]
	moves: tuple[str, ...]
	tags: tuple[OpponentTag, ...]
	pressure_types: tuple[str, ...]
	weather_ids: tuple[str, ...]
	weather_synergy_ids: tuple[str, ...]
	physical_moves: int
	special_moves: int

	@property
	def possible_type_sets(self) -> tuple[tuple[str, ...], ...]:
		if self.transformed_types and self.transformed_types != self.base_types:
			return (self.base_types, self.transformed_types)
		return (self.base_types,)


@dataclass(frozen=True)
class OpponentRosterProfile:
	pokemon: tuple[OpponentPokemonProfile, ...]
	physical_pressure_fraction: float
	special_pressure_fraction: float
	weather_setter_count: int
	no_guard_count: int
	accuracy_bypass_count: int
	spread_fire_count: int
	water_pressure_count: int


@dataclass(frozen=True)
class OpponentLeadHypothesis:
	members: tuple[str, str]
	raw_score: float
	weight: float
	reasons: tuple[str, ...]


@dataclass(frozen=True)
class PreviewPlanScores:
	glaceon_fortress: float
	aggron_fortress: float
	tactical_offense: float
	primary: PlanLabel
	secondary: PlanLabel


@dataclass(frozen=True)
class CoverageAssessment:
	score: float
	structural_penalty: float
	unanswered_major: tuple[str, ...]


@dataclass(frozen=True)
class PreviewCandidateScore:
	action: CanonicalLegalAction
	team: tuple[str, str, str, str]
	lead: tuple[str, str]
	backline: tuple[str, str]
	plans: PreviewPlanScores
	lead_robustness: float
	coverage: float
	backline_quality: float
	synergy: float
	structural_penalty: float
	final_score: float


@dataclass(frozen=True)
class TeamPreviewAssessment:
	config_version: str
	roster: OpponentRosterProfile
	lead_hypotheses: tuple[OpponentLeadHypothesis, ...]
	candidates: tuple[PreviewCandidateScore, ...]
	selected_action_id: str

	@property
	def selected(self) -> PreviewCandidateScore:
		return next(candidate for candidate in self.candidates if candidate.action.action_id == self.selected_action_id)


def assess_team_preview(
	knowledge: KnowledgeState,
	mechanics: MechanicsSnapshot,
	*,
	config: PreviewConfig | None = None,
) -> TeamPreviewAssessment:
	"""Score every harness-supplied ordered Bring-4 action under OTS."""
	config = config or default_preview_config()
	config.validate()
	_require_ots_preview(knowledge)
	if hasattr(mechanics, "require_champions_format"):
		mechanics.require_champions_format()
	roster = build_opponent_roster_profile(knowledge, mechanics)
	hypotheses = generate_opponent_lead_hypotheses(roster, mechanics, config=config)
	own_by_id = {pokemon.id: pokemon for pokemon in knowledge.own_team}
	candidates: list[PreviewCandidateScore] = []
	seen_actions: set[str] = set()
	for action in knowledge.legal_actions:
		payload = action.payload
		team_value = payload.get("team")
		if payload.get("kind") != "team_preview" or not isinstance(team_value, list) or len(team_value) != 4:
			raise PreviewContractError("B5 requires complete ordered pick-4 Team Preview legal actions")
		team = tuple(str(pokemon_id) for pokemon_id in team_value)
		if len(set(team)) != 4 or any(pokemon_id not in own_by_id for pokemon_id in team):
			raise PreviewContractError("Team Preview action references an invalid own team selection")
		if action.action_id in seen_actions:
			raise PreviewContractError("Team Preview legal action was evaluated more than once")
		seen_actions.add(action.action_id)
		candidates.append(_score_candidate(action, team, own_by_id, roster, hypotheses, mechanics, config))
	if len(candidates) != len(knowledge.legal_actions):
		raise PreviewContractError("Every legal Team Preview action must be evaluated exactly once")
	ordered = tuple(sorted(candidates, key=lambda item: (-item.final_score, item.action.canonical_key)))
	if not ordered:
		raise PreviewContractError("No legal Team Preview actions were supplied")
	return TeamPreviewAssessment(config.version, roster, hypotheses, ordered, ordered[0].action.action_id)


def build_opponent_roster_profile(
	knowledge: KnowledgeState, mechanics: MechanicsSnapshot
) -> OpponentRosterProfile:
	_require_ots_roster(knowledge)
	profiles = tuple(_profile_opponent(pokemon, mechanics) for pokemon in knowledge.opponent_roster)
	physical = sum(profile.physical_moves for profile in profiles)
	special = sum(profile.special_moves for profile in profiles)
	damaging = physical + special
	return OpponentRosterProfile(
		pokemon=profiles,
		physical_pressure_fraction=physical / damaging if damaging else 0.0,
		special_pressure_fraction=special / damaging if damaging else 0.0,
		weather_setter_count=sum(OpponentTag.WEATHER_SETTER in profile.tags for profile in profiles),
		no_guard_count=sum(OpponentTag.NO_GUARD in profile.tags for profile in profiles),
		accuracy_bypass_count=sum(OpponentTag.ACCURACY_BYPASS in profile.tags for profile in profiles),
		spread_fire_count=sum(OpponentTag.SPREAD_FIRE in profile.tags for profile in profiles),
		water_pressure_count=sum(OpponentTag.WATER_PRESSURE in profile.tags for profile in profiles),
	)


def generate_opponent_lead_hypotheses(
	roster: OpponentRosterProfile,
	mechanics: MechanicsSnapshot,
	*,
	config: PreviewConfig | None = None,
) -> tuple[OpponentLeadHypothesis, ...]:
	config = config or default_preview_config()
	profiles = {profile.pokemon_id: profile for profile in roster.pokemon}
	pair_values: list[tuple[tuple[str, str], float, tuple[str, ...]]] = []
	for left, right in combinations(roster.pokemon, 2):
		score, reasons = _lead_hypothesis_score(left, right, mechanics, config)
		pair_values.append(((left.pokemon_id, right.pokemon_id), score, reasons))
	pair_values.sort(key=lambda item: (-item[1], item[0]))
	selected: list[tuple[tuple[str, str], float, tuple[str, ...]]] = []
	seen_members: set[str] = set()
	remaining = list(pair_values)
	while remaining and len(selected) < config.max_lead_hypotheses:
		best = max(
			remaining,
			key=lambda item: (
				item[1] + config.weights["LEAD_DIVERSITY_NEW_MEMBER"] * sum(member not in seen_members for member in item[0]),
				-item[0].__hash__(),
			),
		)
		# max() tie-breaking on tuple hashes is not stable across Python processes;
		# replace any score tie with canonical lexical selection below.
		best_adjusted = best[1] + config.weights["LEAD_DIVERSITY_NEW_MEMBER"] * sum(
			member not in seen_members for member in best[0]
		)
		tied = [
			item for item in remaining
			if math.isclose(
				item[1] + config.weights["LEAD_DIVERSITY_NEW_MEMBER"] * sum(member not in seen_members for member in item[0]),
				best_adjusted,
				abs_tol=1e-12,
			)
		]
		best = min(tied, key=lambda item: item[0])
		selected.append(best)
		seen_members.update(best[0])
		remaining.remove(best)
	total = sum(max(1.0, item[1]) for item in selected) or 1.0
	return tuple(
		OpponentLeadHypothesis(members, score, max(1.0, score) / total, reasons)
		for members, score, reasons in selected
	)


def _require_ots_preview(knowledge: KnowledgeState) -> None:
	if knowledge.phase != "team_preview":
		raise PreviewContractError(f"B5 preview only supports team_preview phase, got {knowledge.phase!r}")
	_require_ots_roster(knowledge)
	if len(knowledge.own_team) != 6:
		raise PreviewContractError("B5 target format requires six own submitted Pokemon")
	if len(knowledge.legal_actions) != 360:
		raise PreviewContractError(
			f"B5 target format requires all 360 ordered Bring-4 actions, got {len(knowledge.legal_actions)}"
		)
	if any(action.payload.get("kind") != "team_preview" for action in knowledge.legal_actions):
		raise PreviewContractError("B5 received non-preview legal actions during Team Preview")


def _require_ots_roster(knowledge: KnowledgeState) -> None:
	if len(knowledge.opponent_roster) != 6:
		raise PreviewContractError("B5 OTS preview requires all six opponent roster entries")
	for pokemon in knowledge.opponent_roster:
		if pokemon.source is not KnowledgeSource.OPEN_TEAM_SHEET:
			raise PreviewContractError(f"Opponent {pokemon.id} is not OTS-backed")
		if pokemon.ability is None:
			raise PreviewContractError(f"Opponent {pokemon.id} has no OTS ability")
		if not pokemon.moves:
			raise PreviewContractError(f"Opponent {pokemon.id} has no OTS moves")
		for move in pokemon.moves:
			if KnowledgeSource.OPEN_TEAM_SHEET not in move.sources:
				raise PreviewContractError(
					f"Opponent {pokemon.id} move {move.id} is observed-only; non-OTS preview is out of scope"
				)


def _profile_opponent(pokemon: OpponentRosterKnowledge, mechanics: MechanicsSnapshot) -> OpponentPokemonProfile:
	base = mechanics.species(pokemon.species)
	transformed = None
	if pokemon.item:
		try:
			transformed = mechanics.form_after_item_transformation(pokemon.species, pokemon.item)
		except (KeyError, ValueError):
			transformed = None
	transformed_ability = _fixed_species_ability(transformed) if transformed is not None else None
	abilities = tuple(value for value in (pokemon.ability, transformed_ability) if value)
	tags: set[OpponentTag] = set()
	pressure_types: set[str] = set()
	weather_ids: set[str] = set()
	weather_synergy_ids: set[str] = set()
	physical = 0
	special = 0

	for ability in abilities:
		semantics = _safe_semantic(mechanics, "abilities", ability)
		if semantics.get("entry_weather"):
			tags.add(OpponentTag.WEATHER_SETTER)
			weather_ids.add(to_id(str(semantics["entry_weather"])))
		if semantics.get("accuracy_bypass") is True:
			tags.update((OpponentTag.NO_GUARD, OpponentTag.ACCURACY_BYPASS))
		if semantics.get("electric_redirection") is True:
			tags.add(OpponentTag.LIGHTNING_ROD)
		if semantics.get("fire_immunity") is True:
			tags.add(OpponentTag.FLASH_FIRE)
		if "water_immunity_and_heal_fraction" in semantics:
			tags.add(OpponentTag.WATER_IMMUNITY)
		if any(key in semantics for key in (
			"attack_boost_on_opponent_stat_drop", "spa_boost_on_opponent_stat_drop", "invert_stat_changes",
		)):
			tags.add(OpponentTag.STAT_DROP_PUNISHER)

	possible_types = [tuple(base.types)]
	if transformed is not None:
		possible_types.append(tuple(transformed.types))
	if any(any(to_id(type_name) == "ghost" for type_name in types) for types in possible_types):
		tags.update((OpponentTag.GHOST, OpponentTag.BODY_PRESS_IMMUNE))

	for known_move in pokemon.moves:
		move = mechanics.move(known_move.id)
		if move.base_power > 0:
			pressure_types.add(move.type)
			if move.category == "Physical":
				physical += 1
				tags.add(OpponentTag.PHYSICAL_PRESSURE)
			elif move.category == "Special":
				special += 1
				tags.add(OpponentTag.SPECIAL_PRESSURE)
			if move.is_spread:
				tags.add(OpponentTag.SPREAD_DAMAGE)
				if to_id(move.type) == "fire":
					tags.add(OpponentTag.SPREAD_FIRE)
				if to_id(move.type) == "water":
					tags.add(OpponentTag.SPREAD_WATER)
		_type_pressure_tags(tags, move.type)
		if move.id == "fakeout":
			tags.add(OpponentTag.FAKE_OUT)
		if move.id in ("followme", "ragepowder", "spotlight") or _safe_semantic(
			mechanics, "moves", move.id
		).get("single_target_redirection") is True:
			tags.add(OpponentTag.REDIRECTION)
		boosts = dict(move.boosts)
		self_boosts = dict(move.self_boosts)
		if boosts.get("spe", 0) < 0 or move.id in ("tailwind", "trickroom", "electroweb", "icywind"):
			tags.add(OpponentTag.SPEED_CONTROL)
		if any(self_boosts.get(stat, 0) > 0 for stat in ("atk", "spa", "spe", "def", "spd")):
			tags.add(OpponentTag.SETUP_SWEEPER)
		if move.status or move.volatile_status:
			tags.add(OpponentTag.STATUS_CONTROL)
		if to_id(move.status or "") == "brn" or move.id == "willowisp":
			tags.add(OpponentTag.BURN_PRESSURE)
		if move.id == "gravity":
			tags.add(OpponentTag.GRAVITY)
		if move.weather:
			tags.add(OpponentTag.WEATHER_SETTER)
			weather_ids.add(to_id(move.weather))
		if move.ignore_accuracy or move.ignore_evasion:
			tags.add(OpponentTag.ACCURACY_BYPASS)
		accuracy_by_weather = _safe_semantic(mechanics, "moves", move.id).get("accuracy_by_weather")
		if isinstance(accuracy_by_weather, Mapping):
			for weather, value in accuracy_by_weather.items():
				if value is True:
					weather_synergy_ids.add(to_id(str(weather)))
	if weather_synergy_ids:
		tags.add(OpponentTag.WEATHER_ABUSER)
	return OpponentPokemonProfile(
		pokemon.id,
		pokemon.species,
		pokemon.item,
		pokemon.ability,
		transformed.name if transformed is not None else None,
		transformed_ability,
		tuple(base.types),
		tuple(transformed.types) if transformed is not None else (),
		tuple(move.id for move in pokemon.moves),
		tuple(sorted(tags, key=lambda tag: tag.value)),
		tuple(sorted(pressure_types)),
		tuple(sorted(weather_ids)),
		tuple(sorted(weather_synergy_ids)),
		physical,
		special,
	)


def _fixed_species_ability(species: object | None) -> str | None:
	if species is None:
		return None
	abilities = getattr(species, "abilities", ())
	values = {value for _, value in abilities}
	return next(iter(values)) if len(values) == 1 else None


def _safe_semantic(mechanics: MechanicsSnapshot, category: str, value: str) -> dict[str, object]:
	try:
		return mechanics.semantic(category, value)
	except (KeyError, ValueError):
		return {}


def _type_pressure_tags(tags: set[OpponentTag], move_type: str) -> None:
	mapping = {
		"fighting": OpponentTag.FIGHTING_PRESSURE,
		"fire": OpponentTag.FIRE_PRESSURE,
		"rock": OpponentTag.ROCK_PRESSURE,
		"ground": OpponentTag.GROUND_PRESSURE,
		"water": OpponentTag.WATER_PRESSURE,
		"electric": OpponentTag.ELECTRIC_PRESSURE,
		"ice": OpponentTag.ICE_PRESSURE,
	}
	tag = mapping.get(to_id(move_type))
	if tag is not None:
		tags.add(tag)


def _lead_hypothesis_score(
	left: OpponentPokemonProfile,
	right: OpponentPokemonProfile,
	mechanics: MechanicsSnapshot,
	config: PreviewConfig,
) -> tuple[float, tuple[str, ...]]:
	weights = config.weights
	score = weights["LEAD_HYPOTHESIS_BASE"]
	reasons: list[str] = []
	left_tags, right_tags = set(left.tags), set(right.tags)
	if (OpponentTag.FAKE_OUT in left_tags and OpponentTag.SETUP_SWEEPER in right_tags) or (
		OpponentTag.FAKE_OUT in right_tags and OpponentTag.SETUP_SWEEPER in left_tags
	):
		score += weights["LEAD_HYPOTHESIS_FAKE_OUT_SETUP"]
		reasons.append("Fake Out + setup")
	if (OpponentTag.SPEED_CONTROL in left_tags and _is_attacker(right)) or (
		OpponentTag.SPEED_CONTROL in right_tags and _is_attacker(left)
	):
		score += weights["LEAD_HYPOTHESIS_SPEED_ATTACKER"]
		reasons.append("speed control + attacker")
	if _weather_pair_synergy(left, right) or _weather_pair_synergy(right, left):
		score += weights["LEAD_HYPOTHESIS_WEATHER_SYNERGY"]
		reasons.append("weather setter + set-supported pressure")
	if (OpponentTag.REDIRECTION in left_tags and OpponentTag.SETUP_SWEEPER in right_tags) or (
		OpponentTag.REDIRECTION in right_tags and OpponentTag.SETUP_SWEEPER in left_tags
	):
		score += weights["LEAD_HYPOTHESIS_REDIRECTION_SETUP"]
		reasons.append("redirection + setup")
	if (OpponentTag.SPREAD_DAMAGE in left_tags and _is_support(right)) or (
		OpponentTag.SPREAD_DAMAGE in right_tags and _is_support(left)
	):
		score += weights["LEAD_HYPOTHESIS_SPREAD_SUPPORT"]
		reasons.append("spread pressure + support")
	if _complementary_pressure(left, right):
		score += weights["LEAD_HYPOTHESIS_COMPLEMENTARY_PRESSURE"]
		reasons.append("complementary offensive pressure")
	if not _is_attacker(left) and not _is_attacker(right):
		score -= weights["LEAD_HYPOTHESIS_PASSIVE_PAIR_PENALTY"]
		reasons.append("double passive lead penalty")
	return max(1.0, score), tuple(reasons)


def _weather_pair_synergy(setter: OpponentPokemonProfile, partner: OpponentPokemonProfile) -> bool:
	if OpponentTag.WEATHER_SETTER not in setter.tags:
		return False
	for weather in setter.weather_ids:
		if weather in partner.weather_synergy_ids:
			return True
		if weather in ("raindance", "rain") and OpponentTag.WATER_PRESSURE in partner.tags:
			return True
		if weather in ("sunnyday", "sun") and OpponentTag.FIRE_PRESSURE in partner.tags:
			return True
	return False


def _is_attacker(profile: OpponentPokemonProfile) -> bool:
	return profile.physical_moves + profile.special_moves > 0


def _is_support(profile: OpponentPokemonProfile) -> bool:
	tags = set(profile.tags)
	return bool(tags & {
		OpponentTag.FAKE_OUT,
		OpponentTag.REDIRECTION,
		OpponentTag.SPEED_CONTROL,
		OpponentTag.WEATHER_SETTER,
		OpponentTag.STATUS_CONTROL,
	})


def _complementary_pressure(left: OpponentPokemonProfile, right: OpponentPokemonProfile) -> bool:
	left_types = set(left.pressure_types)
	right_types = set(right.pressure_types)
	return bool(left_types and right_types and left_types != right_types and len(left_types | right_types) >= 2)


def _score_candidate(
	action: CanonicalLegalAction,
	team: tuple[str, str, str, str],
	own_by_id: Mapping[str, OwnPokemonKnowledge],
	roster: OpponentRosterProfile,
	hypotheses: tuple[OpponentLeadHypothesis, ...],
	mechanics: MechanicsSnapshot,
	config: PreviewConfig,
) -> PreviewCandidateScore:
	selected = tuple(own_by_id[pokemon_id] for pokemon_id in team)
	lead = selected[:2]
	backline = selected[2:]
	coverage = _coverage_assessment(selected, roster, mechanics, config)
	plans = _preview_plan_scores(selected, lead, roster, coverage.score, mechanics, config)
	lead_score = _lead_robustness(lead, hypotheses, roster, mechanics, config)
	backline_score = _backline_quality(backline, roster, config)
	synergy = _synergy_score(selected, roster, config)
	structural = coverage.structural_penalty
	selected_species = {to_id(pokemon.species) for pokemon in selected}
	if not ({"glaceon", "aggron"} & selected_species) and plans.tactical_offense < config.tactical_no_fortress_threshold:
		structural += config.weights["STRUCTURAL_NO_FORTRESS"]
	primary = _plan_value(plans, plans.primary)
	secondary = _plan_value(plans, plans.secondary)
	final = (
		config.lead_component_weight * lead_score +
		config.primary_plan_component_weight * primary +
		config.secondary_plan_component_weight * secondary +
		config.coverage_component_weight * coverage.score +
		config.backline_component_weight * backline_score +
		config.synergy_component_weight * synergy -
		structural
	)
	return PreviewCandidateScore(
		action,
		team,
		(team[0], team[1]),
		(team[2], team[3]),
		plans,
		_round(lead_score),
		_round(coverage.score),
		_round(backline_score),
		_round(synergy),
		_round(structural),
		_round(final),
	)


def _preview_plan_scores(
	selected: tuple[OwnPokemonKnowledge, ...],
	lead: tuple[OwnPokemonKnowledge, ...],
	roster: OpponentRosterProfile,
	coverage_score: float,
	mechanics: MechanicsSnapshot,
	config: PreviewConfig,
) -> PreviewPlanScores:
	weights = config.weights
	species = {to_id(pokemon.species) for pokemon in selected}
	lead_species = {to_id(pokemon.species) for pokemon in lead}
	profiles = roster.pokemon

	glaceon = 0.0
	if "glaceon" in species:
		glaceon += weights["GLACEON_SELECTED"]
		if "ninetalesalola" in species:
			glaceon += weights["GLACEON_NINETALES"]
		if "maushold" in species:
			glaceon += weights["GLACEON_MAUSHOLD"]
		if "armarouge" in species and roster.spread_fire_count:
			glaceon += weights["GLACEON_ARMAROUGE_SPREAD_FIRE"]
		glaceon += weights["GLACEON_PHYSICAL_FRACTION"] * roster.physical_pressure_fraction
		ice_matchups = _favorable_matchups(_find_selected(selected, "glaceon"), profiles, mechanics)
		glaceon += min(weights["GLACEON_ICE_MATCHUP_CAP"], weights["GLACEON_ICE_MATCHUP"] * ice_matchups)
		glaceon -= weights["GLACEON_NO_GUARD_PENALTY"] * roster.no_guard_count
		bypass_without_no_guard = max(0, roster.accuracy_bypass_count - roster.no_guard_count)
		glaceon -= weights["GLACEON_ACCURACY_BYPASS_PENALTY"] * bypass_without_no_guard
		glaceon -= weights["GLACEON_GRAVITY_PENALTY"] * sum(OpponentTag.GRAVITY in profile.tags for profile in profiles)
		glaceon -= min(
			weights["GLACEON_WEATHER_SETTER_PENALTY_CAP"],
			weights["GLACEON_WEATHER_SETTER_PENALTY"] * roster.weather_setter_count,
		)
		dangerous = sum(_dangerous_for_glaceon(profile) for profile in profiles)
		glaceon -= min(
			weights["GLACEON_DANGEROUS_PRESSURE_PENALTY_CAP"],
			weights["GLACEON_DANGEROUS_PRESSURE_PENALTY"] * dangerous,
		)
		if roster.weather_setter_count and "ninetalesalola" not in species:
			glaceon -= weights["GLACEON_NO_NINETALES_WEATHER_PENALTY"]

	aggron = 0.0
	if "aggron" in species:
		aggron += weights["AGGRON_SELECTED"]
		if "maushold" in species:
			aggron += weights["AGGRON_MAUSHOLD"]
		aggron += weights["AGGRON_PHYSICAL_FRACTION"] * roster.physical_pressure_fraction
		aggron += weights["AGGRON_BODY_PRESS_QUALITY"] * _body_press_quality(profiles, mechanics)
		ghost_fraction = sum(OpponentTag.BODY_PRESS_IMMUNE in profile.tags for profile in profiles) / len(profiles)
		aggron -= weights["AGGRON_GHOST_PENALTY"] * ghost_fraction
		aggron -= weights["AGGRON_SPECIAL_FRACTION_PENALTY"] * roster.special_pressure_fraction
		if any(OpponentTag.BURN_PRESSURE in profile.tags for profile in profiles):
			aggron -= weights["AGGRON_BURN_PRESSURE_PENALTY"]
		dangerous_switch_pressure = sum(_dangerous_for_base_aggron(profile) for profile in profiles)
		if "aggron" in lead_species and dangerous_switch_pressure:
			aggron += weights["AGGRON_LEAD_MEGA_SAFETY"]
		elif dangerous_switch_pressure:
			aggron -= weights["AGGRON_BACKLINE_DANGER_PENALTY"]

	tactical = weights["TACTICAL_BASE"]
	attacker_count = sum(_own_is_attacker(pokemon, mechanics) for pokemon in selected)
	tactical += weights["TACTICAL_ATTACKER_SELECTED"] * attacker_count
	tactical += weights["TACTICAL_COVERAGE_FACTOR"] * coverage_score
	se_pairs = sum(_selected_super_effective_pairs(pokemon, profiles, mechanics) for pokemon in selected)
	tactical += min(weights["TACTICAL_SUPER_EFFECTIVE_CAP"], weights["TACTICAL_SUPER_EFFECTIVE_PAIR"] * se_pairs)
	fortress_best = max(glaceon, aggron)
	if fortress_best < config.fortress_weak_score:
		tactical += min(
			weights["TACTICAL_WEAK_FORTRESS_CAP"],
			weights["TACTICAL_WEAK_FORTRESS_FACTOR"] * (config.fortress_weak_score - fortress_best),
		)

	values = {
		PlanLabel.GLACEON_FORTRESS: _clamp(glaceon),
		PlanLabel.AGGRON_FORTRESS: _clamp(aggron),
		PlanLabel.TACTICAL_OFFENSE: _clamp(tactical),
	}
	ordered = sorted(values, key=lambda plan: (-values[plan], plan.value))
	return PreviewPlanScores(values[PlanLabel.GLACEON_FORTRESS], values[PlanLabel.AGGRON_FORTRESS], values[PlanLabel.TACTICAL_OFFENSE], ordered[0], ordered[1])


def _coverage_assessment(
	selected: tuple[OwnPokemonKnowledge, ...],
	roster: OpponentRosterProfile,
	mechanics: MechanicsSnapshot,
	config: PreviewConfig,
) -> CoverageAssessment:
	total_importance = 0.0
	covered_importance = 0.0
	unanswered: list[str] = []
	structural = 0.0
	for profile in roster.pokemon:
		importance = _opponent_importance(profile, config)
		strength = _answer_strength(selected, profile, mechanics, config)
		total_importance += importance
		covered_importance += importance * min(1.0, strength)
		if importance >= config.major_threat_importance_threshold and strength < 0.5:
			unanswered.append(profile.pokemon_id)
			structural += config.weights["STRUCTURAL_UNANSWERED_MAJOR"] * importance
	score = 100.0 * covered_importance / total_importance if total_importance else 100.0
	return CoverageAssessment(_clamp(score), structural, tuple(sorted(unanswered)))


def _opponent_importance(profile: OpponentPokemonProfile, config: PreviewConfig) -> float:
	tags = set(profile.tags)
	weights = config.weights
	value = weights["COVERAGE_IMPORTANCE_BASE"]
	if OpponentTag.SETUP_SWEEPER in tags:
		value += weights["COVERAGE_IMPORTANCE_SETUP"]
	if OpponentTag.WEATHER_SETTER in tags:
		value += weights["COVERAGE_IMPORTANCE_WEATHER"]
	if OpponentTag.NO_GUARD in tags:
		value += weights["COVERAGE_IMPORTANCE_NO_GUARD"]
	if OpponentTag.SPREAD_DAMAGE in tags:
		value += weights["COVERAGE_IMPORTANCE_SPREAD"]
	if OpponentTag.SPEED_CONTROL in tags:
		value += weights["COVERAGE_IMPORTANCE_SPEED_CONTROL"]
	if OpponentTag.FAKE_OUT in tags:
		value += weights["COVERAGE_IMPORTANCE_FAKE_OUT"]
	return value


def _answer_strength(
	selected: tuple[OwnPokemonKnowledge, ...],
	profile: OpponentPokemonProfile,
	mechanics: MechanicsSnapshot,
	config: PreviewConfig,
) -> float:
	strength = 0.0
	if any(_own_offensive_answer(pokemon, profile, mechanics) for pokemon in selected):
		strength += config.weights["COVERAGE_OFFENSIVE_ANSWER"]
	if any(_own_defensive_answer(pokemon, profile, mechanics) for pokemon in selected):
		strength += config.weights["COVERAGE_DEFENSIVE_ANSWER"]
	if any(_own_specialist_answer(pokemon, profile, mechanics) for pokemon in selected):
		strength += config.weights["COVERAGE_SPECIALIST_ANSWER"]
	return strength


def _own_offensive_answer(
	pokemon: OwnPokemonKnowledge, profile: OpponentPokemonProfile, mechanics: MechanicsSnapshot
) -> bool:
	for move_knowledge in pokemon.moves:
		try:
			move = mechanics.move(move_knowledge.id)
		except KeyError:
			continue
		if move.base_power <= 0:
			continue
		multipliers = []
		for types in profile.possible_type_sets:
			try:
				multipliers.append(mechanics.move_multiplier(move, types))
			except (KeyError, ValueError, UnresolvedMechanicError):
				multipliers.append(0.0)
		if multipliers and min(multipliers) > 1.0:
			return True
	return False


def _own_defensive_answer(
	pokemon: OwnPokemonKnowledge, profile: OpponentPokemonProfile, mechanics: MechanicsSnapshot
) -> bool:
	ability_semantics = _safe_semantic(mechanics, "abilities", pokemon.ability)
	pressure_ids = {to_id(type_name) for type_name in profile.pressure_types}
	if "fire" in pressure_ids and ability_semantics.get("fire_immunity") is True:
		return True
	if "water" in pressure_ids and "water_immunity_and_heal_fraction" in ability_semantics:
		return True
	if "electric" in pressure_ids and ability_semantics.get("electric_immunity") is True:
		return True
	damaging = []
	for move_id in profile.moves:
		try:
			move = mechanics.move(move_id)
			if move.base_power > 0:
				damaging.append(move)
		except KeyError:
			continue
	if not damaging:
		return False
	multipliers = []
	for move in damaging:
		try:
			multipliers.append(mechanics.move_multiplier(move, pokemon.types))
		except (KeyError, ValueError, UnresolvedMechanicError):
			return False
	return bool(multipliers and max(multipliers) <= 0.5)


def _own_specialist_answer(
	pokemon: OwnPokemonKnowledge, profile: OpponentPokemonProfile, mechanics: MechanicsSnapshot
) -> bool:
	move_ids = {to_id(move.id) for move in pokemon.moves}
	tags = set(profile.tags)
	if "wideguard" in move_ids and OpponentTag.SPREAD_DAMAGE in tags:
		return True
	if "encore" in move_ids and OpponentTag.SETUP_SWEEPER in tags:
		return True
	if ("followme" in move_ids or "ragepowder" in move_ids) and _is_attacker(profile) and OpponentTag.SPREAD_DAMAGE not in tags:
		return True
	ability_semantics = _safe_semantic(mechanics, "abilities", pokemon.ability)
	if OpponentTag.FIRE_PRESSURE in tags and ability_semantics.get("fire_immunity") is True:
		return True
	if OpponentTag.WATER_PRESSURE in tags and "water_immunity_and_heal_fraction" in ability_semantics:
		return True
	if OpponentTag.ELECTRIC_PRESSURE in tags and ability_semantics.get("electric_immunity") is True:
		return True
	if OpponentTag.WEATHER_SETTER in tags and ability_semantics.get("entry_weather"):
		return True
	return False


def _lead_robustness(
	lead: tuple[OwnPokemonKnowledge, ...],
	hypotheses: tuple[OpponentLeadHypothesis, ...],
	roster: OpponentRosterProfile,
	mechanics: MechanicsSnapshot,
	config: PreviewConfig,
) -> float:
	profiles = {profile.pokemon_id: profile for profile in roster.pokemon}
	per_hypothesis = []
	for hypothesis in hypotheses:
		opponents = tuple(profiles[pokemon_id] for pokemon_id in hypothesis.members)
		per_hypothesis.append((hypothesis.weight, _lead_score_against(lead, opponents, mechanics, config)))
	if not per_hypothesis:
		return 0.0
	expected = sum(weight * score for weight, score in per_hypothesis)
	bad_case = min(score for _, score in per_hypothesis)
	return _clamp(config.lead_expected_weight * expected + config.lead_bad_case_weight * bad_case)


def _lead_score_against(
	lead: tuple[OwnPokemonKnowledge, ...],
	opponents: tuple[OpponentPokemonProfile, ...],
	mechanics: MechanicsSnapshot,
	config: PreviewConfig,
) -> float:
	weights = config.weights
	score = weights["LEAD_BASE"]
	lead_species = {to_id(pokemon.species) for pokemon in lead}
	opp_tags = set(tag for profile in opponents for tag in profile.tags)
	for opponent in opponents:
		if any(_own_offensive_answer(pokemon, opponent, mechanics) for pokemon in lead):
			score += weights["LEAD_IMMEDIATE_PRESSURE"]
	for pokemon in lead:
		if any(_opponent_has_super_effective_pressure(opponent, pokemon, mechanics) for opponent in opponents):
			score -= weights["LEAD_SUPER_EFFECTIVE_DANGER_PENALTY"]
	if {"ninetalesalola", "glaceon"} <= lead_species:
		score += weights["LEAD_NINETALES_GLACEON"]
	if "maushold" in lead_species and ("glaceon" in lead_species or "aggron" in lead_species):
		score += weights["LEAD_MAUSHOLD_FORTRESS"]
	if "armarouge" in lead_species and OpponentTag.SPREAD_DAMAGE in opp_tags:
		score += weights["LEAD_ARMAROUGE_SPREAD"]
	if "heliolisk" in lead_species and OpponentTag.WATER_PRESSURE in opp_tags:
		score += weights["LEAD_HELIOLISK_WATER"]
	if OpponentTag.FAKE_OUT in opp_tags and "maushold" in lead_species and (
		"glaceon" in lead_species or "aggron" in lead_species
	):
		score -= weights["LEAD_FAKE_OUT_SUPPORT_PENALTY"]
	if OpponentTag.WEATHER_SETTER in opp_tags and "ninetalesalola" in lead_species:
		score -= weights["LEAD_NINETALES_WEATHER_CONFLICT_PENALTY"]
	if "aggron" in lead_species and (
		OpponentTag.FIGHTING_PRESSURE in opp_tags or OpponentTag.GROUND_PRESSURE in opp_tags
	):
		score += weights["LEAD_AGGRON_MEGA_SAFETY"]
	if "glaceon" in lead_species and any(_dangerous_for_glaceon(profile) for profile in opponents):
		score -= weights["LEAD_GLACEON_DANGEROUS_PENALTY"]
	if "glaceon" in lead_species and OpponentTag.NO_GUARD in opp_tags:
		score -= weights["LEAD_GLACEON_NO_GUARD_PENALTY"]
	return _clamp(score)


def _backline_quality(
	backline: tuple[OwnPokemonKnowledge, ...], roster: OpponentRosterProfile, config: PreviewConfig
) -> float:
	weights = config.weights
	score = weights["BACKLINE_BASE"]
	species = {to_id(pokemon.species) for pokemon in backline}
	dangerous_glaceon = sum(_dangerous_for_glaceon(profile) for profile in roster.pokemon)
	dangerous_aggron = sum(_dangerous_for_base_aggron(profile) for profile in roster.pokemon)
	if "ninetalesalola" in species and roster.weather_setter_count:
		score += weights["BACKLINE_NINETALES_WEATHER_WAR"]
	if "glaceon" in species and dangerous_glaceon >= 2:
		score += weights["BACKLINE_GLACEON_SHELTER"]
	if "aggron" in species and dangerous_aggron:
		score -= weights["BACKLINE_AGGRON_DANGER_PENALTY"]
	if "armarouge" in species and roster.spread_fire_count:
		score -= weights["BACKLINE_ARMAROUGE_LATE_SPREAD_PENALTY"]
	if "heliolisk" in species and roster.water_pressure_count:
		score += weights["BACKLINE_HELIOLISK_WATER"]
	return _clamp(score)


def _synergy_score(
	selected: tuple[OwnPokemonKnowledge, ...], roster: OpponentRosterProfile, config: PreviewConfig
) -> float:
	weights = config.weights
	species = {to_id(pokemon.species) for pokemon in selected}
	score = 0.0
	pairs = (
		("ninetalesalola", "glaceon", "SYNERGY_NINETALES_GLACEON"),
		("maushold", "glaceon", "SYNERGY_MAUSHOLD_GLACEON"),
		("maushold", "aggron", "SYNERGY_MAUSHOLD_AGGRON"),
		("armarouge", "glaceon", "SYNERGY_ARMAROUGE_GLACEON"),
		("armarouge", "maushold", "SYNERGY_ARMAROUGE_MAUSHOLD"),
		("heliolisk", "ninetalesalola", "SYNERGY_HELIOLISK_NINETALES"),
	)
	for left, right, weight_id in pairs:
		if {left, right} <= species:
			score += weights[weight_id]
	if "armarouge" in species and roster.spread_fire_count:
		score += weights["SPECIALIST_ARMAROUGE_SPREAD_FIRE"]
	if "heliolisk" in species and roster.water_pressure_count:
		score += weights["SPECIALIST_HELIOLISK_WATER"]
	return min(config.synergy_cap, score)


def _favorable_matchups(
	pokemon: OwnPokemonKnowledge | None,
	profiles: Iterable[OpponentPokemonProfile],
	mechanics: MechanicsSnapshot,
) -> int:
	if pokemon is None:
		return 0
	return sum(any(_move_robustly_super_effective(move.id, profile, mechanics) for move in pokemon.moves) for profile in profiles)


def _selected_super_effective_pairs(
	pokemon: OwnPokemonKnowledge,
	profiles: Iterable[OpponentPokemonProfile],
	mechanics: MechanicsSnapshot,
) -> int:
	return sum(any(_move_robustly_super_effective(move.id, profile, mechanics) for move in pokemon.moves) for profile in profiles)


def _move_robustly_super_effective(
	move_id: str, profile: OpponentPokemonProfile, mechanics: MechanicsSnapshot
) -> bool:
	try:
		move = mechanics.move(move_id)
		if move.base_power <= 0:
			return False
		return min(mechanics.move_multiplier(move, types) for types in profile.possible_type_sets) > 1.0
	except (KeyError, ValueError, UnresolvedMechanicError):
		return False


def _body_press_quality(profiles: Iterable[OpponentPokemonProfile], mechanics: MechanicsSnapshot) -> float:
	profiles = tuple(profiles)
	if not profiles:
		return 0.0
	good = 0
	for profile in profiles:
		try:
			multipliers = [mechanics.move_multiplier("bodypress", types) for types in profile.possible_type_sets]
		except (KeyError, ValueError, UnresolvedMechanicError):
			continue
		if multipliers and min(multipliers) >= 1.0:
			good += 1
	return good / len(profiles)


def _own_is_attacker(pokemon: OwnPokemonKnowledge, mechanics: MechanicsSnapshot) -> bool:
	for known_move in pokemon.moves:
		try:
			if mechanics.move(known_move.id).base_power > 0:
				return True
		except KeyError:
			pass
	return False


def _opponent_has_super_effective_pressure(
	profile: OpponentPokemonProfile,
	pokemon: OwnPokemonKnowledge,
	mechanics: MechanicsSnapshot,
) -> bool:
	for move_id in profile.moves:
		try:
			move = mechanics.move(move_id)
			if move.base_power > 0 and mechanics.move_multiplier(move, pokemon.types) > 1.0:
				return True
		except (KeyError, ValueError, UnresolvedMechanicError):
			continue
	return False


def _dangerous_for_glaceon(profile: OpponentPokemonProfile) -> bool:
	tags = set(profile.tags)
	return bool(tags & {
		OpponentTag.FIRE_PRESSURE,
		OpponentTag.FIGHTING_PRESSURE,
		OpponentTag.ROCK_PRESSURE,
	})


def _dangerous_for_base_aggron(profile: OpponentPokemonProfile) -> bool:
	tags = set(profile.tags)
	return OpponentTag.FIGHTING_PRESSURE in tags or OpponentTag.GROUND_PRESSURE in tags


def _find_selected(selected: Iterable[OwnPokemonKnowledge], species_id: str) -> OwnPokemonKnowledge | None:
	wanted = to_id(species_id)
	for pokemon in selected:
		if to_id(pokemon.species) == wanted:
			return pokemon
	return None


def _plan_value(plans: PreviewPlanScores, plan: PlanLabel) -> float:
	if plan is PlanLabel.GLACEON_FORTRESS:
		return plans.glaceon_fortress
	if plan is PlanLabel.AGGRON_FORTRESS:
		return plans.aggron_fortress
	if plan is PlanLabel.TACTICAL_OFFENSE:
		return plans.tactical_offense
	return 0.0


def _clamp(value: float) -> float:
	return max(0.0, min(100.0, value))


def _round(value: float) -> float:
	return round(float(value), 6)
