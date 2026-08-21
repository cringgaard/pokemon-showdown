import * as fs from 'fs';
import * as path from 'path';
import type { SpectatorSink } from './spectator-publisher';
import type { PublicTeamSheet } from './public-team-sheet';

export const TOURNAMENT_EVENT_SCHEMA_VERSION = 1;

export type PresentationKind =
	'idle' | 'intro' | 'team_sheet' | 'team_preview' | 'selection_locked' |
	'live' | 'result' | 'standings' | 'champion';

export interface PresentationParticipant {
	id: string;
	name: string;
}

export interface TournamentPresentationState {
	schema_version: number;
	protocol_generation?: number;
	kind: PresentationKind;
	title: string;
	subtitle?: string;
	stage_label?: string;
	game_id?: string;
	game_number?: number;
	p1?: PresentationParticipant;
	p2?: PresentationParticipant;
	teams?: { p1: PublicTeamSheet, p2: PublicTeamSheet };
	team_sheet_side?: 'p1' | 'p2';
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
	protocol_generation?: number;
	reset_protocol?: boolean;
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
	private protocolGeneration = 0;
	private persistenceDisabled = false;
	private readonly listeners = new Set<(event: StoredTournamentEvent) => void>();
	private readonly completionListeners = new Set<() => void>();

	constructor(initial: TournamentPresentationState, filename?: string) {
		this.presentation = initial;
		this.filename = filename ? path.resolve(filename) : null;
		if (this.filename && fs.existsSync(this.filename)) this.load();
		if (!this.events.length) this.publishPresentation(initial);
	}

	publish(chunk: string) {
		this.append({
			sequence: this.events.length + 1, kind: 'protocol',
			protocol_generation: this.protocolGeneration, chunk,
		});
		this.protocolChunks.push(chunk);
	}

	publishPresentation(presentation: TournamentPresentationState, resetProtocol = false) {
		if (resetProtocol) {
			this.protocolGeneration++;
			this.protocolChunks.splice(0);
		}
		const current = { ...presentation, protocol_generation: this.protocolGeneration };
		this.presentation = current;
		this.append({
			sequence: this.events.length + 1, kind: 'presentation',
			protocol_generation: this.protocolGeneration, reset_protocol: resetProtocol, presentation: current,
		});
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
		if (this.filename && !this.persistenceDisabled) {
			try {
				fs.mkdirSync(path.dirname(this.filename), { recursive: true });
				fs.appendFileSync(this.filename, `${JSON.stringify(event)}\n`, 'utf8');
			} catch (error) {
				this.persistenceDisabled = true;
				this.deliveryErrors.push(`Tournament spectator event persistence disabled: ${errorMessage(error)}`);
			}
		}
		this.events.push(event);
		for (const listener of this.listeners) {
			try {
				listener(event);
			} catch {}
		}
	}

	private load() {
		let contents: string;
		try {
			contents = fs.readFileSync(this.filename!, 'utf8');
		} catch (error) {
			this.persistenceDisabled = true;
			this.deliveryErrors.push(`Tournament spectator event history unavailable: ${errorMessage(error)}`);
			return;
		}
		const retainedLines: string[] = [];
		let recoveryReason: string | null = null;
		for (const [index, line] of contents.split(/\r?\n/).entries()) {
			if (!line) continue;
			let event: StoredTournamentEvent;
			try {
				event = JSON.parse(line) as StoredTournamentEvent;
			} catch (error) {
				recoveryReason = `line ${index + 1} is invalid: ${errorMessage(error)}`;
				break;
			}
			if (event.sequence !== this.events.length + 1) {
				recoveryReason = `line ${index + 1} has a non-contiguous sequence`;
				break;
			}
			if (event.kind !== 'presentation' && event.kind !== 'protocol') {
				recoveryReason = `line ${index + 1} has an unknown event kind`;
				break;
			}
			this.events.push(event);
			if (event.kind === 'presentation' && event.presentation) {
				const legacyLiveReset = event.reset_protocol === undefined && event.presentation.kind === 'live';
				if (event.reset_protocol === true || legacyLiveReset) this.protocolChunks.splice(0);
				const generation = event.protocol_generation ?? event.presentation.protocol_generation;
				if (Number.isSafeInteger(generation) && generation! >= 0) {
					this.protocolGeneration = generation!;
				} else if (event.reset_protocol === true || legacyLiveReset) {
					this.protocolGeneration++;
				}
				this.presentation = { ...event.presentation, protocol_generation: this.protocolGeneration };
			} else if (event.kind === 'protocol' && typeof event.chunk === 'string') {
				this.protocolChunks.push(event.chunk);
			} else {
				recoveryReason = `line ${index + 1} is missing its ${event.kind} payload`;
				this.events.pop();
				break;
			}
			retainedLines.push(line);
		}
		if (recoveryReason) this.recoverLog(retainedLines, recoveryReason);
	}

	private recoverLog(retainedLines: string[], reason: string) {
		this.deliveryErrors.push(`Recovered tournament spectator event history: ${reason}`);
		try {
			fs.writeFileSync(this.filename!, retainedLines.length ? `${retainedLines.join('\n')}\n` : '', 'utf8');
		} catch (error) {
			this.persistenceDisabled = true;
			this.deliveryErrors.push(`Tournament spectator event persistence disabled: ${errorMessage(error)}`);
		}
	}
}

function errorMessage(error: unknown) {
	return error instanceof Error ? error.message : String(error);
}
