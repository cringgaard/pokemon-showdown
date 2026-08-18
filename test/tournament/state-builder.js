'use strict';

const assert = require('../assert');
const { buildBotState } = require('../../dist/tournament/state/state-builder');
const { StateTracker } = require('../../dist/tournament/state/state-tracker');

function pokemon(index, condition, active = false) {
	return {
		ident: `p1: Mon ${index}`,
		details: 'Pikachu, L50',
		condition,
		active,
		stats: { atk: 100, def: 100, spa: 100, spd: 100, spe: 100 },
		moves: ['protect'],
		baseAbility: 'static',
		ability: 'static',
		item: '',
		pokeball: 'pokeball',
	};
}

describe('Tournament bot state builder', () => {
	it('clears benched observations and preserves exact max HP after fainting', () => {
		const tracker = new StateTracker('p1');
		const previewPokemon = [
			pokemon(0, '200/200'), pokemon(1, '180/180'), pokemon(2, '160/160'),
			pokemon(3, '140/140'), pokemon(4, '120/120'), pokemon(5, '100/100'),
		];
		tracker.registerRequest({
			teamPreview: true,
			maxChosenTeamSize: 4,
			side: { name: 'Bot', id: 'p1', pokemon: previewPokemon },
		});
		tracker.consume([
			'|switch|p1a: Mon 0|Pikachu, L50|200/200',
			'|-boost|p1a: Mon 0|atk|2',
			'|-start|p1a: Mon 0|confusion',
			'|switch|p1a: Mon 2|Pikachu, L50|160/160',
		].join('\n'));

		const currentTeam = [
			pokemon(2, '160/160', true),
			pokemon(1, '180/180', true),
			pokemon(0, '0 fnt'),
			pokemon(3, '140/140'),
			pokemon(4, '120/120'),
			pokemon(5, '100/100'),
		];
		const state = buildBotState(tracker, {
			active: [
				{ moves: [{ move: 'Protect', id: 'protect', pp: 16, maxpp: 16, target: 'self' }] },
				{ moves: [{ move: 'Protect', id: 'protect', pp: 16, maxpp: 16, target: 'self' }] },
			],
			side: { name: 'Bot', id: 'p1', pokemon: currentTeam },
		}, {
			format: 'gen9vgc2026regf',
			runtime: { decision_id: 1, revision: 0, attempt: 1, previous_error: null, deadline_ms: 1000 },
		});

		const fainted = state.self.team.find(mon => mon.id === 'team_0');
		assert.equal(fainted.health.current, 0);
		assert.equal(fainted.health.max, 200);
		assert.equal(fainted.health.exact, true);
		assert.deepEqual(fainted.boosts, { atk: 0, def: 0, spa: 0, spd: 0, spe: 0, accuracy: 0, evasion: 0 });
		assert.deepEqual(fainted.volatiles, []);
	});
});
