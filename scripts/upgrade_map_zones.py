#!/usr/bin/env python3
"""Dedicated command to upgrade map cards to "Map Zones v2".

This is intentionally NOT part of `compile.py --test/--release`: a normal build
only *reports* who is on v1/v2, it never mutates the cards. Run this by hand when
you want to migrate:

    python3 upgrade_map_zones.py            # rewrite v1 cards in TTSJSON/ftc_base.json
    python3 upgrade_map_zones.py --dry-run  # show what would change, write nothing

It rewrites each v1 card's `scriptzoneCallback` to the deferred v2 form (see
validate_maps.migrate_card_lua) directly in the source JSON, touching only the
changed card lines so the rest of the file keeps its exact formatting.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import term
import validate_maps

JSON_FILE = Path(__file__).parent.parent / "TTSJSON" / "ftc_base.json"


def upgrade_text(json_text: str):
    """Rewrite v1 -> v2 in the raw JSON text. Return (new_text, changed_count).

    Operates line by line so only the changed card LuaScript lines are touched;
    the rest of the file keeps its exact bytes.
    """
    lines = json_text.splitlines()
    changed = 0
    for i, line in enumerate(lines):
        m = validate_maps.LUASCRIPT_FIELD_RE.search(line)
        if not m:
            continue
        prefix = m.group(1)
        try:
            lua = json.loads(m.group(0)[len(prefix):])  # value portion -> raw lua
        except (json.JSONDecodeError, ValueError):
            continue
        if "function scriptzoneCallback" not in lua:
            continue
        new_lua, did = validate_maps.migrate_card_lua(lua)
        if not did:
            continue
        lines[i] = line[:m.start()] + prefix + json.dumps(new_lua) + line[m.end():]
        changed += 1

    new_text = "\n".join(lines)
    if json_text.endswith("\n"):
        new_text += "\n"
    return new_text, changed


def main():
    parser = argparse.ArgumentParser(description="Upgrade map cards to Map Zones v2.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing the file.")
    args = parser.parse_args()

    if not JSON_FILE.exists():
        print(term.red(f"ERROR: {JSON_FILE} not found."))
        return 1

    original = JSON_FILE.read_text(encoding="utf-8")

    # Object tree gives accurate per-card identity for the report; the text pass
    # below does the actual in-place rewrite.
    ctx = validate_maps.build_context(json.loads(original).get("ObjectStates", []))
    _, v1_before = validate_maps.split_by_zone_version(ctx)
    v2_before = [c for c in ctx.cards if c.zones_version == "v2"]

    new_text, changed = upgrade_text(original)

    print(term.bold("Map Zones upgrade" + (" (dry run)" if args.dry_run else "")))
    for c in v1_before:
        print(term.green(f"  v1 -> v2   {c.guid}  {c.name}"))
    for c in v2_before:
        print(term.dim(f"  already v2  {c.guid}  {c.name}"))

    if changed != len(v1_before):
        print(term.yellow(f"  NOTE: rewrote {changed} line(s) but found {len(v1_before)} "
                          f"v1 card(s) — check for an unexpected card layout."))

    if not changed:
        print(term.dim(f"\nNothing to do — {len(v2_before)} card(s) already on v2."))
        return 0

    # Never write a file we can't parse back.
    try:
        json.loads(new_text)
    except json.JSONDecodeError as exc:
        print(term.red(f"ERROR: rewrite produced invalid JSON ({exc}); aborting."))
        return 1

    if args.dry_run:
        print(term.yellow(f"\n[dry run] {changed} card(s) would be upgraded; file unchanged."))
        return 0

    JSON_FILE.write_text(new_text, encoding="utf-8")
    print(term.green(f"\n✓ Upgraded {changed} card(s) to Map Zones v2 "
                     f"({len(v2_before)} already v2). Wrote {JSON_FILE.name}."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
