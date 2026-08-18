export type BattlePhase = 'team_preview' | 'turn' | 'forced_switch';
export type Position = 'left' | 'right';
export type Target = 'self' | 'ally' | 'opponent_left' | 'opponent_right';
export type OwnPokemonID = `team_${number}`;
export type OpponentPokemonID = `opponent_${number}`;

export interface BotState {
	schema_version: 1;
	battle: BattleInfo;
	runtime: RuntimeInfo;
	self: OwnSideState;
	opponent: OpponentSideState;
	field: FieldState;
	request: BotRequest;
	history: BattleEvent[];
}

export interface BattleInfo {
	format: string;
	turn: number;
	phase: BattlePhase;
}

export interface RuntimeInfo {
	decision_id: number;
	revision: number;
	attempt: number;
	previous_error: string | null;
	deadline_ms: number;
}

export interface HealthState {
	current: number;
	max: number;
	exact: boolean;
	percent: number;
}

export interface Stats {
	atk: number;
	def: number;
	spa: number;
	spd: number;
	spe: number;
}

export interface Boosts extends Stats {
	accuracy: number;
	evasion: number;
}

export interface KnownMove {
	id: string;
	name: string;
}

export interface OwnPokemonState {
	id: OwnPokemonID;
	species: string;
	name: string;
	health: HealthState;
	status: string | null;
	fainted: boolean;
	level: number;
	item: string | null;
	ability: string;
	tera_type: string;
	terastallized: boolean;
	stats: Stats;
	boosts: Boosts;
	moves: KnownMove[];
	volatiles: string[];
}

export interface OpponentPokemonState {
	id: OpponentPokemonID;
	species: string;
	name: string;
	item: string | null;
	ability: string | null;
	tera_type: string | null;
	moves: KnownMove[];
}

export interface OpponentActiveState {
	position: Position;
	apparent_species: string;
	team_id: OpponentPokemonID | null;
	health: HealthState;
	status: string | null;
	fainted: boolean;
	item: string | null;
	ability: string | null;
	terastallized: boolean;
	boosts: Boosts;
	volatiles: string[];
}

export interface OwnSideState {
	name: string;
	team: OwnPokemonState[];
	active: Partial<Record<Position, OwnPokemonID>>;
	side_conditions: Record<string, ObservedCondition>;
}

export interface OpponentSideState {
	name: string;
	team: OpponentPokemonState[];
	active: Partial<Record<Position, OpponentActiveState>>;
	side_conditions: Record<string, ObservedCondition>;
}

export interface ObservedCondition {
	active: boolean;
	started_turn: number;
}

export interface FieldState {
	weather: string | null;
	weather_started_turn: number | null;
	conditions: Record<string, ObservedCondition>;
}

export interface MoveOption {
	id: string;
	name: string;
	type: string;
	category: 'Physical' | 'Special' | 'Status';
	base_power: number;
	priority: number;
	pp: number;
	max_pp: number;
	disabled: boolean;
	legal_targets: Target[];
}

export interface MoveAction {
	type: 'move';
	move: string;
	target?: Target;
	terastallize?: boolean;
}

export interface SwitchAction {
	type: 'switch';
	pokemon: OwnPokemonID;
}

export type PokemonAction = MoveAction | SwitchAction;

export interface TurnResponse {
	actions: Partial<Record<Position, PokemonAction>>;
}

export interface TeamPreviewResponse {
	team: [OwnPokemonID, OwnPokemonID, OwnPokemonID, OwnPokemonID];
}

export type BotResponse = TurnResponse | TeamPreviewResponse;

export interface SlotRequest {
	required: boolean;
	moves: MoveOption[];
	switches: OwnPokemonID[];
	can_terastallize: boolean;
}

export interface TeamPreviewBotRequest {
	kind: 'team_preview';
	team_size: number;
	legal_actions: TeamPreviewResponse[];
}

export interface TurnBotRequest {
	kind: 'turn' | 'forced_switch';
	slots: Record<Position, SlotRequest>;
	legal_actions: TurnResponse[];
}

export type BotRequest = TeamPreviewBotRequest | TurnBotRequest;

export interface BattleEvent {
	turn: number;
	type: string;
	data: Record<string, unknown>;
	raw: string;
}
