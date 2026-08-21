import type {
	Boosts, HealthState, KnownMove, OpponentPokemonID, Position, TransformationState,
} from '../api/types';

export const EMPTY_BOOSTS: Boosts = {
	atk: 0, def: 0, spa: 0, spd: 0, spe: 0, accuracy: 0, evasion: 0,
};

export interface ObservedActivePokemon {
	position: Position;
	ident: string;
	name: string;
	apparentSpecies: string;
	teamID: OpponentPokemonID | null;
	health: HealthState;
	status: string | null;
	fainted: boolean;
	item: string | null;
	ability: string | null;
	types: string[] | null;
	transformation: TransformationState | null;
	boosts: Boosts;
	volatiles: Set<string>;
}

export interface ObservedTeamPokemon {
	id: OpponentPokemonID;
	name: string;
	species: string;
	item: string | null;
	ability: string | null;
	teraType: string | null;
	nature: string | null;
	gender: string | null;
	level: number | null;
	moves: KnownMove[];
}
