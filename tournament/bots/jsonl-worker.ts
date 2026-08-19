import type { ChildProcessWithoutNullStreams } from 'child_process';
import type { BotState } from '../api/types';
import { BotExecutionError, BotTimeoutError } from './python-worker-errors';
import type { BotWorker } from './worker-interface';

export const DEFAULT_MAX_PROTOCOL_LINE_BYTES = 1024 * 1024;
export const DEFAULT_MAX_STDERR_BYTES = 256 * 1024;
export const STDERR_TRUNCATION_MARKER = '[tournament] participant stderr truncated at configured byte limit\n';

interface PendingDecision {
	revision: number;
	resolve: (response: unknown) => void;
	reject: (error: Error) => void;
	timer: NodeJS.Timeout;
}

export interface JSONLWorkerLimits {
	maxProtocolLineBytes?: number;
	maxStderrBytes?: number;
}

export abstract class JSONLWorker implements BotWorker {
	readonly stderr: string[] = [];
	private readonly maxProtocolLineBytes: number;
	private readonly maxStderrBytes: number;
	private stderrBytes = 0;
	private stderrTruncated = false;
	private stdoutBuffer = Buffer.alloc(0);
	private process: ChildProcessWithoutNullStreams | null = null;
	private startPromise: Promise<void> | null = null;
	private readonly pending = new Map<number, PendingDecision>();

	constructor(limits: JSONLWorkerLimits = {}) {
		this.maxProtocolLineBytes = limits.maxProtocolLineBytes ?? DEFAULT_MAX_PROTOCOL_LINE_BYTES;
		this.maxStderrBytes = limits.maxStderrBytes ?? DEFAULT_MAX_STDERR_BYTES;
	}

	async start() {
		if (this.process) return;
		if (this.startPromise) return this.startPromise;
		this.startPromise = this.startProcess().finally(() => {
			this.startPromise = null;
		});
		return this.startPromise;
	}

	async decide(id: number, revision: number, state: BotState, timeoutMs: number): Promise<unknown> {
		const deadlineAt = Date.now() + timeoutMs;
		await this.start();
		if (!this.process) throw new BotExecutionError('Participant worker failed to start');
		const remaining = Math.max(0, deadlineAt - Date.now());
		if (!remaining) {
			await this.terminateWithError(new BotExecutionError('Participant worker startup exhausted the decision deadline'));
			throw new BotTimeoutError(`Bot decision ${id}.${revision} exceeded ${timeoutMs} ms`);
		}
		return new Promise((resolve, reject) => {
			const timer = setTimeout(() => void this.timeout(id, revision, timeoutMs), remaining);
			this.pending.set(id, { revision, resolve, reject, timer });
			this.process!.stdin.write(`${JSON.stringify({ type: 'decision', id, revision, state })}\n`, error => {
				if (error) this.rejectDecision(id, new BotExecutionError(`Could not write to participant worker: ${error.message}`));
			});
		});
	}

	async terminate() {
		await this.terminateWithError(new BotExecutionError('Participant worker terminated'));
	}

	async stop() {
		if (this.startPromise) {
			try {
				await this.startPromise;
			} catch {}
		}
		const child = this.process;
		this.process = null;
		if (!child) {
			await this.cleanupAfterExit();
			return;
		}
		child.stdin.end();
		if (child.exitCode === null) {
			const exited = await waitForClose(child, 250);
			if (!exited) await this.killProcess(child);
		}
		releaseChildHandles(child);
		await this.cleanupAfterExit();
		this.failAll(new BotExecutionError('Participant worker stopped'));
	}

	protected abstract launchProcess(): Promise<ChildProcessWithoutNullStreams>;
	protected abstract killProcess(child: ChildProcessWithoutNullStreams): Promise<void>;
	protected async cleanupAfterExit() {}

	private async startProcess() {
		this.stdoutBuffer = Buffer.alloc(0);
		let child: ChildProcessWithoutNullStreams;
		try {
			child = await this.launchProcess();
		} catch (error) {
			throw error instanceof BotExecutionError ? error : new BotExecutionError(String(error));
		}
		this.process = child;
		child.stdout.on('data', chunk => this.receiveData(Buffer.from(chunk)));
		child.stderr.on('data', chunk => this.captureStderr(Buffer.from(chunk)));
		child.on('error', error => void this.terminateWithError(new BotExecutionError(error.message)));
		child.on('exit', (code, signal) => {
			if (this.process === child) this.process = null;
			if (this.pending.size) {
				this.failAll(new BotExecutionError(`Participant worker exited (code=${code}, signal=${signal})`));
			}
			void this.cleanupAfterExit();
		});
	}

	private receiveData(chunk: Buffer) {
		let data = this.stdoutBuffer.length ? Buffer.concat([this.stdoutBuffer, chunk]) : chunk;
		let newline = data.indexOf(0x0A);
		while (newline >= 0) {
			if (newline > this.maxProtocolLineBytes) {
				void this.protocolFailure(`Participant worker JSONL line exceeded ${this.maxProtocolLineBytes} bytes`);
				return;
			}
			const line = data.subarray(0, newline);
			this.receiveLine(line.toString('utf8').replace(/\r$/, ''));
			data = data.subarray(newline + 1);
			newline = data.indexOf(0x0A);
		}
		if (data.length > this.maxProtocolLineBytes) {
			void this.protocolFailure(`Participant worker JSONL line exceeded ${this.maxProtocolLineBytes} bytes`);
			return;
		}
		this.stdoutBuffer = data.length ? Buffer.from(data) : Buffer.alloc(0);
	}

	private receiveLine(line: string) {
		let message: Record<string, unknown>;
		try {
			message = JSON.parse(line);
		} catch {
			this.rejectOldest(new BotExecutionError(`Malformed worker JSONL: ${line.slice(0, 200)}`));
			return;
		}
		const id = Number(message.id);
		const pending = this.pending.get(id);
		if (!pending || Number(message.revision) !== pending.revision) return;
		clearTimeout(pending.timer);
		this.pending.delete(id);
		if (message.type === 'result') {
			pending.resolve(message.response);
		} else {
			const detail = typeof message.error === 'string' ? message.error : JSON.stringify(message.error);
			pending.reject(new BotExecutionError(detail || 'Unknown participant error'));
		}
	}

	private captureStderr(chunk: Buffer) {
		if (this.stderrTruncated) return;
		const remaining = this.maxStderrBytes - this.stderrBytes;
		if (remaining > 0) {
			const retained = chunk.subarray(0, remaining);
			this.stderr.push(retained.toString('utf8'));
			this.stderrBytes += retained.length;
		}
		if (chunk.length > remaining) {
			this.stderrTruncated = true;
			this.stderr.push(STDERR_TRUNCATION_MARKER);
		}
	}

	private async timeout(id: number, revision: number, timeoutMs: number) {
		const pending = this.pending.get(id);
		if (!pending || pending.revision !== revision) return;
		clearTimeout(pending.timer);
		this.pending.delete(id);
		await this.terminateWithError(new BotExecutionError('Participant worker terminated after decision timeout'));
		pending.reject(new BotTimeoutError(`Bot decision ${id}.${revision} exceeded ${timeoutMs} ms`));
	}

	private async protocolFailure(message: string) {
		await this.terminateWithError(new BotExecutionError(message));
	}

	private async terminateWithError(error: Error) {
		const child = this.process;
		this.process = null;
		if (child) {
			try {
				await this.killProcess(child);
			} catch (cleanupError) {
				this.captureStderr(Buffer.from(
					`[tournament] worker cleanup failed: ${cleanupError instanceof Error ? cleanupError.message : cleanupError}\n`
				));
			}
		}
		await this.cleanupAfterExit();
		this.failAll(error);
	}

	private rejectDecision(id: number, error: Error) {
		const pending = this.pending.get(id);
		if (!pending) return;
		clearTimeout(pending.timer);
		this.pending.delete(id);
		pending.reject(error);
	}

	private rejectOldest(error: Error) {
		const first = this.pending.entries().next().value;
		if (first) this.rejectDecision(first[0], error);
	}

	private failAll(error: Error) {
		for (const pending of this.pending.values()) {
			clearTimeout(pending.timer);
			pending.reject(error);
		}
		this.pending.clear();
	}
}

function releaseChildHandles(child: ChildProcessWithoutNullStreams) {
	child.stdin.destroy();
	child.stdout.destroy();
	child.stderr.destroy();
	unrefStream(child.stdin);
	unrefStream(child.stdout);
	unrefStream(child.stderr);
	child.unref();
}

function unrefStream(stream: unknown) {
	(stream as { unref?: () => void }).unref?.();
}

function waitForClose(child: ChildProcessWithoutNullStreams, timeoutMs: number) {
	return new Promise<boolean>(resolve => {
		const timer = setTimeout(() => {
			child.off('close', onClose);
			resolve(false);
		}, timeoutMs);
		const onClose = () => {
			clearTimeout(timer);
			resolve(true);
		};
		child.once('close', onClose);
	});
}
