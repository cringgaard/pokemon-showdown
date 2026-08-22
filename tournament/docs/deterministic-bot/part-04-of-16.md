5. transformation support;
6. Champions integration tests;
7. exact format/mod identification;
8. a recommendation for format-aware mechanics data access/export.

## 10.9 Acceptance gate

Workstream A is complete when two simple reference bots can play full matches in the actual target Champions format through the participant API, including team preview, transformations, switches, moves, forced switches, custom forms and battle completion without needing raw Showdown choice syntax.

---

# 11. Reuse Showdown; do not recreate Showdown

The deterministic policy should use this hierarchy:

```text
1. authoritative facts in BotState
2. format-aware reusable Showdown data/helpers
3. empirical observations in public history
4. small policy-specific semantic models
5. coarse approximation when exact mechanics are unnecessary
```

The policy must not independently recreate:

- `Battle`;
- `BattleActions`;
- `BattleQueue`;
- `Side`;
- `Pokemon`;
- full event dispatch;
- arbitrary move/ability/item callback execution.

Pokémon Showdown already implements those things.

---

# 12. Mechanics categories

## 12.1 Level A — static mechanics

Prefer format-aware Showdown data for:

- species/forms;
- typing;
- base stats;
- move type/category/priority/accuracy/base power/targeting/flags;
- items;
- abilities;
- type chart;
- format/mod relationships.

`Dex.forFormat(actualFormat)` should be the starting point if appropriate.

## 12.2 Level B — simple deterministic derived mechanics

Examples:

- Fighting into Ghost is immune;
- current stat-stage multipliers;
- move is spread or single-target;
- current weather;
- current boost stages;
- current form typing;
- simple type effectiveness.

Where practical, reuse Showdown helpers such as format-aware immunity/effectiveness rather than transcribing mechanics into Python.

## 12.3 Level C — contextual battle resolution

Examples:

- full damage callbacks;
- targeting/redirection chains;
- move callbacks;
- entry ability ordering;
- random secondary effects;
- multi-hit logic;
- arbitrary event interactions.

The shallow evaluator should model only the strategic consequences it actually needs. If exact behavior becomes important, prefer a narrow Showdown-backed helper or simulator integration test over expanding into a second battle engine.

---

# 13. Mechanics adapter / static export

Because the participant bot is Python while Showdown is TypeScript, the recommended v1 approach is likely a compact format-specific mechanics export generated from the configured Showdown mod.

Conceptually:

```text
Showdown format/mod
      ↓
mechanics export
      ↓
Python policy
```

Potential generated artifacts:

```text
format.json
species.json
moves.json
abilities.json
items.json
typechart.json
```

The export should contain data, not serialized executable callbacks.

If strategically important behavior lives in a callback, use one of:

1. safe Showdown-backed query/helper;
2. semantic policy annotation backed by an integration test;
3. coarse/uncertain modelling.

---

# 14. Public-information fairness boundary

Even though the policy lives in the same repository as the simulator, it must never inspect hidden live opponent state.

Forbidden examples:

```text
liveBattle.p2.pokemon[...] hidden moves/stats
liveBattle.p2.choice
actual selected-four identities before public reveal
hidden items/abilities not publicly available
```

Reusable Showdown helpers must operate only on:

- public `BotState`;
- public static Dex data;
- explicit hypothetical assumptions.

The fact that the code is colocated does not make hidden information fair.

---

# 15. High-level policy architecture

The turn pipeline is:

```text
BotState
   ↓
Resolved Mechanics
   ↓
KnowledgeState
   ↓
Derived Mechanical Features
   ↓
Baseline Threat Model
   ↓
Runtime Win-Condition Scores
   ↓
Strategic Resource Values
   ↓
Opponent Response Set
   ↓
Our Legal Joint Actions
   ↓
Action × Response Projection
   ↓
Outcome Feature Extraction
   ↓
Per-Response Utility
   ↓
Robust Response Aggregation
   ↓
Tactical Rule Adjustments
   ↓
Deterministic Ranking
   ↓
Chosen Action
```

No later stage should mutate or redefine an earlier stage.

---

# 16. Determinism

Given the same:

- `BotState`;
- mechanics snapshot;
- team configuration;
- policy weights;
- policy version;

the bot must always return the same response.

No unseeded randomness should be used in policy selection.

Stable tie-break order should be something like:

1. final score;
2. credible bad-case score;
3. expected score;
4. primary win-condition survival;
5. immediate opponent KOs;
6. canonical action key.

The exact tie-breaker syntax is implementation detail; reproducibility is not.

---

# 17. BotState is the public boundary

The bot should not parse raw protocol from scratch for facts already normalized by the harness.

The current public API already exposes, conceptually:

```text
battle
runtime
self
opponent
field
request
history
```

For own Pokémon it exposes exact current state including current stats, boosts, item, ability, moves and volatiles where available.

For the opponent it exposes public/OTS roster information and active observations without inventing hidden precision.

The bot should build a narrower policy-specific `KnowledgeState` on top of this public contract.

---

# 18. Information-source hierarchy

When facts conflict, prefer:

```text
1. current BotState snapshot
2. explicit public history
3. public format-aware static mechanics
4. deterministic deductions from 1–3
5. heuristic inference
```

Never silently promote inference into observation.

Example:

```text
prior: Charizard could be Y
observed form: Mega Charizard X
→ Y/Drought hypothesis removed
```

---

# 19. Knowledge certainty

The internal model should distinguish:

```text
OBSERVED
DERIVED
INFERRED
UNKNOWN
```

Examples:

```text
OBSERVED:
Sneasler used Close Combat.
Pelipper ability is Drizzle from OTS.
Glaceon currently has +2 SpD.

DERIVED:
Close Combat threatens Aggron.
Pelipper entry activates Drizzle.
Body Press cannot damage a known Ghost.

INFERRED:
Pelipper is likely to switch in.
Sneasler may target Aggron again.
Tyranitar may Protect at 9%.

UNKNOWN:
which unrevealed roster Pokémon are in the selected four;
exact hidden opponent defensive stats;
opponent's current simultaneous action.
```

---

# 20. KnowledgeState

Conceptually:

```python
KnowledgeState:
    snapshot

    own_team
    opponent_roster
    opponent_selected_four_model
