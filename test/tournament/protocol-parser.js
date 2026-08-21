'use strict';

const assert = require('../assert');
const { Teams } = require('../../dist/sim/teams');
const { parseProtocolLine, parsePokemonIdent } = require('../../dist/tournament/state/protocol-parser');
const { StateTracker } = require('../../dist/tournament/state/state-tracker');

describe('Tournament player-visible protocol tracking', () => {
	it('parses positional protocol and keyword arguments', () => {
		assert.deepEqual(parsePokemonIdent('p2b: Moth'), { side: 'p2', slot: 'b', name: 'Moth' });
		assert.deepEqual(parseProtocolLine('|-damage|p2b: Moth|73/100 brn|[from] item: Life Orb'), {
			type: '-damage',
			args: ['p2b: Moth', '73/100 brn'],
			kwArgs: { from: 'item: Life Orb' },
			raw: '|-damage|p2b: Moth|73/100 brn|[from] item: Life Orb',
		});
	});

	it('tracks required v1 observations without crashing on unknown lines', () => {
		const tracker = new StateTracker('p1');
		const opponentTeam = Teams.pack([
			{ name: 'Moth', species: 'Volcarona', item: 'leftovers', ability: 'flamebody', teraType: 'Grass', moves: ['heatwave'] },
			{ name: 'Moon', species: 'Roaring Moon', item: 'boosterenergy', ability: 'protosynthesis', teraType: 'Flying', moves: ['knockoff'] },
		]);
		tracker.consume([
			'|player|p1|Alpha|1',
			'|player|p2|Beta|1',
			`|showteam|p2|${opponentTeam}`,
			'|start',
			'|switch|p2a: Moth|Volcarona, L50|100/100',
			'|switch|p2b: Moon|Roaring Moon, L50|100/100',
			'|turn|3',
			'|-damage|p2a: Moth|73/100 brn',
			'|-status|p2a: Moth|brn',
			'|-boost|p2a: Moth|spa|2',
			'|-unboost|p2a: Moth|spa|1',
			'|-weather|RainDance',
			'|-sidestart|p2: Beta|move: Tailwind',
			'|-fieldstart|move: Trick Room',
			'|-fieldstart|move: Electric Terrain',
			'|-start|p2a: Moth|confusion',
			'|-singleturn|p2a: Moth|Protect',
			'|-item|p2a: Moth|Leftovers',
			'|-ability|p2a: Moth|Flame Body',
			'|-terastallize|p2a: Moth|Grass',
			'|totally-new-message|future|data',
		].join('\n'));

		assert.equal(tracker.selfName, 'Alpha');
		assert.equal(tracker.opponentName, 'Beta');
		assert.equal(tracker.turn, 3);
		assert.equal(tracker.opponentTeam.length, 2);
		assert.equal(tracker.opponentActive.right.apparentSpecies, 'Volcarona');
		assert.equal(tracker.opponentActive.right.teamID, 'opponent_0');
		assert.equal(tracker.opponentActive.left.apparentSpecies, 'Roaring Moon');
		assert.equal(tracker.opponentActive.right.health.exact, false);
		assert.equal(tracker.opponentActive.right.health.percent, 73);
		assert.equal(tracker.opponentActive.right.status, 'brn');
		assert.equal(tracker.opponentActive.right.boosts.spa, 1);
		assert.deepEqual(tracker.opponentActive.right.transformation, { kind: 'terastallize' });
		assert.deepEqual(tracker.opponentActive.right.types, ['Grass']);
		assert(tracker.opponentActive.right.volatiles.has('confusion'));
		assert(!tracker.opponentActive.right.volatiles.has('protect'));
		assert.equal(tracker.weather, 'raindance');
		assert.equal(tracker.opponentSideConditions.tailwind.started_turn, 3);
		assert.equal(tracker.fieldConditions.trickroom.started_turn, 3);
		assert.equal(tracker.fieldConditions.electricterrain.started_turn, 3);
		assert.equal(tracker.history.at(-1).type, 'totally-new-message');
	});

	it('keeps Illusion identities unknown until a public replace event', () => {
		const tracker = new StateTracker('p1');
		const opponentTeam = Teams.pack([
			{ name: 'Mask', species: 'Zoroark', item: 'focussash', ability: 'illusion', teraType: 'Dark', moves: ['nightdaze'] },
			{ name: 'Dragon', species: 'Dragonite', item: 'lumberry', ability: 'multiscale', teraType: 'Normal', moves: ['extremespeed'] },
		]);
		tracker.consume(`|showteam|p2|${opponentTeam}\n|switch|p2a: Dragon|Dragonite, L50|100/100`);
		assert.equal(tracker.opponentActive.right.teamID, null);
		tracker.consume('|replace|p2a: Mask|Zoroark, L50|100/100');
		assert.equal(tracker.opponentActive.right.teamID, 'opponent_0');
	});

	it('tracks explicit public type changes and additions until they end or switch', () => {
		const tracker = new StateTracker('p1');
		const opponentTeam = Teams.pack([
			{ name: 'Moth', species: 'Volcarona', item: 'leftovers', ability: 'flamebody', moves: ['heatwave'] },
		]);
		tracker.consume([
			`|showteam|p2|${opponentTeam}`,
			'|switch|p2a: Moth|Volcarona, L50|100/100',
			"|-start|p2a: Moth|typeadd|Ghost|[from] move: Trick-or-Treat",
		].join('\n'));
		assert.deepEqual(tracker.opponentActive.right.types, ['Bug', 'Fire', 'Ghost']);

		tracker.consume('|-start|p2a: Moth|typechange|Water|[from] move: Soak');
		assert.deepEqual(tracker.opponentActive.right.types, ['Water']);

		tracker.consume("|-start|p2a: Moth|typeadd|Ghost|[from] move: Trick-or-Treat");
		assert.deepEqual(tracker.opponentActive.right.types, ['Water', 'Ghost']);
		tracker.consume('|-end|p2a: Moth|typeadd|Ghost');
		assert.deepEqual(tracker.opponentActive.right.types, ['Water']);
		tracker.consume('|-end|p2a: Moth|typechange|[silent]');
		assert.deepEqual(tracker.opponentActive.right.types, ['Bug', 'Fire']);

		tracker.consume('|switch|p2a: Moth|Volcarona, L50|100/100');
		assert.deepEqual(tracker.opponentActive.right.types, ['Bug', 'Fire']);
	});

	it('tracks type protocol conservatively while Illusion leaves identity unresolved', () => {
		const tracker = new StateTracker('p1');
		const opponentTeam = Teams.pack([
			{ name: 'Mask', species: 'Zoroark', item: 'focussash', ability: 'illusion', moves: ['nightdaze'] },
			{ name: 'Dragon', species: 'Dragonite', item: 'lumberry', ability: 'multiscale', moves: ['extremespeed'] },
		]);
		tracker.consume([
			`|showteam|p2|${opponentTeam}`,
			'|switch|p2a: Dragon|Dragonite, L50|100/100',
			"|-start|p2a: Dragon|typeadd|Ghost|[from] move: Trick-or-Treat",
		].join('\n'));
		assert.equal(tracker.opponentActive.right.teamID, null);
		assert.equal(tracker.opponentActive.right.types, null);

		tracker.consume('|-start|p2a: Dragon|typechange|[from] move: Reflect Type|[of] p1a: Hidden');
		assert.equal(tracker.opponentActive.right.types, null);
		tracker.consume('|-start|p2a: Dragon|typechange|Water|[from] move: Soak');
		assert.deepEqual(tracker.opponentActive.right.types, ['Water']);
		tracker.consume("|-start|p2a: Dragon|typeadd|Ghost|[from] move: Trick-or-Treat");
		assert.deepEqual(tracker.opponentActive.right.types, ['Water', 'Ghost']);

		tracker.consume('|replace|p2a: Mask|Zoroark, L50|100/100');
		assert.equal(tracker.opponentActive.right.teamID, 'opponent_0');
		assert.deepEqual(tracker.opponentActive.right.types, ['Water', 'Ghost']);
	});

	it('tracks own boosts and volatiles solely from the player stream', () => {
		const tracker = new StateTracker('p1');
		tracker.consume('|switch|p1a: Hero|Arcanine, L50|200/200\n|-boost|p1a: Hero|atk|1\n|-start|p1a: Hero|substitute');
		const observed = tracker.ownObservationForIdent('p1: Hero');
		assert.equal(observed.boosts.atk, 1);
		assert(observed.volatiles.has('substitute'));
	});

	it('copies boosts from the protocol source to the target', () => {
		const tracker = new StateTracker('p1');
		tracker.consume([
			'|switch|p2a: Source|Volcarona, L50|100/100',
			'|switch|p2b: Target|Roaring Moon, L50|100/100',
			'|-boost|p2a: Source|spa|2',
			'|-copyboost|p2a: Source|p2b: Target|spa',
		].join('\n'));
		assert.equal(tracker.opponentActive.right.boosts.spa, 2);
		assert.equal(tracker.opponentActive.left.boosts.spa, 2);
	});

	it('keeps OTS item and ability knowledge immutable from current active state', () => {
		const tracker = new StateTracker('p1');
		const opponentTeam = Teams.pack([
			{ name: 'Moth', species: 'Volcarona', item: 'leftovers', ability: 'flamebody', moves: ['heatwave'] },
		]);
		tracker.consume([
			`|showteam|p2|${opponentTeam}`,
			'|switch|p2a: Moth|Volcarona, L50|100/100',
			'|-enditem|p2a: Moth|Leftovers',
			'|-endability|p2a: Moth|Flame Body',
		].join('\n'));
		assert.equal(tracker.opponentTeam[0].item, 'leftovers');
		assert.equal(tracker.opponentTeam[0].ability, 'flamebody');
		assert.equal(tracker.opponentActive.right.item, null);
		assert.equal(tracker.opponentActive.right.ability, null);

		tracker.consume('|switch|p2a: Moth|Volcarona, L50|100/100');
		assert.equal(tracker.opponentActive.right.item, null);
		assert.equal(tracker.opponentActive.right.ability, 'flamebody');
	});
});
