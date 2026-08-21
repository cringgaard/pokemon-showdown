'use strict';

const assert = require('../assert');
const fs = require('fs');
const path = require('path');
const { adaptAction } = require('../../dist/tournament/actions/action-adapter');
const { buildBotState } = require('../../dist/tournament/state/state-builder');
const { StateTracker } = require('../../dist/tournament/state/state-tracker');
const { BattlePlayer, BattleStream, getPlayerStreams } = require('../../dist/sim/battle-stream');
const { Dex } = require('../../dist/sim/dex');
const { Teams } = require('../../dist/sim/teams');
const { TeamValidator } = require('../../dist/sim/team-validator');

const FORMAT = 'gen9championsvgc2026regmb';
const CHAMPIONS_TEAM = fs.readFileSync(path.resolve(__dirname, '../../tournament/fixtures/teams/champions-snow.txt'), 'utf8');
const RUNTIME = {
	decision_id: 1, revision: 0, attempt: 1, previous_error: null, deadline_ms: 1000,
};

class SemanticMegaPlayer extends BattlePlayer {
	constructor(stream, sideID, useMega, observed) {
		super(stream);
		this.tracker = new StateTracker(sideID, FORMAT);
		this.useMega = useMega;
		this.observed = observed;
		this.turnRequests = 0;
	}

	receive(chunk) {
		this.tracker.consume(chunk);
		super.receive(chunk);
	}

	receiveRequest(request) {
		if (request.wait) return;
		const teamIDs = this.tracker.teamIDsForRequest(request);
		const state = buildBotState(this.tracker, request, { format: FORMAT, runtime: RUNTIME });
		if (request.teamPreview) {
			assert.equal(state.request.legal_actions.length, 360);
			assert.equal(state.opponent.team.length, 6);
			this.choose(adaptAction(state.request.legal_actions[0], request, teamIDs));
			return;
		}
		if (request.forceSwitch) {
			this.choose(adaptAction(state.request.legal_actions[0], request, teamIDs));
			return;
		}
		this.turnRequests++;
		if (this.turnRequests === 2) this.observed(state);
		if (this.useMega && this.turnRequests === 1) {
			assert(state.request.slots.left.available_transformations.some(option => option.kind === 'mega'));
			assert(state.request.slots.right.available_transformations.some(option => option.kind === 'mega'));
			assert(Object.values(state.request.slots).every(slot =>
				slot.available_transformations.every(option => option.kind === 'mega')
			));
		}
		const response = state.request.legal_actions.find(action => {
			const moves = Object.values(action.actions);
			if (!moves.length || moves.some(action => action.type !== 'move')) return false;
			if (this.useMega && this.turnRequests === 1) {
				return action.actions.left?.transformation === 'mega' && !action.actions.right?.transformation;
			}
			return moves.every(action => !action.transformation);
		});
		assert(response, 'expected a complete semantic move response');
		this.choose(adaptAction(response, request, teamIDs));
	}
}

function packedTeam(lead) {
	const secondMega = lead.species === 'Raichu' ?
		{ species: 'Aggron', item: 'Aggronite', ability: 'Sturdy' } :
		{ species: 'Raichu', item: 'Raichunite X', ability: 'Static' };
	return Teams.pack([
		{ ...lead, level: 50, nature: 'Hardy', evs: { hp: 32, atk: 2, def: 32 }, moves: ['Protect'] },
		{ ...secondMega, level: 50, moves: ['Protect'] },
		{ species: 'Feebas', ability: 'Swift Swim', level: 50, moves: ['Protect'] },
		{ species: 'Caterpie', ability: 'Shield Dust', level: 50, moves: ['Protect'] },
		{ species: 'Weedle', ability: 'Shield Dust', level: 50, moves: ['Protect'] },
		{ species: 'Wurmple', ability: 'Shield Dust', level: 50, moves: ['Protect'] },
	]);
}

async function observeMega(lead) {
	const battleStream = new BattleStream({ noCatch: true });
	const streams = getPlayerStreams(battleStream);
	let ownState;
	let opponentState;
	let complete;
	const observed = new Promise(resolve => { complete = resolve; });
	const capture = (side, state) => {
		if (side === 'own') ownState = state;
		else opponentState = state;
		if (ownState && opponentState) complete();
	};
	const p1 = new SemanticMegaPlayer(streams.p1, 'p1', true, state => capture('own', state));
	const p2 = new SemanticMegaPlayer(streams.p2, 'p2', false, state => capture('opponent', state));
	const players = Promise.all([p1.start(), p2.start()]);
	try {
		await streams.omniscient.write([
			`>start ${JSON.stringify({ formatid: FORMAT, seed: [1, 2, 3, 4] })}`,
			`>player p1 ${JSON.stringify({ name: 'Mega Bot', team: packedTeam(lead) })}`,
			`>player p2 ${JSON.stringify({ name: 'Observer', team: packedTeam({ species: 'Abra', ability: 'Synchronize' }) })}`,
			'>show-openteamsheets',
		].join('\n'));
		let timer;
		try {
			await Promise.race([
				observed,
				new Promise((resolve, reject) => {
					timer = setTimeout(() => reject(new Error(`Mega observation timed out for ${lead.species}`)), 5000);
				}),
			]);
		} finally {
			clearTimeout(timer);
		}
		await streams.omniscient.write('>forcewin p1');
		await players;
		return { ownState, opponentState };
	} finally {
		if (!battleStream.atEOF) await streams.omniscient.writeEnd();
	}
}

describe('Champions tournament harness compatibility', function () {
	this.timeout(30_000);

	for (const scenario of [
		{ species: 'Aggron', item: 'Aggronite', ability: 'Sturdy', result: 'Aggron-Mega', types: ['Steel'], currentAbility: 'filter' },
		{ species: 'Charizard', item: 'Charizardite X', ability: 'Blaze', result: 'Charizard-Mega-X', types: ['Fire', 'Dragon'], currentAbility: 'toughclaws' },
		{ species: 'Charizard', item: 'Charizardite Y', ability: 'Blaze', result: 'Charizard-Mega-Y', types: ['Fire', 'Flying'], currentAbility: 'drought', weather: 'sunnyday' },
		{ species: 'Raichu', item: 'Raichunite X', ability: 'Static', result: 'Raichu-Mega-X', types: ['Electric'], currentAbility: 'electricsurge', condition: 'electricterrain' },
		{ species: 'Raichu', item: 'Raichunite Y', ability: 'Static', result: 'Raichu-Mega-Y', types: ['Electric'], currentAbility: 'noguard' },
	]) {
		it(`round-trips ${scenario.result} and exposes its public post-Mega state`, async () => {
			const { ownState, opponentState } = await observeMega(scenario);
			const own = ownState.self.team.find(pokemon => pokemon.id === ownState.self.active.left);
			assert.equal(own.species, scenario.result);
			assert.deepEqual(own.types, scenario.types);
			assert.equal(own.ability, scenario.currentAbility);
			assert.deepEqual(own.transformation, { kind: 'mega' });
			const opponent = Object.values(opponentState.opponent.active).find(active =>
				active.apparent_species === scenario.result
			);
			assert(opponent);
			assert.equal(opponent.team_id, 'opponent_0');
			assert.deepEqual(opponent.types, scenario.types);
			assert.equal(opponent.ability, scenario.currentAbility);
			assert.deepEqual(opponent.transformation, { kind: 'mega' });
			assert(ownState.request.legal_actions.every(action =>
				Object.values(action.actions).every(action => action.type !== 'move' || !action.transformation)
			));
			if (scenario.weather) assert.equal(ownState.field.weather, scenario.weather);
			if (scenario.condition) assert(ownState.field.conditions[scenario.condition]);
		});
	}

	it('keeps Mega state Illusion-safe when public identity remains unresolved', () => {
		const tracker = new StateTracker('p1', FORMAT);
		const team = Teams.pack([
			{ species: 'Zoroark', ability: 'Illusion', item: 'Focus Sash', moves: ['Night Daze'] },
			{ species: 'Aggron', ability: 'Sturdy', item: 'Aggronite', moves: ['Protect'] },
		]);
		tracker.consume([
			`|showteam|p2|${team}`,
			'|switch|p2a: Zoroark|Zoroark, L50|100/100',
			'|-mega|p2a: Zoroark|Zoroark|Aggronite',
		].join('\n'));
		assert.equal(tracker.opponentActive.right.teamID, null);
		assert.equal(tracker.opponentActive.right.apparentSpecies, 'Zoroark');
		assert.deepEqual(tracker.opponentActive.right.types, ['Dark']);
		assert.deepEqual(tracker.opponentActive.right.transformation, { kind: 'mega' });
		assert.equal(tracker.opponentActive.right.ability, null);
	});

	it('uses the authoritative Champions form and Stat Point rules', () => {
		Dex.includeData();
		const dex = Dex.forFormat(FORMAT);
		const staraptor = dex.species.get('Staraptor-Mega');
		assert(staraptor.types.includes('Flying'));
		assert.equal(dex.getImmunity('Ground', staraptor), false);
		const valid = Teams.import(CHAMPIONS_TEAM);
		assert.equal(TeamValidator.get(FORMAT).validateTeam(valid), null);
		const invalid = valid.map(set => ({ ...set, evs: { ...set.evs } }));
		invalid[0].evs.hp = 33;
		assert(TeamValidator.get(FORMAT).validateTeam(invalid).some(problem => problem.includes('Stat Point')));
	});
});
