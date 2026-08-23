# Deterministic snow policy

This package contains the public-information foundation, static mechanics boundary, temporal knowledge reconstruction, baseline threat model, and runtime strategy valuation for the deterministic Champions snow-team bot. It consumes the semantic `BotState.schema_version == 2` dictionary supplied to participant Python and does not import Pokemon Showdown simulator code.

The package intentionally has no `choose_action()` entrypoint yet.

## Modules

- `knowledge.py` contains the immutable B1 public-information foundation. It keeps apparent and established opponent identity separate, carries explicit certainty/provenance, reconstructs conservative selected-four knowledge, and preserves move provenance.
- `reconstruction.py` is the B3 policy-facing knowledge layer. Its package-level `build_knowledge_state()` deterministically reconstructs Protect chains, switch chronology, move/target history, public damage observations, mechanics-qualified speed-order evidence, weather provenance, current timed-condition records, and Fake Out eligibility. Correctness is rebuilt from the supplied state/history rather than relying on persistent worker memory.
- `mechanics.py` consumes a hash-verified, format-aware JSON snapshot generated from Showdown's `Dex.forFormat('gen9championsvgc2026regmb')`. It exposes deterministic species/form, move, item, ability, type-effectiveness and narrowly annotated semantic mechanics without simulating a turn.
- `threats.py` is the B4 mechanics-to-threat boundary. It classifies known opponent moves, produces coarse public-information damage/KO bands for each active slot, preserves uncertainty when exact mechanics or opponent stats are unavailable, and summarizes double-target/status/control risk without assigning strategic importance to our targets.
- `strategy.py` is downstream from the threat model. It continuously scores `GLACEON_FORTRESS`, `AGGRON_FORTRESS`, and `TACTICAL_OFFENSE`, applies configured interpretation thresholds, and then derives context-sensitive resource values with a configurable nonlinear HP utility curve. Resource values never feed back into the win-condition calculation.
- `actions.py` canonicalizes only actions already present in `request.legal_actions`. Its versioned SHA-256 IDs cover Team Preview order, slot, action kind, target, and transformation.
- `config.py` validates strict configuration sections for versions, action-feature weights, B4 strategy/resource weights, interpretation thresholds, opponent responses, runtime degradation, HP utility, and team roles. B4 scalar heuristic values have stable names in configuration rather than being buried in policy logic; action-scoring feature weights remain deliberately untuned zeros.
- `features.py` owns stable feature IDs and metadata. It never owns weights.
- `trace.py` defines serializable version, strategy, response, candidate, feature-contribution, rule-adjustment, selection, and runtime records without implementing a scorer.

## Mechanics boundary

The executable mechanics in this fork are definitive. Showdown remains the mechanics authority; the snapshot exporter lives in `tournament/mechanics/champions-snapshot.ts`. Final bot packaging should generate its JSON from the exact tournament Showdown revision and include the artifact beside the Python policy.

Python is intentionally limited to static lookups and simple deterministic composition such as multiplying type-chart entries for dual-type targets. Callback-backed mechanics are exposed only through explicit semantic annotations regression-tested against the format-aware Showdown implementation. If the snapshot does not completely resolve a contextual mechanic, Python raises `UnresolvedMechanicError` rather than silently substituting a generic rule.

B3 follows the same rule for temporal deductions. It records public observations even when their downstream interpretation is uncertain, and only derives mechanics-sensitive facts when the supplied mechanics snapshot supports the deduction. For example, a condition with a known public start turn may intentionally retain an unknown duration rather than copying a duration rule into the policy.

B4 damage values are explicitly coarse. Champions OTS does not expose opponent Stat Points, so fallback damage estimates use format-aware move/type mechanics, a neutral public base-stat proxy, exact own defensive stats and deliberately broad bounds. Comparable non-critical public damage observations take precedence. These estimates are for threat bands and KO confidence, not a second general-purpose simulator.

The dependency direction is intentionally one-way:

```text
BotState + generated mechanics
        ↓
B3 public knowledge
        ↓
B4 baseline threats
        ↓
B4 win-condition viability
        ↓
B4 strategic resource values
```

Later phases may generate opponent responses and perform shallow tactical projection from these layers, but must continue treating `request.legal_actions` as authoritative and must not feed preferred strategy back into mechanical threat facts.
