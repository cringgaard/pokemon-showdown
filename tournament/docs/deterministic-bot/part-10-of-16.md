locks dangerous setup/support   very high
locks Protect                   high
locks neutral support           moderate
locks useful attack             low
locks attack opponent wants     zero/negative
```

Encore should not be used simply because it is legal.

---

# 95. Wide Guard scoring

Compute the damage/KO value prevented from currently plausible spread responses.

Do not give a large Wide Guard score if the opponent's known sets contain no strategically relevant spread moves.

Explicitly reward the joint line:

```text
Wide Guard + threatened partner Protect
```

when both spread and focused single-target adaptation are plausible.

---

# 96. Ally Switch scoring

Positive features:

- redirects into immunity;
- redirects into resistance;
- preserves critical partner;
- activates Flash Fire or Dry Skin if applicable.

Negative features:

- repeated previous turn;
- both slots lose equally under likely attack;
- low value against opponent's response set.

Consecutive use should receive a configurable penalty rather than an absolute prohibition.

---

# 97. Switching/positioning features

A switch can gain value from:

- weather reset;
- immunity/resistance;
- preserving a critical resource;
- clearing Encore/Perish or other volatile constraints where mechanics support it;
- creating a free replacement after sacrifice;
- restoring future entry ability value;
- improving board position.

It loses value from:

- unsafe incoming damage;
- sacrificing the only weather resource;
- exposing base Aggron incorrectly;
- losing critical boosts/position.

---

# 98. Sacrificial pivot feature

A low-HP Pokémon may have positive value when switching it into an expected attack:

```text
it dies safely
protects the win condition
creates a free switch
preserves a more important resource
```

The final Heliolisk test game is the canonical example.

---

# 99. Accuracy/evasion feature

Use expected hit probability rather than sampling randomness.

Then add a separate `RNG_DEPENDENCE` feature so the bot does not conclude that a 28% miss chance is equivalent to safety.

Example qualitative risk:

```text
survives deterministically          no penalty
survives ~70%                       small penalty
survives ~50%                       meaningful penalty
requires unlikely miss sequence    large penalty
```

---

# 100. Free-turn conversion

Add a `FREE_TURN_CONVERSION` bonus when the action converts a favorable/denied opponent turn into:

- KO;
- critical recovery;
- weather reset;
- secure screen;
- winning positioning.

This should help Blizzard/Body Press/recovery outrank gratuitous extra setup after a miss.

---

# 101. Joint-action coordination features

The bot must score both active choices together.

Important positive synergies:

- Protect + partner removes threat;
- Follow Me + safe setup/attack;
- Wide Guard + partner Protect;
- weather reset + Blizzard/Veil setup;
- spread move + single-target cleanup;
- sacrificial pivot + preserved win condition.

Important negative synergies:

- redundant overkill;
- both actions into the same Protect with no hedge;
- Body Press into credible Ghost pivot without complementary coverage;
- Wide Guard while partner remains exposed to obvious single-target adaptation;
- Thunderbolt into a credible Lightning Rod pivot.

---

# 102. Robust scoring across opponent responses

For each candidate obtain:

```text
expected utility
credible bad-case utility
best-case utility
variance
```

A reasonable initial aggregation is:

```text
final response score
= 0.65 × weighted expected utility
+ 0.35 × credible bad-case utility
+ small robustness term
```

Exact coefficients are configuration.

The “bad case” should be the worst **credible** response, not the worst absurd theoretical line.

Use a relative plausibility threshold, initially perhaps ~0.15.

---

# 103. Robust reads

Prefer actions such as:

```text
+100 if opponent switches
+40 if opponent stays
```

over:

```text
+150 if exact read is correct
-120 if wrong
```

unless the high-variance action yields a forced win or the safer action cannot prevent losing.

The Heliolisk Thunderbolt into the low Archaludon/Basculegion slot is a canonical robust-read example.

---

# 104. Strong tactical rule layer

Strong rules should usually adjust scores **after** projection rather than immediately returning an action.

Examples:

```text
FOLLOW_ME_RESCUE
OBVIOUS_LETHAL_GLACEON
CASH_OUT
FAILED_WEATHER_DEPENDENT_MOVE
ABILITY_PUNISHMENT
ZERO_EFFECT
BASE_AGGRON_DANGER
```

Most strategic “hard rules” should remain strong penalties rather than absolute prohibitions because projected outcomes may supersede them.

Example:

```text
Mud-Slap into Defiant is terrible
```

but if the tiny damage itself wins the battle immediately, the ability boost never matters.

---

# 105. Absolute constraints

True absolute constraints should be rare and mostly architectural/legal:

- action absent from `request.legal_actions`;
- malformed participant response;
- hidden-information exploit;
- impossible semantic target.

Strategic actions should almost always be scored rather than blindly forbidden.

---

# 106. Turn dependency graph

Allowed dependencies:

| Component | May depend on |
|---|---|
| Mechanics | format/static data |
| Knowledge | BotState, history, mechanics |
| Mechanical features | knowledge, mechanics |
| Baseline threats | mechanical features, knowledge |
| Win conditions | threats, mechanical features, knowledge |
| Resource values | win conditions, knowledge |
| Opponent responses | threats, strategy, history |
| Projection | mechanics, mechanical state, actions/responses |
| Outcome features | projection, strategy, resources |
| Utility | features, weights |
| Tactical rules | scored outcomes, strategy, knowledge |
| Final ranking | final candidate evaluations |

Forbidden reverse/circular dependencies include:

- damage estimator asking whether Glaceon is primary;
- win-condition evaluator calling action scorer;
- resource value feeding back into win-condition viability;
- opponent response generation conditioning on the hidden candidate action currently being scored.

---

# 107. Complete turn pseudocode

```python
def choose_turn(state):
    mechanics = resolve_mechanics(state)

    knowledge = build_knowledge_state(
        state,
        mechanics,
    )

    mechanical = derive_mechanical_features(
        knowledge,
        mechanics,
    )

    baseline_threats = build_baseline_threats(
