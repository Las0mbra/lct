# LCT - 40k TTS Base

A lightweight and actively maintained base for Warhammer 40k Tabletop Simulator maps, focused on gameplay clarity and quality-of-life improvements.

This project is a fork of Hutber’s FTC table (shared with permission), building on that strong foundation with additional features, refinements, and a slightly different design direction.

The aim of this fork is to provide a clean, self-contained experience while continuing to iterate on usability and tooling for both players and developers.

Feel free to take the project and use it as you with it.
New to Tabletop Simulator or this table? Start with the [Quick Guide](TUTORIAL_GUIDE.md).

## Features

- VP/CP overlay for easier score tracking  
- Improved chess clock  
- Expanded dice functionality (including D3 support and quick right-click rolling)  
- Cleaner handling of drawn lines and bubble elements  
- Streamlined and simplified UI  
- Removal of unused UI components  
- Developer-friendly PowerShell compiler improvements  

Some integrations have also been adjusted to keep the project more self-contained.

Dynamic map generation (based on missions) is not yet implemented, but is currently in active development.

## Development

To run the compiler via Python, execute the following from the `scripts` folder:

```bash
python3 compile.py             # prompt for a version, write the compiled JSON
python3 compile.py --test      # tag as "test" and copy to your TTS saves folder
python3 compile.py --release   # take version + patch notes from CHANGELOG.md, then copy
python3 compile.py --no-validate   # skip the map-card check gate (see below)
```

`compile.py` stitches the `TTSLUA/*.ttslua` scripts back into `TTSJSON/ftc_base.json`, stamps the version, and writes `lct_base_<version>_compiled.json` into the `builds` folder, printing a colored build summary at the end.

Battlemaster map imports are baked into normal static LCT map cards, not loaded dynamically at runtime (commit `3039dba` pivoted away from the old runtime warm-cache model). Each terrain theme ships as its **own** creator filter — currently `Battlemaster - BTTF Ruins`, `Battlemaster - Grimdark` (BTTF), and an Armageddon Desert variant — 45 cards apiece, already present in `data/map_manifest.csv`. There is no plain `map_crt_battlemaster` / "Battlemaster" creator; running the importer with default flags would create a duplicate fourth set, so **always pass `--creator-tag`/`--creator-display`** that match the theme you populated.

To (re)import a theme: build a debug save, load it in TTS, press the matching debug button (`BM cache Ruins`, `BM cache Desert`, or `BM cache BTTF` — not the generic `BM cache populate`), wait for it to finish, then save the table. From the `scripts` folder, run the importer once without `--write` to preview the 45 generated cards, then rerun with `--write` to place them in the existing source bags and update the manifest (the importer first removes any prior import of the same creator tag, so it is idempotent per theme). Then clear the now-redundant spawner cache blob, validate, and compile so the generated cards get the standard LCT load hook and appear under their creator filter.

```bash
python3 compile.py --test
# in TTS: click "BM cache Ruins" (or Desert / BTTF), wait, save the table
python3 import_battlemaster_static_maps.py /path/to/SavedBattlemasterDebugTable.json \
    --creator-tag map_crt_battlemaster_bttf_ruins --creator-display "Battlemaster - BTTF Ruins"           # preview 45 cards
python3 import_battlemaster_static_maps.py /path/to/SavedBattlemasterDebugTable.json \
    --creator-tag map_crt_battlemaster_bttf_ruins --creator-display "Battlemaster - BTTF Ruins" --write
python3 bake_battlemaster_cache.py --clear   # drop the spawner LuaScriptState blob; static cards now carry the geometry
python3 validate_maps.py --require-map-tags
python3 compile.py --test
```

The `BM cache *` buttons (and the `BM cache check` reporter) only spawn in `--test`/debug builds — they live on the debug panel gated by the `DEBUG` flag. There is no in-TTS "clear cache" button; `bake_battlemaster_cache.py --clear` resets the shipped spawner cache to cold by writing its `LuaScriptState` back to `""`.

Every build first runs a validator over the baked-in map cards (manifest inventory, whitelist, terrain, zone size, terrain-GUID collisions, mission-matrix references, name-suffix → deployment zone, terrain JSON); errors abort the build. The authoritative deck/card inventory lives in `data/map_manifest.csv`; add or remove map cards there whenever the save changes. Each row records its `map_creator_tag`, `map_type_tag`, `creator_display` (the full creator name shown in UI), and `eligible` (`true`/`false` — a per-map on/off switch that excludes a card from generation without deleting it). The validator also reports map cards found in the save but missing from the manifest, rejects a non-boolean `eligible` or an empty/inconsistent `creator_display`, and fails the build if any deck × layout has no `eligible` map left.

The manifest is the single source of truth for this metadata: at build time `bake_map_index` (in `scripts/compile.py`) generates a GUID-keyed `MAP_INDEX` table (`{creator, display, eligible}`) from the CSV and stamps it into the `@@MAP_INDEX@@` marker in `TTSLUA/global.ttslua` (same mechanism as the `@@LCT_...@@` version markers). The source file keeps an empty `MAP_INDEX = {}` default so dev/uncompiled builds stay valid. Runtime systems (mission generation and the map filter) read it with `Global.getTable("MAP_INDEX")` — this also lets them look up a card's creator/eligibility while it is still inside a deck, where its tags are not directly readable.

Map-card nicknames and manifest `card_name` values include a trailing creator credit, such as ` - Cra5hNatural` or ` - Team Belgium`. Runtime matching strips that credit when resolving shared layout art and deployment zones. Creator tag-to-display-name mappings must stay aligned in `TTSLUA/startMenu.ttslua` and `scripts/validate_maps.py`; validation rejects missing or mismatched credits.

`--test` and `--release` additionally require every manifest-listed map card to have the `map` tag, one tag beginning with `map_crt_`, and one tag beginning with `map_type_`. Missing tags abort the build and print the affected map card GUID. Run the strict check directly with `python3 validate_maps.py --require-map-tags`. Add new checks by decorating a function with `@check` in `validate_maps.py`.

The closing build summary reports map inventory, logical layouts, source containers, creator and map-type distributions, dedicated-versus-fallback matchup coverage, terrain payload size, and each map card's **Map Zones** version (v1 = original wipe, v2 = deferred wipe that loads/clears reliably). Migrating is a separate, explicit step — it is never done by a normal build:

```bash
python3 upgrade_map_zones.py            # rewrite v1 cards to v2 in ftc_base.json
python3 upgrade_map_zones.py --dry-run  # show what would change, write nothing
```

### Migrating map cards (one canonical machinery)

Every map card uses the **same** load/clear machinery — the text before its
`objectJSONs = {` terrain blob — stored once in `data/map_card_machinery.lua`.
`loadMap` spawns a scripting zone, wipes everything inside it except the mats and
`MapExclude`-tagged objects, and only **after the board is verified clear** spawns
that card's terrain; `clearMap` runs the same wipe. A card must never define its
own load system, and a loader card must never carry `GMNotes = "MapExclude"` (it
would exclude itself from the wipe and never clear — the bug that hid behind the
imported "Battlemaster" cards).

Maps imported from other mods often ship a foreign loader. Normalize them instead
of hand-editing:

```bash
# rewrite every card in a bag onto the canonical machinery (head, GMNotes, tags,
# creator-credit nickname, hex GUID), then print manifest rows + a wiring checklist
python3 normalize_map_card.py ../Legacy/SomeSave.json \
    --container <bagGUID> --creator map_crt_<creator> --type map_type_<type> --write
```

New creators must be added to `MAP_CREATOR_DISPLAY_NAMES` in `validate_maps.py`
and `mapCreatorDisplaySuffixes` in `startMenu.ttslua` first.

### What the strict build enforces beyond tags

A map can pass the static checks and still break at runtime, so `--test` /
`--release` (i.e. `validate_maps.py --require-map-tags`) also fail the build if any
manifest map/source-bag is not bound to every runtime system in
`TTSLUA/startMenu.ttslua`:

- the card's head matches `data/map_card_machinery.lua` (no foreign loaders);
- no loader card is self-excluded via `GMNotes = "MapExclude"`;
- every source bag is in `deploymentMatrixDecks` (reachable via Generate Mission),
  `randomDeploymentDecks` (returns to its bag on disposition change), and
  `GAME_MODE_OBJECTS` (hidden pre-game **and** snapshotted for BACK TO SELECTION);
- all 25 disposition matchups have a dedicated deck (no random-mission fallback);
- each map's logical name has matching layout art in deck `fb4b5d`.

The manifest (`data/map_manifest.csv`) is the authoritative inventory; these checks
prove the hand-maintained startMenu wiring stays consistent with it. Runtime
behaviors the validator can't model directly (the snapshot, return-to-bag) are
locked by tests in `scripts/test_validate_maps.py`.

## Map migration

Maps come from many sources, and imported ones often ship their **own** load/clear
system. The "Battlemaster" cards, for example, spawned terrain tagged by GMNotes
instead of wiping the board, and the loader cards carried `GMNotes = "MapExclude"`
— so they excluded *themselves* from every wipe and never cleared off the mat.
Bugs like that pass the tag checks but break play. The fix is a rule: **every map
card uses one canonical load/clear machinery; foreign cards are normalized to it,
never hand-edited.** Challenges this closed: a parallel-timer spawn that raced the
wipe (now the spawn waits for a verified-clear board), self-excluding loader cards,
non-hex GUIDs, and — the deeper one — maps that validated yet weren't wired into
the runtime systems (mission matrix, return-to-bag, hide-pre-game, BACK TO
SELECTION). Those are now hard build errors.

Normal flow to add a batch of maps from another save:

1. **Normalize** the foreign cards onto the canonical machinery (also clears
   GMNotes, applies tags, fixes nicknames/GUIDs) and copy the bag + tiles into
   `TTSJSON/ftc_base.json`:
   ```bash
   python3 normalize_map_card.py ../Legacy/SomeSave.json \
       --container <bagGUID> --creator map_crt_<creator> --type map_type_<type> --write
   ```
2. **Record** the printed rows in `data/map_manifest.csv` (the inventory).
3. **Wire** the bag into `TTSLUA/startMenu.ttslua` using the printed checklist:
   `deploymentMatrixDecks` (under each matchup key), `randomDeploymentDecks`,
   `GAME_MODE_OBJECTS`, and matching layout art in deck `fb4b5d`.
4. **Verify** — the strict build fails until every step above is consistent:
   ```bash
   python3 validate_maps.py --require-map-tags && python3 compile.py --test
   ```

If a new creator is involved, add it to `MAP_CREATOR_DISPLAY_NAMES`
(`validate_maps.py`) and `mapCreatorDisplaySuffixes` (`startMenu.ttslua`) first.