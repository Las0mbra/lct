#!/usr/bin/env python3
"""
Extract each map card's terrain blob out of TTSJSON/ftc_base.json into a
per-map file under data/maps/<card_guid>.lua, leaving the card's load/clear
machinery head in the save.

Why
---
Every map card's LuaScript is `<canonical machinery head>` + `objectJSONs = { ...
terrain... }`. The terrain blobs are ~27 MB of the ~35 MB save and make the
source impossible to edit or diff per-map. This moves the terrain to one file
per map (the editable library) while keeping the card identity in the save
unchanged: same GUID, name, tags, bag membership, and machinery head (so
mission generation, the map filter, BACK TO SELECTION, etc. are untouched).

`scripts/compile.py` re-injects `head + payload` at build time, so the compiled
output is byte-identical to before extraction (proven by recompiling and
diffing). `scripts/validate_maps.py` reads the payload files transparently.

This is the Milestone 1 storage refactor: it changes WHERE terrain lives in
source, not WHAT ships or how anything runs.

Idempotent: a card whose LuaScript no longer contains `objectJSONs = {` (already
extracted) is skipped, so it is safe to re-run -- e.g. after re-exporting a full
save from TTS over ftc_base.json.

Usage
-----
    python3 extract_map_payloads.py            # extract, write files + strip save
    python3 extract_map_payloads.py --dry-run  # report only, write nothing
"""

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PATH_JSON = SCRIPT_DIR.parent / "TTSJSON" / "ftc_base.json"
PATH_MAPS = SCRIPT_DIR.parent / "data" / "maps"

# The terrain blob always begins exactly here; everything before it is the
# canonical load/clear machinery head (see data/map_card_machinery.lua).
TERRAIN_MARKER = "objectJSONs = {"

# Full `"LuaScript": "..."` field on one JSON line, tolerating escaped quotes /
# backslashes -- mirrors compile.py / validate_maps.py so the same fields match.
LUASCRIPT_FIELD_RE = re.compile(r'("LuaScript":\s*)"(?:\\.|[^"\\])*"')


def split_card_lua(lua: str):
    """Return (head, payload) for a map card LuaScript, or None if it carries no
    terrain blob (not a map card, or already extracted)."""
    idx = lua.find(TERRAIN_MARKER)
    if idx == -1:
        return None
    return lua[:idx], lua[idx:]


def write_payload(guid: str, payload: str):
    """Write one terrain payload verbatim. newline="" keeps the blob's mixed
    \\r\\n / \\n endings byte-exact so recompilation reproduces the original."""
    path = PATH_MAPS / f"{guid}.lua"
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change; write nothing.")
    args = parser.parse_args()

    if not PATH_JSON.exists():
        print(f"ERROR: {PATH_JSON} not found.", file=sys.stderr)
        sys.exit(1)

    raw = PATH_JSON.read_text(encoding="utf-8")
    save = json.loads(raw)

    # Walk every object (including ContainedObjects) to map GUID -> payload, and
    # gate each split with a round-trip assert before anything is written.
    def walk(objs):
        for obj in objs:
            yield obj
            yield from walk(obj.get("ContainedObjects") or [])

    payloads = {}          # guid -> payload text
    skipped_already = 0
    for obj in walk(save.get("ObjectStates", [])):
        lua = obj.get("LuaScript", "") or ""
        if TERRAIN_MARKER not in lua:
            continue
        guid = obj.get("GUID")
        if not guid:
            print(f"ERROR: map card with terrain has no GUID "
                  f"({obj.get('Nickname') or obj.get('Name')!r}); aborting.", file=sys.stderr)
            sys.exit(1)
        head, payload = split_card_lua(lua)
        # Safety gate: the split must be perfectly reversible.
        if head + payload != lua:
            print(f"ERROR: round-trip split failed for {guid}; aborting.", file=sys.stderr)
            sys.exit(1)
        if guid in payloads and payloads[guid] != payload:
            print(f"ERROR: duplicate GUID {guid} with differing terrain; aborting.", file=sys.stderr)
            sys.exit(1)
        payloads[guid] = payload

    if not payloads:
        print("No map cards with inline terrain found "
              "(already extracted?). Nothing to do.")
        return

    # Strip the save by recomputing each terrain LuaScript's head from the field
    # value itself. Full-text regex sub touches only LuaScript fields that carry
    # terrain and leaves every other byte (incl. line endings) untouched.
    stripped = 0

    def strip_field(match):
        nonlocal stripped
        prefix, value_json = match.group(1), match.group(0)[len(match.group(1)):]
        try:
            value = json.loads(value_json)
        except (json.JSONDecodeError, ValueError):
            return match.group(0)
        if TERRAIN_MARKER not in value:
            return match.group(0)
        head, _ = split_card_lua(value)
        stripped += 1
        return prefix + json.dumps(head)

    new_raw = LUASCRIPT_FIELD_RE.sub(strip_field, raw)

    if stripped != len(payloads):
        print(f"ERROR: stripped {stripped} field(s) but found {len(payloads)} "
              f"payload(s); counts must match. Aborting.", file=sys.stderr)
        sys.exit(1)

    total_bytes = sum(len(p) for p in payloads.values())
    print(f"Map cards with inline terrain : {len(payloads)}")
    print(f"Terrain payload extracted     : {total_bytes:,} chars "
          f"(~{total_bytes/1e6:.1f} MB)")
    print(f"Save size  {len(raw):,} -> {len(new_raw):,} bytes "
          f"(-{(len(raw)-len(new_raw))/1e6:.1f} MB)")

    if args.dry_run:
        print("\n[dry-run] No files written.")
        return

    PATH_MAPS.mkdir(parents=True, exist_ok=True)
    for guid, payload in payloads.items():
        write_payload(guid, payload)
    PATH_JSON.write_text(new_raw, encoding="utf-8")

    print(f"\nWrote {len(payloads)} payload file(s) to {PATH_MAPS}")
    print(f"Stripped terrain from {PATH_JSON}")
    print("Next: build with compile.py and diff against a pre-extraction build "
          "to confirm a byte-identical compile.")


if __name__ == "__main__":
    main()
