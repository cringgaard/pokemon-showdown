import { Dex } from '../../sim/dex';
import { Teams } from '../../sim/teams';
import type { LoadedSubmission } from '../submissions/submission-loader';

export interface PublicTeamSheetPokemon {
	name: string;
	species: string;
	sprite: string;
	item: string | null;
	ability: string;
	moves: string[];
}

export interface PublicTeamSheet {
	participant: { id: string, name: string };
	pokemon: PublicTeamSheetPokemon[];
}

/** Strict Open Team Sheet projection. Never add training values or calculated stats here. */
export function publicTeamSheet(submission: LoadedSubmission, participantID = submission.id): PublicTeamSheet {
	Dex.includeData();
	const team = Teams.unpack(submission.packedTeam);
	if (!team || team.length !== 6) throw new Error(`Validated team for ${submission.name} could not be unpacked.`);
	return {
		participant: { id: participantID, name: submission.name },
		pokemon: team.map(set => {
			const species = Dex.species.get(set.species);
			return {
				name: set.name || species.name,
				species: species.name,
				sprite: species.spriteid,
				item: set.item ? Dex.items.get(set.item).name : null,
				ability: Dex.abilities.get(set.ability).name,
				moves: set.moves.map(move => Dex.moves.get(move).name),
			};
		}),
	};
}

export function publicTeamSheets(
	participants: Map<string, { submission: LoadedSubmission }>
): Map<string, PublicTeamSheet> {
	return new Map([...participants].map(([id, prepared]) => [id, publicTeamSheet(prepared.submission, id)]));
}
