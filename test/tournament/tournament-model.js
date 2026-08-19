'use strict';

const assert = require('../assert');
const {
	calculateStandings, deriveTournamentSeed, finalGame, pairingIdentity, roundRobinSchedule, seriesScore,
} = require('../../dist/tournament/orchestrator/model');
const { normalizeTournamentConfig } = require('../../dist/tournament/orchestrator/config');

function config(count, overrides = {}) {
	return normalizeTournamentConfig({
		title: 'Company Cup',
		format: 'gen9vgc2025regi',
		seed: '2026',
		runtime: 'host',
		participants: Array.from({ length: count }, (_, index) => ({
			id: `bot-${String.fromCharCode(97 + index)}`,
			name: `Bot ${String.fromCharCode(65 + index)}`,
			submission: `bot-${index}`,
		})),
		round_robin: { games_per_pairing: 3 },
		final: { qualifiers: 2, best_of: 5 },
		...overrides,
	}, process.cwd());
}

describe('Tournament deterministic model', () => {
	for (const count of [2, 3, 4, 6]) {
		it(`schedules every unordered pair exactly once for ${count} participants`, () => {
			const tournament = config(count);
			const schedule = roundRobinSchedule(tournament);
			assert.equal(schedule.length, count * (count - 1) / 2 * 3);
			const pairings = new Map();
			for (const game of schedule) {
				const pair = [game.p1, game.p2].sort().join(':');
				pairings.set(pair, (pairings.get(pair) || 0) + 1);
			}
			assert.equal(pairings.size, count * (count - 1) / 2);
			assert([...pairings.values()].every(games => games === 3));
		});
	}

	it('alternates sides and derives stable documented seeds', () => {
		const tournament = config(2);
		const games = roundRobinSchedule(tournament);
		assert.deepEqual(games.map(game => [game.p1, game.p2]), [
			['bot-a', 'bot-b'], ['bot-b', 'bot-a'], ['bot-a', 'bot-b'],
		]);
		assert.equal(games[0].seed, deriveTournamentSeed(
			'2026', 'round_robin', pairingIdentity('bot-a', 'bot-b'), 0
		));
		assert.equal(games[0].seed, roundRobinSchedule(tournament)[0].seed);
		assert.notEqual(games[0].seed, games[1].seed);
		assert.deepEqual([0, 1, 2].map(index => finalGame(tournament, ['bot-a', 'bot-b'], index).p1), [
			'bot-a', 'bot-b', 'bot-a',
		]);
	});

	it('ranks points, tied-group head-to-head, wins, then stable participant ID', () => {
		const tournament = config(4, { round_robin: { games_per_pairing: 1 } });
		const games = [
			completed('bot-a', 'bot-b', 'bot-a'),
			completed('bot-a', 'bot-c', 'bot-c'),
			completed('bot-a', 'bot-d', null),
			completed('bot-b', 'bot-c', 'bot-b'),
			completed('bot-b', 'bot-d', 'bot-d'),
			completed('bot-c', 'bot-d', null),
		];
		const standings = calculateStandings(tournament, games);
		assert.deepEqual(standings.map(row => row.participant_id), ['bot-d', 'bot-c', 'bot-a', 'bot-b']);
		assert.equal(standings[0].points, 2);
		assert.equal(standings[0].ties, 2);
		assert.equal(standings[0].games_played, 3);
	});

	it('tracks final wins separately from ties', () => {
		const games = [
			{ ...completed('bot-a', 'bot-b', null), stage: 'final' },
			{ ...completed('bot-b', 'bot-a', 'bot-a'), stage: 'final' },
		];
		assert.deepEqual(seriesScore(['bot-a', 'bot-b'], games), {
			score: { 'bot-a': 1, 'bot-b': 0 }, ties: 1,
		});
	});

	it('rejects duplicate IDs/names and invalid final/game settings', () => {
		const base = {
			title: 'Cup', participants: [
				{ id: 'same', name: 'Same', submission: 'a' },
				{ id: 'same', name: 'Same', submission: 'b' },
			],
			round_robin: { games_per_pairing: 1 }, final: { qualifiers: 2, best_of: 2 },
		};
		assert.throws(() => normalizeTournamentConfig(base, process.cwd()), /IDs must be unique/);
		base.participants[1].id = 'other';
		assert.throws(() => normalizeTournamentConfig(base, process.cwd()), /names must be unique/);
		base.participants[1].name = 'Other';
		assert.throws(() => normalizeTournamentConfig(base, process.cwd()), /best_of must be odd/);
	});
});

function completed(p1, p2, winner) {
	return {
		id: `${p1}-${p2}`, stage: 'round_robin', pairing_id: `${p1}-vs-${p2}`, game_index: 0,
		p1, p2, seed: '1,2,3,4', winner_participant_id: winner, tie: !winner, turns: 1,
		artifact_directory: 'unused', attempt: 1,
	};
}
