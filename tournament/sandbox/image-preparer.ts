import { createHash } from 'crypto';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import type { LoadedSubmission } from '../submissions/submission-loader';
import {
	CONTAINER_USER, DEFAULT_DOCKER_RESOURCE_POLICY, PYTHON_BASE_IMAGE, SANDBOX_POLICY_VERSION,
	type DockerResourcePolicy, dockerRuntimeAudit,
} from './policy';
import { assertDockerAvailable, inspectImageID, runDocker } from './docker-cli';
import { DockerPythonWorkerFactory } from './runtime';

export const DEFAULT_BUILD_TIMEOUT_MS = 5 * 60_000;
export const DEFAULT_MAX_SUBMISSION_BYTES = 1024 * 1024 * 1024;
export const DEFAULT_MAX_SUBMISSION_FILES = 10_000;
export const MAX_REQUIREMENTS_BYTES = 64 * 1024;
const IMAGE_NAMESPACE = 'pokemon-showdown-tournament';

export interface SubmissionLimits {
	maxBytes: number;
	maxFiles: number;
}

export interface ImagePreparerOptions {
	buildTimeoutMs?: number;
	resourcePolicy?: Partial<DockerResourcePolicy>;
	submissionLimits?: Partial<SubmissionLimits>;
}

export interface PreparedParticipantImage {
	contentHash: string;
	imageID: string;
	runtimeImageID: string;
	baseImageID: string;
	cached: boolean;
	workerFactory: DockerPythonWorkerFactory;
}

export class DockerImagePreparer {
	readonly buildTimeoutMs: number;
	readonly resourcePolicy: DockerResourcePolicy;
	readonly submissionLimits: SubmissionLimits;

	constructor(options: ImagePreparerOptions = {}) {
		this.buildTimeoutMs = options.buildTimeoutMs ?? DEFAULT_BUILD_TIMEOUT_MS;
		this.resourcePolicy = { ...DEFAULT_DOCKER_RESOURCE_POLICY, ...options.resourcePolicy };
		this.submissionLimits = {
			maxBytes: DEFAULT_MAX_SUBMISSION_BYTES,
			maxFiles: DEFAULT_MAX_SUBMISSION_FILES,
			...options.submissionLimits,
		};
		validatePolicy(this.resourcePolicy);
		validateSubmissionLimits(this.submissionLimits);
	}

	async assertAvailable() {
		await assertDockerAvailable();
	}

	async prepare(submission: LoadedSubmission): Promise<PreparedParticipantImage> {
		assertNoParticipantDockerfile(submission.directory);
		const files = submissionFiles(submission.directory, this.submissionLimits);
		if (submission.requirementsPath) validateRequirementsFile(submission.requirementsPath);
		await this.assertAvailable();
		const baseImage = await this.ensureBaseImage();
		const runtimeImage = await this.ensureTournamentRuntime(baseImage.imageID, baseImage.reference);
		const { imageID: baseImageID } = baseImage;
		const { imageID: runtimeImageID } = runtimeImage;
		const contentHash = await hashSubmissionFiles(files, runtimeImageID);
		const tag = `${IMAGE_NAMESPACE}/participant:${contentHash}`;
		let imageID = await inspectImageID(tag);
		const cached = !!imageID;
		if (!imageID) {
			const context = fs.mkdtempSync(path.join(os.tmpdir(), 'showdown-participant-build-'));
			try {
				copySubmission(files, path.join(context, 'submission'));
				fs.writeFileSync(
					path.join(context, 'Dockerfile'), participantDockerfile(runtimeImage.reference, !!submission.requirementsPath)
				);
				await runDocker(['image', 'build', '--tag', tag, context], {
					timeoutMs: this.buildTimeoutMs,
				});
			} finally {
				fs.rmSync(context, { recursive: true, force: true });
			}
			imageID = await inspectImageID(tag);
			if (!imageID) throw new Error(`Docker built ${tag} but its immutable image ID could not be inspected.`);
		}
		const audit = dockerRuntimeAudit(contentHash, imageID, runtimeImageID, baseImageID, this.resourcePolicy);
		return {
			contentHash, imageID, runtimeImageID, baseImageID, cached,
			workerFactory: new DockerPythonWorkerFactory(imageID, audit, this.resourcePolicy),
		};
	}

	private async ensureBaseImage() {
		let imageID = await inspectImageID(PYTHON_BASE_IMAGE);
		if (!imageID) {
			await runDocker(['image', 'pull', PYTHON_BASE_IMAGE], { timeoutMs: this.buildTimeoutMs });
			imageID = await inspectImageID(PYTHON_BASE_IMAGE);
		}
		if (!imageID) throw new Error(`Unable to resolve immutable image ID for ${PYTHON_BASE_IMAGE}.`);
		const reference = `${IMAGE_NAMESPACE}/python-base:${imageID.replace(/^sha256:/, '')}`;
		await runDocker(['image', 'tag', imageID, reference], { timeoutMs: 10_000, maxOutputBytes: 256 * 1024 });
		return { imageID, reference };
	}

	private async ensureTournamentRuntime(baseImageID: string, baseImageReference: string) {
		const worker = fs.readFileSync(findWorkerScript());
		const hash = createHash('sha256')
			.update(`sandbox-policy:${SANDBOX_POLICY_VERSION}\0base:${baseImageID}\0`)
			.update(worker)
			.digest('hex');
		const tag = `${IMAGE_NAMESPACE}/python-runtime:${hash}`;
		let imageID = await inspectImageID(tag);
		if (imageID) return { imageID, reference: tag };
		const context = fs.mkdtempSync(path.join(os.tmpdir(), 'showdown-runtime-build-'));
		try {
			fs.writeFileSync(path.join(context, 'Dockerfile'), runtimeDockerfile(baseImageReference));
			fs.copyFileSync(findWorkerScript(), path.join(context, 'worker.py'));
			await runDocker(['image', 'build', '--tag', tag, context], {
				timeoutMs: this.buildTimeoutMs,
			});
		} finally {
			fs.rmSync(context, { recursive: true, force: true });
		}
		imageID = await inspectImageID(tag);
		if (!imageID) throw new Error(`Docker built ${tag} but its immutable image ID could not be inspected.`);
		return { imageID, reference: tag };
	}
}

export async function hashSubmission(
	directory: string, runtimeImageID: string, limits: Partial<SubmissionLimits> = {}
) {
	const effectiveLimits = {
		maxBytes: DEFAULT_MAX_SUBMISSION_BYTES,
		maxFiles: DEFAULT_MAX_SUBMISSION_FILES,
		...limits,
	};
	validateSubmissionLimits(effectiveLimits);
	return hashSubmissionFiles(submissionFiles(directory, effectiveLimits), runtimeImageID);
}

async function hashSubmissionFiles(files: SubmissionFile[], runtimeImageID: string) {
	const hash = createHash('sha256');
	hash.update(`sandbox-policy:${SANDBOX_POLICY_VERSION}\0runtime:${runtimeImageID}\0`);
	for (const entry of files) {
		hash.update(`path:${entry.relativePath}\0mode:${entry.mode}\0size:${entry.size}\0`);
		let bytesRead = 0;
		for await (const chunk of fs.createReadStream(entry.fullPath)) {
			bytesRead += chunk.length;
			hash.update(chunk);
		}
		if (bytesRead !== entry.size) {
			throw new Error(`Submission file changed while hashing: ${JSON.stringify(entry.fullPath)}.`);
		}
		hash.update('\0');
	}
	return hash.digest('hex');
}

export function runtimeDockerfile(baseImageID: string) {
	return [
		`FROM ${baseImageID}`,
		'USER root',
		'RUN groupadd --gid 10001 tournament && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin tournament && mkdir -p /submission /opt/participant-python && chown -R 10001:10001 /submission /opt/participant-python',
		'COPY --chown=10001:10001 worker.py /opt/tournament/worker.py',
		'RUN chmod 0555 /opt/tournament/worker.py',
		`USER ${CONTAINER_USER}`,
		'WORKDIR /submission',
		'ENTRYPOINT []',
		'CMD []',
		'',
	].join('\n');
}

export function participantDockerfile(runtimeImageID: string, hasRequirements: boolean) {
	return [
		`FROM ${runtimeImageID}`,
		`USER ${CONTAINER_USER}`,
		'WORKDIR /opt/tournament',
		'COPY --chown=10001:10001 submission/ /submission/',
		...(hasRequirements ? [
			'RUN /usr/local/bin/python -I -m pip install --disable-pip-version-check --no-cache-dir --no-compile --only-binary=:all: --no-deps --target /opt/participant-python -r /submission/requirements.txt',
		] : []),
		'WORKDIR /submission',
		'ENTRYPOINT []',
		'CMD []',
		'',
	].join('\n');
}

interface SubmissionFile {
	fullPath: string;
	relativePath: string;
	mode: number;
	size: number;
}

function copySubmission(files: SubmissionFile[], destination: string) {
	fs.mkdirSync(destination, { recursive: true });
	for (const entry of files) {
		const current = fs.lstatSync(entry.fullPath);
		if (!current.isFile() || current.size !== entry.size || (current.mode & 0o777) !== entry.mode) {
			throw new Error(`Submission file changed while preparing the build context: ${JSON.stringify(entry.fullPath)}.`);
		}
		const target = path.join(destination, ...entry.relativePath.split('/'));
		fs.mkdirSync(path.dirname(target), { recursive: true });
		fs.copyFileSync(entry.fullPath, target);
	}
}

function submissionFiles(root: string, limits: SubmissionLimits) {
	const files: SubmissionFile[] = [];
	let totalBytes = 0;
	let fileCount = 0;
	const visit = (directory: string) => {
		for (const entry of fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
			const fullPath = path.join(directory, entry.name);
			if (entry.isSymbolicLink()) throw new Error(`Submission symlinks are not supported: ${JSON.stringify(fullPath)}.`);
			if (entry.isDirectory()) {
				visit(fullPath);
			} else if (entry.isFile()) {
				const stat = fs.statSync(fullPath);
				fileCount++;
				if (fileCount > limits.maxFiles) {
					throw new Error(`Submission exceeds the ${limits.maxFiles}-file limit.`);
				}
				totalBytes += stat.size;
				if (totalBytes > limits.maxBytes) {
					throw new Error(`Submission exceeds the ${limits.maxBytes}-byte total size limit.`);
				}
				files.push({
					fullPath,
					relativePath: path.relative(root, fullPath).split(path.sep).join('/'),
					mode: stat.mode & 0o777,
					size: stat.size,
				});
			} else {
				throw new Error(`Submission contains unsupported special file: ${JSON.stringify(fullPath)}.`);
			}
		}
	};
	visit(root);
	return files;
}

export function validateRequirementsFile(filename: string) {
	const stat = fs.statSync(filename);
	if (stat.size > MAX_REQUIREMENTS_BYTES) {
		throw new Error(`requirements.txt exceeds the ${MAX_REQUIREMENTS_BYTES}-byte limit.`);
	}
	const requirement = /^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?(?:\[[A-Za-z0-9._-]+(?:,[A-Za-z0-9._-]+)*\])?==[A-Za-z0-9](?:[A-Za-z0-9._+!-]*[A-Za-z0-9])?$/;
	for (const [index, rawLine] of fs.readFileSync(filename, 'utf8').split(/\r?\n/).entries()) {
		const line = rawLine.replace(/\s+#.*$/, '').trim();
		if (!line || line.startsWith('#')) continue;
		if (!requirement.test(line)) {
			throw new Error(
				`Unsupported requirements.txt entry on line ${index + 1}: ${JSON.stringify(rawLine)}. ` +
				'Only exact name[extras]==version pins are accepted; URLs, paths, editable installs, options, ' +
				'markers, constraints, and source/VCS requirements are not supported.'
			);
		}
	}
}

function assertNoParticipantDockerfile(directory: string) {
	for (const name of fs.readdirSync(directory)) {
		if (name.toLowerCase() === 'dockerfile') {
			throw new Error('Participant Dockerfiles are not accepted. The tournament generates and controls the build definition.');
		}
	}
}

function findWorkerScript() {
	const source = path.resolve(__dirname, '../../../tournament/bots/worker.py');
	if (fs.existsSync(source)) return source;
	return path.resolve(__dirname, '../bots/worker.py');
}

function validatePolicy(policy: DockerResourcePolicy) {
	for (const [name, value] of Object.entries(policy)) {
		if (!Number.isFinite(value) || value <= 0) throw new Error(`Docker resource policy ${name} must be positive.`);
	}
	if (!Number.isSafeInteger(policy.memoryMB) || !Number.isSafeInteger(policy.pids) ||
		!Number.isSafeInteger(policy.tmpfsMB) || !Number.isSafeInteger(policy.nofile)) {
		throw new Error('Docker memory, PIDs, tmpfs, and nofile limits must be integers.');
	}
}

function validateSubmissionLimits(limits: SubmissionLimits) {
	if (!Number.isSafeInteger(limits.maxBytes) || limits.maxBytes <= 0 ||
		!Number.isSafeInteger(limits.maxFiles) || limits.maxFiles <= 0) {
		throw new Error('Submission byte and file-count limits must be positive safe integers.');
	}
}
