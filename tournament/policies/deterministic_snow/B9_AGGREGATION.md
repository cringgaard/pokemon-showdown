# B9 robust aggregation and tactical ranking

B9 is the final policy layer before B10 orchestration. It does not generate opponent responses, project turns, or extract B8 features. Instead it consumes already-matched B6/B7/B8 artifacts for each harness-legal candidate.

## Input contract

For every candidate supplied to `rank_candidates()`:

- the candidate must be a canonical legal `turn` action;
- it must have exactly one `CandidateResponseCase` for every response in the supplied `OpponentResponseSet`;
- each case's B7 `candidate_action_id` and `response_key` must match the candidate and B6 response;
- each case's B8 `candidate_action_id` and `response_id` must match the same pair;
- all candidates therefore face the same candidate-independent B6 response distribution.

This preserves the simultaneous-choice dependency rule:

```text
state -> B6 response distribution
state + candidate + response -> B7 projection
projection + strategy/resources -> B8 per-response utility
all B8 response utilities for one candidate -> B9 aggregate
```

## Robust aggregate

B9 normalizes the B6 response weights and records:

- weighted expected utility;
- worst credible response utility;
- best response utility;
- weighted variance and standard deviation.

A response is credible when its normalized weight is at least the configured relative threshold times the largest response weight. The threshold is currently sourced from `PolicyConfig.thresholds.credible_response_relative_weight` (default `0.15`).

The initial aggregate is:

```text
0.65 * expected utility
+ 0.35 * credible bad-case utility
+ 18 * ROBUST_ACROSS_RESPONSES
- 25 * FRAGILE_PREDICTION
```

`FRAGILE_PREDICTION` is the normalized utility standard deviation. `ROBUST_ACROSS_RESPONSES` is the normalized inverse credible-response range. These are candidate-level cross-response features; B8 correctly leaves both at zero because a single response cannot define them.

B9 reconstructs the 0.65/0.35 portion feature-by-feature from the B8 `FeatureContribution` records and appends the two cross-response contributions. This keeps traces interpretable and makes it possible to replace the B8 scorer or B9 aggregation parameters independently.

## Tactical rules

Strong tactical rules run **after** projection and aggregation and contribute additive score adjustments rather than returning actions directly. v1 contains:

- `FOLLOW_ME_RESCUE`
- `OBVIOUS_LETHAL_GLACEON`
- `CASH_OUT`
- `FAILED_WEATHER_DEPENDENT_MOVE`
- `ABILITY_PUNISHMENT`
- `ZERO_EFFECT`
- `BASE_AGGRON_DANGER`

Each adjustment scales with the fraction of credible response/branch mass where its projected condition is actually true. For example, Follow Me receives rescue value only when projected protection preserves the current primary route; Aurora Veil is penalized only when credible projected weather makes it fail.

The rules are deliberately a thin team-policy layer. They do not alter B2 mechanics, B4 strategy facts, the B6 response distribution, B7 outcomes, or B8 raw feature vectors.

## Deterministic ranking

Candidates sort by:

1. final score descending;
2. credible bad-case utility descending;
3. expected utility descending;
4. canonical action ID ascending.

`CandidateRanking.selected_action_id` therefore identifies a deterministic winner, but B9 still does not expose participant `choose_action()`. B10 will orchestrate B2-B9, runtime degradation, Team Preview vs turn dispatch, and trace emission.
