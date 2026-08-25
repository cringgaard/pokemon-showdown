# Deterministic Snow v1 evaluation

This directory contains the first post-acceptance evaluation layer for the deterministic snow bot. It is deliberately above `MatchRunner`: evaluation does not change policy decisions or simulate battles separately.

## What a batch records

Every match retains the normal MatchRunner artifacts and an opt-in `snow-decision-traces.jsonl` file. File-backed traces use `FULL` trace level so the raw candidate/response evaluations remain available for later analysis or learned scorers.

The batch root contains:

- `metadata.json` — format, exact Showdown revision, mechanics snapshot hash, profiles and artifact map.
- `summary.json` — W/L/T, win rate, turns, latency and score-margin distributions, strategy-plan counts and selected-feature statistics.
- `decisions.jsonl` — one normalized record per snow decision, including trace versions, response composition, selected response utilities, alternatives, feature contributions, tactical adjustments and uncertainty signals.
- `review-queue.json` — losses, narrow decisions, high-uncertainty decisions, slow decisions and large-margin decisions from losses for manual inspection.
- `champions-mechanics.json` — mechanics snapshot generated from the exact evaluated repository revision.
- `matches/` — full MatchRunner artifacts plus the raw FULL snow traces for every match.

An evaluation fails closed if the snow participant times out, raises, returns invalid output, requires a fallback, hits an unavailable-choice revision, or fails to produce exactly one trace per logical decision.

## Running locally

Build the repository first, then run:

```sh
npm run build
node dist/tournament/evaluation/deterministic-snow-v1-cli.js \
  --output ./snow-evaluation \
  --games-per-side 8 \
  --profiles greedy-mirror,random-mirror
```

The output directory must be empty. The current default profiles use the snow team itself so the baseline comparison isolates policy quality from team quality:

- `greedy-mirror` chooses the highest immediate public damage score.
- `random-mirror` samples from the complete legal-action list.

## Representative opponent benchmark

Baseline mirrors are useful runtime and policy sanity checks, but they are not a representative Champions tuning distribution. The next evaluation layer is documented in [`opponents/README.md`](./opponents/README.md).

It adds separate **historical**, **representative**, and **stress** suites, one reusable configured opponent bot, explicit provenance for reconstructed ladder teams, and `benchmark-summary.json` with raw/weighted performance by suite and archetype.

Run it after building with:

```sh
node dist/tournament/evaluation/opponent-benchmark-cli.js \
  --output ./snow-opponent-benchmark \
  --games-per-side 2 \
  --suites historical,representative,stress
```

The benchmark uses an 8000 ms analytical deadline by default because FULL trace capture is intentionally expensive, but it separately reports decisions whose measured latency exceeds the real 5000 ms tournament budget. This does not change tournament runtime rules.

Do not collapse stress-suite performance into the representative tuning objective. Stress teams exist to expose specific strategic failures; historical/representative weighting should eventually come from observed Champions matchup frequencies.

## Pairing semantics

For each profile and seed the schedule runs the snow bot once as p1 and once as p2 with the same Showdown battle seed. This balances side-dependent simulator effects.

Participant worker RNG is intentionally seeded by MatchRunner with both battle seed and side. Therefore the random reference bot does **not** replay an identical stochastic action trajectory after the side swap. Greedy mirror is deterministic and does not have that qualification.

## GitHub Actions

`Deterministic Snow v1 Evaluation` can be started manually with configurable profile and game-count inputs. It also runs a bounded post-merge acceptance batch when relevant evaluation, snow-policy, team-fixture or reference-bot files change on `master`.

The post-merge default is 6 seeds per side for both baseline profiles: 24 matches total. Normal pull-request CI still runs only the two-match evaluation smoke test.

The representative opponent benchmark has its own manual workflow so larger historical/representative/stress runs are explicit experiments rather than an automatic cost on every policy change.

Full traces can be large. The GitHub Actions workflows upload the complete evaluation directory as an artifact and write their summary JSON into the workflow summary for quick inspection.

## Interpreting the first experiments

Do not tune weights directly from aggregate win rate alone. Start with the generated review queue and stratify at least:

1. losses where the selected action had a large model margin;
2. narrow decisions where alternatives were nearly tied;
3. decisions with high mechanics/RNG/response fragility;
4. win-condition trajectory changes before decisive turns;
5. repeated feature or tactical-rule contributions associated with mistakes.

Any policy change should be converted into an explicit hypothesis and, where appropriate, a historical or synthetic regression before numeric tuning.
