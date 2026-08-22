These improve expected outcomes but should not be treated as guaranteed safety.

## 5.3 Layer C — punishment and conversion

Examples:

- Blizzard;
- Freeze-Dry;
- Body Press;
- Heavy Slam;
- Armor Cannon;
- Psychic;
- Thunderbolt;
- Grass Knot;
- Wish recovery;
- weather reset;
- safe repositioning.

The team performs best when a denied or missed opponent action is converted immediately into this layer.

---

# 6. Core strategic maxims

The following principles should be visible in the implementation and regression suite.

1. **Deterministic protection beats speculative accuracy denial when protecting the real win condition.**
2. **+2 alive is better than +3 dead.**
3. **Cash out a free turn.** A miss or strong prediction should lead to KO, recovery, screen, weather reset or better positioning.
4. **Preserve strategic resources, not merely HP.** A 1% Ninetales or Heliolisk may still be extremely valuable.
5. **Do not confuse current form with future form.** Base Aggron is not Mega Aggron.
6. **Do not confuse known mechanics with opponent prediction.** Ghost immunity is a fact; a Gourgeist switch is a hypothesis.
7. **Joint actions matter.** The two active Pokémon must be evaluated together.
8. **Robust reads are preferable to coin-flip reads.** Prefer actions that perform acceptably across multiple plausible opponent responses.
9. **Weather is a state machine.** Evaluate what weather exists when an action resolves, not only when the decision starts.
10. **The psychological frustration of evasion is not itself a bot objective.** Only actual probabilities, switch incentives and tactical consequences matter.

---

# 7. Separate implementation workstreams

Two concerns must remain separate.

## Workstream A — Champions tournament harness compatibility

Question:

> Is the tournament environment and public participant interface correct for the actual Champions format?

This workstream owns:

- format ID and mod identification;
- bring-6/pick-4 behavior;
- Open Team Sheet semantics;
- Mega Evolution representation and legality;
- Tera availability or absence;
- transformation API design;
- Champions custom Mega forms, abilities, items and moves;
- Stat Points validation;
- participant-visible information correctness;
- legal-action generation;
- mechanics integration tests.

It must not implement snow-team strategy.

## Workstream B — deterministic snow-team policy

Question:

> Given a correct public environment, how should this team play?

This workstream owns:

- `KnowledgeState`;
- threat model;
- team preview policy;
- dynamic win conditions;
- opponent response generation;
- shallow projection;
- feature scoring;
- configuration;
- traces;
- regression suite;
- deterministic action selection.

It must not change Showdown battle mechanics.

---

# 8. Current harness facts and compatibility risk

The reviewed `tournament-bot-v1` branch already contains a strong architectural foundation.

Relevant files include:

```text
tournament/api/types.ts
tournament/state/state-builder.ts
tournament/state/state-tracker.ts
tournament/state/protocol-parser.ts
tournament/actions/action-generator.ts
tournament/DESIGN.md
```

The public state already provides:

- battle phase and turn;
- exact own team state from the current ChoiceRequest;
- observed opponent roster and active state;
- side conditions;
- weather and field conditions;
- complete public history;
- complete legal joint actions;
- team-preview legal actions.

The current interface is explicitly Tera-aware through fields such as:

```text
tera_type
terastallized
can_terastallize
```

and action generation expands Tera variants. This is a compatibility risk because the target Champions format used for team testing involves Mega Evolution and may have different transformation rules.

Therefore Workstream A must audit the harness before the API is considered stable.

---

# 9. Tournament-format compatibility boundary

The policy must be specified against **semantic public battle state**, not against assumptions from a particular old VGC regulation.

The policy should treat:

```text
state.request.legal_actions
```

as authoritative for what it can legally do.

It should not independently assume:

- Tera exists;
- Tera does not exist;
- Mega Evolution uses any particular syntax;
- only one transformation mechanic exists;
- a transformation occurs at a particular stage without verification;
- standard Gen 9 species data is sufficient for Champions.

The harness must expose the actual configured format correctly.

---

# 10. Workstream A — Champions audit requirements

Codex should answer these questions directly from the repository.

## 10.1 Format

- What exact Showdown format ID corresponds to the tournament?
- What mod does `Dex.forFormat(format)` resolve?
- Are all Champions-specific data/scripts loaded through that mod?

## 10.2 Team Preview

- Does the format use bring-6/pick-4?
- Are the two leads represented correctly?
- Is preview order meaningful beyond the two lead slots?

## 10.3 Open Team Sheets

Verify exactly what the player-visible stream exposes:

- species/form;
- moves;
- item;
- ability;
- Mega stone/transformation information;
- Tera data if relevant;
- other public information.

## 10.4 Mega Evolution

Determine:

- how Mega is represented in `ChoiceRequest`;
- how a participant requests it semantically;
- per-turn/per-team restrictions;
- cross-slot constraints in doubles;
- how the active form/ability/typing is exposed afterward;
- whether the current state tracker handles the relevant form-change events.

## 10.5 Terastallization

Determine:

- whether Tera is legal in the target Champions format;
- whether current Tera-specific public fields should remain, be removed, or be generalized;
- interaction with Mega if both somehow exist.

## 10.6 Champions custom content

Verify:

- Mega Raichu X;
- Mega Raichu Y;
- Mega Meganium variants;
- Mega Staraptor/Contrary behavior;
- Mega Aggron;
- Mega Charizard X/Y;
- other custom Mega forms;
- custom abilities;
- custom moves/items;
- custom move behavior relevant to the format.

## 10.7 Stat Points

Verify the actual Champions rule implementation used during team construction, including the observed 32-per-stat / 66-total constraint if that remains authoritative.

## 10.8 Deliverables

Workstream A should produce:

1. written compatibility findings;
2. required harness changes;
3. implemented fixes;
4. updated BotState/response schema if necessary;
