import * as path from 'path';
import type { PRNGSeed } from '../sim/prng';
import { DEFAULT_FORMAT, MatchRunner } from './match/match-runner';
import { ProtocolStore } from './spectator/protocol-store';
import { SpectatorServer, startReplayServer } from './spectator/server';
import {
	loadSubmission, TOURNAMENT_TEAM_SIZE, type LoadedSubmission,
} from './submissions/submission-loader';

interface ParsedArguments {
	positionals: string[];
	options: Map<string, string>;
}

async function main(argv = process.argv.slice(2)) {
	const [command, ...rest] = argv;
	if (!command || command === '--help' || command === '-h') {
		process.stdout.write(usage());
		return;
	}
	const args = parseArguments(rest);
	const format = args.options.get('format') || DEFAULT_FORMAT;
	if (command === 'validate') {
		if (args.positionals.length !== 1) throw new Error('validate requires exactly one submission directory.\n\n' + usage());
		assertKnownOptions(args, ['format']);
		const submission = loadSubmission(args.positionals[0], { format });
		process.stdout.write(`${JSON.stringify(validationSummary(submission, format), null, 2)}\n`);
		return;
	}
	if (command === 'match') {
		if (args.positionals.length !== 2) {
			throw new Error('match requires exactly two submission directories.\n\n' + usage());
		}
		assertKnownOptions(args, [
			'format', 'seed', 'output', 'decision-timeout-ms', 'max-invalid-attempts', 'match-timeout-ms',
			'spectator-port',
		]);
		const output = requiredOption(args, 'output');
		const seed = parseSeed(args.options.get('seed') || '1,2,3,4');
		const p1 = loadSubmission(args.positionals[0], { format });
		const p2 = loadSubmission(args.positionals[1], { format });
		const spectatorPort = integerOption(args, 'spectator-port');
		const spectatorStore = spectatorPort ? new ProtocolStore({
			metadata: liveMetadata(format, p1, p2),
		}) : null;
		const spectatorServer = spectatorStore ? new SpectatorServer({
			store: spectatorStore,
			mode: 'live',
			port: spectatorPort,
		}) : null;
		if (spectatorServer) {
			await spectatorServer.listen();
			process.stderr.write(`Live spectator: ${spectatorServer.url()}\n`);
		}
		try {
			const result = await new MatchRunner({
				format,
				seed,
				p1: participantSpec(p1),
				p2: participantSpec(p2),
				outputDirectory: output,
				decisionTimeoutMs: integerOption(args, 'decision-timeout-ms'),
				maxInvalidAttempts: integerOption(args, 'max-invalid-attempts'),
				matchTimeoutMs: integerOption(args, 'match-timeout-ms'),
				spectatorSinks: spectatorStore ? [spectatorStore] : [],
			}).run();
			spectatorStore?.setResult(publicResult(result));
			spectatorStore?.markComplete();
			process.stdout.write(`${JSON.stringify({
				winner: result.winner,
				winner_side: result.winner_side,
				winner_participant_id: result.winner_participant_id,
				tie: result.tie,
				turns: result.turns,
				format: result.format,
				seed: result.seed,
				output: path.resolve(output),
			}, null, 2)}\n`);
			if (spectatorServer) await new Promise(resolve => {
				setTimeout(resolve, 1000);
			});
		} finally {
			await spectatorServer?.close();
		}
		return;
	}
	if (command === 'spectate') {
		if (args.positionals.length !== 1) {
			throw new Error('spectate requires exactly one completed match directory.\n\n' + usage());
		}
		assertKnownOptions(args, ['port']);
		const server = await startReplayServer(args.positionals[0], { port: integerOption(args, 'port') ?? 8000 });
		process.stdout.write(`Spectator replay: ${server.url()}\nPress Ctrl+C to stop.\n`);
		await waitForSignal();
		await server.close();
		return;
	}
	throw new Error(`Unknown tournament command ${JSON.stringify(command)}.\n\n${usage()}`);
}

function parseArguments(args: string[]): ParsedArguments {
	const positionals: string[] = [];
	const options = new Map<string, string>();
	for (let index = 0; index < args.length; index++) {
		const arg = args[index];
		if (!arg.startsWith('--')) {
			positionals.push(arg);
			continue;
		}
		const [rawName, inlineValue] = arg.slice(2).split('=', 2);
		const value = inlineValue ?? args[++index];
		if (!rawName || value === undefined || value.startsWith('--')) throw new Error(`Option --${rawName} requires a value.`);
		if (options.has(rawName)) throw new Error(`Option --${rawName} was supplied more than once.`);
		options.set(rawName, value);
	}
	return { positionals, options };
}

function assertKnownOptions(args: ParsedArguments, known: string[]) {
	for (const name of args.options.keys()) {
		if (!known.includes(name)) throw new Error(`Unknown option --${name}.`);
	}
}

function requiredOption(args: ParsedArguments, name: string) {
	const value = args.options.get(name);
	if (!value) throw new Error(`match requires --${name} DIRECTORY.`);
	return value;
}

function integerOption(args: ParsedArguments, name: string) {
	const value = args.options.get(name);
	if (value === undefined) return undefined;
	const parsed = Number(value);
	if (!Number.isSafeInteger(parsed) || parsed <= 0) throw new Error(`--${name} must be a positive integer.`);
	return parsed;
}

function parseSeed(value: string): PRNGSeed {
	if (/^\d+$/.test(value) && validGen5Words([value])) return `${value},0,0,0` as PRNGSeed;
	if (/^(?:\d+,){3}\d+$/.test(value) && validGen5Words(value.split(','))) return value as PRNGSeed;
	if (/^sodium,[0-9a-fA-F]{1,64}$/.test(value) || /^gen5,[0-9a-fA-F]{16}$/.test(value)) {
		return value as PRNGSeed;
	}
	throw new Error(
		'--seed must be an integer from 0 to 65535, four comma-separated 16-bit integers, or a Showdown sodium/gen5 seed.'
	);
}

function validGen5Words(values: string[]) {
	return values.every(value => Number(value) <= 0xFFFF);
}

function participantSpec(submission: LoadedSubmission) {
	return {
		id: submission.id,
		name: submission.name,
		bot: submission.mainPath,
		team: submission.teamText,
	};
}

function validationSummary(submission: LoadedSubmission, format: string) {
	return {
		valid: true,
		id: submission.id,
		name: submission.name,
		directory: submission.directory,
		format,
		team_size: TOURNAMENT_TEAM_SIZE,
		requirements_txt: !!submission.requirementsPath,
	};
}

function liveMetadata(format: string, p1: LoadedSubmission, p2: LoadedSubmission) {
	return {
		schema_version: 1,
		format,
		participants: {
			p1: { id: p1.id, name: p1.name },
			p2: { id: p2.id, name: p2.name },
		},
	};
}

function publicResult(result: Awaited<ReturnType<MatchRunner['run']>>) {
	return {
		winner: result.winner,
		winner_side: result.winner_side,
		winner_participant_id: result.winner_participant_id,
		tie: result.tie,
		turns: result.turns,
	};
}

function waitForSignal() {
	return new Promise<void>(resolve => {
		process.once('SIGINT', () => resolve());
		process.once('SIGTERM', () => resolve());
	});
}

function usage() {
	return [
		'Pokemon Showdown tournament harness',
		'',
		'Usage:',
		'  node dist/tournament/cli.js validate SUBMISSION [--format FORMAT]',
		'  node dist/tournament/cli.js match P1_SUBMISSION P2_SUBMISSION --output DIRECTORY [options]',
		'  node dist/tournament/cli.js spectate MATCH_DIRECTORY [--port PORT]',
		'',
		'Match options:',
		'  --seed SEED                    Integer or Showdown seed (default: 1,2,3,4)',
		'  --format FORMAT                Showdown format ID',
		'  --decision-timeout-ms MS       Per-decision deadline',
		'  --max-invalid-attempts COUNT   Invalid responses before fallback',
		'  --match-timeout-ms MS          Whole-match safety timeout',
		'  --spectator-port PORT          Serve a live read-only viewer during the match',
		'',
	].join('\n');
}

export { main, parseSeed };

if (require.main === module) {
	void main().catch(error => {
		process.stderr.write(`Tournament error: ${error instanceof Error ? error.message : String(error)}\n`);
		process.exitCode = 1;
	});
}
