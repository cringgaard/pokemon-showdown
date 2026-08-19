import type { TournamentEventStore, TournamentPresentationState } from '../spectator/event-store';

export class TournamentPacingController {
	readonly autoAdvance: boolean;
	readonly eventStore: TournamentEventStore;
	private resolver: (() => void) | null = null;
	private primary: TournamentPresentationState | null = null;
	private standings: TournamentPresentationState | null = null;

	constructor(eventStore: TournamentEventStore, autoAdvance = false) {
		this.eventStore = eventStore;
		this.autoAdvance = autoAdvance;
	}

	wait(primary: TournamentPresentationState, standings?: TournamentPresentationState) {
		this.primary = primary;
		this.standings = standings || null;
		if (this.autoAdvance) return Promise.resolve();
		return new Promise<void>(resolve => {
			this.resolver = resolve;
		});
	}

	advance() {
		if (!this.resolver) return false;
		const resolve = this.resolver;
		this.resolver = null;
		resolve();
		return true;
	}

	showStandings() {
		if (!this.standings) return false;
		this.eventStore.publishPresentation(this.standings);
		return true;
	}

	showPrimary() {
		if (!this.primary) return false;
		this.eventStore.publishPresentation(this.primary);
		return true;
	}

	status() {
		return {
			waiting: !!this.resolver,
			auto_advance: this.autoAdvance,
			primary: this.primary?.kind || null,
			standings_available: !!this.standings,
		};
	}
}
