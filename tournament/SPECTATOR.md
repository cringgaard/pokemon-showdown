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

Manual pacing is the default. The operator can advance through the title, intro, detailed team sheets, and locked-selection interstitial; temporarily show either team sheet, Team Preview, or standings; and return to the primary event screen. Presentation overrides do not change the active match or its playback-completion acknowledgement. For automated tests or an unattended demo, add `--auto-advance`.

The Playback controls pause/resume only the official renderer and select one of its native supported speeds: Hyperfast, Fast, Normal, Slow, or Really Slow. Playback settings are server-owned, generation-scoped, idempotent, and restored after a spectator refresh. The simulator, bots, decision deadlines, RNG, artifacts, persisted state, and standings continue independently while visual playback is paused.

During an active pairing, read-only public Open Team Sheets remain available at `/current/p1/team` and `/current/p2/team`, with stable registered-participant pages at `/teams/<participant-id>`. These pages expose only species/form, item, ability, and moves. Tera Type is intentionally omitted because the target `[Gen 9 Champions] VGC 2026 Reg M-B` format does not permit Terastallization. The sheets can be opened or refreshed independently and never control tournament state or playback completion.

After advancing a matchup intro, the simulator may finish much faster than the official renderer. The authoritative completed game and normal match artifacts are saved immediately, but the presentation remains `live` until the official renderer reports that the current protocol generation has visually ended. Only then is the result screen published. The browser acknowledgement is generation-scoped and idempotent; it cannot affect a battle, result, seed, artifact, standing, or participant state.

If the display is absent or broken, the presentation wait releases after 300 seconds. Set a different positive bound with `--playback-timeout-ms MS`. The operator page also provides `Skip pending playback` as an explicit fallback. These fallbacks skip only presentation playback; they do not cancel, rerun, or alter the completed game. `--auto-advance` bypasses the playback wait as part of its test/demo behavior.

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

The event log retains presentation transitions and current-game protocol in order. Every matchup intro starts a new, durable `protocol_generation`; the live state for that game retains it. A browser reloads the official renderer whenever this generation changes, including after a refresh on a result or standings screen, so one renderer instance can never receive two games' protocol.

A refreshed or late-joining browser receives a current HTML snapshot containing only the current generation's complete battle protocol, then continues from the next SSE sequence without duplication. If simulation already completed while the presentation is still pending, the refreshed browser reconstructs that generation, retains the current Team Preview/locked/live presentation, applies the configured pause and speed, animates the complete battle when resumed, and acknowledges it once; stale controls and duplicate acknowledgements are harmless. A disconnect shows a subtle reconnecting status and cannot backpressure or deadlock tournament execution because the timeout/operator fallbacks remain available. The event log is output-only: an invalid or partial tail is truncated to its valid prefix, and a write failure disables further event-log persistence for that process while in-memory presentation continues. Such degradation is reported in spectator delivery errors and never invalidates authoritative `state.json` or ordinary match artifacts.

## Official renderer dependency decision

Both completed replays and live/event battles use Pokémon Showdown's official hosted `replay-embed.js`. The embed declares MIT licensing and a supported third-party protocol boundary, and supplies the official `Battle`, `BattleScene`, sprites, moves, HP/status, switches, weather/terrain, Tera, fainting, and replay behavior.

The larger client repository is AGPLv3 and omits important sprite/audio assets from source control. This MIT server repository therefore does not vendor an ambiguously licensed/incomplete client build. Internet access to `play.pokemonshowdown.com` is an explicit event dependency, enforced by preflight.

For a venue display, use a 1920x1080 browser viewport in fullscreen or kiosk mode. The shell uniformly scales the official renderer's native 640x360 battle viewport into the available 16:9 battle frame; it does not replace or redraw Showdown battle content. Before doors open, walk the operator flow through title, intro, live battle, result, standings, final, and champion, and refresh once during a live game and once on a between-game screen.

The 2026-08-20 real-Chrome regression dry run used a 1920x1080 viewport and a four-participant host-runtime acceptance tournament. After Advance from the first intro, the server had already persisted the completed simulation but remained in `live`. Chrome visibly showed Team Preview, opening switches, and turns; a refresh during pending playback reconstructed Team Preview and continued through Turn 12. The official renderer visibly displayed `Beta Builders won the battle!` before the result screen appeared. A second refresh on standings reconstructed four rows and the next matchup. The event then reached the champion screen after eight completed ordinary matches; later games used the operator playback fallback to keep the acceptance run bounded.

## Single-match replay compatibility

Existing match commands remain available:

```bash
node dist/tournament/cli.js match submissions/alice submissions/bob \
  --seed 1234 --output results/alice-vs-bob --spectator-port 8000

node dist/tournament/cli.js spectate results/alice-vs-bob --port 8000
```

Live and saved single matches use the same official renderer adapter and read-only spectator boundary as the final-event shell.
