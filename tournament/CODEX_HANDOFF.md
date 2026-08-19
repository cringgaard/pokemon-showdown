# Codex Handoff — Milestone 2A: Participant Submissions and CLI

This file is a session handoff for the next implementation pass. `tournament/DESIGN.md` is the authoritative design contract; if this handoff conflicts with it, follow `DESIGN.md`.

## Repository / branch

- Repository: `cringgaard/pokemon-showdown`
- Working branch: `tournament-submissions-v1`
- Base: merged Milestone 1 on `master` (`3c89e19dca5d1278a6d707c060828880250107fb`)
- Milestone 1 PR: #1, merged

Do not restart from the old `tournament-bot-v1` branch.

## First actions

Before changing code:

1. Read `tournament/DESIGN.md` completely.
2. Inspect the existing tournament implementation and tests produced by Milestone 1.
3. Treat the current public bot API/runtime semantics as established contracts unless a concrete bug forces a change.
4. Keep Pokémon Showdown authoritative for mechanics and team legality.

## Task

Implement **Milestone 2A only**: real participant submission loading, preflight validation, CLI flows, and stable match artifact output.

The user should be able to place two participant directories on disk and run a complete match without editing tournament source code.

Target submission shape:

```text
submission/
├── main.py
├── team.txt
├── requirements.txt        # optional, do not install yet
└── arbitrary extra files
```

Participant entrypoint remains:

```python
def choose_action(state: dict) -> dict:
    ...
```

## Required behavior

### Submission loading / validation

Add a reusable submission abstraction/loader that:

- accepts a participant directory;
- verifies `main.py` exists;
- verifies `team.txt` exists and is readable;
- imports the human-readable Showdown team with `Teams.import`;
- enforces the tournament's expected team size;
- validates the team with `TeamValidator` for the configured format;
- produces actionable human-readable validation errors;
- allows arbitrary additional files without interpreting them;
- detects optional `requirements.txt` but does **not** install dependencies yet.

Do not silently repair invalid teams.

### Match integration

Adapt the existing match/CLI path so two valid participant directories can play through the existing Milestone 1 Python runtime.

Preserve all existing guarantees:

- each bot state comes only from its player-specific stream + own request + public static metadata;
- omniscient data never enters `BotState`;
- `legal_actions` remains the participant source of truth;
- timeout/retry/unavailable-choice/fallback behavior remains unchanged;
- Showdown remains the final legality authority.

### CLI

Provide user-facing flows approximately equivalent to:

```bash
node dist/tournament/cli.js validate submissions/alice

node dist/tournament/cli.js match \
  submissions/alice \
  submissions/bob \
  --seed 1234 \
  --output results/alice-vs-bob
```

Exact argument parsing may follow repository conventions. Error output should be useful to a coworker preparing a submission.

### Match artifacts

Write a self-contained result directory. Exact filenames/schema details may evolve, but it should contain the concepts specified in `DESIGN.md`, including:

```text
match/
├── result.json
├── metadata.json
├── battle.protocol.log
├── p1-runtime.log
├── p2-runtime.log
└── bot-state-snapshots/     # optional/configurable if existing behavior already supports it
```

`battle.protocol.log` is important: preserve an ordered spectator/rendering stream from the omniscient path so Milestone 2B can render completed/live matches visually without reconstructing mechanics from BotState.

Do **not** implement the browser spectator frontend in this milestone. Just make the match output/rendering boundary clean.

## Explicitly out of scope

Do not implement in this PR:

- Docker/container sandboxing;
- `requirements.txt` installation;
- network/resource isolation;
- tournament round-robin/bracket scheduling;
- standings;
- polished spectator UI;
- WebSocket/SSE spectator server unless a tiny internal abstraction is strictly necessary for artifact recording;
- new battle mechanics;
- broad refactors unrelated to Milestone 2A.

## Tests

Add focused tests for at least:

- valid participant directory;
- missing `main.py`;
- missing `team.txt`;
- malformed team export;
- team rejected by the configured format;
- wrong team size;
- extra participant assets do not break loading;
- two participant directories complete an end-to-end match;
- expected result/artifact files are produced;
- `battle.protocol.log` is non-empty and ordered/useful for later rendering;
- existing hidden-information/runtime tests still pass.

Use real Showdown validation rather than duplicating legality rules.

## Validation before completion

Run:

1. narrow tournament tests while iterating;
2. TypeScript checking;
3. applicable lint checks;
4. the repository's full verification/test command before declaring the work complete.

Report exact results in the PR body. Do not leave stale Milestone 1 test counts there.

## Delivery

Commit the implementation to `tournament-submissions-v1` and keep/open a focused draft PR against `master` titled along the lines of:

> Implement tournament participant submissions milestone 2A

In the PR description, summarize:

- submission contract;
- validation behavior;
- CLI usage;
- artifact layout;
- tests/validation run;
- explicitly deferred Milestone 2B spectator frontend and Milestone 2C sandboxing.

Do not merge automatically. Stop with the PR ready for review.
