import * as fs from 'fs';
import * as path from 'path';

export interface ReplayArtifacts {
	directory: string;
	metadata: Record<string, unknown>;
	result: Record<string, unknown>;
	protocol: string;
}

export function loadReplayArtifacts(directory: string): ReplayArtifacts {
	const resolved = path.resolve(directory);
	if (!fs.existsSync(resolved)) throw new Error(`Match directory ${JSON.stringify(resolved)} does not exist.`);
	if (!fs.statSync(resolved).isDirectory()) throw new Error(`Match path ${JSON.stringify(resolved)} is not a directory.`);
	const metadata = readJSONObject(resolved, 'metadata.json');
	const result = readJSONObject(resolved, 'result.json');
	const protocolPath = path.join(resolved, 'battle.protocol.log');
	if (!fs.existsSync(protocolPath)) throw new Error(`Match artifact ${JSON.stringify(protocolPath)} is missing.`);
	const protocol = fs.readFileSync(protocolPath, 'utf8');
	if (!protocol.trim()) throw new Error(`Match artifact ${JSON.stringify(protocolPath)} is empty.`);
	return { directory: resolved, metadata, result, protocol };
}

function readJSONObject(directory: string, filename: string) {
	const filepath = path.join(directory, filename);
	if (!fs.existsSync(filepath)) throw new Error(`Match artifact ${JSON.stringify(filepath)} is missing.`);
	let value: unknown;
	try {
		value = JSON.parse(fs.readFileSync(filepath, 'utf8'));
	} catch (error) {
		throw new Error(`Match artifact ${JSON.stringify(filepath)} is not valid JSON: ${error instanceof Error ? error.message : error}`);
	}
	if (!value || typeof value !== 'object' || Array.isArray(value)) {
		throw new Error(`Match artifact ${JSON.stringify(filepath)} must contain a JSON object.`);
	}
	return value as Record<string, unknown>;
}
