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

sys.path.insert(0, str(Path(__file__).parent))
import map_payloads as P

SCRIPT_DIR = Path(__file__).parent
PATH_JSON = SCRIPT_DIR.parent / "TTSJSON" / "ftc_base.json"
PATH_MAPS = P.PAYLOAD_DIR

# The terrain blob always begins exactly here; everything before it is the
# canonical load/clear machinery head (see data/map_card_machinery.lua).
TERRAIN_MARKER = P.TERRAIN_MARKER

# Full `"LuaScript": "..."` field on one JSON line, tolerating escaped quotes /
# backslashes -- mirrors compile.py / validate_maps.py so the same fields match.
LUASCRIPT_FIELD_RE = re.compile(r'("LuaScript":\s*)"(?:\\.|[^"\\])*"')
GUID_FIELD_RE = re.compile(r'"GUID": "([0-9a-fA-F]{6})"')
LUASCRIPT_SLOT_RE = re.compile(r'"LuaScript": ')


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
    P.write_payload(guid, payload, PATH_MAPS)


def should_extract_card(obj, parent_container_guid, manifest_card_guids):
    guid = obj.get("GUID")
    if not guid:
        return False
    if guid in manifest_card_guids:
        return True
    return parent_container_guid in P.EXTRA_MAP_POOL_CONTAINER_GUIDS


def collect_payloads(save, manifest_card_guids):
    """Return GUID -> terrain payload for map cards this script is allowed to own.

    Do not extract by substring alone. Some non-card system scripts build loader
    card text and legitimately contain the marker as data.
    """
    payloads = {}
    for obj, parent_guid in P.walk_objects(save.get("ObjectStates", [])):
        if not should_extract_card(obj, parent_guid, manifest_card_guids):
            continue
        lua = obj.get("LuaScript", "") or ""
        if TERRAIN_MARKER not in lua:
            continue
        guid = obj.get("GUID")
        split = split_card_lua(lua)
        if split is None:
            continue
        head, payload = split
        # Safety gate: the split must be perfectly reversible.
        if head + payload != lua:
            print(f"ERROR: round-trip split failed for {guid}; aborting.", file=sys.stderr)
            sys.exit(1)
        if guid in payloads and payloads[guid] != payload:
            print(f"ERROR: duplicate GUID {guid} with differing terrain; aborting.", file=sys.stderr)
            sys.exit(1)
        payloads[guid] = payload
    return payloads


def json_guid_and_lua_slots(raw):
    guid_entries, lua_line_idxs = [], []
    for i, line in enumerate(raw.splitlines()):
        m = GUID_FIELD_RE.search(line)
        if m:
            guid_entries.append((i, m.group(1)))
        if LUASCRIPT_SLOT_RE.search(line):
            lua_line_idxs.append(i)
    return guid_entries, lua_line_idxs


def strip_payloads_from_raw(raw, payload_guids):
    """Strip terrain only from allowed payload GUIDs, preserving other bytes."""
    lines = raw.splitlines(keepends=True)
    guid_entries, lua_line_idxs = json_guid_and_lua_slots(raw)
    stripped = 0
    used_slots = set()
    for guid_line_idx, guid in guid_entries:
        if guid not in payload_guids:
            continue
        lua_slot_idx = next((idx for idx in lua_line_idxs if idx > guid_line_idx), None)
        if lua_slot_idx is None:
            print(f"ERROR: no LuaScript slot found after GUID {guid}; aborting.", file=sys.stderr)
            sys.exit(1)
        if lua_slot_idx in used_slots:
            print(f"ERROR: LuaScript slot reused while stripping GUID {guid}; aborting.", file=sys.stderr)
            sys.exit(1)
        used_slots.add(lua_slot_idx)
        line = lines[lua_slot_idx]
        m = LUASCRIPT_FIELD_RE.search(line)
        if not m:
            print(f"ERROR: LuaScript field parse failed for GUID {guid}; aborting.", file=sys.stderr)
            sys.exit(1)
        prefix, value_json = m.group(1), m.group(0)[len(m.group(1)):]
        value = json.loads(value_json)
        split = split_card_lua(value)
        if split is None:
            print(f"ERROR: allowed GUID {guid} has no terrain marker; aborting.", file=sys.stderr)
            sys.exit(1)
        head, _ = split
        lines[lua_slot_idx] = line[:m.start()] + prefix + json.dumps(head) + line[m.end():]
        stripped += 1
    return "".join(lines), stripped


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

    manifest_card_guids = P.manifest_card_guids()
    payloads = collect_payloads(save, manifest_card_guids)

    if not payloads:
        print("No map cards with inline terrain found "
              "(already extracted?). Nothing to do.")
        return

    # Strip only the map-card GUIDs this extractor owns. Non-card scripts may
    # contain the terrain marker as generated text and must stay untouched.
    new_raw, stripped = strip_payloads_from_raw(raw, set(payloads))

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
