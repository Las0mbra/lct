#!/usr/bin/env python3
"""
Bake the Battlemaster spawner's populated cache into the source save.

Workflow to ship the mod warm:
  1. Load a compiled build in TTS.
  2. Click the debug "BM cache populate" button (requires a --test/debug build),
     let it finish, then SAVE the table (or save the spawner as a Saved Object).
  3. Run this tool, pointing it at that saved file:
         python3 bake_battlemaster_cache.py "<path to the saved .json>"
     It copies the spawner object's LuaScriptState (the cache) into
     TTSJSON/ftc_base.json so the next `compile.py` ships with the cache baked in.
  4. Commit ftc_base.json and rebuild.

The cache lives in the spawner's LuaScriptState (written by its onSave()), so
restoreSpawnerState() restores it on load with no code changes. compile.py
preserves LuaScriptState as-is, so baking here is enough to ship warm.

ftc_base.json is edited surgically (only the spawner's LuaScriptState line is
rewritten) so the rest of the file and its formatting stay byte-identical.

Use --clear to reset the shipped object back to cold (empty cache).
"""

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
FTC_BASE = SCRIPT_DIR.parent / "TTSJSON" / "ftc_base.json"
SPAWNER_GUID = "b4d10a"

# A full `"LuaScriptState": "...value..."` field on one line, tolerating any
# escaped content (mirrors compile.py's LuaScript field regex).
LUASCRIPTSTATE_FIELD = re.compile(r'("LuaScriptState":\s*)"(?:\\.|[^"\\])*"')


def find_object(states, guid):
    """Depth-first search for an object with the given GUID, descending into
    ContainedObjects/States so a bagged or stateful spawner is still found."""
    for obj in states or []:
        if obj.get("GUID") == guid:
            return obj
        found = find_object(obj.get("ContainedObjects"), guid)
        if found:
            return found
        for child in (obj.get("States") or {}).values():
            found = find_object([child], guid)
            if found:
                return found
    return None


def summarize_cache(state_text):
    """Best-effort one-line summary of what the cache holds."""
    try:
        st = json.loads(state_text)
    except (json.JSONDecodeError, ValueError):
        return "unparseable state"
    themes = st.get("themes") or []
    lc = st.get("layoutCatalog") or {}
    layouts = lc.get("layouts") if isinstance(lc, dict) else None
    lpc = st.get("layoutPayloadCache") or {}
    return (f"template={'yes' if st.get('templateCatalog') else 'no'}, "
            f"themes={len(themes) if isinstance(themes, list) else '?'}, "
            f"themePayload={'yes' if st.get('themePayload') else 'no'}, "
            f"layoutCatalog={len(layouts) if isinstance(layouts, list) else '?'}, "
            f"layoutPayloadCache={len(lpc) if isinstance(lpc, dict) else 0}")


def write_state_into_ftc_base(new_value_literal):
    """Surgically rewrite the spawner's LuaScriptState line in ftc_base.json.
    new_value_literal is a complete JSON string literal (already quoted).
    The match is bounded to the spawner's own object block (before the next GUID)
    so we can never rewrite a different object's state."""
    text = FTC_BASE.read_text(encoding="utf-8")
    guid_idx = text.find(f'"GUID": "{SPAWNER_GUID}"')
    if guid_idx == -1:
        sys.exit(f"ERROR: spawner object {SPAWNER_GUID} not found in {FTC_BASE.name}.")
    next_guid_idx = text.find('"GUID":', guid_idx + len(f'"GUID": "{SPAWNER_GUID}"'))
    m = LUASCRIPTSTATE_FIELD.search(text, guid_idx)
    if not m:
        sys.exit(f"ERROR: no LuaScriptState field found after GUID {SPAWNER_GUID}.")
    if next_guid_idx != -1 and m.start() >= next_guid_idx:
        sys.exit(f"ERROR: LuaScriptState for {SPAWNER_GUID} not found within its own object block "
                 "(the matched field belongs to a later object). Aborting to avoid corrupting it.")
    new_text = text[:m.start()] + m.group(1) + new_value_literal + text[m.end():]
    json.loads(new_text)  # validate the whole file still parses
    FTC_BASE.write_text(new_text, encoding="utf-8")


def cache_completeness(state_text):
    """Return (missing_count, detail). missing_count == 0 means a full warm cache:
    template + theme payload + layout catalog present, and every catalog layout has
    a cached lite payload (mirrors the spawner's layoutPayloadCacheKey)."""
    st = json.loads(state_text)
    problems = []
    if not st.get("templateCatalog"):
        problems.append("no templateCatalog")
    if not st.get("themePayload"):
        problems.append("no themePayload")
    lc = st.get("layoutCatalog") or {}
    layouts = lc.get("layouts") if isinstance(lc, dict) else None
    if not isinstance(layouts, list) or not layouts:
        problems.append("no layoutCatalog.layouts")
        return (1 if problems else 0), "; ".join(problems)
    cache = st.get("layoutPayloadCache") or {}
    missing = 0
    for layout in layouts:
        slot = (layout.get("chapterApprovedSlot") or {}).get("slotIndex", layout.get("slotIndex"))
        pair = layout.get("forcePairKey") or ""
        key = layout.get("layoutKey") or ""
        if not key and layout.get("id") is not None:
            key = f"{layout['id']}@{layout.get('updatedAt', '')}"
        if not pair or slot is None or not key:
            missing += 1
            continue
        payload_key = f"{pair}|slot:{slot}|layout:{key}"
        entry = cache.get(payload_key)
        if not (isinstance(entry, dict) and isinstance(entry.get("payload"), dict)):
            missing += 1
    if missing:
        problems.append(f"{missing}/{len(layouts)} layout payloads missing from cache")
    return (missing + len(problems) if problems else 0), "; ".join(problems) if problems else "complete"


def main():
    ap = argparse.ArgumentParser(description="Bake the Battlemaster cache into ftc_base.json.")
    ap.add_argument("saved_file", nargs="?", help="Populated TTS save / saved-object JSON.")
    ap.add_argument("--clear", action="store_true", help="Reset the shipped cache to cold (empty).")
    ap.add_argument("--allow-partial", action="store_true",
                    help="Bake even if the cache is incomplete (Generate is cache-only, so this ships a "
                         "build that can't make some/all maps).")
    args = ap.parse_args()

    if not FTC_BASE.exists():
        sys.exit(f"ERROR: {FTC_BASE} not found.")

    if args.clear:
        write_state_into_ftc_base('""')
        print(f"Cleared {SPAWNER_GUID} cache in {FTC_BASE.name}. Mod now ships cold.")
        return

    if not args.saved_file:
        ap.error("provide a saved file, or use --clear")
    src_path = Path(args.saved_file)
    if not src_path.exists():
        sys.exit(f"ERROR: {src_path} not found.")
    src = json.loads(src_path.read_text(encoding="utf-8"))
    source_obj = find_object(src.get("ObjectStates"), SPAWNER_GUID)
    if source_obj is None:
        sys.exit(f"ERROR: spawner object {SPAWNER_GUID} not found in {src_path.name}.")

    state_text = source_obj.get("LuaScriptState") or ""
    if state_text.strip() == "":
        sys.exit(f"ERROR: {src_path.name} spawner has an EMPTY cache. Populate it in TTS first "
                 "(debug 'BM cache populate'), save, then re-run.")
    try:
        json.loads(state_text)  # must be restoreable by the spawner
    except (json.JSONDecodeError, ValueError) as exc:
        sys.exit(f"ERROR: spawner LuaScriptState is not valid JSON: {exc}")

    missing, detail = cache_completeness(state_text)
    if missing and not args.allow_partial:
        sys.exit(f"ERROR: cache is incomplete ({detail}). Generate is cache-only, so a partial bake "
                 "ships a build that can't make those maps. Re-run the debug populate (and save), or "
                 "pass --allow-partial to bake anyway.")
    if missing:
        print(f"WARNING: baking an INCOMPLETE cache ({detail}) due to --allow-partial.")

    write_state_into_ftc_base(json.dumps(state_text))
    print(f"Baked {len(state_text)} chars of cache into {FTC_BASE.name} ({SPAWNER_GUID}).")
    print(f"  cache: {summarize_cache(state_text)}")
    print("Commit ftc_base.json and rebuild (compile.py) to ship the warm cache.")


if __name__ == "__main__":
    main()
