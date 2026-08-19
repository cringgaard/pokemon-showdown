# Pokémon Showdown Bot Tournament — VGC Bot Harness Design

Status: living implementation specification. Milestones 1, 2A, 2B, 2C, and 3 are complete. This document defines the preserved v1 contracts for battle execution, participant isolation, tournament orchestration, and final-event presentation.

The tournament uses Pokémon Showdown as the authoritative battle simulator. Participant bots receive a stable semantic Python API built only from their player-visible information, while spectators may consume a separate one-way presentation stream.

## 1. Goals

The tournament harness should:

- use Pokémon Showdown as the only authority for battle mechanics, legality, and battle RNG;
- target Gen 9 VGC-style Doubles;
- support bring-6, pick-4 Team Preview with two leads;
- expose a small Python API that does not require participants to understand Showdown protocol syntax;
- expose only player-visible information to each bot;
- run each bot as a persistent Python process for a match;
- support participant code, models, and configuration files;
- validate submissions and teams before a match begins;
- execute participant code in a controlled Docker environment by default;
- detect malformed, illegal, hanging, or repeatedly-invalid bots and continue using deterministic legal fallback;
- record enough information for deterministic replay, debugging, audit, and spectator presentation;
- provide a visual spectator experience suitable for showing live tournament matches on a shared screen;
- keep the spectator system independent of battle execution so display failures cannot affect match correctness;
- keep custom tournament code outside `sim/` and avoid modifying Showdown battle mechanics.

## 2. Roadmap and scope

### Milestone 1 — core headless harness — COMPLETE

Milestone 1 established:

- real `BattleStream` matches;
- player-specific streams via `getPlayerStreams`;
- semantic bot state/actions;
- complete public `legal_actions`;
- stable team identities;
- Open Team Sheet handling and hidden-information boundaries;
- Team Preview, Doubles targeting, Tera, switching, forced switching, and Revival Blessing;
- persistent Python JSONL workers;
- retries, timeouts, unavailable-choice revisions, and deterministic fallback;
- RandomBot and GreedyDamageBot;
- deterministic/replay-oriented logging and end-to-end tests.

### Milestone 2A — participant submission loading and user-facing CLI — COMPLETE

Implement real participant directories and preflight validation. The immediate goal is that two ordinary submission folders can be validated and run without editing tournament source code.

### Milestone 2B — spectator proof of concept — COMPLETE

Prove that a completed or live harness match can be rendered visually in a browser from the spectator stream/log. The frontend must remain read-only with respect to match execution.

### Milestone 2C — isolated participant execution — COMPLETE

Move participant execution behind a sandbox/container boundary with explicit resource and network policy.

### Milestone 3 — tournament orchestration and polished spectator presentation — COMPLETE

Add scheduling, standings/series handling, crash-resume behavior, aggregate results, and the cafeteria-screen tournament presentation layer.

## 3. Core architecture

```text
                              Tournament / Match Runner
                                       |
                                       v
                                  BattleStream
                                       |
                              getPlayerStreams()
                    _____________/     |      \_____________
                   /                   |                    \
                 p1                    p2             omniscient stream
                  |                     |                    |
                  v                     v                    v
             StateTracker          StateTracker      Spectator Recorder /
                  |                     |             Event Broadcaster
                  v                     v                    |
             StateBuilder          StateBuilder             +----> replay artifact
                  |                     |                    |
                  v                     v                    +----> live browser viewer
            BotState JSON         BotState JSON
                  |                     |
                  v                     v
               BotWorker             BotWorker
                  |                     |
                  v                     v
             BotResponse           BotResponse
                   \                   /
                    v                 v
                 ActionValidator / ActionAdapter
                            |
                            v
                    Showdown choice strings
                            |
                            v
                       BattleStream
```

The information boundary is asymmetric by design:

- **bots** receive only their player-specific stream plus their own current `ChoiceRequest` and public static metadata;
- **spectators** may consume the omniscient/presentation stream according to tournament display policy;
- spectator data must never be routed back into either bot's state or decision process.

The spectator path is an output path only. A disconnected, crashed, or slow viewer must not block or alter battle execution.

For Milestone 2C, each `BotWorker` is created by a prepared generic factory. The safe participant CLI supplies Docker-backed factories; the explicit trusted-development path supplies host Python factories. Docker image preparation and container lifecycle code remain outside `MatchRunner`.

## 4. Showdown integration

Use existing simulator APIs including:

- `BattleStream`;
- `getPlayerStreams`;
- `Teams`;
- `TeamValidator`;
- `Dex`.

Do not expose `Battle`, `Side`, `Pokemon`, or other simulator objects directly to participant bots.

Use explicit battle seeds for reproducibility.

Tournament code must refer to a configurable format ID rather than hardcoding regulation-specific assumptions. The chosen VGC-style format should use forced Open Team Sheets so no human OTS acceptance interaction is required.

Pokémon Showdown remains the final legality authority even though the public harness generates legal semantic actions in advance.

## 5. Participant submission contract

The participant-facing directory shape is:

```text
submission/
├── main.py
├── team.txt
├── requirements.txt        # optional; installed by pip during Docker preparation
└── arbitrary extra files   # models/config/assets
```

ZIP ingestion may be added around this directory contract later. Directory loading is sufficient for Milestone 2A.

Participant code exposes exactly one required function:

```python
def choose_action(state: dict) -> dict:
    ...
```

`main.py` is imported once when the Python worker starts. Module-level initialization/model loading therefore occurs once per worker lifetime.

Participant bots may keep in-process state between decisions. They must not rely on that state for correctness because a timed-out worker may be terminated and restarted.

### 5.1 Submission preflight

Before starting a match, validation must fail fast with human-readable errors for at least:

- missing `main.py`;
- missing or unreadable `team.txt`;
- team import failure;
- wrong team size for the configured tournament contract;
- `TeamValidator` rejection for the configured format;
- malformed participant metadata if/when metadata is introduced.

Use human-readable Pokémon Showdown team export in `team.txt`. Parse with `Teams.import`, pack with Showdown utilities where needed, and validate with `TeamValidator` before the team is sent to `BattleStream`.

Do not silently repair an invalid participant team.

## 6. Public bot API overview

Every invocation receives a JSON-serializable `BotState` in one of three phases:

- `team_preview`;
- `turn`;
- `forced_switch`.

The same `choose_action(state)` function handles all phases.

### 6.1 Stable identities

Own submitted Pokémon receive stable IDs before battle start:

```text
team_0 ... team_5
```

These IDs do not change when Showdown reorders the selected four or Pokémon change active positions.

Open Team Sheet entries receive stable IDs:

```text
opponent_0 ... opponent_5
```

Opponent active identity may remain unknown when public information does not uniquely establish it, especially under Illusion. Never use simulator-hidden identity to resolve it.

## 7. Public API types

The versioned participant contract lives under `tournament/api/types.ts`.

Core concepts include:

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

export interface RuntimeInfo {
    decision_id: number;
    revision: number;
    attempt: number;
    previous_error: string | null;
    deadline_ms: number;
}
```

`deadline_ms` is remaining wall-clock time for the current Showdown decision, not an absolute timestamp.

Own state may expose exact values available from the player's request. Opponent precision must preserve Showdown censorship; never invent exact HP/stats that the player does not know.

Open Team Sheets expose only information public under the chosen format. Do not leak EVs, IVs, hidden exact stats, or other simulator-only information to bots.

## 8. Positions and targets

From player 1's perspective Showdown Doubles positions are conceptually:

```text
p2b p2a
p1a p1b
```

The public API hides numeric Showdown target locations and exposes semantic positions/targets.

For the opponent, protocol slot `b` is visually left and `a` is visually right from the observing player's perspective.

Semantic target translation must continue to match Showdown's target rules. In particular, `normal` may target the adjacent ally while `adjacentFoe` may not.

## 9. Move and slot options

Current move choices are enriched with public static Dex metadata. Disabled moves remain visible in slot metadata with `disabled: true`, but are excluded from `legal_actions`.

A slot request contains:

```ts
export interface SlotRequest {
    required: boolean;
    moves: MoveOption[];
    switches: OwnPokemonID[];
    revives: OwnPokemonID[];
    can_terastallize: boolean;
}
```

The participant API does not expose simulator `pass`. Required simulator passes are represented by omission of that slot's participant action.

Revival Blessing uses a semantic action:

```ts
export interface ReviveAction {
    type: 'revive';
    pokemon: OwnPokemonID;
}
```

The adapter translates it to Showdown's required `switch N` choice syntax.

## 10. Complete legal actions

Every actionable request contains every complete currently legal public response in:

```text
request.legal_actions
```

This is the public source of truth for:

- response validation;
- RandomBot;
- deterministic fallback;
- participant starter bots;
- many harness tests.

Legal action generation must model cross-slot constraints, including duplicate switch targets, one Tera per turn, required/non-required slots, forced implicit passes, and reviving requests.

Showdown remains the final authority and may still reject a provisionally legal response when hidden information becomes newly revealed.

## 11. State tracking and hidden-information boundary

The bot-state pipeline is roughly:

```text
tournament/state/
├── battle-state.ts
├── protocol-parser.ts
├── state-tracker.ts
└── state-builder.ts
```

`state-tracker.ts` maintains observations from that player's stream only. `state-builder.ts` combines those observations, the latest player request, and public static Dex metadata.

The latest own request is authoritative for own-side exact state and current choices. Stable exact own max HP may be cached from previous own requests so a later public `0 fnt` condition does not fabricate max HP.

Boosts/volatiles are battle-temporary. Benched own Pokémon must expose reset boosts/volatiles after switch-out.

Unknown player-visible protocol lines must not crash state tracking; retain them in raw/player history for future support.

The omniscient stream must never be consulted to repair or enrich bot-visible state.

## 12. Runtime protocol and supervision

Use one persistent Python worker per bot per worker lifetime. Node/Python communication uses JSON Lines over stdin/stdout; stdout is reserved for the worker protocol and participant output must be redirected/captured separately. A narrow `BotWorker`/factory boundary supplies either the default prepared Docker worker or an explicitly selected trusted host worker without changing `BotController` decision logic.

Failures must never deadlock a match.

Configuration includes at least:

```yaml
decision_timeout_ms: 5000
max_invalid_attempts: 3
```

Each Showdown decision has a stable `decision_id`. `revision` increments when Showdown updates the current request because hidden information has become newly public. `attempt` increments for participant-invalid responses within the current revision.

The overall decision deadline does not reset on retries or request revisions.

A Showdown `[Unavailable choice]` caused by newly revealed hidden information is not a participant fault. Rebuild the request, increment revision, reset attempt to 1, retain the original deadline, and invoke the bot again.

On deadline expiry or exhausted invalid attempts, select a deterministic random member of the current `legal_actions`. Log every fallback and reason.

A hung worker is terminated; fallback continues the current decision; the worker is restarted before that participant's next decision.

### 12.1 Milestone 2C Docker preparation and runtime policy

Participant-facing CLI matches use Docker by default. `--runtime host` is the only host escape hatch and is explicitly trusted/unsafe; Docker unavailability or build failure never falls back to it. Both participant images are prepared before battle start, and workers are started through the generic runtime boundary before the first Showdown request is issued.

The tournament runtime is generated from the official `python:3.12.13-slim-bookworm` image. Preparation resolves and records its local immutable image ID, then builds a tournament-controlled runtime layer containing the harness `worker.py` and a non-root UID/GID `10001:10001`. Participant images use another tournament-generated Dockerfile and copy every regular submission file into `/submission`. Optional requirements are restricted to exact `name[extras]==version` registry pins, limited to 64 KiB, and installed non-root from `/opt/tournament` with `/usr/local/bin/python -I -m pip --only-binary=:all: --no-deps`. URLs, paths, editable/VCS/source inputs, pip options, markers, constraints, and dependency build hooks are rejected, so preparation does not execute participant-controlled build code. Participant Dockerfiles and symlinks are rejected; apt, raw build flags, secrets, SSH forwarding, privileged entitlements, and arbitrary mounts are not supported. Build networking remains a package-index supply-chain surface, but only wheel retrieval and installation are supported. `main.py` is not invoked by the tournament build definition.

Submission discovery enforces configurable ceilings before a build context is created: 1 GiB total and 10,000 files by default. File contents are streamed into the SHA-256 hash, whose other inputs are the sandbox policy version, resolved tournament runtime image ID, relative paths, modes, and sizes. Images are cached under that hash; matches execute the resolved immutable participant image ID. The artifact records the participant content hash, base/runtime/participant image IDs, Python version, and effective sandbox policy.

Each worker container uses this default policy:

- network mode `none`;
- IPC mode `none`, so Docker does not add a writable `/dev/shm` shared-memory mount;
- read-only root filesystem and only `/tmp` writable as a `64 MiB` `rw,noexec,nosuid,nodev` tmpfs;
- UID/GID `10001:10001`, all capabilities dropped, `no-new-privileges`, Docker's default seccomp/confinement, and Docker's init process;
- `512 MiB` memory with total memory plus swap also limited to `512 MiB`, `1` CPU, `64` PIDs, and `nofile=256:256`;
- no bind mounts, volumes, devices, Docker socket, privileged mode, host namespaces, published ports, or GPU access;
- Docker logging disabled; diagnostics are consumed only through the bounded attached stderr stream;
- participant process environment rebuilt with `env -i` and only `BOT_SEED`, `HOME`, `LANG`, `PATH`, `PYTHONDONTWRITEBYTECODE`, `PYTHONPATH`, `PYTHONUNBUFFERED`, and `TMPDIR`.

Resource settings, submission byte/file ceilings, and the `300000 ms` default build timeout are configurable through typed tournament CLI options; arbitrary Docker flags are never accepted. A unique managed name/label and container ID are tracked for every worker lifetime. Timeout, protocol failure, controller stop, normal completion, and match cleanup kill/remove the actual container rather than relying on the local attached Docker CLI process to terminate descendants. The next decision creates a fresh container while the original deterministic fallback and shared-deadline behavior remain unchanged.

Host-side transport retains at most a `1 MiB` partial JSONL protocol line and `256 KiB` of stderr per worker lifetime. Oversized protocol output terminates that worker; excess stderr is discarded after an explicit truncation marker. These quotas apply to both Docker and trusted host workers.

Docker containers are a practical boundary for an internal competition, not a perfect hostile-kernel boundary. Docker daemon, Linux kernel, base-image, package-index, and malicious prebuilt-wheel compromise or escape are outside this milestone's threat model. Source/dependency build execution is deliberately unsupported. VM/microVM isolation, signed dependency infrastructure, system packages, and GPU policy remain deferred.

## 13. Match runner

`tournament/match/` owns one battle and should:

- receive already-preflighted submissions/teams or invoke the shared preflight layer;
- create `BattleStream` with explicit format and seed;
- create p1/p2 player streams and the spectator/omniscient path;
- start participant runtimes;
- feed only each player's own stream to its tracker;
- invoke bots on requests;
- validate and adapt decisions;
- handle unavailable choices, retries, timeout, and fallback;
- continue through winner/end;
- record audit/runtime artifacts;
- publish spectator events without waiting for a viewer.

The match runner must not access hidden simulator state to help bots.

## 14. Required match artifacts

A completed match should have a self-contained result directory. Exact filenames may evolve, but the conceptual contents are:

```text
match/
├── result.json
├── metadata.json
├── battle.protocol.log
├── p1-runtime.log
├── p2-runtime.log
└── bot-state-snapshots/     # configurable/debug-oriented
```

`battle.protocol.log` is a first-class artifact. It should preserve the ordered spectator/rendering protocol needed to replay the match visually, not merely a human-readable summary.

Artifact schema version 2 adds participant runtime audit policy while preserving the established result/protocol/state files. `metadata.json`/`result.json` should include enough stable data for audit and later tournament aggregation, such as:

- participant identifiers/names;
- format;
- battle seed;
- harness/Showdown version or commit where practical;
- winner/result;
- decision/fallback/timeout/invalid-response statistics;
- artifact schema version.

Artifacts used by the spectator must not become an input to participant decisions.

## 15. Spectator architecture

The tournament will be watched on a shared cafeteria screen. Visual presentation is therefore a first-class product requirement.

### 15.1 Source of spectator truth

The spectator system consumes the omniscient/presentation side of `BattleStream`, never either participant's `BotState`.

This has two purposes:

1. preserve the strict bot information boundary;
2. keep the renderer aligned with Showdown's actual authoritative battle events instead of reconstructing mechanics from normalized bot state.

### 15.2 Live and replay use the same ordered event source

Design one spectator event/log path that supports both:

- **live mode**: ordered battle protocol chunks/events are broadcast to a browser as the match runs;
- **replay mode**: the same stored protocol artifact is fed into the same rendering layer later.

Milestone 2B uses Server-Sent Events because the transport is one-way. A `ProtocolStore` retains the accumulated ordered chunks; a new or refreshed viewer receives history after its last sequence and then continues with newly published chunks. The server disconnects a response that signals backpressure instead of awaiting it. Transport remains uncoupled from simulator timing.

### 15.3 Viewer independence

The browser is read-only. It must not send battle choices or otherwise participate in simulator execution.

The battle must continue correctly if:

- no viewer is connected;
- the browser reloads;
- the network/display transport disconnects;
- rendering is slow;
- the spectator server crashes.

The match runner may buffer/write spectator events, but it must not wait for rendering acknowledgements.

### 15.4 Rendering strategy

Milestone 2B reuses the official client's MIT-licensed replay/animation engine through Pokémon Showdown's hosted `replay-embed.js` third-party entrypoint. The local viewer provides the canonical Showdown protocol in the embed's documented `battle-log-data` boundary and wraps its official `Battle`/`BattleScene` presentation with tournament metadata. No client renderer source is copied into this MIT server repository, and tournament code does not interpret mechanics or draw battle sprites itself. This proof of concept therefore requires network access to the official hosted client assets while loading the viewer.

Custom tournament UI should wrap the battle presentation rather than replace mechanics rendering. Later presentation may include:

- participant/bot names;
- game/series score;
- round/final label;
- turn number;
- team icons/Open Team Sheet presentation;
- next-match/intermission screens;
- winner screen;
- standings/bracket context.

The polished tournament shell is Milestone 3. Milestone 2B only needs to prove a real harness match can be watched visually from beginning to result.

### 15.5 Spectator information policy

Spectator visibility is separate from bot visibility. The tournament may intentionally show more information to spectators than either bot receives, including information available from the omniscient stream or tournament metadata.

This policy must never alter bot inputs. Any later feature that displays bot explanations/debug output must also remain presentation-only and optional.

## 16. Milestone 2A — submission loader and CLI

### 16.1 Acceptance criteria

Milestone 2A is complete when:

1. A participant directory containing `main.py` and `team.txt` can be loaded without tournament-source edits.
2. Team text is imported and validated through Showdown for the configured format before battle start.
3. Invalid submissions fail with actionable human-readable messages.
4. Two valid participant directories can play a complete match through the existing Milestone 1 runtime.
5. A user-facing CLI supports at least validation and direct match execution.
6. Match outputs are written to an explicit result directory using the artifact concepts above.
7. Existing reference bots can be represented through the same submission abstraction or a clearly shared equivalent path.
8. Existing Milestone 1 information-boundary/runtime guarantees remain intact.
9. Tests cover valid and malformed submission fixtures plus end-to-end CLI/match behavior as practical.
10. Full repository verification is run before declaring the milestone complete.

### 16.2 CLI shape

Exact command syntax may follow repository conventions, but the intended UX is approximately:

```bash
node dist/tournament/cli.js validate submissions/alice

node dist/tournament/cli.js match \
  submissions/alice \
  submissions/bob \
  --seed 1234 \
  --output results/alice-vs-bob
```

Do not add tournament scheduling or Docker execution to Milestone 2A.

## 17. Milestone 2B — spectator proof of concept

Milestone 2B is complete when:

1. RandomBot vs GreedyDamageBot (or two participant directories) can be started through the harness.
2. A browser can visually follow the battle from Team Preview/start through the final result using spectator events, without participating in execution.
3. The same completed match can be replayed from its stored `battle.protocol.log` or equivalent ordered spectator artifact.
4. Disconnecting/reloading the viewer does not change battle execution or result.
5. The implementation proves the chosen Showdown-rendering integration path before a polished tournament UI is built.

Do not build standings/brackets or a polished cafeteria shell in this milestone.

## 18. Milestone 2C — isolated execution

Milestone 2C implements the Docker preparation/runtime policy in section 12.1 behind the worker factory boundary. Docker is the participant-facing default; direct host execution remains only as the explicit trusted-development option.

The implemented runtime supports:

- one isolated environment per participant worker/match as appropriate;
- explicit Python version;
- controlled working directory containing the participant submission;
- CPU and memory limits;
- no network by default;
- controlled writable filesystem locations;
- process-tree termination on timeout;
- optional dependency installation from `requirements.txt` under a controlled policy;
- including participant model/config assets in the prepared image without runtime host mounts;
- future GPU policy if explicitly enabled.

The runtime-controller boundary is preserved: `MatchRunner` receives prepared generic worker factories and contains no Docker CLI, image-build, or container-cleanup logic.

## 19. Milestone 3 — tournament orchestration and final event

`TournamentOrchestrator` is a configuration-driven layer above `MatchRunner`. It does not implement battle mechanics, create participant state, or prepare containers. Preflight loads and validates every configured submission, prepares each Docker image when the safe default runtime is selected, and supplies the resulting worker factories to each ordinary `MatchRunner` invocation.

The normalized JSON config is schema version 1. Participant paths resolve relative to the config file and participant IDs are sorted canonically before scheduling. IDs and display names must be unique, timeouts/game counts must be positive, the final has exactly two qualifiers, and `best_of` must be odd. Docker is the default; `runtime: "host"` remains trusted development only. `tournament/tournament.example.json` is the maintained example.

### 19.1 Deterministic schedule and seed derivation

Every unordered participant pair appears once in the round-robin pairing list and plays `games_per_pairing` games. Pairing identity is an unambiguous length-prefixed encoding of the two canonical IDs. Canonically lower participant ID starts as p1; p1/p2 alternate on subsequent games. The final starts with the higher-ranked qualifier as p1 and also alternates sides.

Every Showdown seed is the first four big-endian unsigned 16-bit words of SHA-256 over this exact UTF-8 input:

```text
pokemon-showdown-tournament-v1\0<tournament seed>\0<stage>\0<pairing ID>\0<zero-based game index>
```

The resulting Showdown seed is serialized as `word0,word1,word2,word3`. Wall-clock time, filesystem order, and object iteration order never contribute.

### 19.2 Standings and final tie policy

Round-robin scoring awards 1 point for a win, 0 for a loss, and 0.5 to each participant for a battle tie. Ranking is deterministic:

1. total points;
2. points earned in games among the participants tied on total points;
3. total wins;
4. participant ID in ascending lexical order.

The final is best-of-N and stops when a finalist reaches `floor(N / 2) + 1` wins. A tied battle increments neither finalist's wins and schedules another deterministically seeded, side-alternated game. `final.max_tied_games` is a visible safety limit. If that many final games tie before a majority exists, the higher-ranked qualifier becomes champion with `champion_reason: "tie_safety_limit"`; the tournament never loops or silently exceeds the configured cap.

### 19.3 Durable state and event boundary

The output layout contains `tournament.json`, atomic `state.json`, `event.log.jsonl`, and ordinary per-attempt match directories under `matches/<stage>/<pairing>/<game>/attempt-N/`. State and manifest use schema version 1 and carry the normalized-config SHA-256. A mismatched config fails closed. An in-progress attempt whose ordinary `metadata.json`, `result.json`, and `battle.protocol.log` are complete is adopted on restart; a partial attempt is retained for audit and a new attempt directory is used. Completed games are validated and never rerun.

Tournament presentation events and canonical battle protocol are separate typed event kinds. The durable event store reconstructs the current presentation plus current-game protocol for browser refresh/late join. It is only a `SpectatorSink` to `MatchRunner`; tournament title, stage, standings, series score, and champion metadata never enter `BotState`. Event append/listener/browser failures are failure-isolated output paths.

### 19.4 Presentation and operation

The 16:9 event shell implements idle/title, matchup intro, live battle, result, standings/next-match, and champion states. Live and saved matches use the same official Showdown `replay-embed.js` adapter. The official renderer remains visually dominant and tournament CSS hides developer-oriented logs and controls during presentation.

Manual operation is the default. The localhost `/operator` surface can advance between states, temporarily show standings, and return to the current intro/interstitial. It never pauses an active Showdown battle. `--auto-advance` is provided for tests and rehearsals.

The official hosted embed is retained rather than vendoring the AGPLv3 client and its separately hosted media into this MIT server repository. The embed file itself declares MIT licensing and third-party embedding, but dynamically loads its styles, scripts, data, sprites, and audio from `play.pokemonshowdown.com`. Event preflight fetches the embed, discovers and probes every declared dependency, and fails before tournament play unless the operator explicitly uses `--allow-renderer-unreachable` for a presentation-degraded rehearsal.

## 20. Reference bots and participant documentation

Keep RandomBot and GreedyDamageBot as regression/reference participants.

Before inviting coworkers, add a minimal tutorial submission demonstrating the intended participant experience, for example:

```python
def choose_action(state):
    return state['request']['legal_actions'][0]
```

Participant documentation should explain:

- submission layout;
- `choose_action(state)`;
- `BotState` schema/versioning;
- stable Pokémon IDs;
- Team Preview ordering;
- semantic targets;
- `legal_actions`;
- persistence/restarts;
- timeouts and invalid responses;
- hidden-information guarantees;
- optional dependencies/assets policy.

## 21. Testing strategy

Preserve all Milestone 1 unit/integration coverage and add tests at each new boundary.

### Submission tests

Cover:

- valid directory;
- missing `main.py`;
- missing `team.txt`;
- malformed team export;
- invalid format/team;
- wrong team size;
- arbitrary extra assets do not break loading.

### Match artifact tests

Verify:

- deterministic metadata/result fields;
- spectator protocol artifact is ordered and non-empty;
- participant runtime logs are separated;
- no spectator/omniscient data is serialized into bot state.

### Spectator tests

At minimum:

- a real battle produces a renderable spectator event sequence;
- stored sequence can be replayed;
- viewer absence/disconnection cannot deadlock the battle.

### Runtime/sandbox tests

Retain timeout/exception/invalid/unavailable-choice tests and cover generated build policy, actual container inspection, filesystem/network/environment isolation, arbitrary assets, dependencies, timeout/restart/cleanup, output abuse, and a Docker-vs-Docker match. Docker integration tests explicitly skip only when Docker Engine is genuinely unavailable.

## 22. Repository structure

The current structure should remain modular. Expected additions may look like:

```text
tournament/
├── DESIGN.md
├── CODEX_HANDOFF.md          # temporary/session-oriented handoff; may be deleted later
├── api/
├── actions/
├── bots/
├── state/
├── match/
├── submissions/              # loader/validation code, not participant entries
├── spectator/                # recorder/broadcaster/server integration
├── reference-bots/
└── fixtures/

test/tournament/
├── ...existing milestone-1 tests...
├── submissions.js
├── spectator.js
└── sandbox.js                # Docker integration skips only when Engine is unavailable
```

Exact filenames may change where repository conventions suggest a cleaner organization.

## 23. Implementation order for the next Codex sessions

Do not implement all remaining milestones in one pass.

### Completed session: Milestone 2A

1. Re-read this document and inspect the merged Milestone 1 implementation/tests before changing architecture.
2. Add a submission abstraction/loader for participant directories.
3. Add team import + configured-format validation and actionable diagnostics.
4. Route reference bots through the same submission abstraction where sensible without unnecessary churn.
5. Extend the CLI with `validate` and participant-directory `match` flows.
6. Define/write stable match result/artifact directories, including an ordered `battle.protocol.log` suitable for future rendering.
7. Add focused tests and an end-to-end participant-directory match.
8. Run the tournament-focused tests, TypeScript/lint checks, and full repository verification.
9. Open a focused PR for review.

### Completed session: Milestone 2B

Research the existing Pokémon Showdown client/rendering path first, then implement the smallest browser spectator POC that can consume the saved/live spectator stream. Do not invent a parallel mechanics renderer.

### Completed session: Milestone 2C

Introduced isolated execution behind the runtime abstraction, with Docker as the safe CLI default and explicit trusted host execution only.

### Completed session: Milestone 3

Added deterministic round-robin/final orchestration, durable resume, event preflight/publication, operator pacing, and the polished official-renderer final-event presentation.

## 24. Design principles to preserve

When implementation choices are ambiguous, prefer these principles:

1. Pokémon Showdown is the authoritative mechanics/legality engine.
2. Never leak omniscient/internal battle information to a bot.
3. Spectator data is a one-way output and must never influence match execution.
4. Participant API simplicity is more important than mirroring Showdown internals.
5. Semantic structured actions are preferred over exposing Showdown command syntax.
6. One stable `choose_action(state)` function handles all phases.
7. `legal_actions` is the public source of truth for valid complete participant responses.
8. Runtime failures degrade to deterministic legal fallback rather than hanging the tournament.
9. Reproducibility and auditability matter from the beginning.
10. A renderable ordered spectator protocol is a first-class match artifact.
11. Prefer reuse of Showdown's established battle protocol/rendering concepts over duplicating mechanics for presentation.
12. Keep tournament code modular and outside `sim/` whenever possible.
13. Build and review small vertical slices: submissions, spectator POC, sandboxing, then orchestration/polish.
