Do not branch on every possible secondary effect.

Examples such as Dire Claw status, Thunderbolt paralysis or Blizzard freeze should usually contribute an expected secondary risk/value rather than exponentially branching the response tree.

Promote a secondary to richer modelling only if later testing proves it strategically central.

---

# 80. Deterministic setup/control effects

Explicitly model strategically important deterministic effects such as:

- Calm Mind;
- Iron Defense;
- Dragon Dance;
- Swords Dance;
- Tailwind;
- Encore;
- Mud-Slap;
- Aurora Veil;
- Gravity;
- relevant weather/terrain control.

After an opponent setup move, recompute future threat rather than assigning a constant “+20 per stage.”

A second Dragon Dance may cross Speed/KO thresholds and should therefore be much more dangerous than a linear stage counter suggests.

---

# 81. Burn and major statuses

Burn is strategically important for Aggron because:

- physical damage is reduced;
- Body Press is reduced;
- chip accumulates.

Paralysis primarily affects:

- Speed;
- chance to act.

Sleep primarily affects temporary action availability.

The evaluator may summarize status effects at this strategic level rather than recreate a universal status engine.

---

# 82. End-of-turn effects

Do not recreate the complete Showdown end-of-turn queue.

For v1, approximate only obvious strategically material effects such as:

- Wish resolution;
- known Leftovers;
- relevant residual status damage;
- relevant weather chip.

If exact 1-HP survival depends on an interaction not modelled confidently, mark the projection `SURVIVAL_UNCERTAIN` rather than inventing certainty.

---

# 83. Projection confidence

Projected outcomes should carry confidence such as:

```text
HIGH
MEDIUM
LOW
```

High confidence examples:

- known type immunity;
- known weather entry ability;
- Protect;
- empirical lethal damage;
- straightforward KO.

Low confidence examples:

- obscure callbacks;
- uncertain Speed ordering;
- unknown dynamic effect;
- heavily random secondary outcome.

Low confidence contributes a modest strategic risk penalty.

---

# 84. Unknown mechanics degrade safely

If the bot sees a move/ability whose dynamic effect it cannot model:

- preserve known static data;
- set `unknown_dynamic_effect = true`;
- apply uncertainty;
- do not assume the effect is zero;
- do not infer behavior from the name.

This is preferable to both ignoring the mechanic and trying to recreate arbitrary callbacks.

---

# 85. Team mechanics receive higher fidelity

Because our own action space is fixed, v1 should understand all current-team moves with high strategic fidelity.

Opponent mechanics can be promoted incrementally when actual battles expose gaps.

Development loop:

```text
bot makes bad decision because mechanic misunderstood
    ↓
inspect Showdown implementation
    ↓
add semantic model or safe helper
    ↓
add simulator integration test
    ↓
add policy regression test
```

---

# 86. Action scoring model

For state `s`, our joint action `a`, and opponent response `r`:

```text
ProjectedOutcome = project(s, a, r)
Features = extract(ProjectedOutcome, strategy, resources)
U(a,r) = Σ wi fi
```

Then aggregate over opponent responses.

The policy should expose numeric features before weights whenever reasonably possible.

---

# 87. Score scale

A rough common scale helps interpret traces:

```text
+1000  effectively winning position
+200   extremely strong tactical result
+100   major advantage
+50    meaningful advantage
+20    useful incremental progress
0      neutral
-20    mild cost
-50    meaningful disadvantage
-100   major tactical loss
-200   likely loses critical position
-1000  effectively losing position
```

Terminal battle outcomes override everything:

```text
win  +100000
loss -100000
```

---

# 88. Feature families

Use numeric features in these families:

```text
A. terminal outcome
B. resource/survival
C. damage and KO pressure
D. win-condition progress
E. defensive field control
F. disruption/control
G. positioning/switching
H. accuracy/evasion
I. setup
J. joint-action coordination
K. tactical risk/uncertainty
```

---

# 89. Resource and KO features

Own faint penalty should scale with current strategic resource value.

Opponent KO reward should scale with threat importance.

For example:

- current hard counter to Glaceon → high KO reward;
- active weather setter → elevated KO reward;
- exhausted low-impact support → lower reward.

Damage and KO should be separate features so 50% chip does not automatically outweigh important defensive control.

---

# 90. Setup diminishing returns

For Glaceon, an initial qualitative schedule could be:

```text
first Calm Mind   high
second            high/moderate
third             low/moderate
fourth+           low
```

Multiply setup value by survival confidence and expected opportunity to exploit the boost.

Similarly for Iron Defense, but physical/special threat composition matters more strongly.

---

# 91. Protect scoring

Protect gains value when:

- likely targeted;
- otherwise likely KO'd;
- partner can remove the threat;
- Wish is pending;
- field timers advance favorably;
- current win condition is being preserved.

Protect loses value when:

- partner cannot exploit the turn;
- opponent gains free setup;
- repeated Protect reliability is low.

---

# 92. Follow Me scoring

Do not assign a fixed “support bonus.”

Calculate the consequence prevented:

```text
redirected damage
redirected KO
redirected status/control
```

Then account for Maushold's own survival/trade.

If Follow Me preserves the current primary win condition from an eligible lethal single-target attack, give a very large `DETERMINISTIC_PROTECTION` feature.

This should normally outrank Mud-Slap's speculative future value.

---

# 93. Mud-Slap scoring

Value components:

```text
accuracy reduction
+ chip
- ability activation cost
```

Accuracy-drop value increases with:

- target offensive importance;
- number of turns target likely remains;
- likelihood Glaceon later faces it;
- target's baseline move accuracy.

Reduce value when the target can easily switch and clear the drop.

Hard/near-hard penalties apply to Defiant, Competitive, Contrary and No Guard according to actual mechanics. Stamina is contextual because the accuracy loss may still help Glaceon while the Defense gain may harm Aggron.

---

# 94. Encore scoring

Representative categories:

```text
