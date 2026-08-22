# Deterministic snow policy

This package contains the public-information foundation and static mechanics boundary for the deterministic Champions snow-team bot. It consumes the semantic `BotState.schema_version == 2` dictionary supplied to participant Python and does not import Pokemon Showdown simulator code.

The package intentionally has no `choose_action()` entrypoint yet.

## Modules

- `knowledge.py` builds an immutable, policy-facing `KnowledgeState`. It keeps apparent and established opponent identity separate, carries explicit certainty/provenance, reconstructs selected-four knowledge from public history, preserves move provenance, and provides typed extension points for later temporal derivations.
- `mechanics.py` consumes a hash-verified, format-aware JSON snapshot generated from Showdown's `Dex.forFormat('gen9championsvgc2026regmb')`. It exposes deterministic species/form, move, item, ability, type-effectiveness and narrowly annotated semantic mechanics without simulating a turn.
- `actions.py` canonicalizes only actions already present in `request.legal_actions`. Its versioned SHA-256 IDs cover Team Preview order, slot, action kind, target, and transformation.
- `config.py` validates strict configuration sections for versions, feature weights, thresholds, opponent responses, runtime degradation, and team roles. Current feature weights remain deliberately untuned zeros.
- `features.py` owns stable feature IDs and metadata. It never owns weights.
- `trace.py` defines serializable version, strategy, response, candidate, feature-contribution, rule-adjustment, selection, and runtime records without implementing a scorer.

## Mechanics boundary

Showdown remains the mechanics authority. The snapshot exporter lives in `tournament/mechanics/champions-snapshot.ts`; final bot packaging should generate its JSON from the exact tournament Showdown revision and include the artifact beside the Python policy.

Python is intentionally limited to static lookups and simple deterministic composition such as multiplying type-chart entries for dual-type targets. Callback-backed mechanics such as Freeze-Dry, No Guard, Wide Guard, Snow Cloak and item effects are exposed through explicit semantic annotations which are regression-tested against the format-aware Showdown source/mechanics.

All policy JSON output uses stable ordering and finite numbers so identical public inputs reconstruct and serialize identically across worker restarts.

Later phases may populate history-derived structures and perform shallow tactical projection, but must retain the one-way dependency from public state and generated mechanics into policy logic, and must continue treating `request.legal_actions` as authoritative.
