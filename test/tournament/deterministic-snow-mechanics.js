'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('../assert');
const { Dex } = require('../../dist/sim/dex');
const {
	CHAMPIONS_FORMAT,
	buildChampionsMechanicsSnapshot,
	writeChampionsMechanicsSnapshot,
} = require('../../dist/tournament/mechanics/champions-snapshot');

const ROOT = path.resolve(__dirname, '..', '..');
const PYTHON_VERIFIER = path.resolve(__dirname, 'deterministic-snow', 'verify_mechanics_snapshot.py');

function byID(values, id) {
	const result = values.find(value => value.id === id);
	assert(result, `Expected mechanics entry ${id}`);
	return result;
}

describe('Deterministic snow mechanics integration', () => {
	it('exports format-aware Champions mechanics and stable metadata', () => {
		const first = buildChampionsMechanicsSnapshot(CHAMPIONS_FORMAT, 'test-commit');
		const second = buildChampionsMechanicsSnapshot(CHAMPIONS_FORMAT, 'test-commit');
		assert.equal(first.format.id, CHAMPIONS_FORMAT);
		assert.equal(first.format.mod, 'champions');
		assert.equal(first.format.game_type, 'doubles');
		assert.equal(first.snapshot_hash, second.snapshot_hash);
		assert.match(first.snapshot_hash, /^sha256:[0-9a-f]{64}$/);

		const aggron = byID(first.species, 'aggron');
		const megaAggron = byID(first.species, 'aggronmega');
		assert.deepEqual(aggron.types, ['Steel', 'Rock']);
		assert.equal(aggron.abilities['0'], 'Sturdy');
		assert.deepEqual(megaAggron.types, ['Steel']);
		assert.equal(megaAggron.abilities['0'], 'Filter');
		assert.equal(megaAggron.is_mega, true);
		assert.equal(megaAggron.battle_only, 'Aggron');

		const aggronite = byID(first.items, 'aggronite');
		assert.equal(aggronite.mega_stone.Aggron, 'Aggron-Mega');

		const bodyPress = byID(first.moves, 'bodypress');
		assert.equal(bodyPress.override_offensive_stat, 'def');
		assert.equal(first.semantics.moves.bodypress.offensive_stat, 'def');
		assert.equal(first.type_chart.Fighting.Ghost, 0);

		const freezeDry = byID(first.moves, 'freezedry');
		assert(freezeDry.callback_names.includes('onEffectiveness'));
		assert.equal(first.semantics.moves.freezedry.effectiveness_override.Water, 2);

		const heatWave = byID(first.moves, 'heatwave');
		const weatherBall = byID(first.moves, 'weatherball');
		assert.equal(heatWave.target, 'allAdjacentFoes');
		assert.notEqual(weatherBall.target, 'allAdjacentFoes');
		assert.notEqual(weatherBall.target, 'allAdjacent');

		const noGuard = byID(first.abilities, 'noguard');
		assert(noGuard.callback_names.includes('onAnyAccuracy'));
		assert.equal(first.semantics.abilities.noguard.accuracy_bypass, true);
		assert.deepEqual(first.semantics.field.gravity.accuracy_multiplier_ratio, [6840, 4096]);
		assert.equal(first.semantics.field.gravity.grounds_flying, true);
		assert.equal(Object.hasOwn(first.semantics.field.gravity, 'suppresses_evasion'), false);
	});

	it('keeps every semantic annotation attached to a real format mechanic', () => {
		const snapshot = buildChampionsMechanicsSnapshot(CHAMPIONS_FORMAT, 'test-commit');
		for (const id of Object.keys(snapshot.semantics.moves)) byID(snapshot.moves, id);
		for (const id of Object.keys(snapshot.semantics.abilities)) byID(snapshot.abilities, id);
		for (const id of Object.keys(snapshot.semantics.items)) byID(snapshot.items, id);
	});

	it('contains the exact current-six mechanic surfaces', () => {
		const snapshot = buildChampionsMechanicsSnapshot(CHAMPIONS_FORMAT, 'test-commit');
		for (const species of ['glaceon', 'ninetalesalola', 'maushold', 'aggron', 'armarouge', 'heliolisk']) {
			byID(snapshot.species, species);
		}
		for (const ability of ['snowcloak', 'snowwarning', 'friendguard', 'sturdy', 'filter', 'flashfire', 'dryskin']) {
			byID(snapshot.abilities, ability);
		}
		for (const item of ['brightpowder', 'icyrock', 'chopleberry', 'aggronite', 'colburberry', 'focussash']) {
			byID(snapshot.items, item);
		}
		for (const move of [
			'calmmind', 'blizzard', 'wish', 'protect',
			'auroraveil', 'freezedry', 'encore',
			'followme', 'mudslap',
			'irondefense', 'bodypress', 'heavyslam',
			'wideguard', 'allyswitch', 'armorcannon', 'psychic',
			'thunderbolt', 'grassknot',
		]) {
			byID(snapshot.moves, move);
		}
	});

	it('keeps semantic annotations aligned with the actual Champions Dex', () => {
		const dex = Dex.forFormat(CHAMPIONS_FORMAT);
		const snapshot = buildChampionsMechanicsSnapshot(CHAMPIONS_FORMAT, 'test-commit');

		assert.equal(dex.moves.get('bodypress').overrideOffensiveStat, 'def');
		assert.equal(dex.moves.get('heatwave').target, 'allAdjacentFoes');
		assert.equal(dex.moves.get('weatherball').target, 'normal');
		assert.equal(typeof dex.moves.get('freezedry').onEffectiveness, 'function');
		const gravity = dex.moves.get('gravity').condition;
		assert.equal(typeof gravity.onModifyAccuracy, 'function');
		assert.deepEqual(gravity.onModifyAccuracy.call({ chainModify: modifier => modifier }, 100), [6840, 4096]);
		assert.equal(typeof dex.abilities.get('noguard').onAnyAccuracy, 'function');
		assert.equal(typeof dex.abilities.get('snowcloak').onModifyAccuracy, 'function');
		assert.equal(typeof dex.abilities.get('defiant').onAfterEachBoost, 'function');
		assert.equal(typeof dex.abilities.get('competitive').onAfterEachBoost, 'function');
		assert.equal(typeof dex.abilities.get('contrary').onChangeBoost, 'function');
		assert.equal(typeof dex.abilities.get('stamina').onDamagingHit, 'function');

		const staraptorMega = dex.species.get('Staraptor-Mega');
		assert(staraptorMega.exists);
		assert(staraptorMega.types.includes('Flying'));
		assert.equal(dex.getImmunity('Ground', staraptorMega), false);
		assert.equal(snapshot.type_chart.Ground.Flying, 0);
	});

	it('round-trips the generated snapshot through the Python mechanics consumer', () => {
		const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'snow-mechanics-'));
		const snapshotPath = path.join(directory, 'champions-mechanics.json');
		try {
			writeChampionsMechanicsSnapshot(snapshotPath, CHAMPIONS_FORMAT, 'test-commit');
			const result = childProcess.spawnSync('python', [PYTHON_VERIFIER, snapshotPath], {
				cwd: ROOT,
				encoding: 'utf8',
				env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
			});
			assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
		} finally {
			fs.rmSync(directory, { recursive: true, force: true });
		}
	});
});
