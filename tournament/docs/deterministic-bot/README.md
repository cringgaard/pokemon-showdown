# Deterministic Snow-Team Bot implementation design

This directory contains the complete implementation specification for the deterministic snow-team tournament bot.

The source document is split into numbered parts only to keep the repository write/review workflow manageable. **Read the parts in numeric order as one continuous document.** No content is intentionally omitted between parts.

Target format: `[Gen 9 Champions] VGC 2026 Reg M-B`

Reviewed harness baseline: `tournament-bot-v1` at `f474fa4622b419207f80c415c167e0f7cfe13ec4`.

## Reading order

1. `part-01-of-16.md`
2. `part-02-of-16.md`
3. `part-03-of-16.md`
4. `part-04-of-16.md`
5. `part-05-of-16.md`
6. `part-06-of-16.md`
7. `part-07-of-16.md`
8. `part-08-of-16.md`
9. `part-09-of-16.md`
10. `part-10-of-16.md`
11. `part-11-of-16.md`
12. `part-12-of-16.md`
13. `part-13-of-16.md`
14. `part-14-of-16.md`
15. `part-15-of-16.md`
16. `part-16-of-16.md`

The document deliberately separates two Codex workstreams:

- **Workstream A — Champions Tournament Harness Compatibility:** audit and correct format/mod, Mega/Tera, OTS, transformation, Stat Points, and custom Champions assumptions in the harness.
- **Workstream B — Deterministic Snow-Team Bot:** implement the heuristic policy only after the public tournament interface/mechanics boundary is correct.

Start with Workstream A. Do not implement the snow-team policy as part of the compatibility audit.
