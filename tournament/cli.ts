import * as path from 'path';
import type { PRNGSeed } from '../sim/prng';
import { HostPythonWorkerFactory } from './bots/python-worker';
import type { BotWorkerFactory } from './bots/worker-interface';
import { DEFAULT_FORMAT, MatchRunner } from './match/match-runner';
import {
	DEFAULT_MAX_SUBMISSION_BYTES, DEFAULT_MAX_SUBMISSION_FILES, DockerImagePreparer,
	type ImagePreparerOptions,
} from './sandbox/image-preparer';
import { DEFAULT_DOCKER_RESOURCE_POLICY, type DockerResourcePolicy } from './sandbox/policy';
import { ProtocolStore } from './spectator/protocol-store';
import { SpectatorServer, startReplayServer } from './spectator/server';
import { TournamentEventStore, TOURNAMENT_EVENT_SCHEMA_VERSION } from './spectator/event-store';
import { TournamentEventServer } from './spectator/event-server';
import { publicTeamSheets } from './spectator/public-team-sheet';
import { loadTournamentConfig } from './orchestrator/config';
import { TournamentOrchestrator } from './orchestrator/orchestrator';
import { TournamentPacingController } from './orchestrator/pacing';
import { DEFAULT_PLAYBACK_TIMEOUT_MS, TournamentPlaybackController } from './orchestrator/playback';
import { runTournamentPreflight } from './orchestrator/preflight';
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
	if (command === 'preflight' || command === 'tournament') {
		if (args.positionals.length !== 1) {
			throw new Error(`${command} requires exactly one tournament config file.\n\n${usage()}`);
		}
		assertKnownOptions(args, [
			'output', 'spectator-port', 'auto-advance', 'allow-renderer-unreachable',
			'playback-timeout-ms',
			'build-timeout-ms', 'container-memory-mb', 'container-cpus', 'container-pids',
			'container-tmpfs-mb', 'container-nofile', 'submission-max-bytes', 'submission-max-files',
		]);
		if (command === 'preflight' && args.options.has('auto-advance')) {
			throw new Error('--auto-advance applies only to the tournament command.');
		}
		const output = requiredOption(args, 'output', command);
		const spectatorPort = requiredIntegerOption(args, 'spectator-port');
		const config = loadTournamentConfig(args.positionals[0]);
		const preflight = await runTournamentPreflight({
			config,
			outputDirectory: output,
			spectatorPort,
			allowRendererUnreachable: booleanOption(args, 'allow-renderer-unreachable'),
			imagePreparerOptions: dockerPreparerOptions(args),
		});
		const summary = {
			ready: preflight.ready,
			config_hash: preflight.config_hash,
			runtime: preflight.runtime,
			participants: preflight.participants,
			renderer: preflight.renderer,
			warnings: preflight.warnings,
			output: path.resolve(output),
			spectator_port: spectatorPort,
		};
		if (command === 'preflight') {
			process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
			return;
		}
		for (const warning of preflight.warnings) process.stderr.write(`WARNING: ${warning}\n`);
		const eventStore = new TournamentEventStore({
			schema_version: TOURNAMENT_EVENT_SCHEMA_VERSION,
			kind: 'idle',
			title: config.config.title,
			subtitle: config.config.subtitle,
			message: 'Tournament ready',
		}, path.join(path.resolve(output), 'event.log.jsonl'));
		const autoAdvance = booleanOption(args, 'auto-advance');
		const pacing = new TournamentPacingController(eventStore, autoAdvance);
		const playback = new TournamentPlaybackController({
			autoComplete: autoAdvance,
			timeoutMs: integerOption(args, 'playback-timeout-ms') ?? DEFAULT_PLAYBACK_TIMEOUT_MS,
		});
		const teams = publicTeamSheets(preflight.prepared);
		const server = new TournamentEventServer({ store: eventStore, pacing, playback, teams, port: spectatorPort });
		await server.listen();
		process.stderr.write(`Tournament spectator: ${server.url()}\nOperator controls: ${server.url()}operator\n`);
		try {
			const result = await new TournamentOrchestrator({
				config,
				outputDirectory: output,
				participants: preflight.prepared,
				eventStore,
				pacing,
				playback,
				publicTeams: teams,
			}).run();
			process.stdout.write(`${JSON.stringify({ ...summary, ...result }, null, 2)}\n`);
			if (!autoAdvance) await waitForSignal();
		} finally {
			await server.close();
		}
		return;
	}
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
			'spectator-port', 'runtime', 'build-timeout-ms', 'container-memory-mb', 'container-cpus',
			'container-pids', 'container-tmpfs-mb', 'container-nofile', 'submission-max-bytes',
			'submission-max-files',
		]);
		const output = requiredOption(args, 'output', 'match');
		const seed = parseSeed(args.options.get('seed') || '1,2,3,4');
		const p1 = loadSubmission(args.positionals[0], { format });
		const p2 = loadSubmission(args.positionals[1], { format });
		const runtime = args.options.get('runtime') || 'docker';
		if (runtime !== 'docker' && runtime !== 'host') throw new Error('--runtime must be either docker or host.');
		let p1WorkerFactory: BotWorkerFactory;
		let p2WorkerFactory: BotWorkerFactory;
		if (runtime === 'docker') {
			const preparer = dockerPreparer(args);
			p1WorkerFactory = (await preparer.prepare(p1)).workerFactory;
			p2WorkerFactory = (await preparer.prepare(p2)).workerFactory;
		} else {
			process.stderr.write('WARNING: --runtime host executes trusted participant code directly on this machine without isolation.\n');
			p1WorkerFactory = new HostPythonWorkerFactory();
			p2WorkerFactory = new HostPythonWorkerFactory();
		}
		const spectatorPort = integerOption(args, 'spectator-port');
		let spectatorStore: ProtocolStore | null = null;
		let spectatorServer: SpectatorServer | null = null;
		if (spectatorPort) {
			const store = new ProtocolStore({ metadata: liveMetadata(format, p1, p2) });
			const server = new SpectatorServer({ store, mode: 'live', port: spectatorPort });
			try {
				await server.listen();
				spectatorStore = store;
				spectatorServer = server;
				process.stderr.write(`Live spectator: ${server.url()}\n`);
			} catch (error) {
				process.stderr.write(
					`Live spectator unavailable: ${error instanceof Error ? error.message : error}. ` +
					`Continuing match without live spectator.\n`
				);
			}
		}
		try {
			const result = await new MatchRunner({
				format,
				seed,
				p1: participantSpec(p1, p1WorkerFactory),
				p2: participantSpec(p2, p2WorkerFactory),
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
				runtime,
			}, null, 2)}\n`);
			if (spectatorServer) await new Promise(resolve => {
				setTimeout(resolve, 1000);
			});
		} finally {
			await spectatorServer?.close();
		}
		return;
	}
	if (command === 'prepare') {
		if (args.positionals.length !== 1) throw new Error('prepare requires exactly one submission directory.\n\n' + usage());
		assertKnownOptions(args, [
			'format', 'build-timeout-ms', 'container-memory-mb', 'container-cpus', 'container-pids',
			'container-tmpfs-mb', 'container-nofile', 'submission-max-bytes', 'submission-max-files',
		]);
		const submission = loadSubmission(args.positionals[0], { format });
		const prepared = await dockerPreparer(args).prepare(submission);
		process.stdout.write(`${JSON.stringify({
			prepared: true,
			id: submission.id,
			name: submission.name,
			content_hash: prepared.contentHash,
			image_id: prepared.imageID,
			runtime_image_id: prepared.runtimeImageID,
			base_image_id: prepared.baseImageID,
			cached: prepared.cached,
			runtime: prepared.workerFactory.audit,
		}, null, 2)}\n`);
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
		let value = inlineValue;
		if (value === undefined && BOOLEAN_OPTIONS.has(rawName)) value = 'true';
		if (value === undefined) value = args[++index];
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

function requiredOption(args: ParsedArguments, name: string, command: string) {
	const value = args.options.get(name);
	if (!value) throw new Error(`${command} requires --${name}.`);
	return value;
}

function requiredIntegerOption(args: ParsedArguments, name: string) {
	const value = integerOption(args, name);
	if (value === undefined) throw new Error(`--${name} is required.`);
	return value;
}

function booleanOption(args: ParsedArguments, name: string) {
	const value = args.options.get(name);
	if (value === undefined) return false;
	if (value !== 'true' && value !== 'false') {
		throw new Error(`--${name} must be true or false when given a value.`);
	}
	return value === 'true';
}

function integerOption(args: ParsedArguments, name: string) {
	const value = args.options.get(name);
	if (value === undefined) return undefined;
	const parsed = Number(value);
	if (!Number.isSafeInteger(parsed) || parsed <= 0) throw new Error(`--${name} must be a positive integer.`);
	return parsed;
}

const BOOLEAN_OPTIONS = new Set(['auto-advance', 'allow-renderer-unreachable']);

function numberOption(args: ParsedArguments, name: string) {
	const value = args.options.get(name);
	if (value === undefined) return undefined;
	const parsed = Number(value);
	if (!Number.isFinite(parsed) || parsed <= 0) throw new Error(`--${name} must be a positive number.`);
	return parsed;
}

function dockerPreparer(args: ParsedArguments) {
	return new DockerImagePreparer(dockerPreparerOptions(args));
}

function dockerPreparerOptions(args: ParsedArguments): ImagePreparerOptions {
	const resourcePolicy: DockerResourcePolicy = {
		memoryMB: integerOption(args, 'container-memory-mb') ?? DEFAULT_DOCKER_RESOURCE_POLICY.memoryMB,
		cpus: numberOption(args, 'container-cpus') ?? DEFAULT_DOCKER_RESOURCE_POLICY.cpus,
		pids: integerOption(args, 'container-pids') ?? DEFAULT_DOCKER_RESOURCE_POLICY.pids,
		tmpfsMB: integerOption(args, 'container-tmpfs-mb') ?? DEFAULT_DOCKER_RESOURCE_POLICY.tmpfsMB,
		nofile: integerOption(args, 'container-nofile') ?? DEFAULT_DOCKER_RESOURCE_POLICY.nofile,
	};
	return {
		buildTimeoutMs: integerOption(args, 'build-timeout-ms'),
		resourcePolicy,
		submissionLimits: {
			maxBytes: integerOption(args, 'submission-max-bytes') ?? DEFAULT_MAX_SUBMISSION_BYTES,
			maxFiles: integerOption(args, 'submission-max-files') ?? DEFAULT_MAX_SUBMISSION_FILES,
		},
	};
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

function participantSpec(submission: LoadedSubmission, workerFactory: BotWorkerFactory) {
	return {
		id: submission.id,
		name: submission.name,
		bot: submission.mainPath,
		team: submission.teamText,
		workerFactory,
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
		'  node dist/tournament/cli.js preflight CONFIG --output DIRECTORY --spectator-port PORT [options]',
		'  node dist/tournament/cli.js tournament CONFIG --output DIRECTORY --spectator-port PORT [options]',
		'  node dist/tournament/cli.js validate SUBMISSION [--format FORMAT]',
		'  node dist/tournament/cli.js prepare SUBMISSION [options]',
		'  node dist/tournament/cli.js match P1_SUBMISSION P2_SUBMISSION --output DIRECTORY [options]',
		'  node dist/tournament/cli.js spectate MATCH_DIRECTORY [--port PORT]',
		'',
		'Tournament options:',
		'  --auto-advance                 Advance presentation states automatically (tests/demos)',
		'  --playback-timeout-ms MS       Missing-spectator fallback timeout (default: 300000)',
		'  --allow-renderer-unreachable  Explicitly rehearse despite failed hosted-renderer preflight',
		'',
		'Match options:',
		'  --runtime docker|host           Docker isolation (default); host is trusted/unsafe',
		'  --seed SEED                    Integer or Showdown seed (default: 1,2,3,4)',
		'  --format FORMAT                Showdown format ID',
		'  --decision-timeout-ms MS       Per-decision deadline',
		'  --max-invalid-attempts COUNT   Invalid responses before fallback',
		'  --match-timeout-ms MS          Whole-match safety timeout',
		'  --spectator-port PORT          Serve a live read-only viewer during the match',
		'  --build-timeout-ms MS          Participant image preparation timeout (default: 300000)',
		'  --container-memory-mb MB       Memory and total memory+swap limit (default: 512)',
		'  --container-cpus COUNT         CPU quota (default: 1)',
		'  --container-pids COUNT         Process limit (default: 64)',
		'  --container-tmpfs-mb MB        Writable /tmp limit (default: 64)',
		'  --container-nofile COUNT       File descriptor soft/hard limit (default: 256)',
		'  --submission-max-bytes BYTES   Total submission size limit (default: 1073741824)',
		'  --submission-max-files COUNT   Submission file-count limit (default: 10000)',
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
