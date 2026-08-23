import { execFileSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

import type { PRNGSeed } from '../../sim/prng';
import { DEFAULT_FORMAT, MatchRunner, type MatchResult, type ParticipantSpec } from '../match/match-runner';
import { writeChampionsMechanicsSnapshot } from '../mechanics/champions-snapshot';

export const SNOW_EVALUATION_SCHEMA_VERSION = 1;
export const SNOW_TRACE_FILE_ENV = 'DETERMINISTIC_SNOW_TRACE_FILE';
export const SNOW_TRACE_STDERR_ENV = 'DETERMINISTIC_SNOW_TRACE_STDERR';
export const SNOW_MECHANICS_PATH_ENV = 'DETERMINISTIC_SNOW_MECHANICS_PATH';
export const DEFAULT_NARROW_MARGIN = 20;

export interface SnowEvaluationProfile {
	id: string;
	name: string;
	botPath: string;
	teamPath: string;
}

export interface SnowEvaluationOptions {
	outputDirectory: string;
	profiles: SnowEvaluationProfile[];
	gamesPerSide: number;
	format?: string;
	decisionTimeoutMs?: number;
	matchTimeoutMs?: number;
	maxInvalidAttempts?: number;
	narrowMargin?: number;
}

interface TraceFeatureContribution {
	feature_id: string;
	value: number;
	weight: number;
	contribution: number;
}

interface TraceCandidate {
	action: {
		action_id: string;
		payload: Record<string, unknown>;
	};
	expected_score: number | null;
	credible_bad_case_score: number | null;
	best_case_score: number | null;
	final_score: number | null;
	feature_contributions: TraceFeatureContribution[];
	tactical_adjustments: Array<{ rule_id: string, adjustment: number, reason: string }>;
}

export interface SnowDecisionTrace {
	schema_version: number;
	level: string;
	decision_id: number;
	turn: number;
	versions: Record<string, string>;
	strategy: null | {
		glaceon_fortress: number;
		aggron_fortress: number;
		tactical_offense: number;
		primary_plan: string | null;
	};
	major_threats: string[];
	opponent_responses: Array<{ id: string, weight: number, reasons: string[], actions: string[] }>;
	candidates: TraceCandidate[];
	selected_action_id: string | null;
	runtime: {
		latency_ms: number;
		candidate_count: number;
		response_count: number;
		evaluation_count: number;
	};
}

export interface SnowDecisionSummary {
	match_id: string;
	profile_id: string;
	snow_side: 'p1' | 'p2';
	decision_id: number;
	turn: number;
	phase: string;
	selected_action_id: string | null;
	selected_action: Record<string, unknown> | null;
	selected_score: number | null;
	score_margin: number | null;
	top_alternatives: Array<{
		action_id: string;
		action: Record<string, unknown>;
		score: number | null;
	}>;
	primary_plan: string | null;
	strategy_scores: SnowDecisionTrace['strategy'];
	major_threats: string[];
	response_count: number;
	candidate_count: number;
	evaluation_count: number;
	latency_ms: number;
	mechanic_uncertainty: number;
	rng_dependence: number;
	fragile_prediction: number;
	selected_feature_contributions: TraceFeatureContribution[];
	tactical_adjustments: TraceCandidate['tactical_adjustments'];
}

export interface SnowMatchSummary {
	match_id: string;
	profile_id: string;
	profile_name: string;
	seed: PRNGSeed;
	snow_side: 'p1' | 'p2';
	outcome: 'win' | 'loss' | 'tie';
	turns: number;
	trace_count: number;
	decision_count: number;
	preview_team: unknown[] | null;
	preview_leads: unknown[] | null;
	primary_plan_counts: Record<string, number>;
	mean_score_margin: number | null;
	minimum_score_margin: number | null;
	mean_latency_ms: number | null;
	max_latency_ms: number | null;
	runtime_stats: MatchResult['players']['p1']['stats'];
	unavailable_choice_revisions: number;
	artifact_directory: string;
	trace_file: string;
}

export interface SnowEvaluationReport {
	schema_version: number;
	format: string;
	showdown_commit: string | null;
	mechanics_snapshot_hash: string;
	games_per_side: number;
	match_count: number;
	wins: number;
	losses: number;
	ties: number;
	win_rate: number | null;
	average_turns: number | null;
	trace_coverage: {
		traces: number;
		decisions: number;
		ratio: number | null;
	};
	latency_ms: DistributionSummary;
	score_margin: DistributionSummary;
	primary_plan_counts: Record<string, number>;
	selected_feature_contributions: Record<string, { count: number, mean_value: number, mean_contribution: number }>;
	profiles: Record<string, {
		matches: number;
		wins: number;
		losses: number;
		ties: number;
		win_rate: number | null;
	}>;
	matches: SnowMatchSummary[];
}

export interface DistributionSummary {
	count: number;
	mean: number | null;
	p50: number | null;
	p95: number | null;
	min: number | null;
	max: number | null;
}

interface ScheduledMatch {
	id: string;
	profile: SnowEvaluationProfile;
	seed: PRNGSeed;
	snowSide: 'p1' | 'p2';
}

export async function runDeterministicSnowV1Evaluation(options: SnowEvaluationOptions): Promise<SnowEvaluationReport> {
	validateOptions(options);
	const format = options.format || DEFAULT_FORMAT;
	const output = prepareOutputDirectory(options.outputDirectory);
	const root = repositoryRoot();
	const mechanicsPath = path.join(output, 'champions-mechanics.json');
	const mechanics = writeChampionsMechanicsSnapshot(mechanicsPath, format, currentCommit());
	const snowTeamPath = path.join(root, 'tournament/fixtures/teams/champions-snow.txt');
	const snowBotPath = path.join(root, 'tournament/policies/deterministic_snow/participant.py');
	const snowTeam = fs.readFileSync(snowTeamPath, 'utf8');
	const schedule = buildSchedule(options.profiles, options.gamesPerSide);
	const matchSummaries: SnowMatchSummary[] = [];
	const decisionSummaries: SnowDecisionSummary[] = [];

	for (const scheduled of schedule) {
		const matchDirectory = path.join(output, 'matches', scheduled.id);
		const traceFile = path.join(matchDirectory, 'snow-decision-traces.jsonl');
		const opponentTeam = fs.readFileSync(scheduled.profile.teamPath, 'utf8');
		const snow: ParticipantSpec = {
			id: 'deterministic-snow-v1', name: 'Deterministic Snow v1', bot: snowBotPath, team: snowTeam,
		};
		const opponent: ParticipantSpec = {
			id: scheduled.profile.id,
			name: scheduled.profile.name,
			bot: scheduled.profile.botPath,
			team: opponentTeam,
		};
		const p1 = scheduled.snowSide === 'p1' ? snow : opponent;
		const p2 = scheduled.snowSide === 'p2' ? snow : opponent;
		const result = await withSnowEnvironment({
			[SNOW_MECHANICS_PATH_ENV]: mechanicsPath,
			[SNOW_TRACE_FILE_ENV]: traceFile,
			[SNOW_TRACE_STDERR_ENV]: undefined,
		}, async () => new MatchRunner({
			format,
			seed: scheduled.seed,
			p1,
			p2,
			outputDirectory: matchDirectory,
			decisionTimeoutMs: options.decisionTimeoutMs,
			maxInvalidAttempts: options.maxInvalidAttempts,
			matchTimeoutMs: options.matchTimeoutMs,
		}).run());
		const snowPlayer = result.players[scheduled.snowSide];
		assertHealthySnowRuntime(scheduled.id, snowPlayer);
		const traces = readSnowDecisionTraces(traceFile);
		if (traces.length !== snowPlayer.stats.decisions) {
			throw new Error(
				`${scheduled.id} produced ${traces.length} snow traces for ${snowPlayer.stats.decisions} decisions.`
			);
		}
		const states = snowPlayer.states;
		const summaries = traces.map(trace => summarizeDecision(
			scheduled.id, scheduled.profile.id, scheduled.snowSide, trace, states
		));
		decisionSummaries.push(...summaries);
		matchSummaries.push(summarizeMatch(scheduled, result, traces, summaries, matchDirectory, traceFile));
	}

	const report = aggregateReport(
		format, currentCommit(), mechanics.snapshot_hash, options.gamesPerSide, matchSummaries, decisionSummaries
	);
	writeJSON(path.join(output, 'summary.json'), report);
	writeJSONLines(path.join(output, 'decisions.jsonl'), decisionSummaries);
	writeJSON(path.join(output, 'review-queue.json'), buildReviewQueue(matchSummaries, decisionSummaries, options.narrowMargin));
	writeJSON(path.join(output, 'metadata.json'), {
		schema_version: SNOW_EVALUATION_SCHEMA_VERSION,
		format,
		showdown_commit: currentCommit(),
		mechanics_snapshot_hash: mechanics.snapshot_hash,
		games_per_side: options.gamesPerSide,
		profiles: options.profiles.map(profile => ({ id: profile.id, name: profile.name })),
		artifacts: {
			summary: 'summary.json',
			decisions: 'decisions.jsonl',
			review_queue: 'review-queue.json',
			matches: 'matches/',
			mechanics: 'champions-mechanics.json',
		},
	});
	return report;
}

export function defaultSnowEvaluationProfiles(root = repositoryRoot()): SnowEvaluationProfile[] {
	const teamPath = path.join(root, 'tournament/fixtures/teams/champions-snow.txt');
	return [
		{
			id: 'greedy-mirror',
			name: 'Greedy Mirror',
			botPath: path.join(root, 'tournament/reference-bots/greedy-damage/main.py'),
			teamPath,
		},
		{
			id: 'random-mirror',
			name: 'Random Mirror',
			botPath: path.join(root, 'tournament/reference-bots/random/main.py'),
			teamPath,
		},
	];
}

export function buildSchedule(profiles: SnowEvaluationProfile[], gamesPerSide: number): ScheduledMatch[] {
	const result: ScheduledMatch[] = [];
	for (let profileIndex = 0; profileIndex < profiles.length; profileIndex++) {
		const profile = profiles[profileIndex];
		for (let game = 0; game < gamesPerSide; game++) {
			const seed = evaluationSeed(profileIndex, game);
			result.push({ id: `${profile.id}-${game + 1}-snow-p1`, profile, seed, snowSide: 'p1' });
			result.push({ id: `${profile.id}-${game + 1}-snow-p2`, profile, seed, snowSide: 'p2' });
		}
	}
	return result;
}

export function evaluationSeed(profileIndex: number, gameIndex: number): PRNGSeed {
	const n = profileIndex * 4099 + gameIndex * 997 + 1;
	const word = (offset: number) => (n * offset + offset * offset * 101) & 0xFFFF;
	return `${word(17)},${word(31)},${word(47)},${word(61)}` as PRNGSeed;
}

export function readSnowDecisionTraces(traceFile: string): SnowDecisionTrace[] {
	if (!fs.existsSync(traceFile)) return [];
	const lines = fs.readFileSync(traceFile, 'utf8').split(/\r?\n/).filter(Boolean);
	return lines.map((line, index) => {
		let value: unknown;
		try {
			value = JSON.parse(line);
		} catch (error) {
			throw new Error(`Invalid snow trace JSON at ${traceFile}:${index + 1}: ${error}`);
		}
		assertDecisionTrace(value, `${traceFile}:${index + 1}`);
		return value;
	});
}

export function summarizeDecision(
	matchID: string,
	profileID: string,
	snowSide: 'p1' | 'p2',
	trace: SnowDecisionTrace,
	states: MatchResult['players']['p1']['states'] = []
): SnowDecisionSummary {
	const selected = trace.candidates.find(candidate => candidate.action.action_id === trace.selected_action_id) || null;
	const alternatives = trace.candidates
		.filter(candidate => candidate.action.action_id !== trace.selected_action_id)
		.slice()
		.sort((left, right) => nullableScore(right.final_score) - nullableScore(left.final_score));
	const selectedScore = selected?.final_score ?? null;
	const alternativeScore = alternatives.length ? alternatives[0].final_score : null;
	const margin = selectedScore !== null && alternativeScore !== null ? selectedScore - alternativeScore : null;
	const state = states.find(item => item.runtime.decision_id === trace.decision_id);
	const features = selected?.feature_contributions || [];
	return {
		match_id: matchID,
		profile_id: profileID,
		snow_side: snowSide,
		decision_id: trace.decision_id,
		turn: trace.turn,
		phase: state?.battle.phase || inferTracePhase(trace),
		selected_action_id: trace.selected_action_id,
		selected_action: selected?.action.payload || null,
		selected_score: selectedScore,
		score_margin: margin,
		top_alternatives: alternatives.slice(0, 3).map(candidate => ({
			action_id: candidate.action.action_id,
			action: candidate.action.payload,
			score: candidate.final_score,
		})),
		primary_plan: trace.strategy?.primary_plan || null,
		strategy_scores: trace.strategy,
		major_threats: [...trace.major_threats],
		response_count: trace.runtime.response_count,
		candidate_count: trace.runtime.candidate_count,
		evaluation_count: trace.runtime.evaluation_count,
		latency_ms: trace.runtime.latency_ms,
		mechanic_uncertainty: featureValue(features, 'MECHANIC_UNCERTAINTY'),
		rng_dependence: featureValue(features, 'RNG_DEPENDENCE'),
		fragile_prediction: featureValue(features, 'FRAGILE_PREDICTION'),
		selected_feature_contributions: features,
		tactical_adjustments: selected?.tactical_adjustments || [],
	};
}

function summarizeMatch(
	scheduled: ScheduledMatch,
	result: MatchResult,
	traces: SnowDecisionTrace[],
	decisions: SnowDecisionSummary[],
	matchDirectory: string,
	traceFile: string
): SnowMatchSummary {
	const snowPlayer = result.players[scheduled.snowSide];
	const preview = decisions.find(decision => decision.phase === 'team_preview');
	const previewTeam = preview?.selected_action && Array.isArray(preview.selected_action.team) ? preview.selected_action.team : null;
	const margins = decisions.map(decision => decision.score_margin).filter(isNumber);
	const latencies = decisions.map(decision => decision.latency_ms).filter(isNumber);
	return {
		match_id: scheduled.id,
		profile_id: scheduled.profile.id,
		profile_name: scheduled.profile.name,
		seed: scheduled.seed,
		snow_side: scheduled.snowSide,
		outcome: matchOutcome(result, scheduled.snowSide),
		turns: result.turns,
		trace_count: traces.length,
		decision_count: snowPlayer.stats.decisions,
		preview_team: previewTeam,
		preview_leads: previewTeam ? previewTeam.slice(0, 2) : null,
		primary_plan_counts: countPlans(decisions),
		mean_score_margin: meanOrNull(margins),
		minimum_score_margin: margins.length ? Math.min(...margins) : null,
		mean_latency_ms: meanOrNull(latencies),
		max_latency_ms: latencies.length ? Math.max(...latencies) : null,
		runtime_stats: snowPlayer.stats,
		unavailable_choice_revisions: snowPlayer.unavailable_choice_revisions,
		artifact_directory: path.relative(path.dirname(path.dirname(matchDirectory)), matchDirectory),
		trace_file: path.relative(path.dirname(path.dirname(matchDirectory)), traceFile),
	};
}

function aggregateReport(
	format: string,
	showdownCommit: string | null,
	mechanicsHash: string,
	gamesPerSide: number,
	matches: SnowMatchSummary[],
	decisions: SnowDecisionSummary[]
): SnowEvaluationReport {
	const wins = matches.filter(match => match.outcome === 'win').length;
	const losses = matches.filter(match => match.outcome === 'loss').length;
	const ties = matches.filter(match => match.outcome === 'tie').length;
	const latencyValues = decisions.map(decision => decision.latency_ms).filter(isNumber);
	const margins = decisions.map(decision => decision.score_margin).filter(isNumber);
	const featureTotals = new Map<string, { count: number, value: number, contribution: number }>();
	for (const decision of decisions) {
		for (const feature of decision.selected_feature_contributions) {
			const current = featureTotals.get(feature.feature_id) || { count: 0, value: 0, contribution: 0 };
			current.count++;
			current.value += feature.value;
			current.contribution += feature.contribution;
			featureTotals.set(feature.feature_id, current);
		}
	}
	const profiles: SnowEvaluationReport['profiles'] = {};
	for (const match of matches) {
		const current = profiles[match.profile_id] || { matches: 0, wins: 0, losses: 0, ties: 0, win_rate: null };
		current.matches++;
		if (match.outcome === 'win') current.wins++;
		if (match.outcome === 'loss') current.losses++;
		if (match.outcome === 'tie') current.ties++;
		current.win_rate = current.matches ? current.wins / current.matches : null;
		profiles[match.profile_id] = current;
	}
	const traces = matches.reduce((sum, match) => sum + match.trace_count, 0);
	const decisionCount = matches.reduce((sum, match) => sum + match.decision_count, 0);
	return {
		schema_version: SNOW_EVALUATION_SCHEMA_VERSION,
		format,
		showdown_commit: showdownCommit,
		mechanics_snapshot_hash: mechanicsHash,
		games_per_side: gamesPerSide,
		match_count: matches.length,
		wins,
		losses,
		ties,
		win_rate: matches.length ? wins / matches.length : null,
		average_turns: meanOrNull(matches.map(match => match.turns)),
		trace_coverage: { traces, decisions: decisionCount, ratio: decisionCount ? traces / decisionCount : null },
		latency_ms: distribution(latencyValues),
		score_margin: distribution(margins),
		primary_plan_counts: countPlans(decisions),
		selected_feature_contributions: Object.fromEntries([...featureTotals.entries()].sort().map(([id, total]) => [id, {
			count: total.count,
			mean_value: total.value / total.count,
			mean_contribution: total.contribution / total.count,
		}])),
		profiles,
		matches,
	};
}

export function buildReviewQueue(
	matches: SnowMatchSummary[], decisions: SnowDecisionSummary[], narrowMargin = DEFAULT_NARROW_MARGIN
) {
	const matchByID = new Map(matches.map(match => [match.match_id, match]));
	const narrow = decisions
		.filter(decision => decision.score_margin !== null && decision.score_margin <= narrowMargin)
		.slice()
		.sort((left, right) => (left.score_margin ?? Infinity) - (right.score_margin ?? Infinity))
		.slice(0, 20);
	const uncertain = decisions.slice().sort((left, right) => (
		(right.mechanic_uncertainty - left.mechanic_uncertainty) ||
		(right.rng_dependence - left.rng_dependence) ||
		(right.fragile_prediction - left.fragile_prediction)
	)).slice(0, 20);
	const slow = decisions.slice().sort((left, right) => right.latency_ms - left.latency_ms).slice(0, 20);
	const losses = matches.filter(match => match.outcome === 'loss').slice().sort((left, right) => (
		(right.mean_score_margin ?? -Infinity) - (left.mean_score_margin ?? -Infinity)
	)).slice(0, 10);
	return {
		schema_version: SNOW_EVALUATION_SCHEMA_VERSION,
		narrow_margin_threshold: narrowMargin,
		losses,
		narrow_decisions: narrow,
		high_uncertainty_decisions: uncertain,
		slowest_decisions: slow,
		large_margin_loss_decisions: decisions.filter(decision => {
			const match = matchByID.get(decision.match_id);
			return match?.outcome === 'loss' && decision.score_margin !== null && decision.score_margin >= narrowMargin * 2;
		}).sort((left, right) => (right.score_margin ?? 0) - (left.score_margin ?? 0)).slice(0, 20),
	};
}

function validateOptions(options: SnowEvaluationOptions) {
	if (!options.profiles.length) throw new Error('Snow evaluation requires at least one opponent profile.');
	if (!Number.isSafeInteger(options.gamesPerSide) || options.gamesPerSide <= 0) {
		throw new Error('gamesPerSide must be a positive integer.');
	}
	const ids = new Set<string>();
	for (const profile of options.profiles) {
		if (!profile.id || !profile.name || !profile.botPath || !profile.teamPath) {
			throw new Error('Every snow evaluation profile requires id, name, botPath and teamPath.');
		}
		if (ids.has(profile.id)) throw new Error(`Duplicate snow evaluation profile id: ${profile.id}`);
		ids.add(profile.id);
	}
	if (options.narrowMargin !== undefined && (!Number.isFinite(options.narrowMargin) || options.narrowMargin < 0)) {
		throw new Error('narrowMargin must be a finite non-negative number.');
	}
}

function prepareOutputDirectory(directory: string) {
	const output = path.resolve(directory);
	if (fs.existsSync(output)) {
		if (!fs.statSync(output).isDirectory()) throw new Error(`Evaluation output ${output} is not a directory.`);
		if (fs.readdirSync(output).length) throw new Error(`Evaluation output ${output} must be empty.`);
	} else {
		fs.mkdirSync(output, { recursive: true });
	}
	return output;
}

function assertHealthySnowRuntime(matchID: string, player: MatchResult['players']['p1']) {
	const { stats } = player;
	if (stats.timeouts || stats.invalid_responses || stats.fallbacks || stats.exceptions || player.unavailable_choice_revisions) {
		throw new Error(`${matchID} snow runtime was not clean: ${JSON.stringify({
			stats,
			unavailable_choice_revisions: player.unavailable_choice_revisions,
			fallback_log: player.fallback_log,
			stderr: player.stderr,
		})}`);
	}
}

function assertDecisionTrace(value: unknown, label: string): asserts value is SnowDecisionTrace {
	if (!value || typeof value !== 'object') throw new Error(`${label} must contain a trace object.`);
	const trace = value as Partial<SnowDecisionTrace>;
	if (trace.schema_version !== 1 || !Number.isSafeInteger(trace.decision_id) || !Array.isArray(trace.candidates) ||
		!trace.runtime || typeof trace.runtime.latency_ms !== 'number') {
		throw new Error(`${label} is not a DecisionTrace.schema_version == 1 payload.`);
	}
}

function inferTracePhase(trace: SnowDecisionTrace) {
	const selected = trace.candidates.find(candidate => candidate.action.action_id === trace.selected_action_id);
	if (selected?.action.payload.kind === 'team_preview') return 'team_preview';
	if (!trace.opponent_responses.length && selected?.expected_score === null) return 'forced_switch';
	return 'turn';
}

function matchOutcome(result: MatchResult, snowSide: 'p1' | 'p2'): 'win' | 'loss' | 'tie' {
	if (result.tie || !result.winner_side) return 'tie';
	return result.winner_side === snowSide ? 'win' : 'loss';
}

function countPlans(decisions: SnowDecisionSummary[]) {
	const counts: Record<string, number> = {};
	for (const decision of decisions) {
		if (!decision.primary_plan) continue;
		counts[decision.primary_plan] = (counts[decision.primary_plan] || 0) + 1;
	}
	return counts;
}

function featureValue(features: TraceFeatureContribution[], id: string) {
	return features.find(feature => feature.feature_id === id)?.value || 0;
}

function nullableScore(value: number | null) {
	return value === null ? -Infinity : value;
}

function isNumber(value: number | null): value is number {
	return value !== null && Number.isFinite(value);
}

function meanOrNull(values: number[]) {
	return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

function distribution(values: number[]): DistributionSummary {
	if (!values.length) return { count: 0, mean: null, p50: null, p95: null, min: null, max: null };
	const ordered = values.slice().sort((a, b) => a - b);
	return {
		count: ordered.length,
		mean: meanOrNull(ordered),
		p50: percentile(ordered, 0.50),
		p95: percentile(ordered, 0.95),
		min: ordered[0],
		max: ordered[ordered.length - 1],
	};
}

function percentile(ordered: number[], probability: number) {
	if (ordered.length === 1) return ordered[0];
	const position = (ordered.length - 1) * probability;
	const lower = Math.floor(position);
	const upper = Math.ceil(position);
	if (lower === upper) return ordered[lower];
	const fraction = position - lower;
	return ordered[lower] * (1 - fraction) + ordered[upper] * fraction;
}

function writeJSON(filepath: string, value: unknown) {
	fs.writeFileSync(filepath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

function writeJSONLines(filepath: string, values: unknown[]) {
	fs.writeFileSync(filepath, values.map(value => JSON.stringify(value)).join('\n') + (values.length ? '\n' : ''), 'utf8');
}

async function withSnowEnvironment<T>(
	values: Record<string, string | undefined>, callback: () => Promise<T>
): Promise<T> {
	const previous = Object.fromEntries(Object.keys(values).map(key => [key, process.env[key]]));
	for (const [key, value] of Object.entries(values)) {
		if (value === undefined) delete process.env[key];
		else process.env[key] = value;
	}
	try {
		return await callback();
	} finally {
		for (const [key, value] of Object.entries(previous)) {
			if (value === undefined) delete process.env[key];
			else process.env[key] = value;
		}
	}
}

function repositoryRoot() {
	return path.resolve(__dirname, '../../..');
}

function currentCommit() {
	try {
		return execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8', timeout: 1000 }).trim();
	} catch {
		return null;
	}
}
