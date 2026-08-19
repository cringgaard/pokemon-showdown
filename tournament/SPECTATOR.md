# Tournament spectator viewer

Milestone 2B provides a local read-only browser viewer for completed and live tournament matches. Both modes feed the same canonical omniscient Showdown protocol into Pokémon Showdown's official replay renderer.

## Completed match replay

Build the repository, then serve a self-contained Milestone 2A match directory:

```bash
node build
node dist/tournament/cli.js spectate results/alice-vs-bob --port 8000
```

Open `http://127.0.0.1:8000/`. The official replay controls provide play/pause, reset, turn seeking, viewpoint switching, and playback speed choices.

## Live read-only viewing

Add `--spectator-port` to the normal match command:

```bash
node dist/tournament/cli.js match submissions/alice submissions/bob \
  --seed 1234 \
  --output results/alice-vs-bob \
  --spectator-port 8000
```

The CLI prints the local viewer URL before starting the battle. A new or refreshed browser receives all protocol history accumulated so far and then continues live. The live server closes shortly after the match finishes; the completed output directory can then be served with `spectate`.

The browser is never part of battle execution. The match runner publishes ordered chunks synchronously to failure-isolated sinks, does not wait for browser acknowledgements, and disconnects a slow SSE response rather than backpressuring the simulator.

## Renderer integration and network requirement

The viewer loads Pokémon Showdown's official `replay-embed.js` third-party entrypoint from `play.pokemonshowdown.com`. That entrypoint supplies the official `Battle`, `BattleScene`, protocol interpretation, animations, sprites, field presentation, and replay controls. Tournament code supplies only protocol and the surrounding participant/format/result shell.

The official battle replay/animation engine is MIT-licensed; the larger Pokémon Showdown client is AGPLv3. Loading the hosted official entrypoint avoids copying the larger client into this server repository. Internet access to `play.pokemonshowdown.com` is therefore required when opening the viewer in this proof of concept.
