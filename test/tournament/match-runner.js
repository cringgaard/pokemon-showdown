'use strict';

const fs = require('fs');
const path = require('path');
const assert = require('../assert');
const { MatchRunner, DEFAULT_FORMAT } = require('../../dist/tournament/match/match-runner');

const root = path.resolve(__dirname, '../..');
const team = fs.readFileSync(path.join(root, 'tournament/fixtures/teams/champions-snow.txt'), 'utf8');
const legacyTeam = fs.readFileSync(path.join(root, 'tournament/fixtures/teams/vgc-reg-i.txt'), 'utf8');
const randomBot = path.join(root, 'tournament/reference-bots/random/main.py');
const greedyBot = path.join(root, 'tournament/reference-bots/greedy-damage/main.py');
const invalidBot = path.join(__dirname, 'fixtures/invalid.py');
const validBot = path.join(__dirname, 'fixtures/valid.py');
const shadowTagTeam = legacyTeam.replace(/^Incineroar[\s\S]*?(?=\nRillaboom)/, `Gothitelle @ Sitrus Berry
Ability: Shadow Tag
Level: 50
EVs: 252 HP / 4 Def / 252 SpD
Tera Type: Dark
- Fake Out
- Psychic
- Trick Room
- Protect
`);

function runMatch(
	p1Bot = randomBot, p2Bot = randomBot, seed = '1,2,3,4', p1Team = team, p2Team = team, format = DEFAULT_FORMAT
) {
	return new MatchRunner({
		format,
		seed,
		decisionTimeoutMs: 1000,
		matchTimeoutMs: 20_000,
		p1: { name: 'Bot One', bot: p1Bot, team: p1Team },
		p2: { name: 'Bot Two', bot: p2Bot, team: p2Team },
	}).run();
}

describe('Tournament MatchRunner', function () {
	this.timeout(30_000);

	it('completes a real fixed-seed RandomBot Doubles match through both Python workers', async () => {
		const result = await runMatch();
		assert.equal(result.format, DEFAULT_FORMAT);
		assert(['Bot One', 'Bot Two'].includes(result.winner));
		assert(result.turns > 0);
		assert.equal(result.players.p1.stats.fallbacks, 0);
		assert.equal(result.players.p2.stats.fallbacks, 0);
		for (const player of Object.values(result.players)) {
			assert.equal(player.states[0].schema_version, 2);
			assert.equal(player.states[0].battle.phase, 'team_preview');
			assert.equal(player.states[0].battle.mod, 'champions');
			assert.equal(player.states[0].request.legal_actions.length, 360);
			assert(player.states.some(state => state.battle.phase === 'turn'));
			assert(player.states.some(state => state.opponent.team.length === 6));
			const sheet = player.states.find(state => state.opponent.team.length === 6).opponent.team[0];
			assert(sheet.species);
			assert(sheet.item);
			assert(sheet.ability);
			assert.equal(sheet.moves.length, 4);
			assert(sheet.nature);
			assert(sheet.gender);
			assert.equal(sheet.level, 50);
		}
		assert(Object.values(result.players).some(player =>
			player.states.some(state => state.battle.phase === 'forced_switch')));
	});

	it('replays the same controlled battle outcome and authoritative log', async () => {
		const first = await runMatch(randomBot, randomBot, '8,7,6,5');
		const second = await runMatch(randomBot, randomBot, '8,7,6,5');
		assert.equal(second.winner, first.winner);
		assert.equal(second.turns, first.turns);
		const normalizeTimestamps = log => log.map(chunk => chunk.replace(/\|t:\|\d+/g, '|t:|<time>'));
		assert.deepEqual(normalizeTimestamps(second.authoritative_log), normalizeTimestamps(first.authoritative_log));
	});

	it('completes GreedyDamageBot versus RandomBot using only the public API', async () => {
		const result = await runMatch(greedyBot, randomBot, '10,20,30,40');
		assert(result.winner || result.tie);
		assert.equal(result.players.p1.stats.invalid_responses, 0);
	});

	it('does not serialize hidden opponent values into either bot state', async () => {
		const result = await runMatch(randomBot, randomBot, '11,22,33,44');
		for (const player of Object.values(result.players)) {
			for (const state of player.states) {
				for (const pokemon of state.opponent.team) {
					assert(!Object.hasOwn(pokemon, 'stats'));
					assert(!Object.hasOwn(pokemon, 'evs'));
					assert(!Object.hasOwn(pokemon, 'ivs'));
					assert(!Object.hasOwn(pokemon, 'stat_points'));
				}
				for (const active of Object.values(state.opponent.active)) assert.equal(active.health.exact, false);
			}
		}
	});

	it('finishes when a participant repeatedly returns illegal actions', async () => {
		const result = await runMatch(invalidBot, randomBot, '50,60,70,80');
		assert(result.winner || result.tie);
		assert(result.players.p1.stats.invalid_responses > 0);
		assert(result.players.p1.stats.fallbacks > 0);
	});

	it('revises an unavailable hidden-information choice without charging an invalid attempt', async () => {
		const legacyFormat = 'gen9vgc2025regi@@@!openteamsheets,forceopenteamsheets';
		const result = await runMatch(validBot, validBot, '90,91,92,93', legacyTeam, shadowTagTeam, legacyFormat);
		assert(result.players.p1.unavailable_choice_revisions > 0);
		assert.equal(result.players.p1.stats.invalid_responses, 0);
		assert(result.players.p1.states.some(state => state.runtime.revision > 0 && state.runtime.attempt === 1));
		assert.equal(result.players.p1.stats.decisions,
			new Set(result.players.p1.states.map(state => state.runtime.decision_id)).size);
	});
});
