#!/usr/bin/env python3
"""Merge the Combat Patrol map pool into TTSJSON/ftc_base.json.

The Combat Patrol maps are a self-contained game-mode pool, NOT part of the
Generate Mission map system: they live in their own bag, carry no publishing
tags, and are deliberately ignored by the map validator (see
validate_maps.MAP_VALIDATION_IGNORE_CONTAINER_GUIDS). This tool does two things,
mirroring how foreign LCT maps are normalized:

  1. Re-homes each card's load/clear machinery onto the canonical v2 head
     (data/map_card_machinery.lua) so Load Map no longer races its own wipe --
     but keeps the Combat Patrol 30x44 `zoneScale` instead of Strike Force's
     60x44. The card's own baked terrain (`objectJSONs = {...}`) is preserved,
     and GMNotes is cleared (drops any MapExclude self-exclusion).
  2. Appends the bag (renamed "Combat Patrol Maps") with the three fixed cards
     inside it to ObjectStates, via a text-level insert so the rest of the
     file keeps its exact formatting. On --write, each card's terrain is written
     to data/maps/<card_guid>.lua and stripped from ftc_base.json like normal map
     cards.

The compile step injects the standard `onMapCardLoaded` hook into every card
with a `loadMap`, so these get the LCT load hook automatically on the next build.

    python3 import_combat_patrol_maps.py            # preview only, write nothing
    python3 import_combat_patrol_maps.py --write     # merge into ftc_base.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import map_payloads as P
import term
import validate_maps as V

ROOT = Path(__file__).parent.parent
LEGACY_SAVE = ROOT / "Legacy" / "TS_Save_122.json"
JSON_FILE = ROOT / "TTSJSON" / "ftc_base.json"

BAG_GUID = "fdf6e7"
BAG_NAME = "Combat Patrol Maps"
CARD_GUIDS = ["9200fe", "c2f5b5", "7ed2be"]  # Combat Patrol 1 / 2 / 3

OBJECTJSONS_MARKER = "objectJSONs = {"
# Combat Patrol is always the 44x30 battlefield, so the wipe/load zone must be
# that size, not the canonical Strike Force 60x44.
CP_ZONE_SCALE_LINE = "zoneScale = {x=44.04, y=73, z=30.15} --30x44 Incursion and Combat Patrol Size"
STRIKE_FORCE_ZONE_RE = re.compile(r"zoneScale = \{[^}]*\}[^\n]*")


def walk(objs):
    for o in objs:
        yield o
        for key in ("ContainedObjects", "States"):
            child = o.get(key)
            if isinstance(child, list):
                yield from walk(child)
            elif isinstance(child, dict):
                yield from walk(list(child.values()))


def cp_machinery_head():
    """Canonical v2 head, with the Combat Patrol zoneScale swapped in."""
    head = V.MAP_CARD_MACHINERY.read_text(encoding="utf-8")
    head, n = STRIKE_FORCE_ZONE_RE.subn(CP_ZONE_SCALE_LINE, head, count=1)
    if n != 1:
        sys.exit(term.red("ERROR: could not find zoneScale line in canonical machinery template."))
    return head


def fix_card(card, head):
    """Re-home one card onto the CP machinery head, keeping its terrain blob."""
    guid = card.get("GUID")
    lua = card.get("LuaScript", "") or ""
    if OBJECTJSONS_MARKER not in lua:
        sys.exit(term.red(f"ERROR: card {guid} has no '{OBJECTJSONS_MARKER}' terrain blob."))
    blob = lua[lua.index(OBJECTJSONS_MARKER):]
    card["LuaScript"] = head + blob
    card["GMNotes"] = ""
    return card


def build_bag():
    """Return the finished bag object (renamed, 3 fixed cards inside)."""
    save = json.loads(LEGACY_SAVE.read_text(encoding="utf-8"))
    by_guid = {o.get("GUID"): o for o in walk(save["ObjectStates"])}

    bag = by_guid.get(BAG_GUID)
    if not bag:
        sys.exit(term.red(f"ERROR: bag {BAG_GUID} not found in {LEGACY_SAVE.name}."))

    head = cp_machinery_head()
    cards = []
    for g in CARD_GUIDS:
        card = by_guid.get(g)
        if not card:
            sys.exit(term.red(f"ERROR: card {g} not found in {LEGACY_SAVE.name}."))
        cards.append(fix_card(card, head))

    bag["Nickname"] = BAG_NAME
    bag["ContainedObjects"] = cards
    return bag


def append_object_text(json_text, obj):
    """Insert obj (4-space base indent) just before ObjectStates' closing ]."""
    # The file ends `...\n    }\n  ]\n}\n`: the last object, then the array close.
    close = "\n  ]\n}"
    idx = json_text.rstrip().rfind(close)
    if idx == -1:
        sys.exit(term.red("ERROR: could not locate ObjectStates array close in ftc_base.json."))
    # json.dumps starts the brace at column 0; prefix every line by 4 spaces to
    # match the existing top-level object indentation (brace at 4, keys at 6).
    body = "\n".join("    " + line for line in json.dumps(obj, indent=2, ensure_ascii=False).splitlines())
    return json_text[:idx] + ",\n" + body + json_text[idx:]


def main():
    parser = argparse.ArgumentParser(description="Merge the Combat Patrol map pool into ftc_base.json.")
    parser.add_argument("--write", action="store_true", help="Write the merge (default: preview only).")
    args = parser.parse_args()

    for path in (LEGACY_SAVE, JSON_FILE, V.MAP_CARD_MACHINERY):
        if not path.exists():
            sys.exit(term.red(f"ERROR: {path} not found."))

    main_guids = {o.get("GUID") for o in walk(json.loads(JSON_FILE.read_text(encoding="utf-8"))["ObjectStates"])}
    collisions = [g for g in [BAG_GUID, *CARD_GUIDS] if g in main_guids]
    if collisions:
        sys.exit(term.red(f"ERROR: GUID(s) already present in ftc_base.json: {', '.join(collisions)}."))

    bag = build_bag()
    print(term.bold(f"Combat Patrol pool -> {JSON_FILE.name}" + ("" if args.write else " (preview)")))
    print(term.green(f"  bag {BAG_GUID}  \"{bag['Nickname']}\"  ({len(bag['ContainedObjects'])} cards)"))
    for c in bag["ContainedObjects"]:
        zone = STRIKE_FORCE_ZONE_RE.search(c["LuaScript"])
        v2 = V.MAP_ZONES_V2_MARKER in c["LuaScript"]
        print(term.green(f"    card {c['GUID']}  \"{c.get('Nickname')}\"  v2={v2}  "
                         f"{zone.group(0) if zone else '??'}"))

    original = JSON_FILE.read_text(encoding="utf-8")
    preview_text = append_object_text(original, bag)

    try:
        json.loads(preview_text)
    except json.JSONDecodeError as exc:
        sys.exit(term.red(f"ERROR: merged JSON does not parse ({exc}); aborting."))

    if not args.write:
        print(term.yellow("\n[preview] merged JSON parses cleanly; file unchanged. Re-run with --write."))
        return 0

    for card in bag["ContainedObjects"]:
        P.strip_card_to_payload(card)
    new_text = append_object_text(original, bag)
    try:
        json.loads(new_text)
    except json.JSONDecodeError as exc:
        sys.exit(term.red(f"ERROR: stripped merged JSON does not parse ({exc}); aborting."))

    JSON_FILE.write_text(new_text, encoding="utf-8")
    print(term.green(f"\n✓ Merged the Combat Patrol pool into {JSON_FILE.name} and data/maps."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
