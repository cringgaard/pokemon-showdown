import * as fs from 'fs';
import * as path from 'path';
import { loadReplayArtifacts } from '../spectator/replay-loader';
import type { LoadedTournamentConfig, TournamentConfig } from './config';
import type { CompletedTournamentGame, ScheduledGame } from './model';

export const TOURNAMENT_STATE_SCHEMA_VERSION = 1;

export interface InProgressTournamentGame {
	game: ScheduledGame;
	attempt: number;
	artifact_directory: string;
}

export interface TournamentState {
	schema_version: number;
	config_hash: string;
	phase: 'round_robin' | 'final' | 'complete';
	completed_games: CompletedTournamentGame[];
	in_progress: InProgressTournamentGame | null;
	finalists: [string, string] | null;
	champion: string | null;
	champion_reason: 'series' | 'tie_safety_limit' | null;
}

interface TournamentManifest {
	schema_version: number;
	config_hash: string;
	config: TournamentConfig;
}

export class TournamentStateStore {
	readonly outputDirectory: string;
	readonly manifestPath: string;
	readonly statePath: string;
	readonly config: LoadedTournamentConfig;
	state: TournamentState;

	constructor(outputDirectory: string, config: LoadedTournamentConfig) {
		this.outputDirectory = path.resolve(outputDirectory);
		this.manifestPath = path.join(this.outputDirectory, 'tournament.json');
		this.statePath = path.join(this.outputDirectory, 'state.json');
		this.config = config;
		this.state = this.loadOrCreate();
		this.validateCompletedArtifacts();
	}

	save() {
		atomicWriteJSON(this.statePath, this.state);
	}

	matchAttemptDirectory(game: ScheduledGame, attempt: number) {
		return path.join(this.outputDirectory, 'matches', ...game.id.split('/'), `attempt-${attempt}`);
	}

	completedIDs() {
		return new Set(this.state.completed_games.map(game => game.id));
	}

	private loadOrCreate(): TournamentState {
		if (!fs.existsSync(this.outputDirectory)) fs.mkdirSync(this.outputDirectory, { recursive: true });
		if (!fs.statSync(this.outputDirectory).isDirectory()) {
			throw new Error(`Tournament output ${JSON.stringify(this.outputDirectory)} is not a directory.`);
		}
		const hasManifest = fs.existsSync(this.manifestPath);
		const hasState = fs.existsSync(this.statePath);
		if (!hasManifest && !hasState) {
			if (fs.readdirSync(this.outputDirectory).length) {
				throw new Error(`Tournament output directory ${JSON.stringify(this.outputDirectory)} is not empty or resumable.`);
			}
			const manifest: TournamentManifest = {
				schema_version: TOURNAMENT_STATE_SCHEMA_VERSION,
				config_hash: this.config.hash,
				config: this.config.config,
			};
			atomicWriteJSON(this.manifestPath, manifest);
			const initial: TournamentState = {
				schema_version: TOURNAMENT_STATE_SCHEMA_VERSION,
				config_hash: this.config.hash,
				phase: 'round_robin',
				completed_games: [],
				in_progress: null,
				finalists: null,
				champion: null,
				champion_reason: null,
			};
			atomicWriteJSON(this.statePath, initial);
			return initial;
		}
		if (!hasManifest || !hasState) {
			throw new Error(`Tournament output ${JSON.stringify(this.outputDirectory)} has incomplete manifest/state files.`);
		}
		const manifest = readJSON(this.manifestPath) as Partial<TournamentManifest>;
		const state = readJSON(this.statePath) as Partial<TournamentState>;
		if (manifest.schema_version !== TOURNAMENT_STATE_SCHEMA_VERSION ||
			state.schema_version !== TOURNAMENT_STATE_SCHEMA_VERSION) {
			throw new Error(`Tournament output uses an incompatible state schema version.`);
		}
		if (manifest.config_hash !== this.config.hash || state.config_hash !== this.config.hash) {
			throw new Error('Tournament config does not match the durable state in the selected output directory.');
		}
		if (!Array.isArray(state.completed_games)) throw new Error('Tournament state completed_games must be an array.');
		return state as TournamentState;
	}

	private validateCompletedArtifacts() {
		const seen = new Set<string>();
		for (const game of this.state.completed_games) {
			if (seen.has(game.id)) throw new Error(`Tournament state contains duplicate completed game ${game.id}.`);
			seen.add(game.id);
			const replay = loadReplayArtifacts(game.artifact_directory);
			const result = replay.result;
			if (result.tie !== game.tie || result.winner_participant_id !== game.winner_participant_id) {
				throw new Error(`Completed game artifact ${game.id} does not match tournament state.`);
			}
			if (replay.metadata.seed !== game.seed) {
				throw new Error(`Completed game artifact ${game.id} has a different deterministic seed.`);
			}
		}
	}
}

export function atomicWriteJSON(filename: string, value: unknown) {
	fs.mkdirSync(path.dirname(filename), { recursive: true });
	const temporary = `${filename}.tmp-${process.pid}-${Date.now()}`;
	try {
		fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
		fs.renameSync(temporary, filename);
	} finally {
		if (fs.existsSync(temporary)) fs.rmSync(temporary);
	}
}

function readJSON(filename: string) {
	try {
		return JSON.parse(fs.readFileSync(filename, 'utf8')) as unknown;
	} catch (error) {
		throw new Error(`Tournament state file ${JSON.stringify(filename)} is invalid: ${errorMessage(error)}`);
	}
}

function errorMessage(error: unknown) {
	return error instanceof Error ? error.message : String(error);
}
