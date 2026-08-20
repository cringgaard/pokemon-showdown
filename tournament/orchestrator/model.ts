import { createHash } from 'crypto';
import type { PRNGSeed } from '../../sim/prng';
import type { TournamentConfig } from './config';

export type TournamentStage = 'round_robin' | 'final';

export interface ScheduledGame {
	id: string;
	stage: TournamentStage;
	pairing_id: string;
	game_index: number;
	p1: string;
	p2: string;
	seed: PRNGSeed;
}

export interface CompletedTournamentGame extends ScheduledGame {
	winner_participant_id: string | null;
	tie: boolean;
	turns: number;
	artifact_directory: string;
	attempt: number;
}

export interface Standing {
	rank: number;
	participant_id: string;
	name: string;
	games_played: number;
	wins: number;
	losses: number;
	ties: number;
	points: number;
	win_percentage: number;
	head_to_head_points: number;
}

export function roundRobinSchedule(config: TournamentConfig): ScheduledGame[] {
	const ids = config.participants.map(participant => participant.id);
	const schedule: ScheduledGame[] = [];
	for (let left = 0; left < ids.length; left++) {
		for (let right = left + 1; right < ids.length; right++) {
			const pairingID = pairingIdentity(ids[left], ids[right]);
			for (let gameIndex = 0; gameIndex < config.round_robin.games_per_pairing; gameIndex++) {
				const sides = gameIndex % 2 ? [ids[right], ids[left]] : [ids[left], ids[right]];
				schedule.push({
					id: `round-robin/${pairingID}/game-${gameIndex + 1}`,
					stage: 'round_robin',
					pairing_id: pairingID,
					game_index: gameIndex,
					p1: sides[0],
					p2: sides[1],
					seed: deriveTournamentSeed(config.seed, 'round_robin', pairingID, gameIndex),
				});
			}
		}
	}
	return schedule;
}

export function finalGame(config: TournamentConfig, finalists: [string, string], gameIndex: number): ScheduledGame {
	const pairingID = pairingIdentity(finalists[0], finalists[1]);
	const sides = gameIndex % 2 ? [finalists[1], finalists[0]] : [finalists[0], finalists[1]];
	return {
		id: `final/${pairingID}/game-${gameIndex + 1}`,
		stage: 'final',
		pairing_id: pairingID,
		game_index: gameIndex,
		p1: sides[0],
		p2: sides[1],
		seed: deriveTournamentSeed(config.seed, 'final', pairingID, gameIndex),
	};
}

export function pairingIdentity(left: string, right: string) {
	return `${left.length}-${left}__${right.length}-${right}`;
}

export function deriveTournamentSeed(
	tournamentSeed: string, stage: TournamentStage, pairingID: string, gameIndex: number
): PRNGSeed {
	const digest = createHash('sha256')
		.update(`pokemon-showdown-tournament-v1\0${tournamentSeed}\0${stage}\0${pairingID}\0${gameIndex}`, 'utf8')
		.digest();
	return [0, 2, 4, 6].map(offset => digest.readUInt16BE(offset)).join(',') as PRNGSeed;
}

export function calculateStandings(config: TournamentConfig, completed: CompletedTournamentGame[]): Standing[] {
	const names = new Map(config.participants.map(participant => [participant.id, participant.name]));
	const rows = new Map(config.participants.map(participant => [participant.id, {
		rank: 0,
		participant_id: participant.id,
		name: participant.name,
		games_played: 0,
		wins: 0,
		losses: 0,
		ties: 0,
		points: 0,
		win_percentage: 0,
		head_to_head_points: 0,
	}]));
	const roundRobin = completed.filter(game => game.stage === 'round_robin');
	for (const game of roundRobin) {
		const p1 = rows.get(game.p1);
		const p2 = rows.get(game.p2);
		if (!p1 || !p2) throw new Error(`Completed game ${game.id} references an unknown participant.`);
		p1.games_played++;
		p2.games_played++;
		if (game.tie || !game.winner_participant_id) {
			p1.ties++;
			p2.ties++;
			p1.points += 0.5;
			p2.points += 0.5;
		} else {
			const winner = rows.get(game.winner_participant_id);
			const loser = game.winner_participant_id === game.p1 ? p2 : p1;
			if (!winner) throw new Error(`Completed game ${game.id} has an unknown winner.`);
			winner.wins++;
			winner.points++;
			loser.losses++;
		}
	}
	const byPoints = new Map<number, string[]>();
	for (const row of rows.values()) {
		const group = byPoints.get(row.points) || [];
		group.push(row.participant_id);
		byPoints.set(row.points, group);
	}
	for (const tiedIDs of byPoints.values()) {
		if (tiedIDs.length < 2) continue;
		const tied = new Set(tiedIDs);
		for (const game of roundRobin.filter(candidate => tied.has(candidate.p1) && tied.has(candidate.p2))) {
			if (game.tie || !game.winner_participant_id) {
				rows.get(game.p1)!.head_to_head_points += 0.5;
				rows.get(game.p2)!.head_to_head_points += 0.5;
			} else {
				rows.get(game.winner_participant_id)!.head_to_head_points++;
			}
		}
	}
	const sorted = [...rows.values()].sort((a, b) =>
		b.points - a.points ||
		b.head_to_head_points - a.head_to_head_points ||
		b.wins - a.wins ||
		a.participant_id.localeCompare(b.participant_id)
	);
	return sorted.map((row, index) => ({
		...row,
		name: names.get(row.participant_id) || row.name,
		rank: index + 1,
		win_percentage: row.games_played ? row.wins / row.games_played : 0,
	}));
}

export function seriesScore(finalists: [string, string], games: CompletedTournamentGame[]) {
	const score: Record<string, number> = { [finalists[0]]: 0, [finalists[1]]: 0 };
	let ties = 0;
	for (const game of games.filter(candidate => candidate.stage === 'final')) {
		if (game.tie || !game.winner_participant_id) ties++;
		else score[game.winner_participant_id]++;
	}
	return { score, ties };
}
