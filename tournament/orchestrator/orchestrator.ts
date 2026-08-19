import * as fs from 'fs';
import { MatchRunner, type MatchOptions, type MatchResult, type ParticipantSpec } from '../match/match-runner';
import type { BotWorkerFactory } from '../bots/worker-interface';
import type { LoadedSubmission } from '../submissions/submission-loader';
import { loadReplayArtifacts } from '../spectator/replay-loader';
import {
	TOURNAMENT_EVENT_SCHEMA_VERSION, type PresentationParticipant, type TournamentEventStore,
	type TournamentPresentationState,
} from '../spectator/event-store';
import type { LoadedTournamentConfig } from './config';
import {
	calculateStandings, type CompletedTournamentGame, finalGame, roundRobinSchedule, seriesScore,
	type ScheduledGame, type Standing,
} from './model';
import type { TournamentPacingController } from './pacing';
import { TournamentStateStore } from './state-store';

export interface PreparedTournamentParticipant {
	submission: LoadedSubmission;
	workerFactory: BotWorkerFactory;
}

export interface TournamentOrchestratorOptions {
	config: LoadedTournamentConfig;
	outputDirectory: string;
	participants: Map<string, PreparedTournamentParticipant>;
	eventStore: TournamentEventStore;
	pacing: TournamentPacingController;
	matchExecutor?: (options: MatchOptions) => Promise<MatchResult>;
}

export class TournamentOrchestrator {
	readonly config: LoadedTournamentConfig;
	readonly stateStore: TournamentStateStore;
	readonly participants: Map<string, PreparedTournamentParticipant>;
	readonly eventStore: TournamentEventStore;
	readonly pacing: TournamentPacingController;
	private readonly executeMatch: (options: MatchOptions) => Promise<MatchResult>;

	constructor(options: TournamentOrchestratorOptions) {
		this.config = options.config;
		this.stateStore = new TournamentStateStore(options.outputDirectory, options.config);
		this.participants = options.participants;
		this.eventStore = options.eventStore;
		this.pacing = options.pacing;
		this.executeMatch = options.matchExecutor || (matchOptions => new MatchRunner(matchOptions).run());
		for (const participant of this.config.config.participants) {
			if (!this.participants.has(participant.id)) throw new Error(`Participant ${participant.id} was not prepared.`);
		}
	}

	async run() {
		const recovered = this.recoverCompletedAttempt();
		if (this.stateStore.state.phase === 'complete') return this.publishChampion();
		const roundRobin = roundRobinSchedule(this.config.config);
		if (recovered) {
			const finalBefore = recovered.stage === 'final' ?
				this.stateStore.state.completed_games.filter(game => game.stage === 'final' && game.id !== recovered.id) : [];
			const previousScore = recovered.stage === 'final' && this.stateStore.state.finalists ?
				seriesScore(this.stateStore.state.finalists, finalBefore).score : null;
			this.eventStore.publishPresentation(this.resultState(recovered, recovered.game_index + 1, previousScore));
		}
		if (!this.stateStore.state.completed_games.length) {
			const initialStandings = this.standingsState(roundRobin[0] || null);
			const idle = this.idleState(roundRobin[0] || null);
			this.eventStore.publishPresentation(idle);
			await this.pacing.wait(idle, initialStandings);
		} else if (!this.pacing.autoAdvance && this.eventStore.presentation.kind !== 'live') {
			const next = roundRobin.find(game => !this.stateStore.completedIDs().has(game.id)) || null;
			await this.pacing.wait(this.eventStore.presentation, this.standingsState(next));
		}

		for (let index = 0; index < roundRobin.length; index++) {
			const game = roundRobin[index];
			if (this.stateStore.completedIDs().has(game.id)) continue;
			await this.presentAndRun(game, index + 1, null);
			const next = roundRobin.slice(index + 1).find(candidate => !this.stateStore.completedIDs().has(candidate.id)) || null;
			const standings = this.standingsState(next);
			this.eventStore.publishPresentation(standings);
			await this.pacing.wait(standings);
		}

		if (!this.stateStore.state.finalists) {
			const standings = calculateStandings(this.config.config, this.stateStore.state.completed_games);
			this.stateStore.state.finalists = [standings[0].participant_id, standings[1].participant_id];
			this.stateStore.state.phase = 'final';
			this.stateStore.save();
		}
		await this.runFinal(this.stateStore.state.finalists);
		return this.publishChampion();
	}

	private async runFinal(finalists: [string, string]) {
		const majority = Math.floor(this.config.config.final.best_of / 2) + 1;
		while (!this.stateStore.state.champion) {
			const finalGames = this.stateStore.state.completed_games.filter(game => game.stage === 'final');
			const { score, ties } = seriesScore(finalists, finalGames);
			const winner = finalists.find(id => score[id] >= majority);
			if (winner) {
				this.stateStore.state.champion = winner;
				this.stateStore.state.champion_reason = 'series';
				break;
			}
			if (ties >= this.config.config.final.max_tied_games) {
				this.stateStore.state.champion = finalists[0];
				this.stateStore.state.champion_reason = 'tie_safety_limit';
				break;
			}
			const game = finalGame(this.config.config, finalists, finalGames.length);
			await this.presentAndRun(game, finalGames.length + 1, score);
			const nextScore = seriesScore(finalists, this.stateStore.state.completed_games).score;
			const between = this.finalBetweenState(game, nextScore);
			this.eventStore.publishPresentation(between);
			await this.pacing.wait(between, this.standingsState(game));
		}
		this.stateStore.state.phase = 'complete';
		this.stateStore.save();
	}

	private async presentAndRun(game: ScheduledGame, gameNumber: number, score: Record<string, number> | null) {
		const intro = this.matchState('intro', game, gameNumber, score);
		this.eventStore.publishPresentation(intro, true);
		await this.pacing.wait(intro, this.standingsState(game));
		const completed = await this.runGame(game, gameNumber, score);
		const result = this.resultState(completed, gameNumber, score);
		this.eventStore.publishPresentation(result);
		await this.pacing.wait(result, this.standingsState(null));
	}

	private async runGame(game: ScheduledGame, gameNumber: number, score: Record<string, number> | null) {
		const previous = this.stateStore.state.in_progress;
		const attempt = previous?.game.id === game.id ? previous.attempt + 1 : 1;
		const artifactDirectory = this.stateStore.matchAttemptDirectory(game, attempt);
		this.stateStore.state.in_progress = { game, attempt, artifact_directory: artifactDirectory };
		this.stateStore.save();
		const live = this.matchState('live', game, gameNumber, score);
		this.eventStore.publishPresentation(live);
		const result = await this.executeMatch({
			format: this.config.config.format,
			seed: game.seed,
			p1: this.participantSpec(game.p1),
			p2: this.participantSpec(game.p2),
			decisionTimeoutMs: this.config.config.decision_timeout_ms,
			maxInvalidAttempts: this.config.config.max_invalid_attempts,
			matchTimeoutMs: this.config.config.match_timeout_ms,
			outputDirectory: artifactDirectory,
			spectatorSinks: [this.eventStore],
		});
		if (!result.tie && result.winner_participant_id !== game.p1 && result.winner_participant_id !== game.p2) {
			throw new Error(`Match ${game.id} returned an unknown winner.`);
		}
		const completed: CompletedTournamentGame = {
			...game,
			winner_participant_id: result.winner_participant_id,
			tie: result.tie,
			turns: result.turns,
			artifact_directory: artifactDirectory,
			attempt,
		};
		this.stateStore.state.completed_games.push(completed);
		this.stateStore.state.in_progress = null;
		this.stateStore.save();
		return completed;
	}

	private recoverCompletedAttempt(): CompletedTournamentGame | null {
		const pending = this.stateStore.state.in_progress;
		if (!pending || !fs.existsSync(pending.artifact_directory)) return null;
		try {
			const replay = loadReplayArtifacts(pending.artifact_directory);
			if (replay.metadata.seed !== pending.game.seed) throw new Error('seed mismatch');
			const completed: CompletedTournamentGame = {
				...pending.game,
				winner_participant_id: stringOrNull(replay.result.winner_participant_id),
				tie: replay.result.tie === true,
				turns: Number(replay.result.turns) || 0,
				artifact_directory: pending.artifact_directory,
				attempt: pending.attempt,
			};
			this.stateStore.state.completed_games.push(completed);
			this.stateStore.state.in_progress = null;
			this.stateStore.save();
			return completed;
		} catch {
			return null;
		}
	}

	private participantSpec(id: string): ParticipantSpec {
		const prepared = this.participants.get(id)!;
		return {
			id,
			name: this.participant(id).name,
			bot: prepared.submission.mainPath,
			team: prepared.submission.teamText,
			workerFactory: prepared.workerFactory,
		};
	}

	private participant(id: string) {
		const participant = this.config.config.participants.find(candidate => candidate.id === id);
		if (!participant) throw new Error(`Unknown tournament participant ${id}.`);
		return participant;
	}

	private displayParticipant(id: string): PresentationParticipant {
		const participant = this.participant(id);
		return { id, name: participant.name };
	}

	private common(kind: TournamentPresentationState['kind']): TournamentPresentationState {
		return {
			schema_version: TOURNAMENT_EVENT_SCHEMA_VERSION,
			kind,
			title: this.config.config.title,
			subtitle: this.config.config.subtitle,
		};
	}

	private idleState(next: ScheduledGame | null): TournamentPresentationState {
		return {
			...this.common('idle'),
			message: 'Tournament ready',
			next_match: next ? this.nextMatch(next) : null,
		};
	}

	private matchState(
		kind: 'intro' | 'live', game: ScheduledGame, gameNumber: number, score: Record<string, number> | null
	): TournamentPresentationState {
		return {
			...this.common(kind),
			stage_label: game.stage === 'final' ?
				`Championship Final · Best of ${this.config.config.final.best_of}` : 'Round Robin',
			game_id: game.id,
			game_number: gameNumber,
			p1: this.displayParticipant(game.p1),
			p2: this.displayParticipant(game.p2),
			series_score: score || undefined,
		};
	}

	private resultState(
		game: CompletedTournamentGame, gameNumber: number, previousScore: Record<string, number> | null
	): TournamentPresentationState {
		const score = previousScore ? {
			...previousScore,
			...(game.winner_participant_id ? {
				[game.winner_participant_id]: previousScore[game.winner_participant_id] + 1,
			} : {}),
		} : undefined;
		return {
			...this.common('result'),
			stage_label: game.stage === 'final' ? 'Championship Final' : 'Round Robin',
			game_id: game.id,
			game_number: gameNumber,
			p1: this.displayParticipant(game.p1),
			p2: this.displayParticipant(game.p2),
			winner: game.winner_participant_id ? this.displayParticipant(game.winner_participant_id) : null,
			tie: game.tie,
			series_score: score,
		};
	}

	private standingsState(next: ScheduledGame | null): TournamentPresentationState {
		const standings = calculateStandings(this.config.config, this.stateStore.state.completed_games);
		return {
			...this.common('standings'),
			stage_label: this.stateStore.state.phase === 'final' ? 'Championship Final' : 'Round Robin Standings',
			standings: standings.map(publicStanding),
			next_match: next ? this.nextMatch(next) : null,
		};
	}

	private finalBetweenState(game: ScheduledGame, score: Record<string, number>): TournamentPresentationState {
		return {
			...this.common('standings'),
			stage_label: 'Championship Final',
			series_score: score,
			next_match: this.nextMatch(finalGame(
				this.config.config, this.stateStore.state.finalists!,
				this.stateStore.state.completed_games.filter(candidate => candidate.stage === 'final').length
			)),
			standings: calculateStandings(this.config.config, this.stateStore.state.completed_games).map(publicStanding),
			message: `${this.participant(game.p1).name} vs ${this.participant(game.p2).name}`,
		};
	}

	private nextMatch(game: ScheduledGame) {
		return {
			p1: this.displayParticipant(game.p1),
			p2: this.displayParticipant(game.p2),
			label: game.stage === 'final' ? 'Championship Final' : 'Round Robin',
		};
	}

	private publishChampion() {
		const championID = this.stateStore.state.champion;
		if (!championID) throw new Error('Tournament completed without a champion.');
		const finalists = this.stateStore.state.finalists!;
		const finalScore = seriesScore(finalists, this.stateStore.state.completed_games).score;
		const champion: TournamentPresentationState = {
			...this.common('champion'),
			stage_label: 'Tournament Champion',
			p1: this.displayParticipant(finalists[0]),
			p2: this.displayParticipant(finalists[1]),
			winner: this.displayParticipant(championID),
			series_score: finalScore,
			champion_reason: this.stateStore.state.champion_reason || undefined,
		};
		this.eventStore.publishPresentation(champion);
		this.eventStore.markComplete();
		return {
			champion: championID,
			champion_name: this.participant(championID).name,
			finalists,
			final_score: finalScore,
			completed_games: this.stateStore.state.completed_games.length,
			output: this.stateStore.outputDirectory,
		};
	}
}

function publicStanding(standing: Standing) {
	return {
		rank: standing.rank,
		participant_id: standing.participant_id,
		name: standing.name,
		games_played: standing.games_played,
		wins: standing.wins,
		losses: standing.losses,
		ties: standing.ties,
		points: standing.points,
		win_percentage: standing.win_percentage,
	};
}

function stringOrNull(value: unknown) {
	return typeof value === 'string' ? value : null;
}
