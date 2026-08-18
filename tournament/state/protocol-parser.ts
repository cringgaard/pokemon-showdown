export interface ProtocolEvent {
	type: string;
	args: string[];
	kwArgs: Record<string, string | true>;
	raw: string;
}

export function parseProtocolLine(raw: string): ProtocolEvent | null {
	if (!raw.startsWith('|')) return null;
	const parts = raw.slice(1).split('|');
	const type = parts.shift() || 'message';
	const args: string[] = [];
	const kwArgs: Record<string, string | true> = {};
	for (const part of parts) {
		const match = /^\[([^\]]+)\](?: (.*))?$/.exec(part);
		if (match) {
			kwArgs[match[1]] = match[2] ?? true;
		} else {
			args.push(part);
		}
	}
	return { type, args, kwArgs, raw };
}

export function parsePokemonIdent(value: string) {
	const match = /^(p[1-4])([a-d])?: (.*)$/.exec(value);
	if (!match) return null;
	return { side: match[1] as SideID, slot: match[2] || null, name: match[3] };
}

export function speciesFromDetails(details: string) {
	return details.split(',')[0].trim();
}
