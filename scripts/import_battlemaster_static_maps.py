#!/usr/bin/env python3
"""Import prebuilt Battlemaster cache entries as normal LCT map cards.

Workflow:
  1. Build/load a debug table and click "BM cache populate". The spawner stores
     fetched API payloads plus prebuilt card scripts in its LuaScriptState.
  2. Save that table.
  3. Run this script with the saved JSON. It copies the terrain blobs into
     canonical LCT map cards, places them in the existing matchup source bags,
     and appends map_manifest rows.

The imported cards are static map cards. The Battlemaster provider hook is
intentionally stripped; compile.py will inject the normal map-card load hook.
"""

import argparse
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
SPAWNER_GUID = "b4d10a"
OBJECTJSONS_MARKER = "objectJSONs = {"
DEFAULT_CREATOR_TAG = "map_crt_battlemaster"
DEFAULT_CREATOR_DISPLAY = "Battlemaster"
CREATOR_TAG = DEFAULT_CREATOR_TAG
CREATOR_DISPLAY = DEFAULT_CREATOR_DISPLAY
TYPE_TAG = "map_type_comp"
OLD_CREATOR_TAGS = {"map_crt_battlemaster_default", CREATOR_TAG}
DEFAULT_BACK_URL = "https://steamusercontent-a.akamaihd.net/ugc/10791071673581242/E710A69735A01208EFCAE0A13B7FD487275388FB/"
DEFAULT_FACE_URL = DEFAULT_BACK_URL

ARCHETYPE_DISPLAY = {
    "take-and-hold": "Take and Hold",
    "priority-assets": "Priority Assets",
    "purge-the-foe": "Purge the Foe",
    "reconnaissance": "Reconnaissance",
    "disruption": "Disruption",
}
ARCHETYPE_ABBREV = {
    "take-and-hold": "TnH",
    "priority-assets": "PA",
    "purge-the-foe": "PtF",
    "reconnaissance": "Rec",
    "disruption": "Dis",
}
DEPLOYMENT_NAMES = {
    1: "Search and Destroy",
    2: "Dawn of War",
    3: "Hammer and Anvil",
    4: "Crucible of Battle",
    5: "Sweeping Engagement",
    6: "Tipping Point",
}


def walk(objs):
    for obj in objs or []:
        yield obj
        yield from walk(obj.get("ContainedObjects") or [])
        states = obj.get("States") or {}
        if isinstance(states, dict):
            yield from walk(states.values())


def find_object(root, guid):
    for obj in walk(root.get("ObjectStates") or []):
        if obj.get("GUID") == guid:
            return obj
    return None


def all_guids(root):
    return {obj.get("GUID") for obj in walk(root.get("ObjectStates") or []) if obj.get("GUID")}


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


def pair_key_from_deck_name(deck_name):
    left, right = deck_name.split(" vs ", 1)
    reverse = {v: k for k, v in ARCHETYPE_DISPLAY.items()}
    return "|".join(sorted([reverse[left], reverse[right]]))


def load_manifest(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_manifest(path, rows):
    fieldnames = ["deck_guid", "deck_name", "card_guid", "card_name", "map_creator_tag", "map_type_tag", "creator_display", "eligible"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def validation_command_hint():
    if Path.cwd().resolve() == SCRIPT_DIR.resolve():
        return "python3 validate_maps.py --require-map-tags && python3 compile.py --test"
    return "python3 scripts/validate_maps.py --require-map-tags && python3 scripts/compile.py --test"


def source_bags_by_pair(manifest_rows):
    by_pair = {}
    for row in manifest_rows:
        pair = pair_key_from_deck_name(row["deck_name"])
        by_pair.setdefault(pair, {"deck_guid": row["deck_guid"], "deck_name": row["deck_name"]})
    return by_pair


def strip_manifest_creator_credit(row):
    name = (row.get("card_name") or "").rstrip()
    display = row.get("creator_display") or ""
    suffix = f" - {display}"
    if display and name.casefold().endswith(suffix.casefold()):
        return name[:-len(suffix)].rstrip()
    return name


def manifest_logical_names_by_pair_slot(manifest_rows):
    names = {}
    for row in manifest_rows:
        pair = pair_key_from_deck_name(row["deck_name"])
        logical = strip_manifest_creator_credit(row)
        marker = " - "
        before_suffix = logical.split(marker, 1)[0]
        parts = before_suffix.rsplit(" ", 1)
        if len(parts) != 2:
            continue
        try:
            slot = int(parts[1])
        except ValueError:
            continue
        names.setdefault((pair, slot), logical)
    return names


def layout_payload_key(layout):
    slot = (layout.get("chapterApprovedSlot") or {}).get("slotIndex", layout.get("slotIndex"))
    pair = layout.get("forcePairKey") or ""
    key = layout.get("layoutKey") or ""
    if not key and layout.get("id") is not None:
        key = f"{layout['id']}@{layout.get('updatedAt', '')}"
    return f"{pair}|slot:{slot}|layout:{key}"


def objectjson_entries_from_cached_script(script):
    if OBJECTJSONS_MARKER not in script:
        raise ValueError("prebuilt script has no objectJSONs blob")
    table_text = script[script.index(OBJECTJSONS_MARKER) + len(OBJECTJSONS_MARKER):]

    # Native LCT cards use Lua long strings. The Battlemaster cache currently
    # stores each object as an escaped Lua/JSON string literal, so decode those
    # and re-emit the canonical shape that validate_maps.py and map-card tooling
    # understand. Keep a long-string fallback so the importer remains rerunnable
    # if the cache format is improved upstream later.
    long_entries = re.findall(r"\[\[(.*?)\]\]", table_text, re.DOTALL)
    if long_entries:
        return long_entries

    entries = []
    decoder = json.JSONDecoder()
    i = 0
    while i < len(table_text):
        if table_text[i] == '"':
            value, end = decoder.raw_decode(table_text, i)
            if not isinstance(value, str):
                raise ValueError("objectJSONs entry is not a string literal")
            json.loads(value)  # validate before baking into a card
            entries.append(value)
            i = end
        else:
            i += 1
    if not entries:
        raise ValueError("prebuilt script objectJSONs blob has no entries")
    return entries


def lua_long_string(value):
    if "]]" in value:
        raise ValueError("object JSON contains Lua long-string terminator ]]")
    return f"[[{value}]]"


def static_card_script(script, machinery):
    entries = objectjson_entries_from_cached_script(script)
    lines = [OBJECTJSONS_MARKER]
    for entry in entries:
        lines.append(f"  {lua_long_string(entry)},")
    lines.append("}")
    return machinery + "\n".join(lines) + "\n"


def card_custom_deck(face_url, back_url, deck_id, type_index):
    return {
        str(deck_id): {
            "FaceURL": face_url or DEFAULT_FACE_URL,
            "BackURL": back_url or DEFAULT_BACK_URL,
            "NumWidth": 1,
            "NumHeight": 1,
            "BackIsHidden": True,
            "UniqueBack": False,
            "Type": type_index,
        }
    }


def make_static_map_card(guid, name, script, face_url, deck_id):
    return {
        "GUID": guid,
        "Name": "CardCustom",
        "Transform": {"posX": 0, "posY": 1, "posZ": 0, "rotX": 0, "rotY": 180, "rotZ": 0, "scaleX": 1.5, "scaleY": 1, "scaleZ": 1.5},
        "Nickname": name,
        "Description": "Battlemaster imported static LCT map card.",
        "GMNotes": "",
        "Tags": ["map", CREATOR_TAG, TYPE_TAG],
        "AltLookAngle": {"x": 0, "y": 0, "z": 0},
        "ColorDiffuse": {"r": 0.713235259, "g": 0.713235259, "b": 0.713235259},
        "LayoutGroupSortIndex": 0,
        "Value": 0,
        "Locked": False,
        "Grid": True,
        "Snap": True,
        "IgnoreFoW": False,
        "MeasureMovement": False,
        "DragSelectable": True,
        "Autoraise": True,
        "Sticky": True,
        "Tooltip": True,
        "GridProjection": False,
        "HideWhenFaceDown": True,
        "Hands": True,
        "CardID": deck_id * 100,
        "SidewaysCard": False,
        "CustomDeck": card_custom_deck(face_url, face_url or DEFAULT_BACK_URL, deck_id, 1),
        "LuaScript": script,
        "LuaScriptState": "",
        "XmlUI": "",
    }


def logical_name_for(layout, deck_name, manifest_logical_names):
    slot = int((layout.get("chapterApprovedSlot") or {}).get("slotIndex", layout.get("slotIndex")))
    pair = layout.get("forcePairKey") or pair_key_from_deck_name(deck_name)
    existing = manifest_logical_names.get((pair, slot))
    if existing:
        return existing

    key = int(layout.get("chapterApprovedDeploymentKey"))
    deployment = DEPLOYMENT_NAMES[key]
    left, right = deck_name.split(" vs ", 1)
    reverse = {v: k for k, v in ARCHETYPE_DISPLAY.items()}
    return f"{ARCHETYPE_ABBREV[reverse[left]]} vs {ARCHETYPE_ABBREV[reverse[right]]} {slot} - {deployment}"


def existing_layout_art_names(target):
    deck = find_object(target, "fb4b5d")
    if not deck:
        return set()
    return {str(c.get("Nickname") or "").strip().casefold() for c in deck.get("ContainedObjects") or []}


def remove_previous_import(target):
    removed = 0
    for obj in walk(target.get("ObjectStates") or []):
        children = obj.get("ContainedObjects")
        if not isinstance(children, list):
            continue
        kept = []
        for child in children:
            tags = child.get("Tags") or []
            if any(tag in OLD_CREATOR_TAGS for tag in tags):
                removed += 1
            else:
                kept.append(child)
        obj["ContainedObjects"] = kept
    return removed


def main():
    global CREATOR_TAG, CREATOR_DISPLAY, OLD_CREATOR_TAGS
    ap = argparse.ArgumentParser(description="Import Battlemaster cache as static LCT map cards.")
    ap.add_argument("source_save", help="TTS save/saved-object JSON whose spawner has a populated cardScriptCache.")
    ap.add_argument("--target", default=str(DEFAULT_TARGET), help="ftc_base.json to modify.")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="map_manifest.csv to update.")
    ap.add_argument("--write", action="store_true", help="Write changes. Without this, only preview.")
    ap.add_argument("--allow-missing-layout-art", action="store_true", help="Do not fail if existing layout art is missing.")
    ap.add_argument("--creator-tag", default=DEFAULT_CREATOR_TAG, help="map_crt* tag to add to imported cards and manifest rows.")
    ap.add_argument("--creator-display", default=DEFAULT_CREATOR_DISPLAY, help="Creator/filter label to append to imported card names.")
    args = ap.parse_args()

    CREATOR_TAG = args.creator_tag.strip()
    CREATOR_DISPLAY = args.creator_display.strip()
    if not CREATOR_TAG.startswith("map_crt") or not CREATOR_DISPLAY:
        sys.exit("ERROR: --creator-tag must start with map_crt and --creator-display must be non-empty.")
    OLD_CREATOR_TAGS = {CREATOR_TAG}
    if CREATOR_TAG == DEFAULT_CREATOR_TAG:
        OLD_CREATOR_TAGS.add("map_crt_battlemaster_default")

    source = json.loads(Path(args.source_save).read_text(encoding="utf-8"))
    target_path = Path(args.target)
    manifest_path = Path(args.manifest)
    target = json.loads(target_path.read_text(encoding="utf-8"))
    machinery = MACHINERY.read_text(encoding="utf-8")
    manifest_rows = load_manifest(manifest_path)
    source_bags = source_bags_by_pair(manifest_rows)
    manifest_logical_names = manifest_logical_names_by_pair_slot(manifest_rows)
    layout_art = existing_layout_art_names(target)

    spawner = find_object(source, SPAWNER_GUID)
    if not spawner:
        sys.exit(f"ERROR: Battlemaster spawner {SPAWNER_GUID} not found in {args.source_save}.")
    state_text = spawner.get("LuaScriptState") or ""
    if not state_text.strip():
        sys.exit("ERROR: spawner LuaScriptState is empty. Run BM cache populate in TTS, save, then rerun.")
    state = json.loads(state_text)
    layouts = (state.get("layoutCatalog") or {}).get("layouts") or []
    script_cache = state.get("cardScriptCache") or {}
    if not layouts:
        sys.exit("ERROR: no layoutCatalog.layouts in Battlemaster cache.")
    if not script_cache:
        sys.exit("ERROR: no cardScriptCache in Battlemaster cache. Re-run BM cache populate with the latest spawner, save, then rerun.")

    used_guids = all_guids(target)
    used_deck_ids = set()
    for obj in walk(target.get("ObjectStates") or []):
        for key in (obj.get("CustomDeck") or {}).keys():
            used_deck_ids.add(str(key))

    target_by_guid = {obj.get("GUID"): obj for obj in walk(target.get("ObjectStates") or []) if obj.get("GUID")}
    new_cards = []
    manifest_additions = []
    missing_art = []

    for layout in sorted(layouts, key=lambda l: (l.get("forcePairKey") or "", (l.get("chapterApprovedSlot") or {}).get("slotIndex", 0))):
        pair = layout.get("forcePairKey") or ""
        source_info = source_bags.get(pair)
        if not source_info:
            sys.exit(f"ERROR: no existing source bag found for pair {pair!r} in manifest.")
        payload_key = layout_payload_key(layout)
        entry = script_cache.get(payload_key)
        if not (isinstance(entry, dict) and isinstance(entry.get("script"), str) and entry.get("script")):
            sys.exit(f"ERROR: missing prebuilt card script for {payload_key}. Re-run BM cache populate and save.")
        logical = logical_name_for(layout, source_info["deck_name"], manifest_logical_names)
        if logical.strip().casefold() not in layout_art:
            missing_art.append(logical)
        card_name = f"{logical} - {CREATOR_DISPLAY}"
        seed = f"{CREATOR_TAG}|{payload_key}"
        card_guid = stable_guid("card|" + seed, used_guids)
        deck_id = stable_deck_id("deck|" + seed, used_deck_ids)
        script = static_card_script(entry["script"], machinery)
        card = make_static_map_card(card_guid, card_name, script, layout.get("previewUrl") or DEFAULT_FACE_URL, deck_id)
        new_cards.append((source_info["deck_guid"], card))
        manifest_additions.append({
            "deck_guid": source_info["deck_guid"],
            "deck_name": source_info["deck_name"],
            "card_guid": card_guid,
            "card_name": card_name,
            "map_creator_tag": CREATOR_TAG,
            "map_type_tag": TYPE_TAG,
            "creator_display": CREATOR_DISPLAY,
            "eligible": "true",
        })

    if missing_art and not args.allow_missing_layout_art:
        sample = ", ".join(missing_art[:5])
        sys.exit(f"ERROR: {len(missing_art)} imported maps have no matching layout art card. First: {sample}")

    print(f"Prepared {len(new_cards)} Battlemaster static map cards ({CREATOR_DISPLAY}).")
    print(f"Target bags: {len(set(g for g, _ in new_cards))}; manifest rows: {len(manifest_additions)}")
    if missing_art:
        print(f"WARNING: {len(missing_art)} layout-art matches missing.")

    if not args.write:
        print("[preview] no files written; pass --write to update ftc_base.json and map_manifest.csv.")
        return 0

    removed = remove_previous_import(target)
    manifest_rows = [r for r in manifest_rows if r.get("map_creator_tag") not in OLD_CREATOR_TAGS]
    for bag_guid, card in new_cards:
        bag = target_by_guid.get(bag_guid)
        if not bag:
            sys.exit(f"ERROR: target source bag {bag_guid} not found in {target_path}.")
        bag.setdefault("ContainedObjects", []).append(card)
    manifest_rows.extend(manifest_additions)

    target_path.write_text(json.dumps(target, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_manifest(manifest_path, manifest_rows)
    print(f"Wrote {target_path} and {manifest_path}; removed {removed} previous imported card(s).")
    print(f"Run: {validation_command_hint()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
