
    field
    timed_conditions

    pokemon_timelines
    move_usage
    target_history
    switch_history
    protect_history
    damage_observations
    speed_observations
    weather_history

    bench_candidates
    certainty_map
```

This should be a deterministic pure transformation of:

```text
BotState + static mechanics
```

Persistent process memory may be used as a cache, but correctness must be reconstructable from the supplied state because workers may restart.

---

# 21. Opponent selected-four model

Use explicit states:

```text
POSSIBLE_SELECTED
CONFIRMED_SELECTED
CONFIRMED_NOT_SELECTED
```

At preview:

```text
all six = POSSIBLE_SELECTED
```

As unique Pokémon appear:

```text
appeared Pokémon = CONFIRMED_SELECTED
```

Once four unique selected Pokémon are publicly established:

```text
remaining two = CONFIRMED_NOT_SELECTED
```

This directly affects switch generation. A Pokémon confirmed not selected must never be generated as a switch candidate.

---

# 22. Illusion and unresolved identity

The harness intentionally allows opponent active identity to remain unresolved when public information cannot prove it.

If:

```text
team_id != null
```

then OTS/roster information may be attached confidently.

If:

```text
team_id == null
```

reason from apparent public information and preserve uncertainty.

Never resolve Illusion by consulting hidden simulator state.

---

# 23. History-derived features

History should primarily be used for temporal information unavailable in the current snapshot.

Build reusable structures for:

- last move;
- last target;
- recent target counts;
- Protect history;
- switch entry/exit turns;
- Fake Out eligibility;
- observed damage;
- observed speed order;
- weather source/history;
- item/ability reveal chronology.

Individual heuristics should not repeatedly search raw history independently.

---

# 24. Protect history

Track:

```text
last_used_protect_turn
consecutive_protect_count
```

For ourselves this influences repeated Protect reliability.

For opponents it influences plausibility but never makes Protect impossible.

A low-HP Tyranitar that has not just Protected should receive high Protect plausibility; the same Tyranitar after a successful Protect should still retain the response with a reduced weight.

---

# 25. Fake Out eligibility

Derive from switch chronology and known moves:

```text
fresh entry + Fake Out known → eligible
remained active → not eligible
```

This is important because Fake Out has higher priority than Follow Me and can invalidate a Turn-1 redirection plan.

---

# 26. OTS and move knowledge

If Open Team Sheets are active, full opponent moves/items/abilities may be known at preview. Use those facts directly.

Without OTS, revealed moves should accumulate from public history.

Internally distinguish:

```text
SET_KNOWN
MOVE_OBSERVED
```

because an observed move also contributes behavioral and empirical-damage evidence.

---

# 27. Health precision

Do not invent exact opponent HP when the public state reports only a percentage/fraction.

Use:

```text
health.exact
```

and prefer coarse KO confidence:

```text
CERTAIN
VERY_LIKELY
POSSIBLE
UNLIKELY
IMPOSSIBLE
```

rather than fake exact HP arithmetic.

---

# 28. Observed damage calibration

For successful attacks, store observations such as:

```python
DamageObservation:
    attacker
    move
    target
    target_form
    hp_fraction_removed
    attacker_boosts
    target_boosts
    weather
    terrain
    screens
    critical
    effectiveness
```

Use damage information in this order:

```text
1. comparable empirical observation
2. Showdown-backed public-state damage helper if safely available
3. coarse format-correct estimate
```

Critical hits must be marked and not treated as normal expected damage.

---

# 29. Speed model

Do not invent exact opponent Speed EVs.

Derive relational information:

```text
DEFINITELY_FASTER
LIKELY_FASTER
UNKNOWN
LIKELY_SLOWER
DEFINITELY_SLOWER
```

using:

- form/base speed;
- boosts;
- Tailwind;
- Trick Room;
- weather/terrain effects;
- known items/abilities;
- observed same-priority action order.

Observed speed evidence must retain the field context under which it was observed.

---

# 30. Timed conditions

The harness tracks condition start turns without needing to reimplement all duration mechanics.

The policy may derive:

```python
TimedCondition:
    active
    started_turn
    expected_end_turn
    remaining_turns
    confidence
```

for strategically relevant conditions such as:

- snow/rain/sun/sand;
- Aurora Veil;
- Tailwind;
- Trick Room;
- Gravity;
- terrain.

Duration logic belongs in the policy mechanics layer, not the tournament harness unless required by the public interface.

---

# 31. Baseline mechanical features

Before strategy is considered, derive facts such as:

- move effectiveness;
- current immunities;
- spread/single-target classification;
- priority;
- Fake Out availability;
- current Protect reliability;
- current redirection eligibility;
- weather remaining estimate;
- likely speed ordering bands;
- current boost state;
- known special mechanics tags.

These must not depend on which Pokémon the policy currently values most.

---

# 32. Baseline threat model

For each opponent active and each known move, calculate a descriptive threat profile before applying strategic importance.

Conceptually:

```python
BaselineMoveThreat:
    target_left_damage_band
    target_right_damage_band
    ko_confidence_left
    ko_confidence_right
    control_effects
    spread
    setup_effect
```

The threat layer answers:

> What can this move mechanically do to each slot?

It does not answer:

> How much do we care about the target?

That comes later.

---

# 33. Threat categories

Use semantic tags such as:

```text
SINGLE_TARGET_DAMAGE
SPREAD_DAMAGE
PRIORITY_DAMAGE
LIKELY_KO
DOUBLE_TARGET_KO
FAKE_OUT
REDIRECTION
ENCORE
STATUS
SPEED_CONTROL
WEATHER_CONTROL
FIELD_CONTROL
PHYSICAL_SETUP
SPECIAL_SETUP
SPEED_SETUP
PROTECT
WIDE_GUARD
RECOVERY
SWITCH
IMMUNITY_PIVOT
WEATHER_PIVOT
ABILITY_PIVOT
```

One action may have multiple tags.

---

# 34. Slot threat profile

For each of our active slots derive:

```python
SlotThreat:
    expected_incoming_damage
    worst_credible_damage
    likely_attackers
    likely_moves
    double_target_risk
    ko_confidence
    status_risk
    control_risk
```

Double targets must be represented explicitly. The opponent model must not assume one attack per slot.

---
