'use strict';

const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('../assert');
const { BotController } = require('../../dist/tournament/bots/runtime');
const { loadReplayArtifacts } = require('../../dist/tournament/spectator/replay-loader');
const { MatchRunner, DEFAULT_FORMAT } = require('../../dist/tournament/match/match-runner');
const {
	DockerImagePreparer, hashSubmission, participantDockerfile, runtimeDockerfile,
} = require('../../dist/tournament/sandbox/image-preparer');
const { runDocker } = require('../../dist/tournament/sandbox/docker-cli');
const {
	containerCreateArgs, DEFAULT_DOCKER_RESOURCE_POLICY,
	PROCESS_ENVIRONMENT_ALLOWLIST,
} = require('../../dist/tournament/sandbox/policy');
const { managedContainerIDs } = require('../../dist/tournament/sandbox/runtime');
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
		assert(args.includes('--read-only'));
		assert.deepEqual(option(args, '--cap-drop'), ['ALL']);
		assert.deepEqual(option(args, '--security-opt'), ['no-new-privileges=true']);
		assert.deepEqual(option(args, '--user'), ['10001:10001']);
		assert.deepEqual(option(args, '--memory'), ['512m']);
		assert.deepEqual(option(args, '--memory-swap'), ['512m']);
		assert.deepEqual(option(args, '--cpus'), ['1']);
		assert.deepEqual(option(args, '--pids-limit'), ['64']);
		assert.deepEqual(option(args, '--ulimit'), ['nofile=256:256']);
		assert.match(option(args, '--tmpfs')[0], /^\/tmp:.*size=64m/);
		assert(args.includes('--init'));
		assert.deepEqual(option(args, '--log-driver'), ['none']);
		for (const forbidden of ['--privileged', '--volume', '-v', '--mount', '--device', '--pid', '--ipc', '--env', '-e']) {
			assert(!args.includes(forbidden), forbidden);
		}
		const envIndex = args.indexOf('/usr/bin/env');
		const processEnvironment = args.slice(envIndex + 2, args.indexOf('/usr/local/bin/python'));
		assert.deepEqual(processEnvironment.map(entry => entry.split('=', 1)[0]).sort(),
			[...PROCESS_ENVIRONMENT_ALLOWLIST].sort());
	});

	it('uses tournament-generated build definitions and hashes arbitrary participant assets', () => {
		const submission = path.join(temporaryRoot, 'submission');
		fs.mkdirSync(submission);
		fs.writeFileSync(path.join(submission, 'main.py'), 'def choose_action(state): return {}\n');
		fs.writeFileSync(path.join(submission, 'team.txt'), team);
		fs.writeFileSync(path.join(submission, 'model.bin'), 'model-v1');
		const first = hashSubmission(submission, 'sha256:runtime');
		fs.writeFileSync(path.join(submission, 'model.bin'), 'model-v2');
		assert.notEqual(hashSubmission(submission, 'sha256:runtime'), first);
		assert.match(runtimeDockerfile('sha256:base'), /^FROM sha256:base/m);
		const generated = participantDockerfile('sha256:runtime', true);
		assert.match(generated, /^FROM sha256:runtime/m);
		assert.match(generated, /COPY --chown=10001:10001 submission\/ \/submission\//);
		assert.match(generated, /pip install .*requirements\.txt/);
		assert(!generated.includes('privileged'));
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
			assert.equal(inspected.HostConfig.ReadonlyRootfs, true);
			assert.equal(inspected.Config.User, '10001:10001');
			assert.equal(inspected.HostConfig.Memory, 512 * 1024 * 1024);
			assert.equal(inspected.HostConfig.MemorySwap, 512 * 1024 * 1024);
			assert.equal(inspected.HostConfig.NanoCpus, 1_000_000_000);
			assert.equal(inspected.HostConfig.PidsLimit, 64);
			assert.deepEqual(inspected.HostConfig.CapDrop, ['ALL']);
			assert(inspected.HostConfig.SecurityOpt.some(option => option.startsWith('no-new-privileges')));
			assert.match(inspected.HostConfig.Tmpfs['/tmp'], /size=(?:64m|67108864)/);
			assert.equal(inspected.HostConfig.Privileged, false);
			assert.deepEqual(inspected.HostConfig.Binds, null);
			assert.deepEqual(inspected.Mounts, []);
			assert.equal(inspected.HostConfig.LogConfig.Type, 'none');

			assert.deepEqual(await worker.decide(1, 0, state(1), 2000), legalActions[0]);
			const reportLine = worker.stderr.join('').split(/\r?\n/).find(line => line.startsWith('ISOLATION_REPORT='));
			assert(reportLine);
			const report = JSON.parse(reportLine.slice('ISOLATION_REPORT='.length));
			assert.equal(report.asset, 'bundled-model-data');
			assert.equal(report.root_write, false);
			assert.equal(report.submission_write, false);
			assert.equal(report.tmp_write, true);
			assert.equal(report.network, false);
			assert.equal(report.host_secret, null);
			assert.deepEqual(report.environment.sort(), [...PROCESS_ENVIRONMENT_ALLOWLIST].sort());
		} finally {
			delete process.env.TOURNAMENT_HOST_SECRET_FOR_TEST;
			await worker.stop();
		}
		assert.deepEqual(new Set(await managedContainerIDs()), baselineContainers);
	});

	it('installs optional requirements.txt during controlled image preparation', async () => {
		const directory = makeSubmission(temporaryRoot, 'Dependency Bot', [
			'import six',
			'def choose_action(state):',
			'    assert six.text_type("dependency-ready") == "dependency-ready"',
			'    return state["request"]["legal_actions"][0]',
			'',
		].join('\n'), { 'requirements.txt': 'six==1.17.0\n' });
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
		assert.match(metadata.runtime.participants.p1.participant_image_id, /^sha256:/);
		const replay = loadReplayArtifacts(output);
		assert(replay.protocol.includes('|turn|1'));
		assert(replay.protocol.includes('|win|') || replay.protocol.includes('|tie'));
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
		'        "network": connected,',
		'        "host_secret": os.environ.get("TOURNAMENT_HOST_SECRET_FOR_TEST"),',
		'        "environment": sorted(os.environ),',
		'    }',
		'    print("ISOLATION_REPORT=" + json.dumps(report, sort_keys=True), flush=True)',
		'    return state["request"]["legal_actions"][0]',
		'',
	].join('\n');
}
