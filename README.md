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

Every build first runs a validator over the baked-in map cards (manifest inventory, whitelist, terrain, zone size, terrain-GUID collisions, mission-matrix references, name-suffix → deployment zone, terrain JSON); errors abort the build. The authoritative deck/card inventory lives in `data/map_manifest.csv`; add or remove map cards there whenever the save changes. Each row records both its `map_creator_tag` and `map_type_tag`. The validator also reports map cards found in the save but missing from the manifest.

Map-card nicknames and manifest `card_name` values include a trailing creator credit, such as ` - Cra5shnatural` or ` - Team Belgium`. Runtime matching strips that credit when resolving shared layout art and deployment zones. Creator tag-to-display-name mappings must stay aligned in `TTSLUA/startMenu.ttslua` and `scripts/validate_maps.py`; validation rejects missing or mismatched credits.

`--test` and `--release` additionally require every manifest-listed map card to have the `map` tag, one tag beginning with `map_crt_`, and one tag beginning with `map_type_`. Missing tags abort the build and print the affected map card GUID. Run the strict check directly with `python3 validate_maps.py --require-map-tags`. Add new checks by decorating a function with `@check` in `validate_maps.py`.

The closing build summary reports map inventory, logical layouts, source containers, creator and map-type distributions, dedicated-versus-fallback matchup coverage, terrain payload size, and each map card's **Map Zones** version (v1 = original wipe, v2 = deferred wipe that loads/clears reliably). Migrating is a separate, explicit step — it is never done by a normal build:

```bash
python3 upgrade_map_zones.py            # rewrite v1 cards to v2 in ftc_base.json
python3 upgrade_map_zones.py --dry-run  # show what would change, write nothing
```