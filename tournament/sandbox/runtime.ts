import { randomBytes } from 'crypto';
import type { ChildProcessWithoutNullStreams } from 'child_process';
import { JSONLWorker, type JSONLWorkerLimits } from '../bots/jsonl-worker';
import { BotExecutionError } from '../bots/python-worker';
import type { BotWorkerFactory, BotWorkerOptions } from '../bots/worker-interface';
import { removeContainer, runDocker, spawnDocker } from './docker-cli';
import {
	containerCreateArgs, DEFAULT_DOCKER_RESOURCE_POLICY, MANAGED_CONTAINER_LABEL,
	type DockerResourcePolicy, type PreparedDockerRuntimeAudit,
} from './policy';

export class DockerPythonWorkerFactory implements BotWorkerFactory {
	readonly audit: PreparedDockerRuntimeAudit;
	readonly imageID: string;
	readonly policy: DockerResourcePolicy;
	private readonly limits: JSONLWorkerLimits;

	constructor(
		imageID: string, audit: PreparedDockerRuntimeAudit,
		policy: DockerResourcePolicy = DEFAULT_DOCKER_RESOURCE_POLICY, limits: JSONLWorkerLimits = {}
	) {
		this.imageID = imageID;
		this.audit = audit;
		this.policy = policy;
		this.limits = limits;
	}

	create(_modulePath: string, options: BotWorkerOptions) {
		return new DockerPythonWorker(this.imageID, {
			seed: options.seed || '', policy: this.policy, contentHash: this.audit.content_hash, ...this.limits,
		});
	}
}

export interface DockerPythonWorkerOptions extends JSONLWorkerLimits {
	seed: string;
	policy?: DockerResourcePolicy;
	contentHash?: string;
}

export class DockerPythonWorker extends JSONLWorker {
	readonly imageID: string;
	readonly options: DockerPythonWorkerOptions;
	containerID: string | null = null;
	containerName: string | null = null;
	private cleanupPromise: Promise<void> | null = null;

	constructor(imageID: string, options: DockerPythonWorkerOptions) {
		super(options);
		this.imageID = imageID;
		this.options = options;
	}

	protected async launchProcess() {
		await this.cleanupAfterExit();
		const name = `ps-tournament-${process.pid}-${Date.now()}-${randomBytes(6).toString('hex')}`;
		const labels: Record<string, string> = {};
		if (this.options.contentHash) {
			labels['org.pokemon-showdown.tournament.content-hash'] = this.options.contentHash;
		}
		const result = await runDocker(containerCreateArgs(
			this.imageID, name, this.options.seed, this.options.policy || DEFAULT_DOCKER_RESOURCE_POLICY, labels
		));
		const id = result.stdout.trim();
		if (!id) throw new BotExecutionError('Docker did not return a container ID after container creation.');
		this.containerName = name;
		this.containerID = id;
		return spawnDocker(['container', 'start', '--attach', '--interactive', id]);
	}

	protected async killProcess(child: ChildProcessWithoutNullStreams) {
		const container = this.containerID || this.containerName;
		if (container) {
			try {
				await runDocker(['container', 'kill', container], { timeoutMs: 10_000, maxOutputBytes: 256 * 1024 });
			} catch {}
			await removeContainer(container);
		}
		if (child.exitCode === null && !child.killed) child.kill('SIGKILL');
		child.stdin.destroy();
		child.stdout.destroy();
		child.stderr.destroy();
		unrefStream(child.stdin);
		unrefStream(child.stdout);
		unrefStream(child.stderr);
		child.unref();
		this.containerID = null;
		this.containerName = null;
	}

	protected override async cleanupAfterExit() {
		if (this.cleanupPromise) return this.cleanupPromise;
		const container = this.containerID || this.containerName;
		if (!container) return;
		this.containerID = null;
		this.containerName = null;
		this.cleanupPromise = removeContainer(container).finally(() => {
			this.cleanupPromise = null;
		});
		return this.cleanupPromise;
	}
}

function unrefStream(stream: unknown) {
	(stream as { unref?: () => void }).unref?.();
}

export async function managedContainerIDs() {
	const result = await runDocker([
		'container', 'ls', '--all', '--quiet', '--filter', `label=${MANAGED_CONTAINER_LABEL}=true`,
	], { timeoutMs: 10_000, maxOutputBytes: 256 * 1024 });
	return result.stdout.trim() ? result.stdout.trim().split(/\r?\n/) : [];
}
