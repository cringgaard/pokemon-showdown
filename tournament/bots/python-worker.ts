import { spawn, type ChildProcessWithoutNullStreams } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as readline from 'readline';
import type { BotState } from '../api/types';

export class BotTimeoutError extends Error {}
export class BotExecutionError extends Error {}

interface PendingDecision {
	revision: number;
	resolve: (response: unknown) => void;
	reject: (error: Error) => void;
	timer: NodeJS.Timeout;
}

export interface PythonWorkerOptions {
	python?: string;
	workerScript?: string;
	seed?: string;
}

export class PythonWorker {
	readonly modulePath: string;
	readonly stderr: string[] = [];
	private readonly options: PythonWorkerOptions;
	private process: ChildProcessWithoutNullStreams | null = null;
	private readonly pending = new Map<number, PendingDecision>();

	constructor(modulePath: string, options: PythonWorkerOptions = {}) {
		this.modulePath = path.resolve(modulePath);
		this.options = options;
	}

	start() {
		if (this.process) return;
		const workerScript = this.options.workerScript || findWorkerScript();
		this.process = spawn(this.options.python || process.env.PYTHON || 'python', [workerScript, this.modulePath], {
			cwd: path.dirname(this.modulePath),
			env: { ...process.env, BOT_SEED: this.options.seed || '' },
			stdio: ['pipe', 'pipe', 'pipe'],
		});
		const lines = readline.createInterface({ input: this.process.stdout });
		lines.on('line', line => this.receiveLine(line));
		this.process.stderr.on('data', chunk => this.stderr.push(String(chunk)));
		this.process.on('error', error => this.failAll(new BotExecutionError(error.message)));
		this.process.on('exit', (code, signal) => {
			const wasRunning = !!this.process;
			this.process = null;
			if (wasRunning && this.pending.size) {
				this.failAll(new BotExecutionError(`Python worker exited (code=${code}, signal=${signal})`));
			}
		});
	}

	decide(id: number, revision: number, state: BotState, timeoutMs: number): Promise<unknown> {
		this.start();
		if (!this.process) return Promise.reject(new BotExecutionError('Python worker failed to start'));
		return new Promise((resolve, reject) => {
			const timer = setTimeout(() => {
				this.pending.delete(id);
				this.terminate();
				reject(new BotTimeoutError(`Bot decision ${id}.${revision} exceeded ${timeoutMs} ms`));
			}, timeoutMs);
			this.pending.set(id, { revision, resolve, reject, timer });
			this.process!.stdin.write(`${JSON.stringify({ type: 'decision', id, revision, state })}\n`);
		});
	}

	terminate() {
		const child = this.process;
		this.process = null;
		if (child && !child.killed) child.kill();
		this.failAll(new BotExecutionError('Python worker terminated'));
	}

	async stop() {
		const child = this.process;
		this.process = null;
		if (!child) return;
		child.stdin.end();
		if (child.exitCode !== null) return;
		await new Promise<void>(resolve => {
			child.once('exit', () => resolve());
			setTimeout(() => {
				if (!child.killed) child.kill();
				resolve();
			}, 250).unref();
		});
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

	private rejectOldest(error: Error) {
		const first = this.pending.entries().next().value;
		if (!first) return;
		clearTimeout(first[1].timer);
		this.pending.delete(first[0]);
		first[1].reject(error);
	}

	private failAll(error: Error) {
		for (const pending of this.pending.values()) {
			clearTimeout(pending.timer);
			pending.reject(error);
		}
		this.pending.clear();
	}
}

function findWorkerScript() {
	const besideSource = path.resolve(__dirname, '../../../tournament/bots/worker.py');
	if (fs.existsSync(besideSource)) return besideSource;
	return path.resolve(__dirname, 'worker.py');
}
