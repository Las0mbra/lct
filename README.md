# LCT - 40k TTS Base

A fork of Hutber's FTC table (shared with permission), with extra features, refinements, and a slightly different direction — it also filled a gap, since no other table supported 11th edition when the rules dropped. Feel free to take the project and use it as you wish.

## Development

Run the compiler from the `scripts` folder:

```bash
python3 compile.py             # prompt for a version, write the compiled JSON
python3 compile.py --test      # tag as "test", copy to your TTS saves folder
python3 compile.py --release   # version + patch notes from CHANGELOG.md, then copy
python3 compile.py --no-validate   # skip the map-card validation gate
```

`compile.py` stitches `TTSLUA/*.ttslua` back into `TTSJSON/ftc_base.json`, stamps the version, and writes `lct_base_<version>_compiled.json` into `builds/`, printing a build summary at the end.

### Map terrain payloads (`data/maps/`)

Each map card's `LuaScript` is a canonical load/clear machinery head followed by an `objectJSONs = { ... }` terrain blob. Those blobs total ~27 MB, so they live **outside** `ftc_base.json`, one file per map: `data/maps/<card_guid>.lua`. `validate_maps.py` folds each payload back in for its checks; `compile.py` re-injects `head + payload` **byte-for-byte** during the build (before the Load Map hook pass), so the compiled save is identical to the old inline one (a stripped card with no payload file is a build error).

Pull terrain back out after re-exporting from TTS or after an import (add `--dry-run` to preview, `audit_map_payloads.py --sizes|--strict` to inspect):

```bash
python3 extract_map_payloads.py   # strip terrain to data/maps/, shrink the save
```

### The map manifest & `MAP_INDEX`

`data/map_manifest.csv` is the authoritative map-card inventory. Each row records `map_creator_tag`, `map_type_tag`, `creator_display` (full UI name), and `eligible` (`true`/`false` — a per-map on/off switch that excludes a card from generation without deleting it). Keep it in sync whenever the save changes.

At build time `bake_map_index` generates a GUID-keyed `MAP_INDEX` table (`{creator, display, type, eligible}`) from the CSV and stamps it into the `@@MAP_INDEX@@` marker in `TTSLUA/global.ttslua`. Runtime systems (mission generation, map filter) read it via `Global.getTable("MAP_INDEX")` — this lets them look up a card's creator/eligibility even while it's still inside a deck. The source keeps an empty `MAP_INDEX = {}` default so uncompiled builds stay valid.

Map-card nicknames and manifest `card_name` values carry a trailing creator credit (e.g. ` - Cra5hNatural`, ` - T5S2`); runtime matching strips it when resolving layout art and deployment zones. Creator tag→display mappings must stay aligned between `MAP_CREATOR_DISPLAY_NAMES` (`validate_maps.py`) and `mapCreatorDisplaySuffixes` (`startMenu.ttslua`); validation rejects mismatches.

### Validation

Every build validates the baked-in map cards (inventory, tags, terrain, zone size, GUID collisions, mission-matrix references) unless `--no-validate` is passed; errors abort the build. `--test`/`--release` add strict checks (`validate_maps.py --require-map-tags`) that also fail if a manifest map isn't fully wired into `startMenu.ttslua` — each card's head matches `data/map_card_machinery.lua` (no foreign/self-excluding loaders), every source bag is in `deploymentMatrixDecks`, `randomDeploymentDecks` and `GAME_MODE_OBJECTS`, all 25 disposition matchups have a dedicated deck, and each map's logical name has matching layout art in deck `fb4b5d`. Add new checks with the `@check` decorator; runtime behaviors the validator can't model are locked by `scripts/test_validate_maps.py`.

### Adding / migrating maps

Every map card uses **one** canonical load/clear machinery (`data/map_card_machinery.lua`): `loadMap` wipes the zone except mats and `MapExclude`-tagged objects, then spawns terrain only **after the board is verified clear**. Imported maps often ship their own loader — normalize them, never hand-edit:

1. **Normalize** foreign cards onto the machinery (fixes head, GMNotes, tags, credit nicknames, hex GUIDs). `--write` edits the source save in place (or use `--out`); it does not touch `ftc_base.json`:
   ```bash
   python3 normalize_map_card.py ../Legacy/SomeSave.json \
       --container <bagGUID> --creator map_crt_<creator> --type map_type_<type> --write
   ```
2. **Copy** the normalized bag + layout-art tiles into `TTSJSON/ftc_base.json`.
3. **Record** the printed rows in `data/map_manifest.csv`.
4. **Wire** the bag into `startMenu.ttslua` per the printed checklist (`deploymentMatrixDecks`, `randomDeploymentDecks`, `GAME_MODE_OBJECTS`, layout art in deck `fb4b5d`).
5. **Verify**: `python3 validate_maps.py --require-map-tags && python3 compile.py --test`.

New creators must first be added to `MAP_CREATOR_DISPLAY_NAMES` (`validate_maps.py`) and `mapCreatorDisplaySuffixes` (`startMenu.ttslua`).

Upgrading v1 map cards to v2 (deferred wipe that loads/clears reliably) is a separate, explicit step — never done by a normal build:

```bash
python3 upgrade_map_zones.py            # rewrite v1 cards to v2 in ftc_base.json
python3 upgrade_map_zones.py --dry-run  # show what would change, write nothing
```

### Battlemaster imports

Battlemaster maps are baked into normal static LCT cards, not spawned dynamically at runtime. Each theme ships as its own creator filter (`Battlemaster - BTTF Ruins`, `BTTF`, `Battlemaster - Desert`), 45 cards apiece, already in the manifest. There is no plain `map_crt_battlemaster` creator, so **always pass `--creator-tag`/`--creator-display`** matching the theme, or you create a duplicate set.

To (re)import a theme, build a `--test` save, load it, click the matching debug button (`Ruins`/`Desert`/`BTTF` under the DEBUG-gated Battlemaster cache panel), save the table, then:

```bash
# preview the 45 generated cards (no changes written)
python3 import_battlemaster_static_maps.py /path/to/DebugTable.json \
    --creator-tag map_crt_battlemaster_bttf_ruins --creator-display "Battlemaster - BTTF Ruins"
# rerun with --write to place the cards and update the manifest (idempotent per theme)
python3 import_battlemaster_static_maps.py /path/to/DebugTable.json \
    --creator-tag map_crt_battlemaster_bttf_ruins --creator-display "Battlemaster - BTTF Ruins" --write
python3 bake_battlemaster_cache.py --clear   # reset the shipped spawner cache to cold
python3 validate_maps.py --require-map-tags && python3 compile.py --test
```
