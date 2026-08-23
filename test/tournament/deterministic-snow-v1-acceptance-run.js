'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('../assert');
const {
	defaultSnowEvaluationProfiles,
	runDeterministicSnowV1Evaluation,
} = require('../../dist/tournament/evaluation/deterministic-snow-v1');

function compactDecision(decision) {
	return {
		match_id: decision.match_id,
		profile_id: decision.profile_id,
		snow_side: decision.snow_side,
		decision_id: decision.decision_id,
		turn: decision.turn,
		phase: decision.phase,
		selected_action_id: decision.selected_action_id,
		selected_action: decision.selected_action,
		selected_score: decision.selected_score,
		score_margin: decision.score_margin,
		top_alternatives: decision.top_alternatives,
		primary_plan: decision.primary_plan,
		strategy_scores: decision.strategy_scores,
		major_threats: decision.major_threats,
		opponent_responses: decision.opponent_responses.map(response => ({
			id: response.id,
			weight: response.weight,
		})),
		selected_response_evaluations: decision.selected_response_evaluations.map(evaluation => ({
			response_id: evaluation.response_id,
			utility: evaluation.utility,
			confidence: evaluation.confidence,
		})),
		latency_ms: decision.latency_ms,
		mechanic_uncertainty: decision.mechanic_uncertainty,
		rng_dependence: decision.rng_dependence,
		fragile_prediction: decision.fragile_prediction,
		selected_feature_contributions: decision.selected_feature_contributions
			.filter(feature => feature.value !== 0 || feature.contribution !== 0),
		tactical_adjustments: decision.tactical_adjustments,
	};
}

describe('Deterministic snow v1 acceptance execution', () => {
	it('runs the 24-match baseline acceptance batch for empirical inspection', async function () {
		this.timeout(1_800_000);
		const temporaryDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'snow-v1-acceptance-'));
		try {
			const report = await runDeterministicSnowV1Evaluation({
				outputDirectory: temporaryDirectory,
				profiles: defaultSnowEvaluationProfiles(),
				gamesPerSide: 6,
				decisionTimeoutMs: 5000,
				matchTimeoutMs: 60_000,
			});
			assert.equal(report.match_count, 24);
			assert.equal(report.trace_coverage.ratio, 1);
			assert(report.matches.every(match => match.runtime_stats.fallbacks === 0));

			const decisions = fs.readFileSync(path.join(temporaryDirectory, 'decisions.jsonl'), 'utf8')
				.trim().split('\n').filter(Boolean).map(line => JSON.parse(line));
			const queue = JSON.parse(fs.readFileSync(
				path.join(temporaryDirectory, 'review-queue.json'), 'utf8'
			));
			const losses = new Set(report.matches.filter(match => match.outcome === 'loss').map(match => match.match_id));
			const evidence = {
				report,
				loss_decisions: decisions.filter(decision => losses.has(decision.match_id)).map(compactDecision),
				narrow_decisions: queue.narrow_decisions.map(compactDecision),
				high_uncertainty_decisions: queue.high_uncertainty_decisions.map(compactDecision),
				large_margin_loss_decisions: queue.large_margin_loss_decisions.map(compactDecision),
			};
			process.stdout.write(`\nSNOW_V1_ACCEPTANCE_EVIDENCE_BEGIN\n${JSON.stringify(evidence)}\n`);
			process.stdout.write('SNOW_V1_ACCEPTANCE_EVIDENCE_END\n');
		} finally {
			fs.rmSync(temporaryDirectory, { recursive: true, force: true });
		}
	});
});
