import * as http from 'http';
import type { TournamentPacingController } from '../orchestrator/pacing';
import type { PlaybackSpeed, TournamentPlaybackController } from '../orchestrator/playback';
import type { StoredTournamentEvent, TournamentEventStore } from './event-store';
import type { PublicTeamSheet } from './public-team-sheet';
import { parseSequence, renderTeamSheetHTML, renderViewerHTML, send, webAsset } from './server';

export interface TournamentEventServerOptions {
	store: TournamentEventStore;
	pacing: TournamentPacingController;
	playback: TournamentPlaybackController;
	teams: Map<string, PublicTeamSheet>;
	host?: string;
	port: number;
}

export class TournamentEventServer {
	readonly store: TournamentEventStore;
	readonly pacing: TournamentPacingController;
	readonly playback: TournamentPlaybackController;
	readonly teams: Map<string, PublicTeamSheet>;
	readonly host: string;
	readonly requestedPort: number;
	private readonly server: http.Server;
	private readonly clients = new Set<http.ServerResponse>();

	constructor(options: TournamentEventServerOptions) {
		this.store = options.store;
		this.pacing = options.pacing;
		this.playback = options.playback;
		this.teams = options.teams;
		this.host = options.host || '127.0.0.1';
		this.requestedPort = options.port;
		this.server = http.createServer((request, response) => { void this.handle(request, response); });
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

	private async handle(request: http.IncomingMessage, response: http.ServerResponse) {
		try {
			const url = new URL(request.url || '/', `http://${request.headers.host || 'localhost'}`);
			if (request.method === 'GET' && url.pathname === '/') {
				return send(response, 200, renderViewerHTML({
					mode: 'event',
					presentation: this.store.presentation,
					complete: this.store.complete,
					sequence: this.store.events.length,
					event_mode: true,
					playback: this.playback.status(),
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
				return send(response, 200, webAsset('operator.html'), 'text/html; charset=utf-8');
			}
			if (request.method === 'GET' && url.pathname === '/api/operator') {
				return send(response, 200, JSON.stringify(this.operatorStatus()), 'application/json; charset=utf-8');
			}
			if (request.method === 'GET' && url.pathname.startsWith('/teams/')) {
				return this.teamSheet(decodeURIComponent(url.pathname.slice('/teams/'.length)), response);
			}
			if (request.method === 'GET' && /^\/current\/p[12]\/team$/.test(url.pathname)) {
				const side = url.pathname.includes('/p1/') ? 'p1' : 'p2';
				const participant = this.pacing.primaryState()?.[side] || this.store.presentation[side];
				if (!participant) return send(response, 404, 'No active pairing', 'text/plain; charset=utf-8');
				return this.teamSheet(participant.id, response);
			}
			if (request.method === 'POST' && url.pathname === '/api/playback-complete') {
				const body = await readJSON(request);
				const acknowledgement = this.playback.acknowledge(body.protocol_generation as number);
				return send(response, 200, JSON.stringify(acknowledgement), 'application/json; charset=utf-8');
			}
			if (request.method === 'POST' && url.pathname === '/api/playback-control') {
				const body = await readJSON(request);
				return send(response, 200, JSON.stringify(this.playbackControl(body)), 'application/json; charset=utf-8');
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
			playback: this.playback.status(),
		};
	}

	private teamSheet(id: string, response: http.ServerResponse) {
		const team = this.teams.get(id);
		if (!team) return send(response, 404, 'Unknown participant', 'text/plain; charset=utf-8');
		return send(response, 200, renderTeamSheetHTML(team), 'text/html; charset=utf-8');
	}

	private playbackControl(body: Record<string, unknown>) {
		const generation = body.protocol_generation as number;
		if (body.action === 'pause') return this.playback.setPaused(generation, true);
		if (body.action === 'resume') return this.playback.setPaused(generation, false);
		if (body.action === 'speed') return this.playback.setSpeed(generation, body.speed as PlaybackSpeed);
		throw new Error('Unknown playback control action.');
	}

	private control(action: string, response: http.ServerResponse) {
		let accepted = false;
		if (action === 'advance') accepted = this.pacing.advance();
		else if (action === 'standings') accepted = this.pacing.showStandings();
		else if (action === 'primary') accepted = this.pacing.showPrimary();
		else if (action === 'team-p1' || action === 'team-p2') {
			const primary = this.pacing.primaryState();
			const side = action === 'team-p1' ? 'p1' : 'p2';
			accepted = !!primary?.teams && this.pacing.show({ ...primary, kind: 'team_sheet', team_sheet_side: side });
		} else if (action === 'team-preview') {
			const primary = this.pacing.primaryState();
			accepted = !!primary?.teams && this.pacing.show({ ...primary, kind: 'team_preview' });
		} else if (action === 'playback-complete') accepted = this.playback.forceComplete();
		else return send(response, 404, 'Unknown control', 'text/plain; charset=utf-8');
		return send(
			response, 200, JSON.stringify({ accepted, status: this.operatorStatus() }), 'application/json; charset=utf-8'
		);
	}

	private operatorStatus() {
		const playback = this.playback.status();
		const turns = [...this.store.protocol().matchAll(/^\|turn\|(\d+)$/gm)];
		return {
			pacing: this.pacing.status(),
			playback: {
				...playback,
				state: playback.paused ? 'paused' : 'playing',
				turn: turns.length ? Number(turns[turns.length - 1][1]) : 0,
			},
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
		const unsubscribePlayback = this.playback.subscribe(status => {
			if (active) response.write(`event: playback\ndata: ${JSON.stringify(status)}\n\n`);
		});
		const cleanup = () => {
			if (!active) return;
			active = false;
			unsubscribe();
			unsubscribeComplete();
			unsubscribePlayback();
			this.clients.delete(response);
			response.end();
		};
		request.once('close', cleanup);
		for (const event of this.store.events) writeEvent(event);
		if (this.store.complete && active) response.write('event: complete\ndata: {}\n\n');
	}
}

function errorMessage(error: unknown) {
	return error instanceof Error ? error.message : String(error);
}

function readJSON(request: http.IncomingMessage) {
	return new Promise<Record<string, unknown>>((resolve, reject) => {
		let body = '';
		request.setEncoding('utf8');
		request.on('data', chunk => {
			body += chunk;
			if (body.length > 1024) request.destroy(new Error('Request body too large.'));
		});
		request.on('end', () => {
			try {
				const value = JSON.parse(body);
				if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Expected a JSON object.');
				resolve(value as Record<string, unknown>);
			} catch (error) {
				reject(error);
			}
		});
		request.on('error', reject);
	});
}
