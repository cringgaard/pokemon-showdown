import type { BotState } from '../api/types';

export interface BotWorkerOptions {
	seed?: string;
}

export interface BotWorker {
	readonly stderr: string[];
	start(): Promise<void>;
	decide(id: number, revision: number, state: BotState, timeoutMs: number): Promise<unknown>;
	terminate(): Promise<void>;
	stop(): Promise<void>;
}

export interface RuntimeAudit {
	kind: 'host' | 'docker';
	trusted: boolean;
	[key: string]: unknown;
}

export interface BotWorkerFactory {
	readonly audit: RuntimeAudit;
	create(modulePath: string, options: BotWorkerOptions): BotWorker;
}
