
# 35. Runtime win-condition vector

At every decision compute:

```python
WinConditionVector:
    glaceon_fortress: 0..100
    aggron_fortress: 0..100
    tactical_offense: 0..100
```

The values should be continuous and recomputed from public state.

Categorical labels (`PRIMARY`, `SECONDARY`, `FLEXIBLE`) are primarily for traceability and a few large tactical adjustments.

---

# 36. Glaceon runtime viability

Increase with:

- Glaceon alive;
- healthy HP;
- snow;
- Aurora Veil;
- Calm Mind boosts;
- Ninetales alive while weather remains contested;
- important physical counters removed;
- strong Blizzard/Freeze-Dry offensive matchup.

Decrease with:

- No Guard;
- Gravity;
- major accuracy bypass;
- strong immediate Fire/Fighting/Rock/Steel pressure;
- weather permanently lost;
- Ninetales gone when snow is required;
- opponent counters still healthy;
- lethal baseline incoming pressure.

---

# 37. Aggron runtime viability

Increase with:

- Mega state active;
- healthy HP;
- Defense boosts;
- physical opponent composition;
- remaining Body Press targets;
- Maushold support;
- major Ghosts removed;
- special pressure reduced.

Decrease with:

- burn;
- Ghost-heavy endgame;
- special attackers;
- poor Body Press targets;
- low HP without meaningful defensive line;
- inability to transform before a dangerous hit when still base form.

---

# 38. Tactical offense viability

This score rises when:

- opposing Pokémon are already in KO range;
- few Pokémon remain;
- spread cleanup is available;
- direct super-effective coverage can end the game;
- further setup has little marginal value.

This is the formal representation of **cash out**.

Example:

```text
both opponents in reliable Blizzard KO range
→ tactical offense should dominate immediate decision-making
```

---

# 39. Clear primary versus flexible mode

If the top win-condition score exceeds the second by a configurable margin, call it the primary plan.

Example initial threshold:

```text
15 points
```

Otherwise use `FLEXIBLE` / dual-plan mode.

Downstream scoring should still consume the continuous values rather than only the label.

---

# 40. Strategic resource values

After the win-condition vector is known, calculate current Pokémon resource values.

Conceptually:

```text
resource value = base value × role importance × remaining utility
```

Base values may begin roughly around:

```text
Glaceon      100
Ninetales     90
Maushold      80
Aggron       100
Armarouge     85
Heliolisk     80
```

These are not power rankings; context modifies them strongly.

---

# 41. Nonlinear HP utility

HP should not be valued linearly.

A useful initial curve:

```text
100% → 1.00
75%  → 0.90
50%  → 0.70
25%  → 0.45
1%   → 0.20
0%   → 0
```

The exact curve is configurable.

The key invariant is:

> **1% HP is not zero value.**

Low-HP Pokémon may still weather-reset, redirect, Protect, activate entry abilities, absorb attacks or create a free switch.

---

# 42. Contextual support value

If Glaceon is primary:

- Ninetales value rises;
- Maushold value rises;
- Armarouge rises while relevant spread/Fire threats remain.

If Aggron is primary:

- Maushold value rises sharply;
- Armarouge rises against relevant spread/Fire pressure;
- Ninetales may become less central unless weather/snow still matters.

This dependency is one-way:

```text
win-condition viability → resource value
```

Resource value must not feed back into determining the win condition itself.

---

# 43. Team Preview algorithm

The harness already enumerates legal ordered Bring-4 responses. For bring-6/pick-4 there are at most:

```text
6P4 = 360
```

This is small enough that v1 should score every legal preview action rather than selecting greedily.

Pipeline:

```text
own six + opponent OTS roster
        ↓
OpponentRosterProfile
        ↓
OpponentLeadHypotheses
        ↓
all legal ordered Bring-4 candidates
        ↓
composition score
win-condition score
coverage score
lead score
backline score
synergy/specialist score
        ↓
robust aggregation over opponent lead hypotheses
        ↓
best preview action
```

---

# 44. Opponent roster tags

Derive from actual known moves/abilities/items where possible, not species stereotypes.

Examples:

```text
PHYSICAL_PRESSURE
SPECIAL_PRESSURE
FIGHTING_PRESSURE
FIRE_PRESSURE
ROCK_PRESSURE
GROUND_PRESSURE
WATER_PRESSURE
SPREAD_DAMAGE
SPREAD_FIRE
SPREAD_WATER
WEATHER_SETTER
WEATHER_ABUSER
FAKE_OUT
REDIRECTION
SPEED_CONTROL
SETUP_SWEEPER
STATUS_CONTROL
GHOST
BODY_PRESS_IMMUNE
STAT_DROP_PUNISHER
NO_GUARD
ACCURACY_BYPASS
VEIL_REMOVAL
LIGHTNING_ROD
FLASH_FIRE
WATER_IMMUNITY
```

If OTS says a Sneasler lacks Fake Out, it does not receive the `FAKE_OUT` tag.

---

# 45. Opponent lead hypotheses

There are only 15 unordered lead pairs from a six-Pokémon roster.

Score pair plausibility using synergies such as:

- Fake Out + setup;
- Tailwind + attacker;
- weather setter + abuser;
- redirection + setup;
- spread attacker + support;
- complementary offensive pressure.

Retain roughly the top 6–10 diverse lead hypotheses.

Do not require perfect prediction; the goal is lead robustness.

---

# 46. Preview win-condition scoring

For each legal ordered Bring-4 candidate compute:

```text
Glaceon fortress viability
Aggron fortress viability
Tactical offense viability
```

Then combine primary/secondary viability with coverage and role fit.

A conceptual composition score:

```text
plan viability
+ threat coverage
+ internal synergy
+ specialist value
- unanswered threats
- structural holes
```

---

# 47. Glaceon preview factors

Positive:

- Glaceon selected;
- Ninetales selected;
- Maushold selected;
- snow realistically maintainable;
- Aurora Veil realistically establishable;
- opponent primarily physical;
- strong Ice pressure into opponent;
- Armarouge selected when spread/Fire pressure is high;
- key Glaceon counters can be removed by partners.

Negative:

- No Guard;
- Gravity;
- multiple fast super-effective threats;
- severe Fire/Fighting/Rock/Steel pressure;
- uncontrollable opposing weather;
- inability to preserve Ninetales where weather remains necessary.

---

# 48. Aggron preview factors

Positive:

- Aggron selected;
- physically oriented opponent;
- multiple useful Body Press targets;
- few Ghosts;
- Maushold selected;
- burn pressure limited;
- safe path to Mega state.

Negative:

- Ghost-heavy roster;
- strong special pressure;
- reliable burn;
- poor Body Press target quality;
