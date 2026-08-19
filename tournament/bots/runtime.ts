import { createHash } from 'crypto';
import type { BotResponse, BotState, RuntimeInfo } from '../api/types';
import { validateResponse } from '../actions/action-validator';
import {
	BotExecutionError, BotTimeoutError, HostPythonWorkerFactory, type PythonWorkerOptions,
} from './python-worker';
import { DEFAULT_MAX_STDERR_BYTES, STDERR_TRUNCATION_MARKER } from './jsonl-worker';
import type { BotWorker, BotWorkerFactory } from './worker-interface';

export interface RuntimeStats {
	decisions: number;
	timeouts: number;
	invalid_responses: number;
	fallbacks: number;
	exceptions: number;
}

export interface RuntimeLogEntry {
	decision_id: number;
	revision: number;
	reason: string;
}

export interface BotControllerOptions extends PythonWorkerOptions {
	decisionTimeoutMs?: number;
	maxInvalidAttempts?: number;
	fallbackKey: string;
	workerFactory?: BotWorkerFactory;
}

export interface DecisionOptions {
	decisionID: number;
	revision: number;
	deadlineAt: number;
	newDecision: boolean;
	buildState: (runtime: RuntimeInfo) => BotState;
}

export class BotController {
	readonly stats: RuntimeStats = {
		decisions: 0, timeouts: 0, invalid_responses: 0, fallbacks: 0, exceptions: 0,
	};
	readonly logs: RuntimeLogEntry[] = [];
	private worker: BotWorker;
	private readonly stderrLog: string[] = [];
	private stderrLogBytes = 0;
	private stderrLogTruncated = false;
	private readonly maxStderrBytes: number;
	private readonly modulePath: string;
	private readonly options: Required<Pick<BotControllerOptions, 'decisionTimeoutMs' | 'maxInvalidAttempts'>> &
		BotControllerOptions;

	constructor(modulePath: string, options: BotControllerOptions) {
		this.modulePath = modulePath;
		this.options = {
			...options,
			decisionTimeoutMs: options.decisionTimeoutMs ?? 5000,
			maxInvalidAttempts: options.maxInvalidAttempts ?? 3,
		};
		this.maxStderrBytes = options.maxStderrBytes ?? DEFAULT_MAX_STDERR_BYTES;
		this.worker = this.createWorker();
	}

	async decide(options: DecisionOptions): Promise<BotResponse> {
		if (options.newDecision) this.stats.decisions++;
		let previousError: string | null = null;
		for (let attempt = 1; attempt <= this.options.maxInvalidAttempts; attempt++) {
			const remaining = Math.max(0, Math.min(this.options.decisionTimeoutMs, options.deadlineAt - Date.now()));
			const runtime: RuntimeInfo = {
				decision_id: options.decisionID,
				revision: options.revision,
				attempt,
				previous_error: previousError,
				deadline_ms: remaining,
			};
			const state = options.buildState(runtime);
			if (!remaining) return this.fallback(state, options, 'deadline expired');
			try {
				const response = await this.worker.decide(options.decisionID, options.revision, state, remaining);
				const valid = validateResponse(state.request, response);
				if (valid) return valid;
				this.stats.invalid_responses++;
				previousError = 'Response did not match request.legal_actions';
			} catch (error) {
				if (error instanceof BotTimeoutError) {
					this.stats.timeouts++;
					this.appendStderr(this.worker.stderr);
					this.worker = this.createWorker();
					void this.worker.start().catch(() => {});
					return this.fallback(state, options, error.message);
				}
				this.stats.exceptions++;
				this.stats.invalid_responses++;
				previousError = error instanceof BotExecutionError ? error.message : String(error);
			}
		}
		const finalState = options.buildState({
			decision_id: options.decisionID,
			revision: options.revision,
			attempt: this.options.maxInvalidAttempts,
			previous_error: previousError,
			deadline_ms: Math.max(0, options.deadlineAt - Date.now()),
		});
		return this.fallback(finalState, options, 'maximum invalid attempts exhausted');
	}

	async start() {
		await this.worker.start();
	}

	async stop() {
		await this.worker.stop();
	}

	stderr() {
		return boundedMessages([...this.stderrLog, ...this.worker.stderr], this.maxStderrBytes);
	}

	private fallback(state: BotState, options: DecisionOptions, reason: string) {
		if (!state.request.legal_actions.length) throw new Error('No legal action is available for fallback');
		const digest = createHash('sha256').update([
			this.options.fallbackKey, options.decisionID, options.revision,
		].join(':')).digest();
		const index = digest.readUInt32BE(0) % state.request.legal_actions.length;
		this.stats.fallbacks++;
		this.logs.push({ decision_id: options.decisionID, revision: options.revision, reason });
		return state.request.legal_actions[index];
	}

	private createWorker() {
		const factory = this.options.workerFactory || new HostPythonWorkerFactory({
			python: this.options.python,
			workerScript: this.options.workerScript,
			maxProtocolLineBytes: this.options.maxProtocolLineBytes,
			maxStderrBytes: this.options.maxStderrBytes,
		});
		return factory.create(this.modulePath, { seed: this.options.seed });
	}

	private appendStderr(messages: string[]) {
		if (this.stderrLogTruncated) return;
		for (const message of messages) {
			const remaining = this.maxStderrBytes - this.stderrLogBytes;
			if (remaining <= 0) break;
			const buffer = Buffer.from(message);
			const retained = buffer.subarray(0, remaining);
			this.stderrLog.push(retained.toString('utf8'));
			this.stderrLogBytes += retained.length;
			if (retained.length < buffer.length) break;
		}
		if (this.stderrLogBytes >= this.maxStderrBytes) {
			this.stderrLogTruncated = true;
			this.stderrLog.push(STDERR_TRUNCATION_MARKER);
		}
	}
}

function boundedMessages(messages: string[], maxBytes: number) {
	const result: string[] = [];
	let bytes = 0;
	for (const message of messages) {
		if (message === STDERR_TRUNCATION_MARKER) {
			if (!result.includes(STDERR_TRUNCATION_MARKER)) result.push(message);
			continue;
		}
		const remaining = maxBytes - bytes;
		if (remaining <= 0) break;
		const buffer = Buffer.from(message);
		const retained = buffer.subarray(0, remaining);
		result.push(retained.toString('utf8'));
		bytes += retained.length;
		if (retained.length < buffer.length) break;
	}
	if (bytes >= maxBytes && !result.includes(STDERR_TRUNCATION_MARKER)) result.push(STDERR_TRUNCATION_MARKER);
	return result;
}
