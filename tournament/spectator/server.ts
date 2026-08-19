import * as fs from 'fs';
import * as http from 'http';
import * as path from 'path';
import { ProtocolStore, type StoredProtocolChunk } from './protocol-store';
import { loadReplayArtifacts } from './replay-loader';

export const OFFICIAL_REPLAY_EMBED_URL = 'https://play.pokemonshowdown.com/js/replay-embed.js';

export interface SpectatorServerOptions {
	store: ProtocolStore;
	mode: 'replay' | 'live';
	host?: string;
	port?: number;
}

export class SpectatorServer {
	readonly store: ProtocolStore;
	readonly mode: 'replay' | 'live';
	readonly host: string;
	readonly requestedPort: number;
	private readonly server: http.Server;
	private readonly clients = new Set<http.ServerResponse>();

	constructor(options: SpectatorServerOptions) {
		this.store = options.store;
		this.mode = options.mode;
		this.host = options.host || '127.0.0.1';
		this.requestedPort = options.port ?? 0;
		this.server = http.createServer((request, response) => this.handle(request, response));
	}

	async listen() {
		await new Promise<void>((resolve, reject) => {
			this.server.once('error', reject);
			this.server.listen(this.requestedPort, this.host, () => {
				this.server.off('error', reject);
				resolve();
			});
		});
		return this.url();
	}

	url() {
		const address = this.server.address();
		if (!address || typeof address === 'string') throw new Error('Spectator server is not listening.');
		return `http://${this.host}:${address.port}/`;
	}

	async close() {
		for (const client of this.clients) client.destroy();
		this.clients.clear();
		if (!this.server.listening) return;
		await new Promise<void>((resolve, reject) => {
			this.server.close(error => error ? reject(error) : resolve());
		});
	}

	private handle(request: http.IncomingMessage, response: http.ServerResponse) {
		try {
			const url = new URL(request.url || '/', `http://${request.headers.host || 'localhost'}`);
			if (request.method !== 'GET') return send(response, 405, 'Method not allowed', 'text/plain; charset=utf-8');
			if (url.pathname === '/') return send(response, 200, viewerHTML(this.store, this.mode), 'text/html; charset=utf-8');
			if (url.pathname === '/spectator.js') {
				return send(response, 200, webAsset('spectator.js'), 'text/javascript; charset=utf-8');
			}
			if (url.pathname === '/spectator.css') return send(response, 200, webAsset('spectator.css'), 'text/css; charset=utf-8');
			if (url.pathname === '/api/spectator') {
				return send(response, 200, JSON.stringify(this.publicState()), 'application/json; charset=utf-8');
			}
			if (url.pathname === '/events') return this.events(request, response, url);
			return send(response, 404, 'Not found', 'text/plain; charset=utf-8');
		} catch (error) {
			return send(response, 500, error instanceof Error ? error.message : String(error), 'text/plain; charset=utf-8');
		}
	}

	private publicState() {
		return {
			mode: this.mode,
			metadata: this.store.metadata,
			result: this.store.result,
			complete: this.store.complete,
			sequence: this.store.chunks.length,
		};
	}

	private events(request: http.IncomingMessage, response: http.ServerResponse, url: URL) {
		response.writeHead(200, {
			'Content-Type': 'text/event-stream; charset=utf-8',
			'Cache-Control': 'no-cache, no-transform',
			Connection: 'keep-alive',
			'X-Accel-Buffering': 'no',
		});
		this.clients.add(response);
		const headerSequence = parseSequence(request.headers['last-event-id']);
		const querySequence = parseSequence(url.searchParams.get('after'));
		const after = headerSequence ?? querySequence ?? 0;
		let active = true;
		const writeEntry = (entry: StoredProtocolChunk) => {
			if (!active || entry.sequence <= after) return;
			if (!response.write(`id: ${entry.sequence}\nevent: protocol\ndata: ${JSON.stringify(entry)}\n\n`)) cleanup();
		};
		const unsubscribe = this.store.subscribe(writeEntry);
		const unsubscribeComplete = this.store.onComplete(() => {
			if (active) response.write(`event: complete\ndata: {}\n\n`);
		});
		const cleanup = () => {
			if (!active) return;
			active = false;
			unsubscribe();
			unsubscribeComplete();
			this.clients.delete(response);
			response.end();
		};
		request.once('close', cleanup);
		for (const entry of this.store.chunks) writeEntry(entry);
		if (this.store.complete && active) response.write(`event: complete\ndata: {}\n\n`);
	}
}

export async function startReplayServer(directory: string, options: { host?: string, port?: number } = {}) {
	const replay = loadReplayArtifacts(directory);
	const store = new ProtocolStore({ metadata: replay.metadata, result: replay.result, protocol: replay.protocol });
	store.markComplete();
	const server = new SpectatorServer({ store, mode: 'replay', ...options });
	await server.listen();
	return server;
}

function viewerHTML(store: ProtocolStore, mode: 'replay' | 'live') {
	const state = {
		mode,
		metadata: store.metadata,
		result: store.result,
		complete: store.complete,
		sequence: store.chunks.length,
	};
	return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pokemon Bot Tournament Spectator</title>
<link rel="stylesheet" href="/spectator.css">
</head>
<body>
<header class="tournament-header">
<div class="eyebrow">Pokemon Bot Tournament</div>
<div class="matchup">
<strong id="p1-name">Player 1</strong><span>vs</span><strong id="p2-name">Player 2</strong>
</div>
<div class="match-meta">
<span id="turn-label">Team Preview</span><span id="format-label"></span>
<span id="connection-label">${mode === 'live' ? 'Connecting live...' : 'Saved replay'}</span>
</div>
</header>
<main>
<div class="wrapper replay-wrapper">
<div class="battle"></div>
<div class="battle-log"></div>
<div class="replay-controls"></div>
<div class="replay-controls-2"></div>
</div>
<div id="result-banner" class="result-banner" aria-live="polite"></div>
</main>
<input type="hidden" name="replayid" value="tournament-gen9vgc-local">
<script type="text/plain" class="battle-log-data">${escapeScriptText(store.protocol())}</script>
<script type="application/json" id="spectator-config">${escapeScriptText(JSON.stringify(state))}</script>
<script src="${OFFICIAL_REPLAY_EMBED_URL}"></script>
<script defer src="/spectator.js"></script>
</body>
</html>`;
}

function webAsset(filename: string) {
	const filepath = path.resolve(__dirname, '../../../tournament/spectator-web', filename);
	return fs.readFileSync(filepath, 'utf8');
}

function escapeScriptText(value: string) {
	return value.replace(/<\//g, '<\\/');
}

function parseSequence(value: string | string[] | null | undefined) {
	if (typeof value !== 'string' || !value) return null;
	const sequence = Number(value);
	return Number.isSafeInteger(sequence) && sequence >= 0 ? sequence : null;
}

function send(response: http.ServerResponse, status: number, body: string, contentType: string) {
	response.writeHead(status, { 'Content-Type': contentType, 'Content-Length': Buffer.byteLength(body) });
	response.end(body);
}
