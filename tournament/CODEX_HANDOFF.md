# Codex Handoff — Milestone 3: Tournament Final Event Experience

This is the implementation handoff for the final major milestone of the Pokemon Showdown Bot Tournament project. Milestones 1, 2A, 2B, and 2C are merged. `tournament/DESIGN.md` remains authoritative for battle mechanics, participant-visible information, action semantics, runtime isolation, match artifacts, and the spectator's one-way information boundary.

## Repository / branch

- Repository: `cringgaard/pokemon-showdown`
- Working branch: `tournament-final-event-v1`
- Base: merged Milestone 2C on `master` (`0cf3f9f09e5caf9be1e136b647ee943ab9a31623`)
- PRs #1, #2, #3, #4 are merged.

Do not restart from an earlier tournament branch.

## Goal

Turn the proven battle platform into something that can actually run and present the workplace tournament/final on a large cafeteria screen.

The result should feel like a small esports event rather than a developer replay page:

```text
participant submissions
        |
        v
TournamentOrchestrator
        |
        +--> deterministic schedule / series / standings / resume
        |
        v
existing MatchRunner + Docker sandbox
        |
        +--> existing artifacts
        |
        v
TournamentEventPublisher
        |
        +--> official Showdown battle protocol / renderer
        +--> event metadata (stage, matchup, score, standings, winner)
        |
        v
16:9 browser presentation on the cafeteria screen
```

Do not reopen the simulator, hidden-information model, action API, sandbox, or battle mechanics unless a concrete regression is discovered.

## Product principles

1. **The official Showdown renderer remains the battle renderer.** Do not build a custom Pokemon battle renderer.
2. **Tournament metadata is separate from battle protocol.** Stage names, scores, standings, transitions, etc. must never be injected into participant state.
3. **The event can be operated without editing code.** Participants, format, seeds, stage settings, and presentation title come from configuration / CLI.
4. **The event is resumable.** A browser refresh, spectator disconnect, or process restart must not destroy completed tournament progress.
5. **Presentation pacing is not simulator pacing.** Protocol ordering stays authoritative; visual transitions may deliberately delay the next game without delaying a battle already in progress.
6. **Do not over-engineer a hosted tournament service.** This is a local/internal event, not Battlefy. No accounts, remote auth, cloud database, Kubernetes, chat, etc.

## First actions — discovery before implementation

Before changing code:

1. Read `tournament/DESIGN.md`, `SUBMISSIONS.md`, `SPECTATOR.md`, the merged spectator implementation, match artifacts, CLI, sandbox runtime, and all tournament tests.
2. Run a current RandomBot vs GreedyDamageBot live spectator match and inspect the browser UX at 1920x1080.
3. Inspect exactly how the current official hosted replay renderer is loaded and what network/runtime dependencies it has.
4. Investigate the official Pokemon Showdown client/replay integration for a robust finals setup. Do **not** casually copy AGPL client code into this MIT server repository. If a locally pinned/served official renderer can be used cleanly with correct licensing/build provenance, document and implement it. Otherwise retain the official hosted renderer but add an explicit event preflight/reachability check and a clear operator warning about the network dependency. Reliability is required; license ambiguity is not acceptable.
5. Inspect whether browser automation already exists in this repository/environment. Prefer a practical real-browser smoke test if available; otherwise retain automated DOM/server tests and perform/document a manual Chrome 1920x1080 acceptance run.

## Part A — tournament configuration

Add a small explicit tournament configuration format. JSON is acceptable and preferable to adding a dependency solely for YAML. A reasonable shape is:

```json
{
  "title": "Pokemon Showdown Bot Tournament",
  "format": "gen9vgc2025regi",
  "seed": "2026",
  "runtime": "docker",
  "decision_timeout_ms": 5000,
  "match_timeout_ms": 60000,
  "participants": [
    {"id": "alice", "name": "Alice", "submission": "submissions/alice"},
    {"id": "bob", "name": "Bob", "submission": "submissions/bob"}
  ],
  "round_robin": {
    "games_per_pairing": 3
  },
  "final": {
    "qualifiers": 2,
    "best_of": 5
  }
}
```

Exact field names may follow repository conventions, but configuration must be schema-validated with actionable errors.

Requirements:

- participant IDs and names unique;
- at least two participants;
- odd `best_of` for elimination/final series;
- positive game counts/timeouts;
- deterministic canonical participant ordering independent of filesystem enumeration;
- safe Docker runtime remains default; explicit host runtime remains trusted/dev only;
- participant preparation/validation happens before tournament play where practical;
- paths resolve consistently relative to the config file, not caller cwd surprises.

Do not expose arbitrary Docker flags here.

## Part B — deterministic tournament orchestration

Create a `TournamentOrchestrator` layer **above** `MatchRunner`.

It should be possible to run something like:

```bash
node dist/tournament/cli.js tournament tournament.json --output results/company-cup --spectator-port 8000
```

### Round robin

Implement a deterministic round-robin schedule for all participants.

- every unordered participant pair meets exactly once as a pairing;
- each pairing runs the configured number of games;
- alternate p1/p2 assignment across games where possible so side assignment is not systematically biased;
- derive every Showdown seed deterministically from tournament seed + stage + pairing identity + game index using a documented stable method;
- never use wall-clock time or array iteration accidents as seed input;
- record pairing/game identity in tournament state and match metadata/event metadata.

### Standings

Keep standings deliberately understandable for coworkers watching the event.

Track at minimum:

- games played;
- wins;
- losses;
- ties;
- points;
- win percentage or equivalent display statistic.

Use a documented deterministic ranking order. A reasonable initial rule is:

1. points;
2. head-to-head points among tied participants where unambiguous;
3. total wins;
4. deterministic participant ID as the final stable tie-break.

If another simple rule is materially cleaner, document it. Never allow nondeterministic ordering.

A battle tie must not crash standings; define its points explicitly (for example 0.5 each).

### Final series

Support a configured final between the top qualifiers (initially top 2 is sufficient even if the schema names `qualifiers`).

- best-of-N with early termination when one participant reaches `floor(N/2)+1` wins;
- deterministic per-game seeds;
- alternate sides between games;
- series score published after each game;
- a Showdown tie does not count as a win toward the majority and must have a defined retry/additional-game policy so the series can always produce a champion;
- do not silently exceed a reasonable safety limit; document the tie policy.

The implementation should not require a general-purpose arbitrary bracket engine in this milestone.

## Part C — durable tournament state and resume

Tournament progress must survive process restart.

Create a schema-versioned tournament state/artifact layout, for example:

```text
results/company-cup/
├── tournament.json          # normalized immutable-ish tournament definition / manifest
├── state.json               # current progress, standings, current/next phase
├── matches/
│   ├── round-robin/...      # normal M2A/M2C match artifacts
│   └── final/...
└── event.log.jsonl          # optional ordered presentation/orchestration events
```

Requirements:

- write state atomically (temp + rename or equivalent);
- never mark a game complete until its ordinary match artifacts are complete;
- on restart, reconstruct/validate completed games rather than rerunning them;
- detect incompatible config/state rather than silently mixing tournaments;
- re-running `tournament ... --output same-dir` resumes by default or has one explicit resume command; no duplicate completed games;
- completed match artifacts remain individually replayable through the existing spectator path;
- simulator protocol logs remain the source of truth for battle playback.

Do not attempt distributed locking or multi-host orchestration.

## Part D — event-state publication

Generalize the spectator boundary into an event publisher without weakening the existing battle path.

Conceptually:

```text
TournamentOrchestrator
       |
       +--> event state: intro / matchup / game / result / standings / champion
       |
MatchRunner
       |
       +--> omniscient battle protocol
       |
       v
TournamentEventStore / Publisher
       |
       +--> history snapshot
       +--> SSE live updates
       v
browser
```

The browser must be able to refresh/late-join and reconstruct the current presentation state plus the current battle from retained history.

Spectator/event delivery failure must remain output-only: it may degrade the screen, but must never change a match result or participant state.

Keep event metadata and Showdown protocol as separate typed event kinds. Do not encode fake Showdown protocol lines for tournament UI.

## Part E — polished 16:9 finals presentation

This is a first-class requirement, not an afterthought.

Design for 1920x1080 / 16:9, viewed from several metres away. It must remain usable on smaller desktop screens, but the cafeteria display is the target.

### Presentation states

Implement a clear state machine with visually distinct screens/transitions:

1. **Idle / event title**
   - tournament title;
   - optional subtitle such as format;
   - ready/next-up information;
   - clean enough to leave on screen before the event begins.

2. **Matchup intro**
   - participant names prominently left/right;
   - stage/round/pairing label;
   - game number and series score when relevant;
   - Open Team Sheet information may be shown in a readable pre-game layout because this format already exposes it. Reuse parsed team data; do not leak anything beyond the tournament's existing OTS/public/omniscient spectator allowance.

3. **Live battle**
   - official Showdown battle renderer is visually dominant;
   - large participant names;
   - stage / game / series score;
   - current turn;
   - compact tournament branding/title;
   - avoid developer/debug clutter;
   - battle log text must not overwhelm the screen;
   - controls hidden/minimal during presentation mode.

4. **Game result**
   - clear winner/tie;
   - updated series score or round-robin result;
   - short intentional interstitial before next state, not an instantaneous jarring reset.

5. **Standings / between-match screen**
   - readable standings table with rank, participant, W/L/T/points;
   - highlight next matchup;
   - suitable for the operator to leave displayed while people talk.

6. **Champion screen**
   - final winner prominently displayed;
   - final series score;
   - tournament title;
   - celebratory but professional; CSS effects are fine, but do not introduce heavy graphics dependencies solely for confetti.

### Visual requirements

- coherent typography and spacing;
- strong hierarchy visible from distance;
- no horizontal/vertical scrollbars at 1920x1080;
- smooth but restrained CSS transitions;
- no flashing/high-frequency effects;
- color contrast appropriate for a projector/TV;
- browser full-screen friendly;
- resize should not destroy the battle renderer;
- long participant names must truncate/wrap gracefully rather than overlap;
- spectator disconnect/reconnect should show a subtle status indication, not replace the battle with a stack trace.

Do not spend this milestone inventing custom Pokemon sprite animations. The official renderer already solves battle presentation.

## Part F — operator controls and pacing

The final event should not require racing the CLI while speaking to the room.

Provide a minimal local operator flow. This may be CLI-driven or a small localhost-only control surface.

At minimum the operator must be able to:

- start/resume the tournament;
- pause **between games** before starting the next game;
- advance from intro/interstitial to the next game;
- display standings;
- return to next-match intro;
- recover the browser by refreshing without losing state.

Do not implement a mechanism that pauses a Showdown battle after it has started unless the existing protocol already safely supports it. Operator pacing belongs between games/states.

If a web control endpoint is used, bind it to localhost by default and keep it separate from public spectator read endpoints. No authentication system is required for this local internal tool.

Provide an `--auto-advance` or equivalent mode for automated tests/demo if manual pacing is the default.

## Part G — event preflight

Add a practical preflight command or startup phase that checks before people are watching:

- config parses and participants validate;
- duplicate IDs/names rejected;
- output directory/state compatibility;
- Docker available when Docker runtime selected;
- participant images can prepare;
- spectator port available;
- official renderer dependency reachable if it remains externally hosted;
- clear warnings for non-fatal presentation dependencies.

A failed renderer/network preflight must not cause tournament logic to run accidentally. Give the operator a clear actionable message.

## Tests

Add focused tests for the new final-event layer while preserving all existing tournament tests.

### Tournament model

- deterministic round-robin schedule for 2, 3, 4+ participants;
- every pair exactly once;
- deterministic side alternation;
- deterministic seed derivation stable across repeated runs;
- standings including ties and stable tie-break ordering;
- best-of final early termination;
- final tie policy terminates deterministically.

### Resume/state

- interrupted tournament resumes without rerunning completed games;
- state/config mismatch fails clearly;
- atomic state path behavior;
- completed match artifacts remain valid/replayable;
- current/next event state reconstructed after restart.

### Spectator/event store

- event history + live continuation;
- reconnect/late join does not duplicate battle protocol;
- event metadata cannot reach participant workers;
- zero spectators does not affect tournament;
- failed spectator sink does not affect tournament.

### UI/server

- each presentation state renders required participant/stage/score/standings fields;
- long names do not break the shell structurally;
- replay and live battle use the same official renderer adapter;
- refresh during a live game reconstructs current battle and shell state;
- champion/result screen reached from real orchestration events.

### End to end

Create a small test tournament with at least four distinct fixture/reference participants in trusted-host mode for speed and verify:

- full round robin completes;
- standings deterministic;
- correct finalists selected;
- best-of final completes;
- champion recorded;
- every game has normal match artifacts;
- a fresh process can reload completed tournament state.

Also retain at least one Docker-backed smoke/acceptance path so final orchestration is proven compatible with the M2C default runtime. Do not make every orchestration unit test build Docker images.

## Manual visual acceptance — required

Before declaring this milestone complete, perform a real Chrome acceptance run at a 1920x1080 viewport.

Use a small configured tournament or a shortened round-robin/final demo and verify visually:

1. idle/title screen;
2. matchup intro;
3. Team Preview;
4. live Doubles battle with official sprites, moves, HP/status, switches, weather/terrain, Tera and fainting;
5. names/stage/game/series score remain readable throughout;
6. result interstitial;
7. standings screen;
8. transition into the next game;
9. final series score updates;
10. champion screen;
11. browser refresh during a live game reconstructs correctly;
12. browser refresh between games reconstructs the correct interstitial/standings state;
13. no scrollbars/overlaps at 1920x1080;
14. spectator/browser failure does not stop the tournament process.

Take screenshots for your own validation / PR description if practical. Do not commit generated screenshots unless they are deliberately useful test fixtures.

## Acceptance criteria

Milestone 3 is complete only when:

1. A config file can define participants and tournament/event settings without code edits.
2. Round-robin pairings and game seeds are deterministic.
3. Standings are deterministic and understandable.
4. The configured final series produces a champion.
5. Tournament progress persists and resumes without replaying completed games.
6. Existing MatchRunner/Docker sandbox remains the actual battle execution path.
7. Every game still produces the ordinary auditable match artifacts.
8. Event metadata remains one-way spectator-only and never reaches bots.
9. Live browser refresh/reconnect reconstructs current event + current battle.
10. Spectator failure cannot affect tournament results.
11. The browser has polished idle, intro, live, result, standings, and champion states.
12. The official Showdown renderer remains the battle renderer.
13. The 1920x1080 manual acceptance demonstrates a presentation suitable for the cafeteria screen.
14. The operator can pace transitions between games without editing code.
15. Preflight catches Docker/config/port/renderer issues before the event begins.
16. Full tournament tests, repository TypeScript/lint/tests, and relevant Docker acceptance remain green.
17. `tournament/DESIGN.md` is updated to mark 2C complete and Milestone 3 current/complete as appropriate.
18. `tournament/SPECTATOR.md` and user-facing tournament documentation contain exact final-event commands.

## Explicitly out of scope

Do not implement unless strictly necessary for acceptance:

- participant accounts or web submission portal;
- public internet hosting/authentication;
- arbitrary bracket editors;
- Swiss scheduling;
- distributed workers;
- cloud database;
- Kubernetes;
- GPU sandboxing;
- chat/commentary system;
- bot-written natural-language explanations;
- custom Pokemon battle animation engine;
- mobile-first UI;
- major changes to battle mechanics or participant API.

## Stop condition

Stop when a clean checkout can, from configuration, preflight and run a small tournament through round robin into a final, survive a restart, produce ordinary per-game artifacts, and present the complete event in Chrome as a polished 16:9 experience from title screen through champion screen.

Update the PR description with the actual architecture, config example, exact commands, deterministic ranking/seed/tie rules, renderer dependency decision, automated test results, Docker acceptance, and manual 1920x1080 visual acceptance. Mark the PR ready for review and stop. Do not merge.