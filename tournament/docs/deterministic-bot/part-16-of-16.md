- When should Ninetales be preserved versus sacrificed after snow is established?
- How should unusual Champions Mega abilities be valued before they reveal if OTS is not sufficient?
- How much risk aversion is optimal in the response aggregator?
- How much does opponent-history weighting improve play compared with purely tactical response generation?

---

# 149. Final policy statement

The v1 policy can be summarized as:

> **Construct a public-information model of the battle, identify which of Glaceon, Mega Aggron, or immediate offense is currently the best route to victory, preserve that route using deterministic control whenever possible, model a small diverse set of credible opponent responses, and choose the legal joint action that performs best across those responses. Use evasion and accuracy denial to improve expected outcomes, but never mistake them for guaranteed safety. When a free turn appears, convert it into concrete progress.**

---

# 150. Codex handoff — first task

Do **not** begin by implementing the heuristic bot.

Start with **Workstream A: Champions Tournament Harness Compatibility** on a separate branch.

The first Codex task should be:

> Inspect the existing `tournament-bot-v1` implementation and audit it against the exact `[Gen 9 Champions] VGC 2026 Reg M-B` format that will be used for the tournament. Focus on format/mod resolution, bring-6/pick-4 Team Preview, Open Team Sheets, Mega Evolution, Tera assumptions, legal transformation actions in doubles, public form/ability state tracking, Champions custom forms/abilities/items/moves, and Stat Points validation. Do not implement snow-team strategy. Produce a written compatibility report first, identify any required schema/harness changes, and propose a small phased implementation plan with simulator-backed tests before making large changes.

After Workstream A is stable, implement Workstream B phase-by-phase using this document as the behavioral specification.

