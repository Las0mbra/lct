#!/usr/bin/env python3
"""
Compiles TTSLUA scripts into the TTS JSON save file.

Usage:
    python3 compile.py            # prompts for version, writes compiled JSON
    python3 compile.py --test     # uses "test" as version, copies to TTS saves folder
    python3 compile.py --release  # version + patch notes from CHANGELOG.md, copies to TTS saves folder
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
sys.path.insert(0, str(SCRIPT_DIR))  # allow sibling imports when run from elsewhere
import term
import validate_maps

# Warnings collected across the whole run so the closing summary can report them
# in one place instead of the user having to scroll back through the log.
WARNINGS = []


def warn(msg: str):
    WARNINGS.append(msg)
    print(term.yellow(f"  WARNING: {msg}"))


def fail(msg: str):
    print(term.red(f"ERROR: {msg}"))
    sys.exit(1)

PATH_LUA   = SCRIPT_DIR.parent / "TTSLUA"
PATH_JSON  = SCRIPT_DIR.parent / "TTSJSON"
JSON_NAME  = "ftc_base"
XML_NAME   = "ftc_base_ui"
CHANGELOG  = SCRIPT_DIR.parent / "CHANGELOG.md"
GLOBAL_LUA = "global.ttslua"
# kustom40kDiceRollerMk3.ttslua is the legacy math.random roller for the orphaned
# beae28/4e0e0b bags hidden under the table. It's replaced by the xoshiro
# customKustom40kDiceRollerMk3.ttslua; keeping it out of the build stops the weak
# RNG code from running and re-seeding the process-global C rand() on every load.
DISABLED_LUA = {"statsHelperv2.ttslua", "kustom40kDiceRollerMk3.ttslua"}

REGEX_LUA_GUID       = re.compile(r'([0-9a-f]{6})')
REGEX_JSON_GUID      = re.compile(r'"GUID": "(.*)"')
REGEX_JSON_LUASCRIPT = re.compile(r'"LuaScript": ')
REGEX_JSON_XMLUI     = re.compile(r'"XmlUI":\s+"')
# Matches a full `"LuaScript": "...<value>..."` field on a single JSON line,
# tolerating any value content (including escaped quotes/backslashes) so we can
# replace it cleanly even if the source JSON already had content baked in.
REGEX_JSON_LUASCRIPT_FIELD = re.compile(r'("LuaScript":\s*)"(?:\\.|[^"\\])*"')


def validate_json_text(json_text: str, label: str):
    try:
        json.loads(json_text)
    except json.JSONDecodeError as exc:
        fail(f"{label} is not valid JSON: "
             f"{exc.msg} at line {exc.lineno}, column {exc.colno}.")


def _windows_documents_path():
    """Resolve the Windows Documents folder via the registry so a relocated
    Documents (e.g. moved off C: to N:) is honored. Returns None on non-Windows
    or if the registry value can't be read."""
    try:
        import winreg
    except ImportError:
        return None
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "Personal")
    except OSError:
        return None
    return Path(os.path.expandvars(value))


def get_tts_saves_path() -> Path:
    # Explicit override wins so users with non-standard setups can point at
    # whatever they want without code changes.
    override = os.environ.get("TTS_SAVES_PATH")
    if override:
        return Path(override)

    system = platform.system()
    home = Path.home()
    if system == "Windows":
        docs = _windows_documents_path() or (
            Path(os.environ.get("USERPROFILE", str(home))) / "Documents"
        )
        return docs / "My Games" / "Tabletop Simulator" / "Saves"
    elif system == "Darwin":
        return home / "Library" / "Tabletop Simulator" / "Saves"
    else:
        return home / ".local" / "share" / "Tabletop Simulator" / "Saves"



def inject_xml(json_lines: list, xml_file: Path):
    """Replace the top-level XmlUI value with the content of the xml file.
    Empty per-object XmlUI fields ("XmlUI": "") are skipped."""
    xml_content = json.dumps(xml_file.read_text(encoding="utf-8-sig"))
    for i, line in enumerate(json_lines):
        m = REGEX_JSON_XMLUI.search(line)
        if not m:
            continue
        # Skip empty per-object entries that end with "" (no real content)
        stripped = line.rstrip()
        if stripped.endswith('""') or stripped.endswith('"",'):
            continue
        # m.end() points to the char after the opening quote of the value.
        # Reconstruct: prefix up to (not including) that opening quote + new encoded value + trailing comma.
        prefix = line[:m.end() - 1]
        json_lines[i] = prefix + xml_content + ","
        print(f"  Writing to line {i + 1}. {term.green('Done.')}")
        return
    warn("populated XmlUI line not found in JSON — XML not injected.")


def inject_lua_into_line(json_lines: list, line_idx: int, lua_text: str):
    """Replace the LuaScript value on a JSON line with the given lua source text.

    Works whether the existing field is empty (`""`) or already populated — the
    full `"LuaScript": "..."` field is matched and rewritten in place, so a
    re-export of the save into ftc_base.json can't double-inject content.
    """
    lua_content = json.dumps(lua_text)
    line = json_lines[line_idx]
    new_line, count = REGEX_JSON_LUASCRIPT_FIELD.subn(
        lambda m: m.group(1) + lua_content, line, count=1
    )
    if count != 1:
        raise RuntimeError(
            f"Could not locate `\"LuaScript\": \"...\"` field on line {line_idx + 1}: {line!r}"
        )
    json_lines[line_idx] = new_line
    print(f"  Writing to line {line_idx + 1}.", end=" ")


def inject_map_card_hooks(json_lines: list) -> tuple:
    """Inject the Load Map -> menu notification into each baked map card.

    The source cards (imported from the upstream mod) carry no hook; we add it on
    every build by rewriting the `loadMap` body in place, so a re-import can't
    leave a card un-hooked. Returns (injected, candidates): candidates are lines
    whose LuaScript defines `loadMap`; injected is how many we actually rewrote
    (fewer means a signature we couldn't anchor — see the validator's warning).

    Idempotent: a script already containing the hook call is skipped.
    """
    injected = candidates = 0
    for i, line in enumerate(json_lines):
        m = REGEX_JSON_LUASCRIPT_FIELD.search(line)
        if not m:
            continue
        prefix, field = m.group(1), m.group(0)
        try:
            lua = json.loads(field[len(prefix):])  # value portion -> raw lua
        except (json.JSONDecodeError, ValueError):
            continue
        if "function loadMap" not in lua:
            continue
        candidates += 1
        if "onMapCardLoaded" in lua:  # already hooked
            continue
        new_lua, n = validate_maps.LOADMAP_SIGNATURE_RE.subn(
            lambda mm: mm.group(0) + validate_maps.MAP_LOAD_HOOK, lua, count=1
        )
        if n != 1:
            continue
        json_lines[i] = line[:m.start()] + prefix + json.dumps(new_lua) + line[m.end():]
        injected += 1
    return injected, candidates


def collect_lua_files() -> list:
    """Return [global.ttslua, ...all other .ttslua files recursively sorted]."""
    global_file = PATH_LUA / GLOBAL_LUA
    others = sorted(
        f for f in PATH_LUA.rglob("*.ttslua")
        if f.name != GLOBAL_LUA and f.name not in DISABLED_LUA
    )
    return [global_file] + others


def parse_changelog(path: Path):
    """Return (version, [note, ...]) from the top `## vX.Y.Z` section of CHANGELOG.md.

    The first `## ` heading is the version; the `- ` bullets beneath it (up to the
    next `## ` heading) are the player-facing patch notes.
    """
    if not path.exists():
        return None, []
    version, notes, in_section = None, [], False
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if s.startswith("## "):
            if in_section:
                break
            version = s[3:].strip()
            if version and not version.startswith("v"):
                version = "v" + version
            in_section = True
        elif in_section and s.startswith("- "):
            notes.append(s[2:].strip())
    return version, notes


def stamp_global(lua_text: str, version: str, patch: str, notes: list, debug: bool) -> str:
    """Rewrite the GAME_VERSION / GAME_PATCH / GAME_CHANGELOG / DEBUG markers in global.ttslua.

    version : build stamp ("test" or the release version) — drives chat + save name.
    patch   : latest CHANGELOG version — shown on the splash overlay.
    notes   : latest CHANGELOG bullets — shown on the splash overlay.
    debug   : build-wide debug switch — true for --test, false otherwise.
    """
    note_literal = "{" + ", ".join(json.dumps(n) for n in notes) + "}"
    replacements = [
        (r"^.*--\s*@@LCT_VERSION@@.*$",
         f"GAME_VERSION = {json.dumps(version or 'DEV')}   -- @@LCT_VERSION@@"),
        (r"^.*--\s*@@LCT_PATCH@@.*$",
         f"GAME_PATCH = {json.dumps(patch or 'DEV')}   -- @@LCT_PATCH@@"),
        (r"^.*--\s*@@LCT_CHANGELOG@@.*$",
         f"GAME_CHANGELOG = {note_literal}   -- @@LCT_CHANGELOG@@"),
        (r"^.*--\s*@@LCT_DEBUG@@.*$",
         f"DEBUG = {'true' if debug else 'false'}   -- @@LCT_DEBUG@@"),
    ]
    for pattern, repl in replacements:
        lua_text, count = re.subn(pattern, repl, lua_text, count=1, flags=re.M)
        if count != 1:
            warn(f"marker {pattern!r} not found in global.ttslua — not injected.")
    return lua_text


def stamp_save_name(line: str, version: str) -> str:
    """Append ` - <version>` to a `"SaveName"`/`"GameMode"` JSON string value.

    Matches the full `"key": "value",` shape so it works regardless of the value
    or a trailing escaped newline, instead of slicing a fixed number of chars.
    """
    m = re.match(r'(\s*"(?:SaveName|GameMode)":\s*")(.*)("\s*,?\s*)$', line)
    if not m:
        return line
    head, value, tail = m.groups()
    if value.endswith("\\n"):
        value = value[:-2]
    return f"{head}{value} - {version}{tail}"


def main():
    parser = argparse.ArgumentParser(description="Compile TTS Lua scripts into JSON.")
    parser.add_argument("--test", action="store_true",
                        help="Tag as 'test' build and copy to TTS saves folder.")
    parser.add_argument("--release", action="store_true",
                        help="Take version and patch notes from CHANGELOG.md and copy to TTS saves folder.")
    parser.add_argument("--no-validate", action="store_true",
                        help="Skip the map-card whitelist/terrain validation gate.")
    args = parser.parse_args()
    if args.test and args.release:
        fail("use either --test or --release, not both.")

    json_file = PATH_JSON / f"{JSON_NAME}.json"
    if not json_file.exists():
        fail(f"{json_file} not found. Ending compilation.")

    print(f"Validating {json_file.name}... ", end="")
    json_text = json_file.read_text(encoding="utf-8")
    validate_json_text(json_text, json_file.name)
    print(term.green("Done."))

    # --- Validate the baked-in map cards before doing any work --------------
    # The cards' Clear/Load wipe keeps a hard-coded GUID whitelist; a drifted
    # card can delete the mats. Gate the build on it (errors abort), unless the
    # user is mid-fix and opted out. Warnings never block.
    val_issues, val_ctx = [], None
    if not args.no_validate:
        save = json.loads(json_text)
        val_issues, val_ctx = validate_maps.validate(save.get("ObjectStates", []))
        print(term.cyan(f"Validating {len(val_ctx.cards)} map cards..."))
        n_err, _ = validate_maps.report(val_issues, val_ctx)
        validate_maps.report_zone_versions(val_ctx)
        WARNINGS.extend(
            f"map card: {i.message} [{i.where}]"
            for i in val_issues if i.level == validate_maps.WARN
        )
        if n_err:
            fail(f"{n_err} map-card validation error(s). "
                 f"Fix them or re-run with --no-validate to bypass.")

    # The latest CHANGELOG entry (top section) always drives the splash overlay,
    # for both test and release builds.
    patch, changelog_notes = parse_changelog(CHANGELOG)
    if patch:
        print(f"Latest patch from {CHANGELOG.name}: {patch} ({len(changelog_notes)} notes).")
    else:
        warn(f"no '## vX.Y.Z' entry found in {CHANGELOG.name} — splash not updated.")

    if args.test:
        version = "test"
    elif args.release:
        if not patch:
            fail(f"--release needs a '## vX.Y.Z' entry at the top of {CHANGELOG.name}.")
        version = patch
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
            fail(f"{f} not found. Ending compilation.")
        print(f"Scanning {f.name}... ", end="")
        first_line = f.read_text(encoding="utf-8").splitlines()[0]
        matches = REGEX_LUA_GUID.findall(first_line)
        if not matches:
            fail(f"no GUIDs found in {f.name}! Ending compilation.")
        print(f"GUIDs: {', '.join(matches)}")
        for guid in matches:
            lua_guids.append((guid, idx))

    # --- Load JSON as lines and index GUID / LuaScript positions ---
    print(f"\nLoading {json_file.name}... ", end="")
    json_lines = json_text.splitlines()

    json_guid_entries  = []  # [(line_idx, guid_value), ...]
    json_lua_line_idxs = []  # [line_idx, ...]

    for i, line in enumerate(json_lines):
        m = REGEX_JSON_GUID.search(line)
        if m:
            json_guid_entries.append((i, m.group(1)))
        if REGEX_JSON_LUASCRIPT.search(line):
            json_lua_line_idxs.append(i)

    print(f"{len(json_guid_entries)} GUIDs, {len(json_lua_line_idxs)} LuaScript slots found.")

    # --- Inject ftc_base_ui.xml into the top-level XmlUI field ---
    xml_file = PATH_JSON / f"{XML_NAME}.xml"
    if not xml_file.exists():
        fail(f"{xml_file} not found. Ending compilation.")
    print(f"Injecting {xml_file.name}... ", end="")
    inject_xml(json_lines, xml_file)

    # --- Inject global.ttslua into the first LuaScript slot ---
    # Stamp the player-facing version + patch notes into the Global script as it
    # is injected; the source file on disk is left untouched.
    # Debug build switch: on for --test, off for --release and prompted builds.
    debug_enabled = args.test
    print("Injecting global.ttslua... ", end="")
    global_text = stamp_global(
        lua_files[0].read_text(encoding="utf-8"), version, patch, changelog_notes, debug_enabled
    )
    inject_lua_into_line(json_lines, json_lua_line_idxs[0], global_text)
    print(term.green("Done."))

    # --- Inject each object script by matching GUIDs ---
    for find_guid, file_idx in lua_guids:
        print(f"Injecting {lua_files[file_idx].name} (GUID {find_guid})... ", end="")
        found = False
        for guid_line_idx, guid_val in json_guid_entries:
            if find_guid == guid_val:
                # Find the first LuaScript slot that appears after this GUID's line.
                # This is always the LuaScript field belonging to the same object block.
                lua_slot_idx = next(
                    (idx for idx in json_lua_line_idxs if idx > guid_line_idx), None
                )
                if lua_slot_idx is None:
                    fail(f"No LuaScript slot found after GUID {find_guid}! Ending compilation.")
                inject_lua_into_line(
                    json_lines, lua_slot_idx,
                    lua_files[file_idx].read_text(encoding="utf-8"),
                )
                print(term.green("Done."))
                found = True
                break
        if not found:
            fail(f"GUID {find_guid} not found in JSON! Ending compilation.")

    # --- Inject the Load Map hook into every baked map card ---
    print("Injecting Load Map hooks into map cards... ", end="")
    hooks_injected, hook_candidates = inject_map_card_hooks(json_lines)
    print(term.green(f"{hooks_injected}/{hook_candidates} done."))
    if hooks_injected != hook_candidates:
        warn(f"{hook_candidates - hooks_injected} map card(s) could not be hooked "
             f"(unexpected loadMap signature).")

    # --- Stamp version into SaveName (line 1) and GameMode (line 2) ---
    if version:
        print(f"\nStamping version '{version}'...")
        json_lines[1] = stamp_save_name(json_lines[1], version)
        json_lines[2] = stamp_save_name(json_lines[2], version)

    # --- Write output ---
    out_name = f"{JSON_NAME}_{version}_compiled.json" if version else f"{JSON_NAME}_compiled.json"
    out_file = SCRIPT_DIR / out_name
    compiled_json = "\n".join(json_lines)
    validate_json_text(compiled_json, out_name)
    out_file.write_text(compiled_json, encoding="utf-8")

    # --- Copy to TTS saves for test/release builds ---
    copied_to = None
    if args.test or args.release:
        tts_saves = get_tts_saves_path()
        if tts_saves.exists():
            shutil.copy(out_file, tts_saves)
            copied_to = tts_saves
        else:
            warn(f"TTS saves folder not found at {tts_saves}. Skipping copy.")

    print_summary(version, debug_enabled, lua_guids, json_guid_entries, val_ctx,
                  val_issues, hooks_injected, out_file, copied_to)


def print_summary(version, debug_enabled, lua_guids, json_guid_entries, val_ctx,
                  val_issues, hooks_injected, out_file, copied_to):
    """Closing one-look report: what was built, what was checked, where it went."""
    val_errs = sum(1 for i in val_issues if i.level == validate_maps.ERROR)
    val_warns = len(val_issues) - val_errs

    if val_ctx is not None:
        v2, v1 = validate_maps.split_by_zone_version(val_ctx)
        zones = f"{len(v2)} v2 / {len(v1)} v1"
        zones = term.yellow(zones) if v1 else term.green(zones)
    else:
        zones = term.dim("not checked")

    if val_ctx is None:
        validation = term.dim("skipped (--no-validate)")
    elif val_errs:
        validation = term.red(f"{val_errs} error(s), {val_warns} warning(s)")
    elif val_warns:
        validation = term.yellow(f"passed, {val_warns} warning(s)")
    else:
        validation = term.green(f"passed ({len(val_ctx.cards)} cards)")

    rows = [
        ("Version", version or "(none)"),
        ("Debug diagnostics", term.yellow("enabled") if debug_enabled else "disabled"),
        ("Scripts injected", f"{len(lua_guids)} object + 1 global"),
        ("Map card hooks", f"{hooks_injected} injected"),
        ("JSON GUIDs", str(len(json_guid_entries))),
        ("Map validation", validation),
        ("Map Zones", zones),
        ("Warnings", term.yellow(str(len(WARNINGS))) if WARNINGS else "0"),
        ("Output", str(out_file)),
        ("Copied to", str(copied_to) if copied_to else term.dim("not copied")),
    ]

    bar = "─" * 56
    print()
    print(term.cyan(bar))
    print(term.bold("  BUILD SUMMARY"))
    print(term.cyan(bar))
    for label, value in rows:
        print(f"  {label:<17}: {value}")
    if WARNINGS:
        print(term.yellow("\n  Warnings this run:"))
        for w in WARNINGS:
            print(term.yellow(f"    • {w}"))
    print(term.cyan(bar))
    print(term.green("  ✓ Build complete.") if not WARNINGS
          else term.yellow("  ✓ Build complete (with warnings)."))


if __name__ == "__main__":
    main()
