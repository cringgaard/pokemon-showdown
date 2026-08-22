- Freeze-Dry
- Encore
- Protect
```

### Role

Renewable weather-control resource, screen setter, anti-Water pressure and tactical Encore user.

### Policy principles

- Treat Ninetales as a weather-reset resource, not a disposable Turn-1 Veil machine.
- Preserve it while opposing weather setters remain relevant.
- Aurora Veil only receives value if snow is expected to exist **when the move resolves**.
- If Pelipper or Politoed can switch in before Ninetales acts, weather sequencing must be projected.
- Freeze-Dry into a predicted Pelipper/Politoed slot is a major punishment line.
- Freeze-Dry is single-target and is therefore strategically useful against opposing Wide Guard.
- Encore is strong only when repeating the last move is actually bad for the opponent.
- Excellent Encore targets: Protect, Dragon Dance, Swords Dance, Tailwind in the wrong state, other setup/support.
- Poor Encore targets: attacks the opponent is already happy to repeat.
- Against known/suspected Mega Charizard Y, Ninetales usually belongs in reserve until Drought has activated.
- Against Mega Charizard X, do not treat Ninetales as an automatic weather response.

---

## 4.3 Maushold

```text
Maushold @ Chople Berry
Ability: Friend Guard
Level: 50
Stat Points: 32 HP / 17 Def / 17 SpD
Calm Nature

- Follow Me
- Mud-Slap
- Encore
- Protect
```

### Role

Deterministic single-target protection first; accuracy control second.

### Default action hierarchy

When several actions are plausible, the policy should roughly prioritize:

1. **Follow Me** when it deterministically protects the current critical partner from an eligible single-target attack.
2. **Protect** when preserving Maushold, burning Fake Out, or blocking a predicted double target is important.
3. **Encore** when the target is locked into a strategically poor move.
4. **Mud-Slap** when no higher-value deterministic control is required.

This hierarchy is not an unconditional move script. Immediate wins or other strong lines may supersede it.

### Mud-Slap safety

Strongly penalize or nullify Mud-Slap value against:

- Defiant;
- Competitive;
- Contrary;
- No Guard;
- Stamina when the Defense boost materially harms the current Aggron plan.

### Important Follow Me mechanics

- Does not redirect spread moves.
- Can redirect eligible single-target moves aimed at the opponent's ally.
- This can disrupt support combos such as Decorate or Beat Up.
- Fake Out has higher priority and can flinch Maushold before Follow Me becomes active.
- Eligible Ghost moves redirected into Normal-type Maushold may be blanked by immunity; verify Champions behavior via Showdown integration tests.

---

## 4.4 Aggron / Mega Aggron

```text
Aggron @ Aggronite
Ability: Sturdy -> Filter
Level: 50
Stat Points: 32 HP / 2 Def / 32 SpD
Careful Nature

- Iron Defense
- Body Press
- Heavy Slam
- Protect
```

### Role

Alternative physical fortress and often the primary win condition against physical Dark/Rock/Ice/Steel-heavy teams.

### Policy principles

- Transform as early as practical when the Mega defensive profile is needed.
- Never evaluate base Aggron as though it were already Mega.
- Strongly penalize switching base Aggron into powerful Water/Ground/Fighting pressure when it cannot transform before taking the hit.
- Evaluate Fire according to the actual current form and format mechanics; do not use a blanket assumption.
- First Iron Defense can be high value in physical matchups.
- Further Iron Defense has diminishing value and should be sharply penalized against special pressure.
- Body Press uses Defense, so ordinary Attack drops do not reduce its damage.
- Burn **does** reduce Body Press because it is still a physical move.
- Ghosts are immune to Body Press unless the actual target typing changes.
- Heavy Slam is the key non-Body-Press fallback into Ghosts and many Fairy targets.
- Ghost pivots into an obvious Body Press slot must be considered by the opponent-response model.

---

## 4.5 Armarouge

```text
Armarouge @ Colbur Berry
Ability: Flash Fire
Level: 50
Stat Points: 32 HP / 32 SpA / 2 SpD
Modest Nature

- Wide Guard
- Ally Switch
- Armor Cannon
- Psychic
```

### Role

Spread-denial and Fire-pressure patch.

### Policy principles

- Wide Guard is a primary answer to dangerous spread moves.
- Important examples include Heat Wave, Eruption, Water Spout, Muddy Water, Rock Slide, Earthquake, Blizzard and Discharge where applicable.
- Wide Guard does not solve strong single-target adaptation such as Weather Ball.
- When both spread and focused single-target pressure are plausible, explicitly evaluate **Wide Guard + partner Protect** as a joint defensive line.
- Ally Switch is high value when it redirects a single-target attack into an immunity/resistance, especially Flash Fire.
- Repeated Ally Switch should receive a penalty because its informational/surprise value drops and it can become very low-impact.
- If Armarouge is Encored into a useless Ally Switch loop, switching out must be treated as a strong option.

---

## 4.6 Heliolisk

```text
Heliolisk @ Focus Sash
Ability: Dry Skin
Level: 50
Stat Points: 2 HP / 32 SpA / 32 Spe
Timid Nature

- Thunderbolt
- Grass Knot
- Ally Switch
- Protect
```

### Role

Fast anti-Water/rain specialist, Focus Sash utility piece and expendable late pivot.

### Policy principles

- Value Thunderbolt into Pelipper/Politoed and Grass Knot into heavy Water/Ground targets where mechanics support it.
- Do not blindly click Electric attacks when Lightning Rod can pivot in.
- Dry Skin gives Water-oriented defensive utility.
- Focus Sash at full HP materially changes Heliolisk's survival value.
- After Focus Sash is consumed, Heliolisk may retain large **positional** value even at ~1% HP.
- A tiny-HP Heliolisk may be worth protecting now and sacrificing later as a pivot to preserve Ninetales or Glaceon.
- Heliolisk should not be modelled as useful only while rain is active.

---

# 5. Strategic identity

The team should be understood in three layers.

## 5.1 Layer A — deterministic prevention

Examples:

- Protect;
- Follow Me;
- Wide Guard;
- immunity pivots;
- Flash Fire;
- Dry Skin;
- weather resets;
- Encore;
- Friend Guard.

These should generally be preferred when they **deterministically** preserve the actual win condition.

## 5.2 Layer B — probabilistic denial

Examples:

- Snow Cloak;
- Bright Powder;
- Mud-Slap;
- other accuracy/evasion interactions.

