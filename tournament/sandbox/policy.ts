import type { RuntimeAudit } from '../bots/worker-interface';

export const SANDBOX_POLICY_VERSION = 1;
export const PYTHON_BASE_IMAGE = 'python:3.12.13-slim-bookworm';
export const PYTHON_RUNTIME_VERSION = '3.12.13';
export const CONTAINER_USER = '10001:10001';
export const MANAGED_CONTAINER_LABEL = 'org.pokemon-showdown.tournament.managed';
export const SANDBOX_VERSION_LABEL = 'org.pokemon-showdown.tournament.sandbox-version';

export interface DockerResourcePolicy {
	memoryMB: number;
	cpus: number;
	pids: number;
	tmpfsMB: number;
	nofile: number;
}

export const DEFAULT_DOCKER_RESOURCE_POLICY: DockerResourcePolicy = {
	memoryMB: 512,
	cpus: 1,
	pids: 64,
	tmpfsMB: 64,
	nofile: 256,
};

export const PROCESS_ENVIRONMENT_ALLOWLIST = [
	'BOT_SEED', 'HOME', 'LANG', 'PATH', 'PYTHONDONTWRITEBYTECODE', 'PYTHONPATH', 'PYTHONUNBUFFERED', 'TMPDIR',
] as const;

export interface PreparedDockerRuntimeAudit extends RuntimeAudit {
	kind: 'docker';
	trusted: false;
	sandbox_policy_version: number;
	content_hash: string;
	participant_image_id: string;
	tournament_runtime_image_id: string;
	base_image: string;
	base_image_id: string;
	python_version: string;
	network: 'none';
	root_filesystem: 'read-only';
	tmpfs: { path: '/tmp', size_mb: number, options: string[] };
	user: string;
	capabilities: 'drop-all';
	no_new_privileges: true;
	default_seccomp: true;
	limits: { memory_mb: number, swap_mb: number, cpus: number, pids: number, nofile: number };
	environment_allowlist: readonly string[];
	host_bind_mounts: false;
	docker_socket: false;
	gpu: false;
}

export function dockerRuntimeAudit(
	contentHash: string, participantImageID: string, runtimeImageID: string, baseImageID: string,
	policy: DockerResourcePolicy
): PreparedDockerRuntimeAudit {
	return {
		kind: 'docker',
		trusted: false,
		sandbox_policy_version: SANDBOX_POLICY_VERSION,
		content_hash: contentHash,
		participant_image_id: participantImageID,
		tournament_runtime_image_id: runtimeImageID,
		base_image: PYTHON_BASE_IMAGE,
		base_image_id: baseImageID,
		python_version: PYTHON_RUNTIME_VERSION,
		network: 'none',
		root_filesystem: 'read-only',
		tmpfs: { path: '/tmp', size_mb: policy.tmpfsMB, options: ['rw', 'noexec', 'nosuid', 'nodev'] },
		user: CONTAINER_USER,
		capabilities: 'drop-all',
		no_new_privileges: true,
		default_seccomp: true,
		limits: {
			memory_mb: policy.memoryMB,
			swap_mb: policy.memoryMB,
			cpus: policy.cpus,
			pids: policy.pids,
			nofile: policy.nofile,
		},
		environment_allowlist: PROCESS_ENVIRONMENT_ALLOWLIST,
		host_bind_mounts: false,
		docker_socket: false,
		gpu: false,
	};
}

export function containerCreateArgs(
	imageID: string, containerName: string, seed: string, policy: DockerResourcePolicy,
	labels: Record<string, string> = {}
) {
	const args = [
		'container', 'create', '--interactive',
		'--name', containerName,
		'--label', `${MANAGED_CONTAINER_LABEL}=true`,
		'--label', `${SANDBOX_VERSION_LABEL}=${SANDBOX_POLICY_VERSION}`,
		'--network', 'none',
		'--read-only',
		'--tmpfs', `/tmp:rw,noexec,nosuid,nodev,size=${policy.tmpfsMB}m,mode=1777`,
		'--cap-drop', 'ALL',
		'--security-opt', 'no-new-privileges=true',
		'--user', CONTAINER_USER,
		'--memory', `${policy.memoryMB}m`,
		'--memory-swap', `${policy.memoryMB}m`,
		'--cpus', String(policy.cpus),
		'--pids-limit', String(policy.pids),
		'--ulimit', `nofile=${policy.nofile}:${policy.nofile}`,
		'--init',
		'--log-driver', 'none',
	];
	for (const [name, value] of Object.entries(labels).sort(([a], [b]) => a.localeCompare(b))) {
		args.push('--label', `${name}=${value}`);
	}
	args.push(
		imageID,
		'/usr/bin/env', '-i',
		`BOT_SEED=${seed}`,
		'HOME=/tmp',
		'LANG=C.UTF-8',
		'PATH=/usr/local/bin:/usr/bin:/bin',
		'PYTHONDONTWRITEBYTECODE=1',
		'PYTHONPATH=/opt/participant-python',
		'PYTHONUNBUFFERED=1',
		'TMPDIR=/tmp',
		'/usr/local/bin/python', '/opt/tournament/worker.py', '/submission/main.py'
	);
	return args;
}
