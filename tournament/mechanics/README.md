# Tournament mechanics snapshots

The deterministic Python policy must reason about the exact tournament format without importing or recreating Pokemon Showdown's simulator.

For `[Gen 9 Champions] VGC 2026 Reg M-B`, `champions-snapshot.ts` resolves the authoritative mechanics with:

```ts
Dex.forFormat('gen9championsvgc2026regmb')
```

and exports a deterministic JSON snapshot containing the format/mod identity, type chart, species/forms, moves, abilities, items, Mega-stone mappings, and a small set of explicit semantic annotations for callback-backed mechanics needed by later policy stages.

## Boundary

The generated snapshot is static mechanics data, not a serialized `Battle` and not a second simulator. Python may use it for deterministic facts such as type effectiveness, immunity, form typing, move targeting, move metadata, and known semantic properties. Contextual turn resolution remains the responsibility of later projection code and must stay intentionally shallow.

Semantic annotations are interpretations of Showdown mechanics. Each annotation must be backed by format-aware Dex/source assertions or simulator regressions. Adding an annotation without a regression is a mechanics-boundary change and should be reviewed accordingly.

## Generation

After compiling the repository:

```sh
node dist/tournament/mechanics/champions-snapshot.js path/to/champions-mechanics.json
```

The output embeds:

- snapshot schema version;
- format ID and resolved mod;
- optional Showdown commit metadata from `GIT_COMMIT_SHA`;
- semantic-annotation version;
- a deterministic SHA-256 hash over the complete snapshot payload.

The Python consumer in `tournament/policies/deterministic_snow/mechanics.py` verifies the hash before accepting the snapshot. Final bot packaging should generate this artifact from the exact Showdown revision used by the tournament and package the resulting JSON alongside the Python policy.
