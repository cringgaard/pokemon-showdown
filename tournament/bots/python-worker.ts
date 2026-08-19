import { spawn, type ChildProcessWithoutNullStreams } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { JSONLWorker, type JSONLWorkerLimits } from './jsonl-worker';
import { BotExecutionError, BotTimeoutError } from './python-worker-errors';
import type { BotWorkerFactory, BotWorkerOptions, RuntimeAudit } from './worker-interface';

export { BotExecutionError, BotTimeoutError };

export interface PythonWorkerOptions extends BotWorkerOptions, JSONLWorkerLimits {
	python?: string;
	workerScript?: string;
}

export class PythonWorker extends JSONLWorker {
	readonly modulePath: string;
	private readonly options: PythonWorkerOptions;

	constructor(modulePath: string, options: PythonWorkerOptions = {}) {
		super(options);
		this.modulePath = path.resolve(modulePath);
		this.options = options;
	}

	protected launchProcess() {
		const workerScript = this.options.workerScript || findWorkerScript();
		return Promise.resolve(spawn(this.options.python || process.env.PYTHON || 'python', [workerScript, this.modulePath], {
			cwd: path.dirname(this.modulePath),
			detached: process.platform !== 'win32',
			env: { ...process.env, BOT_SEED: this.options.seed || '' },
			stdio: ['pipe', 'pipe', 'pipe'],
		}));
	}

	protected killProcess(child: ChildProcessWithoutNullStreams) {
		if (child.exitCode !== null) return Promise.resolve();
		if (process.platform === 'win32') {
			child.kill('SIGKILL');
			closeChildStreams(child);
			child.unref();
			return Promise.resolve();
		}
		try {
			process.kill(-(child.pid || 0), 'SIGKILL');
		} catch {
			if (!child.killed) child.kill('SIGKILL');
		}
		closeChildStreams(child);
		child.unref();
		return Promise.resolve();
	}
}

function closeChildStreams(child: ChildProcessWithoutNullStreams) {
	child.stdin.destroy();
	child.stdout.destroy();
	child.stderr.destroy();
	unrefStream(child.stdin);
	unrefStream(child.stdout);
	unrefStream(child.stderr);
}

function unrefStream(stream: unknown) {
	(stream as { unref?: () => void }).unref?.();
}

export class HostPythonWorkerFactory implements BotWorkerFactory {
	readonly audit: RuntimeAudit = {
		kind: 'host',
		trusted: true,
		isolation: 'none',
		warning: 'Trusted development mode; participant code runs directly on the host.',
	};
	private readonly options: Omit<PythonWorkerOptions, 'seed'>;

	constructor(options: Omit<PythonWorkerOptions, 'seed'> = {}) {
		this.options = options;
	}

	create(modulePath: string, options: BotWorkerOptions) {
		return new PythonWorker(modulePath, { ...this.options, ...options });
	}
}

function findWorkerScript() {
	const besideSource = path.resolve(__dirname, '../../../tournament/bots/worker.py');
	if (fs.existsSync(besideSource)) return besideSource;
	return path.resolve(__dirname, 'worker.py');
}
