'use strict';

const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('../assert');
const { DEFAULT_FORMAT } = require('../../dist/tournament/match/match-runner');
const { validateTeamExport } = require('../../dist/tournament/submissions/submission-loader');
const {
	loadOpponentBenchmarkProfiles,
	runOpponentBenchmark,
	selectProfiles,
} = require('../../dist/tournament/evaluation/opponent-benchmark');

const root = path.resolve(__dirname, '../..');

describe('Deterministic snow opponent benchmark', function () {
	this.timeout(180_000);

	it('loads the historical, representative and stress catalogue with valid Champions teams', () => {
		const profiles = loadOpponentBenchmarkProfiles();
		assert.equal(profiles.length, 11);
		assert.equal(profiles.filter(profile => profile.suite === 'historical').length, 4);
		assert.equal(profiles.filter(profile => profile.suite === 'representative').length, 3);
		assert.equal(profiles.filter(profile => profile.suite === 'stress').length, 4);
		assert.equal(new Set(profiles.map(profile => profile.id)).size, profiles.length);
		for (const profile of profiles) {
			const team = fs.readFileSync(profile.teamPath, 'utf8');
			validateTeamExport(team, DEFAULT_FORMAT, profile.name);
			assert(profile.weight > 0);
			assert(profile.tags.length > 0);
			assert(profile.provenance.length > 0);
		}
	});

	it('selects suites and explicit profiles deterministically', () => {
		const profiles = loadOpponentBenchmarkProfiles();
		const stress = selectProfiles(profiles, ['stress']);
		assert.equal(stress.length, 4);
		assert(stress.every(profile => profile.suite === 'stress'));
		const rain = selectProfiles(profiles, undefined, ['historical-rain-archaludon']);
		assert.deepEqual(rain.map(profile => profile.id), ['historical-rain-archaludon']);
		assert.throws(() => selectProfiles(profiles, undefined, ['missing-profile']), /Unknown benchmark profile/);
	});

	it('passes public-state archetype behavior acceptance checks', () => {
		const script = path.join(root, 'test/tournament/fixtures/opponent-archetype-selftest.py');
		const output = execFileSync('python3', [script], { encoding: 'utf8', timeout: 15_000 });
		assert.match(output, /self-test passed/);
	});

	it('runs a paired real benchmark profile and writes suite/archetype evidence', async () => {
		const temporaryDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'snow-opponent-benchmark-'));
		try {
			const report = await runOpponentBenchmark({
				outputDirectory: temporaryDirectory,
				gamesPerSide: 1,
				profileIDs: ['historical-rain-archaludon'],
				decisionTimeoutMs: 8000,
				matchTimeoutMs: 90_000,
			});
			assert.equal(report.base_evaluation.match_count, 2);
			assert.equal(report.base_evaluation.trace_coverage.ratio, 1);
			assert.equal(report.suites.historical.matches, 2);
			assert.equal(report.archetypes.rain_offense.matches, 2);
			assert.equal(report.profiles['historical-rain-archaludon'].matches, 2);
			assert(fs.existsSync(path.join(temporaryDirectory, 'benchmark-summary.json')));
			assert(report.tournament_deadline_exceedances >= 0);
		} finally {
			fs.rmSync(temporaryDirectory, { recursive: true, force: true });
		}
	});
});
