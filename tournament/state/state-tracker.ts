import { Dex } from '../../sim/dex';
import { Teams } from '../../sim/teams';
import type { ChoiceRequest } from '../../sim/side';
import type {
	BattleEvent, HealthState, ObservedCondition, OpponentPokemonID, OwnPokemonID, Position,
} from '../api/types';
import { EMPTY_BOOSTS, type ObservedActivePokemon, type ObservedTeamPokemon } from './battle-state';
import { parsePokemonIdent, parseProtocolLine, speciesFromDetails, type ProtocolEvent } from './protocol-parser';

const OPPONENT_SLOT_TO_POSITION: Record<string, Position> = { a: 'right', b: 'left' };

export class StateTracker {
	readonly sideID: SideID;
	turn = 0;
	started = false;
	winner: string | null = null;
	tie = false;
	selfName = '';
	opponentName = '';
	weather: string | null = null;
	weatherStartedTurn: number | null = null;
	readonly fieldConditions: Record<string, ObservedCondition> = {};
	readonly selfSideConditions: Record<string, ObservedCondition> = {};
	readonly opponentSideConditions: Record<string, ObservedCondition> = {};
	readonly opponentActive: Partial<Record<Position, ObservedActivePokemon>> = {};
	readonly opponentTeam: ObservedTeamPokemon[] = [];
	readonly history: BattleEvent[] = [];

	private readonly ownIDByIdent = new Map<string, OwnPokemonID>();
	private readonly ownIDByName = new Map<string, OwnPokemonID>();
	private readonly ownMaxHP = new Map<OwnPokemonID, number>();
	private readonly ownObserved = new Map<string, { boosts: typeof EMPTY_BOOSTS, volatiles: Set<string> }>();
	private readonly opponentCurrentItems = new Map<OpponentPokemonID, string | null>();
	private opponentHasIllusion = false;

	constructor(sideID: SideID) {
		this.sideID = sideID;
	}

	consume(chunk: string) {
		for (const raw of chunk.split('\n')) {
			const event = parseProtocolLine(raw);
			if (!event || event.type === 'request') continue;
			this.history.push({ turn: this.turn, type: event.type, data: { args: event.args, kwArgs: event.kwArgs }, raw });
			this.apply(event);
		}
	}

	registerRequest(request: ChoiceRequest) {
		if (!this.selfName) this.selfName = request.side.name;
		if (request.teamPreview && !this.ownIDByIdent.size) {
			request.side.pokemon.forEach((pokemon, index) => {
				const id = ownPokemonID(index);
				this.ownIDByIdent.set(pokemon.ident, id);
				this.ownIDByName.set(parsePokemonIdent(pokemon.ident)?.name || pokemon.ident, id);
			});
		}
		request.side.pokemon.forEach((pokemon, index) => {
			const maxHP = Number(/^\d+\/(\d+)/.exec(pokemon.condition)?.[1]);
			if (maxHP > 0) this.ownMaxHP.set(this.ownIDForRequestPokemon(pokemon, index), maxHP);
		});
	}

	teamIDsForRequest(request: ChoiceRequest): OwnPokemonID[] {
		this.registerRequest(request);
		return request.side.pokemon.map((pokemon, index) => this.ownIDForRequestPokemon(pokemon, index));
	}

	ownMaxHPForID(id: OwnPokemonID) {
		return this.ownMaxHP.get(id);
	}

	ownIDForIdent(ident: string) {
		return this.ownIDByIdent.get(ident) || this.ownIDByName.get(parsePokemonIdent(ident)?.name || '') || null;
	}

	ownObservationForIdent(ident: string) {
		const name = parsePokemonIdent(ident)?.name || ident;
		return this.ownObserved.get(name) || null;
	}

	private ownIDForRequestPokemon(pokemon: ChoiceRequest['side']['pokemon'][number], index: number) {
		return this.ownIDByIdent.get(pokemon.ident) ||
			this.ownIDByName.get(parsePokemonIdent(pokemon.ident)?.name || '') || ownPokemonID(index);
	}

	private apply(event: ProtocolEvent) {
		switch (event.type) {
		case 'start': this.started = true; break;
		case 'turn': this.turn = Number(event.args[0]) || this.turn; break;
		case 'win': this.winner = event.args[0] || null; break;
		case 'tie': this.tie = true; break;
		case 'player': this.applyPlayer(event); break;
		case 'showteam': this.applyOpenTeamSheet(event); break;
		case 'switch':
		case 'drag': this.applySwitch(event); break;
		case 'replace': this.applyReplace(event); break;
		case 'swap': this.applySwap(event); break;
		case 'detailschange':
		case '-formechange': this.applyDetailsChange(event); break;
		case '-terastallize': this.applyTerastallize(event); break;
		case 'move': this.applyMove(event); break;
		case 'faint': this.applyFaint(event); break;
		case '-damage':
		case '-heal':
		case '-sethp': this.applyHealth(event); break;
		case '-status': this.applyStatus(event, false); break;
		case '-curestatus': this.applyStatus(event, true); break;
		case '-boost': this.applyBoost(event, 1); break;
		case '-unboost': this.applyBoost(event, -1); break;
		case '-setboost': this.applyBoost(event, 0); break;
		case '-invertboost': this.applyInvertBoost(event); break;
		case '-clearboost': this.applyClearBoost(event); break;
		case '-clearnegativeboost': this.applyDirectionalClear(event, -1); break;
		case '-clearpositiveboost': this.applyDirectionalClear(event, 1); break;
		case '-clearallboost': this.applyClearAllBoost(); break;
		case '-copyboost': this.applyCopyBoost(event); break;
		case '-swapboost': this.applySwapBoost(event); break;
		case '-weather': this.applyWeather(event); break;
		case '-fieldstart': this.setCondition(this.fieldConditions, effectID(event.args[0]), true); break;
		case '-fieldend': this.setCondition(this.fieldConditions, effectID(event.args[0]), false); break;
		case '-sidestart': this.applySideCondition(event, true); break;
		case '-sideend': this.applySideCondition(event, false); break;
		case '-swapsideconditions': this.swapSideConditions(); break;
		case '-start': this.applyVolatile(event, true); break;
		case '-end': this.applyVolatile(event, false); break;
		case '-item': this.applyReveal(event, 'item'); break;
		case '-enditem': this.applyReveal(event, 'item', true); break;
		case '-ability': this.applyReveal(event, 'ability'); break;
		case '-endability': this.applyReveal(event, 'ability', true); break;
		}
	}

	private applyPlayer(event: ProtocolEvent) {
		if (event.args[0] === this.sideID) this.selfName = event.args[1] || this.selfName;
		else if (event.args[0]?.startsWith('p')) this.opponentName = event.args[1] || this.opponentName;
	}

	private applyOpenTeamSheet(event: ProtocolEvent) {
		if (event.args[0] === this.sideID || !event.args[1]) return;
		const team = Teams.unpack(event.args.slice(1).join('|'));
		if (!team) return;
		this.opponentTeam.splice(0, this.opponentTeam.length, ...team.map((set, index) => ({
			id: opponentPokemonID(index),
			name: set.name || set.species,
			species: set.species,
			item: set.item ? Dex.toID(set.item) : null,
			ability: set.ability ? Dex.toID(set.ability) : null,
			teraType: set.teraType || null,
			moves: set.moves.map(id => ({ id: Dex.moves.get(id).id, name: Dex.moves.get(id).name })),
		})));
		this.opponentCurrentItems.clear();
		for (const pokemon of this.opponentTeam) this.opponentCurrentItems.set(pokemon.id, pokemon.item);
		this.opponentHasIllusion = this.opponentTeam.some(pokemon => pokemon.ability === 'illusion');
	}

	private applySwitch(event: ProtocolEvent) {
		const ident = parsePokemonIdent(event.args[0] || '');
		if (!ident?.slot || !OPPONENT_SLOT_TO_POSITION[ident.slot]) return;
		if (ident.side === this.sideID) {
			this.ownObserved.set(ident.name, { boosts: { ...EMPTY_BOOSTS }, volatiles: new Set() });
			return;
		}
		const position = OPPONENT_SLOT_TO_POSITION[ident.slot];
		const apparentSpecies = speciesFromDetails(event.args[1] || ident.name);
		const matched = this.opponentHasIllusion ? null : this.findOpponent(apparentSpecies, ident.name);
		this.opponentActive[position] = {
			position,
			ident: event.args[0],
			name: ident.name,
			apparentSpecies,
			teamID: matched?.id || null,
			health: parseHealth(event.args[2] || '100/100', false),
			status: statusFromCondition(event.args[2] || ''),
			fainted: (event.args[2] || '').endsWith(' fnt'),
			item: matched ? this.currentOpponentItem(matched) : null,
			ability: matched?.ability || null,
			terastallized: false,
			boosts: { ...EMPTY_BOOSTS },
			volatiles: new Set(),
		};
	}

	private applyReplace(event: ProtocolEvent) {
		const active = this.activeFor(event.args[0]);
		if (!active) return;
		active.apparentSpecies = speciesFromDetails(event.args[1] || active.apparentSpecies);
		const matched = this.findOpponent(active.apparentSpecies, active.name);
		active.teamID = matched?.id || null;
		active.item = matched ? this.currentOpponentItem(matched) : active.item;
		active.ability = matched?.ability || active.ability;
	}

	private applySwap(event: ProtocolEvent) {
		const ident = parsePokemonIdent(event.args[0] || '');
		if (!ident || ident.side === this.sideID || !ident.slot) return;
		const from = OPPONENT_SLOT_TO_POSITION[ident.slot];
		const to = event.args[1] === '0' ? 'right' : event.args[1] === '1' ? 'left' : null;
		if (!from || !to || from === to) return;
		const first = this.opponentActive[from];
		const second = this.opponentActive[to];
		if (first) first.position = to;
		if (second) second.position = from;
		this.opponentActive[from] = second;
		this.opponentActive[to] = first;
	}

	private applyDetailsChange(event: ProtocolEvent) {
		const active = this.activeFor(event.args[0]);
		if (!active) return;
		active.apparentSpecies = speciesFromDetails(event.args[1] || active.apparentSpecies);
		if (event.type === '-formechange' && effectID(event.args[1]) === 'terastallized') active.terastallized = true;
	}

	private applyTerastallize(event: ProtocolEvent) {
		const active = this.activeFor(event.args[0]);
		if (active) active.terastallized = true;
	}

	private applyMove(event: ProtocolEvent) {
		const active = this.activeFor(event.args[0]);
		if (!active?.teamID) return;
		const pokemon = this.opponentTeam.find(entry => entry.id === active.teamID);
		const move = Dex.moves.get(event.args[1]);
		if (pokemon && move.exists && !pokemon.moves.some(known => known.id === move.id)) {
			pokemon.moves.push({ id: move.id, name: move.name });
		}
	}

	private applyFaint(event: ProtocolEvent) {
		const active = this.activeFor(event.args[0]);
		if (!active) return;
		active.fainted = true;
		active.health = { current: 0, max: 100, exact: false, percent: 0 };
	}

	private applyHealth(event: ProtocolEvent) {
		const active = this.activeFor(event.args[0]);
		if (!active) return;
		active.health = parseHealth(event.args[1] || '', false);
		active.fainted = (event.args[1] || '').endsWith(' fnt');
		active.status = statusFromCondition(event.args[1] || '') || active.status;
	}

	private applyStatus(event: ProtocolEvent, cured: boolean) {
		const active = this.activeFor(event.args[0]);
		if (active) active.status = cured ? null : event.args[1] || null;
	}

	private applyBoost(event: ProtocolEvent, direction: -1 | 0 | 1) {
		const active = this.observedFor(event.args[0]);
		const stat = event.args[1] as keyof typeof EMPTY_BOOSTS;
		const amount = Number(event.args[2]);
		if (!active || !(stat in active.boosts) || !Number.isFinite(amount)) return;
		active.boosts[stat] = direction ? clampBoost(active.boosts[stat] + direction * amount) : clampBoost(amount);
	}

	private applyInvertBoost(event: ProtocolEvent) {
		const active = this.observedFor(event.args[0]);
		if (!active) return;
		for (const stat of Object.keys(active.boosts) as (keyof typeof active.boosts)[]) active.boosts[stat] *= -1;
	}

	private applyClearBoost(event: ProtocolEvent) {
		const active = this.observedFor(event.args[0]);
		if (active) Object.assign(active.boosts, EMPTY_BOOSTS);
	}

	private applyClearAllBoost() {
		for (const active of Object.values(this.opponentActive)) if (active) Object.assign(active.boosts, EMPTY_BOOSTS);
		for (const active of this.ownObserved.values()) Object.assign(active.boosts, EMPTY_BOOSTS);
	}

	private applyDirectionalClear(event: ProtocolEvent, direction: -1 | 1) {
		const active = this.observedFor(event.args[0]);
		if (!active) return;
		for (const stat of Object.keys(active.boosts) as (keyof typeof active.boosts)[]) {
			if (Math.sign(active.boosts[stat]) === direction) active.boosts[stat] = 0;
		}
	}

	private applyCopyBoost(event: ProtocolEvent) {
		const source = this.observedFor(event.args[0]);
		const target = this.observedFor(event.args[1]);
		if (!target || !source) return;
		const stats = event.args[2]?.split(',').map(stat => stat.trim()) || Object.keys(EMPTY_BOOSTS);
		for (const stat of stats as (keyof typeof EMPTY_BOOSTS)[]) {
			if (stat in target.boosts) target.boosts[stat] = source.boosts[stat];
		}
	}

	private applySwapBoost(event: ProtocolEvent) {
		const first = this.observedFor(event.args[0]);
		const second = this.observedFor(event.args[1]);
		if (!first || !second) return;
		const stats = event.args[2]?.split(',').map(stat => stat.trim()) || Object.keys(EMPTY_BOOSTS);
		for (const stat of stats as (keyof typeof EMPTY_BOOSTS)[]) {
			if (!(stat in first.boosts)) continue;
			[first.boosts[stat], second.boosts[stat]] = [second.boosts[stat], first.boosts[stat]];
		}
	}

	private applyWeather(event: ProtocolEvent) {
		const weather = effectID(event.args[0]);
		if (!weather || weather === 'none') {
			this.weather = null;
			this.weatherStartedTurn = null;
		} else {
			this.weather = weather;
			if (!event.kwArgs.upkeep) this.weatherStartedTurn = this.turn;
		}
	}

	private applySideCondition(event: ProtocolEvent, active: boolean) {
		const ident = parsePokemonIdent(event.args[0] || '');
		const conditions = ident?.side === this.sideID ? this.selfSideConditions : this.opponentSideConditions;
		this.setCondition(conditions, effectID(event.args[1]), active);
	}

	private swapSideConditions() {
		const own = { ...this.selfSideConditions };
		for (const key of Object.keys(this.selfSideConditions)) delete this.selfSideConditions[key];
		Object.assign(this.selfSideConditions, this.opponentSideConditions);
		for (const key of Object.keys(this.opponentSideConditions)) delete this.opponentSideConditions[key];
		Object.assign(this.opponentSideConditions, own);
	}

	private applyVolatile(event: ProtocolEvent, active: boolean) {
		const pokemon = this.observedFor(event.args[0]);
		if (!pokemon) return;
		const volatile = effectID(event.args[1]);
		if (active) pokemon.volatiles.add(volatile);
		else pokemon.volatiles.delete(volatile);
	}

	private applyReveal(event: ProtocolEvent, property: 'item' | 'ability', ended = false) {
		const active = this.activeFor(event.args[0]);
		if (!active) return;
		active[property] = ended ? null : effectID(event.args[1]);
		if (property === 'item' && active.teamID) this.opponentCurrentItems.set(active.teamID, active.item);
	}

	private setCondition(conditions: Record<string, ObservedCondition>, id: string, active: boolean) {
		if (!id) return;
		if (active) conditions[id] = { active: true, started_turn: this.turn };
		else delete conditions[id];
	}

	private activeFor(value: string | undefined) {
		const ident = parsePokemonIdent(value || '');
		if (!ident || ident.side === this.sideID || !ident.slot) return null;
		return this.opponentActive[OPPONENT_SLOT_TO_POSITION[ident.slot]] || null;
	}

	private observedFor(value: string | undefined) {
		const ident = parsePokemonIdent(value || '');
		if (!ident) return null;
		if (ident.side === this.sideID) {
			let observed = this.ownObserved.get(ident.name);
			if (!observed) {
				observed = { boosts: { ...EMPTY_BOOSTS }, volatiles: new Set() };
				this.ownObserved.set(ident.name, observed);
			}
			return observed;
		}
		return this.activeFor(value);
	}

	private findOpponent(species: string, name: string) {
		return this.opponentTeam.find(pokemon => pokemon.species === species || pokemon.name === name) || null;
	}

	private currentOpponentItem(pokemon: ObservedTeamPokemon) {
		return this.opponentCurrentItems.has(pokemon.id) ? this.opponentCurrentItems.get(pokemon.id)! : pokemon.item;
	}
}

export function parseHealth(condition: string, exact: boolean, knownMax?: number): HealthState {
	const match = /^(\d+)(?:\/(\d+))?/.exec(condition);
	const current = Number(match?.[1] || 0);
	const max = Number(match?.[2] || knownMax || (exact ? current || 1 : 100));
	return { current, max, exact, percent: max ? current / max * 100 : 0 };
}

function statusFromCondition(condition: string) {
	const parts = condition.trim().split(' ');
	const status = parts[1];
	return status && status !== 'fnt' ? status : null;
}

function effectID(value = '') {
	return Dex.toID(value.replace(/^(move|ability|item): /, ''));
}

function clampBoost(value: number) {
	return Math.max(-6, Math.min(6, value));
}

function ownPokemonID(index: number): OwnPokemonID {
	return `team_${index}`;
}

function opponentPokemonID(index: number): OpponentPokemonID {
	return `opponent_${index}`;
}
