import * as fs from 'fs';
import * as path from 'path';
import { MatchRunner } from './match/match-runner';

async function main() {
	const root = path.resolve(__dirname, '..');
	const sourceRoot = path.basename(root) === 'dist' ? path.dirname(root) : root;
	const team = fs.readFileSync(path.join(sourceRoot, 'tournament/fixtures/teams/vgc-reg-i.txt'), 'utf8');
	const randomBot = path.join(sourceRoot, 'tournament/reference-bots/random/main.py');
	const result = await new MatchRunner({
		seed: '1,2,3,4',
		p1: { name: 'Random Bot 1', bot: randomBot, team },
		p2: { name: 'Random Bot 2', bot: randomBot, team },
	}).run();
	process.stdout.write(`${JSON.stringify({
		format: result.format,
		seed: result.seed,
		winner: result.winner,
		tie: result.tie,
		turns: result.turns,
		showdown_version: result.showdown_version,
		showdown_commit: result.showdown_commit,
		players: {
			p1: result.players.p1.stats,
			p2: result.players.p2.stats,
		},
	}, null, 2)}\n`);
}

if (require.main === module) {
	void main().catch(error => {
		process.stderr.write(`${error.stack || error}\n`);
		process.exitCode = 1;
	});
}
