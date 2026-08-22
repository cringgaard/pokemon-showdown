- always returns legal responses;
- no crashes;
- no timeout;
- same seed/config gives deterministic behavior;
- trace emitted each turn.

Initial smoke tests do not require a particular win rate.

---

# 129. Historical battle use

The manual battle set is excellent for finding tactical/mechanical failure modes but poor for estimating optimal numeric weights because it is:

- small;
- non-random;
- played by one human;
- against changing opponents;
- based on several team versions;
- ladder-sample dependent.

Use it to derive:

- invariants;
- semantic features;
- regression positions.

Do not infer precise optimal weights from win counts.

Current-team battles should drive current preview/role tests. Legacy Incineroar/Sinistcha games may still contribute generic mechanic/strategy lessons but must not be used to test current-six selection.

---

# 130. Failure classification during bot testing

Classify strange/lost games before changing the policy:

```text
STATE_ERROR
MECHANICS_ERROR
THREAT_ERROR
OPPONENT_MODEL_ERROR
PROJECTION_ERROR
FEATURE_MISSING
WEIGHT_ERROR
PREVIEW_ERROR
VARIANCE
NO_REASONABLE_POLICY_SOLUTION
```

Examples:

```text
Body Press believed to hit Ghost
→ MECHANICS_ERROR

Ghost immunity known but switch never generated
→ OPPONENT_MODEL_ERROR

switch generated but fragile line still overvalued
→ WEIGHT_ERROR / robustness issue

two very unlikely events decide game
→ likely VARIANCE
```

Every systematic failure should become a minimal regression test before or alongside the fix.

---

# 131. Workstream B implementation phases

Do not ask Codex to implement the entire policy in one change.

## B1 — foundations

Implement:

- policy package/module;
- configuration schema;
- feature registry;
- KnowledgeState structure;
- decision-trace schema;
- canonical action keys.

Acceptance:

- deterministic state transformation;
- config validation;
- trace serialization.

## B2 — mechanics integration

Consume the format-correct output of Workstream A.

Implement:

- static mechanics access;
- type effectiveness/immunity;
- form data;
- move metadata;
- current-team semantic mechanics.

Acceptance:

- P0 mechanics tests pass.

## B3 — knowledge reconstruction

Implement:

- selected-four tracking;
- Protect history;
- switch chronology;
- Fake Out eligibility;
- move/target history;
- damage observations;
- weather source/history;
- timed conditions;
- basic speed observations.

Acceptance:

- knowledge regressions pass.

## B4 — baseline threats and runtime strategy

Implement:

- coarse damage bands;
- KO confidence;
- spread/control/setup threats;
- Glaceon viability;
- Aggron viability;
- tactical offense viability;
- resource valuation.

Acceptance:

- strategy regressions pass.

## B5 — Team Preview

Implement:

- roster tags;
- lead hypotheses;
- all legal preview candidate scoring;
- Bring-4 composition;
- lead/backline scoring;
- preview win-condition vector.

Acceptance:

- preview matrix passes.

## B6 — opponent response model

Implement:

- individual action ranking;
- archetypes;
- selected-four-aware switch candidates;
- Protect/setup/weather/immunity pivots;
- double targets;
- response weighting.

Acceptance:

- P0/P1 response tests pass.

## B7 — shallow projection

Implement only required tactical semantics:

- switches;
- entry effects;
- transformation;
- priority/approximate ordering;
- Protect;
- Wide Guard;
- Follow Me;
- Ally Switch;
- damage bands;
- major boost/status changes;
- weather/field changes.

Acceptance:

- projection regressions pass.

## B8 — feature scoring

Implement numeric feature extraction and named weights.

Acceptance:

- traces show expected feature contributions;
- relative policy tests begin to pass.

## B9 — robust aggregation and strong tactical adjustments

Implement:

- weighted expected utility;
- credible bad case;
- robustness term;
- tactical rule adjustments;
- deterministic tie-breaking.

Acceptance:

- all golden P0 decisions pass.

## B10 — full battles

Run against reference bots and self-play.

Collect:

- win/loss;
- turn count;
- preview choices;
- win-condition trajectory;
- score margins;
- feature contributions;
- uncertain mechanics;
- latency/timeouts.

Do not immediately optimize for win rate before classifying failure types.

## B11 — expand historical regression suite

Encode remaining P0 then P1 manual positions as the implementation stabilizes.

---

# 132. Minimal first playable slice

Do not wait for every sophisticated feature before battle-testing.

A minimal playable heuristic bot may contain:

- KnowledgeState;
- basic mechanics;
- basic threat analysis;
- Glaceon/Aggron importance;
- resource loss;
- damage/KO scoring;
- Protect;
- Follow Me;
- Wide Guard;
- basic switching;
- four response archetypes;
- deterministic ranking.

Then progressively add:

- Mud-Slap sophistication;
- Encore sophistication;
- Ally Switch;
- weather-switch prediction;
- empirical damage;
- richer switch modelling;
- history weighting.

This enables fast empirical feedback without sacrificing architecture.

---

# 133. Computational budget

Typical turn scale is expected to be roughly:

```text
20–100 own legal joint actions
×
4–8 opponent responses
=
80–800 shallow evaluations
```

This should be manageable in deterministic Python if projection remains lightweight.

Trace:

- candidate count;
- response count;
- evaluation count;
- total decision time.

Optimize only when measurements show a problem.

---

# 134. Caching

Useful caches:

- format mechanics;
- type effectiveness;
- move metadata;
- baseline damage bands;
- opponent response set;
- current win-condition vector;
- current resource values.

Do not rebuild KnowledgeState separately for each candidate.

---

# 135. Policy versioning and future experiments

The deterministic architecture is intentionally designed to support later variants.

## v1

```text
handcrafted features
handcrafted weights
```

## v2

```text
handcrafted features
optimized weights via self-play / RL / black-box optimization
```

## v3

```text
handcrafted + learned features
learned value/policy components
```

## later

Potential sequence/transformer or LLM policy using the same public state and evaluation harness.

---

# 136. Weight-optimization boundary

A future learned-weight experiment should preferably optimize:

- feature weights;
- risk coefficients;
- a limited number of thresholds.

It should keep fixed:

- legal actions;
- public information model;
- mechanics;
