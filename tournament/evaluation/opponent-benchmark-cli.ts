import * as path from 'path';

import {
	DEFAULT_ANALYSIS_DECISION_TIMEOUT_MS,
	loadOpponentBenchmarkProfiles,
	runOpponentBenchmark,
	type OpponentBenchmarkSuite,
} from './opponent-benchmark';

interface Arguments {
	output: string;
	gamesPerSide: number;
	suites: OpponentBenchmarkSuite[] | null;
	profiles: string[] | null;
	decisionTimeoutMs: number;
	matchTimeoutMs?: number;
	narrowMargin?: number;
}

async function main(argv = process.argv.slice(2)) {
	if (argv.includes('--help') || argv.includes('-h')) {
		process.stdout.write(usage());
		return;
	}
	const args = parseArguments(argv);
	const report = await runOpponentBenchmark({
		outputDirectory: args.output,
		gamesPerSide: args.gamesPerSide,
		suites: args.suites || undefined,
		profileIDs: args.profiles || undefined,
		decisionTimeoutMs: args.decisionTimeoutMs,
		matchTimeoutMs: args.matchTimeoutMs,
		narrowMargin: args.narrowMargin,
	});
	process.stdout.write(`${JSON.stringify({
		completed: true,
		output: path.resolve(args.output),
		match_count: report.base_evaluation.match_count,
		wins: report.base_evaluation.wins,
		losses: report.base_evaluation.losses,
		ties: report.base_evaluation.ties,
		win_rate: report.base_evaluation.win_rate,
		tournament_deadline_exceedances: report.tournament_deadline_exceedances,
		suites: report.suites,
		archetypes: report.archetypes,
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
		'output', 'games-per-side', 'suites', 'profiles', 'decision-timeout-ms', 'match-timeout-ms', 'narrow-margin',
	]);
	for (const key of values.keys()) if (!known.has(key)) throw new Error(`Unknown option --${key}.`);
	const output = values.get('output');
	if (!output) throw new Error(`--output is required.\n\n${usage()}`);
	return {
		output,
		gamesPerSide: positiveInteger(values.get('games-per-side') || '2', 'games-per-side'),
		suites: values.has('suites') ? suiteList(values.get('suites')!) : null,
		profiles: values.has('profiles') ? commaList(values.get('profiles')!, 'profiles') : null,
		decisionTimeoutMs: positiveInteger(
			values.get('decision-timeout-ms') || String(DEFAULT_ANALYSIS_DECISION_TIMEOUT_MS), 'decision-timeout-ms'
		),
		matchTimeoutMs: optionalPositiveInteger(values.get('match-timeout-ms'), 'match-timeout-ms'),
		narrowMargin: optionalNonNegativeNumber(values.get('narrow-margin'), 'narrow-margin'),
	};
}

function suiteList(value: string): OpponentBenchmarkSuite[] {
	const values = commaList(value, 'suites');
	const allowed = new Set<OpponentBenchmarkSuite>(['historical', 'representative', 'stress']);
	const invalid = values.filter(item => !allowed.has(item as OpponentBenchmarkSuite));
	if (invalid.length) throw new Error(`Unknown benchmark suite(s): ${invalid.join(', ')}`);
	return values as OpponentBenchmarkSuite[];
}

function commaList(value: string, name: string) {
	const result = value.split(',').map(item => item.trim()).filter(Boolean);
	if (!result.length) throw new Error(`--${name} must contain at least one value.`);
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

function optionalNonNegativeNumber(value: string | undefined, name: string) {
	if (value === undefined) return undefined;
	const parsed = Number(value);
	if (!Number.isFinite(parsed) || parsed < 0) throw new Error(`--${name} must be non-negative.`);
	return parsed;
}

function usage() {
	const profiles = loadOpponentBenchmarkProfiles();
	return [
		'Deterministic snow representative opponent benchmark',
		'',
		'Usage:',
		'  node dist/tournament/evaluation/opponent-benchmark-cli.js --output DIRECTORY [options]',
		'',
		'Options:',
		'  --games-per-side COUNT       Paired seeds per selected profile and side (default: 2)',
		'  --suites IDS                 historical,representative,stress (default: all)',
		'  --profiles IDS               Comma-separated profile ids (default: all selected suites)',
		`  --decision-timeout-ms MS     Analysis deadline (default: ${DEFAULT_ANALYSIS_DECISION_TIMEOUT_MS})`,
		'  --match-timeout-ms MS        Whole-match safety timeout',
		'  --narrow-margin SCORE        Override review-queue narrow decision threshold',
		'',
		'Available profiles:',
		...profiles.map(profile => `  ${profile.id} [${profile.suite}/${profile.archetype}]`),
		'',
	].join('\n');
}

export { main, parseArguments };

if (require.main === module) {
	void main().catch(error => {
		process.stderr.write(`Opponent benchmark error: ${error instanceof Error ? error.message : String(error)}\n`);
		process.exitCode = 1;
	});
}
