export interface SpectatorSink {
	publish(chunk: string): void;
}

export class SpectatorPublisher {
	private readonly sinks = new Set<SpectatorSink>();
	private readonly failureHandler: (error: unknown) => void;

	constructor(sinks: SpectatorSink[] = [], failureHandler: (error: unknown) => void = () => {}) {
		for (const sink of sinks) this.sinks.add(sink);
		this.failureHandler = failureHandler;
	}

	addSink(sink: SpectatorSink) {
		this.sinks.add(sink);
		return () => this.sinks.delete(sink);
	}

	publish(chunk: string) {
		for (const sink of this.sinks) {
			try {
				sink.publish(chunk);
			} catch (error) {
				this.failureHandler(error);
			}
		}
	}
}

export class ProtocolRecorder implements SpectatorSink {
	readonly chunks: string[] = [];

	publish(chunk: string) {
		this.chunks.push(chunk);
	}
}
