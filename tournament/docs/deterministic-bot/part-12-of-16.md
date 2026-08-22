These annotations must be backed by Showdown source/provenance and regression tests. They are interpretations of the authoritative mechanics, not a replacement source of truth.

---

# 118. Mechanics/version metadata

Every bot run should record:

- format ID;
- mod ID;
- Showdown commit;
- mechanics snapshot hash/version;
- team configuration version;
- policy version;
- weights version.

This is essential once experiments begin.

---

# 119. Feature registry

Every numeric feature should have a stable identifier, description and expected range.

Examples:

```text
DETERMINISTIC_PROTECTION
RNG_DEPENDENCE
PRIMARY_WINCON_SURVIVAL
FREE_TURN_CONVERSION
WEATHER_CONTROL_GAIN
OPPONENT_SETUP_ALLOWED
SACRIFICIAL_PIVOT_VALUE
ROBUST_ACROSS_RESPONSES
```

Stable feature IDs enable:

- traces;
- regression assertions;
- ablation studies;
- later learned-weight optimization;
- analysis across many self-play games.

---

# 120. Decision traces

Trace structured data first; render human-readable summaries second.

A decision should record at least:

```text
turn / decision id
policy/mechanics/weights versions
runtime win-condition vector
major threats
opponent response set + weights/reasons
candidate actions
per-candidate expected utility
credible bad case
feature contributions
rule adjustments
selected action
latency/evaluation counts
```

Example human-readable form:

```text
TURN 5

STRATEGY
Glaceon: 81
Aggron: 44
Offense: 53

PRIMARY THREATS
Sneasler CC → Aggron: VERY_LIKELY heavy
Tyranitar Protect: high plausibility
Gourgeist switch: medium plausibility

TOP ACTION
Maushold Follow Me
Aggron Body Press → Tyranitar

Expected utility: 92
Bad-case utility: 51
Final score: 101

WHY
+68 deterministic protection of Aggron
+57 Tyranitar KO pressure
+21 preserves primary answer
-18 Maushold resource loss
-11 Ghost-pivot risk
```

---

# 121. Trace levels

Support something like:

```text
NONE
SUMMARY
TOP_CANDIDATES
FULL
```

Tournament runs likely use `TOP_CANDIDATES`; regression debugging can use `FULL`.

Traces belong in developer/bot logs, not the actual `BotResponse` contract.

---

# 122. Regression-suite philosophy

Regression tests should preserve **strategic ordering**, not arbitrary exact scores.

Prefer:

```python
assert score(good_line) > score(known_bad_line)
```

rather than:

```python
assert score(good_line) == 127.4
```

Likewise, response tests should usually assert that a response exists, not that it has an exact probability.

---

# 123. Regression test classes

Use categories:

```text
MECHANIC
KNOWLEDGE
THREAT
STRATEGY
RESPONSE
PROJECTION
POLICY
FULL_BATTLE
```

Severity:

```text
P0 fundamental/catastrophic
P1 major strategic behavior
P2 useful refinement
P3 nice-to-have
```

All P0 and most P1 tests should pass before v1 is considered ready.

---

# 124. P0 regression catalogue

## P0-01 — Follow Me protects the actual Aggron win condition

Situation:

```text
Maushold + Mega Aggron
vs
very low Tyranitar + Sneasler

Sneasler knows Close Combat
Maushold has Chople
Aggron is the critical Tyranitar answer
```

Required:

- Close Combat → Aggron classified as major threat;
- Tyranitar Protect response retained;
- Aggron resource value high;
- `Follow Me + Body Press` ranks above `Mud-Slap + Body Press` unless another line immediately wins.

Canonical source: manual Tyranitar/Sneasler/Gourgeist loss.

---

## P0-02 — Ghost pivot affects Body Press

If a known selected Ghost is available in back against an obvious Body Press target:

- immunity switch response must be generated;
- projected Body Press into incoming Ghost is zero;
- obvious Body Press slot loses expected value;
- complementary coverage/robust actions gain relative value.

---

## P0-03 — Fake Out before Follow Me

With a fresh Fake Out user:

- Turn-1 Follow Me cannot be treated as deterministic protection;
- Ninetales Protect/double Protect may gain value when burning Fake Out is strategically important.

Verify actual priority behavior with Showdown.

---

## P0-04 — Protect established Glaceon

With Glaceon already usefully boosted and under obvious lethal focus:

```text
Protect + partner progress
>
additional Calm Mind + partner progress
```

Parameterize around +1/+2/+3.

---

## P0-05 — Cash out Blizzard

If both opponents are in reliable Blizzard KO range:

```text
Blizzard > Calm Mind
Blizzard > Wish
```

unless weather/accuracy makes Blizzard itself unreliable.

---

## P0-06 — Pelipper weather reset invalidates Veil

If snow is active, Ninetales is active and a confirmed Pelipper can switch in:

- Pelipper switch response retained;
- Drizzle projected before Ninetales's action;
- Aurora Veil projected to fail without snow;
- Veil expected value reduced accordingly.

Simulator-backed ordering test required.

---

## P0-07 — Freeze-Dry punishes Pelipper reset

In the same state, Freeze-Dry into the likely switch slot should receive strong value and normally outrank Aurora Veil when the predicted switch creates a likely Pelipper KO.

---

## P0-08 — Lightning Rod constrains blind Thunderbolt

When Raichu/another known Lightning Rod pivot is available:

- Electric-immunity pivot response retained;
- Thunderbolt into the obvious Water slot loses robustness;
- projected Lightning Rod boost represented where relevant.

---

## P0-09 — No Guard invalidates accuracy-denial benefit

Against a confirmed No Guard attacker:

- Snow Cloak/Bright Powder do not reduce relevant attack hit probability;
- Mud-Slap defensive accuracy value is zero for that interaction;
- deterministic defense remains valued.

Verify Champions Mega Raichu Y behavior directly in Showdown.

---

## P0-10 — Defiant / Competitive / Contrary

Stat-lowering effects must account for these abilities.

Representative cases:

- Mud-Slap into Defiant Annihilape;
- generic Competitive target;
- Mud-Slap into Contrary Mega Staraptor.

Strong negative unless the immediate action ends the threat before the punishment matters.

---

## P0-11 — Stamina contextual Mud-Slap

Mud-Slap into Stamina Archaludon should project both:

```text
accuracy down
Defense up
```

Value may remain positive for Glaceon plan and negative for Aggron Body Press plan.

---

## P0-12 — Base Aggron is not Mega Aggron

Switching base Aggron into strong Water/Ground/Fighting must use base-form defensive profile.

Leading and transforming before the hit may be much safer.

This is both policy and Champions transformation-API acceptance.

---

