- feature definitions initially.

This creates a low-dimensional and interpretable first RL/optimization experiment.

---

# 137. Future sequence-model data

The deterministic bot can log:

```text
state
history
legal actions
opponent response hypotheses
feature vectors
heuristic scores
chosen action
eventual battle result
```

Potential future training tasks:

- imitation: `state → heuristic action`;
- ranking: `state + action → heuristic score`;
- value: `state → eventual outcome`;
- sequence modelling: `battle history → next action / event / win probability`.

The public `BotState → BotResponse` contract should remain shared across heuristic, RL, transformer and LLM bots where possible.

---

# 138. Feature ablation

The modular design should allow experiments such as:

- disable Mud-Slap value;
- disable history weighting;
- disable bad-case robustness;
- disable win-condition-aware resource values;
- disable switch-response modelling.

Compare win rate and decision quality.

This is important because intuitively attractive heuristics are not guaranteed to help.

---

# 139. Mechanics tests versus policy tests

For important mechanics, pair:

```text
Showdown integration test
```

with:

```text
policy regression test
```

Example:

```text
Mechanics test:
No Guard bypasses relevant accuracy/evasion interaction.

Policy test:
Glaceon no longer receives evasion survival value against that attacker.
```

Showdown tests prove mechanics. Policy tests prove decisions.

---

# 140. Champions mechanics tests requested in Workstream A

At minimum verify actual target-format behavior for:

- Mega Aggron transformation, typing and ability;
- Mega Charizard X;
- Mega Charizard Y + Drought;
- Mega Raichu X;
- Mega Raichu Y + No Guard;
- Snow Cloak + Bright Powder;
- Aurora Veil weather requirement;
- Pelipper switch → Drizzle → Veil sequencing;
- Fake Out vs Follow Me priority;
- Wide Guard versus spread;
- Body Press versus Ghost;
- Defiant/Competitive/Contrary interactions;
- Gravity/evasion interaction;
- transformation legality across two doubles slots.

These tests should run through actual Showdown mechanics rather than a copied formula.

---

# 141. Codex branch / PR strategy

Prefer reviewable, concept-focused changes.

Conceptual split:

```text
A1 champions-format-audit
A2 champions-harness-fixes
A3 champions-mechanics-tests

B1 heuristic-bot-foundations
B2 heuristic-bot-preview
B3 heuristic-bot-threat-model
B4 heuristic-bot-projection
B5 heuristic-bot-policy
B6 heuristic-bot-regressions
```

Exact branch names are unimportant.

Each PR should establish one conceptual layer plus tests.

---

# 142. Codex execution protocol

For each phase, Codex should first:

1. inspect relevant repository code;
2. summarize existing architecture;
3. identify reusable components;
4. state proposed modifications;
5. implement;
6. run tests;
7. report discrepancies between the design and actual repository behavior.

Codex should not silently implement an assumed solution if repository mechanics disagree with this document.

---

# 143. Codex deviation policy

If the design conflicts with actual Showdown behavior or harness architecture, Codex should report:

```text
design assumption
actual repository behavior
recommended resolution
```

Then choose the smallest architecturally sound change.

This is especially important for:

- Mega action representation;
- Tera assumptions;
- transformation ordering;
- Champions-specific mechanics.

---

# 144. Codex implementation discretion

Codex may choose:

- module/class organization;
- exact file names;
- fixture representation;
- configuration format;
- cache structure;
- logging implementation;
- internal type names.

Codex should preserve:

- deterministic policy;
- public-information-only boundary;
- Showdown mechanics authority;
- complete legal joint action source from harness;
- joint-action evaluation;
- mechanical/strategic separation;
- dynamic win-condition scoring;
- response distribution independent of current hidden candidate;
- shallow rather than complete simulation;
- numeric feature/weight separation;
- traceable scoring;
- regression-first development.

---

# 145. Definition of done — Workstream A

Champions harness compatibility is ready when:

- exact tournament format/mod is identified;
- public information semantics are documented;
- Team Preview is correct;
- transformations are exposed semantically and legally;
- Tera assumptions are resolved;
- Champions forms/abilities/items/moves are represented correctly;
- Stat Points rules are validated;
- key Champions mechanics integration tests pass;
- reference bots can complete actual-format matches through the participant API.

---

# 146. Definition of done — deterministic bot v1

The deterministic bot is v1-complete when:

- it selects legal Bring-4 and leads;
- it completes full target-format battles without manual intervention;
- all decisions are deterministic;
- each decision has a readable structured trace;
- current-team moves are modelled with high strategic fidelity;
- major battle-derived mechanics are represented;
- multiple plausible opponent responses are generated;
- Glaceon/Aggron/tactical-offense viability updates dynamically;
- P0 regression suite passes;
- most core P1 regressions pass;
- simulator-sensitive assumptions are verified against Showdown;
- hidden opponent state is never accessed;
- no second general-purpose Pokémon simulator exists in the policy.

---

# 147. Recommended first post-v1 experiment

Once v1 passes acceptance tests, pause architectural expansion and run a meaningful match batch.

Collect:

- outcomes;
- preview selections;
- leads;
- win-condition trajectory;
- selected action score margins;
- top alternatives;
- feature contributions;
- response-set composition;
- mechanic uncertainty;
- runtime/latency.

Manually inspect a stratified sample of:

- wins;
- losses;
- narrow decisions;
- large-score mistakes;
- unusual opponent lines.

Use failure classification to decide v1.1 changes.

---

# 148. Open questions to resolve empirically

These should remain experiments rather than premature hard rules:

- Is Heliolisk better than the removed Incineroar slot over a larger matchup sample?
- Is Colbur Berry optimal on Armarouge?
- Should Armarouge eventually run Protect instead of Ally Switch?
- Is Mud-Slap better than the old Super Fang concept across larger samples?
- What is the best standard rain Bring-4 when Lightning Rod is absent?
