import * as fs from 'fs';
import * as path from 'path';

import {
	runDeterministicSnowV1Evaluation,
	type SnowEvaluationProfile,
	type SnowEvaluationReport,
	type SnowMatchSummary,
} from './deterministic-snow-v1';

export const OPPONENT_BENCHMARK_SCHEMA_VERSION = 1;
export const DEFAULT_ANALYSIS_DECISION_TIMEOUT_MS = 8000;
export const TOURNAMENT_DECISION_BUDGET_MS = 5000;

export type OpponentBenchmarkSuite = 'historical' | 'representative' | 'stress';

export interface OpponentBenchmarkProfile extends SnowEvaluationProfile {
	suite: OpponentBenchmarkSuite;
	archetype: string;
	weight: number;
	tags: string[];
	provenance: string;
}

interface ManifestProfile {
	id: string;
	name: string;
	suite: OpponentBenchmarkSuite;
	archetype: string;
	weight: number;
	team: string;
	tags: string[];
	provenance: string;
}

interface BenchmarkManifest {
	schema_version: number;
	profiles: ManifestProfile[];
}

export interface OpponentBenchmarkOptions {
	outputDirectory: string;
	gamesPerSide: number;
	suites?: OpponentBenchmarkSuite[];
	profileIDs?: string[];
	decisionTimeoutMs?: number;
	matchTimeoutMs?: number;
	narrowMargin?: number;
}

interface GroupSummary {
	profiles: number;
	matches: number;
	wins: number;
	losses: number;
	ties: number;
	win_rate: number | null;
	weighted_match_mass: number;
	weighted_win_mass: number;
	weighted_win_rate: number | null;
}

interface GroupAccumulator {
	profileIDs: Set<string>;
	matches: SnowMatchSummary[];
}

export interface OpponentBenchmarkReport {
	schema_version: number;
	analysis_decision_timeout_ms: number;
	tournament_decision_budget_ms: number;
	tournament_deadline_exceedances: number;
	base_evaluation: SnowEvaluationReport;
	suites: Record<string, GroupSummary>;
	archetypes: Record<string, GroupSummary>;
	profiles: Record<string, {
		name: string,
		suite: OpponentBenchmarkSuite,
		archetype: string,
		weight: number,
		tags: string[],
		provenance: string,
		matches: number,
		wins: number,
		losses: number,
		ties: number,
		win_rate: number | null,
	}>;
}

export function loadOpponentBenchmarkProfiles(root = repositoryRoot()): OpponentBenchmarkProfile[] {
	const benchmarkRoot = path.join(root, 'tournament/evaluation/opponents');
	const manifestPath = path.join(benchmarkRoot, 'manifest.json');
	const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8')) as BenchmarkManifest;
	if (manifest.schema_version !== OPPONENT_BENCHMARK_SCHEMA_VERSION || !Array.isArray(manifest.profiles)) {
		throw new Error(`Opponent benchmark manifest must use schema_version ${OPPONENT_BENCHMARK_SCHEMA_VERSION}.`);
	}
	const ids = new Set<string>();
	return manifest.profiles.map(entry => {
		validateManifestProfile(entry, ids);
		ids.add(entry.id);
		const teamPath = path.resolve(benchmarkRoot, entry.team);
		if (!teamPath.startsWith(`${benchmarkRoot}${path.sep}`) || !fs.existsSync(teamPath)) {
			throw new Error(`Benchmark profile ${entry.id} references missing/out-of-root team ${entry.team}.`);
		}
		return {
			id: entry.id,
			name: entry.name,
			botPath: path.join(benchmarkRoot, 'archetype_bot.py'),
			teamPath,
			suite: entry.suite,
			archetype: entry.archetype,
			weight: entry.weight,
			tags: [...entry.tags],
			provenance: entry.provenance,
		};
	});
}

export async function runOpponentBenchmark(options: OpponentBenchmarkOptions): Promise<OpponentBenchmarkReport> {
	const available = loadOpponentBenchmarkProfiles();
	const profiles = selectProfiles(available, options.suites, options.profileIDs);
	if (!profiles.length) throw new Error('Opponent benchmark selection produced no profiles.');
	const decisionTimeoutMs = options.decisionTimeoutMs ?? DEFAULT_ANALYSIS_DECISION_TIMEOUT_MS;
	const base = await runDeterministicSnowV1Evaluation({
		outputDirectory: options.outputDirectory,
		profiles,
		gamesPerSide: options.gamesPerSide,
		decisionTimeoutMs,
		matchTimeoutMs: options.matchTimeoutMs ?? 120_000,
		narrowMargin: options.narrowMargin,
	});
	const byID = new Map(profiles.map(profile => [profile.id, profile]));
	const report: OpponentBenchmarkReport = {
		schema_version: OPPONENT_BENCHMARK_SCHEMA_VERSION,
		analysis_decision_timeout_ms: decisionTimeoutMs,
		tournament_decision_budget_ms: TOURNAMENT_DECISION_BUDGET_MS,
		tournament_deadline_exceedances: countDeadlineExceedances(
			path.join(options.outputDirectory, 'decisions.jsonl'), TOURNAMENT_DECISION_BUDGET_MS
		),
		base_evaluation: base,
		suites: aggregateGroups(base, byID, profile => profile.suite),
		archetypes: aggregateGroups(base, byID, profile => profile.archetype),
		profiles: Object.fromEntries(profiles.map(profile => {
			const matches = base.matches.filter(match => match.profile_id === profile.id);
			const wins = matches.filter(match => match.outcome === 'win').length;
			const losses = matches.filter(match => match.outcome === 'loss').length;
			const ties = matches.filter(match => match.outcome === 'tie').length;
			return [profile.id, {
				name: profile.name,
				suite: profile.suite,
				archetype: profile.archetype,
				weight: profile.weight,
				tags: [...profile.tags],
				provenance: profile.provenance,
				matches: matches.length,
				wins,
				losses,
				ties,
				win_rate: matches.length ? wins / matches.length : null,
			}];
		})),
	};
	fs.writeFileSync(
		path.join(options.outputDirectory, 'benchmark-summary.json'),
		`${JSON.stringify(report, null, 2)}\n`,
		'utf8'
	);
	return report;
}

export function selectProfiles(
	profiles: OpponentBenchmarkProfile[],
	suites?: OpponentBenchmarkSuite[],
	profileIDs?: string[]
) {
	const suiteSet = suites?.length ? new Set(suites) : null;
	const profileSet = profileIDs?.length ? new Set(profileIDs) : null;
	if (profileSet) {
		const known = new Set(profiles.map(profile => profile.id));
		const unknown = [...profileSet].filter(id => !known.has(id));
		if (unknown.length) throw new Error(`Unknown benchmark profile(s): ${unknown.join(', ')}`);
	}
	return profiles.filter(profile =>
		(!suiteSet || suiteSet.has(profile.suite)) && (!profileSet || profileSet.has(profile.id))
	);
}

function validateManifestProfile(entry: ManifestProfile, ids: Set<string>) {
	if (!entry || typeof entry !== 'object') throw new Error('Benchmark manifest profiles must be objects.');
	for (const field of ['id', 'name', 'archetype', 'team', 'provenance'] as const) {
		if (typeof entry[field] !== 'string' || !entry[field].trim()) {
			throw new Error(`Benchmark profile has invalid ${field}.`);
		}
	}
	if (ids.has(entry.id)) throw new Error(`Duplicate benchmark profile id ${entry.id}.`);
	if (!['historical', 'representative', 'stress'].includes(entry.suite)) {
		throw new Error(`Benchmark profile ${entry.id} has invalid suite ${entry.suite}.`);
	}
	if (!Number.isFinite(entry.weight) || entry.weight <= 0) {
		throw new Error(`Benchmark profile ${entry.id} weight must be positive and finite.`);
	}
	if (!Array.isArray(entry.tags) || entry.tags.some(tag => typeof tag !== 'string' || !tag)) {
		throw new Error(`Benchmark profile ${entry.id} tags must be non-empty strings.`);
	}
}

function aggregateGroups(
	report: SnowEvaluationReport,
	profiles: Map<string, OpponentBenchmarkProfile>,
	key: (profile: OpponentBenchmarkProfile) => string
): Record<string, GroupSummary> {
	const groups = new Map<string, GroupAccumulator>();
	for (const match of report.matches) {
		const profile = profiles.get(match.profile_id);
		if (!profile) throw new Error(`Evaluation returned unknown benchmark profile ${match.profile_id}.`);
		const groupID = key(profile);
		const group: GroupAccumulator = groups.get(groupID) || { profileIDs: new Set<string>(), matches: [] };
		group.profileIDs.add(profile.id);
		group.matches.push(match);
		groups.set(groupID, group);
	}
	return Object.fromEntries([...groups.entries()].sort().map(([groupID, group]) => {
		let weightedMatchMass = 0;
		let weightedWinMass = 0;
		for (const match of group.matches) {
			const profile = profiles.get(match.profile_id)!;
			weightedMatchMass += profile.weight;
			if (match.outcome === 'win') weightedWinMass += profile.weight;
		}
		const wins = group.matches.filter(match => match.outcome === 'win').length;
		const losses = group.matches.filter(match => match.outcome === 'loss').length;
		const ties = group.matches.filter(match => match.outcome === 'tie').length;
		return [groupID, {
			profiles: group.profileIDs.size,
			matches: group.matches.length,
			wins,
			losses,
			ties,
			win_rate: group.matches.length ? wins / group.matches.length : null,
			weighted_match_mass: weightedMatchMass,
			weighted_win_mass: weightedWinMass,
			weighted_win_rate: weightedMatchMass ? weightedWinMass / weightedMatchMass : null,
		}];
	}));
}

function countDeadlineExceedances(decisionsPath: string, budgetMs: number) {
	if (!fs.existsSync(decisionsPath)) return 0;
	return fs.readFileSync(decisionsPath, 'utf8').split(/\r?\n/).filter(Boolean).reduce((count, line) => {
		const decision = JSON.parse(line) as { latency_ms?: unknown };
		return count + (typeof decision.latency_ms === 'number' && decision.latency_ms > budgetMs ? 1 : 0);
	}, 0);
}

function repositoryRoot() {
	return path.resolve(__dirname, '../../..');
}
