import { Dex } from '../../sim/dex';
import type { ChoiceRequest, MoveRequest, PokemonMoveRequestData } from '../../sim/side';
import type {
	BotRequest, MoveAction, MoveOption, OwnPokemonID, PokemonAction, Position, SlotRequest,
	Target, TeamPreviewResponse, TurnResponse,
} from '../api/types';

const POSITIONS: Position[] = ['left', 'right'];

export interface ActionContext {
	teamIDs: OwnPokemonID[];
	teamSize?: number;
}

export function generateLegalActions(request: ChoiceRequest, context: ActionContext): BotRequest | null {
	if (request.wait) return null;
	if (request.teamPreview) {
		const teamSize = request.maxChosenTeamSize || request.side.pokemon.length;
		const selections = permutations(context.teamIDs.slice(0, request.side.pokemon.length), teamSize);
		return {
			kind: 'team_preview',
			team_size: teamSize,
			legal_actions: selections.map(team => ({ team }) as TeamPreviewResponse),
		};
	}

	const forced = !!request.forceSwitch;
	const slots = {} as Record<Position, SlotRequest>;
	const slotActions: PokemonAction[][] = [];
	for (let i = 0; i < 2; i++) {
		const position = POSITIONS[i];
		const required = forced ? !!request.forceSwitch[i] : isMoveSlotRequired(request, i);
		const switches = required ? getSwitches(request, context, i, forced) : [];
		const moves = !forced && required ? buildMoveOptions(request.active[i], i, request.active.length) : [];
		const canTera = !forced && required && !!request.active[i]?.canTerastallize;
		slots[position] = { required, moves, switches, can_terastallize: canTera };
		if (!required) {
			slotActions.push([]);
			continue;
		}
		const actions: PokemonAction[] = switches.map(pokemon => ({ type: 'switch', pokemon }));
		for (const move of moves) {
			const targets: (Target | undefined)[] = move.legal_targets.length ? move.legal_targets : [undefined];
			for (const target of targets) {
				actions.push(cleanMoveAction(move.id, target, false));
				if (canTera) actions.push(cleanMoveAction(move.id, target, true));
			}
		}
		slotActions.push(actions);
	}

	const legalActions: TurnResponse[] = [];
	const leftChoices = slots.left.required ? slotActions[0] : [undefined];
	const rightChoices = slots.right.required ? slotActions[1] : [undefined];
	for (const left of leftChoices) {
		for (const right of rightChoices) {
			if (!isJointActionLegal(left, right)) continue;
			const actions: Partial<Record<Position, PokemonAction>> = {};
			if (left) actions.left = left;
			if (right) actions.right = right;
			legalActions.push({ actions });
		}
	}
	return { kind: forced ? 'forced_switch' : 'turn', slots, legal_actions: legalActions };
}

function isMoveSlotRequired(request: MoveRequest, index: number) {
	const pokemon = request.side.pokemon[index];
	return !!request.active[index] && !!pokemon && !pokemon.condition.endsWith(' fnt') && !pokemon.commanding;
}

function buildMoveOptions(active: PokemonMoveRequestData, activeIndex: number, activeCount: number): MoveOption[] {
	return active.moves.map(moveData => {
		const move = Dex.moves.get(moveData.id);
		return {
			id: move.id,
			name: move.name,
			type: move.type,
			category: move.category,
			base_power: move.basePower,
			priority: move.priority,
			pp: moveData.pp ?? 0,
			max_pp: moveData.maxpp ?? move.pp,
			disabled: !!moveData.disabled,
			legal_targets: moveData.disabled ? [] : semanticTargets(moveData.target || move.target, activeIndex, activeCount),
		};
	}).filter(move => !move.disabled);
}

function semanticTargets(target: string, activeIndex: number, activeCount: number): Target[] {
	if (activeCount < 2) return [];
	switch (target) {
	case 'normal':
	case 'adjacentFoe': return ['opponent_left', 'opponent_right'];
	case 'any': return ['ally', 'opponent_left', 'opponent_right'];
	case 'adjacentAlly': return ['ally'];
	case 'adjacentAllyOrSelf': return activeIndex < activeCount ? ['self', 'ally'] : ['self'];
	default: return [];
	}
}

function getSwitches(request: Exclude<ChoiceRequest, { wait: true } | { teamPreview: true }>, context: ActionContext,
	activeIndex: number, forced: boolean) {
	if (!forced && 'active' in request && request.active[activeIndex]?.trapped) return [];
	return request.side.pokemon.flatMap((pokemon, index) => {
		if (pokemon.active || pokemon.condition.endsWith(' fnt')) return [];
		return context.teamIDs[index] ? [context.teamIDs[index]] : [];
	});
}

function cleanMoveAction(move: string, target: Target | undefined, terastallize: boolean): MoveAction {
	const action: MoveAction = { type: 'move', move };
	if (target) action.target = target;
	if (terastallize) action.terastallize = true;
	return action;
}

function isJointActionLegal(left: PokemonAction | undefined, right: PokemonAction | undefined) {
	if (left?.type === 'switch' && right?.type === 'switch' && left.pokemon === right.pokemon) return false;
	if (left?.type === 'move' && right?.type === 'move' && left.terastallize && right.terastallize) return false;
	return true;
}

function permutations<T>(values: T[], length: number): [T, T, T, T][] {
	if (length !== 4) throw new Error(`Milestone 1 requires bring-6/pick-4; received pick-${length}`);
	const output: [T, T, T, T][] = [];
	const visit = (chosen: T[], remaining: T[]) => {
		if (chosen.length === length) {
			output.push(chosen as [T, T, T, T]);
			return;
		}
		for (let i = 0; i < remaining.length; i++) {
			visit([...chosen, remaining[i]], [...remaining.slice(0, i), ...remaining.slice(i + 1)]);
		}
	};
	visit([], values);
	return output;
}
