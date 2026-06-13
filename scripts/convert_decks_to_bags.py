#!/usr/bin/env python3
"""One-time migration: convert the map source Decks into standard Bags.

Why: a TTS Deck cannot exist with fewer than two cards. When the second-last
card is drawn the Deck object is destroyed, the final card spawns in its place,
and the old Deck GUID becomes invalid. The mission-generation logic in
startMenu.ttslua takes map cards out of these sources by exact GUID and later
returns them, so a 3-card matchup deck collapses after two draws and every
fixed-GUID lookup against it breaks.

Standard Bags fix this permanently: a Bag keeps its GUID when empty, supports
getObjects()/takeObject({guid=...})/putObject(), and never collapses. Cards are
selected here by GUID, not drawn randomly, so a Bag fits the actual behaviour.

This is intentionally NOT part of compile.py -- run it by hand once:

    python3 convert_decks_to_bags.py            # rewrite the source decks in place
    python3 convert_decks_to_bags.py --dry-run  # show what would change, write nothing

A round-trip of TTSJSON/ftc_base.json through json.load/json.dump(indent=2) is
byte-identical, so loading, mutating only the target objects, and dumping back
touches only the converted objects.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import term

JSON_FILE = Path(__file__).parent.parent / "TTSJSON" / "ftc_base.json"

# The 11 map matchup source decks (see deploymentMatrixDecks in startMenu.ttslua).
# Helper sources (primary decks, deployment deck, layout-art deck) stay Decks.
SOURCE_DECK_GUIDS = {
    "6e0d78", "eae80b", "cfeba5", "1e6711", "109a6b", "32e34a",
    "7b5ba7", "3ebbd6", "9ac38f", "dc8738", "a22c33",
}

# Deck-only fields that have no meaning on a Bag.
DECK_ONLY_FIELDS = ("DeckIDs", "CustomDeck", "SidewaysCard")


def convert_deck_to_bag(obj):
    """Mutate a Deck object dict in place into a standard Bag. Cards keep their
    own CustomDeck/CardID, so they stay valid loose or inside the bag."""
    obj["Name"] = "Bag"
    for field in DECK_ONLY_FIELDS:
        obj.pop(field, None)
    obj["Bag"] = {"Order": 0}
    obj.setdefault("MaterialIndex", -1)
    obj.setdefault("MeshIndex", -1)


def main():
    parser = argparse.ArgumentParser(description="Convert map source Decks to Bags.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing the file.")
    args = parser.parse_args()

    if not JSON_FILE.exists():
        print(term.red(f"ERROR: {JSON_FILE} not found."))
        return 1

    original = JSON_FILE.read_text(encoding="utf-8")
    data = json.loads(original)

    converted, skipped = [], []
    for obj in data.get("ObjectStates", []):
        if obj.get("GUID") not in SOURCE_DECK_GUIDS:
            continue
        if obj.get("Name") == "Bag":
            skipped.append(obj)
            continue
        name = obj.get("Nickname") or obj.get("Name") or ""
        cards = len(obj.get("ContainedObjects") or [])
        convert_deck_to_bag(obj)
        converted.append((obj.get("GUID"), name, cards))

    print(term.bold("Convert map source Decks -> Bags" + (" (dry run)" if args.dry_run else "")))
    for guid, name, cards in converted:
        print(term.green(f"  Deck -> Bag  {guid}  {name}  ({cards} cards)"))
    for obj in skipped:
        print(term.dim(f"  already Bag  {obj.get('GUID')}  {obj.get('Nickname') or ''}"))

    found = {g for g, _, _ in converted} | {o.get("GUID") for o in skipped}
    missing = SOURCE_DECK_GUIDS - found
    if missing:
        print(term.yellow(f"  NOTE: {len(missing)} source GUID(s) not found in save: "
                          f"{', '.join(sorted(missing))}"))

    if not converted:
        print(term.dim("\nNothing to do."))
        return 0

    out = json.dumps(data, indent=2, ensure_ascii=False)
    if original.endswith("\n"):
        out += "\n"

    if args.dry_run:
        print(term.yellow(f"\n[dry run] {len(converted)} deck(s) would be converted; file unchanged."))
        return 0

    JSON_FILE.write_text(out, encoding="utf-8")
    print(term.green(f"\n✓ Converted {len(converted)} deck(s) to bags. Wrote {JSON_FILE.name}."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
