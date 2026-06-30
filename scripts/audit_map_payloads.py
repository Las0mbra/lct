#!/usr/bin/env python3
"""Audit extracted map terrain payload files.

Checks the source split introduced by extract_map_payloads.py:

  * every expected map card has data/maps/<guid>.lua
  * no payload files are orphaned
  * payload sizes are visible by creator/source

This is intentionally source-level tooling. It does not compile or mutate the
save; compile.py and validate_maps.py remain the build gates.
"""

import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import map_payloads as P
import term

ROOT = Path(__file__).parent.parent
DEFAULT_SAVE = ROOT / "TTSJSON" / "ftc_base.json"
OBJECTJSON_ENTRY_RE = re.compile(r"\[\[(.*?)\]\]", re.DOTALL)


def payload_files(payload_dir):
    if not payload_dir.exists():
        return {}
    return {p.stem: p for p in payload_dir.glob("*.lua") if p.is_file()}


def card_index(save):
    cards = {}
    parent_by_guid = {}
    for obj, parent_guid in P.walk_objects(save.get("ObjectStates", [])):
        guid = obj.get("GUID")
        if not guid:
            continue
        cards[guid] = obj
        parent_by_guid[guid] = parent_guid
    return cards, parent_by_guid


def creator_for_guid(guid, manifest_by_guid, parent_by_guid):
    row = manifest_by_guid.get(guid)
    if row:
        return row.get("creator_display") or row.get("map_creator_tag") or "Manifest"
    if parent_by_guid.get(guid) in P.EXTRA_MAP_POOL_CONTAINER_GUIDS:
        return "Combat Patrol"
    return "Unknown"


def payload_size(path):
    return path.stat().st_size


def terrain_count(path):
    return len(OBJECTJSON_ENTRY_RE.findall(path.read_text(encoding="utf-8")))


def print_guid_report(guid, path, manifest_by_guid, cards, parent_by_guid):
    row = manifest_by_guid.get(guid)
    card = cards.get(guid)
    print(term.bold(f"Payload {guid}"))
    print(f"  file     : {path if path else 'missing'}")
    print(f"  card     : {(card or {}).get('Nickname') or (row or {}).get('card_name') or 'missing from save/manifest'}")
    print(f"  creator  : {creator_for_guid(guid, manifest_by_guid, parent_by_guid)}")
    if row:
        print(f"  deck     : {row.get('deck_guid')}  {row.get('deck_name')}")
    if path and path.exists():
        print(f"  size     : {payload_size(path):,} bytes")
        print(f"  terrain  : {terrain_count(path):,} object(s)")


def main():
    parser = argparse.ArgumentParser(description="Audit data/maps terrain payloads.")
    parser.add_argument("--save", default=str(DEFAULT_SAVE), help="Source save JSON to audit.")
    parser.add_argument("--payload-dir", default=str(P.PAYLOAD_DIR), help="Payload directory.")
    parser.add_argument("--guid", help="Print detailed info for one card GUID.")
    parser.add_argument("--sizes", action="store_true", help="Print creator totals and largest payloads.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on missing or orphan payloads.")
    args = parser.parse_args()

    save_path = Path(args.save)
    payload_dir = Path(args.payload_dir)
    if not save_path.exists():
        print(term.red(f"ERROR: {save_path} not found."))
        return 1

    save = json.loads(save_path.read_text(encoding="utf-8"))
    rows = P.load_manifest_rows()
    manifest_guids = {row["card_guid"] for row in rows}
    manifest_by_guid = {row["card_guid"]: row for row in rows}
    cards, parent_by_guid = card_index(save)
    expected = P.expected_payload_guids(save, manifest_guids)
    files = payload_files(payload_dir)
    file_guids = set(files)

    if args.guid:
        print_guid_report(args.guid, files.get(args.guid), manifest_by_guid, cards, parent_by_guid)
        if args.strict and args.guid in expected and args.guid not in file_guids:
            return 1
        return 0

    missing = sorted(expected - file_guids)
    orphan = sorted(file_guids - expected)

    print(term.bold("Map Payload Audit"))
    print(f"  expected payloads : {len(expected)}")
    print(f"  payload files     : {len(files)}")
    print(f"  missing           : {len(missing)}")
    print(f"  orphan            : {len(orphan)}")

    if missing:
        print(term.red("\nMissing payloads:"))
        for guid in missing[:30]:
            card = cards.get(guid) or {}
            print(f"  {guid}  {card.get('Nickname') or (manifest_by_guid.get(guid) or {}).get('card_name') or '?'}")
        if len(missing) > 30:
            print(f"  ... {len(missing) - 30} more")

    if orphan:
        print(term.yellow("\nOrphan payloads:"))
        for guid in orphan[:30]:
            print(f"  {guid}  {files[guid]}")
        if len(orphan) > 30:
            print(f"  ... {len(orphan) - 30} more")

    if args.sizes:
        by_creator = collections.defaultdict(lambda: {"count": 0, "bytes": 0})
        largest = []
        for guid in sorted(file_guids & expected):
            path = files[guid]
            size = payload_size(path)
            creator = creator_for_guid(guid, manifest_by_guid, parent_by_guid)
            by_creator[creator]["count"] += 1
            by_creator[creator]["bytes"] += size
            largest.append((size, guid, creator, (cards.get(guid) or {}).get("Nickname")
                            or (manifest_by_guid.get(guid) or {}).get("card_name") or "?"))

        print(term.bold("\nSize by creator:"))
        for creator, stats in sorted(by_creator.items(), key=lambda kv: (-kv[1]["bytes"], kv[0])):
            print(f"  {stats['bytes']:>11,} bytes  {stats['count']:>3}  {creator}")

        print(term.bold("\nLargest payloads:"))
        for size, guid, creator, name in sorted(largest, reverse=True)[:15]:
            print(f"  {size:>9,}  {guid}  {creator}  {name}")

    if args.strict and (missing or orphan):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
