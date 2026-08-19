'use strict';

const { execFile } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { promisify } = require('util');
const assert = require('../assert');

const execFileAsync = promisify(execFile);
const root = path.resolve(__dirname, '../..');
const cli = path.join(root, 'dist/tournament/cli.js');
const team = fs.readFileSync(path.join(root, 'tournament/fixtures/teams/vgc-reg-i.txt'), 'utf8');
const bot = fs.readFileSync(path.join(root, 'tournament/reference-bots/random/main.py'), 'utf8');

describe('Tournament participant CLI', function () {
	this.timeout(40_000);
	let temporaryRoot;

	beforeEach(() => {
		temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'showdown-cli-'));
	});

	afterEach(() => {
		fs.rmSync(temporaryRoot, { recursive: true, force: true });
	});

	function makeSubmission(name) {
		const directory = path.join(temporaryRoot, name);
		fs.mkdirSync(directory);
		fs.writeFileSync(path.join(directory, 'main.py'), bot);
		fs.writeFileSync(path.join(directory, 'team.txt'), team);
		return directory;
	}

	it('validates a directory and runs two directories into self-contained ordered artifacts', async () => {
		const p1 = makeSubmission('Alice Bot');
		const p2 = makeSubmission('Bob Bot');
		const output = path.join(temporaryRoot, 'result');
		const validated = await execFileAsync(process.execPath, [cli, 'validate', p1], { cwd: root });
		const validation = JSON.parse(validated.stdout);
		assert.equal(validation.valid, true);
		assert.equal(validation.team_size, 6);

		const completed = await execFileAsync(process.execPath, [
			cli, 'match', p1, p2, '--seed', '1234', '--output', output,
			'--decision-timeout-ms', '1000', '--match-timeout-ms', '20000',
		], { cwd: root, timeout: 30_000 });
		const summary = JSON.parse(completed.stdout);
		assert(summary.winner || summary.tie);
		assert.equal(summary.seed, '1234,0,0,0');

		const expected = [
			'result.json', 'metadata.json', 'battle.protocol.log', 'p1-runtime.log', 'p2-runtime.log',
			'bot-state-snapshots/p1.jsonl', 'bot-state-snapshots/p2.jsonl',
		];
		for (const filename of expected) assert(fs.statSync(path.join(output, filename)).isFile(), filename);
		const metadata = JSON.parse(fs.readFileSync(path.join(output, 'metadata.json'), 'utf8'));
		const result = JSON.parse(fs.readFileSync(path.join(output, 'result.json'), 'utf8'));
		assert.equal(metadata.schema_version, 1);
		assert.equal(metadata.participants.p1.id, 'alice-bot');
		assert.equal(result.schema_version, 1);
		assert.deepEqual(result.players.p1.stats, {
			decisions: result.players.p1.stats.decisions,
			timeouts: 0,
			invalid_responses: 0,
			fallbacks: 0,
			exceptions: 0,
		});

		const protocol = fs.readFileSync(path.join(output, 'battle.protocol.log'), 'utf8');
		assert(protocol.length > 0);
		assert(protocol.indexOf('|start') < protocol.indexOf('|turn|1'));
		assert(protocol.indexOf('|turn|1') < Math.max(protocol.lastIndexOf('|win|'), protocol.lastIndexOf('|tie')));
		const p1States = fs.readFileSync(path.join(output, 'bot-state-snapshots/p1.jsonl'), 'utf8')
			.trim().split('\n').map(line => JSON.parse(line));
		assert(p1States.length > 0);
		for (const state of p1States) {
			for (const pokemon of state.opponent.team) {
				assert(!Object.hasOwn(pokemon, 'stats'));
				assert(!Object.hasOwn(pokemon, 'evs'));
				assert(!Object.hasOwn(pokemon, 'ivs'));
			}
		}
	});
});
