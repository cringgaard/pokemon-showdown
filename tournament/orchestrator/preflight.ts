import * as https from 'https';
import * as net from 'net';
import { HostPythonWorkerFactory } from '../bots/python-worker';
import { OFFICIAL_REPLAY_EMBED_URL } from '../spectator/server';
import { loadSubmission } from '../submissions/submission-loader';
import { DockerImagePreparer, type ImagePreparerOptions } from '../sandbox/image-preparer';
import type { LoadedTournamentConfig } from './config';
import type { PreparedTournamentParticipant } from './orchestrator';
import { TournamentStateStore } from './state-store';

export interface TournamentPreflightOptions {
	config: LoadedTournamentConfig;
	outputDirectory: string;
	spectatorPort: number;
	allowRendererUnreachable?: boolean;
	imagePreparerOptions?: ImagePreparerOptions;
	rendererCheck?: () => Promise<RendererPreflightResult>;
}

export interface RendererPreflightResult {
	url: string;
	dependencies: string[];
	reachable: boolean;
	errors: string[];
}

export interface TournamentPreflightResult {
	ready: boolean;
	config_hash: string;
	runtime: 'docker' | 'host';
	participants: { id: string, name: string, submission: string }[];
	renderer: RendererPreflightResult;
	warnings: string[];
	prepared: Map<string, PreparedTournamentParticipant>;
}

export async function runTournamentPreflight(options: TournamentPreflightOptions): Promise<TournamentPreflightResult> {
	const { config } = options;
	new TournamentStateStore(options.outputDirectory, config);
	await assertPortAvailable(options.spectatorPort);
	const loaded = config.config.participants.map(participant => ({
		participant,
		submission: loadSubmission(participant.submission, {
			format: config.config.format,
			name: participant.name,
		}),
	}));
	const renderer = await (options.rendererCheck || checkOfficialRenderer)();
	const warnings: string[] = [];
	if (!renderer.reachable) {
		const message = `Official Showdown renderer preflight failed: ${renderer.errors.join('; ')}`;
		if (!options.allowRendererUnreachable) {
			throw new Error(`${message}. Check internet access to play.pokemonshowdown.com or use ` +
				'--allow-renderer-unreachable only for a rehearsal without a working presentation.');
		}
		warnings.push(message);
	}
	const prepared = new Map<string, PreparedTournamentParticipant>();
	if (config.config.runtime === 'docker') {
		const preparer = new DockerImagePreparer(options.imagePreparerOptions);
		for (const entry of loaded) {
			const image = await preparer.prepare(entry.submission);
			prepared.set(entry.participant.id, { submission: entry.submission, workerFactory: image.workerFactory });
		}
	} else {
		warnings.push('Trusted host runtime selected; participant code is not isolated.');
		for (const entry of loaded) {
			prepared.set(entry.participant.id, {
				submission: entry.submission,
				workerFactory: new HostPythonWorkerFactory(),
			});
		}
	}
	return {
		ready: true,
		config_hash: config.hash,
		runtime: config.config.runtime,
		participants: config.config.participants.map(participant => ({
			id: participant.id, name: participant.name, submission: participant.submission,
		})),
		renderer,
		warnings,
		prepared,
	};
}

export async function checkOfficialRenderer(): Promise<RendererPreflightResult> {
	const errors: string[] = [];
	let source = '';
	try {
		source = await fetchText(OFFICIAL_REPLAY_EMBED_URL);
	} catch (error) {
		errors.push(`${OFFICIAL_REPLAY_EMBED_URL}: ${errorMessage(error)}`);
		return { url: OFFICIAL_REPLAY_EMBED_URL, dependencies: [], reachable: false, errors };
	}
	const dependencies = rendererDependencies(source);
	if (!dependencies.length) errors.push('Hosted embed did not declare its expected runtime dependencies');
	await Promise.all(dependencies.map(async url => {
		try {
			await probeURL(url);
		} catch (error) {
			errors.push(`${url}: ${errorMessage(error)}`);
		}
	}));
	return { url: OFFICIAL_REPLAY_EMBED_URL, dependencies, reachable: !errors.length, errors };
}

export function rendererDependencies(source: string) {
	return [...new Set([...source.matchAll(/['"](https:\/\/play\.pokemonshowdown\.com\/[^'"]+)['"]/g)]
		.map(match => match[1]))].sort();
}

export function assertPortAvailable(port: number, host = '127.0.0.1') {
	return new Promise<void>((resolve, reject) => {
		const server = net.createServer();
		server.once('error', error => reject(new Error(
			`Spectator port ${host}:${port} is unavailable: ${errorMessage(error)}`
		)));
		server.listen(port, host, () => server.close(error => error ? reject(error) : resolve()));
	});
}

function fetchText(url: string) {
	return requestURL(url, true);
}

async function probeURL(url: string) {
	await requestURL(url, false);
}

function requestURL(url: string, retainBody: boolean) {
	return new Promise<string>((resolve, reject) => {
		const outgoing = https.get(url, {
			headers: { 'User-Agent': 'pokemon-showdown-tournament-preflight/1' },
		}, response => {
			if (!response.statusCode || response.statusCode < 200 || response.statusCode >= 400) {
				response.resume();
				reject(new Error(`HTTP ${response.statusCode || 'unknown'}`));
				return;
			}
			if (!retainBody) {
				response.destroy();
				resolve('');
				return;
			}
			response.setEncoding('utf8');
			let body = '';
			response.on('data', chunk => {
				body += chunk;
				if (body.length > 256 * 1024) outgoing.destroy(new Error('response exceeded 256 KiB'));
			});
			response.on('end', () => resolve(body));
		});
		outgoing.setTimeout(5000, () => outgoing.destroy(new Error('request timed out after 5000 ms')));
		outgoing.once('error', reject);
	});
}

function errorMessage(error: unknown) {
	return error instanceof Error ? error.message : String(error);
}
