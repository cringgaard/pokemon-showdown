'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('../assert');
const { loadTournamentConfig } = require('../../dist/tournament/orchestrator/config');
const { calculateStandings } = require('../../dist/tournament/orchestrator/model');
const { TournamentOrchestrator } = require('../../dist/tournament/orchestrator/orchestrator');
const { TournamentPacingController } = require('../../dist/tournament/orchestrator/pacing');
const { TournamentPlaybackController } = require('../../dist/tournament/orchestrator/playback');
const { runTournamentPreflight } = require('../../dist/tournament/orchestrator/preflight');
const { TournamentStateStore } = require('../../dist/tournament/orchestrator/state-store');
const { TournamentEventStore } = require('../../dist/tournament/spectator/event-store');
const { loadReplayArtifacts } = require('../../dist/tournament/spectator/replay-loader');

const root = path.resolve(__dirname, '../..');

describe('Tournament four-participant end to end', function () {
	this.timeout(4 * 60_000);

	it('runs round robin through final, preserves normal artifacts, and reloads complete state', async () => {
		const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'showdown-tournament-e2e-'));
		try {
			const configPath = path.join(temporaryRoot, 'company-cup.json');
			fs.writeFileSync(configPath, JSON.stringify({
				title: 'Cafeteria Company Cup',
				subtitle: 'Automated acceptance tournament',
				format: 'gen9vgc2025regi',
				seed: 'e2e-2026',
				runtime: 'host',
				decision_timeout_ms: 1000,
				match_timeout_ms: 20_000,
				participants: [
					{ id: 'alpha', name: 'Alpha Analytics', submission: path.join(root, 'tournament/reference-bots/random') },
					{ id: 'beta', name: 'Beta Builders', submission: path.join(root, 'tournament/reference-bots/greedy-damage') },
					{ id: 'gamma', name: 'Gamma Group', submission: path.join(root, 'tournament/reference-bots/random') },
					{ id: 'delta', name: 'Delta Division', submission: path.join(root, 'tournament/reference-bots/greedy-damage') },
				],
				round_robin: { games_per_pairing: 1 },
				final: { qualifiers: 2, best_of: 3, max_tied_games: 2 },
			}));
			const config = loadTournamentConfig(configPath);
			const output = path.join(temporaryRoot, 'results');
			const preflight = await runTournamentPreflight({
				config, outputDirectory: output, spectatorPort: 39123,
				rendererCheck: async () => ({ url: 'official', dependencies: [], reachable: true, errors: [] }),
			});
			const events = new TournamentEventStore({
				schema_version: 1, kind: 'idle', title: config.config.title,
			}, path.join(output, 'event.log.jsonl'));
			const pacing = new TournamentPacingController(events, true);
			const orchestrator = new TournamentOrchestrator({
				config, outputDirectory: output, participants: preflight.prepared, eventStore: events, pacing,
				playback: new TournamentPlaybackController({ autoComplete: true }),
			});
			const result = await orchestrator.run();
			const state = orchestrator.stateStore.state;
			assert.equal(state.phase, 'complete');
			assert.equal(result.champion, state.champion);
			assert.equal(state.completed_games.filter(game => game.stage === 'round_robin').length, 6);
			assert(state.completed_games.filter(game => game.stage === 'final').length >= 2);
			const standings = calculateStandings(config.config, state.completed_games);
			assert.deepEqual(state.finalists, standings.slice(0, 2).map(row => row.participant_id));
			for (const game of state.completed_games) {
				const replay = loadReplayArtifacts(game.artifact_directory);
				assert(replay.protocol.includes('|turn|1'));
				for (const side of ['p1', 'p2']) {
					const snapshot = fs.readFileSync(path.join(
						game.artifact_directory, 'bot-state-snapshots', `${side}.jsonl`
					), 'utf8');
					assert(!snapshot.includes('Cafeteria Company Cup'));
					assert(!snapshot.includes('stage_label'));
				}
			}
			const reloaded = new TournamentStateStore(output, config);
			assert.equal(reloaded.state.champion, result.champion);
			assert.equal(reloaded.state.completed_games.length, state.completed_games.length);
			assert.equal(events.presentation.kind, 'champion');
			assert.deepEqual(
				[events.presentation.p1.name, events.presentation.p2.name].sort(),
				state.finalists.map(id => config.config.participants.find(participant => participant.id === id).name).sort()
			);
		} finally {
			fs.rmSync(temporaryRoot, { recursive: true, force: true });
		}
	});
});
