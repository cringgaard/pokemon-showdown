'use strict';

const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const assert = require('../assert');
const { TournamentPacingController } = require('../../dist/tournament/orchestrator/pacing');
const { TournamentEventServer } = require('../../dist/tournament/spectator/event-server');
const { TournamentEventStore } = require('../../dist/tournament/spectator/event-store');
const { renderViewerHTML } = require('../../dist/tournament/spectator/server');

describe('Tournament event reconstruction and presentation shell', function () {
	this.timeout(10_000);
	let temporaryRoot;
	let server;

	beforeEach(() => {
		temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'showdown-event-'));
	});

	afterEach(async () => {
		await server?.close();
		fs.rmSync(temporaryRoot, { recursive: true, force: true });
	});

	it('reconstructs the latest event and current battle protocol after restart', () => {
		const filename = path.join(temporaryRoot, 'event.log.jsonl');
		const idle = presentation('idle');
		const store = new TournamentEventStore(idle, filename);
		store.publishPresentation({ ...presentation('live'), game_id: 'game-1' }, true);
		store.publish('|start');
		store.publish('|turn|1');
		store.publishPresentation({ ...presentation('result'), winner: { id: 'a', name: 'Alice' } });

		const restored = new TournamentEventStore(idle, filename);
		assert.equal(restored.presentation.kind, 'result');
		assert.equal(restored.presentation.winner.name, 'Alice');
		assert.equal(restored.protocol(), '|start\n|turn|1');
		assert.deepEqual(restored.events.map(event => event.sequence), [1, 2, 3, 4, 5]);
	});

	it('serves retained history followed by live continuation without duplication', async () => {
		const store = new TournamentEventStore(presentation('idle'));
		store.publishPresentation({ ...presentation('live'), game_id: 'game-1' }, true);
		store.publish('|start');
		const pacing = new TournamentPacingController(store, false);
		server = new TournamentEventServer({ store, pacing, port: 0 });
		await server.listen();

		const page = await requestText(server.url());
		assert(page.includes('|start'));
		assert(page.includes('battle-log-data'));
		assert(page.includes('idle-screen'));
		const continuation = openEvents(`${server.url()}events?after=3`, 'id: 4', () => store.publish('|turn|1'));
		const received = await continuation;
		assert(!received.text.includes('id: 3'));
		assert(received.text.includes('event: protocol'));
		received.abort();
	});

	it('exposes operator pacing controls separately from spectator reads', async () => {
		const store = new TournamentEventStore(presentation('intro'));
		const pacing = new TournamentPacingController(store, false);
		server = new TournamentEventServer({ store, pacing, port: 0 });
		await server.listen();
		let resolved = false;
		void pacing.wait(presentation('intro'), presentation('standings')).then(() => { resolved = true; });
		const operator = await requestText(`${server.url()}operator`);
		assert(operator.includes('Advance'));
		await requestText(`${server.url()}control/standings`, 'POST');
		assert.equal(store.presentation.kind, 'standings');
		await requestText(`${server.url()}control/primary`, 'POST');
		assert.equal(store.presentation.kind, 'intro');
		await requestText(`${server.url()}control/advance`, 'POST');
		await Promise.resolve();
		assert.equal(resolved, true);
	});

	for (const kind of ['idle', 'intro', 'live', 'result', 'standings', 'champion']) {
		it(`renders the ${kind} state in the shared official-renderer shell`, () => {
			const html = renderViewerHTML({
				mode: 'event', presentation: presentation(kind), complete: kind === 'champion', sequence: 1,
				event_mode: true,
			}, '|start\n|turn|1');
			assert(html.includes(`data-state="${kind}"`));
			assert(html.includes('replay-embed.js'));
			assert(html.includes('A Participant Name That Is Deliberately Very Long'));
			assert(html.includes('standings-body'));
		});
	}
});

function presentation(kind) {
	return {
		schema_version: 1,
		kind,
		title: 'Company Cup',
		subtitle: 'VGC Finals',
		stage_label: 'Round Robin',
		p1: { id: 'a', name: 'A Participant Name That Is Deliberately Very Long' },
		p2: { id: 'b', name: 'Bob' },
		standings: [{ rank: 1, name: 'Alice', wins: 1, losses: 0, ties: 0, points: 1 }],
	};
}

function requestText(url, method = 'GET') {
	return new Promise((resolve, reject) => {
		const request = http.request(url, { method }, response => {
			response.setEncoding('utf8');
			let text = '';
			response.on('data', chunk => { text += chunk; });
			response.on('end', () => resolve(text));
		});
		request.on('error', reject);
		request.end();
	});
}

function openEvents(url, expected, afterOpen) {
	return new Promise((resolve, reject) => {
		let settled = false;
		const request = http.get(url, response => {
			response.setEncoding('utf8');
			let text = '';
			response.on('data', chunk => {
				text += chunk;
				if (!settled && text.includes(expected)) {
					settled = true;
					clearTimeout(timeout);
					resolve({ text, abort: () => request.destroy() });
				}
			});
		});
		request.on('error', error => { if (!settled) reject(error); });
		if (afterOpen) setTimeout(afterOpen, 20);
		const timeout = setTimeout(() => reject(new Error(`Timed out waiting for ${expected}`)), 2000);
	});
}
