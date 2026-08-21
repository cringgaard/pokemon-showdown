'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('../assert');
const { loadTournamentConfig } = require('../../dist/tournament/orchestrator/config');
const { TournamentOrchestrator } = require('../../dist/tournament/orchestrator/orchestrator');
const { TournamentPacingController } = require('../../dist/tournament/orchestrator/pacing');
const { TournamentPlaybackController } = require('../../dist/tournament/orchestrator/playback');
const { roundRobinSchedule } = require('../../dist/tournament/orchestrator/model');
const { TournamentStateStore } = require('../../dist/tournament/orchestrator/state-store');
const {
	prepareMatchArtifactDirectory, writeMatchArtifacts,
} = require('../../dist/tournament/match/artifacts');
const { TournamentEventStore } = require('../../dist/tournament/spectator/event-store');
const { loadReplayArtifacts } = require('../../dist/tournament/spectator/replay-loader');

describe('TournamentOrchestrator durable deterministic execution', function () {
	this.timeout(30_000);
	let temporaryRoot;

	beforeEach(() => {
		temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'showdown-orchestrator-'));
	});

	afterEach(() => fs.rmSync(temporaryRoot, { recursive: true, force: true }));

	it('ends a best-of-five final early after three wins', async () => {
		const loaded = makeConfig(temporaryRoot, { bestOf: 5 });
		const output = path.join(temporaryRoot, 'results');
		const calls = [];
		const tournament = harness(loaded, output, fakeExecutor(calls, options => (
			options.outputDirectory.includes(`${path.sep}final${path.sep}`) ? 'alpha' : options.p1.id
		)));
		const result = await tournament.orchestrator.run();
		assert.equal(result.champion, 'alpha');
		assert.equal(calls.filter(call => call.outputDirectory.includes(`${path.sep}final${path.sep}`)).length, 3);
		assert.equal(tournament.state().completed_games.length, 4);
		assert.equal(tournament.events.presentation.kind, 'champion');
	});

	it('terminates repeated final ties at the configured safety limit', async () => {
		const loaded = makeConfig(temporaryRoot, { bestOf: 3, maxTiedGames: 2 });
		const output = path.join(temporaryRoot, 'tie-results');
		const calls = [];
		const tournament = harness(loaded, output, fakeExecutor(calls, options => (
			options.outputDirectory.includes(`${path.sep}final${path.sep}`) ? null : options.p1.id
		)));
		const result = await tournament.orchestrator.run();
		assert.equal(result.champion, 'alpha');
		assert.equal(tournament.state().champion_reason, 'tie_safety_limit');
		assert.equal(tournament.state().completed_games.filter(game => game.stage === 'final').length, 2);
	});

	it('adopts a completed interrupted attempt and never reruns it on resume', async () => {
		const loaded = makeConfig(temporaryRoot, { bestOf: 3 });
		const output = path.join(temporaryRoot, 'resume-results');
		let interruptedSeed;
		const first = harness(loaded, output, async options => {
			interruptedSeed = options.seed;
			await fakeMatch(options, options.p1.id);
			throw new Error('simulated crash after ordinary artifacts completed');
		});
		await assert.rejects(first.orchestrator.run(), /simulated crash/);
		const pending = first.state().in_progress;
		assert(pending);
		assert(loadReplayArtifacts(pending.artifact_directory).protocol.includes('|turn|1'));

		const resumedCalls = [];
		const resumed = harness(loaded, output, fakeExecutor(resumedCalls, options => options.p1.id));
		const result = await resumed.orchestrator.run();
		assert(result.champion);
		assert(!resumedCalls.some(call => call.seed === interruptedSeed));
		assert.equal(resumed.state().completed_games.filter(game => game.seed === interruptedSeed).length, 1);
		assert.equal(resumed.state().in_progress, null);
	});

	it('rejects config/state mismatch and validates every completed replay artifact', async () => {
		const loaded = makeConfig(temporaryRoot, { title: 'Original Cup' });
		const output = path.join(temporaryRoot, 'mismatch-results');
		const tournament = harness(loaded, output, fakeExecutor([], options => options.p1.id));
		await tournament.orchestrator.run();
		const changed = makeConfig(temporaryRoot, { title: 'Changed Cup', filename: 'changed.json' });
		assert.throws(() => new TournamentStateStore(output, changed), /config does not match/);
		for (const game of tournament.state().completed_games) {
			const replay = loadReplayArtifacts(game.artifact_directory);
			assert(replay.protocol.includes('|turn|1'));
			assert.equal(replay.metadata.seed, game.seed);
		}
		assert(!fs.readdirSync(output).some(filename => filename.includes('.tmp-')));
	});

	it('reloads a complete tournament without invoking MatchRunner again', async () => {
		const loaded = makeConfig(temporaryRoot, {});
		const output = path.join(temporaryRoot, 'complete-results');
		const first = harness(loaded, output, fakeExecutor([], options => options.p1.id));
		const completed = await first.orchestrator.run();
		let reruns = 0;
		const reloaded = harness(loaded, output, async () => { reruns++; throw new Error('must not run'); });
		const result = await reloaded.orchestrator.run();
		assert.equal(result.champion, completed.champion);
		assert.equal(reruns, 0);
	});

	it('persists a fast simulator result but keeps presentation live until visual completion', async () => {
		const loaded = makeConfig(temporaryRoot, {});
		const playback = new TournamentPlaybackController({ timeoutMs: 5000 });
		const tournament = harness(
			loaded, path.join(temporaryRoot, 'playback-results'),
			fakeExecutor([], options => options.p1.id), playback
		);
		const game = roundRobinSchedule(loaded.config)[0];
		const presentation = tournament.orchestrator.presentAndRun(game, 1, null);
		await waitUntil(() => tournament.state().completed_games.length === 1);
		assert.equal(tournament.events.presentation.kind, 'live');
		assert(!tournament.events.events.some(event => event.presentation?.kind === 'result'));
		const generation = tournament.events.presentation.protocol_generation;
		assert.deepEqual(playback.acknowledge(generation), { accepted: true, duplicate: false });
		assert.deepEqual(playback.acknowledge(generation), { accepted: false, duplicate: true });
		await presentation;
		assert.equal(tournament.events.presentation.kind, 'result');
	});

	it('releases pending playback after the disconnected-spectator timeout', async () => {
		const loaded = makeConfig(temporaryRoot, {});
		const playback = new TournamentPlaybackController({ timeoutMs: 20 });
		const tournament = harness(
			loaded, path.join(temporaryRoot, 'timeout-results'),
			fakeExecutor([], options => options.p1.id), playback
		);
		const game = roundRobinSchedule(loaded.config)[0];
		await tournament.orchestrator.presentAndRun(game, 1, null);
		assert.equal(tournament.events.presentation.kind, 'result');
		assert.equal(playback.status().last_completion_reason, 'timeout');
	});

	it('shows detailed sheets once per series and Team Preview before every game', async () => {
		const loaded = makeConfig(temporaryRoot, { bestOf: 3 });
		const tournament = harness(
			loaded, path.join(temporaryRoot, 'presentation-results'),
			fakeExecutor([], options => options.p1.id)
		);
		await tournament.orchestrator.run();
		const presentations = tournament.events.events.filter(event => event.presentation).map(event => event.presentation);
		const games = tournament.state().completed_games;
		assert.equal(presentations.filter(state => state.kind === 'team_preview').length, games.length);
		assert.equal(presentations.filter(state => state.kind === 'selection_locked').length, games.length);
		assert.equal(presentations.filter(state => state.kind === 'team_sheet').length, 4);
		for (const game of games) {
			const kinds = presentations.filter(state => state.game_id === game.id).map(state => state.kind);
			assert(kinds.indexOf('team_preview') < kinds.indexOf('selection_locked'));
			assert(kinds.indexOf('selection_locked') < kinds.indexOf('live'));
		}
		assert(!JSON.stringify(presentations).includes('team_0'));
	});
});

function makeConfig(root, options) {
	const filename = path.join(root, options.filename || 'tournament.json');
	fs.writeFileSync(filename, JSON.stringify({
		title: options.title || 'Company Cup',
		subtitle: 'Test Event',
		format: 'gen9vgc2025regi',
		seed: '2026',
		runtime: 'host',
		decision_timeout_ms: 1000,
		match_timeout_ms: 5000,
		participants: [
			{ id: 'alpha', name: 'Alpha', submission: 'alpha' },
			{ id: 'beta', name: 'Beta', submission: 'beta' },
		],
		round_robin: { games_per_pairing: 1 },
		final: { qualifiers: 2, best_of: options.bestOf || 3, max_tied_games: options.maxTiedGames || 3 },
	}));
	return loadTournamentConfig(filename);
}

function harness(config, output, executor, playback = new TournamentPlaybackController({ autoComplete: true })) {
	const events = new TournamentEventStore({ schema_version: 1, kind: 'idle', title: config.config.title });
	const pacing = new TournamentPacingController(events, true);
	const participants = new Map(config.config.participants.map(participant => [participant.id, {
		submission: {
			id: participant.id, name: participant.name, directory: participant.submission,
			mainPath: path.join(participant.submission, 'main.py'), teamText: '', packedTeam: '', requirementsPath: null,
		},
		workerFactory: { audit: { kind: 'host', trusted: true }, create() { throw new Error('unused'); } },
	}]));
	const orchestrator = new TournamentOrchestrator({
		config, outputDirectory: output, participants, eventStore: events, pacing, playback,
		publicTeams: testTeams(config), matchExecutor: executor,
	});
	return { orchestrator, events, state: () => orchestrator.stateStore.state };
}

function testTeams(config) {
	const pokemon = Array.from({ length: 6 }, (_, index) => ({
		name: `Pokemon ${index}`, species: 'Incineroar', sprite: 'incineroar', item: 'Sitrus Berry',
		ability: 'Intimidate', moves: ['Fake Out', 'Flare Blitz', 'Knock Off', 'Protect'],
	}));
	return new Map(config.config.participants.map(participant => [participant.id, {
		participant: { id: participant.id, name: participant.name }, pokemon,
	}]));
}

async function waitUntil(predicate) {
	for (let attempt = 0; attempt < 100; attempt++) {
		if (predicate()) return;
		await new Promise(resolve => { setTimeout(resolve, 5); });
	}
	throw new Error('Timed out waiting for tournament state.');
}

function fakeExecutor(calls, outcome) {
	return async options => {
		calls.push(options);
		return fakeMatch(options, outcome(options));
	};
}

async function fakeMatch(options, winnerID) {
	prepareMatchArtifactDirectory(options.outputDirectory);
	const winnerSide = winnerID === options.p1.id ? 'p1' : winnerID === options.p2.id ? 'p2' : null;
	const winner = winnerSide ? options[winnerSide].name : null;
	const player = {
		stats: { decisions: 1, timeouts: 0, invalid_responses: 0, fallbacks: 0, exceptions: 0 },
		fallback_log: [], unavailable_choice_revisions: 0, stderr: [], states: [],
	};
	const result = {
		format: options.format,
		seed: options.seed,
		winner,
		winner_side: winnerSide,
		winner_participant_id: winnerID,
		tie: !winnerID,
		turns: 1,
		showdown_version: 'test',
		showdown_commit: null,
		authoritative_log: ['|start', '|turn|1', winner ? `|win|${winner}` : '|tie'],
		players: { p1: player, p2: player },
	};
	writeMatchArtifacts(options.outputDirectory, result, { p1: options.p1, p2: options.p2 }, options);
	for (const sink of options.spectatorSinks || []) {
		for (const chunk of result.authoritative_log) sink.publish(chunk);
	}
	return result;
}
