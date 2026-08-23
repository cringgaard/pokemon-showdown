import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';

import { Dex, type ModdedDex } from '../../sim/dex';

export const CHAMPIONS_FORMAT = 'gen9championsvgc2026regmb';
export const MECHANICS_SNAPSHOT_SCHEMA_VERSION = 1;
export const SEMANTIC_ANNOTATION_VERSION = 1;

export interface MechanicsSnapshot {
	schema_version: number;
	format: {
		id: string,
		name: string,
		mod: string,
		gen: number,
		game_type: string,
	};
	source: {
		showdown_commit: string | null,
	};
	type_chart: Record<string, Record<string, number>>;
	species: SpeciesSnapshot[];
	moves: MoveSnapshot[];
	abilities: EffectSnapshot[];
	items: ItemSnapshot[];
	semantics: SemanticAnnotations;
	snapshot_hash: string;
}

export interface SpeciesSnapshot {
	id: string;
	name: string;
	base_species: string;
	forme: string;
	types: string[];
	base_stats: Record<string, number>;
	abilities: Record<string, string>;
	weight_kg: number;
	is_mega: boolean;
	battle_only: string | string[] | null;
	changes_from: string | null;
	required_item: string | null;
	required_items: string[];
	is_nonstandard: string | null;
}

export interface MoveSnapshot {
	id: string;
	name: string;
	type: string;
	category: string;
	base_power: number;
	accuracy: number | true;
	pp: number;
	priority: number;
	target: string;
	flags: string[];
	boosts: Record<string, number>;
	self_boosts: Record<string, number>;
	status: string | null;
	volatile_status: string | null;
	side_condition: string | null;
	weather: string | null;
	terrain: string | null;
	pseudo_weather: string | null;
	heal: number[] | null;
	drain: number[] | null;
	recoil: number[] | null;
	force_switch: boolean;
	self_switch: string | boolean | null;
	breaks_protect: boolean;
	override_offensive_stat: string | null;
	override_defensive_stat: string | null;
	ignore_accuracy: boolean;
	ignore_evasion: boolean;
	ignore_immunity: boolean | Record<string, boolean>;
	callback_names: string[];
	is_nonstandard: string | null;
}

export interface EffectSnapshot {
	id: string;
	name: string;
	callback_names: string[];
	is_nonstandard: string | null;
}

export interface ItemSnapshot extends EffectSnapshot {
	mega_stone: Record<string, string> | null;
	is_berry: boolean;
	is_choice: boolean;
	boosts: Record<string, number>;
}

export interface SemanticAnnotations {
	version: number;
	abilities: Record<string, Record<string, unknown>>;
	moves: Record<string, Record<string, unknown>>;
	items: Record<string, Record<string, unknown>>;
	field: Record<string, Record<string, unknown>>;
}

/**
 * Small, explicit interpretations of callback-backed mechanics that later policy
 * stages need to reason about. The executable format implementation is the
 * authority; B2 tests pin these annotations directly to its callbacks/data.
 */
const SEMANTICS: SemanticAnnotations = {
	version: SEMANTIC_ANNOTATION_VERSION,
	abilities: {
		noguard: { accuracy_bypass: true, invulnerability_bypass: true },
		lightningrod: { electric_redirection: true, electric_immunity: true, spa_boost_on_redirect: 1 },
		stamina: { defense_boost_on_damaging_hit: 1 },
		defiant: { attack_boost_on_opponent_stat_drop: 2 },
		competitive: { spa_boost_on_opponent_stat_drop: 2 },
		contrary: { invert_stat_changes: true },
		snowcloak: {
			incoming_accuracy_modifier_in_weather: {
				hail: [3277, 4096],
				snowscape: [3277, 4096],
			},
		},
		friendguard: { ally_damage_multiplier: 0.75 },
		filter: { super_effective_damage_multiplier: 0.75 },
		flashfire: { fire_immunity: true, fire_power_multiplier_after_activation: 1.5 },
		dryskin: { water_immunity_and_heal_fraction: 0.25, fire_damage_multiplier: 1.25 },
		drizzle: { entry_weather: 'raindance' },
		drought: { entry_weather: 'sunnyday' },
		snowwarning: { entry_weather: 'snowscape' },
	},
	moves: {
		freezedry: { effectiveness_override: { Water: 2 } },
		bodypress: { offensive_stat: 'def' },
		blizzard: {
			accuracy_by_weather: { hail: true, snowscape: true },
			weather_accuracy_fully_modeled: true,
		},
		thunder: {
			accuracy_by_weather: { raindance: true, primordialsea: true, sunnyday: 50, desolateland: 50 },
			weather_accuracy_fully_modeled: true,
		},
		hurricane: {
			accuracy_by_weather: { raindance: true, primordialsea: true, sunnyday: 50, desolateland: 50 },
			weather_accuracy_fully_modeled: true,
		},
		wideguard: { spread_protection: true },
		followme: { single_target_redirection: true },
		allyswitch: { swaps_active_positions: true, repeated_use_can_fail: true },
		auroraveil: { requires_weather: ['hail', 'snowscape'], side_condition: 'auroraveil' },
		wish: { delayed_heal_fraction: 0.5, delay_turns: 1 },
		grassknot: { weight_based_power: true },
		heavyslam: { weight_ratio_power: true },
		protect: { protection_move: true },
		encore: { locks_last_move: true },
		fakeout: { first_turn_only: true },
		mudslap: { target_accuracy_change: -1 },
	},
	items: {
		brightpowder: { incoming_accuracy_modifier: [3686, 4096] },
		focussash: { survive_full_hp_lethal_hit: true, consumable: true },
		chopleberry: { super_effective_type_damage_multiplier: { Fighting: 0.5 }, consumable: true },
		icyrock: { weather_extension_turns: { hail: 8, snowscape: 8 } },
	},
	field: {
		gravity: { accuracy_multiplier_ratio: [6840, 4096], grounds_flying: true },
	},
};

export function buildChampionsMechanicsSnapshot(
	formatID = CHAMPIONS_FORMAT,
	showdownCommit: string | null = process.env.GIT_COMMIT_SHA || null
): MechanicsSnapshot {
	const format = Dex.formats.get(formatID);
	if (!format.exists) throw new Error(`Unknown format: ${formatID}`);
	const dex = Dex.forFormat(format);
	const payload = {
		schema_version: MECHANICS_SNAPSHOT_SCHEMA_VERSION,
		format: {
			id: format.id,
			name: format.name,
			mod: dex.currentMod,
			gen: dex.gen,
			game_type: format.gameType,
		},
		source: { showdown_commit: showdownCommit },
		type_chart: buildTypeChart(dex),
		species: dex.species.all().filter(species => species.exists).map(species => ({
			id: species.id,
			name: species.name,
			base_species: species.baseSpecies,
			forme: species.forme,
			types: [...species.types],
			base_stats: { ...species.baseStats },
			abilities: { ...species.abilities },
			weight_kg: species.weightkg,
			is_mega: !!species.isMega,
			battle_only: species.battleOnly || null,
			changes_from: species.changesFrom || null,
			required_item: species.requiredItem || null,
			required_items: [...(species.requiredItems || [])],
			is_nonstandard: species.isNonstandard || null,
		})).sort(compareID),
		moves: canonicalMoves(dex).map(move => ({
			id: move.id,
			name: move.name,
			type: move.type,
			category: move.category,
			base_power: move.basePower,
			accuracy: move.accuracy,
			pp: move.pp,
			priority: move.priority,
			target: move.target,
			flags: Object.keys(move.flags).filter(flag => !!(move.flags as Record<string, unknown>)[flag]).sort(),
			boosts: { ...(move.boosts || {}) },
			self_boosts: { ...(move.self?.boosts || {}), ...(move.selfBoost?.boosts || {}) },
			status: move.status || null,
			volatile_status: move.volatileStatus || null,
			side_condition: move.sideCondition || null,
			weather: move.weather || null,
			terrain: move.terrain || null,
			pseudo_weather: move.pseudoWeather || null,
			heal: move.heal ? [...move.heal] : null,
			drain: move.drain ? [...move.drain] : null,
			recoil: move.recoil ? [...move.recoil] : null,
			force_switch: !!move.forceSwitch,
			self_switch: move.selfSwitch ?? null,
			breaks_protect: !!move.breaksProtect,
			override_offensive_stat: move.overrideOffensiveStat || null,
			override_defensive_stat: move.overrideDefensiveStat || null,
			ignore_accuracy: !!move.ignoreAccuracy,
			ignore_evasion: !!move.ignoreEvasion,
			ignore_immunity: normalizeIgnoreImmunity(move.ignoreImmunity),
			callback_names: callbackNames(move),
			is_nonstandard: move.isNonstandard || null,
		})).sort(compareID),
		abilities: dex.abilities.all().filter(ability => ability.exists).map(ability => ({
			id: ability.id,
			name: ability.name,
			callback_names: callbackNames(ability),
			is_nonstandard: ability.isNonstandard || null,
		})).sort(compareID),
		items: dex.items.all().filter(item => item.exists).map(item => ({
			id: item.id,
			name: item.name,
			callback_names: callbackNames(item),
			is_nonstandard: item.isNonstandard || null,
			mega_stone: item.megaStone ? { ...item.megaStone } : null,
			is_berry: item.isBerry,
			is_choice: !!item.isChoice,
			boosts: item.boosts ? { ...item.boosts } : {},
		})).sort(compareID),
		semantics: SEMANTICS,
	};
	const snapshotHash = `sha256:${crypto.createHash('sha256').update(stableStringify(payload)).digest('hex')}`;
	return { ...payload, snapshot_hash: snapshotHash };
}

export function writeChampionsMechanicsSnapshot(
	outputPath: string,
	formatID = CHAMPIONS_FORMAT,
	showdownCommit: string | null = process.env.GIT_COMMIT_SHA || null
) {
	const snapshot = buildChampionsMechanicsSnapshot(formatID, showdownCommit);
	fs.mkdirSync(path.dirname(outputPath), { recursive: true });
	fs.writeFileSync(outputPath, `${JSON.stringify(sortRecursively(snapshot), null, 2)}\n`);
	return snapshot;
}

export function stableStringify(value: unknown): string {
	return JSON.stringify(sortRecursively(value));
}

function canonicalMoves(dex: ModdedDex) {
	const ids = [...new Set(dex.moves.all().filter(move => move.exists).map(move => move.id))].sort();
	return ids.map(id => dex.moves.get(id)).filter(move => move.exists);
}

function buildTypeChart(dex: ModdedDex) {
	const typeNames = dex.types.all().filter(type => type.exists).map(type => type.name).sort();
	const chart: Record<string, Record<string, number>> = {};
	for (const attackingType of typeNames) {
		chart[attackingType] = {};
		for (const defendingType of typeNames) {
			if (!dex.getImmunity(attackingType, defendingType)) {
				chart[attackingType][defendingType] = 0;
			} else {
				chart[attackingType][defendingType] = 2 ** dex.getEffectiveness(attackingType, defendingType);
			}
		}
	}
	return chart;
}

function normalizeIgnoreImmunity(value: boolean | { [typeName: string]: boolean } | undefined) {
	if (!value) return false;
	if (value === true) return true;
	return { ...value };
}

function callbackNames(value: object) {
	return Object.keys(value).filter(key => typeof (value as Record<string, unknown>)[key] === 'function').sort();
}

function compareID<T extends { id: string }>(left: T, right: T) {
	return left.id.localeCompare(right.id);
}

function sortRecursively(value: unknown): unknown {
	if (Array.isArray(value)) return value.map(sortRecursively);
	if (!value || typeof value !== 'object') return value;
	const object = value as Record<string, unknown>;
	return Object.fromEntries(Object.keys(object).sort().map(key => [key, sortRecursively(object[key])]));
}

if (require.main === module) {
	const outputPath = process.argv[2];
	if (!outputPath) {
		throw new Error('Usage: node dist/tournament/mechanics/champions-snapshot.js <output-path> [format-id]');
	}
	writeChampionsMechanicsSnapshot(outputPath, process.argv[3] || CHAMPIONS_FORMAT);
}
