#!/usr/bin/env python3
"""Merge the Narrative (Dominatus) game-mode objects into TTSJSON/ftc_base.json.

These are the 12 components for the Narrative game mode (rules PDF, relic/agenda/
twist/skill decks, Phase bags) that the menu shows on Narrative and destroys on
the other modes. This tool only RE-HOMES the objects verbatim (no script/tag
rewrites -- they are not map cards); all show/hide/destroy behavior lives in
startMenu.ttslua, which normalizes their visibility on load.

Objects are appended at their legacy transforms via a text-level insert so the
rest of the 40MB file keeps its exact formatting.

    python3 import_narrative_objects.py            # preview only, write nothing
    python3 import_narrative_objects.py --write     # merge into ftc_base.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import term

ROOT = Path(__file__).parent.parent
LEGACY_SAVE = ROOT / "Legacy" / "TS_Save_122.json"
JSON_FILE = ROOT / "TTSJSON" / "ftc_base.json"

OBJECT_GUIDS = [
    "813dfe", "a9f390", "021888", "2416e0", "5c9320", "3df7da",
    "69d348", "b574de", "5d128a", "2cf446", "ad038d", "877bb3",
]


def walk(objs):
    for o in objs:
        yield o
        for key in ("ContainedObjects", "States"):
            child = o.get(key)
            if isinstance(child, list):
                yield from walk(child)
            elif isinstance(child, dict):
                yield from walk(list(child.values()))


def append_object_text(json_text, obj):
    """Insert obj (4-space base indent) just before ObjectStates' closing ]."""
    close = "\n  ]\n}"
    idx = json_text.rstrip().rfind(close)
    if idx == -1:
        sys.exit(term.red("ERROR: could not locate ObjectStates array close in ftc_base.json."))
    body = "\n".join("    " + line for line in json.dumps(obj, indent=2, ensure_ascii=False).splitlines())
    return json_text[:idx] + ",\n" + body + json_text[idx:]


def main():
    parser = argparse.ArgumentParser(description="Merge the Narrative game-mode objects into ftc_base.json.")
    parser.add_argument("--write", action="store_true", help="Write the merge (default: preview only).")
    args = parser.parse_args()

    for path in (LEGACY_SAVE, JSON_FILE):
        if not path.exists():
            sys.exit(term.red(f"ERROR: {path} not found."))

    legacy = json.loads(LEGACY_SAVE.read_text(encoding="utf-8"))
    by_guid = {o.get("GUID"): o for o in legacy["ObjectStates"] if o.get("GUID")}
    objs = []
    for g in OBJECT_GUIDS:
        o = by_guid.get(g)
        if not o:
            sys.exit(term.red(f"ERROR: object {g} not found at root of {LEGACY_SAVE.name}."))
        objs.append(o)

    # Collision check across the full subtree of every object being merged.
    main_guids = {o.get("GUID") for o in walk(json.loads(JSON_FILE.read_text(encoding="utf-8"))["ObjectStates"]) if o.get("GUID")}
    collisions = sorted({s.get("GUID") for o in objs for s in walk([o]) if s.get("GUID") in main_guids})
    if collisions:
        sys.exit(term.red(f"ERROR: GUID(s) already present in ftc_base.json: {', '.join(collisions)}."))

    print(term.bold(f"Narrative objects -> {JSON_FILE.name}" + ("" if args.write else " (preview)")))
    for o in objs:
        print(term.green(f"  {o['GUID']}  {o.get('Name')}  \"{o.get('Nickname')}\""))

    new_text = JSON_FILE.read_text(encoding="utf-8")
    for o in objs:
        new_text = append_object_text(new_text, o)

    try:
        json.loads(new_text)
    except json.JSONDecodeError as exc:
        sys.exit(term.red(f"ERROR: merged JSON does not parse ({exc}); aborting."))

    if not args.write:
        print(term.yellow(f"\n[preview] {len(objs)} object(s) would be merged; JSON parses cleanly. Re-run with --write."))
        return 0

    JSON_FILE.write_text(new_text, encoding="utf-8")
    print(term.green(f"\n✓ Merged {len(objs)} Narrative object(s) into {JSON_FILE.name}."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
