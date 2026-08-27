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

Each map card's `LuaScript` is a canonical load/clear machinery head followed by an `objectJSONs = { ... }` terrain blob. Those blobs total ~38 MB, so they live **outside** `ftc_base.json`, one file per map: `data/maps/<card_guid>.lua`. `validate_maps.py` folds each payload back in for its checks; `compile.py` re-injects `head + payload` **byte-for-byte** during the build (before the Load Map hook pass), so the compiled save is identical to the old inline one (a stripped card with no payload file is a build error).

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

Battlemaster maps are baked into normal static LCT cards, not spawned dynamically at runtime. The supported updater now runs entirely outside TTS: it fetches the public Battlemaster API, reconstructs the compact terrain payloads in Python, and prepares normal source cards and payload files.

Run it from the repository root. Every command is preview-only unless `--write` is present:

```bash
# One 45-card pack; granular flags can be combined.
python3 scripts/sync_battlemaster_maps.py --desert
python3 scripts/sync_battlemaster_maps.py --desert --bttf --write

# The four packs formerly populated by the debug "All 4" button (180 cards).
python3 scripts/sync_battlemaster_maps.py --all-four

# Atomic Ice layout 1 + Lava layout 2 + Mars layout 3 (45 cards).
python3 scripts/sync_battlemaster_maps.py --lct-pack-1

# All Four plus LCT Pack 1 (225 cards).
python3 scripts/sync_battlemaster_maps.py --all
```

The granular selectors are `--bttf-ruins`, `--desert`, `--bttf`,
`--armageddon-ruins`, and `--lct-pack-1` (`--lct-p1` is an alias).

Footprint states are selected by pack, with an explicit contract:

- The four Battlemaster packs contain two states: rugged terrain is the
  top-level/default state and smooth terrain is state 2.
- LCT Pack 1 contains three states: its theme-specific custom bordered floor is
  the top-level/default state, rugged terrain is state 2, and smooth terrain is
  state 3.

Preview validates every reconstructed footprint against that state count,
ordering, asset pairing, transform, and objective-tag contract. A mismatched
profile or partially reconstructed map aborts before any source file is changed.

For a reproducible review/apply split, save the normalized API responses during
preview and apply that exact snapshot later without another network request:

```bash
python3 scripts/sync_battlemaster_maps.py --all \
    --snapshot-out /tmp/lct-battlemaster.json
python3 scripts/sync_battlemaster_maps.py --all \
    --snapshot-in /tmp/lct-battlemaster.json --write
```

Before any source write, the updater requires complete 15-pair slot sets,
matching catalog/payload identities, zero skipped terrain parts, valid
deployment/layout-art mappings, unique identities, and a clean full-map
validation against a temporary payload overlay. It preserves existing public
card GUIDs and deck IDs. Semantically unchanged terrain retains its original
bytes, avoiding a large no-op diff.

`--write` stages every replacement before changing source, updates
`TTSJSON/ftc_base.json`, `data/map_manifest.csv`, and `data/maps/` as one
rollback-capable operation, then runs strict map validation, both Python test
suites, the payload audit, and `compile.py --test`. A failed post-write check
restores every affected source file. Use `--skip-compile-test` only when a debug
build is deliberately unnecessary.

`LCT - Pack 1` remains a composite pack with fixed slots:

- Layout 1: `lct - ice colony`
- Layout 2: `lct - lava temple v2.1`
- Layout 3: `lct - mars base`

The DEBUG-gated `All 4`/`LCT P1` cache buttons and
`import_battlemaster_static_maps.py` remain only as a legacy/offline fallback
when a cache has been rebuilt with the current spawner. They are no longer part
of the normal update path: their large persisted `LuaScriptState` forces TTS to
repeatedly serialize tens of megabytes during save/rewind, which is the source
of the long UI stalls. New
legacy cache archives also record their reconstruction schema and footprint
profile, so the importer rejects stale caches built with the former all-three-
state behavior.
