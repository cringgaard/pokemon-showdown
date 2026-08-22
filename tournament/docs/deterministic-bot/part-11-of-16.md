        knowledge,
        mechanical,
    )

    strategy = evaluate_runtime_win_conditions(
        knowledge,
        mechanical,
        baseline_threats,
    )

    resources = calculate_resource_values(
        knowledge,
        strategy,
    )

    responses = generate_opponent_responses(
        knowledge,
        mechanical,
        baseline_threats,
        strategy,
    )

    candidates = annotate_legal_actions(
        state["request"]["legal_actions"],
        knowledge,
        mechanics,
    )

    scored = []

    for action in candidates:
        per_response = []

        for response in responses:
            projected = project_turn(
                knowledge,
                mechanical,
                action,
                response,
            )

            features = extract_outcome_features(
                knowledge,
                strategy,
                resources,
                action,
                response,
                projected,
            )

            utility = score_features(features)

            per_response.append(
                ResponseEvaluation(
                    response=response,
                    projected=projected,
                    features=features,
                    utility=utility,
                )
            )

        aggregate = aggregate_responses(per_response)

        adjusted = apply_tactical_rules(
            action,
            aggregate,
            per_response,
            knowledge,
            strategy,
        )

        scored.append(adjusted)

    return deterministic_best(scored)
```

The exact classes/functions are not prescribed. The dependency structure is.

---

# 108. Pure-function preference

Prefer pure functions for:

- knowledge reconstruction;
- mechanical feature derivation;
- win-condition scoring;
- resource valuation;
- feature extraction;
- response aggregation.

Benefits:

- easy unit testing;
- easy regression fixtures;
- easy feature ablation;
- later weight optimization;
- easier debugging.

---

# 109. Configuration philosophy

Configuration contains tunable policy behavior, not Pokémon mechanics.

Good configuration:

- survival weight;
- risk aversion;
- response count;
- setup diminishing-return thresholds;
- preview weights;
- timeout degradation thresholds.

Bad configuration:

- Ghost is immune to Fighting;
- Protect priority;
- Snow Cloak mechanic;
- Mega Aggron typing.

Those belong to Showdown mechanics.

---

# 110. Configuration layers

Conceptually separate:

```text
policy/
    weights
    thresholds
    response_model
    runtime

mechanics/
    generated format data
    semantic annotations

team/
    roles
    synergy relationships

metadata/
    versions
```

Exact file structure is implementation discretion.

---

# 111. Weight configuration

All scalar utility constants should have named weights.

Conceptual example:

```yaml
weights:
  terminal:
    win: 100000
    loss: -100000

  resources:
    own_resource_loss: -1.0
    opponent_resource_loss: 0.8

  offense:
    damage: 0.4
    opponent_ko: 80

  defense:
    deterministic_protection: 50
    protect_survival: 40
    spread_prevention: 35

  strategy:
    win_condition_progress: 30
    weather_control: 20
    veil: 30

  setup:
    safe_setup: 20
    unsafe_setup: -50
    opponent_setup_allowed: -35

  positioning:
    safe_switch: 15
    weather_pivot: 25
    sacrificial_pivot: 20

  uncertainty:
    rng_dependence: -25
    mechanic_uncertainty: -15
    fragile_prediction: -20
```

These numbers are illustrative starting points only.

Never bury unexplained numeric constants in logic.

---

# 112. Threshold configuration

Keep thresholds separate from utility weights.

Examples:

```yaml
thresholds:
  clear_primary_plan_margin: 15
  credible_response_relative_weight: 0.15
  low_hp: 0.25
  critical_hp: 0.10

  calm_mind_marginal_value:
    stage_0: 1.0
    stage_1: 0.8
    stage_2: 0.4
    stage_3_plus: 0.1
```

A threshold says **when interpretation changes**; a weight says **how much the policy cares**.

---

# 113. Opponent-model configuration

Potential configuration:

```yaml
opponent_model:
  max_individual_actions_per_pokemon: 4
  max_joint_responses: 8

  history:
    same_move_multiplier: 1.10
    same_target_multiplier: 1.10
    repeated_pattern_cap: 1.25

  switching:
    confirmed_selected_multiplier: 1.0
    possible_selected_multiplier: 0.5
    immunity_pivot_bonus: 0.8
    weather_pivot_bonus: 0.7

  protect:
    low_hp_bonus: 0.5
    consecutive_use_penalty: 0.4
```

These are heuristic priors, not calibrated probabilities.

---

# 114. Risk configuration

Potential initial values:

```yaml
risk:
  expected_utility_weight: 0.65
  bad_case_weight: 0.35
  robustness_bonus_weight: 0.10
  credible_response_threshold: 0.15
```

This is an obvious later optimization target.

---

# 115. Runtime/deadline degradation

The public state contains decision timing information.

Use configurable modes such as:

```text
full time budget:
    all legal actions
    ~8 opponent responses
    full optional features

medium:
    all legal actions
    ~4 responses
    reduced optional features

low:
    hard tactical features
    cheap damage
    2–3 response archetypes

emergency:
    immediate survival + KO pressure + strong rules
```

The bot should not timeout because it insists on finishing sophisticated evaluation.

Random fallback should be an infrastructure safety net, not the normal low-time policy.

---

# 116. Team role configuration

Keep team-specific strategic intent separate from generic mechanics.

Conceptually:

```text
Glaceon:
    fortress win condition
    spread special attacker

Ninetales:
    weather control
    Veil support
    Water pressure

Maushold:
    deterministic redirection
    Friend Guard support
    accuracy control

Aggron:
    fortress win condition
    physical wall

Armarouge:
    spread defense
    Fire immunity pivot

Heliolisk:
    Water pressure
    Sash pivot
```

---

# 117. Semantic mechanics annotations

For strategically important behavior not easily represented by static Dex fields, maintain semantic tags such as:

```text
No Guard → accuracy bypass
Lightning Rod → Electric redirection/immunity + SpA boost
Stamina → Defense boost on hit
Wide Guard → spread protection
Follow Me → priority redirection
Freeze-Dry → special Water interaction
```

