# Workstream A executable-format amendment

Status: authoritative amendment to the 16-part deterministic-bot design after testing the executable `[Gen 9 Champions] VGC 2026 Reg M-B` format.

This amendment changes harness/mechanics assumptions only. It does not begin Workstream B or prescribe snow-team decisions.

The final Champions-compatible participant contract is `BotState.schema_version: 2` because Workstream A intentionally replaced the original Tera-specific schema.

## Exact format boundary

- Configured format ID: `gen9championsvgc2026regmb`.
- Resolved mod: `champions`.
- The format is bring-6/pick-4 Doubles and generates 360 ordered Team Preview responses.
- Terastallization is illegal. A submitted Tera type can still appear as inert OTS metadata and must never be interpreted as action availability.
- Champions Stat Points are validated by Showdown: at most 32 per stat, at most 66 total, with 31 IVs required. Tournament code must not duplicate this validator.

## Final transformation API

The public API uses `available_transformations` on each slot, `transformation` on move actions, and nullable current `transformation` state on Pokemon. Transformation kinds are format-neutral:

```ts
type TransformationKind =
    'mega' | 'mega_x' | 'mega_y' | 'ultra' | 'dynamax' | 'terastallize';

interface TransformationOption {
    kind: TransformationKind;
    result_species?: string;
}
```

For this Champions format, all stones—including Charizardite X/Y and Raichunite X/Y—use ordinary `kind: 'mega'`; the stone fixes the result. `mega_x` and `mega_y` are reserved for formats whose real request exposes those distinct flags. Only the adapter translates semantic kinds into Showdown suffixes. The current request is authoritative, so transformation options disappear after an ally Mega Evolves.

## Format-aware mechanics data

All move, species, item, form, type, and public ability resolution must start from `Dex.forFormat(configuredFormat)`. The base Dex is not equivalent: the Champions mod changes data such as Growth's type, Anchorshot's base power, Protect's PP, and the custom Mega forms. Bot battle metadata includes the resolved mod.

## Open Team Sheets

The exact format uses consensual `Open Team Sheets`; a raw headless battle does not publish sheets automatically. The runner performs the simulator-supported OTS acceptance command during Team Preview, before participant decisions. It does not replace the exact format with a custom rule string.

Champions OTS exposes species, item, ability, moves, nature, gender, level, and inert Tera type. It excludes calculated stats, Stat Points/EVs, and IVs. Immutable sheet values stay separate from observed current active form, types, ability, item, and transformation.

The checked-in `champions-snow.txt` fixture is the exact six-set team specified in parts 1-2, including its natures, Stat Points, items, and moves. It is both the CLI Champions fixture and a validation regression.

## Public post-Mega state

Own current state comes from the player's request. Opponent current state comes only from that player's protocol stream. Public `detailschange` and `-mega` events update apparent form, format-correct types, public fixed Mega ability, and transformation use while preserving stable OTS identity when already established.

Returning publicly identified Mega forms are normalized through the format Dex on every switch-in, so immutable OTS base abilities never overwrite their current Mega abilities.

Illusion remains conservative: `apparent_species` preserves the visible appearance, while opponent `types` is `null` if actual identity/type is unresolved. Transformation is not inferred solely from an unresolved apparent form. A direct public Mega event may reveal that the active PokÃ©mon transformed without authorizing hidden type or ability inference.

## Corrected mechanics assumptions

- Mud-Slap has no ordinary defensive value into Mega Staraptor because Mega Staraptor remains Flying and is immune to Ground. Contrary becomes relevant only after grounding or a relevant type/immunity change allows the move to affect it.
- Gravity multiplies accuracy; it is not equivalent to No Guard for every move.
- Mega Charizard Y activates Drought and Mega Raichu X activates Electric Surge on transformation. Mega Raichu Y exposes No Guard. Their current public state must reflect those abilities and resulting field effects.
- OTS availability is a harness responsibility in unattended play and cannot be assumed merely because the exact format contains the consensual rule.

Workstream B may rely on these corrected public contracts but must continue treating Showdown as the mechanics authority.
