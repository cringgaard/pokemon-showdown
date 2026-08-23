import * as path from 'path';

import {
	DEFAULT_NARROW_MARGIN,
	defaultSnowEvaluationProfiles,
	runDeterministicSnowV1Evaluation,
} from './deterministic-snow-v1';

interface Arguments {
	output: string;
	gamesPerSide: number;
	profiles: string[] | null;
	decisionTimeoutMs?: number;
	matchTimeoutMs?: number;
	narrowMargin: number;
}

async function main(argv = process.argv.slice(2)) {
	if (argv.includes('--help') || argv.includes('-h')) {
		process.stdout.write(usage());
		return;
	}
	const args = parseArguments(argv);
	const available = defaultSnowEvaluationProfiles();
	const selected = args.profiles ? available.filter(profile => args.profiles!.includes(profile.id)) : available;
	if (args.profiles) {
		const known = new Set(available.map(profile => profile.id));
		const unknown = args.profiles.filter(profile => !known.has(profile));
		if (unknown.length) throw new Error(`Unknown evaluation profile(s): ${unknown.join(', ')}`);
	}
	const report = await runDeterministicSnowV1Evaluation({
		outputDirectory: args.output,
		profiles: selected,
		gamesPerSide: args.gamesPerSide,
		decisionTimeoutMs: args.decisionTimeoutMs,
		matchTimeoutMs: args.matchTimeoutMs,
		narrowMargin: args.narrowMargin,
	});
	process.stdout.write(`${JSON.stringify({
		completed: true,
		output: path.resolve(args.output),
		match_count: report.match_count,
		wins: report.wins,
		losses: report.losses,
		ties: report.ties,
		win_rate: report.win_rate,
		trace_coverage: report.trace_coverage,
		latency_ms: report.latency_ms,
	}, null, 2)}\n`);
}

function parseArguments(argv: string[]): Arguments {
	const values = new Map<string, string>();
	for (let index = 0; index < argv.length; index++) {
		const arg = argv[index];
		if (!arg.startsWith('--')) throw new Error(`Unexpected positional argument ${JSON.stringify(arg)}.\n\n${usage()}`);
		const [name, inline] = arg.slice(2).split('=', 2);
		const value = inline === undefined ? argv[++index] : inline;
		if (!name || value === undefined || value.startsWith('--')) throw new Error(`Option --${name} requires a value.`);
		if (values.has(name)) throw new Error(`Option --${name} was supplied more than once.`);
		values.set(name, value);
	}
	const known = new Set([
		'output', 'games-per-side', 'profiles', 'decision-timeout-ms', 'match-timeout-ms', 'narrow-margin',
	]);
	for (const key of values.keys()) if (!known.has(key)) throw new Error(`Unknown option --${key}.`);
	const output = values.get('output');
	if (!output) throw new Error(`--output is required.\n\n${usage()}`);
	return {
		output,
		gamesPerSide: positiveInteger(values.get('games-per-side') || '4', 'games-per-side'),
		profiles: values.has('profiles') ? commaList(values.get('profiles')!) : null,
		decisionTimeoutMs: optionalPositiveInteger(values.get('decision-timeout-ms'), 'decision-timeout-ms'),
		matchTimeoutMs: optionalPositiveInteger(values.get('match-timeout-ms'), 'match-timeout-ms'),
		narrowMargin: nonNegativeNumber(values.get('narrow-margin') || String(DEFAULT_NARROW_MARGIN), 'narrow-margin'),
	};
}

function commaList(value: string) {
	const result = value.split(',').map(item => item.trim()).filter(Boolean);
	if (!result.length) throw new Error('--profiles must contain at least one profile id.');
	return [...new Set(result)];
}

function positiveInteger(value: string, name: string) {
	const parsed = Number(value);
	if (!Number.isSafeInteger(parsed) || parsed <= 0) throw new Error(`--${name} must be a positive integer.`);
	return parsed;
}

function optionalPositiveInteger(value: string | undefined, name: string) {
	return value === undefined ? undefined : positiveInteger(value, name);
}

function nonNegativeNumber(value: string, name: string) {
	const parsed = Number(value);
	if (!Number.isFinite(parsed) || parsed < 0) throw new Error(`--${name} must be a non-negative number.`);
	return parsed;
}

function usage() {
	return [
		'Deterministic snow v1 post-acceptance evaluation',
		'',
		'Usage:',
		'  node dist/tournament/evaluation/deterministic-snow-v1-cli.js --output DIRECTORY [options]',
		'',
		'Options:',
		'  --games-per-side COUNT       Paired seeds per profile and side (default: 4)',
		'  --profiles IDS               Comma-separated profile ids (default: all)',
		'  --decision-timeout-ms MS     Per-decision MatchRunner deadline',
		'  --match-timeout-ms MS        Whole-match safety timeout',
		'  --narrow-margin SCORE        Review-queue narrow decision cutoff (default: 20)',
		'',
		'Default profiles:',
		'  greedy-mirror, random-mirror',
		'',
	].join('\n');
}

export { main, parseArguments };

if (require.main === module) {
	void main().catch(error => {
		process.stderr.write(`Snow evaluation error: ${error instanceof Error ? error.message : String(error)}\n`);
		process.exitCode = 1;
	});
}
