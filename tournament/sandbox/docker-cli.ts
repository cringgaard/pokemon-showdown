import { execFile, spawn, type ChildProcessWithoutNullStreams } from 'child_process';

export const DEFAULT_DOCKER_COMMAND_TIMEOUT_MS = 30_000;
export const DEFAULT_DOCKER_OUTPUT_BYTES = 2 * 1024 * 1024;

export class DockerUnavailableError extends Error {
	override name = 'DockerUnavailableError';
}

export class DockerCommandError extends Error {
	override name = 'DockerCommandError';
}

export interface DockerCommandOptions {
	timeoutMs?: number;
	maxOutputBytes?: number;
	input?: string;
}

export interface DockerCommandResult {
	stdout: string;
	stderr: string;
}

export async function assertDockerAvailable() {
	try {
		await runDocker(['version', '--format', '{{.Server.Version}}'], { timeoutMs: 10_000, maxOutputBytes: 256 * 1024 });
	} catch (error) {
		throw new DockerUnavailableError(
			'Docker isolation is required but Docker Engine is unavailable. Install/start Docker Desktop or Docker Engine, ' +
			'or explicitly use --runtime host only for trusted development. ' + errorMessage(error)
		);
	}
}

export function runDocker(args: string[], options: DockerCommandOptions = {}) {
	return new Promise<DockerCommandResult>((resolve, reject) => {
		const child = execFile('docker', args, {
			encoding: 'utf8',
			timeout: options.timeoutMs ?? DEFAULT_DOCKER_COMMAND_TIMEOUT_MS,
			maxBuffer: options.maxOutputBytes ?? DEFAULT_DOCKER_OUTPUT_BYTES,
		}, (error, stdout, stderr) => {
			if (error) {
				reject(new DockerCommandError(
					`docker ${displayArgs(args)} failed: ${error.message}${stderr ? `\n${String(stderr).slice(-4000)}` : ''}`
				));
				return;
			}
			resolve({ stdout: String(stdout), stderr: String(stderr) });
		});
		if (options.input !== undefined) child.stdin?.end(options.input);
	});
}

export function spawnDocker(args: string[]): ChildProcessWithoutNullStreams {
	return spawn('docker', args, { stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
}

export async function inspectImageID(reference: string) {
	try {
		const result = await runDocker(['image', 'inspect', '--format', '{{.Id}}', reference], {
			timeoutMs: 10_000,
			maxOutputBytes: 256 * 1024,
		});
		return result.stdout.trim() || null;
	} catch {
		return null;
	}
}

export async function removeContainer(container: string) {
	try {
		await runDocker(['container', 'rm', '--force', container], { timeoutMs: 10_000, maxOutputBytes: 256 * 1024 });
	} catch {}
}

function displayArgs(args: string[]) {
	return args.map(arg => /^[a-zA-Z0-9._:@=/-]+$/.test(arg) ? arg : JSON.stringify(arg)).join(' ');
}

function errorMessage(error: unknown) {
	return error instanceof Error ? error.message : String(error);
}
