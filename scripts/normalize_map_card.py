#!/usr/bin/env python3
"""Normalize foreign map cards onto this table's one canonical load/clear machinery.

Maps imported from other mods often ship their own load system (the "Battlemaster"
cards spawned/cleared by GMNotes tag, never wiping the board; they were also tagged
`MapExclude`, so they excluded *themselves* from every wipe). A card can satisfy
the manifest/tag checks and still behave completely differently at runtime.

This tool rewrites such cards into the standard form, exactly as done by hand for
a foreign map-card batch:

  * LuaScript head  -> data/map_card_machinery.lua (the canonical wipe/spawn), with
                       the card's own terrain blob (`objectJSONs = {...}`) kept.
  * GMNotes         -> "" (drops MapExclude / BattlemasterSpawned self-exclusion).
  * Tags            -> [map, map_crt_<creator>, map_type_<type>].
  * Nickname        -> trailing creator credit normalized to " - <DisplayName>".
  * GUID            -> a fresh 6-hex GUID if the card's is non-hex (the `bmcard` case).

It then prints the map_manifest rows and a startMenu wiring checklist to paste in;
`validate_maps.py --require-map-tags` enforces the rest.

    # normalize every card in a bag, write the result back into the legacy save:
    python3 normalize_map_card.py ../Legacy/TS_Save_122.json \\
        --container <bagGUID> --creator map_crt_example --type map_type_comp --write

    # preview only (no file written):
    python3 normalize_map_card.py ../Legacy/TS_Save_122.json --cards e154fa,4c3e76 \\
        --creator map_crt_example --type map_type_comp
"""

import argparse
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import term
import validate_maps as V

OBJECTJSONS_MARKER = "objectJSONs = {"


def walk(objs):
    for o in objs:
        yield o
        for key in ("ContainedObjects", "States"):
            child = o.get(key)
            if isinstance(child, list):
                yield from walk(child)
            elif isinstance(child, dict):
                yield from walk(list(child.values()))


def all_guids(save):
    return {o.get("GUID") for o in walk(save.get("ObjectStates", [])) if o.get("GUID")}


def fresh_guid(used):
    while True:
        guid = "".join(random.choice("0123456789abcdef") for _ in range(6))
        if guid not in used:
            used.add(guid)
            return guid


def strip_creator_credit(name):
    """Remove any recognized trailing ' - <Creator>' credit (reuses validator logic)."""
    return V.map_logical_name(name)


def normalize_card(card, template, creator_tag, type_tag, used_guids):
    """Mutate one card object in place. Return (changes:list[str]) or raise ValueError."""
    guid = card.get("GUID") or "??????"
    changes = []
    lua = card.get("LuaScript", "") or ""
    if OBJECTJSONS_MARKER not in lua:
        raise ValueError(f"card {guid} has no '{OBJECTJSONS_MARKER}' terrain blob to keep")

    blob = lua[lua.index(OBJECTJSONS_MARKER):]
    new_lua = template + blob
    if new_lua != lua:
        changes.append("machinery -> canonical head")
    card["LuaScript"] = new_lua

    if card.get("GMNotes"):
        changes.append(f'GMNotes {card.get("GMNotes")!r} -> ""')
    card["GMNotes"] = ""

    display = V.MAP_CREATOR_DISPLAY_NAMES[creator_tag]
    want_tags = [V.REQUIRED_MAP_TAG, creator_tag, type_tag]
    if list(card.get("Tags") or []) != want_tags:
        changes.append(f"Tags -> {want_tags}")
    card["Tags"] = want_tags

    logical = strip_creator_credit(card.get("Nickname") or "")
    new_name = f"{logical} - {display}"
    if new_name != (card.get("Nickname") or ""):
        changes.append(f"Nickname -> {new_name!r}")
    card["Nickname"] = new_name

    if not V._GUID_RE.fullmatch(guid):
        new_guid = fresh_guid(used_guids)
        changes.append(f"GUID {guid} -> {new_guid} (non-hex)")
        card["GUID"] = new_guid

    return changes


def resolve_cards(save, container, card_guids):
    """Return [(card_obj, deck_guid, deck_name)] for the requested cards."""
    by_guid = {}
    deck_of = {}
    for o in walk(save["ObjectStates"]):
        g = o.get("GUID")
        if g:
            by_guid[g] = o
        if o.get("Name") in V.MAP_SOURCE_CONTAINER_NAMES:
            for child in o.get("ContainedObjects", []) or []:
                if child.get("GUID"):
                    deck_of[child["GUID"]] = (o.get("GUID"),
                                              o.get("Nickname") or o.get("Name") or "")
    result = []
    if container:
        bag = by_guid.get(container)
        if not bag:
            sys.exit(term.red(f"ERROR: container {container} not found in save."))
        for child in bag.get("ContainedObjects", []) or []:
            result.append((child, container, bag.get("Nickname") or bag.get("Name") or ""))
    for g in card_guids:
        card = by_guid.get(g)
        if not card:
            sys.exit(term.red(f"ERROR: card {g} not found in save."))
        deck_guid, deck_name = deck_of.get(g, (None, ""))
        result.append((card, deck_guid, deck_name))
    return result


def main():
    p = argparse.ArgumentParser(description="Normalize foreign map cards to the canonical machinery.")
    p.add_argument("source", help="Save JSON to read/normalize cards in.")
    p.add_argument("--container", help="Bag/Deck GUID; normalize every card inside it.")
    p.add_argument("--cards", help="Comma-separated card GUIDs to normalize.")
    p.add_argument("--creator", required=True, help="Creator tag, e.g. map_crt_example.")
    p.add_argument("--type", required=True, dest="type_tag", help="Map type tag, e.g. map_type_comp.")
    p.add_argument("--out", help="Write the modified save to this path.")
    p.add_argument("--write", action="store_true", help="Write back to the source file in place.")
    args = p.parse_args()

    if args.creator not in V.MAP_CREATOR_DISPLAY_NAMES:
        sys.exit(term.red(f"ERROR: unknown creator tag {args.creator!r}. Known: "
                          f"{', '.join(sorted(V.MAP_CREATOR_DISPLAY_NAMES))}. "
                          "Add it to validate_maps.MAP_CREATOR_DISPLAY_NAMES and "
                          "startMenu mapCreatorDisplaySuffixes first."))
    if not args.type_tag.startswith(V.MAP_TYPE_TAG_PREFIX + "_"):
        sys.exit(term.red(f"ERROR: type tag must start with {V.MAP_TYPE_TAG_PREFIX}_."))
    if not args.container and not args.cards:
        sys.exit(term.red("ERROR: pass --container or --cards."))

    template = V._read_machinery_template()
    if template is None:
        sys.exit(term.red(f"ERROR: canonical template missing: {V.MAP_CARD_MACHINERY}"))

    src = Path(args.source)
    save = json.loads(src.read_text(encoding="utf-8"))
    used = all_guids(save)
    card_guids = [g.strip() for g in (args.cards or "").split(",") if g.strip()]
    targets = resolve_cards(save, args.container, card_guids)

    print(term.bold(f"Normalizing {len(targets)} card(s) in {src.name} "
                    f"as {args.creator} / {args.type_tag}"))
    manifest_rows = []
    for card, deck_guid, deck_name in targets:
        try:
            changes = normalize_card(card, template, args.creator, args.type_tag, used)
        except ValueError as exc:
            print(term.red(f"  SKIP {exc}"))
            continue
        guid, name = card["GUID"], card["Nickname"]
        print(term.green(f"  {guid}  {name}"))
        for c in changes:
            print(term.dim(f"      - {c}"))
        manifest_rows.append((deck_guid or "??????", deck_name, guid, name,
                              args.creator, args.type_tag))

    # The manifest + wiring are the human-facing output: paste these, then the
    # strict validator confirms every system is wired.
    print(term.bold("\nmap_manifest.csv rows:"))
    for r in manifest_rows:
        print("  " + ",".join(r))

    print(term.bold("\nstartMenu.ttslua wiring checklist (validate --require-map-tags enforces all):"))
    print(term.dim("  1. deploymentMatrixDecks  -> add the bag under its matchup key(s) \"R_B\""))
    print(term.dim("  2. randomDeploymentDecks  -> add the bag (return-to-bag / source resolution)"))
    print(term.dim("  3. GAME_MODE_OBJECTS      -> add the bag (+ any art tile) so it hides pre-game"))
    print(term.dim("                               and is restored by BACK TO SELECTION"))
    print(term.dim("  4. layout art deck fb4b5d -> ensure a card named like each map's logical name"))

    out = Path(args.out) if args.out else (src if args.write else None)
    if not out:
        print(term.yellow("\n[preview] no --out/--write given; nothing written."))
        return 0
    text = json.dumps(save, indent=2, ensure_ascii=False) + "\n"
    json.loads(text)  # never write unparseable JSON
    out.write_text(text, encoding="utf-8")
    print(term.green(f"\n✓ Wrote {out}."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
