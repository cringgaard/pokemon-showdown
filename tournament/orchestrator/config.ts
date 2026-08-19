import { createHash } from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import { toID } from '../../sim/dex-data';
import { DEFAULT_FORMAT } from '../match/match-runner';

export const TOURNAMENT_CONFIG_SCHEMA_VERSION = 1;

export interface TournamentParticipantConfig {
	id: string;
	name: string;
	submission: string;
}

export interface TournamentConfig {
	schema_version: number;
	title: string;
	subtitle: string;
	format: string;
	seed: string;
	runtime: 'docker' | 'host';
	decision_timeout_ms: number;
	max_invalid_attempts: number;
	match_timeout_ms: number;
	participants: TournamentParticipantConfig[];
	round_robin: { games_per_pairing: number };
	final: { qualifiers: 2, best_of: number, max_tied_games: number };
}

export interface LoadedTournamentConfig {
	configPath: string;
	configDirectory: string;
	config: TournamentConfig;
	hash: string;
}

export function loadTournamentConfig(filename: string): LoadedTournamentConfig {
	const configPath = path.resolve(filename);
	let source: unknown;
	try {
		source = JSON.parse(fs.readFileSync(configPath, 'utf8'));
	} catch (error) {
		throw new Error(`Tournament config ${JSON.stringify(configPath)} could not be read as JSON: ${errorMessage(error)}`);
	}
	const configDirectory = path.dirname(configPath);
	const config = normalizeTournamentConfig(source, configDirectory);
	return { configPath, configDirectory, config, hash: tournamentConfigHash(config) };
}

export function normalizeTournamentConfig(source: unknown, configDirectory: string): TournamentConfig {
	const raw = objectValue(source, 'Tournament config');
	const participantsRaw = arrayValue(raw.participants, 'participants');
	if (participantsRaw.length < 2) throw new Error('Tournament config requires at least two participants.');
	const participants = participantsRaw.map((entry, index) => {
		const participant = objectValue(entry, `participants[${index}]`);
		const id = stringValue(participant.id, `participants[${index}].id`);
		if (!/^[a-z0-9][a-z0-9_-]*$/.test(id)) {
			throw new Error(`participants[${index}].id must use lowercase letters, digits, underscores, or hyphens.`);
		}
		return {
			id,
			name: stringValue(participant.name, `participants[${index}].name`),
			submission: path.resolve(configDirectory, stringValue(
				participant.submission, `participants[${index}].submission`
			)),
		};
	}).sort((a, b) => a.id.localeCompare(b.id));
	assertUnique(participants.map(participant => participant.id), 'participant IDs');
	assertUnique(participants.map(participant => toID(participant.name)), 'participant names');
	const runtime = raw.runtime ?? 'docker';
	if (runtime !== 'docker' && runtime !== 'host') throw new Error('runtime must be either "docker" or "host".');
	const roundRobin = objectValue(raw.round_robin, 'round_robin');
	const final = objectValue(raw.final, 'final');
	const bestOf = positiveInteger(final.best_of, 'final.best_of');
	if (bestOf % 2 !== 1) throw new Error('final.best_of must be odd.');
	const qualifiers = final.qualifiers ?? 2;
	if (qualifiers !== 2) throw new Error('Milestone 3 supports exactly two final.qualifiers.');
	return {
		schema_version: TOURNAMENT_CONFIG_SCHEMA_VERSION,
		title: stringValue(raw.title, 'title'),
		subtitle: optionalString(raw.subtitle) || optionalString(raw.format) || DEFAULT_FORMAT,
		format: optionalString(raw.format) || DEFAULT_FORMAT,
		seed: seedValue(raw.seed),
		runtime,
		decision_timeout_ms: positiveInteger(raw.decision_timeout_ms ?? 5000, 'decision_timeout_ms'),
		max_invalid_attempts: positiveInteger(raw.max_invalid_attempts ?? 3, 'max_invalid_attempts'),
		match_timeout_ms: positiveInteger(raw.match_timeout_ms ?? 60_000, 'match_timeout_ms'),
		participants,
		round_robin: {
			games_per_pairing: positiveInteger(roundRobin.games_per_pairing, 'round_robin.games_per_pairing'),
		},
		final: {
			qualifiers: 2,
			best_of: bestOf,
			max_tied_games: positiveInteger(final.max_tied_games ?? bestOf, 'final.max_tied_games'),
		},
	};
}

export function tournamentConfigHash(config: TournamentConfig) {
	return createHash('sha256').update(stableJSON(config)).digest('hex');
}

export function stableJSON(value: unknown): string {
	if (Array.isArray(value)) return `[${value.map(stableJSON).join(',')}]`;
	if (value && typeof value === 'object') {
		return `{${Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b))
			.map(([key, child]) => `${JSON.stringify(key)}:${stableJSON(child)}`).join(',')}}`;
	}
	return JSON.stringify(value);
}

function objectValue(value: unknown, name: string) {
	if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${name} must be a JSON object.`);
	return value as Record<string, unknown>;
}

function arrayValue(value: unknown, name: string) {
	if (!Array.isArray(value)) throw new Error(`${name} must be a JSON array.`);
	return value;
}

function stringValue(value: unknown, name: string) {
	if (typeof value !== 'string' || !value.trim()) throw new Error(`${name} must be a non-empty string.`);
	return value.trim();
}

function optionalString(value: unknown) {
	return typeof value === 'string' ? value.trim() : '';
}

function seedValue(value: unknown) {
	if (value === undefined) return '1';
	if (typeof value !== 'string' && typeof value !== 'number') throw new Error('seed must be a string or number.');
	return String(value);
}

function positiveInteger(value: unknown, name: string) {
	if (!Number.isSafeInteger(value) || Number(value) <= 0) throw new Error(`${name} must be a positive integer.`);
	return Number(value);
}

function assertUnique(values: string[], label: string) {
	const seen = new Set<string>();
	for (const value of values) {
		if (seen.has(value)) throw new Error(`Tournament ${label} must be unique; duplicate ${JSON.stringify(value)}.`);
		seen.add(value);
	}
}

function errorMessage(error: unknown) {
	return error instanceof Error ? error.message : String(error);
}
