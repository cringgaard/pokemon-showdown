- expected unsafe base-form switch-ins.

---

# 49. Tactical offense preview factors

Begin relatively low and increase when:

- both fortress plans are weak;
- opponent is fragile;
- Heliolisk/Armarouge/Ninetales coverage creates strong immediate pressure;
- direct attacking solves the matchup more cleanly than setup.

Most candidate fours should contain Glaceon or Aggron unless tactical offense is unusually strong.

---

# 50. Bring-4 threat coverage

For each important opposing Pokémon, calculate whether the selected four contain at least one credible answer via:

- offensive pressure;
- resistance/immunity;
- redirection;
- Wide Guard;
- weather control;
- Encore;
- ability interaction.

Major opponent win conditions, weather setters and hard counters to our intended plan receive higher importance.

A candidate with a major unanswered opposing sweeper should receive a large penalty.

---

# 51. Composition synergies

Important current-team synergies include:

```text
Ninetales + Glaceon
    snow / Veil / Blizzard / Snow Cloak / Ice Defense

Maushold + Glaceon
    Friend Guard / Follow Me / Mud-Slap / Encore

Maushold + Aggron
    Follow Me / Friend Guard / setup protection

Armarouge + Glaceon
    Wide Guard / Fire patch / Ally Switch immunity lines

Armarouge + Maushold
    multiple forms of target denial

Heliolisk + Ninetales
    complementary anti-rain pressure
```

Avoid uncontrolled pairwise-synergy explosion by using caps/saturation.

---

# 52. Lead scoring

For our lead `L` and opponent lead hypothesis `H`, evaluate:

```text
opening survival
immediate pressure
setup access
field control
matchup position
information value
- immediate KO risk
- denied core action
- transformation risk
```

Robustly aggregate over opponent lead hypotheses rather than optimizing against only the most likely lead.

---

# 53. Ninetales lead versus backline

Increase Ninetales lead value when:

- snow immediately benefits partner;
- Veil likely resolves;
- opponent cannot immediately overwrite weather;
- Freeze-Dry pressures the opening;
- fast Rock/Fire pressure is limited.

Decrease when:

- Mega Charizard Y can overwrite snow after Ninetales enters;
- Pelipper/Politoed weather reset is highly credible;
- fast Rock Slide threatens KO/flinch;
- Ninetales likely dies before producing useful value.

Increase Ninetales **backline** value when the weather war remains unresolved.

---

# 54. Aggron lead versus backline

Increase lead value when:

- Mega state is urgently needed before taking pressure;
- opponent is physical;
- switching base Aggron in later would be dangerous.

Decrease backline value when likely incoming attacks severely punish base Aggron before it can transform.

This specifically captures the difference between:

```text
lead → transform → take attack
```

and:

```text
switch base Aggron → take attack → maybe transform later
```

---

# 55. Maushold lead factors

Increase when:

- partner requires protection;
- opponent relies on single-target pressure;
- Friend Guard changes survival thresholds;
- Encore opportunities are plausible.

Decrease Turn-1 Follow Me reliability when the opponent has a fresh Fake Out user.

---

# 56. Armarouge lead factors

Increase strongly against:

- Heat Wave;
- Eruption;
- dangerous spread Fire;
- dangerous spread pressure generally;
- Charizard Y uncertainty.

Armarouge is most valuable when it is already on the field before the spread attack occurs.

---

# 57. Heliolisk lead factors

Increase against:

- Water/rain pressure;
- Pelipper/Politoed/Basculegion/Swampert-like targets;
- positions where Focus Sash gives scouting/aggressive utility.

Do not conflate:

```text
Heliolisk is useful
```

with:

```text
Thunderbolt is currently safe
```

because Lightning Rod may constrain Electric attacks.

---

# 58. Glaceon lead versus backline

Prefer Glaceon in back when:

- support must be established first;
- opening pressure is severe;
- counters remain active;
- Armarouge/Maushold need to scout or deny the opening.

Glaceon lead becomes attractive when snow/Veil can be established safely and immediate Blizzard pressure is useful.

---

# 59. Initial preview score decomposition

A reasonable first decomposition is:

```text
30% lead robustness
25% primary-plan viability
10% secondary-plan viability
15% threat coverage
10% backline quality
10% specialist/synergy
- structural penalties
```

These are configurable starting values, not permanent truths.

---

# 60. Opponent-response model

The opponent model should answer:

> What can a competent opponent plausibly do on this turn before we get another useful decision?

It should **not** attempt to estimate a perfect opponent policy.

For each opponent active retain several diverse individual actions, then combine them into 4–8 plausible joint responses.

---

# 61. Opponent action sources

With OTS:

- use the actual known four moves;
- use Protect only if actually on the set;
- use switches from selected-four-aware bench candidates.

Without OTS:

- use revealed moves;
- use a limited set of generic hypotheses only where necessary;
- preserve uncertainty.

Do not generate moves that the public information proves are absent.

---

# 62. Individual opponent-action plausibility

Increase for:

- high damage;
- likely KO;
- super-effective pressure;
- removing the current primary win condition;
- protecting a threatened Pokémon;
- strong setup opportunity;
- speed/weather/control value;
- known tactical synergy;
- modest historical targeting evidence.

Decrease for:

- immunity;
- obvious redundancy;
- harmful ability interaction;
- repeated Protect reliability reduction;
- strategically irrelevant action.

---

# 63. Keep multiple opponent action types

For each opponent active retain approximately the top 3–5 actions with diversity, including where relevant:

- best attack;
- best Protect/defense;
- best setup/control;
- best switch.

Otherwise the model would systematically ignore important lines such as Protect, setup and immunity pivots.

---

# 64. Opponent response archetypes

Explicitly attempt to preserve:

```text
MAX_DAMAGE
FOCUS_PRIMARY_WINCON
PROTECT_AND_PROGRESS
DISRUPT_AND_SETUP
PIVOT_AND_ACT
SPREAD_PRESSURE
```

After deduplication, target 4–8 responses in full mode.

---

# 65. Double targets

Generate tactically plausible combinations such as:

```text
A → left, B → left
A → right, B → right
A → left, B → right
A → right, B → left
```

