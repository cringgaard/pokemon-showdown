# Deterministic snow policy

This package contains the public-information foundation, static mechanics boundary, and temporal knowledge reconstruction for the deterministic Champions snow-team bot. It consumes the semantic `BotState.schema_version == 2` dictionary supplied to participant Python and does not import Pokemon Showdown simulator code.

The package intentionally has no `choose_action()` entrypoint yet.

## Modules

- `knowledge.py` contains the immutable B1 public-information foundation. It keeps apparent and established opponent identity separate, carries explicit certainty/provenance, reconstructs conservative selected-four knowledge, and preserves move provenance.
- `reconstruction.py` is the B3 policy-facing knowledge layer. Its package-level `build_knowledge_state()` deterministically reconstructs Protect chains, switch chronology, move/target history, public damage observations, mechanics-qualified speed-order evidence, weather provenance, current timed-condition records, and Fake Out eligibility. Correctness is rebuilt from the supplied state/history rather than relying on persistent worker memory.
- `mechanics.py` consumes a hash-verified, format-aware JSON snapshot generated from Showdown's `Dex.forFormat('gen9championsvgc2026regmb')`. It exposes deterministic species/form, move, item, ability, type-effectiveness and narrowly annotated semantic mechanics without simulating a turn.
- `actions.py` canonicalizes only actions already present in `request.legal_actions`. Its versioned SHA-256 IDs cover Team Preview order, slot, action kind, target, and transformation.
- `config.py` validates strict configuration sections for versions, feature weights, thresholds, opponent responses, runtime degradation, and team roles. Current feature weights remain deliberately untuned zeros.
- `features.py` owns stable feature IDs and metadata. It never owns weights.
- `trace.py` defines serializable version, strategy, response, candidate, feature-contribution, rule-adjustment, selection, and runtime records without implementing a scorer.

## Mechanics boundary

The executable mechanics in this fork are definitive. Showdown remains the mechanics authority; the snapshot exporter lives in `tournament/mechanics/champions-snapshot.ts`. Final bot packaging should generate its JSON from the exact tournament Showdown revision and include the artifact beside the Python policy.

Python is intentionally limited to static lookups and simple deterministic composition such as multiplying type-chart entries for dual-type targets. Callback-backed mechanics are exposed only through explicit semantic annotations regression-tested against the format-aware Showdown implementation. If the snapshot does not completely resolve a contextual mechanic, Python raises `UnresolvedMechanicError` rather than silently substituting a generic rule.

B3 follows the same rule for temporal deductions. It records public observations even when their downstream interpretation is uncertain, and only derives mechanics-sensitive facts when the supplied mechanics snapshot supports the deduction. For example, a condition with a known public start turn may intentionally retain an unknown duration rather than copying a duration rule into the policy.

All policy JSON output uses stable ordering and finite numbers so identical public inputs reconstruct and serialize identically across worker restarts.

Later phases may derive threats and perform shallow tactical projection from this knowledge, but must retain the one-way dependency from public state and generated mechanics into policy logic, and must continue treating `request.legal_actions` as authoritative.
