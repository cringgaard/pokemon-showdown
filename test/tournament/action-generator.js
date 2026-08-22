'use strict';

const assert = require('../assert');
const { generateLegalActions } = require('../../dist/tournament/actions/action-generator');
const { adaptAction } = require('../../dist/tournament/actions/action-adapter');
const { validateResponse } = require('../../dist/tournament/actions/action-validator');

const teamIDs = ['team_0', 'team_1', 'team_2', 'team_3', 'team_4', 'team_5'];
const FORMAT = 'gen9championsvgc2026regmb';

function sidePokemon() {
	return teamIDs.map((id, index) => ({
		ident: `p1: Mon ${index}`,
		details: 'Pikachu, L50',
		condition: '100/100',
		active: index < 2,
		stats: { atk: 1, def: 1, spa: 1, spd: 1, spe: 1 },
		moves: ['thunderbolt'],
		baseAbility: 'static',
		ability: 'static',
		item: '',
		pokeball: 'pokeball',
	}));
}

function moveRequest(overrides = {}) {
	return {
		active: [
			{
				moves: [
					{ move: 'Thunderbolt', id: 'thunderbolt', pp: 15, maxpp: 15, target: 'normal' },
					{ move: 'Protect', id: 'protect', pp: 16, maxpp: 16, target: 'self' },
				],
				canTerastallize: 'Electric',
			},
			{
				moves: [{ move: 'Discharge', id: 'discharge', pp: 15, maxpp: 15, target: 'allAdjacent' }],
				canTerastallize: 'Electric',
			},
		],
		side: { name: 'Bot', id: 'p1', pokemon: sidePokemon() },
		...overrides,
	};
}

describe('Tournament action generator', () => {
	it('generates all ordered bring-four Team Preview selections', () => {
		const request = {
			teamPreview: true,
			maxChosenTeamSize: 4,
			side: { name: 'Bot', id: 'p1', pokemon: sidePokemon() },
		};
		const generated = generateLegalActions(request, { teamIDs, format: FORMAT });
		assert.equal(generated.kind, 'team_preview');
		assert.equal(generated.legal_actions.length, 360);
		assert.equal(adaptAction(generated.legal_actions[0], request, teamIDs), 'team 1234');
	});

	it('expands transformations while filtering double use and duplicate switches', () => {
		const request = moveRequest();
		const generated = generateLegalActions(request, { teamIDs, format: FORMAT });
		assert.equal(generated.kind, 'turn');
		assert.deepEqual(generated.slots.left.moves[0].legal_targets, ['ally', 'opponent_left', 'opponent_right']);
		assert.deepEqual(generated.slots.left.moves[1].legal_targets, []);
		assert.deepEqual(generated.slots.right.moves[0].legal_targets, []);
		assert(!generated.legal_actions.some(action => (
			action.actions.left?.transformation && action.actions.right?.transformation
		)));
		assert(!generated.legal_actions.some(action => (
			action.actions.left?.type === 'switch' && action.actions.right?.type === 'switch' &&
			action.actions.left.pokemon === action.actions.right.pokemon
		)));
	});

	it('exposes real Mega requests semantically and adapts only at the Showdown boundary', () => {
		const pokemon = sidePokemon();
		pokemon[0] = { ...pokemon[0], details: 'Aggron, L50', item: 'aggronite', ability: 'sturdy', baseAbility: 'sturdy' };
		pokemon[1] = { ...pokemon[1], details: 'Raichu, L50', item: 'raichunitex', ability: 'static', baseAbility: 'static' };
		const request = moveRequest({
			active: [
				{ moves: [{ move: 'Protect', id: 'protect', pp: 5, maxpp: 5, target: 'self' }], canMegaEvo: true },
				{ moves: [{ move: 'Protect', id: 'protect', pp: 5, maxpp: 5, target: 'self' }], canMegaEvo: true },
			],
			side: { name: 'Bot', id: 'p1', pokemon },
		});
		const generated = generateLegalActions(request, { teamIDs, format: FORMAT });
		assert.deepEqual(generated.slots.left.available_transformations, [
			{ kind: 'mega', result_species: 'Aggron-Mega' },
		]);
		assert.deepEqual(generated.slots.right.available_transformations, [
			{ kind: 'mega', result_species: 'Raichu-Mega-X' },
		]);
		const mega = generated.legal_actions.find(action =>
			action.actions.left?.transformation === 'mega' && action.actions.right?.type === 'move' &&
			!action.actions.right.transformation
		);
		assert(mega);
		assert.equal(adaptAction(mega, request, teamIDs), 'move 1 mega, move 1');
		assert(!generated.legal_actions.some(action =>
			action.actions.left?.transformation === 'mega' && action.actions.right?.transformation === 'mega'
		));
	});

	it('uses format-aware public move metadata', () => {
		const request = moveRequest({
			active: [
				{ moves: [{ move: 'Growth', id: 'growth', pp: 20, maxpp: 20, target: 'self' }] },
				{ moves: [{ move: 'Protect', id: 'protect', pp: 5, maxpp: 5, target: 'self' }] },
			],
		});
		const champions = generateLegalActions(request, { teamIDs, format: FORMAT });
		const standard = generateLegalActions(request, { teamIDs, format: 'gen9doublescustomgame' });
		assert.equal(champions.slots.left.moves[0].type, 'Grass');
		assert.equal(standard.slots.left.moves[0].type, 'Normal');
	});

	it('handles trapped slots, non-required fainted slots, and semantic translation', () => {
		const pokemon = sidePokemon();
		pokemon[1].condition = '0 fnt';
		const request = moveRequest({
			active: [
				{ moves: [{ move: 'Thunderbolt', id: 'thunderbolt', pp: 15, maxpp: 15, target: 'normal' }], trapped: true },
				{ moves: [{ move: 'Protect', id: 'protect', pp: 16, maxpp: 16, target: 'self' }] },
			],
			side: { name: 'Bot', id: 'p1', pokemon },
		});
		const generated = generateLegalActions(request, { teamIDs, format: FORMAT });
		assert.equal(generated.slots.left.switches.length, 0);
		assert.equal(generated.slots.right.required, false);
		const action = generated.legal_actions.find(candidate => candidate.actions.left?.target === 'opponent_right');
		assert.equal(adaptAction(action, request, teamIDs), 'move 1 1, pass');
		const leftTarget = generated.legal_actions.find(candidate => candidate.actions.left?.target === 'opponent_left');
		assert.equal(adaptAction(leftTarget, request, teamIDs), 'move 1 2, pass');
		assert.deepEqual(validateResponse(generated, JSON.parse(JSON.stringify(action))), action);
		assert.equal(validateResponse(generated, { actions: { left: { type: 'move', move: 'splash' } } }), null);
	});

	it('supports one and two-slot forced switches', () => {
		const one = generateLegalActions({
			forceSwitch: [true, false],
			side: { name: 'Bot', id: 'p1', pokemon: sidePokemon() },
		}, { teamIDs, format: FORMAT });
		assert.equal(one.kind, 'forced_switch');
		assert(one.legal_actions.every(action => action.actions.left && !action.actions.right));

		const two = generateLegalActions({
			forceSwitch: [true, true],
			side: { name: 'Bot', id: 'p1', pokemon: sidePokemon() },
		}, { teamIDs, format: FORMAT });
		assert(two.legal_actions.every(action => action.actions.left.pokemon !== action.actions.right.pokemon));
	});

	it('distributes one viable forced switch across either fainted active slot', () => {
		const pokemon = sidePokemon();
		pokemon[0].condition = '0 fnt';
		pokemon[1].condition = '0 fnt';
		for (let i = 3; i < pokemon.length; i++) pokemon[i].condition = '0 fnt';
		const request = {
			forceSwitch: [true, true],
			side: { name: 'Bot', id: 'p1', pokemon },
		};
		const generated = generateLegalActions(request, { teamIDs, format: FORMAT });
		assert.deepEqual(generated.legal_actions, [
			{ actions: { left: { type: 'switch', pokemon: 'team_2' } } },
			{ actions: { right: { type: 'switch', pokemon: 'team_2' } } },
		]);
		assert.deepEqual(generated.legal_actions.map(action => adaptAction(action, request, teamIDs)), [
			'switch 3, pass',
			'pass, switch 3',
		]);
	});

	it('represents Revival Blessing selection as a revive action over fainted Pokemon', () => {
		const pokemon = sidePokemon();
		pokemon[0].reviving = true;
		pokemon[2].condition = '0 fnt';
		const request = {
			forceSwitch: [true, false],
			side: { name: 'Bot', id: 'p1', pokemon },
		};
		const generated = generateLegalActions(request, { teamIDs, format: FORMAT });
		assert.deepEqual(generated.slots.left.switches, []);
		assert.deepEqual(generated.slots.left.revives, ['team_2']);
		assert.deepEqual(generated.legal_actions, [
			{ actions: { left: { type: 'revive', pokemon: 'team_2' } } },
		]);
		assert.equal(adaptAction(generated.legal_actions[0], request, teamIDs), 'switch 3, pass');
	});

	it('allows normal moves to target allies while keeping adjacentFoe foe-only', () => {
		const request = moveRequest();
		request.active[0].moves.push({
			move: 'Fake Out', id: 'fakeout', pp: 10, maxpp: 10, target: 'adjacentFoe',
		});
		const generated = generateLegalActions(request, { teamIDs, format: FORMAT });
		assert(generated.slots.left.moves.find(move => move.id === 'thunderbolt').legal_targets.includes('ally'));
		assert(!generated.slots.left.moves.find(move => move.id === 'fakeout').legal_targets.includes('ally'));
	});

	it('keeps maybeTrapped switches provisionally legal', () => {
		const request = moveRequest();
		request.active[0].maybeTrapped = true;
		const generated = generateLegalActions(request, { teamIDs, format: FORMAT });
		assert(generated.slots.left.switches.length > 0);
	});

	it('keeps disabled moves in slot metadata but excludes them from legal actions', () => {
		const request = moveRequest();
		request.active[0].moves[0].disabled = true;
		const generated = generateLegalActions(request, { teamIDs, format: FORMAT });
		const disabled = generated.slots.left.moves.find(move => move.id === 'thunderbolt');
		assert(disabled);
		assert.equal(disabled.disabled, true);
		assert.deepEqual(disabled.legal_targets, []);
		assert(!generated.legal_actions.some(action => action.actions.left?.move === 'thunderbolt'));
	});
});
