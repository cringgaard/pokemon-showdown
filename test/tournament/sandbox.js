'use strict';

const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('../assert');
const { BotController } = require('../../dist/tournament/bots/runtime');
const { loadReplayArtifacts } = require('../../dist/tournament/spectator/replay-loader');
const { MatchRunner, DEFAULT_FORMAT } = require('../../dist/tournament/match/match-runner');
const { loadTournamentConfig } = require('../../dist/tournament/orchestrator/config');
const { TournamentOrchestrator } = require('../../dist/tournament/orchestrator/orchestrator');
const { TournamentPacingController } = require('../../dist/tournament/orchestrator/pacing');
const {
	DockerImagePreparer, hashSubmission, participantDockerfile, runtimeDockerfile, validateRequirementsFile,
} = require('../../dist/tournament/sandbox/image-preparer');
const { runDocker } = require('../../dist/tournament/sandbox/docker-cli');
const {
	containerCreateArgs, DEFAULT_DOCKER_RESOURCE_POLICY,
	PROCESS_ENVIRONMENT_ALLOWLIST,
} = require('../../dist/tournament/sandbox/policy');
const { managedContainerIDs } = require('../../dist/tournament/sandbox/runtime');
const { TournamentEventStore } = require('../../dist/tournament/spectator/event-store');
const { loadSubmission } = require('../../dist/tournament/submissions/submission-loader');

const root = path.resolve(__dirname, '../..');
const team = fs.readFileSync(path.join(root, 'tournament/fixtures/teams/vgc-reg-i.txt'), 'utf8');
const legalActions = [
	{ team: ['team_0', 'team_1', 'team_2', 'team_3'] },
	{ team: ['team_3', 'team_2', 'team_1', 'team_0'] },
];

describe('Tournament Docker sandbox policy construction', () => {
	let temporaryRoot;

	beforeEach(() => {
		temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'showdown-sandbox-unit-'));
	});

	afterEach(() => fs.rmSync(temporaryRoot, { recursive: true, force: true }));

	it('constructs a locked-down container without mounts, privileges, devices, or host environment', () => {
		const args = containerCreateArgs('sha256:participant', 'worker-name', 'seed-value', DEFAULT_DOCKER_RESOURCE_POLICY);
		assert.deepEqual(option(args, '--network'), ['none']);
		assert.deepEqual(option(args, '--ipc'), ['none']);
		assert(args.includes('--read-only'));
		assert.deepEqual(option(args, '--cap-drop'), ['ALL']);
		assert.deepEqual(option(args, '--security-opt'), ['no-new-privileges=true']);
		assert.deepEqual(option(args, '--user'), ['10001:10001']);
		assert.deepEqual(option(args, '--memory'), ['512m']);
		assert.deepEqual(option(args, '--memory-swap'), ['512m']);
		assert.deepEqual(option(args, '--cpus'), ['1']);
		assert.deepEqual(option(args, '--pids-limit'), ['64']);
		assert.deepEqual(option(args, '--ulimit'), ['nofile=256:256']);
		assert(/^\/tmp:.*size=64m/.test(option(args, '--tmpfs')[0]));
		assert(args.includes('--init'));
		assert.deepEqual(option(args, '--log-driver'), ['none']);
		for (const forbidden of ['--privileged', '--volume', '-v', '--mount', '--device', '--pid', '--env', '-e']) {
			assert(!args.includes(forbidden), forbidden);
		}
		const envIndex = args.indexOf('/usr/bin/env');
		const processEnvironment = args.slice(envIndex + 2, args.indexOf('/usr/local/bin/python'));
		assert.deepEqual(processEnvironment.map(entry => entry.split('=', 1)[0]).sort(),
			[...PROCESS_ENVIRONMENT_ALLOWLIST].sort());
	});

	it('uses tournament-generated build definitions and hashes arbitrary participant assets', async () => {
		const submission = path.join(temporaryRoot, 'submission');
		fs.mkdirSync(submission);
		fs.writeFileSync(path.join(submission, 'main.py'), 'def choose_action(state): return {}\n');
		fs.writeFileSync(path.join(submission, 'team.txt'), team);
		fs.writeFileSync(path.join(submission, 'model.bin'), 'model-v1');
		const first = await hashSubmission(submission, 'sha256:runtime');
		fs.writeFileSync(path.join(submission, 'model.bin'), 'model-v2');
		assert.notEqual(await hashSubmission(submission, 'sha256:runtime'), first);
		assert(/^FROM sha256:base/m.test(runtimeDockerfile('sha256:base')));
		const generated = participantDockerfile('sha256:runtime', true);
		assert(/^FROM sha256:runtime/m.test(generated));
		assert(/COPY --chown=10001:10001 submission\/ \/submission\//.test(generated));
		assert(/WORKDIR \/opt\/tournament[\s\S]*python -I -m pip install/.test(generated));
		assert(/--only-binary=:all: --no-deps/.test(generated));
		assert(/-r \/submission\/requirements\.txt/.test(generated));
		assert(!generated.includes('privileged'));
	});

	it('streams large asset hashing and enforces submission size and file-count ceilings', async () => {
		const submission = path.join(temporaryRoot, 'streamed-submission');
		fs.mkdirSync(submission);
		const model = path.join(submission, 'model.bin');
		const descriptor = fs.openSync(model, 'w');
		try {
			fs.ftruncateSync(descriptor, 8 * 1024 * 1024);
		} finally {
			fs.closeSync(descriptor);
		}
		const originalReadFileSync = fs.readFileSync;
		Object.defineProperty(fs, 'readFileSync', { configurable: true, value(filename, ...args) {
			if (path.resolve(filename) === model) throw new Error('large asset was read wholly');
			return originalReadFileSync.call(this, filename, ...args);
		} });
		try {
			assert(/^[0-9a-f]{64}$/.test(await hashSubmission(submission, 'sha256:runtime')));
		} finally {
			Object.defineProperty(fs, 'readFileSync', { configurable: true, value: originalReadFileSync });
		}
		await assert.rejects(
			hashSubmission(submission, 'sha256:runtime', { maxBytes: 1024, maxFiles: 10 }),
			/exceeds the 1024-byte total size limit/
		);
		fs.writeFileSync(path.join(submission, 'second.bin'), 'x');
		await assert.rejects(
			hashSubmission(submission, 'sha256:runtime', { maxBytes: 16 * 1024 * 1024, maxFiles: 1 }),
			/exceeds the 1-file limit/
		);
	});

	it('accepts only exact registry pins in bounded requirements files', () => {
		const requirements = path.join(temporaryRoot, 'requirements.txt');
		fs.writeFileSync(requirements, 'six==1.17.0\nrequests[security]==2.32.3 # exact wheel\n');
		validateRequirementsFile(requirements);
		for (const unsupported of [
			'-e .\n', '.\n', 'git+https://example.test/repository.git\n',
			'package @ https://example.test/package.whl\n', '--extra-index-url https://example.test/simple\n',
			'package>=1.0\n', 'package==1.0; python_version > "3"\n',
		]) {
			fs.writeFileSync(requirements, unsupported);
			assert.throws(() => validateRequirementsFile(requirements), /Unsupported requirements\.txt entry/);
		}
	});

	it('rejects participant Dockerfiles before contacting Docker', async () => {
		const submission = makeSubmission(temporaryRoot, 'Dockerfile Bot', validBot(), { Dockerfile: 'FROM busybox\n' });
		const loaded = loadSubmission(submission, { format: DEFAULT_FORMAT });
		await assert.rejects(new DockerImagePreparer().prepare(loaded), /Participant Dockerfiles are not accepted/);
	});
});

describe('Tournament Docker sandbox integration', function () {
	this.timeout(10 * 60_000);
	let temporaryRoot;
	let baselineContainers;
	let preparer;

	before(async function () {
		if (!dockerAvailable()) {
			process.stderr.write('Skipping Docker sandbox integration: Docker Engine is not installed, running, or reachable.\n');
			this.skip();
		}
	});

	beforeEach(async () => {
		temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'showdown-sandbox-docker-'));
		baselineContainers = new Set(await managedContainerIDs());
		preparer = new DockerImagePreparer({ buildTimeoutMs: 5 * 60_000 });
	});

	afterEach(async () => {
		for (const container of await managedContainerIDs()) {
			if (!baselineContainers.has(container)) {
				await runDocker(['container', 'rm', '--force', container]).catch(() => {});
			}
		}
		fs.rmSync(temporaryRoot, { recursive: true, force: true });
	});

	it('enforces actual container policy and isolation while preserving JSONL', async () => {
		const source = isolationBot();
		const directory = makeSubmission(temporaryRoot, 'Isolation Bot', source, { 'asset.txt': 'bundled-model-data' });
		const prepared = await preparer.prepare(loadSubmission(directory, { format: DEFAULT_FORMAT }));
		process.env.TOURNAMENT_HOST_SECRET_FOR_TEST = 'must-not-cross-boundary';
		const worker = prepared.workerFactory.create(path.join(directory, 'main.py'), { seed: 'policy-seed' });
		try {
			await worker.start();
			const inspected = JSON.parse((await runDocker(['container', 'inspect', worker.containerID])).stdout)[0];
			assert.equal(inspected.HostConfig.NetworkMode, 'none');
			assert.equal(inspected.HostConfig.IpcMode, 'none');
			assert.equal(inspected.HostConfig.ReadonlyRootfs, true);
			assert.equal(inspected.Config.User, '10001:10001');
			assert.equal(inspected.HostConfig.Memory, 512 * 1024 * 1024);
			assert.equal(inspected.HostConfig.MemorySwap, 512 * 1024 * 1024);
			assert.equal(inspected.HostConfig.NanoCpus, 1_000_000_000);
			assert.equal(inspected.HostConfig.PidsLimit, 64);
			assert.deepEqual(inspected.HostConfig.CapDrop, ['ALL']);
			assert(inspected.HostConfig.SecurityOpt.some(option => option.startsWith('no-new-privileges')));
			assert(/size=(?:64m|67108864)/.test(inspected.HostConfig.Tmpfs['/tmp']));
			assert.equal(inspected.HostConfig.Privileged, false);
			assert.deepEqual(inspected.HostConfig.Binds, null);
			assert.deepEqual(inspected.Mounts, []);
			assert.equal(inspected.HostConfig.LogConfig.Type, 'none');

			assert.deepEqual(await worker.decide(1, 0, state(1), 2000), legalActions[0]);
			const reportLine = await waitForValue(() =>
				worker.stderr.join('').split(/\r?\n/).find(line => line.startsWith('ISOLATION_REPORT='))
			);
			assert(reportLine);
			const report = JSON.parse(reportLine.slice('ISOLATION_REPORT='.length));
			assert.equal(report.asset, 'bundled-model-data');
			assert.equal(report.root_write, false);
			assert.equal(report.submission_write, false);
			assert.equal(report.tmp_write, true);
			assert.equal(report.dev_shm_write, false);
			assert.equal(report.network, false);
			assert.equal(report.host_secret, null);
			assert.deepEqual(report.environment.sort(), [...PROCESS_ENVIRONMENT_ALLOWLIST].sort());
		} finally {
			delete process.env.TOURNAMENT_HOST_SECRET_FOR_TEST;
			await worker.stop();
		}
		assert.deepEqual(new Set(await managedContainerIDs()), baselineContainers);
	});

	it('installs wheel-only requirements without importing a participant pip.py during preparation', async () => {
		const directory = makeSubmission(temporaryRoot, 'Dependency Bot', [
			'import os',
			'import six',
			'def choose_action(state):',
			'    assert six.text_type("dependency-ready") == "dependency-ready"',
			'    assert not os.path.exists("/submission/pip-shadowed")',
			'    return state["request"]["legal_actions"][0]',
			'',
		].join('\n'), {
			'requirements.txt': 'six==1.17.0\n',
			'pip.py': 'from pathlib import Path\nPath("/submission/pip-shadowed").write_text("unsafe")\n',
		});
		const prepared = await preparer.prepare(loadSubmission(directory, { format: DEFAULT_FORMAT }));
		const cached = await preparer.prepare(loadSubmission(directory, { format: DEFAULT_FORMAT }));
		assert.equal(cached.cached, true);
		assert.equal(cached.imageID, prepared.imageID);
		const worker = prepared.workerFactory.create(path.join(directory, 'main.py'), { seed: 'dependency-seed' });
		try {
			assert.deepEqual(await worker.decide(1, 0, state(1), 3000), legalActions[0]);
		} finally {
			await worker.stop();
		}
	});

	it('kills the entire timed-out container and starts a fresh worker for the next decision', async () => {
		const source = fs.readFileSync(path.join(__dirname, 'fixtures/spawn_hang.py'), 'utf8');
		const directory = makeSubmission(temporaryRoot, 'Container Hang Bot', source);
		const prepared = await preparer.prepare(loadSubmission(directory, { format: DEFAULT_FORMAT }));
		const workers = [];
		const trackingFactory = {
			audit: prepared.workerFactory.audit,
			create(modulePath, options) {
				const worker = prepared.workerFactory.create(modulePath, options);
				workers.push(worker);
				return worker;
			},
		};
		const controller = new BotController(path.join(directory, 'main.py'), {
			fallbackKey: 'docker-timeout', decisionTimeoutMs: 150, maxInvalidAttempts: 3,
			workerFactory: trackingFactory,
		});
		try {
			await controller.start();
			const timedOutContainer = workers[0].containerID;
			const fallback = await decide(controller, 7, 150);
			assert(legalActions.some(action => JSON.stringify(action) === JSON.stringify(fallback)));
			assert.equal(controller.stats.timeouts, 1);
			assert.equal(controller.stats.fallbacks, 1);
			assert.equal(workers.length, 2);
			assert.equal(workers[0].containerID, null);
			assert(!(await managedContainerIDs()).includes(timedOutContainer));
			assert.deepEqual(await decide(controller, 8, 2000), legalActions[0]);
		} finally {
			await controller.stop();
		}
		assert.deepEqual(new Set(await managedContainerIDs()), baselineContainers);
	});

	it('runs an end-to-end Docker-vs-Docker match with auditable artifacts and spectator protocol', async () => {
		const random = loadSubmission(path.join(root, 'tournament/reference-bots/random'), { format: DEFAULT_FORMAT });
		const greedy = loadSubmission(path.join(root, 'tournament/reference-bots/greedy-damage'), { format: DEFAULT_FORMAT });
		const [p1, p2] = [await preparer.prepare(random), await preparer.prepare(greedy)];
		const output = path.join(temporaryRoot, 'docker-match');
		const result = await new MatchRunner({
			format: DEFAULT_FORMAT,
			seed: '44,55,66,77',
			decisionTimeoutMs: 2000,
			matchTimeoutMs: 30_000,
			outputDirectory: output,
			p1: { id: random.id, name: random.name, bot: random.mainPath, team: random.teamText, workerFactory: p1.workerFactory },
			p2: { id: greedy.id, name: greedy.name, bot: greedy.mainPath, team: greedy.teamText, workerFactory: p2.workerFactory },
		}).run();
		assert(result.winner || result.tie);
		assert(result.authoritative_log.length > 0);
		const metadata = JSON.parse(fs.readFileSync(path.join(output, 'metadata.json'), 'utf8'));
		assert.equal(metadata.schema_version, 2);
		assert.equal(metadata.runtime.participants.p1.kind, 'docker');
		assert.equal(metadata.runtime.participants.p1.ipc, 'none');
		assert(/^sha256:/.test(metadata.runtime.participants.p1.participant_image_id));
		const replay = loadReplayArtifacts(output);
		assert(replay.protocol.includes('|turn|1'));
		assert(replay.protocol.includes('|win|') || replay.protocol.includes('|tie'));
		assert.deepEqual(new Set(await managedContainerIDs()), baselineContainers);
	});

	it('runs a complete deterministic tournament through ordinary Docker MatchRunner games', async () => {
		const random = loadSubmission(path.join(root, 'tournament/reference-bots/random'), { format: DEFAULT_FORMAT });
		const greedy = loadSubmission(path.join(root, 'tournament/reference-bots/greedy-damage'), { format: DEFAULT_FORMAT });
		const [randomPrepared, greedyPrepared] = [await preparer.prepare(random), await preparer.prepare(greedy)];
		const configPath = path.join(temporaryRoot, 'docker-tournament.json');
		fs.writeFileSync(configPath, JSON.stringify({
			title: 'Docker Acceptance Cup',
			format: DEFAULT_FORMAT,
			seed: 'docker-acceptance',
			runtime: 'docker',
			decision_timeout_ms: 2000,
			match_timeout_ms: 30_000,
			participants: [
				{ id: random.id, name: random.name, submission: random.directory },
				{ id: greedy.id, name: greedy.name, submission: greedy.directory },
			],
			round_robin: { games_per_pairing: 1 },
			final: { qualifiers: 2, best_of: 1, max_tied_games: 2 },
		}));
		const config = loadTournamentConfig(configPath);
		const output = path.join(temporaryRoot, 'docker-tournament');
		const events = new TournamentEventStore({
			schema_version: 1, kind: 'idle', title: config.config.title,
		}, path.join(output, 'event.log.jsonl'));
		const orchestrator = new TournamentOrchestrator({
			config,
			outputDirectory: output,
			participants: new Map([
				[random.id, { submission: random, workerFactory: randomPrepared.workerFactory }],
				[greedy.id, { submission: greedy, workerFactory: greedyPrepared.workerFactory }],
			]),
			eventStore: events,
			pacing: new TournamentPacingController(events, true),
		});
		const result = await orchestrator.run();
		assert(result.champion);
		assert.equal(orchestrator.stateStore.state.phase, 'complete');
		assert(orchestrator.stateStore.state.completed_games.length >= 2);
		for (const game of orchestrator.stateStore.state.completed_games) {
			const metadata = JSON.parse(fs.readFileSync(path.join(game.artifact_directory, 'metadata.json'), 'utf8'));
			assert.equal(metadata.runtime.participants.p1.kind, 'docker');
			assert.equal(metadata.runtime.participants.p2.kind, 'docker');
			assert(loadReplayArtifacts(game.artifact_directory).protocol.includes('|turn|1'));
		}
		assert.equal(events.presentation.kind, 'champion');
		assert.deepEqual(new Set(await managedContainerIDs()), baselineContainers);
	});
});

function option(args, name) {
	const values = [];
	for (let index = 0; index < args.length - 1; index++) if (args[index] === name) values.push(args[index + 1]);
	return values;
}

function dockerAvailable() {
	try {
		execFileSync('docker', ['version', '--format', '{{.Server.Version}}'], { stdio: 'ignore', timeout: 10_000 });
		return true;
	} catch {
		return false;
	}
}

function makeSubmission(parent, name, main, extra = {}) {
	const directory = path.join(parent, name);
	fs.mkdirSync(directory, { recursive: true });
	fs.writeFileSync(path.join(directory, 'main.py'), main);
	fs.writeFileSync(path.join(directory, 'team.txt'), team);
	for (const [filename, contents] of Object.entries(extra)) fs.writeFileSync(path.join(directory, filename), contents);
	return directory;
}

function validBot() {
	return 'def choose_action(state):\n    return state["request"]["legal_actions"][0]\n';
}

function state(decisionID) {
	return {
		schema_version: 1,
		battle: { format: 'test', turn: 0, phase: 'team_preview' },
		runtime: { decision_id: decisionID, revision: 0, attempt: 1, previous_error: null, deadline_ms: 2000 },
		self: { name: 'Bot', team: [], active: {}, side_conditions: {} },
		opponent: { name: 'Foe', team: [], active: {}, side_conditions: {} },
		field: { weather: null, weather_started_turn: null, conditions: {} },
		request: { kind: 'team_preview', team_size: 4, legal_actions: legalActions },
		history: [],
	};
}

function decide(controller, decisionID, timeoutMs) {
	return controller.decide({
		decisionID,
		revision: 0,
		deadlineAt: Date.now() + timeoutMs,
		newDecision: true,
		buildState: runtime => ({ ...state(decisionID), runtime }),
	});
}

async function waitForValue(read, timeoutMs = 2000) {
	const deadline = Date.now() + timeoutMs;
	do {
		const value = read();
		if (value) return value;
		await new Promise(resolve => { setTimeout(resolve, 10); });
	} while (Date.now() < deadline);
	return read();
}

function isolationBot() {
	return [
		'import json',
		'import os',
		'import socket',
		'',
		'def attempt_write(filename):',
		'    try:',
		'        with open(filename, "w", encoding="utf-8") as handle: handle.write("test")',
		'        return True',
		'    except OSError:',
		'        return False',
		'',
		'def choose_action(state):',
		'    connected = False',
		'    sock = socket.socket()',
		'    sock.settimeout(0.25)',
		'    try:',
		'        sock.connect(("1.1.1.1", 53))',
		'        connected = True',
		'    except OSError:',
		'        pass',
		'    finally:',
		'        sock.close()',
		'    report = {',
		'        "asset": open("/submission/asset.txt", encoding="utf-8").read(),',
		'        "root_write": attempt_write("/forbidden.txt"),',
		'        "submission_write": attempt_write("/submission/forbidden.txt"),',
		'        "tmp_write": attempt_write("/tmp/allowed.txt"),',
		'        "dev_shm_write": attempt_write("/dev/shm/forbidden.txt"),',
		'        "network": connected,',
		'        "host_secret": os.environ.get("TOURNAMENT_HOST_SECRET_FOR_TEST"),',
		'        "environment": sorted(os.environ),',
		'    }',
		'    print("ISOLATION_REPORT=" + json.dumps(report, sort_keys=True), flush=True)',
		'    return state["request"]["legal_actions"][0]',
		'',
	].join('\n');
}
