import * as fs from 'fs';
import * as path from 'path';
import type { MatchOptions, MatchResult, ParticipantSpec, PlayerMatchResult } from './match-runner';

export const MATCH_ARTIFACT_SCHEMA_VERSION = 2;

export function prepareMatchArtifactDirectory(outputDirectory: string) {
	const output = path.resolve(outputDirectory);
	if (fs.existsSync(output)) {
		if (!fs.statSync(output).isDirectory()) {
			throw new Error(`Match output path ${JSON.stringify(output)} is not a directory.`);
		}
		if (fs.readdirSync(output).length) throw new Error(`Match output directory ${JSON.stringify(output)} is not empty.`);
	} else {
		fs.mkdirSync(output, { recursive: true });
	}
	return output;
}

export function writeMatchArtifacts(
	outputDirectory: string, result: MatchResult, participants: { p1: ParticipantSpec, p2: ParticipantSpec },
	options: MatchOptions
) {
	const output = path.resolve(outputDirectory);
	const snapshots = path.join(output, 'bot-state-snapshots');
	fs.mkdirSync(snapshots, { recursive: true });

	writeJSON(path.join(output, 'metadata.json'), {
		schema_version: MATCH_ARTIFACT_SCHEMA_VERSION,
		format: result.format,
		seed: result.seed,
		showdown: { version: result.showdown_version, commit: result.showdown_commit },
		participants: {
			p1: publicParticipant(participants.p1),
			p2: publicParticipant(participants.p2),
		},
		runtime: {
			decision_timeout_ms: options.decisionTimeoutMs ?? 5000,
			max_invalid_attempts: options.maxInvalidAttempts ?? 3,
			match_timeout_ms: options.matchTimeoutMs ?? 60_000,
			participants: {
				p1: runtimeAudit(participants.p1),
				p2: runtimeAudit(participants.p2),
			},
		},
		artifacts: {
			result: 'result.json',
			battle_protocol: 'battle.protocol.log',
			p1_runtime: 'p1-runtime.log',
			p2_runtime: 'p2-runtime.log',
			bot_state_snapshots: 'bot-state-snapshots/',
		},
	});
	writeJSON(path.join(output, 'result.json'), {
		schema_version: MATCH_ARTIFACT_SCHEMA_VERSION,
		winner: result.winner,
		winner_side: result.winner_side,
		winner_participant_id: result.winner_participant_id,
		tie: result.tie,
		turns: result.turns,
		players: {
			p1: publicPlayerResult(result.players.p1),
			p2: publicPlayerResult(result.players.p2),
		},
	});
	fs.writeFileSync(path.join(output, 'battle.protocol.log'), `${result.authoritative_log.join('\n')}\n`, 'utf8');
	writeRuntimeLog(path.join(output, 'p1-runtime.log'), result.players.p1);
	writeRuntimeLog(path.join(output, 'p2-runtime.log'), result.players.p2);
	writeJSONLines(path.join(snapshots, 'p1.jsonl'), result.players.p1.states);
	writeJSONLines(path.join(snapshots, 'p2.jsonl'), result.players.p2.states);
}

function publicParticipant(participant: ParticipantSpec) {
	return { id: participant.id || participant.name, name: participant.name };
}

function runtimeAudit(participant: ParticipantSpec) {
	return participant.workerFactory?.audit || {
		kind: 'host',
		trusted: true,
		isolation: 'none',
		warning: 'Trusted development mode; participant code ran directly on the host.',
	};
}

function publicPlayerResult(player: PlayerMatchResult) {
	return {
		stats: player.stats,
		unavailable_choice_revisions: player.unavailable_choice_revisions,
	};
}

function writeRuntimeLog(filepath: string, player: PlayerMatchResult) {
	const entries: object[] = [
		{ type: 'summary', stats: player.stats, unavailable_choice_revisions: player.unavailable_choice_revisions },
		...player.fallback_log.map(entry => ({ type: 'fallback', ...entry })),
		...player.stderr.map(message => ({ type: 'stderr', message })),
	];
	writeJSONLines(filepath, entries);
}

function writeJSON(filepath: string, value: unknown) {
	fs.writeFileSync(filepath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

function writeJSONLines(filepath: string, values: unknown[]) {
	fs.writeFileSync(filepath, values.map(value => JSON.stringify(value)).join('\n') + (values.length ? '\n' : ''), 'utf8');
}
