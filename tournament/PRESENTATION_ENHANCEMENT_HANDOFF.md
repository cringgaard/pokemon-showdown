# Pokémon Showdown Bot Tournament — VGC Presentation Enhancement Handoff

Status: implementation handoff following the Milestone 3 dry run.

This document defines a focused post-Milestone-3 enhancement to the tournament spectator and operator experience. It is intentionally presentation-centric. The existing battle engine, participant API, hidden-information boundary, MatchRunner behavior, sandbox, deterministic tournament model, artifact model, and resume semantics remain authoritative and should not be redesigned as part of this work.

The dry run established that the current event can now show a complete animated battle after simulator completion was decoupled from presentation completion. Preserve that architecture.

## 1. Goal

Make the event presentation feel closer to an actual Pokémon VGC broadcast by adding:

1. operator playback controls for the official Showdown renderer;
2. public Open Team Sheet presentation;
3. a proper Team Preview presentation before every game;
4. stable read-only team-sheet URLs during the match;
5. clearer participant documentation for the existing Bring-6 / Pick-4 decision.

The implementation should remain suitable for a 1920×1080 cafeteria/projector display and for manual operator pacing.

## 2. VGC model to preserve

The tournament format is VGC-style Doubles with forced Open Team Sheets.

For each game:

```text
registered team of 6
        ↓
open team information is available
        ↓
Team Preview
        ↓
choose 4 of the 6
        ↓
first 2 selected become the leads
remaining 2 become reserves
        ↓
battle
```

In a multi-game series, the same registered team remains fixed, but the four selected Pokémon and the two leads may change independently for every game.

The distinction between **Open Team Sheet** and **Team Preview** must remain explicit:

- the Open Team Sheet describes the public strategic information about all six registered Pokémon;
- Team Preview is the per-game selection phase in which each bot chooses four and orders its leads.

## 3. Preserve the existing participant contract

The current participant API already implements the desired Bring-6 / Pick-4 model and must remain compatible.

The existing response contract is:

```ts
interface TeamPreviewResponse {
    team: [
        OwnPokemonID,
        OwnPokemonID,
        OwnPokemonID,
        OwnPokemonID
    ];
}
```

Ordering is meaningful:

```text
team[0] = lead 1
team[1] = lead 2
team[2] = reserve
team[3] = reserve
```

Do not replace or broaden this contract.

Bots must continue to receive only their existing player-visible state. The participant information boundary remains unchanged.

Pokémon Showdown remains authoritative for:

- battle mechanics;
- Team Preview legality;
- battle RNG;
- Showdown choice validation.

Do not introduce tournament presentation metadata, playback state, standings, operator state, or spectator-only data into `BotState`.

## 4. Target event flow

### 4.1 New pairing / new series

Change the beginning of a new pairing from roughly:

```text
MATCHUP INTRO
→ LIVE BATTLE
```

into:

```text
MATCHUP INTRO
      ↓
P1 OPEN TEAM SHEET
      ↓
P2 OPEN TEAM SHEET
      ↓
TEAM PREVIEW
six Pokémon vs six Pokémon
bots selecting...
      ↓
SELECTION LOCKED
      ↓
LIVE BATTLE
```

The detailed team-sheet presentation is a broadcast introduction to the registered teams.

### 4.2 Multi-game final / series

Detailed team sheets should appear once at the beginning of the pairing/series, not before every game.

For example:

```text
FINAL INTRO
→ P1 detailed team sheet
→ P2 detailed team sheet
→ Game 1 Team Preview
→ Game 1
→ result / series state
→ Game 2 Team Preview
→ Game 2
→ ...
```

Team Preview itself must occur before **every game**, because the bots may choose a different four and different leads each time.

### 4.3 Selected-four reveal

For this first implementation, do **not** reveal which four Pokémon or which leads each bot selected before the battle begins.

A simple visible state such as:

```text
Selection locked
```

is sufficient.

Let the leads reveal naturally when the official Showdown battle renderer starts the game.

## 5. Public Open Team Sheet projection

Create an explicit spectator/public team-sheet model derived from the already validated submitted `team.txt`.

For this Regulation I tournament, expose only the intended public Open Team Sheet fields:

- Pokémon species/form;
- held item;
- ability;
- Tera Type;
- four moves.

Do **not** expose spectator team-sheet fields that are outside this public projection, including:

- EVs;
- IVs;
- Nature;
- exact calculated stats;
- private simulator values;
- any other hidden or organizer-only information.

Prefer deriving the public representation through existing Pokémon Showdown team parsing and Dex utilities rather than independently reparsing the human-readable export format.

The public team-sheet model is spectator/event data. It must not broaden the participant API or hidden-information contract.

## 6. Broadcast-style team-sheet UI

Add a full-screen team presentation suitable for a 1920×1080 venue display.

Each team should display six visually distinct Pokémon cards. Each card should contain approximately:

```text
Pokémon name/species
[sprite / official Showdown visual asset where supported]

Ability
Item
Tera Type

Move 1
Move 2
Move 3
Move 4
```

Design priorities:

- readable from several metres away;
- visually closer to a tournament broadcast graphic than a raw PokéPaste/team export;
- six Pokémon visible without document scrolling at 1920×1080;
- clear participant/team identity;
- graceful handling of long participant names;
- graceful handling of long Pokémon, move, item, and ability names;
- no horizontal or vertical page overflow at the target resolution.

Reuse the same team-sheet visual component/style for standalone team-sheet pages where practical.

## 7. Stable team-sheet URLs

Team sheets must remain independently viewable while a battle is running.

Add stable read-only routes for registered tournament participants, conceptually:

```text
/teams/<participant-id>
```

Also add convenience routes for the currently active pairing, conceptually:

```text
/current/p1/team
/current/p2/team
```

Exact route naming may differ if a cleaner routing structure exists.

Requirements:

- pages are read-only spectator resources;
- refreshing them works independently of the main spectator display;
- they do not control tournament state;
- they do not influence playback completion;
- they do not expose private/non-OTS team information;
- they remain useful during an active battle.

## 8. Team Preview presentation

Add a distinct Team Preview presentation before every game.

The visual should clearly show both complete six-Pokémon rosters, for example:

```text
Participant A                         Participant B

[ six Pokémon icons / sprites ]       [ six Pokémon icons / sprites ]

                   Selecting teams...
```

Use Pokémon visuals prominently enough that spectators can understand the matchup quickly.

When both Team Preview decisions have been submitted, transition to a visible locked state:

```text
Selection locked
```

Then proceed to the live battle according to the event's existing pacing model.

Do not expose the selected four or selected leads before battle in this implementation.

The Team Preview UI may use the same public team information model as the detailed Open Team Sheet presentation, but it should be substantially more compact.

## 9. Operator playback controls

Extend `/operator` with presentation-only controls for the official Showdown renderer.

At minimum support:

```text
PLAYBACK
[ Pause / Resume ]

Speed:
[ native supported speed options ]

Status:
Playing · Normal · Turn 6
```

Before implementing the speed control, inspect the official hosted replay renderer API (`replay-embed.js` / existing `Replays.changeSetting(...)`) and use values genuinely supported by the renderer.

Do not build a second custom battle animation/timing engine unless absolutely necessary.

### 9.1 Strict presentation-only boundary

Pause and speed controls must affect only visual playback.

They must never pause, slow, or modify:

- `MatchRunner`;
- `BattleStream`;
- either participant process;
- participant decision deadlines;
- battle RNG;
- result persistence;
- tournament state persistence;
- standings;
- artifact generation.

The simulator may already be complete while the display is paused. The existing presentation-completion gate should simply remain pending until the official renderer resumes and reaches `ended`.

The existing operator escape hatch for skipping/releasing pending playback must continue to work.

### 9.2 Playback state and reconnect

Define refresh/reconnect behavior clearly.

Prefer server/operator-owned playback state if it produces clean semantics. A refreshed spectator may return to the current configured operator playback state rather than trying to preserve arbitrary browser-local transient state.

Stale or duplicate playback-control messages must be harmless.

Playback controls should remain generation-aware so controls for an old battle cannot accidentally manipulate the current generation.

## 10. Operator presentation controls

Add convenient controls or links to `/operator` for presentation inspection, conceptually:

```text
PRESENTATION
[ Show P1 Team Sheet ]
[ Show P2 Team Sheet ]
[ Show Team Preview ]
[ Show Standings ]
[ Return to Primary ]
```

Distinguish between:

1. changing the **main event presentation** temporarily; and
2. opening/copying the independent team-sheet URL.

Showing a team sheet or Team Preview overlay/state must not interfere with the active match or corrupt the presentation-completion acknowledgement for the live battle.

## 11. Participant documentation

Update `tournament/SUBMISSIONS.md` and maintained starter/reference examples so Bring-6 / Pick-4 behavior is unambiguous.

Include a clear example such as:

```python
if state["battle"]["phase"] == "team_preview":
    # state["self"]["team"] contains your six Pokémon.
    # state["opponent"]["team"] contains the opponent's public OTS information.

    return {
        "team": [
            "team_4",  # lead 1
            "team_1",  # lead 2
            "team_0",  # reserve
            "team_5",  # reserve
        ]
    }
```

Explicitly document:

- exactly four Pokémon are selected;
- ordering matters;
- the first two are leads;
- the other two are reserves;
- Team Preview occurs again for every game;
- the opponent's public Open Team Sheet information may be used in the decision;
- participant code does not need to generate Showdown protocol syntax;
- `request.legal_actions` remains the public source of truth for legal complete responses.

Do not change the public schema solely to make this documentation easier.

## 12. Team Preview timeout investigation

Do not silently change existing timeout behavior.

Investigate whether `team_preview` currently uses the same general `decision_timeout_ms` as ordinary turn decisions.

Report whether a separate setting such as:

```json
"team_preview_timeout_ms": 10000
```

would be useful and how invasive the change would be.

A small, clean, backward-compatible configuration extension is acceptable if justified, but:

- retain a sensible default;
- document it explicitly;
- do not copy the official human 90-second Team Preview timer merely for authenticity;
- do not weaken existing timeout/fallback guarantees.

## 13. Frozen architectural boundaries

The following relationships remain forbidden:

```text
spectator/operator presentation state
               X
               |
               v
        participant BotState
```

and:

```text
playback pause / playback speed
               X
               |
               v
       simulator execution timing
```

Specifically, team sheets, selected presentation screens, playback speed, pause state, standings, tournament stage labels, and operator controls must never enter participant input.

Preserve:

- hidden-information rules;
- ordinary MatchRunner semantics;
- deterministic battle seeds and side assignment;
- tournament resume behavior;
- generation-scoped spectator reconstruction;
- simulator-completion vs presentation-completion separation;
- output-only spectator failure isolation;
- Docker-default participant execution;
- ordinary match artifact semantics.

Do not modify `sim/` unless a concrete upstream integration defect genuinely requires it. If such a change appears necessary, document the reason rather than using simulator modifications as a shortcut for presentation behavior.

## 14. Tests

Add focused automated coverage for at least the following.

### Open Team Sheets

- public OTS projection contains the intended allowed fields;
- EVs do not leak;
- IVs do not leak;
- Nature does not leak;
- exact calculated stats do not leak;
- participant and current-pairing team-sheet routes return the correct public team;
- independent team-sheet pages can be refreshed.

### Team Preview

- Team Preview presentation occurs before every game;
- detailed team-sheet presentation occurs once per pairing/series rather than before every final game;
- the existing Pick-4 participant action remains unchanged;
- selected four/leads are not prematurely exposed through the spectator presentation if the design intentionally withholds them;
- no tournament/presentation metadata enters bot state.

### Playback controls

- operator pause does not affect simulator/tournament completion;
- the result remains presentation-gated while visual playback is paused;
- resume allows the renderer to continue and eventually release the result;
- speed changes are reflected in spectator playback state;
- stale/duplicate playback-control messages are harmless;
- spectator refresh/reconnect during a paused battle has defined behavior;
- the existing skip/fallback path still releases a broken or missing display.

### Presentation

- long participant names remain renderable;
- long Pokémon/move/item/ability text degrades gracefully;
- existing standings, result, champion, renderer-generation, replay, resume, sandbox, and tournament tests remain green.

## 15. Real-browser acceptance

Perform another real Chrome acceptance with an explicit **1920×1080 viewport** and manual operator pacing.

Walk through and inspect:

```text
title
→ matchup intro
→ P1 detailed team sheet
→ P2 detailed team sheet
→ Team Preview
→ Selection locked
→ live battle
→ pause
→ resume
→ change playback speed
→ result
→ standings
→ next game's Team Preview
→ final series
→ champion
```

During a live battle:

1. open both current participant team-sheet URLs;
2. verify they contain only public OTS information;
3. refresh both team-sheet pages;
4. refresh the main spectator;
5. pause and resume playback after refresh;
6. change playback speed;
7. verify the complete official-renderer battle is still visibly shown before result;
8. verify the operator fallback still works;
9. verify no scrolling or layout overlap at 1920×1080.

Use the real dry run to judge whether `Normal` should become the default battle playback speed. Do not choose the default purely from code; document what looked appropriate in the actual browser presentation.

Update PR #5 with the exact automated and manual acceptance results.

## 16. Completion criteria

This enhancement is complete when:

- the existing participant/battle architecture remains intact;
- detailed public team sheets are polished and accessible before and during matches;
- Team Preview is visually represented before every game;
- Bring-6 / Pick-4 behavior is clearly documented for participants;
- pause/resume and supported playback-speed controls work from the operator UI without affecting simulation;
- refresh/reconnect remains safe;
- target-resolution acceptance is documented;
- existing tournament and sandbox validation remains green.

Keep PR #5 open for review when implementation is complete.

**Do not merge as part of the implementation task.**
