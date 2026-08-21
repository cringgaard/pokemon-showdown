# Pokémon Showdown Bot Tournament — VGC Bot Harness Design

Status: implementation specification for the first working vertical slice.

This document defines the architecture and public bot API for a headless Pokémon Showdown bot tournament. The tournament uses Pokémon Showdown as the authoritative battle simulator and exposes a stable Python interface to participant bots.

The first milestone is intentionally narrow: two bundled Python reference bots must be able to play complete deterministic Champions VGC Doubles matches through the same interface that participants will use.

## 1. Goals

The tournament harness should:

- use Pokémon Showdown as the only authority for battle mechanics, legality and RNG;
- target Gen 9 VGC-style Doubles from the beginning;
- support bring-6, pick-4 Team Preview with two leads;
- expose a small Python API that does not require participants to understand Showdown protocol syntax;
- expose only player-visible information to each bot;
- run each bot as a persistent Python process for a match;
- support arbitrary participant code and model files later via isolated execution;
- detect malformed, illegal, hanging or repeatedly-invalid bots and continue the match using a deterministic random legal fallback;
- record enough information for deterministic replay and debugging;
- keep tournament code outside `sim/` and avoid modifying Showdown battle mechanics.

## 2. Non-goals for Milestone 1

Do not implement these yet unless required to complete the vertical slice:

- tournament brackets, standings or scheduling;
- ZIP submission ingestion;
- dependency installation from participant `requirements.txt`;
- Docker/container sandboxing;
- GPU support;
- web UI or spectator frontend;
- full replay presentation;
- advanced damage calculation SDK;
- every obscure simulator protocol message;
- final production tournament regulation.

Milestone 1 should establish the architectural boundary cleanly so these can be added later.

## 3. Core architecture

```text
Tournament / Match Runner
        |
        v
    BattleStream
        |
  getPlayerStreams()
   /           \
 p1             p2
 |               |
 v               v
StateTracker   StateTracker
 |               |
 v               v
StateBuilder   StateBuilder
 |               |
 v               v
BotState JSON  BotState JSON
 |               |
 v               v
PythonWorker   PythonWorker
 |               |
 v               v
BotResponse    BotResponse
 |               |
 v               v
ActionValidator / ActionAdapter
        |
        v
  Showdown choice strings
        |
        v
    BattleStream
```

The omniscient stream must never be used to construct bot-visible state. It may be consumed only by match logging/result code.

## 4. Showdown integration

Use the existing simulator APIs:

- `BattleStream`
- `getPlayerStreams`
- `Teams`
- `TeamValidator`
- `Dex`

Do not directly expose `Battle`, `Side`, `Pokemon`, or other simulator objects to participant bots.

Use explicit battle seeds for reproducibility.

The production default is the exact `[Gen 9 Champions] VGC 2026 Reg M-B` format (`gen9championsvgc2026regmb`). The format remains configurable. For its consensual `Open Team Sheets` rule, the headless runner explicitly issues the simulator's OTS acceptance command during Team Preview; it does not alter the format ID or duplicate sheet data itself.

Resolve mechanics data with `Dex.forFormat(configuredFormat)` wherever format semantics matter. Record the resolved mod in bot-visible battle metadata.

## 5. Participant submission contract

The intended participant submission is eventually:

```text
submission.zip
├── main.py
├── team.txt
├── requirements.txt        # optional
└── arbitrary extra files   # models/config/etc.
```

For Milestone 1, bundled reference bots may live directly inside the repository rather than ZIP archives.

Participant code exposes exactly one required function:

```python
def choose_action(state: dict) -> dict:
    ...
```

`main.py` is imported once when the Python worker starts. Module-level initialization and model loading therefore occur once per worker lifetime.

Participant bots may keep in-process state between decisions. They must not rely on it for correctness because a timed-out worker may be terminated and restarted.

## 6. Public bot API overview

Every invocation receives a JSON-serializable `BotState` with one of three phases:

- `team_preview`
- `turn`
- `forced_switch`

The same `choose_action(state)` function handles all phases.

### 6.1 Stable own-team IDs

Every submitted Pokémon receives a stable ID before battle start:

```text
team_0
team_1
team_2
team_3
team_4
team_5
```

These IDs never change when Showdown reorders the selected four after Team Preview or when Pokémon switch positions.

### 6.2 Opponent identities and Illusion

Open Team Sheet entries should similarly receive IDs such as:

```text
opponent_0 ... opponent_5
```

However, active opponent identity must be allowed to be unknown when the player-visible protocol does not uniquely establish it, especially under Illusion.

Never use hidden simulator state to map a disguised active Pokémon to its true team slot. An opponent active entry therefore has both:

- `apparent_species`
- `team_id: OpponentPokemonID | null`

When `|replace|` or another public event resolves identity, the tracker may reconcile it.

## 7. TypeScript public API types

Create the public contract under something like:

```text
tournament/api/types.ts
```

The exact syntax may evolve during implementation, but the semantics below should remain stable.

```ts
export type BattlePhase = 'team_preview' | 'turn' | 'forced_switch';
export type Position = 'left' | 'right';

export type Target =
    | 'self'
    | 'ally'
    | 'opponent_left'
    | 'opponent_right';

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
    mod: string;
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
```

`deadline_ms` means remaining wall-clock time for the current Showdown decision, not an absolute timestamp.

## 8. Pokémon state

Own Pokémon may expose exact values available in the player's current request.

```ts
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

export interface Boosts {
    atk: number;
    def: number;
    spa: number;
    spd: number;
    spe: number;
    accuracy: number;
    evasion: number;
}

export interface KnownMove {
    id: string;
    name: string;
}

export type TransformationKind =
    'mega' | 'mega_x' | 'mega_y' | 'ultra' | 'dynamax' | 'terastallize';

export interface TransformationState {
    kind: TransformationKind;
}

export interface TransformationOption {
    kind: TransformationKind;
    result_species?: string;
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
    types: string[];
    transformation: TransformationState | null;
    stats: Stats;
    boosts: Boosts;
    moves: KnownMove[];
    volatiles: string[];
}
```

Do not invent precision for opponents. If Showdown reports opponent HP as a percentage/fraction rather than exact HP, preserve that censorship through `exact: false`.

Open Team Sheets expose only information publicly available under the chosen format. Champions sheets contain species, item, ability, moves, nature, gender, level, and an inert submitted Tera type. They must not expose stats, Stat Points/EVs, IVs, or other simulator-only information. Sheet fields remain immutable set metadata; current active form, types, ability, and transformation are tracked separately from player-visible protocol.

## 9. Active positions

From player 1's perspective Showdown Doubles positions are conceptually:

```text
p2b p2a
p1a p1b
```

The public API should hide Showdown position syntax and expose semantic positions:

- `left`
- `right`
- `opponent_left`
- `opponent_right`

Maintain an internal position-to-stable-ID mapping and update it on switch/drag/swap/etc.

## 10. Move options

Current move choices should be enriched with static public Dex information.

```ts
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
```

`legal_targets` is semantic. Participant bots never need Showdown target locations such as `+1`, `+2`, `-1`, etc.

Moves that do not require an explicit target should have an empty `legal_targets` array.

## 11. Bot requests and responses

### 11.1 Move/switch action

```ts
export interface MoveAction {
    type: 'move';
    move: string;
    target?: Target;
    transformation?: TransformationKind;
}

export interface SwitchAction {
    type: 'switch';
    pokemon: OwnPokemonID;
}

export interface ReviveAction {
    type: 'revive';
    pokemon: OwnPokemonID;
}

export type PokemonAction = MoveAction | SwitchAction | ReviveAction;

export interface TurnResponse {
    actions: Partial<Record<Position, PokemonAction>>;
}
```

### 11.2 Team Preview

```ts
export interface TeamPreviewResponse {
    team: [OwnPokemonID, OwnPokemonID, OwnPokemonID, OwnPokemonID];
}
```

The order is meaningful:

1. left lead
2. right lead
3. first back Pokémon
4. second back Pokémon

### 11.3 Slot request

```ts
export interface SlotRequest {
    required: boolean;
    moves: MoveOption[];
    switches: OwnPokemonID[];
    revives: OwnPokemonID[];
    available_transformations: TransformationOption[];
}
```

`TransformationOption` contains `kind` and may contain `result_species` when that result follows from public request/set data. Champions requests expose ordinary `mega`; Charizard and Raichu X/Y stones do not use `mega_x` or `mega_y`. Tera type on a Champions OTS entry is not transformation availability.

The participant API does not expose `pass`. If Showdown requires a pass for a fainted/non-acting slot, the adapter inserts it.

Revival Blessing selection is exposed as the semantic `revive` action. The adapter translates it to Showdown's
`switch N` choice syntax; participant bots never emit simulator choice syntax directly.

## 12. Complete legal actions

Every request should contain the complete set of currently legal public responses:

```ts
request.legal_actions
```

For Team Preview this contains all legal ordered bring-four selections.

For turns and forced switches it contains all legal complete joint actions after applying cross-slot constraints.

This list is the single source of truth for:

- response validation;
- `RandomBot`;
- runtime fallbacks;
- many unit tests;
- simple participant strategies.

A minimal legal bot is therefore:

```python
import random

def choose_action(state):
    return random.choice(state['request']['legal_actions'])
```

### 12.1 Action generation

Create an action generator, likely:

```text
tournament/actions/action-generator.ts
```

It should:

1. derive legal per-slot move/switch options from the latest Showdown request;
2. expand explicit move target choices;
3. expand transformation variants only where the current Showdown request allows them;
4. create the Cartesian product for required slots;
5. filter invalid cross-slot combinations.

Cross-slot constraints include at minimum:

- both slots cannot switch into the same bench Pokémon;
- both slots cannot consume the same side-wide transformation resource in one turn;
- required slots must act;
- inactive/non-required slots must not provide participant actions;
- forced-switch requests may contain one or two required positions.

Showdown remains the final legality authority.

## 13. Action validation and translation

Create a validator/adapter layer between Python and Showdown.

Participant responses should first be structurally validated and canonicalized. The preferred validation model is equivalence to one entry in `request.legal_actions`.

The adapter then translates semantic actions into Showdown choice strings, for example conceptually:

```text
move protect mega, move fakeout +1
```

Participants must never need to produce this syntax themselves.

## 14. State tracking and information boundary

Create roughly:

```text
tournament/state/
├── battle-state.ts
├── protocol-parser.ts
├── state-tracker.ts
└── state-builder.ts
```

Responsibilities:

### `protocol-parser.ts`

Convert player-visible Showdown protocol lines into typed/internal events.

### `state-tracker.ts`

Maintain mutable observed state from only that player's stream.

### `state-builder.ts`

Combine:

- tracked observations;
- latest player `ChoiceRequest`;
- public static Dex metadata;

into immutable `BotState` JSON.

The player's latest `ChoiceRequest` should be authoritative for own-side exact state and current choices. Opponent state must be reconstructed only from public protocol/Open Team Sheet information.

Never read hidden `Battle`/opponent simulator state to populate the bot state.

## 15. Protocol events required for v1

Do not attempt exhaustive protocol support immediately. Handle the events needed for useful VGC state and complete battle progression.

At minimum:

### Battle

- `turn`
- `start`
- `win`
- `tie`

### Pokémon identity/position

- `switch`
- `drag`
- `swap`
- `replace`
- `detailschange`
- forme-change messages as needed

### Actions/outcomes

- `move`
- `cant`
- `faint`
- `-damage`
- `-heal`
- `-sethp`
- `-status`
- `-curestatus`

### Stat boosts

- `-boost`
- `-unboost`
- `-setboost`
- `-swapboost`
- `-invertboost`
- `-clearboost`
- `-clearallboost`
- related clear/copy events as practical

### Field and side state

- `-weather`
- `-fieldstart`
- `-fieldend`
- `-sidestart`
- `-sideend`
- `-swapsideconditions`

### Volatiles

- `-start`
- `-end`
- `-singleturn`
- `-singlemove`

### Revealed information

- `-item`
- `-enditem`
- `-ability`
- `-endability`

Unknown protocol lines should not crash the tracker. Preserve them in history/raw logs for debugging and future support.

## 16. Field-condition duration philosophy

The tracker should primarily represent observations, not reimplement Pokémon mechanics.

For example, rather than embedding a second Tailwind simulator, it is acceptable for v1 state to retain information such as:

```json
{
  "active": true,
  "started_turn": 3
}
```

A future SDK/derived-state layer can provide known mechanic durations. Do not duplicate Showdown battle logic unless necessary for the public interface.

## 17. History

For v1, a lightweight structured history is sufficient:

```ts
export interface BattleEvent {
    turn: number;
    type: string;
    data: Record<string, unknown>;
    raw: string;
}
```

The bot should receive player-visible history only. Including the raw line is useful for advanced bots and debugging.

## 18. Python worker protocol

Use one persistent Python subprocess per bot per match.

Node-to-Python communication should use JSON Lines over stdin/stdout.

Example request:

```json
{"type":"decision","id":17,"revision":0,"state":{}}
```

Example response:

```json
{"type":"result","id":17,"revision":0,"response":{}}
```

Worker-side exceptions should be serialized as an error message rather than corrupting the protocol.

Participant stdout must not corrupt JSONL. The worker wrapper should redirect participant stdout to stderr while invoking `choose_action`, or otherwise reserve stdout exclusively for the worker protocol.

Capture stderr into match/bot logs.

## 19. Runtime supervision

Bot failures must never deadlock a match.

Support two independent limits:

- total wall-clock decision timeout;
- maximum invalid responses for a request revision.

Initial configuration may use values such as:

```yaml
decision_timeout_ms: 5000
max_invalid_attempts: 3
```

Keep these configurable.

### 19.1 Decision identity

Each Showdown decision receives a `decision_id`.

A `revision` increments when Showdown legitimately updates the current request, especially after an `[Unavailable choice]` response reveals new information.

An `attempt` increments when the participant returns a malformed/structurally invalid response for the current revision.

### 19.2 Deadline semantics

The wall-clock deadline belongs to the overall Showdown decision and does not reset on retries or request revisions.

Example:

```text
decision 17, revision 0, attempt 1
  -> participant invalid response
revision 0, attempt 2
  -> participant returns provisionally legal switch
  -> Showdown replies [Unavailable choice] due to hidden trapping info
revision 1, attempt 1
  -> only remaining wall-clock time is available
```

### 19.3 Invalid vs unavailable choice

Treat these differently.

Participant/harness-invalid examples:

- malformed JSON/result;
- unknown move ID;
- illegal target;
- duplicate switch-in;
- duplicate use of a side-wide transformation resource;
- response not matching a legal action.

These increment invalid attempts.

A Showdown `[Unavailable choice]` caused by newly revealed hidden information does not count as a participant error. Rebuild the request, increment `revision`, reset `attempt` to 1, preserve the original deadline, and invoke the bot again.

### 19.4 Fallback

When either:

- the decision deadline expires; or
- maximum invalid attempts are exhausted;

select a random entry from `request.legal_actions` and submit it.

Do not use Showdown's `default` for tournament fallback because it deterministically chooses a first available option and creates bias.

Fallback randomness must itself be deterministic/replayable, derived from stable match data such as battle seed + player + decision ID + revision.

Log every fallback and its reason.

### 19.5 Hung Python workers

If a Python invocation exceeds the decision deadline:

1. terminate the worker process;
2. record a timeout;
3. choose deterministic random fallback;
4. continue the battle;
5. restart the participant worker before that bot's next decision.

A future runtime config should distinguish startup timeout from per-decision timeout so model loading is not charged against move time.

## 20. Runtime statistics

Record per-bot metrics such as:

```json
{
  "decisions": 17,
  "timeouts": 1,
  "invalid_responses": 2,
  "fallbacks": 1,
  "exceptions": 0
}
```

Fallback does not automatically mean forfeiture in v1.

## 21. Reference bots

Create two bundled reference bots.

### 21.1 RandomBot

Purpose:

- prove the minimal participant API;
- provide deterministic fallback machinery;
- test complete legal action generation.

Conceptual implementation:

```python
import random

def choose_action(state):
    return random.choice(state['request']['legal_actions'])
```

For reproducible tests, prefer a tournament-provided seed/helper or otherwise ensure the bundled reference implementation can be deterministic.

### 21.2 GreedyDamageBot

Purpose:

- demonstrate how to inspect normalized state;
- demonstrate legal-action scoring;
- be stronger than random without becoming a complicated VGC AI.

Team Preview may initially choose randomly or with a simple heuristic.

For battle turns, score legal joint actions approximately using public information such as:

```text
base power × STAB × type effectiveness × simple attack/stat heuristic
```

Then select the highest-scoring entry from `legal_actions`.

The bot should deliberately operate only through the public state and must not import/access Showdown simulator internals.

## 22. Match runner

Create a headless match runner, likely under:

```text
tournament/match/
```

Responsibilities:

- validate supplied teams with `TeamValidator` before battle start;
- create `BattleStream` with explicit format and seed;
- create player streams via `getPlayerStreams`;
- start two Python workers;
- feed each player's stream into its tracker;
- invoke bots only when that player receives a request;
- validate/translate decisions;
- handle retries, unavailable choices, timeout and fallback;
- continue until `end`/winner;
- collect logs and runtime statistics.

The match runner should not access hidden simulator state to help bots.

## 23. Team format

Use human-readable Pokémon Showdown team export for `team.txt`.

Parse with `Teams.import` and validate with `TeamValidator` for the configured format.

The simulator itself does not validate externally supplied teams, so validation is a harness responsibility before creating the match.

## 24. Proposed repository structure

A reasonable initial layout is:

```text
tournament/
├── DESIGN.md
├── api/
│   └── types.ts
├── actions/
│   ├── action-generator.ts
│   ├── action-validator.ts
│   └── action-adapter.ts
├── bots/
│   ├── python-worker.ts
│   └── worker.py
├── state/
│   ├── battle-state.ts
│   ├── protocol-parser.ts
│   ├── state-tracker.ts
│   └── state-builder.ts
├── match/
│   └── match-runner.ts
├── reference-bots/
│   ├── random/
│   │   └── main.py
│   └── greedy-damage/
│       └── main.py
└── fixtures/
    └── teams/

test/tournament/
├── protocol-parser.js
├── action-generator.js
├── runtime.js
└── match-runner.js
```

Exact filenames can be adjusted if a cleaner repository-conforming structure becomes apparent during implementation.

## 25. Repository integration

Current `tsconfig.json` does not include a top-level `tournament/` directory. Add:

```json
"./tournament/**/*.ts"
```

to TypeScript compilation coverage.

Current Mocha configuration does not include `test/tournament/**/*.js`. Add it to the test spec.

Follow existing repository lint/style conventions.

## 26. Testing strategy

### 26.1 Protocol parser unit tests

Cover at minimum:

- switch/drag position mapping;
- damage/heal/status;
- boosts and clears;
- weather;
- Tailwind/side conditions;
- Trick Room/terrain field conditions;
- transformation/form changes, including public `-mega` state;
- Illusion `replace` reconciliation;
- unknown protocol lines do not crash parsing/tracking.

### 26.2 Action generator unit tests

Cover at minimum:

- normal two-slot move choices;
- explicit target expansion;
- spread/self moves with no explicit target;
- move + switch combinations;
- duplicate switch target filtering;
- only one side-wide Mega selection across both active slots;
- no transformation after the authoritative request removes availability;
- format-aware move/form/type/ability metadata;
- fainted/non-required slot handling;
- single forced switch;
- double forced switch;
- trapped/maybeTrapped behavior as represented by Showdown requests;
- Team Preview bring-four ordering.

### 26.3 Runtime controller tests

Use fake Python bots/workers that:

- return malformed results forever;
- return the same illegal action forever;
- raise exceptions;
- hang forever;
- fail twice then return a valid action;
- receive an updated request after an unavailable choice.

Verify the match cannot deadlock and fallback occurs deterministically.

### 26.4 End-to-end tests

At minimum:

- RandomBot vs RandomBot completes a VGC-style battle with a fixed seed;
- repeated run with the same seed produces the same authoritative battle outcome when all bot randomness is controlled;
- GreedyDamageBot vs RandomBot completes;
- neither bot receives hidden opponent values in its serialized state.

## 27. Milestone 1 acceptance criteria

Milestone 1 is complete when all of the following are true:

1. A TypeScript test/CLI can launch one headless Gen 9 VGC-style Doubles match.
2. Both sides use the real `getPlayerStreams` player-specific streams.
3. Both sides are controlled by persistent Python subprocesses using JSONL.
4. Both Python bots expose only `choose_action(state)`.
5. Team Preview is performed through the public API using bring-6/pick-4 ordering.
6. Normal Doubles turns support two simultaneous actions, move targets, switches and request-authorized transformations.
7. Forced switch requests can be completed.
8. `request.legal_actions` is generated and used for validation.
9. RandomBot can play complete battles using only `legal_actions`.
10. GreedyDamageBot can play complete battles using only public state.
11. A bot that hangs or repeatedly returns illegal actions cannot deadlock the match; deterministic random fallback continues play.
12. Showdown `[Unavailable choice]` updates are retried without counting as participant invalid attempts.
13. The state tracker uses only that bot's player-visible stream/request data.
14. Exact battle seed, Showdown version/commit where practical, result and runtime fallback/error statistics are logged.
15. Tournament tests are included in normal TypeScript/Mocha verification and pass.

## 28. Implementation order for Codex

Implement Milestone 1 incrementally. Do not try to build the full production tournament in one pass.

Recommended sequence:

1. Add repository integration (`tsconfig`, Mocha path) and skeleton tournament modules.
2. Define public API types.
3. Implement action generation/translation from real Showdown `ChoiceRequest` data; test it independently.
4. Implement a minimal player-stream state tracker sufficient for Team Preview and basic turns.
5. Implement Python JSONL worker and Node supervisor.
6. Implement RandomBot.
7. Implement a minimal `MatchRunner` and get RandomBot vs RandomBot completing end-to-end.
8. Add timeout/invalid retry/fallback supervision and tests.
9. Expand state tracking for the v1 strategic events listed above.
10. Implement GreedyDamageBot.
11. Add information-boundary and deterministic replay tests.
12. Refactor only after the vertical slice works.

After each meaningful step, run the narrow relevant tests plus TypeScript checking. Before declaring Milestone 1 complete, run the repository's appropriate full test/lint commands or clearly report any unrelated upstream failures.

## 29. Design principles to preserve

When implementation choices are ambiguous, prefer these principles:

1. Pokémon Showdown is the authoritative mechanics/legality engine.
2. Never leak information from omniscient/internal battle state to a bot.
3. Participant API simplicity is more important than mirroring Showdown internals.
4. Semantic structured actions are preferred over exposing Showdown command syntax.
5. One stable `choose_action(state)` function handles all phases.
6. `legal_actions` is the public source of truth for valid complete responses.
7. Runtime failures must degrade to deterministic legal fallback rather than hang the tournament.
8. Reproducibility and auditability matter from the first implementation.
9. Keep custom tournament code modular and outside `sim/` whenever possible.
10. Build the smallest working vertical slice before production hardening.
