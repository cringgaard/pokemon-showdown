Double-target plausibility rises when one of our Pokémon is a clear win condition or vulnerable to both attackers.

This is central to Protect evaluation.

---

# 66. Switch hypotheses

Candidate switches come from:

```text
confirmed selected + currently benched
+
possible selected unrevealed
```

Never from `CONFIRMED_NOT_SELECTED`.

Switch motivation should include:

- survival gain;
- immunity;
- resistance;
- weather control;
- ability activation;
- avoiding an obvious KO;
- offensive positioning;
- preserving a low-HP strategic resource.

---

# 67. Important switch motives for this team

Strongly model:

- Ghost pivot into Body Press;
- Lightning Rod pivot into Thunderbolt;
- Pelipper/Politoed into snow to reset weather;
- Flash Fire pivot into Fire;
- other known public immunity pivots.

These are tactical concepts, not species-name scripts.

---

# 68. Response history modifiers

History should adjust plausibility modestly.

Example initial modifiers:

```text
same move last turn   ×1.10
same target last turn ×1.10
repeated pattern cap  ~×1.25
```

Never let behavioral history overwhelm a much stronger current tactical response.

---

# 69. Response set independence from our candidate

Both players choose simultaneously.

Therefore:

```text
state → opponent response distribution
```

must be generated **before** evaluating a particular hidden candidate action.

The response generator may know our board, revealed moves, strategic plan and history, but it must not see which candidate action is currently being scored.

Then:

```text
state + our action + opponent response → projected outcome
```

This distinction is mandatory.

---

# 70. Shallow outcome evaluator

The evaluator is not a second simulator.

Its question is:

> Given our candidate joint action and one plausible opponent response, what broad strategic board are we likely to end the turn in?

Output may be coarse and uncertain.

Conceptually:

```python
ProjectedOutcome:
    own_hp_changes
    opponent_hp_changes

    own_faints
    opponent_faints

    boost_changes
    status_changes

    projected_weather
    projected_field_conditions
    projected_positions

    protected_slots
    blocked_actions
    redirected_actions

    unresolved_random_effects
    uncertain_interactions
    confidence
```

---

# 71. Shallow resolution stages

Model only strategically relevant ordering:

```text
initial state
    ↓
voluntary switches
    ↓
known entry effects
    ↓
transformations
    ↓
priority / approximate speed order
    ↓
Protect / Wide Guard / redirection / Ally Switch
    ↓
primary move effects
    ↓
damage bands / KOs
    ↓
major boosts / deterministic statuses
    ↓
weather / field changes
    ↓
coarse end-of-turn effects
    ↓
projected board
```

When order is uncertain and tactically important, branch across plausible orderings rather than inventing an exact Speed.

---

# 72. Entry effects

Model strategically relevant entry effects such as:

- Snow Warning;
- Drizzle;
- Drought;
- Sand Stream;
- Electric Surge;
- Intimidate where relevant;
- other entry effects later proven important.

Unknown entry effects may remain unmodelled/uncertain until they matter.

---

# 73. Transformation stage

Use whatever semantic transformation action/state Workstream A establishes.

After a transformation, update projected:

- form;
- typing;
- stats relevant to coarse evaluation;
- ability;
- transformation availability.

Do not build the policy around Tera-specific field names.

---

# 74. Move ordering

The evaluator only needs enough fidelity to answer questions such as:

- Fake Out before Follow Me;
- Protect before ordinary attacks;
- whether an attacker KOs Aggron before Body Press;
- whether a weather switch occurs before Aurora Veil;
- whether Glaceon moves before a threat.

Use format-aware priority metadata, speed relations, Tailwind, Trick Room and known modifiers.

Do not recreate Showdown's entire BattleQueue.

---

# 75. Protective effects

## Protect

Project eligible incoming effects as blocked if Protect succeeds. Consecutive Protect should carry reduced reliability rather than deterministic failure.

## Wide Guard

Project known spread moves as blocked and single-target moves as unaffected.

## Follow Me

Redirect eligible single-target moves to Maushold. Do not redirect spread moves or known redirection-immune cases.

## Ally Switch

Project semantic slot switching before eligible single-target attacks. Value depends on the attack target and resulting immunity/resistance. Consecutive use receives a strategic penalty.

---

# 76. Damage evaluation tiers

## Tier 1 — empirical

Use comparable observed damage when available.

## Tier 2 — Showdown-backed helper

If Codex finds a clean public-state-only path to exact/near-exact damage using Showdown mechanics, it may be used.

Do not make this a prerequisite for v1.

`BattleActions.getDamage()` is deeply coupled to a `Battle` and its event system; blindly importing it would pull the policy toward reconstructing a full hypothetical battle.

## Tier 3 — coarse estimate

Use format-correct data and public state to classify:

```text
NEGLIGIBLE
LIGHT
MODERATE
HEAVY
LIKELY_KO
```

For many tactical decisions this is sufficient.

---

# 77. Special move semantics requiring higher fidelity

Current-team examples include:

- Body Press uses Defense;
- Heavy Slam uses relative weight;
- Grass Knot uses target weight;
- Freeze-Dry has special Water interaction;
- Blizzard is spread and snow-accurate;
- Wish resolves later;
- Encore affects future action availability.

Source static values such as weights/forms from Showdown data rather than maintaining a separate handwritten database.

---

# 78. Accuracy and evasion

Accuracy/evasion should modify expected value, not become a hard safety guarantee.

For ordinary 100%-accurate moves into Glaceon in snow, the expected manual model was roughly:

```text
Snow Cloak × Bright Powder ≈ 0.8 × 0.9 = 0.72 hit probability
```

This exact behavior must be verified against the target Champions implementation.

After one Mud-Slap accuracy drop, the effective hit chance can fall substantially further.

The policy should distinguish:

```text
exploit evasion
```

from:

```text
require an unlikely miss to avoid losing
```

The latter receives an `RNG_DEPENDENCE` risk penalty.

No Guard and Gravity must modify this reasoning according to actual Champions mechanics.

---

# 79. Random secondary effects

