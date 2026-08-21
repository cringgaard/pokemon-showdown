# Pokémon Showdown Bot Tournament
## Deterministic Snow-Team Bot — Complete Implementation Design

**Status:** Implementation specification / Codex handoff draft  
**Target battle format:** `[Gen 9 Champions] VGC 2026 Reg M-B`  
**Current harness branch reviewed:** `tournament-bot-v1`  
**Reviewed harness commit:** `f474fa4622b419207f80c415c167e0f7cfe13ec4`  
**Policy type:** deterministic, heuristic, shallow one-turn response evaluation  
**Primary purpose:** establish a reproducible and interpretable first tournament bot before experimenting with learned weights, RL, sequence models, or LLM-based policies.

---

# 1. Executive summary

This document specifies the first serious bot for the Pokémon Showdown Bot Tournament. The bot is deliberately **not** intended to be a general optimal Pokémon AI. It is a deterministic policy specialized around the current snow/control team and around the strategic principles learned through extensive manual ladder testing.

The team evolved from an evasion gimmick into a more coherent defensive-control strategy. The central idea is:

> **Use deterministic control first, probabilistic denial second, and convert every free turn into concrete progress.**

The team tries to make the opponent's actions unreliable through several complementary layers:

1. **Deterministic prevention** — Protect, Follow Me, Wide Guard, immunity pivots, weather control, Encore.
2. **Probabilistic denial** — Snow Cloak, Bright Powder, Mud-Slap accuracy drops.
3. **Punishment and conversion** — Blizzard, Freeze-Dry, Body Press, Heavy Slam, direct KOs, Wish recovery, safe repositioning.

The strongest repeated lesson from manual testing was that the bot should **not maximize setup**. It should preserve whichever Pokémon is currently the actual win condition and then cash out advantages as soon as deterministic progress is available. In practice, `+1` or `+2` is usually enough for Glaceon and Mega Aggron.

The current six are:

1. **Glaceon** — snow fortress / special win condition.
2. **Ninetales-Alola** — weather reset, Aurora Veil, Freeze-Dry, Encore.
3. **Maushold** — Friend Guard, Follow Me, Encore, Mud-Slap.
4. **Aggron / Mega Aggron** — physical fortress / Body Press win condition.
5. **Armarouge** — Wide Guard, Flash Fire, Ally Switch, anti-spread-Fire patch.
6. **Heliolisk** — Dry Skin anti-rain pressure, Focus Sash utility, fast Water punishment.

The policy should have two main strategic plans and one fallback mode:

- `GLACEON_FORTRESS`
- `AGGRON_FORTRESS`
- `TACTICAL_OFFENSE`

These should be represented as **continuous viability scores**, not only as a single categorical label. The current primary win condition can therefore change as the battle develops.

The implementation should be built around the public `BotState` already produced by the tournament harness. It should not parse raw Showdown protocol from scratch for information the harness already normalizes. Instead it should construct a deterministic `KnowledgeState` on top of the supplied snapshot and history, derive threats and plausible opponent responses, project one turn approximately, extract numeric features, score them, and choose the best legal joint action.

The architecture must preserve a strict boundary:

> **Pokémon Showdown remains the authoritative battle engine. The bot may reuse format-aware Showdown data and safe mechanics helpers, but it must not recreate a second general-purpose simulator or read hidden live battle state.**

A separate Codex workstream must audit the existing tournament harness against the actual Champions format because the current harness was originally developed around Gen 9 VGC assumptions and exposes Tera-specific fields. Mega Evolution, Champions custom forms and abilities, transformation legality, Open Team Sheet behavior, and Stat Points must be verified before the participant interface is treated as stable.

---

# 2. Goals

The first deterministic bot should be:

- deterministic;
- reproducible;
- explainable;
- easy to regression-test;
- specialized enough to exploit the current team's strategic structure;
- general enough that the implementation is built from reusable tactical concepts rather than opponent-name scripts;
- able to coordinate both active Pokémon as one joint action;
- robust against several plausible opponent responses rather than betting everything on one prediction;
- designed so handcrafted scoring weights can later be optimized automatically;
- a useful baseline and data generator for later ML/RL/transformer/LLM policies.

The policy should reproduce the **decision-making principles** discovered in manual testing, not mechanically reproduce every historical move.

---

# 3. Non-goals for v1

The first version should not attempt to implement:

- reinforcement learning;
- neural networks;
- transformers;
- LLM calls;
- Monte Carlo tree search;
- exhaustive minimax;
- deep multi-turn search;
- exact probabilistic inference over all hidden sets;
- a second complete Pokémon battle engine;
- opponent-specific scripts keyed to player names;
- a hardcoded response for every species;
- perfect exact damage calculation as a prerequisite.

These may be explored after the deterministic baseline exists.

---

# 4. Current team specification

## 4.1 Glaceon

```text
Glaceon @ Bright Powder
Ability: Snow Cloak
Level: 50
Stat Points: 32 HP / 2 Def / 32 SpD
Calm Nature

- Calm Mind
- Blizzard
- Wish
- Protect
```

### Role

Primary snow fortress and special win condition.

The intended defensive stack is:

```text
Snow
+ Ice-type Defense bonus
+ Snow Cloak
+ Bright Powder
+ Aurora Veil
+ Calm Mind
+ Wish / Protect
```

### Policy principles

- First Calm Mind: usually high value if safe.
- Second Calm Mind: still valuable if safe.
- Third Calm Mind: much smaller value.
- Fourth+: normally negligible unless truly free.
- `+2 alive > +3 dead` is a hard strategic principle.
- Strongly prefer Protect when both opponents plausibly focus Glaceon and the partner can make progress.
- Wish is valuable when it establishes a credible Wish → Protect recovery cycle.
- Do not Wish when immediate Blizzard pressure wins the position.
- When evasion creates a free turn, prefer KO/recovery/weather control over greedier setup.
- Blizzard in snow should be valued very differently from Blizzard outside snow.

---

## 4.2 Ninetales-Alola

```text
Ninetales-Alola @ Icy Rock
Ability: Snow Warning
Level: 50
Stat Points: 2 HP / 32 SpA / 32 Spe
Timid Nature

- Aurora Veil
