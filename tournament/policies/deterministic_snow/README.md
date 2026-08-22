# Deterministic snow policy foundations

This package is the B1 public-information foundation for the deterministic Champions snow-team bot. It consumes only the semantic `BotState.schema_version == 2` dictionary supplied to participant Python and does not import Pokémon Showdown simulator code.

The package intentionally has no `choose_action()` entrypoint yet.

## Modules

- `knowledge.py` builds an immutable, policy-facing `KnowledgeState`. It keeps apparent and established opponent identity separate, carries explicit certainty/provenance, represents selected-four knowledge, preserves public history, and provides typed extension points for later temporal derivations.
- `actions.py` canonicalizes only actions already present in `request.legal_actions`. Its versioned SHA-256 IDs cover Team Preview order, slot, action kind, target, and transformation.
- `config.py` validates strict configuration sections for versions, feature weights, thresholds, opponent responses, runtime degradation, and team roles. Default B1 feature weights are deliberately untuned zeros.
- `features.py` owns stable feature IDs and metadata. It never owns weights.
- `trace.py` defines serializable version, strategy, response, candidate, feature-contribution, rule-adjustment, selection, and runtime records without implementing a scorer.

All JSON output uses sorted keys, finite numbers, and compact separators so identical public inputs reconstruct and serialize identically across worker restarts.

Later phases may populate the history-derived structures and traces, but must retain the one-way dependency from public state into knowledge and must continue treating `request.legal_actions` as authoritative.
