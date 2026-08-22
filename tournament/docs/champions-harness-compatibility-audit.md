# Champions tournament harness compatibility audit

Status: historical audit of the pre-fix harness at `eeee09826`, followed by the merged Workstream A implementation and its state-contract corrective follow-up. Workstream B and snow-team policy remain intentionally unimplemented.

## Implementation status

- **A1 complete:** the exact target format is the default, the runner performs a deliberate headless OTS acceptance handshake, and battle state records the resolved `champions` mod.
- **A2 complete:** request/action APIs are format-neutral; real Mega request flags produce semantic transformation variants; the adapter alone emits raw suffixes; duplicate side-wide Mega use is filtered.
- **A3 complete:** action, own-state, OTS, history, form, type, and ability metadata use the configured format Dex; Champions OTS public fields are preserved without hidden stats; public opponent Mega state is normalized both during transformation and on later switch-in; unresolved Illusion exposes appearance without claiming hidden types, ability, or appearance-derived transformation.
- **A4 acceptance complete for this compatibility milestone:** focused simulator tests cover all five required Mega forms, weather/terrain activation, post-Mega availability, OTS, format-specific data, Staraptor's Ground immunity, Stat Points, information boundaries, and full participant-API matches with both reference bots.
- **Contract follow-up complete:** `BotState.schema_version` is `2`, and the CLI/compatibility fixture is the exact deterministic-bot design team.

The implementation deliberately does not add the Workstream B deterministic policy or any snow-team heuristic.

Audited commit: `eeee09826fc5f234c9c0c88acc72d8f5d87bd05f`

Target display name: `[Gen 9 Champions] VGC 2026 Reg M-B`

## Executive conclusion

The exact format ID is `gen9championsvgc2026regmb`, and `Dex.forFormat()` resolves it to the `champions` mod. The simulator correctly implements bring-6/pick-4 doubles, Champions Stat Points, Mega Evolution, the custom Mega forms, and the mechanics sampled in this audit.

At the audited pre-fix commit, the tournament harness was **not yet compatible enough to be the tournament participant boundary**. Its critical failures were:

1. its default remains Gen 9 VGC 2025 Regulation I;
2. the exact target format offers consensual, not forced, Open Team Sheets, while the headless runner performs no OTS acceptance handshake;
3. the simulator offers Mega Evolution through `ChoiceRequest.active[*].canMegaEvo`, but the harness ignores that flag and generates no Mega legal actions;
4. the public schema and action path are specialized for an illegal mechanic, Terastallization;
5. opponent post-Mega ability and typing are not tracked correctly; and
6. the harness uses the base `Dex` for public move metadata instead of the configured format's Dex.

Consequently, at the audited commit, a reference bot could complete a Champions match only by never Mega Evolving, and `request.legal_actions` was not the complete authoritative action set promised by the public API. The implementation status above records the resolution of those findings.

## Exact format and rules

Repository and executable resolution produced:

| Property | Result |
|---|---|
| Format ID | `gen9championsvgc2026regmb` |
| Display name | `[Gen 9 Champions] VGC 2026 Reg M-B` |
| Format `mod` | `champions` |
| `Dex.forFormat(format).currentMod` | `champions` |
| Game type | `doubles` |
| Team size | exactly 6 |
| Picked team size | 4 |
| Stat Point limit | 32 per stat, 66 total |
| OTS rule | `Open Team Sheets` (consensual) |
| Tera | unavailable |

The format definition is at `config/formats.ts:311-316`. `Flat Rules` supplies Team Preview, minimum team size 6, and `Picked Team Size = Auto`; doubles resolves Auto to four (`data/mods/champions/rulesets.ts:25-30`, `sim/dex-formats.ts:337-349`).

## Compatibility findings

In sections A-J, **Current behavior** means behavior observed in the audited pre-fix harness at `eeee09826`, not the post-Workstream-A implementation, unless a paragraph explicitly says otherwise. The recommendations and proof tests are retained as the historical basis for the implemented changes.

### A. Runtime format selection is wrong by default

- **Current behavior:** `MatchRunner.DEFAULT_FORMAT` is `gen9vgc2025regi@@@!openteamsheets,forceopenteamsheets` (`tournament/match/match-runner.ts:16`). The CLI does not accept or supply a different format.
- **Actual Champions behavior:** the required base format is `gen9championsvgc2026regmb`, using the `champions` mod.
- **Why it matters:** default CLI matches validate the wrong team syntax and execute the wrong mechanics, data, transformations, and stat system.
- **Recommended change:** make an explicit tournament configuration own the target format. For unattended matches, use the target format plus a deliberate OTS policy, rather than silently inheriting the development default.
- **Proof tests:** assert resolved ID/mod/rule table at startup; validate and complete a match using the tested snow team.

### B. Exact-format Open Team Sheets do not appear in a headless match

- **Current behavior:** the runner starts the battle and players but never writes `>show-openteamsheets`. The exact target uses `Open Team Sheets`, whose preview callback only asks players to accept (`data/rulesets.ts:1979-1999`). A BattleStream probe received no `|showteam|` messages. The old default avoided this through `!openteamsheets,forceopenteamsheets`.
- **Actual Champions behavior:** after acceptance, `Battle.showOpenTeamSheets()` sends species/form, item, ability, moves, Champions nature, gender, level, and (because this is Gen 9 without `Terastal Clause`) the submitted Tera type. It explicitly removes EVs and IVs (`sim/battle.ts:3184-3222`). Tera type appearing on the sheet does **not** make Tera legal.
- **Why it matters:** with the unmodified target ID, `BotState.opponent.team` is empty at preview, invalidating OTS-based selection and threat analysis. With forced OTS, the current tracker preserves species, item, ability, moves, and Tera type but drops public nature, gender, and level.
- **Recommended change:** define unattended tournament execution as either `gen9championsvgc2026regmb@@@!openteamsheets,forceopenteamsheets` or an equally explicit runner-controlled OTS handshake. Prefer the custom-rule format because it makes the battle contract self-describing. Expand the OTS schema to preserve nature, gender, and level. Continue excluding stats, Stat Points/EVs, and IVs.
- **Proof tests:** an exact-format test must demonstrate the absence of sheets without acceptance; the configured tournament-format test must observe both six-entry sheets before the preview decision and assert the precise included/excluded fields.

### C. Bring-6/pick-4 Team Preview is correct

- **Current behavior:** the action generator uses `maxChosenTeamSize`, enumerates ordered permutations, and requires length four. A real target-format request had `maxChosenTeamSize: 4`; the harness generated all `6P4 = 360` responses and serialized the first as `team 1234`.
- **Actual Champions behavior:** the first two selected entries become the doubles leads; entries three and four are the ordered backline. The other two are not brought.
- **Why it matters:** preview is one of the few major inherited assumptions that already matches the target.
- **Recommended change:** retain the semantic ordered-four response. Replace the hard-coded error message eventually with a format-derived invariant if the harness is intended to support other formats, but no Champions fix is required.
- **Proof tests:** keep the 360-action unit test and add a real target-format BattleStream round trip that checks both leads and selected bench order.

### D. Mega Evolution is present in the real request but absent from public legal actions

- **Current behavior:** a real first-turn request for active Aggron and Raichu holding their stones set `canMegaEvo: true` on both active slots. `generateLegalActions()` only reads `canTerastallize`; both public slots reported `can_terastallize: false`, and zero generated actions requested Mega Evolution. `action-adapter.ts` only knows the `terastallize` suffix.
- **Actual Champions behavior:** the request flag is `canMegaEvo: true`. A player requests the transformation by appending `mega` to that Pokemon's move choice, for example `move 1 mega`. Champions Charizard X/Y and Raichu X/Y still use ordinary `mega`; their held stone determines the resulting form. The simulator's `megax`/`megay` request flags and suffixes are separate mechanics and are not how these Champions stones are chosen.
- **Why it matters:** participant bots cannot use the central mechanic, and `request.legal_actions` is incomplete.
- **Recommended change:** expose a semantic transformation choice derived directly from request flags. For this format, emit `kind: "mega"` and adapt it to the `mega` suffix. Do not infer X/Y choice independently and do not rename Tera fields to Mega fields.
- **Proof tests:** real requests for Aggron, both Charizard stones, and both Raichu stones; semantic action-to-`mega` round trip; no transformation action when the request omits the flag.

### E. Mega restrictions are side-wide, including both doubles slots

- **Current behavior:** the harness enforces only the analogous same-turn double-Tera restriction. It has no Mega constraint because it has no Mega actions.
- **Actual Champions behavior:** `Side.chooseMove()` rejects the second Mega selection in a joint doubles choice with `You can only mega-evolve once per battle` (`sim/side.ts:771-842`). After Mega Evolution, `runMegaEvo()` sets `canMegaEvo = false` for every ally (`sim/battle-actions.ts:1899-1912`). A probe confirmed both a same-turn double-Mega rejection and that the other active slot loses Mega availability after one ally transforms.
- **Why it matters:** independently expanding both slots without a joint filter would publish invalid actions and cause avoidable retries/fallbacks.
- **Recommended change:** generate per-slot Mega variants only when the real request says so, then reject joint responses containing more than one side-wide Mega transformation. The next request remains authoritative for future availability.
- **Proof tests:** both active slots initially Mega-capable; either single-Mega line legal; double Mega absent from `legal_actions`; second teammate cannot Mega on a later turn.

### F. Post-Mega own state is accurate, but opponent state is not

- **Current behavior:** the own `ChoiceRequest` after Mega Aggron publicly contains `details: Aggron-Mega`, recalculated stats, `baseAbility: filter`, and `ability: filter`; `state-builder.ts` therefore gets own species/stats/ability right. For the opponent, the player stream sends `|detailschange|...|Aggron-Mega` followed by `|-mega|...|Aggron|Aggronite`. `StateTracker` updates `apparentSpecies` for `detailschange` but ignores `-mega`, retains the OTS base ability (`sturdy`), and has no types field. A forced-OTS probe produced opponent species `Aggron-Mega` with the incorrect active ability `sturdy`.
- **Actual Champions behavior:** Mega Aggron becomes pure Steel with Filter. Mega Charizard X becomes Fire/Dragon with Tough Claws; Mega Charizard Y remains Fire/Flying and starts Drought. Mega Raichu X is Electric with Electric Surge; Mega Raichu Y is Electric with No Guard.
- **Why it matters:** bots see the wrong defensive profile, immunities/resistances, accuracy behavior, and entry effects after an opposing Mega.
- **Recommended change:** parse `-mega` as a public transformation event and resolve the now-public form through the format Dex. Expose current public species/form, types, and ability separately from the immutable OTS set. Never consult hidden battle objects. Preserve `team_id` when identity was already public; preserve null under unresolved Illusion.
- **Proof tests:** feed real player-stream Mega protocol into `StateTracker` for all five relevant forms and assert current form/types/ability plus unchanged OTS base set.

### G. Tera is illegal, but Tera assumptions dominate the public API

- **Current behavior:** the schema contains own `tera_type`/`terastallized`, opponent `tera_type`/`terastallized`, `MoveAction.terastallize`, and `SlotRequest.can_terastallize`; the generator expands Tera variants; the adapter writes `terastallize`; tests and GreedyDamageBot are Tera-specific.
- **Actual Champions behavior:** `data/mods/champions/scripts.ts:180-181` overrides `canTerastallize()` to return `null`. Real requests contain no `canTerastallize`. There is no Mega/Tera interaction because Tera cannot be selected. A submitted Tera type may still be visible in generic Gen 9 OTS serialization, but it is inert metadata.
- **Why it matters:** the API emphasizes an unavailable mechanic while omitting the available one. Policy code could confuse sheet metadata with transformation availability.
- **Recommended change:** replace battle/action Tera booleans with a format-neutral transformation structure. Keep OTS `tera_type` only as nullable sheet metadata if exact public-sheet fidelity is desired, clearly separate from `available_transformations`.
- **Proof tests:** target-format requests and legal actions never expose a Tera transformation; attempts to submit Tera are rejected by Showdown; a sheet Tera type does not create a legal action.

### H. Static public mechanics metadata is not format-aware

- **Current behavior:** `action-generator.ts`, `state-builder.ts`, and `state-tracker.ts` call the base `Dex.moves.get()` (`tournament/actions/action-generator.ts:81`, `tournament/state/state-builder.ts:86-87`, `tournament/state/state-tracker.ts:150,224`).
- **Actual Champions behavior:** the `champions` mod changes public move metadata. An executable comparison found, among others, `Growth` type Normal -> Grass, `Snap Trap` type Grass -> Steel, `Anchorshot` 80 -> 90 BP, `Gear Grind` 50 -> 60 BP, `Protect` 10 -> 5 base PP, and a global cap of 20 PP. The request itself usually supplies actual current/max PP, but move type and base power still come from the wrong Dex.
- **Why it matters:** legal targets still come from the request and remain correct, but public scoring metadata can be mechanically false. This directly misleads GreedyDamageBot and would mislead Workstream B.
- **Recommended change:** resolve `const dex = Dex.forFormat(format)` once per match and inject/use it in action generation, state construction, and public OTS/history normalization. Record the resolved mod in battle metadata.
- **Proof tests:** compare exported/public metadata for representative Champions overrides and custom content against `Dex.forFormat()`.

### I. Champions custom forms and team validation are simulator-correct, harness support is partial

- **Current behavior:** `TeamValidator.get(format)` is correctly called with the configured format (`tournament/match/match-runner.ts:230-234`). The base data contains the custom Champions species/items and the mod marks them legal. The tested six-Pokemon snow team validates successfully under the exact target format. However, the action/state layers' base-Dex usage and missing Mega support prevent correct runtime representation.
- **Actual Champions behavior:** format-aware data resolves at least Mega Aggron, both Mega Charizards, both Mega Raichus, Mega Meganium, and Mega Staraptor with their Champions forms, stats, types, abilities, and stones.
- **Why it matters:** validation alone can accept the team while the bot API still omits or misstates its mechanics.
- **Recommended change:** retain Showdown validation, add a startup format/mod assertion and format-aware data provider, then cover custom forms through the real transformation path.
- **Proof tests:** validate representative custom stones/forms and complete reference-bot matches containing custom Megas.

### J. Stat Points are implemented correctly

- **Current behavior:** validation is delegated to Showdown using the chosen format.
- **Actual Champions behavior:** Champions sets require all IVs to be 31, allow at most 32 Stat Points per stat, and at most 66 total (`sim/team-validator.ts:1148-1160,1306-1309,1350-1356`). `EV Limit = Auto` resolves to 66 for Champions (`sim/dex-formats.ts:343-349`). Champions stat calculation consumes the imported `evs` fields as Stat Points (`data/mods/champions/scripts.ts:10-33`).
- **Why it matters:** the manually tested spreads are represented as intended; no tournament-side validator should duplicate these rules.
- **Recommended change:** no mechanics change. Rename participant-facing documentation from EVs to Stat Points for Champions, and retain `TeamValidator` as authority.
- **Proof tests:** the complete tested team passes; 33 in one stat fails; total 66 passes; total 67 fails; any non-31 IV fails.

## Simulator mechanics evidence

The audit used the exact Champions format/mod through real `BattleStream` request/protocol probes and real `Battle` event resolution. Results:

| Mechanic | Observed target-format behavior | Recommended permanent test |
|---|---|---|
| Mega Aggron | `Aggron-Mega`, pure Steel, Filter; own next request exposes the new form/stats/ability | BattleStream semantic Mega round trip, public-state assertions, and a Filter damage comparison |
| Mega Charizard X | Fire/Dragon, Tough Claws, no weather activation | Transformation/form/type/ability test |
| Mega Charizard Y | Fire/Flying, Drought; sun active after transformation | Transformation plus weather-order test |
| Mega Raichu X | Electric, Electric Surge; Electric Terrain active | Transformation plus terrain test |
| Mega Raichu Y | Electric, No Guard; real Accuracy event returned guaranteed hit | Transformation plus accuracy/evasion bypass test |
| Snow Cloak + Bright Powder | A 100-accuracy event was modified to 72 in snow (the simulator fixed-point forms of approximately 0.8 x 0.9) | Controlled Accuracy-event boundary test and one BattleStream miss/hit fixture |
| Gravity + evasion | The same modified accuracy became 120 before the ordinary 100% cap, so a base-100 move is guaranteed; lower-base-accuracy moves are not universally guaranteed | Test both a base-100 and a lower-accuracy move; do not model Gravity as unconditional No Guard |
| Aurora Veil | Requires hail/snow at resolution | Success-in-snow and fail-outside-snow tests |
| Pelipper switch before Veil | Switch activated Drizzle before Ninetales acted; weather was rain and Veil was absent | BattleStream ordering regression |
| Fake Out vs Follow Me | Fake Out acted first, flinched Maushold, Follow Me never activated, and the partner-targeted attack stayed on the partner | Priority/redirection Battle test |
| Wide Guard | Blocked Surf against both allies; did not block single-target Weather Ball, which damaged its selected target | Spread and single-target test in one turn |
| Body Press into Ghost | Gengar's HP was unchanged | Immunity test; separately assert Body Press's `overrideOffensiveStat: def` |
| Defiant | Mud-Slap produced -1 Accuracy and +2 Attack on Annihilape | Actual-move/ability test |
| Competitive | Mud-Slap produced -1 Accuracy and +2 Special Attack on Milotic | Actual-move/ability test |
| Contrary Mega Staraptor | In ordinary conditions Mud-Slap had no effect because Mega Staraptor remains Flying and is immune to Ground; Contrary did not activate | Test ordinary immunity, then a grounded/type-changed case where Contrary reverses the drop |
| Transformation restrictions | Both active slots could initially advertise Mega; a double-Mega choice was rejected; after one Mega, the ally's `canMegaEvo` was false | Generator cross-slot and later-turn availability tests |

Showdown source also directly defines Fake Out at priority +3, Follow Me at +2, Wide Guard at +3, Aurora Veil's weather check, Body Press's Defense override, No Guard's guaranteed Accuracy event, and the Defiant/Competitive/Contrary callbacks. Permanent tests should exercise these callbacks rather than transcribe their logic into tournament code.

## Recommended public schema

The smallest clean direction is a format-neutral transformation layer, not a Mega-flavored copy of the old Tera fields:

```ts
type TransformationKind = 'mega' | 'mega_x' | 'mega_y' |
    'ultra' | 'dynamax' | 'terastallize';

interface TransformationOption {
    kind: TransformationKind;
    result_species?: string; // only when derivable from public/request data
}

interface MoveAction {
    type: 'move';
    move: string;
    target?: Target;
    transformation?: TransformationKind;
}

interface SlotRequest {
    required: boolean;
    moves: MoveOption[];
    switches: OwnPokemonID[];
    revives: OwnPokemonID[];
    available_transformations: TransformationOption[];
}
```

For Champions, only `kind: 'mega'` should occur. `mega_x`/`mega_y` must not be invented for Charizard or Raichu stones; include those kinds only if a format's real ChoiceRequest uses `canMegaEvoX`/`canMegaEvoY`.

Pokemon state should distinguish immutable sheet data from observed current battle data. Current active state should expose at least current/apparent species, public types, current public ability, and active transformation kind. OTS entries should additionally preserve public nature, gender, and level. The schema should not claim an ability is current merely because it was the base ability on the sheet.

`battle` metadata should include both the configured format string and resolved base format/mod so custom OTS rules remain auditable.

## Design-document assumptions requiring amendment

1. **Mud-Slap into Contrary Mega Staraptor:** the document treats this primarily as a Contrary punishment. In the normal field state, Ground-type Mud-Slap is ineffective against Mega Staraptor's Flying typing, so it neither lowers nor raises Accuracy. Contrary matters only after grounding or a relevant type/immunity change.
2. **Gravity “suppresses evasion”:** this is directionally correct for the intended base-100 attacks, but Gravity is an accuracy multiplier, not No Guard. It brought the tested 72 to 120 before capping; lower-accuracy attacks can remain imperfect.
3. **OTS availability:** the target's `Open Team Sheets` rule does not automatically produce sheets in headless BattleStream play. Workstream B may assume OTS only after Workstream A makes acceptance/forcing explicit.
4. **OTS contents:** Champions OTS includes nature, gender, level, and even submitted Tera type while excluding stats/Stat Points/IVs. The current `BotState` only preserves a subset.
5. **X/Y Mega request semantics:** Charizard and Raichu X/Y do not require `megax`/`megay` participant actions in this format. The stone fixes the form and the request/action is ordinary Mega Evolution.
6. **Current-form availability in BotState:** the document describes current own form correctly at a conceptual level, but the implemented opponent state does not update the active ability or expose types after Mega.

The document's 32-per-stat/66-total Stat Point expectation, approximately 72% Snow Cloak + Bright Powder result for a base-100 move, Pelipper-before-Veil ordering concern, Fake Out priority concern, Wide Guard distinction, Body Press Ghost immunity, and No Guard concern were all supported.

## Phased Workstream A implementation plan

### A1 - lock the executable tournament format

- Add a named Champions tournament format/configuration with forced OTS for unattended play.
- Replace the development default and make CLI/result metadata show configured format, resolved format ID, and mod.
- Add exact format/mod/rule-table and tested-team validation tests.

### A2 - make transformations semantic and legal

- Replace Tera-specific action/request fields with `available_transformations` and `transformation`.
- Map actual ChoiceRequest flags to semantic options and semantic options back to Showdown suffixes.
- Enforce side-wide cross-slot Mega uniqueness.
- Update reference bots and action generator/adapter/validator tests.

### A3 - make public state Champions- and format-aware

- Resolve/inject `Dex.forFormat(configuredFormat)` throughout action/state metadata construction.
- Preserve complete public OTS fields without stats.
- Parse `-mega`, reconcile `detailschange`, and expose current public form/types/ability while keeping OTS base data immutable.
- Add player-stream information-boundary regressions, including Illusion.

### A4 - simulator-backed acceptance

- Add the mechanics tests listed above, prioritizing transformation/state, weather ordering, protection/redirection, accuracy, and stat-drop abilities.
- Run two simple reference bots through complete target-format matches with team preview, Mega Evolution from either active slot, switches, forced switches, custom forms, and battle completion.
- Run focused tournament tests, TypeScript, lint, and the appropriate full simulator suite before declaring Workstream A complete.

Workstream B must remain blocked until A1-A3 are complete and the A4 participant-API acceptance match passes.

## Files inspected

- Authoritative design: `tournament/DESIGN.md` and every file under `tournament/docs/deterministic-bot/` in numeric order.
- Harness API/action/state/runtime: `tournament/api/types.ts`, all files in `tournament/actions/`, all files in `tournament/state/`, `tournament/match/match-runner.ts`, `tournament/cli.ts`, and both reference bots.
- Harness tests: action generator, protocol/state builder, match runner, runtime, and Revival Blessing tests under `test/tournament/`.
- Format/mod: `config/formats.ts`, `data/aliases.ts`, and Champions `scripts.ts`, `rulesets.ts`, `items.ts`, `abilities.ts`, `moves.ts`, `formats-data.ts`, plus relevant base Pokedex/item/move/ability entries.
- Simulator path: `sim/dex-formats.ts`, `sim/team-validator.ts`, `sim/teams.ts`, `sim/pokemon.ts`, `sim/side.ts`, `sim/battle-actions.ts`, `sim/battle.ts`, and `sim/battle-stream.ts`.

## Investigative commands/tests run

- Built commit `eeee09826` successfully with `node build` in an isolated worktree.
- Executably resolved format ID/mod/rules, custom Mega species data, picked-team size, and Stat Point limit.
- Compared base Dex and Champions move metadata to identify format-unaware API fields.
- Validated the complete tested snow team; probed per-stat, total, and IV failures.
- Ran real BattleStream probes for target requests, OTS behavior, Mega protocol, next-turn own request data, and current harness legal-action generation.
- Ran real simulator probes for the transformations, weather/terrain entry effects, accuracy/evasion, weather-before-Veil ordering, Fake Out/Follow Me, Wide Guard, Body Press/Ghost, stat-drop abilities, and doubles Mega restrictions summarized above.

The investigative scripts were temporary audit probes, not proposed production mechanics code.
