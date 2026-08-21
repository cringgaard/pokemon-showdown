'use strict';

const fs = require('fs');
const path = require('path');
const assert = require('../assert');
const { Teams } = require('../../dist/sim/teams');
const { publicTeamSheet } = require('../../dist/tournament/spectator/public-team-sheet');
const { renderTeamSheetHTML } = require('../../dist/tournament/spectator/server');

describe('Tournament public Open Team Sheets', () => {
	it('projects only the allowed public fields from a validated Showdown team', () => {
		const teamText = fs.readFileSync(path.resolve(__dirname, '../../tournament/fixtures/teams/vgc-reg-i.txt'), 'utf8');
		const sheet = publicTeamSheet({
			id: 'alpha', name: 'Alpha', teamText, packedTeam: Teams.pack(Teams.import(teamText)),
			directory: '', mainPath: '', requirementsPath: null,
		});
		assert.equal(sheet.pokemon.length, 6);
		assert.deepEqual(Object.keys(sheet.pokemon[0]).sort(), [
			'ability', 'item', 'moves', 'name', 'species', 'sprite',
		]);
		assert.deepEqual(sheet.pokemon[0], {
			name: 'Incineroar', species: 'Incineroar', sprite: 'incineroar', item: 'Sitrus Berry',
			ability: 'Intimidate', moves: ['Fake Out', 'Flare Blitz', 'Knock Off', 'Protect'],
		});
		const serialized = JSON.stringify(sheet).toLowerCase();
		for (const forbidden of ['evs', 'ivs', 'nature', 'stats', 'level', 'tera_type']) {
			assert(!serialized.includes(`"${forbidden}"`));
		}
	});

	it('renders the public model without the private source export', () => {
		const sheet = {
			participant: { id: 'alpha', name: 'A Very Long Participant Name That Must Remain Safe' },
			pokemon: Array.from({ length: 6 }, (_, index) => ({
				name: `Pokemon ${index}`, species: 'Incineroar', sprite: 'incineroar', item: 'Sitrus Berry',
				ability: 'Intimidate',
				moves: ['A Very Long Move Name', 'Flare Blitz', 'Knock Off', 'Protect'],
			})),
		};
		const html = renderTeamSheetHTML(sheet);
		assert(html.includes('team-card-grid'));
		assert(html.includes('A Very Long Move Name'));
		assert(!/EVs|IVs|Nature|Tera|calculated stats/i.test(html));
	});
});
