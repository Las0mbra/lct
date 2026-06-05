# LCT - 40k TTS Base

A lightweight and actively maintained base for Warhammer 40k Tabletop Simulator maps, focused on gameplay clarity and quality-of-life improvements.

This project is a fork of Hutber’s FTC table (shared with permission), building on that strong foundation with additional features, refinements, and a slightly different design direction.

The aim of this fork is to provide a clean, self-contained experience while continuing to iterate on usability and tooling for both players and developers.

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

To run the compiler via Python, execute the following from the `Compiler` folder:

```bash
python3 compile.py             # prompt for a version, write the compiled JSON
python3 compile.py --test      # tag as "test" and copy to your TTS saves folder
python3 compile.py --release   # take version + patch notes from CHANGELOG.md, then copy
python3 compile.py --no-validate   # skip the map-card check gate (see below)
```

`compile.py` stitches the `TTSLUA/*.ttslua` scripts back into `TTSJSON/ftc_base.json`, stamps the version, and prints a colored build summary at the end.

Every build first runs a validator over the baked-in map cards (whitelist, terrain, zone size); errors abort the build. Run it on its own with `python3 validate_maps.py`, and add new checks by decorating a function with `@check` in `validate_maps.py`.