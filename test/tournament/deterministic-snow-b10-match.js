'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('../assert');
const { MatchRunner, DEFAULT_FORMAT } = require('../../dist/tournament/match/match-runner');
const { writeChampionsMechanicsSnapshot } = require('../../dist/tournament/mechanics/champions-snapshot');

const root = path.resolve(__dirname, '../..');
const team = fs.readFileSync(path.join(root, 'tournament/fixtures/teams/champions-snow.txt'), 'utf8');
const snowBot = path.join(root, 'tournament/policies/deterministic_snow/participant.py');
const greedyBot = path.join(root, 'tournament/reference-bots/greedy-damage/main.py');


describe('Deterministic snow B10 MatchRunner integration', function () {
	this.timeout(90_000);

	it('completes a real fixed-seed Champions match without snow-policy fallback', async () => {
		const temporaryDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'snow-b10-'));
		const mechanicsPath = path.join(temporaryDirectory, 'champions-mechanics.json');
		writeChampionsMechanicsSnapshot(mechanicsPath, DEFAULT_FORMAT, 'b10-match-smoke');
		const previousMechanicsPath = process.env.DETERMINISTIC_SNOW_MECHANICS_PATH;
		process.env.DETERMINISTIC_SNOW_MECHANICS_PATH = mechanicsPath;
		try {
			const result = await new MatchRunner({
				format: DEFAULT_FORMAT,
				seed: '101,202,303,404',
				decisionTimeoutMs: 5000,
				matchTimeoutMs: 60_000,
				p1: { id: 'snow-b10', name: 'Snow B10', bot: snowBot, team },
				p2: { id: 'greedy-smoke', name: 'Greedy Smoke', bot: greedyBot, team },
			}).run();
			assert(result.winner || result.tie);
			assert(result.turns > 0);
			assert.equal(result.players.p1.stats.invalid_responses, 0);
			assert.equal(result.players.p1.stats.timeouts, 0);
			assert.equal(result.players.p1.stats.fallbacks, 0);
			assert.equal(result.players.p1.stats.exceptions, 0);
			assert.equal(result.players.p1.states[0].battle.phase, 'team_preview');
			assert.equal(result.players.p1.states[0].request.legal_actions.length, 360);
			assert(result.players.p1.states.some(state => state.battle.phase === 'turn'));
			assert(result.players.p1.states.every(state => state.schema_version === 2));
		} finally {
			if (previousMechanicsPath === undefined) {
				delete process.env.DETERMINISTIC_SNOW_MECHANICS_PATH;
			} else {
				process.env.DETERMINISTIC_SNOW_MECHANICS_PATH = previousMechanicsPath;
			}
			fs.rmSync(temporaryDirectory, { recursive: true, force: true });
		}
	});
});
