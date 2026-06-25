#!/usr/bin/env python3
"""Import the Alvaricus "thematic" map cards from a TTS save into the LCT base.

The Alvaricus batch ships as 45 cards spread across three delivery bags that are
organized BY DEPLOYMENT (e.g. "Search and Destroy + Crucible of Battle"):

    1a7f23  Search and Destroy + Crucible of Battle   (15 cards)
    f95f25  Tipping point + Hammer and Anvil           (15 cards)
    4dcebf  Sweeping engagement + Dawn of War          (15 cards)

LCT instead organizes maps BY MATCHUP: one source bag per disposition pairing,
each holding the three logical layout slots (1/2/3) with one card per creator
variant. So this importer does not keep the three delivery bags. For every card
it parses the matchup (two dispositions) + deployment from the nickname, looks up
the existing (matchup, slot) in data/map_manifest.csv -- which fixes the slot
number, the canonical logical name, and the destination matchup bag -- and emits
a normalized static LCT map card into that existing bag. Because the cards reuse
existing logical names they share the existing layout art (deck fb4b5d) and the
matchup bags are already wired into deploymentMatrixDecks / randomDeploymentDecks
/ GAME_MODE_OBJECTS, so no new startMenu wiring is required.

Each emitted card:
  * LuaScript head  -> data/map_card_machinery.lua (canonical, already Map Zones v2),
                       keeping the card's own `objectJSONs = {...}` terrain blob.
  * GMNotes         -> "".
  * Tags            -> [map, map_crt_alvaricus, map_type_thematic].
  * Nickname        -> "<existing logical name> - Alvaricus".
  * GUID / CardID   -> fresh, stable, collision-free against the target.
  * Face art        -> preserved from the source card (deck id remapped).

    # preview the 45 cards without writing:
    python3 import_alvaricus_thematic_maps.py ../Legacy/TS_Save_122.json

    # write them into ftc_base.json + map_manifest.csv:
    python3 import_alvaricus_thematic_maps.py ../Legacy/TS_Save_122.json --write

Re-running is idempotent: a previous Alvaricus import (cards tagged
map_crt_alvaricus + matching manifest rows) is removed first.
"""

import argparse
import copy
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ROOT = SCRIPT_DIR.parent
DEFAULT_TARGET = ROOT / "TTSJSON" / "ftc_base.json"
DEFAULT_MANIFEST = ROOT / "data" / "map_manifest.csv"
MACHINERY = ROOT / "data" / "map_card_machinery.lua"

DELIVERY_BAGS = ("1a7f23", "f95f25", "4dcebf")
CREATOR_TAG = "map_crt_alvaricus"
CREATOR_DISPLAY = "Alvaricus"
TYPE_TAG = "map_type_thematic"
REQUIRED_MAP_TAG = "map"
OBJECTJSONS_MARKER = "objectJSONs = {"
DEFAULT_BACK_URL = "https://steamusercontent-a.akamaihd.net/ugc/10791071673581242/E710A69735A01208EFCAE0A13B7FD487275388FB/"

# Messy source abbreviations -> canonical disposition names.
DISP = {
    "d": "Disruption", "dis": "Disruption",
    "pa": "Priority Assets",
    "ptf": "Purge the Foe",
    "r": "Reconnaissance", "rec": "Reconnaissance", "recon": "Reconnaissance",
    "tah": "Take and Hold", "tdh": "Take and Hold", "tnh": "Take and Hold",
}
# Case-insensitive deployment name -> canonical form (matches existing logical names).
DEPLOYMENT = {
    "crucible of battle": "Crucible of Battle",
    "search and destroy": "Search and Destroy",
    "tipping point": "Tipping Point",
    "hammer and anvil": "Hammer and Anvil",
    "sweeping engagement": "Sweeping Engagement",
    "dawn of war": "Dawn of War",
}


def walk(objs):
    for obj in objs or []:
        yield obj
        yield from walk(obj.get("ContainedObjects") or [])
        states = obj.get("States") or {}
        if isinstance(states, dict):
            yield from walk(list(states.values()))


def all_guids(root):
    return {o.get("GUID") for o in walk(root.get("ObjectStates") or []) if o.get("GUID")}


def stable_guid(seed, used):
    counter = 0
    while True:
        digest = hashlib.sha1(f"{seed}|{counter}".encode("utf-8")).hexdigest()[:6]
        if digest not in used:
            used.add(digest)
            return digest
        counter += 1


def stable_deck_id(seed, used):
    counter = 0
    while True:
        value = 1000 + (int(hashlib.sha1(f"{seed}|{counter}".encode("utf-8")).hexdigest()[:8], 16) % 8000)
        key = str(value)
        if key not in used:
            used.add(key)
            return value
        counter += 1


def load_manifest(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_manifest(path, rows):
    fieldnames = ["deck_guid", "deck_name", "card_guid", "card_name", "map_creator_tag", "map_type_tag", "creator_display", "eligible"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def strip_creator_credit(name, display):
    name = (name or "").rstrip()
    suffix = f" - {display}"
    if name.casefold().endswith(suffix.casefold()):
        return name[:-len(suffix)].rstrip()
    return name


def existing_slots_index(manifest_rows):
    """(frozenset(disp_a, disp_b), deployment) -> (deck_guid, deck_name, slot, logical_name)."""
    index = {}
    for row in manifest_rows:
        logical = strip_creator_credit(row["card_name"], row["creator_display"])
        m = re.match(r"^(.*?)\s+vs\s+(.*?)\s+(\d+)\s+-\s+(.*)$", logical)
        if not m:
            continue
        a, b, slot, deployment = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        key = (frozenset([DISP[a.lower()], DISP[b.lower()]]), deployment)
        index.setdefault(key, (row["deck_guid"], row["deck_name"], slot, logical))
    return index


def parse_source_card(nickname):
    """Return (frozenset(disp_a, disp_b), deployment) parsed from a delivery nickname."""
    m = re.match(r"^(\S+)\s+vs\s+(\S+)\s+(.*)$", nickname.strip(), flags=re.I)
    if not m:
        raise ValueError(f"cannot parse matchup/deployment from {nickname!r}")
    a, b, deployment = m.group(1), m.group(2), m.group(3).strip()
    if a.lower() not in DISP or b.lower() not in DISP:
        raise ValueError(f"unknown disposition abbreviation in {nickname!r}")
    if deployment.lower() not in DEPLOYMENT:
        raise ValueError(f"unknown deployment {deployment!r} in {nickname!r}")
    return frozenset([DISP[a.lower()], DISP[b.lower()]]), DEPLOYMENT[deployment.lower()]


def remap_custom_deck(card, deck_id):
    """Preserve the source card's face art but move it onto a fresh deck id."""
    old = card.get("CustomDeck") or {}
    entry = next(iter(old.values()), {}) if old else {}
    card["CustomDeck"] = {
        str(deck_id): {
            "FaceURL": entry.get("FaceURL") or DEFAULT_BACK_URL,
            "BackURL": entry.get("BackURL") or DEFAULT_BACK_URL,
            "NumWidth": entry.get("NumWidth", 1),
            "NumHeight": entry.get("NumHeight", 1),
            "BackIsHidden": entry.get("BackIsHidden", True),
            "UniqueBack": entry.get("UniqueBack", False),
            "Type": entry.get("Type", 1),
        }
    }
    card["CardID"] = deck_id * 100


def terrain_entry_count(lua):
    """Number of baked terrain pieces in a card's objectJSONs blob."""
    if OBJECTJSONS_MARKER not in lua:
        return 0
    blob = lua[lua.index(OBJECTJSONS_MARKER):]
    return len(re.findall(r"\[\[(.*?)\]\]", blob, re.DOTALL))


def build_card(source_card, logical, machinery, guid, deck_id):
    card = copy.deepcopy(source_card)
    lua = source_card.get("LuaScript", "") or ""
    if OBJECTJSONS_MARKER not in lua:
        raise ValueError(f"source card {source_card.get('GUID')} has no terrain blob")
    blob = lua[lua.index(OBJECTJSONS_MARKER):]
    card["GUID"] = guid
    card["Nickname"] = f"{logical} - {CREATOR_DISPLAY}"
    card["Description"] = "Alvaricus imported thematic LCT map card."
    card["GMNotes"] = ""
    card["Tags"] = [REQUIRED_MAP_TAG, CREATOR_TAG, TYPE_TAG]
    card["LuaScript"] = machinery + blob
    card["LuaScriptState"] = ""
    card["XmlUI"] = ""
    card["Locked"] = False
    tr = card.get("Transform") or {}
    tr.update({"posX": 0, "posY": 1, "posZ": 0, "rotX": 0, "rotY": 180, "rotZ": 0,
               "scaleX": 1.5, "scaleY": 1, "scaleZ": 1.5})
    card["Transform"] = tr
    remap_custom_deck(card, deck_id)
    return card


def remove_previous_import(target, names=None):
    """Drop previously imported Alvaricus cards. If `names` is given, only cards
    whose Nickname is in that set are removed (used by the targeted --cards mode so
    a partial add never disturbs the other slots); otherwise every Alvaricus card
    is removed (full re-import)."""
    removed = 0
    for obj in walk(target.get("ObjectStates") or []):
        children = obj.get("ContainedObjects")
        if not isinstance(children, list):
            continue
        kept = [c for c in children
                if CREATOR_TAG not in (c.get("Tags") or [])
                or (names is not None and (c.get("Nickname") or "") not in names)]
        removed += len(children) - len(kept)
        obj["ContainedObjects"] = kept
    return removed


def validation_command_hint():
    if Path.cwd().resolve() == SCRIPT_DIR.resolve():
        return "python3 validate_maps.py --require-map-tags && python3 compile.py --test"
    return "python3 scripts/validate_maps.py --require-map-tags && python3 scripts/compile.py --test"


def main():
    ap = argparse.ArgumentParser(description="Import Alvaricus thematic maps into the LCT base.")
    ap.add_argument("source_save", help="TTS save JSON containing the three Alvaricus delivery bags.")
    ap.add_argument("--target", default=str(DEFAULT_TARGET), help="ftc_base.json to modify.")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="map_manifest.csv to update.")
    ap.add_argument("--write", action="store_true", help="Write changes. Without this, only preview.")
    ap.add_argument("--bags", help="Comma-separated delivery-bag GUIDs to read (default: the "
                                    "known three). Use when a re-export gives the bags new GUIDs.")
    ap.add_argument("--cards", help="Comma-separated source card GUIDs to import individually. "
                                    "Only the matching matchup slots are replaced; the rest of the "
                                    "existing Alvaricus import is left untouched (targeted top-up).")
    args = ap.parse_args()

    source = json.loads(Path(args.source_save).read_text(encoding="utf-8"))
    target_path = Path(args.target)
    manifest_path = Path(args.manifest)
    target = json.loads(target_path.read_text(encoding="utf-8"))
    machinery = MACHINERY.read_text(encoding="utf-8")
    manifest_rows = load_manifest(manifest_path)
    slots = existing_slots_index(manifest_rows)

    src_by_guid = {o.get("GUID"): o for o in walk(source.get("ObjectStates") or [])}
    partial = bool(args.cards)
    source_cards = []
    if partial:
        for g in (c.strip() for c in args.cards.split(",") if c.strip()):
            card = src_by_guid.get(g)
            if not card:
                sys.exit(f"ERROR: card {g} not found in {args.source_save}.")
            source_cards.append(card)
    else:
        bag_guids = [b.strip() for b in args.bags.split(",")] if args.bags else list(DELIVERY_BAGS)
        for bag_guid in bag_guids:
            bag = src_by_guid.get(bag_guid)
            if not bag:
                sys.exit(f"ERROR: delivery bag {bag_guid} not found in {args.source_save}.")
            source_cards.extend(bag.get("ContainedObjects") or [])
        if len(source_cards) != 45:
            print(f"WARNING: expected 45 source cards, found {len(source_cards)}.")

    # Pass 1: resolve each source card to its target slot/name (no GUIDs yet) so we
    # know exactly which Alvaricus cards this run replaces.
    plan = []
    skipped_empty = []
    for src in source_cards:
        nick = src.get("Nickname") or ""
        try:
            key = parse_source_card(nick)
        except ValueError as exc:
            sys.exit(f"ERROR: {exc}")
        if key not in slots:
            sys.exit(f"ERROR: no existing matchup slot for {nick!r} "
                     f"({sorted(key[0])} / {key[1]}); cannot place.")
        deck_guid, deck_name, slot, logical = slots[key]
        target_name = f"{logical} - {CREATOR_DISPLAY}"
        # Some delivery cards ship unbaked (empty objectJSONs); importing them would
        # produce a map whose "Load Map" spawns nothing. Skip + report them so the
        # build stays valid; a re-run picks them up once their terrain is baked.
        if terrain_entry_count(src.get("LuaScript", "") or "") == 0:
            skipped_empty.append((src.get("GUID"), nick, target_name))
            continue
        plan.append((src, deck_guid, deck_name, slot, logical, target_name))

    replaced_names = {p[5] for p in plan} if partial else None

    # GUIDs/deck-ids are assigned against the target with exactly the cards this run
    # replaces removed, so a re-run reproduces identical ids (stable + idempotent)
    # while a targeted --cards run never reuses a surviving card's GUID.
    pre = json.loads(target_path.read_text(encoding="utf-8"))
    remove_previous_import(pre, replaced_names)
    used_guids = all_guids(pre)
    used_deck_ids = set()
    for obj in walk(pre.get("ObjectStates") or []):
        for key in (obj.get("CustomDeck") or {}).keys():
            used_deck_ids.add(str(key))

    new_cards = []
    manifest_additions = []
    for src, deck_guid, deck_name, slot, logical, target_name in plan:
        seed = f"{CREATOR_TAG}|{deck_guid}|{slot}"
        guid = stable_guid("card|" + seed, used_guids)
        deck_id = stable_deck_id("deck|" + seed, used_deck_ids)
        card = build_card(src, logical, machinery, guid, deck_id)
        new_cards.append((deck_guid, card))
        manifest_additions.append({
            "deck_guid": deck_guid,
            "deck_name": deck_name,
            "card_guid": guid,
            "card_name": target_name,
            "map_creator_tag": CREATOR_TAG,
            "map_type_tag": TYPE_TAG,
            "creator_display": CREATOR_DISPLAY,
            "eligible": "true",
        })

    bags_touched = sorted({g for g, _ in new_cards})
    print(f"Prepared {len(new_cards)} Alvaricus thematic map cards into {len(bags_touched)} matchup bag(s).")
    for row in sorted(manifest_additions, key=lambda r: r["card_name"]):
        print(f"  {row['deck_guid']}  {row['card_guid']}  {row['card_name']}")
    if skipped_empty:
        print(f"\nSKIPPED {len(skipped_empty)} unbaked (empty-terrain) source card(s) — "
              "bake their terrain in TTS, re-save, and re-run to import:")
        for guid, nick, target_name in sorted(skipped_empty, key=lambda x: x[2]):
            print(f"  source {guid}  {nick!r}  -> would be {target_name!r}")

    if not args.write:
        print("\n[preview] no files written; pass --write to update ftc_base.json and map_manifest.csv.")
        return 0

    removed = remove_previous_import(target, replaced_names)
    target_by_guid = {o.get("GUID"): o for o in walk(target.get("ObjectStates") or []) if o.get("GUID")}
    for deck_guid, card in new_cards:
        bag = target_by_guid.get(deck_guid)
        if not bag:
            sys.exit(f"ERROR: target matchup bag {deck_guid} not found in {target_path}.")
        bag.setdefault("ContainedObjects", []).append(card)

    if partial:
        manifest_rows = [r for r in manifest_rows
                         if not (r.get("map_creator_tag") == CREATOR_TAG
                                 and r.get("card_name") in replaced_names)]
    else:
        manifest_rows = [r for r in manifest_rows if r.get("map_creator_tag") != CREATOR_TAG]
    manifest_rows.extend(manifest_additions)

    target_path.write_text(json.dumps(target, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_manifest(manifest_path, manifest_rows)
    print(f"\nWrote {target_path} and {manifest_path}; removed {removed} previous Alvaricus card(s).")
    print(f"Run: {validation_command_hint()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
