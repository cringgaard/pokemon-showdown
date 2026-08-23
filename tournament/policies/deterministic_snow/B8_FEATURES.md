# B8 semantic outcome feature contract

B8 is the stable interface between public battle reasoning and decision-model preferences.

```text
public BotState
  -> B2/B3 mechanics + knowledge
  -> B4 threats + strategy/resources
  -> B6 candidate-independent opponent response
  -> B7 projected outcome branch
  -> B8 semantic feature vector
  -> swappable scorer/model
```

B8 does **not** aggregate different B6 opponent responses. B7 mechanics branches for one fixed response may be averaged inside one `ResponseUtilityEvaluation`; B9 owns expected/bad-case/variance/robust aggregation across different response hypotheses.

## Versioning

Every raw vector carries:

- `schema_version = 1`;
- `feature_set_version = b8-outcome-features-v1`;
- the B7 branch ID and branch weight;
- every feature in the exact `FEATURE_REGISTRY` order.

Feature IDs, meanings, ranges, and ordering are training-data contracts. If one of those meanings changes incompatibly, create a new feature-set version rather than silently reinterpreting historical vectors.

## Separation of facts and preferences

`extract_outcome_features(...)` does not consume scoring weights. It emits bounded numeric consequences.

`score_feature_vector(...)` separately consumes a `ScoringConfig`. The initial deterministic bot uses `b8-hand-linear-v1`, but a learned model may replace the linear scorer while consuming exactly the same feature vectors.

This enables a progression such as:

```text
hand-tuned linear weights
-> learned linear/ranking weights
-> tree/boosted utility model
-> small neural utility model
```

without modifying the legal-information boundary or B2-B7 mechanics pipeline.

## Generic features

The feature IDs are intentionally not named after the current six Pokemon. Team-specific strategic knowledge enters through B4 plan/resource values and is translated into generic consequences.

For example, a Follow Me line that saves the current Aggron route produces high `DETERMINISTIC_PROTECTION` and `PRIMARY_WINCON_SURVIVAL`; there is no `SAVE_AGGRON` feature.

Current families cover:

- offense: expected opponent damage, threat-weighted KOs, free-turn conversion;
- defense: strategic resource survival, deterministic protection, spread prevention;
- strategy: primary-route survival, diminishing-return setup/recovery progress, weather-control gain;
- positioning: safe switches and sacrificial pivots;
- control: restriction gained and opponent setup actually conceded;
- uncertainty: RNG dependence and unresolved/branch-sensitive mechanics;
- joint coordination: complementary value created by both allied actions.

`FRAGILE_PREDICTION` and `ROBUST_ACROSS_RESPONSES` are intentionally emitted as zero by B8. They require comparison across multiple B6 responses and therefore belong to B9.

## Training records

A future self-play or labelled-decision dataset should retain at minimum:

```text
battle/decision identity
public state / knowledge version
candidate action ID
opponent response ID + plausibility
B7 branch ID + branch weight + confidence
feature schema/version
raw ordered feature vector
scoring/model version
utility / later action ranking
battle outcome or richer training target
```

The raw vector must be retained even when a feature currently has zero hand weight. A future learned model may discover that the feature matters.

## Information boundary

Features may depend only on the same public information available to the tournament participant plus deterministic derived mechanics. They must never use hidden opponent stats, unrevealed selected-four identities, future opponent choices, or simulator-private battle objects.

Keeping training extraction on this same boundary prevents offline models from learning information they could not legally observe at tournament runtime.
