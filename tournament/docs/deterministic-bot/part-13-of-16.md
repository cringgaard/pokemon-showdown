## P0-13 — Wide Guard does not block single-target adaptation

Verify:

```text
Heat Wave → blocked
Weather Ball → not blocked
```

In a fork where both are plausible:

```text
Wide Guard + threatened partner Protect
```

should gain strong robustness value.

---

## P0-14 — Charizard Y sequencing

At preview:

- Ninetales inclusion high;
- Ninetales lead value low;
- Armarouge lead value high where spread Fire is relevant.

Representative preferred structure:

```text
Armarouge + Maushold
Ninetales + Glaceon back
```

rather than snow core lead.

Turn projection must handle Drought overwriting snow before Veil where appropriate.

---

## P0-15 — Charizard X changes strategic mode

After Mega X reveal and one Dragon Dance:

- weather-reset urgency drops;
- setup threat rises sharply;
- second Dragon Dance response retained if we apply low pressure;
- passive action giving a second free DD ranks poorly against pressure/control lines.

---

# 125. P1 regression catalogue

## P1-01 — Encore quality

`Encore Protect/setup` should outrank `Encore strong attack the opponent wants to spam`.

## P1-02 — Encored Armarouge can switch

If Armarouge is locked into low-value Ally Switch and a good switch exists:

```text
switch > repeat Ally Switch
```

unless the repeated Ally Switch still creates a concrete immunity/protection line.

## P1-03 — Ally Switch immunity

If Ally Switch redirects a known single-target Fire move into Flash Fire Armarouge, projection should recognize the immunity/ability interaction.

## P1-04 — Low-HP Heliolisk retains value

A ~1% Heliolisk has nonzero resource value and may later be a good sacrificial pivot.

## P1-05 — Protect absorbs predicted double target

When opponent Fake Out + attack plausibly double-target Heliolisk:

```text
Heliolisk Protect + Aggron progress
```

should score highly.

## P1-06 — Robust slot targeting through Basculegion switch

Low Archaludon with Basculegion available:

- stay, Protect and switch responses retained;
- Thunderbolt into the slot retains value into stay and Basculegion switch;
- robust value recognized.

## P1-07 — Protect tiny Heliolisk for future pivot

At Focus-Sash HP, Protect may outrank throwing Heliolisk away when the partner can remove the current threat and Heliolisk remains useful later.

## P1-08 — Weather sequencing + partner Protect

Ninetales switch-in + Aggron Protect should receive positive joint positioning value when it establishes snow, blanks a predicted attack and preserves future pivot resources.

## P1-09 — Blizzard cash-out after engineered miss

When evasion creates a free turn and Blizzard removes a major threat, Blizzard should outrank further Calm Mind/Wish.

## P1-10 — Engineered evasion versus ordinary luck

Glaceon in snow gets mechanic-based evasion value. Mega Aggron does not become “evasive” because Will-O-Wisp happened to miss in one battle.

## P1-11 — Evasion lowers risk but does not erase it

Protect should outrank “hope the lethal attack misses + extra setup” when deterministic survival exists.

## P1-12 — Gravity suppresses evasion value

Verify Champions behavior and reduce Glaceon's passive evasion value under Gravity.

## P1-13 — Friend Guard changes partner threat

Projected survival should account for Friend Guard while Maushold is active and remove it after Maushold leaves/faints.

## P1-14 — Chople is consumable

First Fighting redirection with Chople and later redirection without Chople must differ.

## P1-15 — Focus Sash is consumable

Full-HP Heliolisk with intact Sash has higher immediate survival value; after activation the Sash benefit disappears while positional value remains.

## P1-16 — Wide Guard matchup derivation

High against known spread pressure, low against only single-target pressure, and insufficient alone when partner is vulnerable to obvious single-target adaptation.

## P1-17 — Follow Me does not stop spread

Simulator and policy test.

## P1-18 — Follow Me + Ghost immunity interaction

Verify the eligible redirection/immunity sequence through Showdown and score accordingly.

## P1-19 — Freeze-Dry is generic coverage, not only Pelipper tech

Value against Water and Water/Ground as mechanics dictate; also ordinary Ice coverage where relevant.

## P1-20 — Heliolisk is not only a rain button

Preview/resource scoring should recognize Sash, fast pressure and Basculegion/Water coverage even when rain is not currently active.

## P1-21 — Ghost-heavy preview lowers Aggron fortress viability

Compare otherwise similar rosters.

## P1-22 — Accuracy bypass lowers Glaceon fortress viability

No Guard/Gravity pressure reduces, but does not necessarily zero, Glaceon plan score.

## P1-23 — Ninetales can be more valuable in back

Same four Pokémon, different preview order; weather conflict should make safe lead + Ninetales reserve outperform Ninetales lead.

## P1-24 — Aggron can be more valuable in lead

When base-form switch-in would be dangerous but lead transformation gives a viable line, lead value should be higher.

---

# 126. P2 regression catalogue

Useful but not required for first playable policy:

- target-history modest plausibility adjustment;
- repeated Protect weighting;
- contextual speed observations;
- empirical damage dominance over crude estimate;
- robust-action preference over fragile prediction;
- response-set independence from our hidden candidate;
- more advanced switch tendency modelling.

---

# 127. Golden decision tests

A small subset may assert the final chosen action outright where confidence is high.

Suggested initial golden principles:

1. Established Glaceon under obvious lethal focus while partner can act → Protect Glaceon.
2. Both opponents in reliable Blizzard KO range → Blizzard / cash out.
3. Chople Maushold can redirect lethal Sneasler Close Combat from critical Mega Aggron → Follow Me line.
4. Pelipper weather reset makes Veil fail and Freeze-Dry punishes the slot → Freeze-Dry line.
5. Body Press into a currently known Ghost with no other purpose → do not choose it.
6. Mud-Slap into known Defiant/Contrary where target survives → do not choose it.
7. Encored into useless support move with strong switch available → switch.

Most other tests should remain relational.

---

# 128. Full-battle smoke tests

The first complete bot should play deterministic matches against:

- RandomBot;
- simple maximum-damage bot;
- simple Protect-aware bot if available;
- itself.

Smoke-test assertions:

- completes battle;
