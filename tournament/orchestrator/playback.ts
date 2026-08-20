export type PlaybackCompletionReason = 'spectator' | 'operator' | 'timeout' | 'automated';
export const DEFAULT_PLAYBACK_TIMEOUT_MS = 300_000;

export interface PlaybackAcknowledgement {
	accepted: boolean;
	duplicate: boolean;
}

export interface TournamentPlaybackControllerOptions {
	timeoutMs?: number;
	autoComplete?: boolean;
}

export class TournamentPlaybackController {
	readonly timeoutMs: number;
	readonly autoComplete: boolean;
	private readonly completedGenerations = new Set<number>();
	private activeGeneration: number | null = null;
	private pendingGeneration: number | null = null;
	private pendingResolver: ((reason: PlaybackCompletionReason) => void) | null = null;
	private timeout: NodeJS.Timeout | null = null;
	private lastCompletionReason: PlaybackCompletionReason | null = null;

	constructor(options: TournamentPlaybackControllerOptions = {}) {
		this.timeoutMs = options.timeoutMs ?? DEFAULT_PLAYBACK_TIMEOUT_MS;
		this.autoComplete = options.autoComplete ?? false;
		if (!Number.isSafeInteger(this.timeoutMs) || this.timeoutMs <= 0) {
			throw new Error('Playback completion timeout must be a positive integer.');
		}
	}

	beginGeneration(protocolGeneration: number) {
		assertGeneration(protocolGeneration);
		if (this.activeGeneration !== null && this.activeGeneration !== protocolGeneration) {
			throw new Error('A tournament playback generation is already active.');
		}
		this.activeGeneration = protocolGeneration;
	}

	waitForCompletion(protocolGeneration: number): Promise<PlaybackCompletionReason> {
		assertGeneration(protocolGeneration);
		if (this.activeGeneration !== protocolGeneration) {
			throw new Error('The requested tournament playback generation is not active.');
		}
		if (this.autoComplete) {
			this.lastCompletionReason = 'automated';
			this.activeGeneration = null;
			return Promise.resolve('automated');
		}
		if (this.completedGenerations.has(protocolGeneration)) {
			this.lastCompletionReason = 'spectator';
			this.activeGeneration = null;
			return Promise.resolve('spectator');
		}
		if (this.pendingResolver) throw new Error('A tournament playback generation is already pending.');
		this.pendingGeneration = protocolGeneration;
		return new Promise(resolve => {
			this.pendingResolver = resolve;
			this.timeout = setTimeout(() => this.complete('timeout'), this.timeoutMs);
		});
	}

	acknowledge(protocolGeneration: number): PlaybackAcknowledgement {
		assertGeneration(protocolGeneration);
		const duplicate = this.completedGenerations.has(protocolGeneration);
		if (!duplicate && this.activeGeneration !== protocolGeneration) return { accepted: false, duplicate: false };
		this.completedGenerations.add(protocolGeneration);
		if (this.pendingGeneration === protocolGeneration) this.complete('spectator');
		return { accepted: !duplicate, duplicate };
	}

	forceComplete() {
		if (!this.pendingResolver || this.pendingGeneration === null) return false;
		this.completedGenerations.add(this.pendingGeneration);
		this.complete('operator');
		return true;
	}

	status() {
		return {
			waiting: !!this.pendingResolver,
			protocol_generation: this.activeGeneration,
			timeout_ms: this.timeoutMs,
			auto_complete: this.autoComplete,
			last_completion_reason: this.lastCompletionReason,
		};
	}

	private complete(reason: PlaybackCompletionReason) {
		if (!this.pendingResolver) return;
		const resolve = this.pendingResolver;
		this.pendingResolver = null;
		this.pendingGeneration = null;
		this.activeGeneration = null;
		this.lastCompletionReason = reason;
		if (this.timeout) clearTimeout(this.timeout);
		this.timeout = null;
		resolve(reason);
	}
}

function assertGeneration(protocolGeneration: number) {
	if (!Number.isSafeInteger(protocolGeneration) || protocolGeneration < 0) {
		throw new Error('protocol_generation must be a non-negative integer.');
	}
}
