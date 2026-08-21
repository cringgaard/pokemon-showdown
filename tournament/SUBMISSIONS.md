# Tournament participant submissions

A participant is a directory containing:

```text
my-bot/
├── main.py
├── team.txt
├── requirements.txt     # optional; installed by pip during Docker preparation
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

Prepare/cache an isolated participant image:

```bash
node dist/tournament/cli.js prepare path/to/my-bot
```

Run two submissions with the default Docker isolation:

```bash
node dist/tournament/cli.js match path/to/alice path/to/bob --seed 1234 --output results/alice-vs-bob
```

The match command prepares both images before battle start. If Docker is missing, stopped, or a build fails, the match fails without starting and never silently runs participant code on the host. Trusted local development can opt in explicitly with `--runtime host`; this mode has no sandbox and must not be used for untrusted submissions.

Every actionable state supplies all complete valid public responses in `state["request"]["legal_actions"]`. Stable
own-team IDs are `team_0` through `team_5`; Open Team Sheet opponent IDs are `opponent_0` through `opponent_5`.
The same `choose_action` function handles Team Preview, ordinary turns, and forced switches. The runtime retries
invalid responses, enforces the shared decision deadline, and uses a deterministic legal fallback after failures.

## Bring 6 / Pick 4 Team Preview

Every game starts with Team Preview, including every game in a multi-game final. Your registered six-Pokemon team
stays fixed for the event, but your bot chooses and orders four Pokemon independently for each game. The first two
entries are the leads and the final two are reserves:

```python
def choose_action(state):
    if state["battle"]["phase"] == "team_preview":
        # self.team contains your six Pokemon. opponent.team contains only
        # the opponent's public Open Team Sheet information.
        preferred = {
            "team": [
                "team_4",  # lead 1
                "team_1",  # lead 2
                "team_0",  # reserve
                "team_5",  # reserve
            ]
        }
        # legal_actions is authoritative for complete legal responses.
        return preferred if preferred in state["request"]["legal_actions"] else state["request"]["legal_actions"][0]

    return state["request"]["legal_actions"][0]
```

Select exactly four distinct Pokemon. Ordering matters. Participant code returns semantic IDs and never needs to
generate Showdown's `team 1234` protocol syntax. Open Team Sheet information about the opponent may be used for the
decision, but no selected-four, lead, spectator, standings, or operator metadata is provided to bots.

Team Preview currently uses the same `decision_timeout_ms` as turn and forced-switch decisions. A separate timeout
was investigated for the presentation enhancement but was not added: enforcing it correctly would require a
phase-aware worker deadline in addition to config and runtime plumbing. The shared deadline keeps existing timeout
and deterministic-fallback guarantees unchanged; events that need more thinking time can raise the documented
general decision timeout.

The tournament generates all build definitions. Participant Dockerfiles and symlinks are rejected. Each non-comment
`requirements.txt` line must be an exact `name[extras]==version` registry pin. Installation runs non-root from a
trusted directory with isolated Python, `--only-binary=:all:`, and `--no-deps`; URLs, paths, editable/VCS/source
installs, pip options, markers, constraints, and dependency build hooks are rejected. List every required package
explicitly. Dependency retrieval may use network access during preparation; match containers have no network.
`requirements.txt` is limited to 64 KiB. Arbitrary regular model/configuration/assets are copied into `/submission`,
subject by default to a 1 GiB total and 10,000-file ceiling. Participant apt/system packages, raw Docker flags,
build secrets/SSH forwarding, privileged features, and runtime mounts are not supported.

Each match worker is an ephemeral non-root container with IPC disabled, a read-only root, a bounded writable `/tmp`,
dropped capabilities, no-new-privileges, default Docker seccomp, and explicit CPU/memory/PID/file-descriptor limits. It gets
no host bind mounts, Docker socket, devices, host environment, or runtime network. Runtime artifacts record the
resolved image IDs, submission content hash, Python version, and effective limits. Container isolation mitigates
ordinary untrusted application behavior but does not claim protection from Docker daemon/kernel/container escapes
or malicious package supply-chain compromise.

Participant display names and machine IDs must be unique within a match. Result artifacts record the winning side
and participant ID in addition to Showdown's display-name winner.

To run a complete configured event, copy `tournament/tournament.example.json`, point each participant entry at its submission directory, then use the `preflight` and `tournament` commands documented in `tournament/SPECTATOR.md`. Paths in the event config are resolved relative to that config file.
