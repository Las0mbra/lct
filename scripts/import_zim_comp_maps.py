#!/usr/bin/env python3
"""Import Zim competitive map cards from single-card TTS JSON files.

The Zim batch is delivered as individual saved-object JSON files named/nicknamed
like "Dis vs PA 2 - Tipping Point". LCT stores maps in existing matchup source
bags, one bag per disposition pair, and uses data/map_manifest.csv as the source
of truth for each logical slot. This importer maps each source nickname onto the
existing canonical logical name, emits a static LCT map card tagged
map_crt_zim/map_type_comp, and places it into that matchup bag.

If no file paths are supplied, the importer scans ~/Downloads for *vs PA*.json.
Re-running is idempotent: all previous Zim cards/manifest rows are removed first.
"""

import argparse
import copy
import csv
import glob
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import map_payloads as P

SCRIPT_DIR = Path(__file__).parent
ROOT = SCRIPT_DIR.parent
DEFAULT_TARGET = ROOT / "TTSJSON" / "ftc_base.json"
DEFAULT_MANIFEST = ROOT / "data" / "map_manifest.csv"
MACHINERY = ROOT / "data" / "map_card_machinery.lua"

CREATOR_TAG = "map_crt_zim"
CREATOR_DISPLAY = "Zim"
TYPE_TAG = "map_type_comp"
REQUIRED_MAP_TAG = "map"
OBJECTJSONS_MARKER = "objectJSONs = {"
DEFAULT_BACK_URL = "https://steamusercontent-a.akamaihd.net/ugc/10791071673581242/E710A69735A01208EFCAE0A13B7FD487275388FB/"

DISP = {
    "d": "Disruption", "dis": "Disruption",
    "pa": "Priority Assets",
    "ptf": "Purge the Foe",
    "r": "Reconnaissance", "rec": "Reconnaissance", "recon": "Reconnaissance",
    "tah": "Take and Hold", "tdh": "Take and Hold", "tnh": "Take and Hold",
}
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
    if display and name.casefold().endswith(suffix.casefold()):
        return name[:-len(suffix)].rstrip()
    return name


def existing_slots_index(manifest_rows):
    """(frozenset(disp_a, disp_b), deployment) -> target slot metadata."""
    index = {}
    for row in manifest_rows:
        logical = strip_creator_credit(row["card_name"], row["creator_display"])
        m = re.match(r"^(.*?)\s+vs\s+(.*?)\s+(\d+)\s+-\s+(.*)$", logical)
        if not m:
            continue
        a, b, slot, deployment = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        try:
            key = (frozenset([DISP[a.lower()], DISP[b.lower()]]), deployment)
        except KeyError:
            continue
        index.setdefault(key, {
            "deck_guid": row["deck_guid"],
            "deck_name": row["deck_name"],
            "slot": slot,
            "logical": logical,
        })
    return index


def parse_source_card_name(nickname):
    m = re.match(r"^(\S+)\s+vs\s+(\S+)\s+(\d+)\s+-\s+(.*)$", nickname.strip(), flags=re.I)
    if not m:
        raise ValueError(f"cannot parse matchup/deployment from {nickname!r}")
    a, b, _slot, deployment = m.group(1), m.group(2), int(m.group(3)), m.group(4).strip()
    if a.lower() not in DISP or b.lower() not in DISP:
        raise ValueError(f"unknown disposition abbreviation in {nickname!r}")
    if deployment.lower() not in DEPLOYMENT:
        raise ValueError(f"unknown deployment {deployment!r} in {nickname!r}")
    return frozenset([DISP[a.lower()], DISP[b.lower()]]), DEPLOYMENT[deployment.lower()]


def source_card_from_file(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    candidates = list(walk(data.get("ObjectStates") or []))
    cards = [c for c in candidates if c.get("LuaScript") and OBJECTJSONS_MARKER in c.get("LuaScript", "")]
    if not cards:
        raise ValueError(f"{path}: no card with an objectJSONs terrain blob found")
    if len(cards) > 1:
        # Saved-object exports should contain one map card; fail loudly if a full
        # save was passed by accident so we do not import an arbitrary card.
        raise ValueError(f"{path}: expected 1 map card, found {len(cards)}")
    return cards[0]


def remap_custom_deck(card, deck_id):
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
    if OBJECTJSONS_MARKER not in lua:
        return 0
    blob = lua[lua.index(OBJECTJSONS_MARKER):]
    return len(re.findall(r"\[\[(.*?)\]\]", blob, re.DOTALL))


def terrain_blob_hash(lua):
    blob = lua[lua.index(OBJECTJSONS_MARKER):] if OBJECTJSONS_MARKER in lua else lua
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def build_card(source_card, logical, machinery, guid, deck_id):
    card = copy.deepcopy(source_card)
    lua = source_card.get("LuaScript", "") or ""
    if OBJECTJSONS_MARKER not in lua:
        raise ValueError(f"source card {source_card.get('GUID')} has no terrain blob")
    blob = lua[lua.index(OBJECTJSONS_MARKER):]
    card["GUID"] = guid
    card["Nickname"] = f"{logical} - {CREATOR_DISPLAY}"
    card["Description"] = "Zim imported competitive LCT map card."
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


def remove_previous_import(target):
    removed = []
    for obj in walk(target.get("ObjectStates") or []):
        children = obj.get("ContainedObjects")
        if not isinstance(children, list):
            continue
        kept = []
        for child in children:
            if CREATOR_TAG in (child.get("Tags") or []):
                removed.append(child.get("GUID"))
            else:
                kept.append(child)
        obj["ContainedObjects"] = kept
    return removed


def validation_command_hint():
    if Path.cwd().resolve() == SCRIPT_DIR.resolve():
        return "python3 validate_maps.py --require-map-tags && python3 compile.py --test"
    return "python3 scripts/validate_maps.py --require-map-tags && python3 scripts/compile.py --test"


def default_source_files(source_dir):
    pattern = str(Path(source_dir).expanduser() / "*vs PA*.json")
    return [Path(p) for p in sorted(glob.glob(pattern))]


def main():
    ap = argparse.ArgumentParser(description="Import Zim competitive map cards into the LCT base.")
    ap.add_argument("source_files", nargs="*", help="Single-card TTS JSON files. Defaults to ~/Downloads/*vs PA*.json.")
    ap.add_argument("--source-dir", default="~/Downloads", help="Directory scanned when no source files are provided.")
    ap.add_argument("--target", default=str(DEFAULT_TARGET), help="ftc_base.json to modify.")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="map_manifest.csv to update.")
    ap.add_argument("--write", action="store_true", help="Write changes. Without this, only preview.")
    args = ap.parse_args()

    source_paths = [Path(p).expanduser() for p in args.source_files] if args.source_files else default_source_files(args.source_dir)
    if not source_paths:
        sys.exit("ERROR: no source files found.")

    target_path = Path(args.target)
    manifest_path = Path(args.manifest)
    target = json.loads(target_path.read_text(encoding="utf-8"))
    machinery = MACHINERY.read_text(encoding="utf-8")
    manifest_rows = load_manifest(manifest_path)
    slots = existing_slots_index(manifest_rows)

    loaded = []
    seen_source = set()
    for path in source_paths:
        try:
            card = source_card_from_file(path)
            key = parse_source_card_name(card.get("Nickname") or path.stem)
        except ValueError as exc:
            sys.exit(f"ERROR: {exc}")
        if key not in slots:
            sys.exit(f"ERROR: no existing matchup slot for {card.get('Nickname')!r}; cannot place.")
        lua = card.get("LuaScript", "") or ""
        count = terrain_entry_count(lua)
        if count == 0:
            sys.exit(f"ERROR: source card {path} has no baked terrain entries.")
        source_id = f"{card.get('GUID')}|{terrain_blob_hash(lua)}"
        if source_id in seen_source:
            print(f"WARNING: duplicate source payload skipped: {path}")
            continue
        seen_source.add(source_id)
        loaded.append((path, card, key, count, source_id))

    if len(loaded) != 12:
        print(f"WARNING: expected 12 source cards, found {len(loaded)}.")

    pre = json.loads(target_path.read_text(encoding="utf-8"))
    remove_previous_import(pre)
    used_guids = all_guids(pre)
    used_deck_ids = set()
    for obj in walk(pre.get("ObjectStates") or []):
        for key in (obj.get("CustomDeck") or {}).keys():
            used_deck_ids.add(str(key))

    new_cards = []
    manifest_additions = []
    for path, source_card, key, count, source_id in loaded:
        slot = slots[key]
        logical = slot["logical"]
        seed = f"{CREATOR_TAG}|{source_id}|{logical}"
        guid = stable_guid("card|" + seed, used_guids)
        deck_id = stable_deck_id("deck|" + seed, used_deck_ids)
        card = build_card(source_card, logical, machinery, guid, deck_id)
        new_cards.append((slot["deck_guid"], card, path, count))
        manifest_additions.append({
            "deck_guid": slot["deck_guid"],
            "deck_name": slot["deck_name"],
            "card_guid": guid,
            "card_name": f"{logical} - {CREATOR_DISPLAY}",
            "map_creator_tag": CREATOR_TAG,
            "map_type_tag": TYPE_TAG,
            "creator_display": CREATOR_DISPLAY,
            "eligible": "true",
        })

    bags_touched = sorted({deck_guid for deck_guid, _card, _path, _count in new_cards})
    print(f"Prepared {len(new_cards)} Zim competitive map cards into {len(bags_touched)} matchup bag(s).")
    for row, (_deck_guid, _card, path, count) in sorted(zip(manifest_additions, new_cards), key=lambda item: (item[0]["card_name"], item[1][2].name)):
        print(f"  {row['deck_guid']}  {row['card_guid']}  {row['card_name']}  terrain={count}  source={path.name}")

    if not args.write:
        print("\n[preview] no files written; pass --write to update ftc_base.json and map_manifest.csv.")
        return 0

    removed_guids = remove_previous_import(target)
    target_by_guid = {o.get("GUID"): o for o in walk(target.get("ObjectStates") or []) if o.get("GUID")}
    new_guids = {card.get("GUID") for _deck_guid, card, _path, _count in new_cards}
    for deck_guid, card, _path, _count in new_cards:
        bag = target_by_guid.get(deck_guid)
        if not bag:
            sys.exit(f"ERROR: target matchup bag {deck_guid} not found in {target_path}.")
        P.strip_card_to_payload(card)
        bag.setdefault("ContainedObjects", []).append(card)
    for guid in removed_guids:
        if guid and guid not in new_guids:
            P.remove_payload(guid)

    manifest_rows = [r for r in manifest_rows if r.get("map_creator_tag") != CREATOR_TAG]
    manifest_rows.extend(manifest_additions)

    target_path.write_text(json.dumps(target, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_manifest(manifest_path, manifest_rows)
    print(f"\nWrote {target_path}, {manifest_path}, and data/maps payloads; "
          f"removed {len(removed_guids)} previous Zim card(s).")
    print(f"Run: {validation_command_hint()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
