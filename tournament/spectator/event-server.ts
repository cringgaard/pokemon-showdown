import * as http from 'http';
import type { TournamentPacingController } from '../orchestrator/pacing';
import type { StoredTournamentEvent, TournamentEventStore } from './event-store';
import { parseSequence, renderViewerHTML, send, webAsset } from './server';

export interface TournamentEventServerOptions {
	store: TournamentEventStore;
	pacing: TournamentPacingController;
	host?: string;
	port: number;
}

export class TournamentEventServer {
	readonly store: TournamentEventStore;
	readonly pacing: TournamentPacingController;
	readonly host: string;
	readonly requestedPort: number;
	private readonly server: http.Server;
	private readonly clients = new Set<http.ServerResponse>();

	constructor(options: TournamentEventServerOptions) {
		this.store = options.store;
		this.pacing = options.pacing;
		this.host = options.host || '127.0.0.1';
		this.requestedPort = options.port;
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
		if (!address || typeof address === 'string') throw new Error('Tournament event server is not listening.');
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
			if (request.method === 'GET' && url.pathname === '/') {
				return send(response, 200, renderViewerHTML({
					mode: 'event',
					presentation: this.store.presentation,
					complete: this.store.complete,
					sequence: this.store.events.length,
					event_mode: true,
				}, this.store.protocol()), 'text/html; charset=utf-8');
			}
			if (request.method === 'GET' && url.pathname === '/spectator.js') {
				return send(response, 200, webAsset('spectator.js'), 'text/javascript; charset=utf-8');
			}
			if (request.method === 'GET' && url.pathname === '/spectator.css') {
				return send(response, 200, webAsset('spectator.css'), 'text/css; charset=utf-8');
			}
			if (request.method === 'GET' && url.pathname === '/api/spectator') {
				return send(response, 200, JSON.stringify(this.publicState()), 'application/json; charset=utf-8');
			}
			if (request.method === 'GET' && url.pathname === '/events') return this.events(request, response, url);
			if (request.method === 'GET' && url.pathname === '/operator') {
				return send(response, 200, operatorHTML(), 'text/html; charset=utf-8');
			}
			if (request.method === 'GET' && url.pathname === '/api/operator') {
				return send(response, 200, JSON.stringify(this.pacing.status()), 'application/json; charset=utf-8');
			}
			if (request.method === 'POST' && url.pathname.startsWith('/control/')) {
				return this.control(url.pathname.slice('/control/'.length), response);
			}
			return send(response, 404, 'Not found', 'text/plain; charset=utf-8');
		} catch (error) {
			return send(response, 500, errorMessage(error), 'text/plain; charset=utf-8');
		}
	}

	private publicState() {
		return {
			mode: 'event',
			presentation: this.store.presentation,
			complete: this.store.complete,
			sequence: this.store.events.length,
		};
	}

	private control(action: string, response: http.ServerResponse) {
		let accepted = false;
		if (action === 'advance') accepted = this.pacing.advance();
		else if (action === 'standings') accepted = this.pacing.showStandings();
		else if (action === 'primary') accepted = this.pacing.showPrimary();
		else return send(response, 404, 'Unknown control', 'text/plain; charset=utf-8');
		return send(
			response, 200, JSON.stringify({ accepted, status: this.pacing.status() }), 'application/json; charset=utf-8'
		);
	}

	private events(request: http.IncomingMessage, response: http.ServerResponse, url: URL) {
		response.writeHead(200, {
			'Content-Type': 'text/event-stream; charset=utf-8',
			'Cache-Control': 'no-cache, no-transform',
			Connection: 'keep-alive',
			'X-Accel-Buffering': 'no',
		});
		this.clients.add(response);
		const after = parseSequence(request.headers['last-event-id']) ??
			parseSequence(url.searchParams.get('after')) ?? 0;
		let active = true;
		const writeEvent = (event: StoredTournamentEvent) => {
			if (!active || event.sequence <= after) return;
			if (!response.write(
				`id: ${event.sequence}\nevent: ${event.kind}\ndata: ${JSON.stringify(event)}\n\n`
			)) cleanup();
		};
		const unsubscribe = this.store.subscribe(writeEvent);
		const unsubscribeComplete = this.store.onComplete(() => {
			if (active) response.write('event: complete\ndata: {}\n\n');
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
		for (const event of this.store.events) writeEvent(event);
		if (this.store.complete && active) response.write('event: complete\ndata: {}\n\n');
	}
}

function operatorHTML() {
	return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Tournament operator</title><style>body{font:18px system-ui;background:#07111f;color:#fff;max-width:700px;margin:50px auto;padding:20px}button{font:inherit;padding:18px 24px;margin:8px;border:0;border-radius:10px;background:#39a0ff;color:#04101c;font-weight:800}.secondary{background:#d7e5f5}pre{background:#101e31;padding:18px;border-radius:10px}</style></head><body><h1>Tournament operator</h1><p>Controls only affect presentation pacing between games. An active battle is never paused.</p><button data-action="advance">Advance</button><button class="secondary" data-action="standings">Show standings</button><button class="secondary" data-action="primary">Return to current screen</button><pre id="status">Loading…</pre><script>const status=document.querySelector('#status');async function refresh(){status.textContent=JSON.stringify(await (await fetch('/api/operator')).json(),null,2)}document.addEventListener('click',async e=>{const action=e.target.dataset.action;if(!action)return;await fetch('/control/'+action,{method:'POST'});await refresh()});refresh();</script></body></html>`;
}

function errorMessage(error: unknown) {
	return error instanceof Error ? error.message : String(error);
}
