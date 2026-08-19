# Codex Handoff — Milestone 2B: Visual Spectator Viewer

This file is the session handoff for Milestone 2B. `tournament/DESIGN.md` remains the authoritative architecture contract for bot information boundaries, battle execution, runtime semantics, and the spectator output path. Milestone 2A has now been merged; where the roadmap text in `DESIGN.md` still says 2A is next, treat that status label as stale and update it as part of this PR without changing established contracts.

## Repository / branch

- Repository: `cringgaard/pokemon-showdown`
- Working branch: `tournament-spectator-v1`
- Base: merged Milestone 2A on `master` (`c68ed0fceb9e1a2a16f06d3be347609a7405ee90`)
- Milestone 1 PR: #1, merged
- Milestone 2A PR: #2, merged

Do not restart from `tournament-bot-v1` or `tournament-submissions-v1`.

## Goal

Implement **Milestone 2B only**: prove that a real tournament battle can be watched visually in a browser from the authoritative spectator protocol produced by the harness, both as a saved replay and, after that works, as a live read-only stream.

The end-state acceptance demo should be concrete:

> Start a real RandomBot vs GreedyDamageBot (or two ordinary participant submissions), open the spectator page in Chrome on another screen, watch the Doubles battle visually from beginning to result, refresh/reconnect without affecting the match, and later replay the same completed battle from its saved match directory.

This is a proof of concept for the eventual cafeteria-screen tournament presentation. It is **not** the polished tournament dashboard yet.

## First actions — investigate before choosing the frontend architecture

Before implementing the viewer:

1. Read `tournament/DESIGN.md` completely.
2. Inspect the merged Milestone 2A match runner, `battle.protocol.log`, artifact schema, CLI, and tests.
3. Inspect the repository/package structure and existing dependencies before adding any new dependency.
4. Determine where Pokémon Showdown's official browser battle renderer currently lives and how it can be reused cleanly from this project. The server repository may not contain the full web client; do not assume it does.
5. If reuse requires code/assets from the official Pokémon Showdown client project or an official distributable package, inspect its current build/module structure and license compatibility. Prefer a small integration boundary over copying a large client tree into tournament code.
6. Document the chosen rendering integration in the PR summary and, if it materially affects architecture, update the spectator section of `tournament/DESIGN.md`.

**Do not implement a second Pokémon battle simulator or manually reproduce battle mechanics in the browser.** The spectator frontend should consume Showdown protocol and reuse Showdown rendering/protocol concepts as directly as practical.

If the official renderer cannot reasonably be integrated inside the scope of this PR, do not silently fall back to a homemade sprite renderer. Produce the smallest defensible adapter/proof that uses the official client components and explain any remaining integration limitation.

## Architectural invariant

The established information split must remain intact:

```text
                              BattleStream
                                  |
                    getPlayerStreams()
                  /          |          \
                p1           p2       omniscient
                 |             |            |
             BotState       BotState        v
                 |             |      SpectatorPublisher
                 |             |        /           \
                 v             v       v             v
              Bot 1          Bot 2  recorder    live broadcaster
                                         \          /
                                          v        v
                                         browser viewer
```

- Bots continue to receive only their player-specific stream + own request + public static metadata.
- Spectator/replay data comes from the omniscient/presentation stream.
- Bot-state snapshots are debugging artifacts and **must not** be used to render the spectator battle.
- The spectator path is one-way with respect to battle execution.
- No viewer, a disconnected viewer, a slow viewer, or a crashed spectator server must not change battle choices, timing, RNG, or completion.

## Implementation order

Implement the milestone in this order. Do not start with live networking before saved replay rendering works.

### Phase 1 — replay viewer from Milestone 2A artifacts

Create a local spectator command/server capable of opening a completed match directory, approximately:

```bash
node dist/tournament/spectator/server.js results/alice-vs-bob
```

or a clean equivalent integrated into the existing tournament CLI, for example:

```bash
node dist/tournament/cli.js spectate results/alice-vs-bob
```

The server/viewer should load the relevant self-contained artifacts:

```text
match/
├── metadata.json
├── result.json
└── battle.protocol.log
```

The browser must visually replay the battle from `battle.protocol.log`. It must not reconstruct battle mechanics from `result.json`, runtime logs, or bot-state snapshots.

Minimum replay presentation:

- p1 and p2 participant names;
- current turn;
- configured format;
- visual Doubles battlefield;
- Pokémon sprites/positions;
- HP/status presentation;
- switches;
- moves and battle messages;
- damage/healing/fainting;
- weather/terrain/field effects to the extent supported by the official Showdown renderer;
- Terastallization visibly represented;
- final winner/tie state.

Minimum controls:

- play/pause;
- restart from beginning;
- playback speed control if straightforward with the reused renderer (at least 1x; 0.5x/2x are desirable but not worth compromising the integration).

Playback timing is presentation state, not battle authority. Do not modify protocol ordering to simulate animation delays.

### Phase 2 — canonical spectator publication path

Refactor the current omniscient-log collection only as much as necessary so recording and live viewing consume one canonical ordered spectator publication path.

The conceptual shape should be equivalent to:

```text
omniscient BattleStream
          |
          v
   SpectatorPublisher
      /          \
     v            v
ProtocolRecorder  LiveBroadcaster
```

Exact class names are not prescribed. A small `SpectatorSink`/publisher abstraction is reasonable if it fits the codebase.

Required semantics:

- chunks/events are published in exactly authoritative order;
- recording remains sufficient to produce `battle.protocol.log`;
- publishing must not wait for browser rendering acknowledgements;
- broadcaster failures are isolated from match execution;
- existing completed-match artifacts remain stable or are schema-versioned if a real schema change is required.

Do not rewrite the battle runner around the UI.

### Phase 3 — live read-only transport

After replay works, expose the same ordered spectator source to connected browsers during a running match.

Use the simplest transport compatible with the repository and browser runtime. Because this is fundamentally one-way, **Server-Sent Events is a good default if there is no existing WebSocket stack**; WebSocket is also acceptable if existing project/client integration makes it simpler. Do not add a heavy networking framework solely for this POC.

Required live behavior:

1. the match runs correctly with zero connected viewers;
2. a connected viewer receives spectator protocol in authoritative order;
3. a newly connected or refreshed viewer can reconstruct the battle up to the current point and then continue live;
4. viewer disconnect/reconnect does not affect the battle;
5. a slow viewer cannot backpressure simulator execution indefinitely.

The simplest acceptable late-join strategy is:

- retain or read the accumulated ordered spectator protocol so far;
- send/replay that history to the newly connected browser;
- then deliver newly published chunks live.

Do not build snapshot/delta optimization unless actually necessary.

## Replay/live unification

Replay and live mode should feed the **same browser battle rendering adapter**.

Conceptually:

```text
Saved protocol -----------\
                           > SpectatorPlayback -> Showdown renderer -> browser
Live protocol transport --/
```

Avoid two separate rendering implementations.

The rendering adapter may need to distinguish "catch up quickly" from normal-paced presentation, but protocol interpretation must remain identical.

## Spectator information policy

For Milestone 2B, the spectator may consume what is present on the omniscient Showdown stream plus tournament metadata/result information.

The viewer may show more than either bot knows. That is intentional and independent of the bot information boundary.

Do not enrich the viewer from:

- p1/p2 `BotState` snapshots;
- participant internal Python state;
- hidden `Battle` object inspection outside the already-defined spectator stream;
- inferred mechanics that are not expressed by/reliably handled from Showdown protocol.

## Cafeteria-screen considerations for the POC

The final tournament will be watched on a shared screen, so the viewer should be usable fullscreen at normal TV/projector distance, but do not spend this PR on final branding.

A minimal shell around the battle should include:

```text
+---------------------------------------------------------+
| Pokemon Bot Tournament                                  |
| AliceBot                                TensorTyrant    |
|                                                         |
|              [ Showdown battle view ]                   |
|                                                         |
| Turn 7                      Gen 9 VGC ...                |
+---------------------------------------------------------+
```

Prioritize readable participant names and the battle itself. Detailed bracket/series presentation belongs to Milestone 3.

## Suggested repository structure

Do not force this exact layout before inspecting the renderer integration, but keep tournament-specific code modular. A reasonable shape would be:

```text
tournament/
├── spectator/
│   ├── server.ts
│   ├── spectator-publisher.ts
│   ├── protocol-store.ts
│   └── ...
├── spectator-web/
│   ├── index.html
│   ├── spectator.ts
│   ├── styles.css
│   └── showdown-renderer-adapter.ts
└── match/
    └── ...
```

If the official Showdown client build system suggests a cleaner structure, follow that and document why.

## Tests

Add focused automated coverage. At minimum:

### Spectator publication / isolation

- authoritative omniscient chunks are published in order;
- the recorder produces the replay protocol from that path;
- zero viewers does not affect match completion;
- broadcaster/client failure does not fail or block a match;
- p1/p2 bot-state construction remains unchanged and does not consume spectator data.

### Replay loading

Given a known completed match fixture/artifact directory:

- metadata/result/protocol load successfully;
- missing or malformed required artifacts fail with useful errors;
- protocol is delivered to the browser/render adapter in stored order.

### Live transport

- a client receives accumulated history on initial connection;
- later chunks arrive in order;
- reconnect/refresh reconstructs history then continues live;
- disconnect does not affect the underlying match.

### Browser smoke test

Use Playwright or the repository's most appropriate existing browser test tooling if practical. A smoke test should verify behavior rather than pixel-perfect rendering, for example:

1. start spectator server with a fixed completed battle or controlled live match;
2. open the browser page;
3. verify both participant names are visible;
4. verify the battle reaches/represents turn 1;
5. verify the rendered playback reaches the final winner/tie state;
6. if live mode is tested here, reload the page mid-battle and verify it reconstructs/continues.

If integrating the official Showdown renderer makes headless browser setup non-trivial, still provide the strongest automated smoke test practical and document exactly what remains manually verified.

## Manual acceptance test

Before declaring the milestone complete, manually exercise the exact spectator workflow intended for the tournament:

1. run two valid participant/reference submissions through the normal tournament match path;
2. open the spectator page in a normal desktop Chrome browser;
3. watch a complete VGC Doubles battle visually;
4. refresh during a live battle and confirm reconstruction/continuation;
5. finish the match with the viewer disconnected and confirm execution is unaffected;
6. reopen the completed match directory and replay it from the beginning.

Record the exact commands used in the PR body.

## Milestone 2B acceptance criteria

Milestone 2B is complete when all of the following are true:

1. A completed Milestone 2A match can be opened locally and visually replayed in a browser.
2. The browser renderer consumes `battle.protocol.log` / the canonical spectator protocol, not bot-state snapshots.
3. Official Pokémon Showdown battle rendering/protocol components are reused as directly as practical; no second mechanics simulator is introduced.
4. A Gen 9 Doubles match visibly represents active Pokémon positions, switches, moves, HP changes, fainting, and Terastallization.
5. Participant names, current turn, format, and final winner/tie are visible in the spectator shell.
6. Replay can be restarted from the beginning; basic playback control is available.
7. The match runner has a clean one-way spectator publication boundary shared by recording and live delivery.
8. A running match can be viewed live in the browser from that same event source.
9. A browser connecting or refreshing mid-match reconstructs accumulated history and continues live.
10. A match completes correctly with no viewer connected.
11. Viewer disconnect, slow rendering, or broadcaster failure cannot change or deadlock battle execution.
12. Bot hidden-information boundaries and Milestone 1/2A runtime semantics remain unchanged.
13. Automated tests cover ordered publication, replay loading, reconnect/live behavior, and at least a practical browser/render smoke test.
14. Existing tournament tests remain green.
15. The repository's applicable full validation/test command passes, or unrelated upstream failures are reported precisely.
16. `tournament/DESIGN.md` roadmap is updated to mark Milestone 2A complete and Milestone 2B as the current implementation milestone.

## Explicitly out of scope

Do **not** implement in this PR:

- tournament round-robin/bracket scheduling;
- standings or ranking logic;
- best-of-X series orchestration;
- polished cafeteria dashboard/branding;
- automatic next-match/intermission transitions;
- commentator overlays or bot reasoning/explanations;
- music/sound-design work;
- Docker/container sandboxing;
- participant `requirements.txt` installation;
- network/resource isolation for participant code;
- GPU support;
- remote/public deployment;
- authentication;
- multiple simultaneous match dashboards;
- broad refactors unrelated to spectator presentation.

Milestone 2C remains isolated participant execution. Milestone 3 remains tournament orchestration plus polished presentation.

## Validation before completion

During implementation:

1. run narrow spectator/tournament tests while iterating;
2. run TypeScript/build checks;
3. run applicable lint checks;
4. run browser smoke tests;
5. run the repository's full verification command before completion.

Update the PR description with exact results. Do not copy Milestone 2A test counts forward.

## Delivery

Implement on `tournament-spectator-v1` and use a focused PR against `master`, titled approximately:

> Implement tournament spectator viewer milestone 2B

The PR description should include:

- how the official Showdown renderer/client components are integrated;
- replay command and local URL/workflow;
- live-view command/workflow;
- spectator publication/transport design;
- late-join/reconnect behavior;
- proof that spectator failures do not affect match execution;
- automated and manual validation performed;
- screenshots or a short recording if convenient, but do not make visual attachments the only verification;
- explicitly deferred Milestone 2C/Milestone 3 work.

Do not merge automatically. Stop with the PR ready for review.