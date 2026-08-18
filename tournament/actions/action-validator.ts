import type { BotRequest, BotResponse } from '../api/types';

export function validateResponse(request: BotRequest, response: unknown): BotResponse | null {
	if (!response || typeof response !== 'object') return null;
	const serialized = canonicalJSON(response);
	return request.legal_actions.find(action => canonicalJSON(action) === serialized) || null;
}

function canonicalJSON(value: unknown): string {
	if (Array.isArray(value)) return `[${value.map(canonicalJSON).join(',')}]`;
	if (value && typeof value === 'object') {
		return `{${Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b))
			.map(([key, child]) => `${JSON.stringify(key)}:${canonicalJSON(child)}`).join(',')}}`;
	}
	return JSON.stringify(value);
}
