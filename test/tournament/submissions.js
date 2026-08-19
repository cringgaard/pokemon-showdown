'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('../assert');
const { Teams } = require('../../dist/sim/teams');
const { DEFAULT_FORMAT } = require('../../dist/tournament/match/match-runner');
const {
	SubmissionValidationError, loadSubmission,
} = require('../../dist/tournament/submissions/submission-loader');

const root = path.resolve(__dirname, '../..');
const team = fs.readFileSync(path.join(root, 'tournament/fixtures/teams/vgc-reg-i.txt'), 'utf8');
const bot = 'def choose_action(state):\n    return state["request"]["legal_actions"][0]\n';

describe('Tournament participant submissions', () => {
	let temporaryRoot;

	beforeEach(() => {
		temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'showdown-submission-'));
	});

	afterEach(() => {
		fs.rmSync(temporaryRoot, { recursive: true, force: true });
	});

	function submission(files = {}) {
		const directory = path.join(temporaryRoot, 'My Great Bot');
		fs.mkdirSync(directory);
		const contents = { 'main.py': bot, 'team.txt': team, ...files };
		for (const [filename, content] of Object.entries(contents)) {
			if (content !== null) fs.writeFileSync(path.join(directory, filename), content);
		}
		return directory;
	}

	it('loads a valid directory and detects optional requirements and arbitrary assets', () => {
		const loaded = loadSubmission(submission({
			'requirements.txt': '# installation deliberately deferred\n',
			'model.bin': 'opaque participant asset',
		}), { format: DEFAULT_FORMAT });
		assert.equal(loaded.id, 'my-great-bot');
		assert.equal(loaded.name, 'My Great Bot');
		assert.equal(path.basename(loaded.mainPath), 'main.py');
		assert.equal(path.basename(loaded.requirementsPath), 'requirements.txt');
		assert(loaded.packedTeam);
	});

	it('reports a missing main.py', () => {
		assert.throws(() => loadSubmission(submission({ 'main.py': null }), { format: DEFAULT_FORMAT }),
			error => error instanceof SubmissionValidationError && /missing required file main\.py/.test(error.message));
	});

	it('reports a missing team.txt', () => {
		assert.throws(() => loadSubmission(submission({ 'team.txt': null }), { format: DEFAULT_FORMAT }),
			error => error instanceof SubmissionValidationError && /missing required file team\.txt/.test(error.message));
	});

	it('reports a team import failure', () => {
		assert.throws(() => loadSubmission(submission({ 'team.txt': '' }), { format: DEFAULT_FORMAT }),
			error => error instanceof SubmissionValidationError && /could not be imported/.test(error.message));
	});

	it('rejects packed team.txt input before Showdown import', () => {
		const packed = Teams.pack(Teams.import(team));
		assert.throws(() => loadSubmission(submission({ 'team.txt': packed }), { format: DEFAULT_FORMAT }),
			error => error instanceof SubmissionValidationError && /packed teams are not accepted/.test(error.message));
	});

	it('rejects JSON team.txt input before Showdown import', () => {
		const json = JSON.stringify(Teams.import(team));
		assert.throws(() => loadSubmission(submission({ 'team.txt': json }), { format: DEFAULT_FORMAT }),
			error => error instanceof SubmissionValidationError && /JSON teams are not accepted/.test(error.message));
	});

	it('reports the tournament team-size contract before starting a match', () => {
		const fivePokemon = team.split(/\r?\n\r?\n/).slice(0, 5).join('\n\n');
		assert.throws(() => loadSubmission(submission({ 'team.txt': fivePokemon }), { format: DEFAULT_FORMAT }),
			error => error instanceof SubmissionValidationError && /exactly 6 Pokemon; found 5/.test(error.message));
	});

	it('surfaces TeamValidator rejection for the configured format', () => {
		const illegal = team.replace('Incineroar @ Sitrus Berry', 'MissingNo @ Sitrus Berry');
		assert.throws(() => loadSubmission(submission({ 'team.txt': illegal }), { format: DEFAULT_FORMAT }),
			error => error instanceof SubmissionValidationError &&
				/invalid for/.test(error.message) && /MissingNo/.test(error.message));
	});
});
