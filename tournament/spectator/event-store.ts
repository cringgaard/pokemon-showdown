import * as fs from 'fs';
import * as path from 'path';
import type { SpectatorSink } from './spectator-publisher';

export const TOURNAMENT_EVENT_SCHEMA_VERSION = 1;

export type PresentationKind = 'idle' | 'intro' | 'live' | 'result' | 'standings' | 'champion';

export interface PresentationParticipant {
	id: string;
	name: string;
}

export interface TournamentPresentationState {
	schema_version: number;
	kind: PresentationKind;
	title: string;
	subtitle?: string;
	stage_label?: string;
	game_id?: string;
	game_number?: number;
	p1?: PresentationParticipant;
	p2?: PresentationParticipant;
	series_score?: Record<string, number>;
	winner?: PresentationParticipant | null;
	tie?: boolean;
	standings?: Record<string, unknown>[];
	next_match?: { p1: PresentationParticipant, p2: PresentationParticipant, label: string } | null;
	champion_reason?: string;
	message?: string;
}

export interface StoredTournamentEvent {
	sequence: number;
	kind: 'presentation' | 'protocol';
	presentation?: TournamentPresentationState;
	chunk?: string;
}

export class TournamentEventStore implements SpectatorSink {
	readonly events: StoredTournamentEvent[] = [];
	readonly protocolChunks: string[] = [];
	readonly deliveryErrors: string[] = [];
	presentation: TournamentPresentationState;
	complete = false;
	private readonly filename: string | null;
	private readonly listeners = new Set<(event: StoredTournamentEvent) => void>();
	private readonly completionListeners = new Set<() => void>();

	constructor(initial: TournamentPresentationState, filename?: string) {
		this.presentation = initial;
		this.filename = filename ? path.resolve(filename) : null;
		if (this.filename && fs.existsSync(this.filename)) this.load();
		if (!this.events.length) this.publishPresentation(initial);
	}

	publish(chunk: string) {
		this.append({ sequence: this.events.length + 1, kind: 'protocol', chunk });
		this.protocolChunks.push(chunk);
	}

	publishPresentation(presentation: TournamentPresentationState, resetProtocol = false) {
		this.presentation = presentation;
		if (resetProtocol) this.protocolChunks.splice(0);
		this.append({ sequence: this.events.length + 1, kind: 'presentation', presentation });
	}

	subscribe(listener: (event: StoredTournamentEvent) => void) {
		this.listeners.add(listener);
		return () => this.listeners.delete(listener);
	}

	onComplete(listener: () => void) {
		this.completionListeners.add(listener);
		return () => this.completionListeners.delete(listener);
	}

	markComplete() {
		if (this.complete) return;
		this.complete = true;
		for (const listener of this.completionListeners) {
			try {
				listener();
			} catch {}
		}
	}

	protocol() {
		return this.protocolChunks.join('\n');
	}

	private append(event: StoredTournamentEvent) {
		this.events.push(event);
		if (this.filename) {
			try {
				fs.mkdirSync(path.dirname(this.filename), { recursive: true });
				fs.appendFileSync(this.filename, `${JSON.stringify(event)}\n`, 'utf8');
			} catch (error) {
				this.deliveryErrors.push(errorMessage(error));
			}
		}
		for (const listener of this.listeners) {
			try {
				listener(event);
			} catch {}
		}
	}

	private load() {
		for (const [index, line] of fs.readFileSync(this.filename!, 'utf8').split(/\r?\n/).entries()) {
			if (!line) continue;
			let event: StoredTournamentEvent;
			try {
				event = JSON.parse(line) as StoredTournamentEvent;
			} catch (error) {
				throw new Error(`Tournament event log line ${index + 1} is invalid: ${errorMessage(error)}`);
			}
			if (event.sequence !== this.events.length + 1) throw new Error('Tournament event log sequence is not contiguous.');
			this.events.push(event);
			if (event.kind === 'presentation' && event.presentation) {
				this.presentation = event.presentation;
				if (event.presentation.kind === 'live') this.protocolChunks.splice(0);
			} else if (event.kind === 'protocol' && typeof event.chunk === 'string') {
				this.protocolChunks.push(event.chunk);
			}
		}
	}
}

function errorMessage(error: unknown) {
	return error instanceof Error ? error.message : String(error);
}
