# Deterministic snow policy

This package is the public-information deterministic policy for the Champions snow team. It consumes only `BotState.schema_version == 2`, the harness-supplied legal actions, public battle history/Open Team Sheets, and a generated format-aware mechanics snapshot. It never imports Pokemon Showdown's Python-inaccessible simulator or receives the omniscient battle stream.

B10 exposes the participant-facing `choose_action(state)` entrypoint while preserving the phase boundaries developed in B1-B9. B11 adds a historical strategic regression layer around that policy without changing runtime policy semantics.

## Dependency graph

Normal turns follow one direction only:

```text
BotState + generated mechanics
        ↓
B3 public knowledge
        ↓
B4 baseline threats
        ↓
B4 runtime strategy + resource values
        ↓
B6 candidate-independent opponent responses
        ↓
B7 candidate × response shallow projection
        ↓
B8 semantic feature vectors + per-response utility
        ↓
B9 robust cross-response aggregation + tactical adjustments
        ↓
B10 selected harness-legal BotResponse
```

Opponent response generation never receives the candidate action being evaluated. B8's feature vector remains a separate, versioned representation from its hand-tuned scorer, so later learned weights/models can consume the same feature contract.

## Modules

- `knowledge.py` / `reconstruction.py` — public-information foundation and temporal reconstruction: identities/provenance, selected-four state, Protect history, switches, damage evidence, Speed evidence, weather/timed conditions and Fake Out eligibility.
- `mechanics.py` — immutable consumer for the hash-verified Champions mechanics artifact generated from `Dex.forFormat('gen9championsvgc2026regmb')`.
- `threats.py` — strategy-independent public move/threat descriptions and intentionally coarse damage/KO bands.
- `strategy.py` — continuous `GLACEON_FORTRESS`, `AGGRON_FORTRESS` and `TACTICAL_OFFENSE` scores plus nonlinear strategic resource values.
- `preview.py` — B5 OTS-only Team Preview. It scores every one of the 360 harness-provided ordered Bring-4 actions; it never invents a preview candidate.
- `responses.py` — B6 OTS-only, candidate-independent opponent move/switch response set.
- `projection.py` — B7 bounded shallow turn projection with explicit uncertainty branches.
- `features.py` / `scoring.py` — B8 stable semantic features and swappable per-response scorer.
- `aggregation.py` — B9 expected/credible-bad-case aggregation, cross-response robustness/fragility, tactical score adjustments and deterministic ranking.
- `policy.py` — B10 request routing, runtime degradation, full turn orchestration, forced replacement selection, traces and `choose_action(state)`.
- `orchestration_config.py` — strict versioned B10 response-budget and forced-replacement preference parameters.
- `participant.py` — worker-loadable participant wrapper; it avoids trace construction unless stderr tracing is explicitly enabled.
- `actions.py` — stable IDs for actions already supplied by `request.legal_actions`; it never generates legality.
- `config.py` — named thresholds/strategy/runtime/response parameters shared by earlier policy layers.
- `trace.py` — structured decision traces for experiments/regressions; traces are not part of `BotResponse`.

## B10 request routing

`SnowPolicy.decide(state)` is the testable policy API. It returns a `PolicyDecision` containing the exact public response, selected canonical action ID, request phase, runtime mode and optional trace. `SnowPolicy.choose_action(state)` and package-level `choose_action(state)` return only the `BotResponse` required by the tournament worker.

Requests are routed by public phase:

```text
team_preview  → B5 assess_team_preview
turn          → B3/B4 → one B6 set → every legal candidate through B7/B8 → B9
forced_switch → deterministic public replacement scorer over legal actions only
```

Forced replacement is intentionally separate from B6/B7 because Showdown is not asking both sides for a simultaneous ordinary turn. The replacement selector uses current public resource values, primary-plan roles, public OTS attack typing, weather-reset value and simple pair synergy, but it still chooses exclusively from `request.legal_actions`. Its numeric preferences live in the exported `OrchestrationConfig` rather than being hidden in orchestration control flow.

## Runtime modes

`state.runtime.deadline_ms` is the remaining decision budget supplied by the tournament controller. B10 chooses a mode from the existing `PolicyConfig.runtime` thresholds. The degraded response caps are named/versioned in `OrchestrationConfig`:

- `FULL`: normal configured B6 caps (currently up to 4 individual actions per opponent and 8 joint responses).
- `MEDIUM`: at most 3 individual actions and 4 joint responses.
- `LOW`: at most 2 individual actions and 3 joint responses.
- `EMERGENCY`: 1 individual action per opponent and at most 2 joint responses.

All modes remain deterministic and return a harness-legal action. The outer tournament `BotController` still owns the hard process timeout, invalid-response retry and deterministic infrastructure fallback; that fallback is not the intended normal low-time policy.

## B5/B6 OTS scope

The target tournament accepts Open Team Sheets. B5/B6 therefore fail closed rather than guessing hidden movesets. B5 requires all six OTS roster entries and all 360 ordered Bring-4 legal actions. B6 requires a normal `turn`, an explicit `showteam` event, OTS-backed moves/abilities, and established identities for active opponents.

Opponent switches are retained only from publicly possible/confirmed selected bench members. Important semantic pivot motives include Ghost into Body Press, Lightning Rod into Electric pressure, weather reset, Flash Fire, resistance and offensive positioning.

## B7 projection scope

B7 resolves only strategically material ordering/effects: voluntary switches, entry weather/field effects, transformation, priority/approximate Speed, Protect/Wide Guard/Follow Me/Ally Switch, primary effects, coarse damage/KO, deterministic boosts/status/control and coarse end-of-turn effects.

It represents relevant uncertainty explicitly instead of becoming a second Showdown simulator. Current-team mechanics with dedicated coverage include Mega Aggron sequencing, Sturdy/Focus Sash survival, Body Press, Heavy Slam, Grass Knot, Freeze-Dry, Blizzard-in-snow, Aurora Veil weather requirements, Wish, Follow Me, Wide Guard, Ally Switch, Snow Cloak/Bright Powder, Friend Guard, Filter, Flash Fire, Dry Skin, typed resist berries and Lightning Rod.

## B8 feature/training boundary

B8 feature vectors are versioned independently of the scorer. Features are semantic and mostly team-independent (`OPPONENT_DAMAGE`, `DETERMINISTIC_PROTECTION`, `PRIMARY_WINCON_SURVIVAL`, `RNG_DEPENDENCE`, `CONTROL_GAIN`, etc.). Team-specific strategic knowledge enters through resource/plan context rather than features such as `SAVE_AGGRON`.

That separation is deliberate: later experiments can replace the current hand linear weights with learned linear weights, ranking models, boosted models or neural utility models while keeping B3-B7 fixed and using the same legally available inputs.

## B9 aggregation boundary

B9 combines B8 utilities across the shared B6 response distribution. The initial robust score uses expected utility plus a credible bad case, then candidate-level robustness/fragility and strong post-projection tactical adjustments. Rare responses below the credibility threshold still contribute to expectation/variance but cannot become the policy-driving bad case or fire tactical rules.

The tactical layer adjusts scores; it does not bypass projection or generate moves. Current rules include Follow Me rescue, obvious lethal Glaceon conversion, cash-out, failed weather-dependent Veil, stat-drop ability punishment, genuinely zero-effect attacks and base-Aggron danger when Mega is legally available.

## B11 historical regression boundary

B11 treats the manually analysed ladder games as a source of strategic invariants and failure modes, not as a dataset for fitting the current numeric weights. Historical tests therefore prefer relational assertions such as “Protect ranks above another Calm Mind under lethal focus” or “Freeze-Dry ranks above Aurora Veil into a Pelipper reset” instead of pinning exact utility values.

The dedicated `test_b11_historical_regressions.py` suite runs public B3 knowledge and B4 strategy, then evaluates the historical decision fork through B7 projection, B8 semantic features/utility and B9 robust ranking. The opponent responses in these tests are explicit public-information fixtures representing the particular read being preserved. B6 has its own candidate-independent generation tests; historical regressions do not force B6's search heuristics to reproduce one exact response-set composition before they can protect a downstream strategic lesson.

The initial B11 catalogue protects these current-team behaviors:

- fresh Fake Out acts before Follow Me, so deterministic protection can beat relying on redirection;
- an established boosted Glaceon protects under lethal focus rather than greedily adding setup;
- boosted Glaceon cashes out Blizzard when both opponents are already in reliable KO range;
- Freeze-Dry punishes the Pelipper slot when a weather reset would make Aurora Veil fail;
- publicly known Defiant, Competitive or Contrary makes a surviving Mud-Slap target strategically dangerous;
- a 1 HP Heliolisk can retain enough future pivot value to justify Protect under a predicted double target;
- Ninetales weather reset plus partner Protect can improve a rain position;
- Wide Guard plus partner Protect can hedge spread pressure against a credible single-target adaptation.

Historical fixtures must remain mechanically possible. For example, Fake Out cases include public switch chronology that makes B3 itself mark the user as fresh; a manually injected response is not allowed to bypass the knowledge model and create a false-green test.

Because B11 currently adds tests and documentation rather than changing runtime semantics, the production policy/version identifiers remain at B10. A future behavior change discovered by a historical regression should receive its own named feature/rule/configuration change and corresponding version update rather than being hidden in the test fixture.

## Mechanics artifact and participant packaging

Showdown remains authoritative. Generate the mechanics artifact from the exact tournament checkout after compilation:

```sh
node dist/tournament/mechanics/champions-snapshot.js \
  tournament/policies/deterministic_snow/champions-mechanics.json
```

The Python consumer verifies the embedded SHA-256 hash before accepting it. The snapshot contains format/mod identity, type chart, species/forms, moves/items/abilities and narrowly regression-backed semantic annotations for callback-driven mechanics.

`policy.py` looks for the artifact beside the package by default. `DETERMINISTIC_SNOW_MECHANICS_PATH` can override that location, which is useful for development/tests. The persistent worker imports mechanics once when the first decision is evaluated and reuses the immutable `SnowPolicy`; battle correctness itself is reconstructed from each public state/history rather than hidden mutable policy memory.

Inside this repository, `tournament/policies/deterministic_snow/participant.py` can be passed to the generic Python worker. A standalone submission can use an equivalent root `main.py` wrapper and package the policy plus generated mechanics JSON.

Set `DETERMINISTIC_SNOW_TRACE_STDERR=1` to enable TOP_CANDIDATES trace construction and emit those structured traces to stderr. With the variable unset, the production participant uses `TraceLevel.NONE` so normal decisions do not pay trace-construction cost. Stdout remains reserved for the worker JSONL protocol.
