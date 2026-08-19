import type { SpectatorSink } from './spectator-publisher';

export interface StoredProtocolChunk {
	sequence: number;
	chunk: string;
}

export class ProtocolStore implements SpectatorSink {
	readonly chunks: StoredProtocolChunk[] = [];
	metadata: unknown;
	result: unknown;
	complete = false;
	private readonly listeners = new Set<(entry: StoredProtocolChunk) => void>();
	private readonly completionListeners = new Set<() => void>();

	constructor(options: { metadata?: unknown, result?: unknown, protocol?: string } = {}) {
		this.metadata = options.metadata ?? null;
		this.result = options.result ?? null;
		if (options.protocol) this.publish(options.protocol);
	}

	publish(chunk: string) {
		const entry = { sequence: this.chunks.length + 1, chunk };
		this.chunks.push(entry);
		for (const listener of this.listeners) {
			try {
				listener(entry);
			} catch {}
		}
	}

	subscribe(listener: (entry: StoredProtocolChunk) => void) {
		this.listeners.add(listener);
		return () => this.listeners.delete(listener);
	}

	onComplete(listener: () => void) {
		this.completionListeners.add(listener);
		return () => this.completionListeners.delete(listener);
	}

	setResult(result: unknown) {
		this.result = result;
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
		return this.chunks.map(entry => entry.chunk).join('\n');
	}
}
