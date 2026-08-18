'use strict';

const assert = require('../assert');
const { adaptAction } = require('../../dist/tournament/actions/action-adapter');
const { buildBotState } = require('../../dist/tournament/state/state-builder');
const { StateTracker } = require('../../dist/tournament/state/state-tracker');
const { BattlePlayer, BattleStream, getPlayerStreams } = require('../../dist/sim/battle-stream');
const { Teams } = require('../../dist/sim/teams');
const { RandomPlayerAI } = require('../../dist/sim/tools/random-player-ai');

class RevivalPlayer extends BattlePlayer {
	constructor(stream, revived) {
		super(stream);
		this.tracker = new StateTracker('p1');
		this.revived = revived;
		this.moveRequests = 0;
		this.usedSemanticRevive = false;
	}

	receive(chunk) {
		this.tracker.consume(chunk);
		super.receive(chunk);
	}

	receiveLine(line) {
		super.receiveLine(line);
		if (line.includes('[from] move: Revival Blessing')) this.revived();
	}

	receiveRequest(request) {
		this.tracker.registerRequest(request);
		if (request.wait) return;
		if (request.teamPreview) {
			this.choose('team 123');
			return;
		}
		if (request.forceSwitch) {
			if (request.side.pokemon.some(mon => mon.reviving)) {
				const teamIDs = this.tracker.teamIDsForRequest(request);
				const state = buildBotState(this.tracker, request, {
					format: 'gen9doublescustomgame',
					runtime: { decision_id: 1, revision: 0, attempt: 1, previous_error: null, deadline_ms: 1000 },
				});
				const response = state.request.legal_actions.find(action => action.actions.left?.type === 'revive');
				assert(response, 'expected a semantic revive action from the real Showdown request');
				assert(state.request.slots.left.revives.length > 0);
				this.usedSemanticRevive = true;
				this.choose(adaptAction(response, request, teamIDs));
				return;
			}
			this.choose('switch 3, pass');
			return;
		}
		this.moveRequests++;
		if (this.moveRequests === 1) this.choose('move memento 1, move splash');
		else if (this.moveRequests === 2) this.choose('move revivalblessing, move splash');
		else this.choose('move splash, move splash');
	}
}

describe('Tournament Revival Blessing integration', () => {
	it('round-trips a semantic revive action through a real BattleStream', async function () {
		this.timeout(10_000);
		const battleStream = new BattleStream({ noCatch: true });
		const streams = getPlayerStreams(battleStream);
		let complete;
		const revived = new Promise(resolve => { complete = resolve; });
		const p1 = new RevivalPlayer(streams.p1, complete);
		const p2 = new RandomPlayerAI(streams.p2);
		const players = Promise.all([p1.start(), p2.start()]);
		const p1Team = Teams.pack([
			{ species: 'Corviknight', ability: 'Pressure', moves: ['Memento'] },
			{ species: 'Smeargle', ability: 'Own Tempo', moves: ['Splash'] },
			{ species: 'Pawmot', ability: 'Natural Cure', moves: ['Revival Blessing', 'Splash'] },
		]);
		const p2Team = Teams.pack([
			{ species: 'Magikarp', ability: 'Swift Swim', moves: ['Splash'] },
			{ species: 'Feebas', ability: 'Swift Swim', moves: ['Splash'] },
		]);

		try {
			await streams.omniscient.write([
				`>start ${JSON.stringify({ formatid: 'gen9doublescustomgame', seed: [1, 2, 3, 4] })}`,
				`>player p1 ${JSON.stringify({ name: 'Semantic Bot', team: p1Team })}`,
				`>player p2 ${JSON.stringify({ name: 'Random Bot', team: p2Team })}`,
			].join('\n'));
			let revivalTimer;
			try {
				await Promise.race([
					revived,
					new Promise((resolve, reject) => {
						revivalTimer = setTimeout(() => reject(new Error('Revival Blessing timed out')), 5000);
					}),
				]);
			} finally {
				clearTimeout(revivalTimer);
			}
			assert.equal(p1.usedSemanticRevive, true);
			await streams.omniscient.write('>forcewin p1');
			await players;
		} finally {
			if (!battleStream.atEOF) await streams.omniscient.writeEnd();
		}
	});
});
