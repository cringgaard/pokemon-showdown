'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('../assert');
const { ProtocolStore } = require('../../dist/tournament/spectator/protocol-store');
const { loadReplayArtifacts } = require('../../dist/tournament/spectator/replay-loader');
const {
	OFFICIAL_REPLAY_EMBED_URL, SpectatorServer, startReplayServer,
} = require('../../dist/tournament/spectator/server');
const {
	ProtocolRecorder, SpectatorPublisher,
} = require('../../dist/tournament/spectator/spectator-publisher');

describe('Tournament spectator publication and transport', function () {
	this.timeout(10_000);
	let temporaryRoot;
	const servers = [];

	beforeEach(() => {
		temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'showdown-spectator-'));
	});

	afterEach(async () => {
		await Promise.all(servers.splice(0).map(server => server.close()));
		fs.rmSync(temporaryRoot, { recursive: true, force: true });
	});

	it('publishes authoritative chunks to every sink in order and isolates a failed sink', () => {
		const recorder = new ProtocolRecorder();
		const observed = [];
		const failures = [];
		const publisher = new SpectatorPublisher([
			recorder,
			{ publish() { throw new Error('display failed'); } },
			{ publish(chunk) { observed.push(chunk); } },
		], error => failures.push(error.message));
		publisher.publish('|turn|1');
		publisher.publish('|move|p1a: Cat|Protect|p1a: Cat');
		assert.deepEqual(recorder.chunks, ['|turn|1', '|move|p1a: Cat|Protect|p1a: Cat']);
		assert.deepEqual(observed, recorder.chunks);
		assert.deepEqual(failures, ['display failed', 'display failed']);
	});

	it('loads a completed artifact directory and reports malformed artifacts usefully', () => {
		const valid = makeReplayDirectory(temporaryRoot);
		const replay = loadReplayArtifacts(valid);
		assert.equal(replay.metadata.participants.p1.name, 'Alice Bot');
		assert(replay.protocol.indexOf('|turn|1') < replay.protocol.indexOf('|win|Alice Bot'));

		fs.writeFileSync(path.join(valid, 'metadata.json'), '{');
		assert.throws(() => loadReplayArtifacts(valid), /metadata\.json.*not valid JSON/);
		fs.rmSync(path.join(valid, 'metadata.json'));
		assert.throws(() => loadReplayArtifacts(valid), /metadata\.json.*missing/);
	});

	it('serves a replay through the official Showdown embed and preserves stored protocol order', async () => {
		const server = await startReplayServer(makeReplayDirectory(temporaryRoot), { port: 0 });
		servers.push(server);
		const html = await (await fetch(server.url())).text();
		assert(html.includes('Alice Bot'));
		assert(html.includes('Bob Bot'));
		assert(html.includes(OFFICIAL_REPLAY_EMBED_URL));
		assert(html.indexOf('|turn|1') < html.indexOf('|win|Alice Bot'));
		assert(html.includes('battle-log-data'));
	});

	it('sends accumulated live history, then new chunks, and reconstructs on reconnect', async () => {
		const store = new ProtocolStore({ metadata: metadata() });
		store.publish('|start');
		store.publish('|turn|1');
		const server = new SpectatorServer({ store, mode: 'live', port: 0 });
		await server.listen();
		servers.push(server);

		const first = await openEvents(`${server.url()}events?after=0`, '"sequence":2');
		assert(first.text.includes('"sequence":1'));
		assert(first.text.includes('"sequence":2'));
		first.abort();

		const continuing = openEvents(`${server.url()}events?after=2`, '"sequence":3', () => {
			store.publish('|move|p1a: Cat|Protect|p1a: Cat');
		});
		const next = await continuing;
		assert(!next.text.includes('"sequence":1'));
		assert(next.text.includes('"sequence":3'));
		next.abort();

		const refreshed = await openEvents(`${server.url()}events?after=0`, '"sequence":3');
		assert(refreshed.text.indexOf('"sequence":1') < refreshed.text.indexOf('"sequence":3'));
		refreshed.abort();

		const reconnected = await openEvents(
			`${server.url()}events?after=1`, '"sequence":3', undefined, { 'Last-Event-ID': '2' }
		);
		assert(!reconnected.text.includes('"sequence":1'));
		assert(!reconnected.text.includes('"sequence":2'));
		assert(reconnected.text.includes('"sequence":3'));
		reconnected.abort();
	});

	it('disconnecting a live client does not stop publication', async () => {
		const store = new ProtocolStore({ metadata: metadata() });
		const server = new SpectatorServer({ store, mode: 'live', port: 0 });
		await server.listen();
		servers.push(server);
		const connection = await openEvents(`${server.url()}events?after=0`, '"sequence":1', () => store.publish('|start'));
		connection.abort();
		store.publish('|turn|1');
		store.publish('|win|Alice Bot');
		assert.deepEqual(store.chunks.map(entry => entry.chunk), ['|start', '|turn|1', '|win|Alice Bot']);
	});
});

async function openEvents(url, expected, afterOpen, headers) {
	const controller = new AbortController();
	const responsePromise = fetch(url, { signal: controller.signal, headers });
	if (afterOpen) setTimeout(afterOpen, 20);
	const response = await responsePromise;
	const reader = response.body.getReader();
	let text = '';
	while (!text.includes(expected)) {
		const result = await Promise.race([
			reader.read(),
			new Promise((resolve, reject) => {
				setTimeout(() => reject(new Error('Timed out reading spectator events')), 2000);
			}),
		]);
		if (result.done) break;
		text += Buffer.from(result.value).toString('utf8');
	}
	return { text, abort: () => controller.abort() };
}

function makeReplayDirectory(root) {
	const directory = path.join(root, 'match');
	fs.mkdirSync(directory, { recursive: true });
	fs.writeFileSync(path.join(directory, 'metadata.json'), JSON.stringify(metadata()));
	fs.writeFileSync(path.join(directory, 'result.json'), JSON.stringify({ winner: 'Alice Bot', tie: false, turns: 1 }));
	fs.writeFileSync(path.join(directory, 'battle.protocol.log'), '|start\n|turn|1\n|win|Alice Bot\n');
	return directory;
}

function metadata() {
	return {
		schema_version: 1,
		format: 'gen9vgc2025regi',
		participants: {
			p1: { id: 'alice', name: 'Alice Bot' },
			p2: { id: 'bob', name: 'Bob Bot' },
		},
	};
}
