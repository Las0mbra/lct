#!/usr/bin/env python3
"""
Compiles TTSLUA scripts into the TTS JSON save file.

Usage:
    python3 compile.py          # prompts for version, writes compiled JSON
    python3 compile.py --test   # uses "test" as version, copies to TTS saves folder
"""

import argparse
import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PATH_LUA   = SCRIPT_DIR.parent / "TTSLUA"
PATH_JSON  = SCRIPT_DIR.parent / "TTSJSON"
JSON_NAME  = "ftc_base"

REGEX_LUA_GUID      = re.compile(r'([0-9a-f]{6})')
REGEX_JSON_GUID     = re.compile(r'"GUID": "(.*)"')
REGEX_JSON_LUASCRIPT = re.compile(r'"LuaScript": ')


def get_tts_saves_path() -> Path:
    system = platform.system()
    home = Path.home()
    if system == "Windows":
        docs = Path(os.environ.get("USERPROFILE", str(home))) / "Documents"
        return docs / "My Games" / "Tabletop Simulator" / "Saves"
    elif system == "Darwin":
        return home / "Library" / "Tabletop Simulator" / "Saves"
    else:
        return home / ".local" / "share" / "Tabletop Simulator" / "Saves"


def inject_lua_into_line(json_lines: list, line_idx: int, lua_file: Path):
    """Replace the empty LuaScript value on a JSON line with the content of a lua file."""
    lua_content = json.dumps(lua_file.read_text(encoding="utf-8"))
    line = json_lines[line_idx]
    # Strip trailing `"",` (3 chars) and append the encoded content + ","
    json_lines[line_idx] = line[:-3] + lua_content + ","
    print(f"  Writing to line {line_idx + 1}.", end=" ")


def collect_lua_files() -> list:
    """Return [global.ttslua, ...all other .ttslua files recursively sorted]."""
    global_file = PATH_LUA / "global.ttslua"
    others = sorted(
        f for f in PATH_LUA.rglob("*.ttslua") if f.name != "global.ttslua"
    )
    return [global_file] + others


def main():
    parser = argparse.ArgumentParser(description="Compile TTS Lua scripts into JSON.")
    parser.add_argument("--test", action="store_true",
                        help="Tag as 'test' build and copy to TTS saves folder.")
    args = parser.parse_args()

    json_file = PATH_JSON / f"{JSON_NAME}.json"
    if not json_file.exists():
        print(f"ERROR: {json_file} not found. Ending compilation.")
        sys.exit(1)

    if args.test:
        version = "test"
    else:
        version = input("Version number (leave blank for none): ").strip()
        if version and not version.startswith("v"):
            version = "v" + version

    lua_files = collect_lua_files()

    # --- Extract GUIDs from each non-global lua file ---
    lua_guids = []  # [(guid_str, file_index), ...]
    for idx in range(1, len(lua_files)):
        f = lua_files[idx]
        if not f.exists():
            print(f"ERROR: {f} not found. Ending compilation.")
            sys.exit(1)
        print(f"Scanning {f.name}... ", end="")
        first_line = f.read_text(encoding="utf-8").splitlines()[0]
        matches = REGEX_LUA_GUID.findall(first_line)
        if not matches:
            print("no GUIDs found! Ending compilation.")
            sys.exit(1)
        print(f"GUIDs: {', '.join(matches)}")
        for guid in matches:
            lua_guids.append((guid, idx))

    # --- Load JSON as lines and index GUID / LuaScript positions ---
    print(f"\nLoading {json_file.name}... ", end="")
    json_lines = json_file.read_text(encoding="utf-8").splitlines()

    json_guid_entries  = []  # [(line_idx, guid_value), ...]
    json_lua_line_idxs = []  # [line_idx, ...]

    for i, line in enumerate(json_lines):
        m = REGEX_JSON_GUID.search(line)
        if m:
            json_guid_entries.append((i, m.group(1)))
        if REGEX_JSON_LUASCRIPT.search(line):
            json_lua_line_idxs.append(i)

    print(f"{len(json_guid_entries)} GUIDs, {len(json_lua_line_idxs)} LuaScript slots found.")

    # --- Inject global.ttslua into the first LuaScript slot ---
    print("Injecting global.ttslua... ", end="")
    inject_lua_into_line(json_lines, json_lua_line_idxs[0], lua_files[0])
    print("Done.")

    # --- Inject each object script by matching GUIDs ---
    for find_guid, file_idx in lua_guids:
        print(f"Injecting {lua_files[file_idx].name} (GUID {find_guid})... ", end="")
        found = False
        for entry_idx, (_, guid_val) in enumerate(json_guid_entries):
            if find_guid == guid_val:
                lua_slot_idx = json_lua_line_idxs[entry_idx + 1]
                inject_lua_into_line(json_lines, lua_slot_idx, lua_files[file_idx])
                print("Done.")
                found = True
                break
        if not found:
            print(f"GUID {find_guid} not found in JSON! Ending compilation.")
            sys.exit(1)

    # --- Stamp version into SaveName (line 1) and GameMode (line 2) ---
    if version:
        print(f"\nStamping version '{version}'...")
        # Lines end with `\n",` — strip last 4 chars and append version tag
        json_lines[1] = json_lines[1][:-4] + f' - {version}",'
        json_lines[2] = json_lines[2][:-4] + f' - {version}",'

    # --- Write output ---
    out_name = f"{JSON_NAME}_{version}_compiled.json" if version else f"{JSON_NAME}_compiled.json"
    out_file = SCRIPT_DIR / out_name
    out_file.write_text("\n".join(json_lines), encoding="utf-8")
    print(f"\nOutput: {out_file}")

    # --- Copy to TTS saves if --test ---
    if args.test:
        tts_saves = get_tts_saves_path()
        if tts_saves.exists():
            shutil.copy(out_file, tts_saves)
            print(f"Copied to {tts_saves}")
        else:
            print(f"WARNING: TTS saves folder not found at {tts_saves}. Skipping copy.")


if __name__ == "__main__":
    main()
