'use strict';

const assert = require('../assert');
const { Dex } = require('../../dist/sim/dex');
const {
	CHAMPIONS_FORMAT,
	buildChampionsMechanicsSnapshot,
} = require('../../dist/tournament/mechanics/champions-snapshot');

describe('Deterministic snow B7 mechanics promotion', () => {
	it('pins Sturdy full-HP move survival to the Champions callback', () => {
		const dex = Dex.forFormat(CHAMPIONS_FORMAT);
		const sturdy = dex.abilities.get('sturdy');
		const target = { hp: 100, maxhp: 100 };
		assert.equal(sturdy.onDamage.call({ add() {} }, 100, target, {}, { effectType: 'Move' }), 99);

		const snapshot = buildChampionsMechanicsSnapshot(CHAMPIONS_FORMAT, 'test-commit');
		assert.equal(snapshot.semantics.abilities.sturdy.survive_full_hp_lethal_hit, true);
	});
});
