# Codex Handoff — Milestone 2C: Isolated Participant Execution

This file is the implementation handoff for Milestone 2C. `tournament/DESIGN.md` remains authoritative for battle mechanics, bot-visible information, decision semantics, artifacts, and spectator isolation. Milestones 1, 2A, and 2B are merged. Update the roadmap/status text in `DESIGN.md` as part of this PR so 2B is complete and 2C is current.

## Repository / branch

- Repository: `cringgaard/pokemon-showdown`
- Working branch: `tournament-sandbox-v1`
- Base: merged Milestone 2B on `master` (`67bb537df72a92a65a553e0e28cc9f34aadd6f1b`)
- Milestone 1 PR: #1, merged
- Milestone 2A PR: #2, merged
- Milestone 2B PR: #3, merged

Do not restart from any earlier tournament feature branch.

## Goal

Implement **Milestone 2C only**: participant Python code and its dependencies must execute behind a practical isolation boundary suitable for accepting ordinary untrusted coworker submissions, without changing the established bot API or battle behavior.

The end-state should be:

> A normal participant directory can be validated, prepared into an isolated runtime image, and used in a complete tournament match. Each worker runs in an ephemeral resource-limited Linux container with no runtime network, no host filesystem mounts, no inherited host secrets/environment, and reliable process-tree termination. Existing timeout/retry/fallback semantics, bot information boundaries, artifacts, and live/replay spectators continue to work unchanged.

This milestone is about **safe participant execution**, not tournament scheduling or visual polish.

## Threat model

Treat participant Python and Python dependencies as untrusted application code.

Milestone 2C should protect the tournament host and other participants against ordinary accidental or malicious behavior such as:

- reading arbitrary host files;
- reading host environment variables/secrets;
- contacting the internet/LAN during a match;
- binding/listening on useful network interfaces;
- writing outside controlled temporary storage;
- consuming unbounded memory, CPU, processes, file descriptors, or host-side log memory;
- leaving subprocesses/containers running after timeout or match completion;
- using participant-controlled Dockerfiles or container options to weaken isolation.

Do **not** claim Docker is a perfect hostile-kernel security boundary. This is an internal programming competition running on a controlled Docker host. Container/daemon/kernel escape vulnerabilities are outside the project threat model. Document this limitation clearly.

## First actions — inspect before refactoring

Before changing code:

1. Read `tournament/DESIGN.md`, `tournament/SUBMISSIONS.md`, and `tournament/SPECTATOR.md` completely.
2. Inspect `tournament/bots/python-worker.ts`, `runtime.ts`, `worker.py`, `match-runner.ts`, submission loading, CLI code, and all tournament tests.
3. Preserve the existing JSONL worker protocol and `BotController` decision semantics unless a concrete sandbox requirement forces a narrow change.
4. Inspect the Docker CLI available in the implementation environment. Target standard Linux containers through Docker Engine / Docker Desktop; do not design around Kubernetes or a cloud service.
5. Prefer invoking the normal `docker` CLI through Node child processes over adding a heavy Docker SDK dependency unless the CLI proves inadequate.
6. Verify Docker security/runtime flags against current official Docker documentation before finalizing command construction.

## Core architectural requirement

Sandboxing must sit **behind** the existing runtime/controller boundary.

Conceptually:

```text
MatchRunner
    |
    v
BotController
    |
    v
BotWorker interface / factory
      |                 |
      v                 v
HostPythonWorker   DockerPythonWorker
(trusted/dev)      (participant default)
                        |
                        v
                 ephemeral container
                        |
                 tournament worker.py
                        |
                 participant main.py
```

Do not make `MatchRunner` understand Docker commands, container IDs, pip, or filesystem isolation.

A narrow worker/factory abstraction is expected. Exact names are not prescribed.

The existing host worker may remain for trusted development/tests, but after 2C the **participant-facing CLI must be safe by default**. If host execution remains available, require an explicit option such as `--runtime host` and describe it as trusted/unsafe execution. Do not silently fall back from Docker to host execution when Docker is unavailable.

## Phase 1 — controlled runtime image

### Base runtime

Create a tournament-controlled Linux Python base runtime containing the harness `worker.py` and a fixed explicit Python version.

Requirements:

- participant does not supply the base image;
- participant does not supply a Dockerfile;
- use an explicit Python version, not floating `latest`;
- run the participant worker as a non-root user;
- set `PYTHONDONTWRITEBYTECODE=1` / unbuffered behavior as appropriate for the JSONL protocol;
- the tournament worker script is supplied by the harness, not copied from participant input;
- no Docker socket, SSH agent, credentials, or host secrets are included in the image.

Pin the base image by digest if practical in the current Docker workflow. At minimum pin the Python major/minor image and record the resolved runtime image/image ID so the execution environment is auditable.

### Participant image preparation

Build a participant image from the submission directory using a **tournament-generated Dockerfile/build definition**.

The participant build should:

1. start FROM the tournament-controlled base runtime;
2. install `requirements.txt` if present;
3. copy the complete participant submission, including arbitrary models/config/assets, into a fixed path such as `/submission`;
4. retain the non-root runtime user;
5. set a stable working directory;
6. not execute participant `main.py` during image build.

Dependency installation is now in scope for Milestone 2C.

A practical initial policy is Python packages only through `pip` from `requirements.txt`. Do not support participant `apt`, Dockerfiles, privileged build entitlements, host networking, BuildKit secret/SSH mounts, or arbitrary host mounts in this milestone. If some dependency cannot be installed without system packages, fail preparation with an actionable error rather than weakening the sandbox.

Build-time networking may be enabled only as needed for dependency retrieval. **Runtime networking must remain disabled.** Document clearly that dependency resolution/build is a separate trust/supply-chain surface from the runtime network policy.

### Preparation UX and caching

Provide a reusable preparation abstraction and a user-facing command or equivalent workflow, for example:

```bash
node dist/tournament/cli.js prepare submissions/alice
```

A Docker match should also prepare both participants automatically if needed and fail **before battle start** if either image cannot be built.

Avoid rebuilding an identical submission for every match. Use a deterministic content/runtime hash or another robust cache key based on participant contents + sandbox/runtime version. Return/record the resulting immutable Docker image ID, not just a mutable tag.

Do not make image caching affect battle determinism.

## Phase 2 — locked-down container worker

Each participant worker lifetime should run in its own ephemeral container.

The container must be started with a tournament-controlled policy equivalent to at least:

- `--network none`;
- `--read-only` root filesystem;
- one bounded writable tmpfs such as `/tmp`;
- `--cap-drop ALL`;
- `--security-opt no-new-privileges`;
- Docker's normal/default seccomp/confinement retained;
- explicit non-root user;
- explicit memory limit;
- swap policy bounded consistently with the memory limit where supported;
- explicit CPU limit;
- explicit PIDs/process limit;
- sensible file-descriptor ulimit;
- `--init` or equivalent child reaping if useful;
- `--rm` / explicit cleanup;
- **no host bind mounts** for the participant submission;
- **no Docker socket**;
- **no privileged mode**;
- **no added devices or capabilities**;
- **no host PID/network/IPC namespace modes**.

Use configurable limits with conservative tournament defaults. Choose defaults that are practical for ordinary Python/ML inference on a developer workstation and document them. Do not implement GPU access in this PR.

The participant image already contains the submission, so normal runtime should not need to mount the participant host directory at all.

### Environment isolation

Do not pass `{...process.env}` into an untrusted worker/container.

Use an allowlist containing only values actually required by the worker, for example the deterministic bot seed and safe Python runtime variables. A participant must not be able to read unrelated environment variables from the Node host.

Do not put tournament secrets into container labels, command-line arguments, environment variables, image history, or build args.

## Phase 3 — preserve the persistent worker protocol

Inside the container, continue using the established protocol:

```text
Node BotController
      |
      | JSON Lines stdin/stdout
      v
worker.py
      |
      v
participant choose_action(state)
```

Preserve these existing semantics:

- one persistent Python process per worker lifetime;
- module-level participant initialization happens once per worker lifetime;
- state/action JSON contract unchanged;
- participant stdout cannot corrupt the JSONL protocol;
- participant stderr remains diagnostic only;
- decision timeout does not reset due to sandbox operations;
- timeout => terminate entire worker environment/process tree, deterministic fallback, fresh worker next decision;
- invalid/exception/unavailable-choice semantics remain unchanged;
- no omniscient spectator data reaches participant code.

Container creation/preparation time must not be charged against a participant's already-started Showdown decision. Prepare images before battle and, where practical, start workers before or immediately at the first request without silently shrinking the configured decision budget.

## Phase 4 — reliable termination and cleanup

Killing only the local `docker run` CLI process is insufficient.

The runtime must track a unique container ID/name for each worker lifetime and explicitly stop/kill the **container** on:

- decision timeout;
- worker protocol fatal error where restart is required;
- `BotController.stop()`;
- normal match completion;
- match-level timeout/error cleanup.

A participant may create subprocesses. All of them must disappear when the worker is terminated.

Use unique names/labels so concurrent future matches cannot collide. Normal completion and timeout tests must verify there are no managed participant containers left running.

If cleanup itself fails, do not deadlock the battle. Report/log the failure and use best-effort forced cleanup.

## Phase 5 — host-side I/O quotas

Container memory limits do **not** protect the Node process from unbounded participant output.

Harden the worker transport for untrusted output:

- bound captured participant/container stderr by bytes and/or lines; after the limit, truncate/discard while retaining an explicit truncation marker;
- bound the maximum JSONL protocol line size / receive buffer;
- reject/terminate a worker that exceeds the protocol output limit;
- do not allow a participant to make Node retain an unbounded amount of stdout/stderr in memory;
- keep useful diagnostics in runtime artifacts within those bounds.

Preserve normal participant debugging output within reasonable limits.

This requirement applies to both Docker and host worker implementations if they share the same protocol code.

## CLI / configuration

The exact syntax can follow repository conventions. A reasonable shape is:

```bash
# Validate static submission/team contract only
node dist/tournament/cli.js validate submissions/alice

# Build/cache an isolated runtime image
node dist/tournament/cli.js prepare submissions/alice

# Safe participant execution (default)
node dist/tournament/cli.js match submissions/alice submissions/bob \
  --seed 1234 \
  --output results/alice-vs-bob

# Explicit trusted-development escape hatch only
node dist/tournament/cli.js match ... --runtime host
```

Potential sandbox settings include:

```text
--runtime docker|host
--container-memory-mb N
--container-cpus N
--container-pids N
--build-timeout-ms N
```

Do not expose arbitrary raw Docker flags from participant-controlled input.

If Docker is unavailable and Docker runtime was requested/defaulted, fail before the match with an actionable message explaining how to install/start Docker or explicitly opt into trusted host mode. Never silently downgrade isolation.

## Metadata / audit

Extend match metadata in a backward-compatible/schema-versioned way to record enough runtime information to audit a tournament match, for example:

- runtime kind (`docker` / explicit trusted host);
- participant image IDs/content hashes;
- Python/runtime version;
- memory/CPU/PID limits;
- network policy (`none`);
- sandbox policy/version.

Do not put host secrets, full host environment, or unnecessary filesystem paths into artifacts.

The battle seed and all established result/artifact semantics remain unchanged.

## Tests

Docker-dependent tests should be clearly separated and may skip with an explicit reason when Docker is genuinely unavailable in a generic development/CI environment. They must run when Docker is available. Core non-Docker tournament tests must remain runnable without Docker by explicitly selecting/injecting trusted host runtime where appropriate.

Add focused coverage for at least the following.

### Runtime abstraction

- existing host worker behavior remains compatible;
- Docker worker speaks the same JSONL request/response protocol;
- BotController does not need Docker-specific battle logic;
- timeout/restart/fallback behavior is unchanged.

### Container policy

Verify the actual created container configuration, not only string construction, where practical:

- network mode is `none`;
- root filesystem is read-only;
- expected tmpfs is writable and bounded;
- non-root user;
- memory limit configured;
- CPU limit configured;
- PIDs limit configured;
- capabilities dropped;
- no-new-privileges enabled;
- no host bind mounts / Docker socket;
- participant gets only allowlisted environment variables.

### Isolation fixtures

Use controlled malicious/edge-case test bots that attempt behaviors and then still return legal actions when the sandbox blocks them. Cover at least:

- write inside submission/root filesystem is rejected;
- write to allowed `/tmp` succeeds;
- outbound network connection fails;
- an environment variable deliberately present in the host test process is absent inside the container;
- arbitrary bundled participant asset/model file is readable inside `/submission`;
- optional `requirements.txt` is installed during image preparation (use a deterministic/practical fixture or document why a network-backed test is manual-only).

### Cleanup / timeout

- a bot that hangs triggers existing deterministic fallback;
- its entire container/process tree is killed;
- next decision can start a fresh container;
- match completes;
- no managed participant container remains after timeout + match cleanup;
- normal match completion also leaves no managed containers.

### Resource and output abuse

- oversized/malformed JSONL output does not grow host memory without bound and causes controlled worker failure;
- excessive stderr is truncated/bounded;
- resource-limit configuration is inspectable and correct;
- OOM/process-limit worker termination is handled as participant runtime failure rather than crashing the tournament where a stable test is practical.

### End-to-end

Run two ordinary submission directories through the Docker runtime and verify:

- complete match;
- normal result/runtime/state artifacts;
- `battle.protocol.log` still valid;
- live/replay spectator path still works independently;
- bot information-boundary tests remain green.

## Manual acceptance

Before declaring 2C complete, perform and document a real local Docker acceptance workflow:

1. build/prepare RandomBot and GreedyDamageBot as participant images;
2. run a complete Docker-vs-Docker match;
3. watch or replay it through the merged 2B spectator path;
4. run a controlled network/filesystem/environment-isolation fixture and confirm the expected blocks;
5. run a hanging worker and verify fallback + container cleanup;
6. run a participant with a small `requirements.txt` dependency and confirm preparation + execution;
7. confirm `docker ps -a` / labels show no leaked managed containers after normal completion and timeout scenarios.

Record exact commands and observed results in the PR description.

## Milestone 2C acceptance criteria

Milestone 2C is complete only when all are true:

1. Participant-facing match execution uses Docker isolation by default or an equivalently safe explicit default path.
2. Host execution, if retained, is explicitly selected and clearly marked trusted/unsafe.
3. Each worker lifetime runs in its own ephemeral isolated container.
4. Runtime network is disabled.
5. Participant submission is not host bind-mounted into the runtime container.
6. Container root filesystem is read-only except bounded approved temporary storage.
7. Worker runs non-root with capabilities dropped and no-new-privileges.
8. CPU, memory, process, and file-descriptor limits are applied.
9. Host environment/secrets are not inherited.
10. `requirements.txt` can be installed during controlled preparation without participant Dockerfiles or privileged build features.
11. Arbitrary participant model/config assets are available in the container.
12. Timeout kills the whole container/process tree and preserves deterministic fallback/restart semantics.
13. Normal completion and failures do not leak managed containers.
14. Host-side protocol/stderr buffers are bounded against output abuse.
15. Existing BotState/action/hidden-information contracts are unchanged.
16. Existing artifacts and spectator live/replay behavior remain compatible.
17. Docker-unavailable/build failures fail before battle with actionable errors and never silently fall back to host execution.
18. Automated Docker policy/isolation/cleanup tests pass when Docker is available.
19. Existing tournament and full repository validation remain green.
20. `tournament/DESIGN.md` marks 2B complete and 2C current and documents the chosen isolation/runtime architecture.

## Explicitly out of scope

Do **not** implement in this PR:

- round-robin/bracket scheduling;
- standings/ranking/series orchestration;
- polished cafeteria spectator shell;
- automatic match/intermission transitions;
- remote/public deployment;
- authentication/authorization system;
- Kubernetes or cloud orchestration;
- GPU access/passthrough;
- arbitrary participant Dockerfiles;
- participant-controlled apt/system-package installation;
- privileged containers;
- host networking;
- Docker socket access;
- VM/microVM isolation;
- advanced signed-package/SBOM/supply-chain infrastructure;
- broad unrelated refactors.

Milestone 3/final event work starts only after isolated one-match execution is robust.

## Validation before completion

Run:

1. narrow runtime/sandbox tests while iterating;
2. existing tournament test suite;
3. TypeScript/build checks;
4. applicable lint checks;
5. Docker-enabled integration tests on a machine with Docker;
6. repository full verification.

Update the PR body with **actual** commands and results. Do not copy old test counts forward.

## Delivery

Implement on `tournament-sandbox-v1` and keep/open a focused PR against `master` titled approximately:

> Implement tournament participant sandbox milestone 2C

The PR description must summarize:

- runtime abstraction chosen;
- Docker image/preparation strategy;
- exact runtime security policy/limits;
- dependency policy;
- host-output quota design;
- timeout/container cleanup behavior;
- CLI workflow;
- Docker availability requirements;
- threat-model limitations;
- automated/manual validation;
- explicitly deferred Milestone 3 visual/orchestration work.

Do not merge automatically. Stop ready for review.