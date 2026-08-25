# Deterministic Snow Opponent Benchmark

This directory defines the first representative opponent benchmark for the deterministic snow v1 policy.

The benchmark deliberately separates three questions:

- **historical** — can the policy handle team compositions that were actually encountered on the Champions ladder?
- **representative** — can it handle broadly useful strategic archetypes that should generalize beyond one recorded team?
- **stress** — does it retain specific strategic/mechanical lessons under deliberately adversarial pressure?

Stress performance is diagnostic. It is not, by itself, a tuning objective. A change that improves stress cases while degrading historical or representative performance should be treated as suspicious.

## Evidence boundary

Historical profiles preserve a real six-species roster from previously reviewed ladder games. Unless a set was fully observed, the benchmark team file reconstructs moves, items and stat points for repeatability. `manifest.json` records this explicitly in `provenance`; reconstructed details must never be presented as observed ladder facts.

Constructed representative and stress profiles are labeled as such.

## Files

- `manifest.json` — profile identity, suite, archetype, weight, tags, provenance and team path.
- `policies.json` — roster-specific tactical preferences for the reusable archetype bot.
- `archetype_bot.py` — one public-state-only bot shared by every benchmark profile.
- `teams/*.txt` — Champions-valid human-readable Showdown exports.

The archetype bot identifies its policy from its own six-species roster. Rosters therefore need to be unique within the policy catalogue.

## Initial catalogue

Historical:

- `historical-rain-archaludon` — rain/weather reset, spread pressure and Fighting coverage.
- `historical-blastoise-incineroar` — Mega pressure, Fake Out, Fighting damage and redirection.
- `historical-gengar-balance` — Ghost pressure, redirection and spread offense.
- `historical-sableye-blaziken` — Fake Out/control, setup and speed-mode interaction.

Representative:

- `representative-trick-room` — Trick Room, redirection and slow offense.
- `representative-spread-offense` — Tailwind, spread damage and Fake Out balance.
- `representative-control-balance` — Fake Out, pivoting, speed control and flexible board states.

Stress:

- `stress-fighting-pressure` — Aggron survival, Follow Me rescue and focus fire.
- `stress-ghost-pivots` — Body Press immunity awareness and Ghost switching/pivots.
- `stress-no-guard-gravity` — explicit accuracy/evasion denial.
- `stress-stat-drop-punish` — Defiant, Competitive and Contrary constraints on Mud-Slap/stat drops.

## Archetype bot contract

`archetype_bot.py` never generates commands. It scores `state.request.legal_actions` and returns one of them exactly.

Its configuration supports:

- preferred Bring-4/lead ordering;
- move-specific tactical weights;
- opponent-species focus weights;
- switch preferences;
- weather-reset bonuses;
- low-HP preservation and Protect incentives;
- spread-move preference;
- transformation preference.

This is intentionally weaker than the deterministic snow policy. The goal is to instantiate repeatable strategic problems, not pretend these benchmark opponents are optimal human players.

Each important archetype behavior should have an acceptance test. Do not add configuration that merely looks plausible without proving that the bot actually produces the intended pressure in a public state.

## Running the benchmark

After `npm run build`:

```bash
node dist/tournament/evaluation/opponent-benchmark-cli.js \
  --output snow-opponent-benchmark \
  --games-per-side 2 \
  --suites historical,representative,stress
```

The default analytical decision timeout is 8000 ms because FULL decision traces are intentionally expensive. This does **not** change the tournament's 5000 ms decision budget. `benchmark-summary.json` reports how many recorded decisions had measured latency above 5000 ms so analytical tracing cannot hide runtime regressions.

Outputs include all normal v1 evaluation artifacts plus `benchmark-summary.json`, which reports raw and weighted results by suite, archetype and individual profile.

## Weighting

Every initial profile has weight `1.0`. These are placeholders, not claims about metagame frequency.

Once enough real Champions matches are collected, representative weights should be estimated from the observed matchup distribution. Keep stress weights conceptually separate from that empirical distribution.

## Adding an opponent

1. Add a six-Pokémon team under `teams/`.
2. Add one manifest entry with explicit suite, archetype, tags, weight and provenance.
3. Add a roster-matching policy entry to `policies.json`.
4. Keep the roster unique so the shared bot can resolve exactly one policy.
5. Ensure the team passes the real Champions team validator.
6. Add a behavioral acceptance test for any new strategic behavior the profile is intended to exercise.
7. Run at least one real paired MatchRunner smoke before treating the profile as benchmark ground truth.

Do not tune the snow policy in the same change that introduces a new benchmark opponent. First establish and validate the benchmark; only then use its evidence to motivate policy changes.
