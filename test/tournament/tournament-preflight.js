'use strict';

const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const assert = require('../assert');
const { loadTournamentConfig } = require('../../dist/tournament/orchestrator/config');
const {
	assertPortAvailable, rendererDependencies, runTournamentPreflight,
} = require('../../dist/tournament/orchestrator/preflight');

const root = path.resolve(__dirname, '../..');
const team = fs.readFileSync(path.join(root, 'tournament/fixtures/teams/vgc-reg-i.txt'), 'utf8');
const bot = 'def choose_action(state):\n    return state["request"]["legal_actions"][0]\n';

describe('Tournament event preflight', function () {
	this.timeout(10_000);
	let temporaryRoot;

	beforeEach(() => {
		temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'showdown-preflight-'));
	});

	afterEach(() => fs.rmSync(temporaryRoot, { recursive: true, force: true }));

	it('resolves submissions relative to the config and prepares trusted-host participants', async () => {
		makeSubmission('submissions/alpha');
		makeSubmission('submissions/beta');
		const config = makeConfig();
		const port = await availablePort();
		const result = await runTournamentPreflight({
			config,
			outputDirectory: path.join(temporaryRoot, 'results'),
			spectatorPort: port,
			rendererCheck: async () => ({
				url: 'https://play.pokemonshowdown.com/js/replay-embed.js', dependencies: ['official.js'],
				reachable: true, errors: [],
			}),
		});
		assert.equal(result.ready, true);
		assert.equal(result.prepared.size, 2);
		assert.equal(result.prepared.get('alpha').submission.name, 'Alpha Bot');
		assert.equal(result.prepared.get('alpha').workerFactory.audit.kind, 'host');
		assert(result.warnings.some(warning => /not isolated/.test(warning)));
		assert(fs.statSync(path.join(temporaryRoot, 'results/state.json')).isFile());
	});

	it('fails closed on an unreachable official renderer unless explicitly overridden', async () => {
		makeSubmission('submissions/alpha');
		makeSubmission('submissions/beta');
		const options = {
			config: makeConfig(), outputDirectory: path.join(temporaryRoot, 'renderer-results'),
			spectatorPort: await availablePort(),
			rendererCheck: async () => ({
				url: 'official', dependencies: [], reachable: false, errors: ['network unavailable'],
			}),
		};
		await assert.rejects(runTournamentPreflight(options), /Official Showdown renderer preflight failed/);
		const allowed = await runTournamentPreflight({ ...options, allowRendererUnreachable: true });
		assert(allowed.warnings.some(warning => /network unavailable/.test(warning)));
	});

	it('extracts every hosted dependency declared by the official embed adapter', () => {
		const source = [
			"linkStyle('https://play.pokemonshowdown.com/style/battle.css?a7');",
			"requireScript('https://play.pokemonshowdown.com/js/battle.js?a7');",
			"requireScript('https://play.pokemonshowdown.com/js/battle.js?a7');",
		].join('\n');
		assert.deepEqual(rendererDependencies(source), [
			'https://play.pokemonshowdown.com/js/battle.js?a7',
			'https://play.pokemonshowdown.com/style/battle.css?a7',
		]);
	});

	it('reports an occupied spectator port before tournament play', async () => {
		const blocker = net.createServer();
		await new Promise((resolve, reject) => {
			blocker.once('error', reject);
			blocker.listen(0, '127.0.0.1', resolve);
		});
		const address = blocker.address();
		try {
			await assert.rejects(assertPortAvailable(address.port), /Spectator port.*unavailable/);
		} finally {
			await new Promise((resolve, reject) => {
				blocker.close(error => error ? reject(error) : resolve());
			});
		}
	});

	function makeSubmission(relative) {
		const directory = path.join(temporaryRoot, relative);
		fs.mkdirSync(directory, { recursive: true });
		fs.writeFileSync(path.join(directory, 'main.py'), bot);
		fs.writeFileSync(path.join(directory, 'team.txt'), team);
	}

	function makeConfig() {
		const filename = path.join(temporaryRoot, 'event.json');
		fs.writeFileSync(filename, JSON.stringify({
			title: 'Company Cup', format: 'gen9vgc2025regi', seed: '2026', runtime: 'host',
			participants: [
				{ id: 'beta', name: 'Beta Bot', submission: 'submissions/beta' },
				{ id: 'alpha', name: 'Alpha Bot', submission: 'submissions/alpha' },
			],
			round_robin: { games_per_pairing: 1 }, final: { qualifiers: 2, best_of: 3 },
		}));
		const loaded = loadTournamentConfig(filename);
		assert.deepEqual(loaded.config.participants.map(participant => participant.id), ['alpha', 'beta']);
		return loaded;
	}
});

function availablePort() {
	return new Promise((resolve, reject) => {
		const server = net.createServer();
		server.once('error', reject);
		server.listen(0, '127.0.0.1', () => {
			const address = server.address();
			server.close(error => error ? reject(error) : resolve(address.port));
		});
	});
}
