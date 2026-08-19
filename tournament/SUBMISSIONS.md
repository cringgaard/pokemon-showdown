# Tournament participant submissions

A participant is a directory containing:

```text
my-bot/
├── main.py
├── team.txt
├── requirements.txt     # optional; dependencies are not installed in Milestone 2A
└── other assets         # optional
```

`main.py` must define one function:

```python
def choose_action(state):
    return state["request"]["legal_actions"][0]
```

The module is loaded once in a persistent Python process for a match, so module-level model/config loading and
in-process state are supported. A worker may be restarted after a timeout, so persistent state must not be required
for correctness. Participant stdout is captured as runtime output; it cannot corrupt the JSONL worker protocol.

`team.txt` must be a human-readable Pokemon Showdown export containing exactly six Pokemon. Preflight uses
Pokemon Showdown's `Teams.import` and `TeamValidator` for the configured format. Invalid teams are reported and are
never repaired automatically. Packed and JSON team representations are rejected.

Validate a submission:

```bash
node dist/tournament/cli.js validate path/to/my-bot
```

Run two submissions:

```bash
node dist/tournament/cli.js match path/to/alice path/to/bob --seed 1234 --output results/alice-vs-bob
```

Every actionable state supplies all complete valid public responses in `state["request"]["legal_actions"]`. Stable
own-team IDs are `team_0` through `team_5`; Open Team Sheet opponent IDs are `opponent_0` through `opponent_5`.
The same `choose_action` function handles Team Preview, ordinary turns, and forced switches. The runtime retries
invalid responses, enforces the shared decision deadline, and uses a deterministic legal fallback after failures.

Participant dependencies are not installed and participant code is not sandboxed in Milestone 2A. Only run trusted
submissions in this version.

Participant display names and machine IDs must be unique within a match. Result artifacts record the winning side
and participant ID in addition to Showdown's display-name winner.
