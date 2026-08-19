# Tournament final-event spectator and operator guide

Milestone 3 provides a local, read-only 16:9 event presentation for a complete deterministic tournament. The browser has idle/title, matchup intro, live battle, result, standings/next-match, and champion states. Canonical Showdown battle protocol and tournament metadata remain separate event kinds; neither can influence a match or enter participant `BotState`.

## Configure and preflight

Copy and edit `tournament/tournament.example.json`. Submission paths are relative to the config file, regardless of the shell's current directory.

Build and run the mandatory event preflight:

```bash
node build
node dist/tournament/cli.js preflight tournament/tournament.example.json \
  --output results/company-cup \
  --spectator-port 8000
```

Preflight validates the config and all teams/submissions, checks state/output compatibility, confirms the spectator port, requires Docker and prepares participant images when `runtime` is `docker`, and probes the official hosted renderer plus every script/style/data dependency declared by its embed.

If renderer access is intentionally unavailable during a rehearsal, `--allow-renderer-unreachable` converts that one failure into a prominent warning. This is an explicit degraded-presentation override; normal event startup fails closed so tournament play cannot begin accidentally without a working renderer.

## Run or resume the event

```bash
node dist/tournament/cli.js tournament tournament/tournament.example.json \
  --output results/company-cup \
  --spectator-port 8000
```

Open:

- presentation: `http://127.0.0.1:8000/`
- operator controls: `http://127.0.0.1:8000/operator`

The command resumes the selected output directory by default. It validates completed artifacts, adopts an in-progress attempt if its ordinary match artifacts finished before the previous process stopped, and never reruns a completed game. A partial attempt remains for audit and the resumed game uses a new `attempt-N` directory.

Manual pacing is the default. The operator can advance from the title/intro/interstitial, show standings while waiting, and return to the current event screen. Controls affect only the interval between games and states; they never pause a battle in progress. For automated tests or an unattended demo, add `--auto-advance`.

Docker remains the safe default runtime. A config may set `"runtime": "host"` only for trusted development; the CLI emits an explicit warning.

## Deterministic tournament rules

- Participants are ordered by canonical participant ID.
- Every unordered round-robin pair meets once, with the configured games per pairing.
- Sides alternate by game index in both round robin and final.
- A round-robin win is 1 point and a tie is 0.5 points for each participant.
- Ranking order is points, tied-group head-to-head points, total wins, then lexical participant ID.
- The top two play the configured odd best-of final; the series stops at a majority.
- Final battle ties do not count as wins and cause another seeded, side-alternated game.
- After `final.max_tied_games` tied final games, the higher-ranked qualifier advances as the documented safety fallback.
- Seeds are the first four big-endian 16-bit words of SHA-256 over `pokemon-showdown-tournament-v1\0<tournament seed>\0<stage>\0<pairing ID>\0<game index>`.

## Durable artifacts and refresh/reconnect

```text
results/company-cup/
|-- tournament.json
|-- state.json
|-- event.log.jsonl
`-- matches/
    |-- round-robin/...
    `-- final/...
```

Every game directory is a normal existing `MatchRunner` artifact set with `metadata.json`, `result.json`, `battle.protocol.log`, runtime logs, and bot-state snapshots. `state.json` is written atomically and is validated against the normalized-config hash on every start.

The event log retains presentation transitions and current-game protocol in order. A refreshed or late-joining browser receives a current HTML snapshot containing the complete current battle protocol, then continues from the next SSE sequence without duplication. A disconnect shows a subtle reconnecting status and cannot backpressure or stop tournament execution.

## Official renderer dependency decision

Both completed replays and live/event battles use Pokémon Showdown's official hosted `replay-embed.js`. The embed declares MIT licensing and a supported third-party protocol boundary, and supplies the official `Battle`, `BattleScene`, sprites, moves, HP/status, switches, weather/terrain, Tera, fainting, and replay behavior.

The larger client repository is AGPLv3 and omits important sprite/audio assets from source control. This MIT server repository therefore does not vendor an ambiguously licensed/incomplete client build. Internet access to `play.pokemonshowdown.com` is an explicit event dependency, enforced by preflight.

## Single-match replay compatibility

Existing match commands remain available:

```bash
node dist/tournament/cli.js match submissions/alice submissions/bob \
  --seed 1234 --output results/alice-vs-bob --spectator-port 8000

node dist/tournament/cli.js spectate results/alice-vs-bob --port 8000
```

Live and saved single matches use the same official renderer adapter and read-only spectator boundary as the final-event shell.
