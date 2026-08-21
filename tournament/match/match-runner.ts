import { execFileSync } from 'child_process';
import * as path from 'path';
import type { ObjectReadWriteStream } from '../../lib/streams';
import { BattleStream, getPlayerStreams } from '../../sim/battle-stream';
import { Dex } from '../../sim/dex';
import type { PRNGSeed } from '../../sim/prng';
import type { ChoiceRequest } from '../../sim/side';
import { Teams } from '../../sim/teams';
import { TeamValidator } from '../../sim/team-validator';
import type { BotState, RuntimeInfo } from '../api/types';
import { adaptAction } from '../actions/action-adapter';
import { BotController, type RuntimeLogEntry, type RuntimeStats } from '../bots/runtime';
import { buildBotState } from '../state/state-builder';
import { StateTracker } from '../state/state-tracker';

export const DEFAULT_FORMAT = 'gen9championsvgc2026regmb';

export interface ParticipantSpec {
	name: string;
	bot: string;
	team: string;
}

export interface MatchOptions {
	format?: string;
	seed: PRNGSeed;
	p1: ParticipantSpec;
	p2: ParticipantSpec;
	decisionTimeoutMs?: number;
	maxInvalidAttempts?: number;
	matchTimeoutMs?: number;
	python?: string;
}

export interface PlayerMatchResult {
	stats: RuntimeStats;
	fallback_log: RuntimeLogEntry[];
	unavailable_choice_revisions: number;
	stderr: string[];
	states: BotState[];
}

export interface MatchResult {
	format: string;
	seed: PRNGSeed;
	winner: string | null;
	tie: boolean;
	turns: number;
	showdown_version: string;
	showdown_commit: string | null;
	authoritative_log: string[];
	players: { p1: PlayerMatchResult, p2: PlayerMatchResult };
}

interface ValidatedParticipant extends ParticipantSpec {
	packedTeam: string;
}

export class MatchRunner {
	readonly options: Required<Pick<MatchOptions,
		'decisionTimeoutMs' | 'maxInvalidAttempts' | 'matchTimeoutMs'>> & MatchOptions;

	constructor(options: MatchOptions) {
		this.options = {
			decisionTimeoutMs: options.decisionTimeoutMs ?? 5000,
			maxInvalidAttempts: options.maxInvalidAttempts ?? 3,
			matchTimeoutMs: options.matchTimeoutMs ?? 60_000,
			...options,
		};
	}

	async run(): Promise<MatchResult> {
		Dex.includeData();
		const format = this.options.format || DEFAULT_FORMAT;
		const p1 = validateParticipant(this.options.p1, format);
		const p2 = validateParticipant(this.options.p2, format);
		const battleStream = new BattleStream({ noCatch: true });
		const streams = getPlayerStreams(battleStream);
		const p1Runtime = new MatchPlayerRuntime('p1', streams.p1, p1, format, this.options);
		const p2Runtime = new MatchPlayerRuntime('p2', streams.p2, p2, format, this.options);
		const authoritativeLog: string[] = [];
		let winner: string | null = null;
		let tie = false;
		let turns = 0;

		const observe = (async () => {
			for await (const chunk of streams.omniscient) {
				authoritativeLog.push(chunk);
				for (const line of chunk.split('\n')) {
					if (line.startsWith('|win|')) winner = line.slice(5);
					if (line === '|tie') tie = true;
					if (line.startsWith('|turn|')) turns = Number(line.slice(6)) || turns;
				}
			}
		})();
		const players = Promise.all([p1Runtime.run(), p2Runtime.run(), observe]);
		let matchTimer: NodeJS.Timeout | null = null;
		try {
			const openTeamSheets = shouldAcceptOpenTeamSheets(format) ? '\n>show-openteamsheets' : '';
			await streams.omniscient.write(`>start ${JSON.stringify({ formatid: format, seed: this.options.seed })}\n` +
				`>player p1 ${JSON.stringify({ name: p1.name, team: p1.packedTeam })}\n` +
				`>player p2 ${JSON.stringify({ name: p2.name, team: p2.packedTeam })}${openTeamSheets}`);
			await Promise.race([
				players,
				new Promise<never>((resolve, reject) => {
					matchTimer = setTimeout(() => reject(new Error(
						`Match exceeded the ${this.options.matchTimeoutMs} ms safety timeout`
					)), this.options.matchTimeoutMs);
				}),
			]);
		} finally {
			if (matchTimer) clearTimeout(matchTimer);
			await Promise.all([p1Runtime.stop(), p2Runtime.stop()]);
			if (!battleStream.atEOF) await streams.omniscient.writeEnd();
		}

		return {
			format,
			seed: this.options.seed,
			winner,
			tie,
			turns,
			showdown_version: require(path.resolve(__dirname, '../../../package.json')).version,
			showdown_commit: currentCommit(),
			authoritative_log: authoritativeLog,
			players: { p1: p1Runtime.result(), p2: p2Runtime.result() },
		};
	}
}

class MatchPlayerRuntime {
	readonly tracker: StateTracker;
	readonly states: BotState[] = [];
	unavailableChoiceRevisions = 0;
	private readonly sideID: 'p1' | 'p2';
	private readonly stream: ObjectReadWriteStream<string>;
	private readonly format: string;
	private readonly controller: BotController;
	private decisionID = 0;
	private revision = 0;
	private deadlineAt = 0;
	private unavailable = false;
	private stopped = false;
	private readonly decisionTimeoutMs: number;

	constructor(
		sideID: 'p1' | 'p2',
		stream: ObjectReadWriteStream<string>,
		participant: ValidatedParticipant,
		format: string,
		options: MatchRunner['options']
	) {
		this.sideID = sideID;
		this.stream = stream;
		this.format = format;
		this.tracker = new StateTracker(sideID, format);
		this.decisionTimeoutMs = options.decisionTimeoutMs;
		this.controller = new BotController(participant.bot, {
			python: options.python,
			seed: `${options.seed}:${sideID}`,
			fallbackKey: `${options.seed}:${sideID}`,
			decisionTimeoutMs: options.decisionTimeoutMs,
			maxInvalidAttempts: options.maxInvalidAttempts,
		});
	}

	async run() {
		for await (const chunk of this.stream) {
			this.tracker.consume(chunk);
			for (const line of chunk.split('\n')) {
				if (line.startsWith('|error|')) {
					const message = line.slice('|error|'.length);
					if (message.startsWith('[Unavailable choice]')) {
						this.unavailable = true;
						continue;
					}
					throw new Error(`${this.sideID} received a Showdown choice error: ${message}`);
				}
				if (!line.startsWith('|request|')) continue;
				const request = JSON.parse(line.slice('|request|'.length)) as ChoiceRequest;
				if (request.wait) continue;
				await this.answer(request);
			}
		}
	}

	async stop() {
		if (this.stopped) return;
		this.stopped = true;
		await this.controller.stop();
	}

	result(): PlayerMatchResult {
		return {
			stats: { ...this.controller.stats },
			fallback_log: [...this.controller.logs],
			unavailable_choice_revisions: this.unavailableChoiceRevisions,
			stderr: this.controller.stderr(),
			states: this.states,
		};
	}

	private async answer(request: ChoiceRequest) {
		let newDecision = true;
		if (this.unavailable) {
			this.revision++;
			this.unavailableChoiceRevisions++;
			this.unavailable = false;
			newDecision = false;
		} else {
			this.decisionID++;
			this.revision = 0;
			this.deadlineAt = Date.now() + this.decisionTimeoutMs;
		}
		const teamIDs = this.tracker.teamIDsForRequest(request);
		const response = await this.controller.decide({
			decisionID: this.decisionID,
			revision: this.revision,
			deadlineAt: this.deadlineAt,
			newDecision,
			buildState: (runtime: RuntimeInfo) => {
				const state = buildBotState(this.tracker, request, { format: this.format, runtime });
				this.states.push(state);
				return state;
			},
		});
		await this.stream.write(adaptAction(response, request, teamIDs));
	}
}

function shouldAcceptOpenTeamSheets(format: string) {
	const rules = Dex.formats.getRuleTable(Dex.formats.get(format));
	return rules.has('openteamsheets') && !rules.has('forceopenteamsheets');
}

function validateParticipant(participant: ParticipantSpec, format: string): ValidatedParticipant {
	const team = Teams.import(participant.team);
	if (!team) throw new Error(`${participant.name}'s team could not be parsed`);
	const problems = TeamValidator.get(format).validateTeam(team);
	if (problems?.length) throw new Error(`${participant.name}'s team is invalid:\n${problems.join('\n')}`);
	return { ...participant, packedTeam: Teams.pack(team) };
}

function currentCommit() {
	try {
		return execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8', timeout: 1000 }).trim();
	} catch {
		return null;
	}
}
