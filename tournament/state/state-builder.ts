import { Dex, type ModdedDex } from '../../sim/dex';
import type { ChoiceRequest } from '../../sim/side';
import type {
	BotState, Boosts, OpponentActiveState, OwnPokemonID, OwnPokemonState, Position, RuntimeInfo,
} from '../api/types';
import { generateLegalActions } from '../actions/action-generator';
import { EMPTY_BOOSTS } from './battle-state';
import { parsePokemonIdent, speciesFromDetails } from './protocol-parser';
import { parseHealth, type StateTracker } from './state-tracker';

export interface StateBuildOptions {
	format: string;
	runtime: RuntimeInfo;
}

export function buildBotState(tracker: StateTracker, request: ChoiceRequest, options: StateBuildOptions): BotState {
	const teamIDs = tracker.teamIDsForRequest(request);
	const dex = Dex.forFormat(options.format);
	const botRequest = generateLegalActions(request, { teamIDs, format: options.format });
	if (!botRequest) throw new Error('Cannot build a decision state for a wait request');
	const phase = botRequest.kind;
	const ownTeam = request.side.pokemon.map((pokemon, index) => ownPokemonState(
		pokemon, teamIDs[index] || `team_${index}`, tracker, dex
	));
	const active: Partial<Record<Position, OwnPokemonID>> = {};
	const activePokemon = request.side.pokemon.filter(pokemon => pokemon.active);
	if (activePokemon[0]) active.left = tracker.ownIDForIdent(activePokemon[0].ident) || teamIDs[0];
	if (activePokemon[1]) active.right = tracker.ownIDForIdent(activePokemon[1].ident) || teamIDs[1];

	return {
		schema_version: 1,
		battle: { format: options.format, mod: dex.currentMod, turn: tracker.turn, phase },
		runtime: options.runtime,
		self: {
			name: request.side.name,
			team: ownTeam,
			active,
			side_conditions: { ...tracker.selfSideConditions },
		},
		opponent: {
			name: tracker.opponentName,
			team: tracker.opponentTeam.map(pokemon => ({
				id: pokemon.id,
				species: pokemon.species,
				name: pokemon.name,
				item: pokemon.item,
				ability: pokemon.ability,
				tera_type: pokemon.teraType,
				nature: pokemon.nature,
				gender: pokemon.gender,
				level: pokemon.level,
				moves: pokemon.moves.map(move => ({ ...move })),
			})),
			active: Object.fromEntries(Object.entries(tracker.opponentActive).map(([position, pokemon]) => [
				position, opponentActiveState(pokemon),
			])),
			side_conditions: { ...tracker.opponentSideConditions },
		},
		field: {
			weather: tracker.weather,
			weather_started_turn: tracker.weatherStartedTurn,
			conditions: { ...tracker.fieldConditions },
		},
		request: botRequest,
		history: tracker.history.map(event => ({ ...event, data: { ...event.data } })),
	};
}

function ownPokemonState(
	pokemon: ChoiceRequest['side']['pokemon'][number], id: OwnPokemonID, tracker: StateTracker, dex: ModdedDex
): OwnPokemonState {
	const species = speciesFromDetails(pokemon.details);
	const speciesData = dex.species.get(species);
	// Showdown clears boosts and volatiles on switch-out. Ignore any older observation for benched Pokemon.
	const observed = pokemon.active ? tracker.ownObservationForIdent(pokemon.ident) : null;
	return {
		id,
		species,
		name: parsePokemonIdent(pokemon.ident)?.name || species,
		health: parseHealth(pokemon.condition, true, tracker.ownMaxHPForID(id)),
		status: conditionStatus(pokemon.condition),
		fainted: pokemon.condition.endsWith(' fnt'),
		level: Number(/(?:^|, )L(\d+)/.exec(pokemon.details)?.[1] || 100),
		item: pokemon.item || null,
		ability: pokemon.ability || pokemon.baseAbility,
		types: pokemon.terastallized ? [pokemon.terastallized] : [...speciesData.types],
		transformation: transformationForOwnPokemon(pokemon, speciesData),
		stats: { ...pokemon.stats },
		boosts: { ...(observed?.boosts || EMPTY_BOOSTS) } as Boosts,
		moves: pokemon.moves.map(moveID => ({
			id: dex.moves.get(moveID).id,
			name: dex.moves.get(moveID).name,
		})),
		volatiles: observed ? [...observed.volatiles] : [],
	};
}

function opponentActiveState(pokemon: NonNullable<StateTracker['opponentActive'][Position]>): OpponentActiveState {
	return {
		position: pokemon.position,
		apparent_species: pokemon.apparentSpecies,
		team_id: pokemon.teamID,
		health: { ...pokemon.health },
		status: pokemon.status,
		fainted: pokemon.fainted,
		item: pokemon.item,
		ability: pokemon.ability,
		types: [...pokemon.types],
		transformation: pokemon.transformation ? { ...pokemon.transformation } : null,
		boosts: { ...pokemon.boosts },
		volatiles: [...pokemon.volatiles],
	};
}

function transformationForOwnPokemon(
	pokemon: ChoiceRequest['side']['pokemon'][number], species: ReturnType<ModdedDex['species']['get']>
) {
	if (pokemon.terastallized) return { kind: 'terastallize' as const };
	if (species.isMega) return { kind: 'mega' as const };
	if (species.forme === 'Ultra') return { kind: 'ultra' as const };
	return null;
}

function conditionStatus(condition: string) {
	const status = condition.trim().split(' ')[1];
	return status && status !== 'fnt' ? status : null;
}
