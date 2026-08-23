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

function isWeather(current, expected) {
	return (Array.isArray(expected) ? expected : [expected]).includes(current);
}

function moveAccuracyInWeather(move, weather) {
	assert.equal(typeof move.onModifyMove, 'function');
	const activeMove = { accuracy: move.accuracy };
	move.onModifyMove.call(
		{ field: { isWeather: expected => isWeather(weather, expected) } },
		activeMove,
		{},
		{ effectiveWeather: () => weather }
	);
	return activeMove.accuracy;
}

describe('Deterministic snow mechanics integration', () => {
	it('exports a deterministic Champions snapshot with unique public move IDs', () => {
		const first = buildChampionsMechanicsSnapshot(CHAMPIONS_FORMAT, 'test-commit');
		const second = buildChampionsMechanicsSnapshot(CHAMPIONS_FORMAT, 'test-commit');
		assert.equal(first.format.id, CHAMPIONS_FORMAT);
		assert.equal(first.format.mod, 'champions');
		assert.equal(first.format.game_type, 'doubles');
		assert.equal(first.snapshot_hash, second.snapshot_hash);
		assert(/^sha256:[0-9a-f]{64}$/.test(first.snapshot_hash));

		const moveIDs = first.moves.map(move => move.id);
		assert.equal(new Set(moveIDs).size, moveIDs.length);
		assert.equal(moveIDs.filter(id => id === 'hiddenpower').length, 1);
		assert.equal(byID(first.moves, 'hiddenpower').name, Dex.forFormat(CHAMPIONS_FORMAT).moves.get('hiddenpower').name);
	});

	it('contains the current-six mechanics and format-resolved Mega data', () => {
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
			'calmmind', 'blizzard', 'wish', 'protect', 'auroraveil', 'freezedry', 'encore',
			'followme', 'mudslap', 'irondefense', 'bodypress', 'heavyslam', 'wideguard',
			'allyswitch', 'armorcannon', 'psychic', 'thunderbolt', 'grassknot',
		]) {
			byID(snapshot.moves, move);
		}

		assert.deepEqual(byID(snapshot.species, 'aggron').types, ['Steel', 'Rock']);
		assert.deepEqual(byID(snapshot.species, 'aggronmega').types, ['Steel']);
		assert.equal(byID(snapshot.species, 'aggronmega').abilities['0'], 'Filter');
		assert.equal(byID(snapshot.items, 'aggronite').mega_stone.Aggron, 'Aggron-Mega');
		assert.equal(byID(snapshot.moves, 'bodypress').override_offensive_stat, 'def');
		assert.equal(snapshot.type_chart.Fighting.Ghost, 0);
	});

	it('pins snow and weather-accuracy annotations to the actual callbacks', () => {
		const dex = Dex.forFormat(CHAMPIONS_FORMAT);
		const snapshot = buildChampionsMechanicsSnapshot(CHAMPIONS_FORMAT, 'test-commit');

		let entryWeather = null;
		dex.abilities.get('snowwarning').onStart.call({
			field: { setWeather: weather => { entryWeather = weather; } },
		}, {});
		assert.equal(entryWeather, 'snowscape');
		assert.equal(snapshot.semantics.abilities.snowwarning.entry_weather, 'snowscape');

		const snowCloak = dex.abilities.get('snowcloak');
		const snowCloakContext = weather => ({
			field: { isWeather: expected => isWeather(weather, expected) },
			debug() {},
			chainModify: modifier => modifier,
		});
		assert.deepEqual(snowCloak.onModifyAccuracy.call(snowCloakContext('snowscape'), 100), [3277, 4096]);
		assert.deepEqual(snowCloak.onModifyAccuracy.call(snowCloakContext('hail'), 100), [3277, 4096]);
		assert.equal(snowCloak.onModifyAccuracy.call(snowCloakContext('raindance'), 100), undefined);
		assert.deepEqual(
			snapshot.semantics.abilities.snowcloak.incoming_accuracy_modifier_in_weather.snowscape,
			[3277, 4096]
		);

		const brightPowder = dex.items.get('brightpowder');
		assert.deepEqual(brightPowder.onModifyAccuracy.call({
			debug() {}, chainModify: modifier => modifier,
		}, 100), [3686, 4096]);
		assert.deepEqual(snapshot.semantics.items.brightpowder.incoming_accuracy_modifier, [3686, 4096]);

		const icyRockHolder = { hasItem: item => item === 'icyrock' };
		assert.equal(dex.conditions.get('snowscape').durationCallback.call({}, icyRockHolder, null), 8);
		assert.equal(dex.conditions.get('hail').durationCallback.call({}, icyRockHolder, null), 8);
		assert.deepEqual(snapshot.semantics.items.icyrock.weather_extension_turns, { hail: 8, snowscape: 8 });

		const auroraVeil = dex.moves.get('auroraveil');
		assert.equal(auroraVeil.onTry.call({ field: { isWeather: expected => isWeather('snowscape', expected) } }), true);
		assert.equal(auroraVeil.onTry.call({ field: { isWeather: expected => isWeather('sunnyday', expected) } }), false);
		assert.deepEqual(snapshot.semantics.moves.auroraveil.requires_weather, ['hail', 'snowscape']);

		assert.equal(moveAccuracyInWeather(dex.moves.get('blizzard'), 'snowscape'), true);
		assert.equal(moveAccuracyInWeather(dex.moves.get('blizzard'), 'hail'), true);
		assert.equal(moveAccuracyInWeather(dex.moves.get('blizzard'), 'raindance'), 70);
		assert.equal(moveAccuracyInWeather(dex.moves.get('thunder'), 'raindance'), true);
		assert.equal(moveAccuracyInWeather(dex.moves.get('thunder'), 'primordialsea'), true);
		assert.equal(moveAccuracyInWeather(dex.moves.get('thunder'), 'sunnyday'), 50);
		assert.equal(moveAccuracyInWeather(dex.moves.get('hurricane'), 'raindance'), true);
		assert.equal(moveAccuracyInWeather(dex.moves.get('hurricane'), 'sunnyday'), 50);
	});

	it('pins key defensive and protection semantics to Showdown mechanics', () => {
		const dex = Dex.forFormat(CHAMPIONS_FORMAT);
		const snapshot = buildChampionsMechanicsSnapshot(CHAMPIONS_FORMAT, 'test-commit');

		const friendGuardHolder = {};
		const friendGuardAlly = { isAlly: pokemon => pokemon === friendGuardHolder };
		assert.equal(dex.abilities.get('friendguard').onAnyModifyDamage.call({
			effectState: { target: friendGuardHolder }, debug() {}, chainModify: modifier => modifier,
		}, 100, {}, friendGuardAlly, {}), 0.75);
		assert.equal(snapshot.semantics.abilities.friendguard.ally_damage_multiplier, 0.75);

		assert.equal(dex.abilities.get('filter').onSourceModifyDamage.call({
			debug() {}, chainModify: modifier => modifier,
		}, 100, {}, { getMoveHitData: () => ({ typeMod: 1 }) }, {}), 0.75);
		assert.equal(snapshot.semantics.abilities.filter.super_effective_damage_multiplier, 0.75);

		const gravity = dex.moves.get('gravity').condition;
		assert.deepEqual(gravity.onModifyAccuracy.call({ chainModify: modifier => modifier }, 100), [6840, 4096]);
		assert.deepEqual(snapshot.semantics.field.gravity.accuracy_multiplier_ratio, [6840, 4096]);
		assert.equal(Object.hasOwn(snapshot.semantics.field.gravity, 'suppresses_evasion'), false);

		assert.equal(dex.moves.get('heatwave').target, 'allAdjacentFoes');
		assert(dex.moves.get('heatwave').flags['protect']);
		assert.equal(dex.moves.get('weatherball').target, 'normal');
		assert.equal(typeof dex.moves.get('wideguard').condition.onTryHit, 'function');
		assert.equal(typeof dex.moves.get('freezedry').onEffectiveness, 'function');
		assert.equal(typeof dex.abilities.get('noguard').onAnyAccuracy, 'function');
	});

	it('round-trips the snapshot through the fail-closed Python consumer', () => {
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
