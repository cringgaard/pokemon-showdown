import type { ChoiceRequest } from '../../sim/side';
import type { BotResponse, OwnPokemonID, PokemonAction, Position, Target } from '../api/types';

const POSITIONS: Position[] = ['left', 'right'];

export function adaptAction(response: BotResponse, request: ChoiceRequest, teamIDs: OwnPokemonID[]): string {
	if ('team' in response) {
		const indexes = response.team.map(id => teamIDs.indexOf(id) + 1);
		if (indexes.some(index => index < 1)) throw new Error('Team Preview response contains an unknown Pokemon ID');
		return `team ${indexes.join('')}`;
	}
	const choices = POSITIONS.map((position, index) => {
		const action = (response).actions[position];
		if (!action) return 'pass';
		return adaptPokemonAction(action, request, teamIDs, index);
	});
	return choices.join(', ');
}

function adaptPokemonAction(
	action: PokemonAction, request: ChoiceRequest, teamIDs: OwnPokemonID[], activeIndex: number
) {
	if (action.type === 'switch') {
		const slot = teamIDs.indexOf(action.pokemon) + 1;
		if (!slot) throw new Error(`Unknown switch target ${action.pokemon}`);
		return `switch ${slot}`;
	}
	if (!('active' in request)) throw new Error('Move action supplied outside a move request');
	const slot = request.active[activeIndex].moves.findIndex(move => move.id === action.move) + 1;
	if (!slot) throw new Error(`Unknown move ${action.move}`);
	let choice = `move ${slot}`;
	if (action.target) choice += ` ${targetLocation(action.target, activeIndex)}`;
	if (action.terastallize) choice += ' terastallize';
	return choice;
}

function targetLocation(target: Target, activeIndex: number) {
	switch (target) {
	case 'opponent_left': return 1;
	case 'opponent_right': return 2;
	case 'self': return -(activeIndex + 1);
	case 'ally': return -((activeIndex ^ 1) + 1);
	}
}
