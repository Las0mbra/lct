#!/usr/bin/env python3
"""Transfer objective-marker tags from an in-TTS editing session into ftc_base.json.

Companion to the "Back to Selection (SAVE TAGS)" debug button in startMenu.ttslua
(--test builds only). That button records, per loaded map, every table object that
carries an `obj_*` tag -- keyed by the map card's GUID -- and the menu object
persists the whole accumulator in its `LuaScriptState` (svDebugMapTagData). So a
single editing session, where you load each map, tag its objective markers, and
press the button, ends with all the edits baked into one save file.

This script reads that save, and for each recorded map card writes the recorded
tags onto the matching baked terrain object inside the card's `objectJSONs` blob
in TTSJSON/ftc_base.json. The join key is the object GUID: only one map is loaded
at a time in TTS, so a baked object's GUID is free and preserved when the card
spawns it, meaning the live (recorded) GUID equals the baked GUID. Nickname and
position are recorded alongside each GUID purely for diagnostics: if a baked GUID
ever collided with a live scene object, TTS would reassign the spawned object a
fresh GUID (validate_maps flags such collisions), the match would fail, and this
script reports the object's name/position so you can resolve it by hand.

Writes are in place at the text level (the card's single LuaScript line is
replaced as a whole), so every other byte of the 60 MB file keeps its exact
formatting -- mirroring upgrade_map_zones.py.

    python3 apply_map_tags_from_save.py --save path/to/edited_save.json
    python3 apply_map_tags_from_save.py --save ... --dry-run
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import term

FTC_BASE = Path(__file__).parent.parent / "TTSJSON" / "ftc_base.json"
# The startMenu object; its LuaScriptState holds svDebugMapTagData. Same GUID the
# Load Map hook calls (see validate_maps.MENU_GUID).
MENU_GUID = "738804"

# First (object-level) GUID inside a baked `[[ {json} ]]` terrain entry.
_ENTRY_GUID_RE = re.compile(r'"GUID":\s*"([0-9a-fA-F]{6})"')
# Each baked terrain object is a Lua long-string [[ {json} ]] in objectJSONs.
_OBJECTJSON_ENTRY_RE = re.compile(r'\[\[(.*?)\]\]', re.DOTALL)
# A top-level (exactly two-space indent) Tags field, inline or multi-line, with
# either newline style. Tags arrays hold only strings, so `[^\]]*` safely spans
# the whole array. The leading newline is consumed so the replacement supplies
# its own (matching the entry's CRLF/LF style).
_TOP_TAGS_RE = re.compile(r'\r?\n  "Tags": \[[^\]]*\],?')
# Canonical insertion anchor: Tags sits immediately before LayoutGroupSortIndex
# in the TTS object schema (verified against existing obj_*-tagged cards).
_LAYOUT_SORT_ANCHOR_RE = re.compile(r'\r?\n  "LayoutGroupSortIndex"')
_ENTRY_GUID_LINE_RE = re.compile(r'\r?\n  "GUID": "[0-9a-fA-F]{6}",')


def find_menu_object(object_states):
    """Locate the startMenu object by GUID anywhere in the object tree."""
    stack = list(object_states)
    while stack:
        o = stack.pop()
        if o.get("GUID") == MENU_GUID:
            return o
        stack.extend(o.get("ContainedObjects") or [])
    return None


def load_tag_data(save_path):
    """Pull svDebugMapTagData out of the editing save's menu LuaScriptState.

    Returns { cardGuid: {"name": str, "objects": {objGuid: {"tags": [...],
    "nickname": str, "pos": {x,y,z}}}} }.
    """
    save = json.loads(Path(save_path).read_text(encoding="utf-8"))
    menu = find_menu_object(save.get("ObjectStates", []))
    if not menu:
        raise SystemExit(term.red(f"ERROR: menu object {MENU_GUID} not found in {save_path}."))
    state = menu.get("LuaScriptState") or ""
    if not state.strip():
        raise SystemExit(term.red("ERROR: menu object has no LuaScriptState (nothing was saved)."))
    decoded = json.loads(state)
    data = decoded.get("svDebugMapTagData")
    # TTS JSON.encode emits an empty table as [] rather than {}.
    if not data or not isinstance(data, dict):
        raise SystemExit(term.yellow("No svDebugMapTagData recorded in this save -- nothing to apply."))
    return data


def build_tags_block(tags, nl):
    """Render a top-level Tags field matching TTS's pretty-printed entry format,
    using the entry's own newline style (nl is "\\n" or "\\r\\n")."""
    if not tags:
        return nl + '  "Tags": [],'
    inner = ("," + nl).join("    " + json.dumps(t) for t in tags)
    return nl + '  "Tags": [' + nl + inner + nl + '  ],'


def set_entry_tags(entry, tags):
    """Set the top-level Tags of one baked object's JSON text (minimal edit),
    preserving the entry's CRLF/LF newline style."""
    nl = "\r\n" if "\r\n" in entry else "\n"
    block = build_tags_block(tags, nl)
    if _TOP_TAGS_RE.search(entry):
        return _TOP_TAGS_RE.sub(lambda _m: block, entry, count=1)
    m = _LAYOUT_SORT_ANCHOR_RE.search(entry)
    if m:
        return entry[:m.start()] + block + entry[m.start():]
    # No schema anchor (unexpected): fall back to just after the object's GUID line.
    m = _ENTRY_GUID_LINE_RE.search(entry)
    if m:
        return entry[:m.end()] + block + entry[m.end():]
    raise ValueError("could not locate an insertion point for Tags")


def rewrite_card_lua(lua, objects):
    """Rewrite the card's objectJSONs so recorded objects get their tags.

    Returns (new_lua, matched_guids, unmatched_records). Matching is by baked
    object GUID; records with no GUID match are returned so the caller can report
    them (see the module docstring on GUID collisions).
    """
    head, sep, blob = lua.partition("objectJSONs = {")
    if not sep:
        return lua, set(), dict(objects)

    matched = set()

    def repl(m):
        entry = m.group(1)
        gm = _ENTRY_GUID_RE.search(entry)
        guid = gm.group(1) if gm else None
        if guid and guid in objects:
            matched.add(guid)
            return "[[" + set_entry_tags(entry, objects[guid].get("tags") or []) + "]]"
        return m.group(0)

    new_blob = _OBJECTJSON_ENTRY_RE.sub(repl, blob)
    unmatched = {g: rec for g, rec in objects.items() if g not in matched}
    return head + sep + new_blob, matched, unmatched


def index_cards(object_states):
    """Map cardGuid -> card object dict (only objects that carry a LuaScript)."""
    cards = {}
    stack = list(object_states)
    while stack:
        o = stack.pop()
        g = o.get("GUID")
        if g and o.get("LuaScript"):
            cards[g] = o
        stack.extend(o.get("ContainedObjects") or [])
    return cards


def main():
    parser = argparse.ArgumentParser(description="Apply recorded obj_* tags into ftc_base.json.")
    parser.add_argument("--save", required=True, help="Path to the TTS editing save (.json).")
    parser.add_argument("--base", default=str(FTC_BASE), help="Target ftc_base.json (default: TTSJSON/ftc_base.json).")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing.")
    args = parser.parse_args()

    base_path = Path(args.base)
    if not base_path.exists():
        print(term.red(f"ERROR: {base_path} not found."))
        return 1

    data = load_tag_data(args.save)
    raw = base_path.read_text(encoding="utf-8")
    cards = index_cards(json.loads(raw).get("ObjectStates", []))

    print(term.bold(f"Applying tags from {len(data)} recorded map(s):"))
    total_objs = 0
    total_unmatched = 0
    missing_cards = 0
    changes = []  # (old_encoded, new_encoded)

    for card_guid, rec in sorted(data.items(), key=lambda kv: kv[1].get("name") or ""):
        name = rec.get("name") or "?"
        objects = rec.get("objects") or {}
        if not isinstance(objects, dict) or not objects:
            print(term.dim(f"  {card_guid}  {name}: no objects recorded, skipped."))
            continue
        card = cards.get(card_guid)
        if not card:
            print(term.red(f"  {card_guid}  {name}: card not found in base, SKIPPED."))
            missing_cards += 1
            continue

        old_lua = card["LuaScript"]
        new_lua, matched, unmatched = rewrite_card_lua(old_lua, objects)
        if unmatched:
            for g, urec in unmatched.items():
                pos = urec.get("pos") or {}
                where = (f" at ({pos.get('x'):.1f},{pos.get('z'):.1f})"
                         if isinstance(pos.get("x"), (int, float)) else "")
                print(term.yellow(f"      ! object {g} ({urec.get('nickname') or ''!r}){where} "
                                  f"not found in card's baked terrain -- resolve by hand"))
            total_unmatched += len(unmatched)

        if new_lua == old_lua:
            print(term.dim(f"  {card_guid}  {name}: no change."))
            continue

        old_encoded = json.dumps(old_lua)
        if raw.count(old_encoded) != 1:
            print(term.red(f"  {card_guid}  {name}: LuaScript not uniquely locatable in file, SKIPPED."))
            continue
        changes.append((old_encoded, json.dumps(new_lua)))
        total_objs += len(matched)
        print(term.green(f"  {card_guid}  {name}: tagged {len(matched)} object(s)."))

    if not changes:
        print(term.dim("\nNothing to write."))
        return 1 if (missing_cards or total_unmatched) else 0

    new_raw = raw
    for old_encoded, new_encoded in changes:
        new_raw = new_raw.replace(old_encoded, new_encoded, 1)

    # Never write a file we can't parse back.
    try:
        json.loads(new_raw)
    except json.JSONDecodeError as exc:
        print(term.red(f"ERROR: rewrite produced invalid JSON ({exc}); aborting."))
        return 1

    summary = (f"{total_objs} object(s) across {len(changes)} card(s)"
               + (f", {total_unmatched} unmatched" if total_unmatched else "")
               + (f", {missing_cards} card(s) missing" if missing_cards else ""))
    if args.dry_run:
        print(term.yellow(f"\n[dry run] would tag {summary}; file unchanged."))
        return 0

    base_path.write_text(new_raw, encoding="utf-8")
    print(term.green(f"\n✓ Tagged {summary}. Wrote {base_path.name}."))
    print(term.dim("  Next: run `python3 scripts/validate_maps.py` to confirm no drift."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
