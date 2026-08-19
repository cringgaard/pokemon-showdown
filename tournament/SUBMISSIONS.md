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

The tournament generates all build definitions. Participant Dockerfiles and symlinks are rejected. Optional
`requirements.txt` entries are installed with non-root `pip` into the prepared image; arbitrary regular model,
configuration, and asset files are copied into `/submission`. Participant apt/system packages, raw Docker flags,
build secrets/SSH forwarding, privileged features, and runtime mounts are not supported. Dependency retrieval may
use network access while building; match containers have no network.

Each match worker is an ephemeral non-root container with a read-only root, a bounded writable `/tmp`, dropped
capabilities, no-new-privileges, default Docker seccomp, and explicit CPU/memory/PID/file-descriptor limits. It gets
no host bind mounts, Docker socket, devices, host environment, or runtime network. Runtime artifacts record the
resolved image IDs, submission content hash, Python version, and effective limits. Container isolation mitigates
ordinary untrusted application behavior but does not claim protection from Docker daemon/kernel/container escapes
or malicious package supply-chain compromise.

Participant display names and machine IDs must be unique within a match. Result artifacts record the winning side
and participant ID in addition to Showdown's display-name winner.
