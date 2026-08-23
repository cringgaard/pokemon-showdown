'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('../assert');
const {
	buildReviewQueue,
	buildSchedule,
	defaultSnowEvaluationProfiles,
	readSnowDecisionTraces,
	runDeterministicSnowV1Evaluation,
	summarizeDecision,
} = require('../../dist/tournament/evaluation/deterministic-snow-v1');

function syntheticTrace() {
	return {
		schema_version: 1,
		level: 'TOP_CANDIDATES',
		decision_id: 7,
		turn: 3,
		versions: { policy: 'p', config: 'c', weights: 'w', mechanics: 'm', team: 't', format: 'f', mod: 'x' },
		strategy: { glaceon_fortress: 80, aggron_fortress: 40, tactical_offense: 55, primary_plan: 'GLACEON_FORTRESS' },
		major_threats: ['focus Glaceon'],
		opponent_responses: [{ id: 'r1', weight: 1, reasons: ['damage'], actions: ['move'] }],
		candidates: [
			{
				action: { action_id: 'selected', payload: { kind: 'turn', actions: { left: { type: 'move', move: 'blizzard' } } } },
				expected_score: 100,
				credible_bad_case_score: 80,
				best_case_score: 120,
				final_score: 95,
				feature_contributions: [
					{ feature_id: 'MECHANIC_UNCERTAINTY', value: 0.2, weight: -35, contribution: -7 },
					{ feature_id: 'RNG_DEPENDENCE', value: 0.1, weight: -45, contribution: -4.5 },
					{ feature_id: 'FRAGILE_PREDICTION', value: 0.3, weight: 0, contribution: 0 },
				],
				tactical_adjustments: [{ rule_id: 'CASH_OUT', adjustment: 25, reason: 'convert' }],
			},
			{
				action: { action_id: 'other', payload: { kind: 'turn', actions: { left: { type: 'move', move: 'calmmind' } } } },
				expected_score: 75,
				credible_bad_case_score: 70,
				best_case_score: 85,
				final_score: 70,
				feature_contributions: [],
				tactical_adjustments: [],
			},
		],
		selected_action_id: 'selected',
		runtime: { latency_ms: 12.5, candidate_count: 20, response_count: 4, evaluation_count: 80 },
	};
}

describe('Deterministic snow v1 evaluation', function () {
	it('builds paired reproducible side-balanced schedules', () => {
		const profile = { id: 'x', name: 'X', botPath: '/x.py', teamPath: '/x.txt' };
		const schedule = buildSchedule([profile], 2);
		assert.equal(schedule.length, 4);
		assert.equal(schedule[0].snowSide, 'p1');
		assert.equal(schedule[1].snowSide, 'p2');
		assert.equal(schedule[0].seed, schedule[1].seed);
		assert.equal(schedule[2].seed, schedule[3].seed);
		assert.notEqual(schedule[0].seed, schedule[2].seed);
	});

	it('parses trace JSONL and exposes semantic review metrics', () => {
		const temporaryDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'snow-eval-trace-'));
		const traceFile = path.join(temporaryDirectory, 'trace.jsonl');
		try {
			fs.writeFileSync(traceFile, JSON.stringify(syntheticTrace()) + '\n');
			const traces = readSnowDecisionTraces(traceFile);
			assert.equal(traces.length, 1);
			const decision = summarizeDecision('m1', 'profile', 'p1', traces[0]);
			assert.equal(decision.primary_plan, 'GLACEON_FORTRESS');
			assert.equal(decision.score_margin, 25);
			assert.equal(decision.mechanic_uncertainty, 0.2);
			assert.equal(decision.rng_dependence, 0.1);
			assert.equal(decision.fragile_prediction, 0.3);
			assert.equal(decision.top_alternatives[0].action_id, 'other');
			const queue = buildReviewQueue([
				{
					match_id: 'm1', profile_id: 'profile', profile_name: 'Profile', seed: '1,2,3,4', snow_side: 'p1',
					outcome: 'loss', turns: 4, trace_count: 1, decision_count: 1, preview_team: null, preview_leads: null,
					primary_plan_counts: {}, mean_score_margin: 25, minimum_score_margin: 25,
					mean_latency_ms: 12.5, max_latency_ms: 12.5,
					runtime_stats: { decisions: 1, timeouts: 0, invalid_responses: 0, fallbacks: 0, exceptions: 0 },
					unavailable_choice_revisions: 0, artifact_directory: 'matches/m1', trace_file: 'matches/m1/trace.jsonl',
				},
			], [decision], 30);
			assert.equal(queue.losses.length, 1);
			assert.equal(queue.narrow_decisions.length, 1);
		} finally {
			fs.rmSync(temporaryDirectory, { recursive: true, force: true });
		}
	});

	it('runs a paired real MatchRunner evaluation with complete snow traces', async function () {
		this.timeout(150_000);
		const temporaryDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'snow-v1-eval-'));
		try {
			const greedy = defaultSnowEvaluationProfiles().find(profile => profile.id === 'greedy-mirror');
			assert(greedy);
			const report = await runDeterministicSnowV1Evaluation({
				outputDirectory: temporaryDirectory,
				profiles: [greedy],
				gamesPerSide: 1,
				decisionTimeoutMs: 5000,
				matchTimeoutMs: 60_000,
			});
			assert.equal(report.match_count, 2);
			assert.equal(report.trace_coverage.ratio, 1);
			assert.equal(report.matches.length, 2);
			assert(report.matches.every(match => match.runtime_stats.fallbacks === 0));
			assert(fs.existsSync(path.join(temporaryDirectory, 'summary.json')));
			assert(fs.existsSync(path.join(temporaryDirectory, 'decisions.jsonl')));
			assert(fs.existsSync(path.join(temporaryDirectory, 'review-queue.json')));
			assert(fs.existsSync(path.join(temporaryDirectory, 'matches', report.matches[0].match_id, 'snow-decision-traces.jsonl')));
		} finally {
			fs.rmSync(temporaryDirectory, { recursive: true, force: true });
		}
	});
});
