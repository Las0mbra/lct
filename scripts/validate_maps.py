#!/usr/bin/env python3
"""Static validation of the baked-in map cards in ftc_base.json.

Each map card (a mission-terrain card imported from the upstream "Map Saver"
mod) carries a `scriptzoneCallback` that spawns a scripting zone to wipe the
table before (re)spawning its terrain — see the Load Map / Clear Map buttons.
The wipe keeps a hard-coded whitelist of GUIDs so the mats and the build-tool
tables survive. Because that whitelist is copy-pasted into every card (~15 of
them), it drifts silently the moment one card is re-imported: a card that drops
the mat GUID will happily destruct the surface every other system sits on.

These checks guard the invariants that keep Clear/Load from nuking the mats.

Adding a check:
    @check
    def my_rule(ctx):
        for card in ctx.cards:
            if something_wrong(card):
                yield Issue(ERROR, card.where, "what went wrong")

Run standalone:  python3 validate_maps.py
Or import:       issues, ctx = validate(object_states)
"""

import argparse
import csv
import json
import re
import sys
from collections import namedtuple
from pathlib import Path

try:
    import term
except ImportError:  # allow `python3 Compiler/validate_maps.py` from repo root
    sys.path.insert(0, str(Path(__file__).parent))
    import term

# --- Configuration: the invariants the cards must uphold --------------------

# Every map card's wipe whitelist must keep these GUIDs (id -> human label).
REQUIRED_KEEP_GUIDS = {
    "28865a": "FTC Felt Surface (mapMat)",
    "4ee1f2": "FTC board matObjSurface (mat)",
    "6012bf": "ForceOrg Table",
    "948ce5": "FTC Table",
    "e7ca6e": "Map Builder Table",
}

# Subset of the above that must ALSO exist as a real object in this save. The
# build-tool tables live only in the upstream builder environment and are
# legitimately absent here, so we only assert the mats actually ship.
KEEP_GUIDS_MUST_EXIST = {"28865a", "4ee1f2"}

# Every card is expected to honor the per-object opt-out tag.
EXPECTED_GM_EXCLUDE = "MapExclude"

# --- Compile-time "Load Map" hook -------------------------------------------
# compile.py injects a one-liner at the top of each card's loadMap so pressing
# Load Map notifies the menu object (738804) with the card's name/GUID. The
# source cards stay hook-free; the hook is (re)injected on every build, so a
# re-import from the upstream mod can't leave a card un-hooked.
MENU_GUID = "738804"
LOADMAP_SIGNATURE_RE = re.compile(r'function\s+loadMap\s*\([^)]*\)')
MAP_LOAD_HOOK = (
    '\n    do local _m = getObjectFromGUID("' + MENU_GUID + '"); '
    'if _m then _m.call("onMapCardLoaded", '
    '{name = self.getName(), guid = self.getGUID()}) end end'
)

# --- Map Zones v2 ------------------------------------------------------------
# The upstream wipe (scriptzoneCallback) reads zone.getObjects() the instant the
# scripting zone spawns -- before TTS has populated the zone with its contained
# objects -- so the wipe often removes nothing and the player has to re-click.
# "Map Zones v2" rewrites the callback to (a) defer detection by a couple of
# frames so the zone is populated first, (b) keep the card itself (obj ~= self)
# so its 0.5s terrain-spawn timer survives, and (c) tag itself with a marker so
# we can tell v1 from v2. This is applied by the dedicated upgrade command only,
# never by a normal compile; compile just reports who is on which version.
MAP_ZONES_V2_MARKER = "@@MAP_ZONES_V2@@"
# Locate the whole `function scriptzoneCallback ... end` by stopping at the next
# top-level function (loadMap is always next in these cards).
_NEXT_CARD_FUNC_RE = re.compile(r'function\s+(?:loadMap|clearMap|on[lL]oad)\b')
# Single-line LuaScript field, used by the line-level in-place rewriter so the
# rest of the 1.4MB JSON keeps its exact formatting (only the card lines change).
LUASCRIPT_FIELD_RE = re.compile(r'("LuaScript":\s*)"(?:\\.|[^"\\])*"')


def build_v2_callback(keep_guids) -> str:
    """Return the canonical v2 `scriptzoneCallback` Lua text for a keep-list."""
    keepset = ", ".join(f'["{g}"]=true' for g in sorted(keep_guids))
    return (
        'function scriptzoneCallback(zone) -- ' + MAP_ZONES_V2_MARKER + ' deferred detection\n'
        '        Wait.frames(function()\n'
        '            local keep = {' + keepset + '}\n'
        '            for _, obj in ipairs(zone.getObjects()) do\n'
        '                if obj ~= self and not keep[obj.getGUID()] and obj.getGMNotes() ~= "MapExclude" then\n'
        '                    obj.destruct()\n'
        '                end\n'
        '            end\n'
        '            zone.destruct()\n'
        '        end, 2)\n'
        '    end'
    )


def migrate_card_lua(lua: str):
    """Rewrite a card's v1 scriptzoneCallback to v2. Return (new_lua, changed).

    Idempotent: a card already carrying the v2 marker is returned unchanged.
    The keep-list is preserved (union'd with the required GUIDs as a floor, so a
    mat can never be dropped), and all formatting outside the callback is kept.
    """
    if "function scriptzoneCallback" not in lua or MAP_ZONES_V2_MARKER in lua:
        return lua, False
    start = lua.index("function scriptzoneCallback")
    nxt = _NEXT_CARD_FUNC_RE.search(lua, start + 1)
    if not nxt:
        return lua, False
    end = nxt.start()
    old_block = lua[start:end]
    trailing = old_block[len(old_block.rstrip()):]          # ws before next function
    keep = set(_KEEP_GUID_RE.findall(old_block)) | set(REQUIRED_KEEP_GUIDS)
    return lua[:start] + build_v2_callback(keep) + trailing + lua[end:], True

# --- Model ------------------------------------------------------------------

ERROR = "ERROR"
WARN = "WARN"

Issue = namedtuple("Issue", ["level", "where", "message"])

# A card is identified by its wipe/spawn machinery rather than by GUID, so newly
# imported cards are picked up automatically. Two keep-list forms exist: v1's
# `getGUID() ~= "xxxxxx"` and-chain, and v2's `["xxxxxx"]=true` lookup table.
_KEEP_GUID_RE = re.compile(r'getGUID\(\)\s*~=\s*"([0-9a-fA-F]{6})"')
_KEEP_GUID_V2_RE = re.compile(r'\["([0-9a-fA-F]{6})"\]\s*=\s*true')
_GM_EXCLUDE_RE = re.compile(r'getGMNotes\(\)\s*~=\s*"([^"]+)"')
_ZONE_SCALE_RE = re.compile(r'zoneScale\s*=\s*\{([^}]*)\}')
_TERRAIN_GUID_RE = re.compile(r'"GUID"\s*:')
_TERRAIN_GUID_VALUE_RE = re.compile(r'"GUID"\s*:\s*"([0-9a-fA-F]{6})"')
# Each baked terrain object is a Lua long-string [[ {json} ]] in objectJSONs.
_OBJECTJSON_ENTRY_RE = re.compile(r'\[\[(.*?)\]\]', re.DOTALL)
# Card name "... - Sweeping Engagement" -> "Sweeping Engagement" (mirrors the
# Lua suffix match the Load Map auto-deploy uses).
_NAME_SUFFIX_RE = re.compile(r'^.*-\s*(.*?)\s*$')

# startMenu.ttslua holds the mission matrix and the deployment-zone names that a
# couple of cross-checks need. Read best-effort; checks skip if it isn't found.
STARTMENU_LUA = Path(__file__).parent.parent / "TTSLUA" / "startMenu.ttslua"
MAP_MANIFEST = Path(__file__).parent.parent / "data" / "map_manifest.csv"
MAP_MANIFEST_COLUMNS = {"deck_guid", "deck_name", "card_guid", "card_name", "map_creator_tag"}
REQUIRED_MAP_TAG = "map"
MAP_CREATOR_TAG_PREFIX = "map_crt"
_GUID_RE = re.compile(r"^[0-9a-fA-F]{6}$")
_MATRIX_GUID_RE = re.compile(r'guid\s*=\s*"([0-9a-fA-F]{6})"')
_DEPLOY_ZONE_NAME_RE = re.compile(r'\{name = "([^"]+)",\s*draw')


class MapCard:
    """One parsed map card: its identity plus everything the checks read.

    The keep-list lives in `scriptzoneCallback`, which sits BEFORE the giant
    `objectJSONs` terrain blob. We scope GUID extraction to that head region so
    a terrain piece's own GUID can never be mistaken for a whitelist entry.
    """

    def __init__(self, obj, deck_guid=None):
        self.guid = obj.get("GUID") or "??????"
        self.name = obj.get("Nickname") or obj.get("Name") or ""
        self.deck_guid = deck_guid
        self.tags = list(obj.get("Tags") or [])
        lua = obj.get("LuaScript", "") or ""
        self.lua = lua

        self.zones_version = "v2" if MAP_ZONES_V2_MARKER in lua else "v1"

        head, _, tail = lua.partition("objectJSONs")
        self.keep_guids = (set(_KEEP_GUID_RE.findall(head))
                           | set(_KEEP_GUID_V2_RE.findall(head)))
        self.gm_excludes = set(_GM_EXCLUDE_RE.findall(head))
        m = _ZONE_SCALE_RE.search(lua)
        self.zone_scale = re.sub(r"\s+", "", m.group(1)) if m else None
        # Terrain lives in the blob region only.
        self.terrain_count = len(_TERRAIN_GUID_RE.findall(tail))
        self.terrain_guids = set(_TERRAIN_GUID_VALUE_RE.findall(tail))
        self.terrain_entries = _OBJECTJSON_ENTRY_RE.findall(tail)
        sm = _NAME_SUFFIX_RE.match(self.name)
        self.suffix = sm.group(1) if sm and sm.group(1) else None

    @property
    def where(self) -> str:
        return f"card {self.guid} {self.name!r}"


class MapContext:
    def __init__(self, cards, scene_guids, startmenu_lua=None, inventory_issues=None,
                 require_map_tags=False, manifest_path=MAP_MANIFEST):
        self.cards = cards
        self.scene_guids = scene_guids
        self.startmenu_lua = startmenu_lua
        self.inventory_issues = inventory_issues or []
        self.require_map_tags = require_map_tags
        self.manifest_path = manifest_path

    def matrix_referenced_guids(self):
        """GUIDs referenced by startMenu's mission matrix tables, or None if the
        lua isn't available."""
        lua = self.startmenu_lua
        if not lua:
            return None
        try:
            seg = lua[lua.index("deploymentMatrixDecks"):lua.index("deploymentCardSourceDeckByGuid")]
        except ValueError:
            return None
        return set(_MATRIX_GUID_RE.findall(seg))

    def deploy_zone_names(self):
        """All deployment-zone names defined in startMenu, or None if unavailable."""
        if not self.startmenu_lua:
            return None
        return set(_DEPLOY_ZONE_NAME_RE.findall(self.startmenu_lua))


def _is_map_card(obj) -> bool:
    lua = obj.get("LuaScript", "") or ""
    return "scriptzoneCallback" in lua or "function loadMap" in lua


def load_map_manifest(path=MAP_MANIFEST):
    """Return (rows, issues) from the authoritative map deck/card CSV."""
    path = Path(path)
    if not path.exists():
        return [], [Issue(ERROR, "map manifest", f"missing {path}")]

    rows, issues, seen_cards = [], [], set()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = MAP_MANIFEST_COLUMNS - set(reader.fieldnames or [])
        if missing:
            return [], [Issue(ERROR, "map manifest",
                              f"missing column(s): {', '.join(sorted(missing))}")]
        for line_no, raw in enumerate(reader, 2):
            row = {key: (raw.get(key) or "").strip() for key in MAP_MANIFEST_COLUMNS}
            where = f"map manifest line {line_no}"
            if not _GUID_RE.fullmatch(row["deck_guid"]):
                issues.append(Issue(ERROR, where, f"invalid deck_guid {row['deck_guid']!r}"))
            if not _GUID_RE.fullmatch(row["card_guid"]):
                issues.append(Issue(ERROR, where, f"invalid card_guid {row['card_guid']!r}"))
            if row["card_guid"] in seen_cards:
                issues.append(Issue(ERROR, where,
                                    f"duplicate card_guid {row['card_guid']}"))
            if not row["map_creator_tag"].startswith(MAP_CREATOR_TAG_PREFIX + "_"):
                issues.append(Issue(ERROR, where,
                                    f"invalid map_creator_tag {row['map_creator_tag']!r}"))
            seen_cards.add(row["card_guid"])
            rows.append(row)
    return rows, issues


def build_context(object_states, require_map_tags=False, manifest_path=MAP_MANIFEST) -> MapContext:
    scene_guids, objects_by_guid, detected_cards = set(), {}, {}

    def walk(objs, parent_deck_guid=None):
        for o in objs:
            g = o.get("GUID")
            if g:
                scene_guids.add(g)
                objects_by_guid.setdefault(g, []).append((o, parent_deck_guid))
            if _is_map_card(o):
                detected_cards[g] = MapCard(o, parent_deck_guid)
            if "ContainedObjects" in o:
                child_parent = g if o.get("Name") == "Deck" else parent_deck_guid
                walk(o["ContainedObjects"], child_parent)

    walk(object_states)
    manifest_rows, inventory_issues = load_map_manifest(manifest_path)
    cards, manifest_card_guids = [], set()

    for row in manifest_rows:
        deck_guid, card_guid = row["deck_guid"], row["card_guid"]
        manifest_card_guids.add(card_guid)
        deck_matches = objects_by_guid.get(deck_guid, [])
        if not deck_matches:
            inventory_issues.append(Issue(ERROR, "map manifest",
                                          f"deck {deck_guid} is missing from the save"))
        elif not any(obj.get("Name") == "Deck" for obj, _ in deck_matches):
            inventory_issues.append(Issue(ERROR, "map manifest",
                                          f"deck {deck_guid} is not a Deck object"))

        card = detected_cards.get(card_guid)
        if not card:
            inventory_issues.append(Issue(ERROR, "map manifest",
                                          f"map card {card_guid} is missing or has no map loader script"))
            continue
        cards.append(card)
        if card.deck_guid != deck_guid:
            inventory_issues.append(Issue(ERROR, card.where,
                                          f"manifest assigns it to deck {deck_guid}, "
                                          f"but save contains it in {card.deck_guid or 'no deck'}"))
        if row["card_name"] and card.name != row["card_name"]:
            inventory_issues.append(Issue(WARN, card.where,
                                          f"manifest card_name is {row['card_name']!r}"))
        if row["map_creator_tag"] not in card.tags:
            inventory_issues.append(Issue(ERROR, card.where,
                                          f"manifest map_creator_tag is {row['map_creator_tag']!r}, "
                                          f"but save tags are {card.tags}"))
        deck_obj = deck_matches[0][0] if deck_matches else None
        deck_name = (deck_obj.get("Nickname") or deck_obj.get("Name") or "") if deck_obj else ""
        if row["deck_name"] and deck_name and deck_name != row["deck_name"]:
            inventory_issues.append(Issue(WARN, f"deck {deck_guid} {deck_name!r}",
                                          f"manifest deck_name is {row['deck_name']!r}"))

    for guid, card in detected_cards.items():
        if guid not in manifest_card_guids:
            inventory_issues.append(Issue(ERROR, card.where,
                                          "map card exists in the save but is missing from map_manifest.csv"))

    startmenu = STARTMENU_LUA.read_text(encoding="utf-8") if STARTMENU_LUA.exists() else None
    return MapContext(cards, scene_guids, startmenu, inventory_issues,
                      require_map_tags, Path(manifest_path))


# --- Check registry ---------------------------------------------------------

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


@check
def manifest_inventory_consistent(ctx):
    """The CSV is authoritative and must match the map decks/cards in the save."""
    yield from ctx.inventory_issues


@check
def publishing_tags_present(ctx):
    """Test/release builds require the generic map tag and a creator tag."""
    if not ctx.require_map_tags:
        return
    for card in ctx.cards:
        missing = []
        if REQUIRED_MAP_TAG not in card.tags:
            missing.append(REQUIRED_MAP_TAG)
        if not any(tag.startswith(MAP_CREATOR_TAG_PREFIX) for tag in card.tags):
            missing.append(MAP_CREATOR_TAG_PREFIX + "*")
        if missing:
            yield Issue(ERROR, card.where,
                        f"missing required publishing tag(s): {', '.join(missing)}; "
                        f"current tags: {card.tags}")


@check
def keep_list_complete(ctx):
    """Every card must whitelist every required GUID."""
    for card in ctx.cards:
        for guid, label in REQUIRED_KEEP_GUIDS.items():
            if guid not in card.keep_guids:
                yield Issue(ERROR, card.where,
                            f"wipe whitelist is missing {guid} ({label})")


@check
def kept_mats_exist(ctx):
    """A whitelisted mat that no longer exists means it was renamed/removed —
    the whitelist now protects nothing and Clear would delete the live mat."""
    for guid in sorted(KEEP_GUIDS_MUST_EXIST):
        if guid not in ctx.scene_guids:
            label = REQUIRED_KEEP_GUIDS.get(guid, "")
            yield Issue(ERROR, "scene",
                        f"whitelisted mat {guid} ({label}) is not present in the save")


@check
def zone_scale_uniform(ctx):
    """All cards should wipe the same area; a mismatch under-clears or reaches
    off-table."""
    by_scale = {}
    for card in ctx.cards:
        by_scale.setdefault(card.zone_scale, []).append(card.guid)
    if len(by_scale) > 1:
        detail = "; ".join(
            f"{scale or 'MISSING'} <- {', '.join(guids)}"
            for scale, guids in by_scale.items()
        )
        yield Issue(WARN, "scene", f"zoneScale differs across cards: {detail}")


@check
def terrain_not_empty(ctx):
    """A map card with no baked terrain spawns an empty board on Load Map."""
    for card in ctx.cards:
        if card.terrain_count == 0:
            yield Issue(ERROR, card.where, "objectJSONs contains no terrain pieces")


@check
def gm_exclude_present(ctx):
    """The per-object opt-out keeps user-tagged objects from being wiped."""
    for card in ctx.cards:
        if EXPECTED_GM_EXCLUDE not in card.gm_excludes:
            yield Issue(WARN, card.where,
                        f'wipe does not honor GM-notes "{EXPECTED_GM_EXCLUDE}" opt-out')


@check
def terrain_guid_collisions(ctx):
    """A baked terrain piece must not reuse a whitelisted GUID (the wipe would
    then spare that terrain, or two objects would claim the mat's GUID). A clash
    with a live scene object is softer — TTS reassigns the GUID on spawn — but
    still worth surfacing."""
    for card in ctx.cards:
        for g in sorted(card.terrain_guids):
            if g in REQUIRED_KEEP_GUIDS:
                yield Issue(ERROR, card.where,
                            f"baked terrain reuses whitelisted GUID {g} ({REQUIRED_KEEP_GUIDS[g]})")
            elif g in ctx.scene_guids:
                yield Issue(WARN, card.where,
                            f"baked terrain GUID {g} collides with a live scene object "
                            "(TTS will reassign it on spawn)")


@check
def mission_matrix_resolves(ctx):
    """Every GUID referenced by startMenu's mission matrix must exist, and every
    map card should be referenced by it (else it's unreachable in-game)."""
    refs = ctx.matrix_referenced_guids()
    if refs is None:
        return
    for g in sorted(refs):
        if g not in ctx.scene_guids:
            yield Issue(ERROR, "startMenu matrix",
                        f"references GUID {g} but no such deck/card exists in the save")
    for card in ctx.cards:
        if card.guid not in refs:
            yield Issue(WARN, card.where,
                        "not referenced by any deploymentMatrixDecks/randomDeploymentDecks entry")


@check
def name_suffix_resolves(ctx):
    """The Load Map auto-deploy keys off the card name's ' - <zone>' suffix, so
    that suffix must match a real deployment-zone name."""
    zones = ctx.deploy_zone_names()
    if zones is None:
        return
    for card in ctx.cards:
        if not card.suffix:
            yield Issue(WARN, card.where,
                        "name has no ' - <zone>' suffix; Load Map auto-deploy will not select a zone")
        elif card.suffix not in zones:
            yield Issue(WARN, card.where,
                        f'name suffix "{card.suffix}" matches no deployment zone; auto-deploy will not fire')


@check
def objectjsons_parseable(ctx):
    """Each baked terrain entry must be valid JSON (a truncated/corrupt import
    breaks Load Map), and a card far below the median piece count is suspicious."""
    counts = sorted(len(c.terrain_entries) for c in ctx.cards)
    median = counts[len(counts) // 2] if counts else 0
    for card in ctx.cards:
        bad = sum(1 for e in card.terrain_entries if not _is_json(e))
        if bad:
            yield Issue(ERROR, card.where,
                        f"{bad} of {len(card.terrain_entries)} baked terrain entries are not valid JSON")
        if median and len(card.terrain_entries) < max(1, median // 4):
            yield Issue(WARN, card.where,
                        f"only {len(card.terrain_entries)} terrain pieces (median {median}) "
                        "— possible truncated import")


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


@check
def loadmap_is_hookable(ctx):
    """compile.py injects the Load Map -> menu notification at the loadMap
    signature. If a re-imported card changed that signature, injection would
    silently no-op and the deployment auto-select would stop firing."""
    for card in ctx.cards:
        if "function loadMap" in card.lua and not LOADMAP_SIGNATURE_RE.search(card.lua):
            yield Issue(WARN, card.where,
                        "loadMap signature not in the expected form; "
                        "compile-time Load Map hook will be skipped")


# --- Runner / reporting ------------------------------------------------------

def validate(object_states, require_map_tags=False, manifest_path=MAP_MANIFEST):
    """Return (issues, ctx). issues is sorted ERROR-first."""
    ctx = build_context(object_states, require_map_tags, manifest_path)
    issues = []
    for fn in CHECKS:
        issues.extend(fn(ctx))
    issues.sort(key=lambda i: 0 if i.level == ERROR else 1)
    return issues, ctx


def split_by_zone_version(ctx):
    """Return (v2_cards, v1_cards) split on the Map Zones marker."""
    v2 = [c for c in ctx.cards if c.zones_version == "v2"]
    v1 = [c for c in ctx.cards if c.zones_version != "v2"]
    return v2, v1


def report_zone_versions(ctx):
    """Print the Map Zones v1/v2 breakdown. Read-only; never fails a build."""
    v2, v1 = split_by_zone_version(ctx)
    total = len(ctx.cards)
    print(f"  Map Zones: {term.green(str(len(v2)) + ' on v2')}, "
          f"{(term.yellow if v1 else term.dim)(str(len(v1)) + ' on v1')} of {total}.")
    if v1:
        for c in v1:
            print(term.yellow(f"    v1  {c.guid}  {c.name}"))
        print(term.dim("    (run the upgrade command to migrate v1 -> v2)"))


def report(issues, ctx) -> tuple:
    """Print a grouped, colored report. Return (n_errors, n_warnings)."""
    n_err = sum(1 for i in issues if i.level == ERROR)
    n_warn = len(issues) - n_err

    if not issues:
        print(term.green(f"  All {len(ctx.cards)} map cards passed validation."))
        return 0, 0

    for issue in issues:
        tag = term.red("ERROR") if issue.level == ERROR else term.yellow("WARN ")
        print(f"  {tag} [{issue.where}] {issue.message}")
    return n_err, n_warn


def main():
    parser = argparse.ArgumentParser(description="Validate manifest-listed map cards.")
    parser.add_argument("--require-map-tags", action="store_true",
                        help="Require each map card to have 'map' and a 'map_crt*' tag.")
    args = parser.parse_args()
    json_file = Path(__file__).parent.parent / "TTSJSON" / "ftc_base.json"
    if not json_file.exists():
        print(term.red(f"ERROR: {json_file} not found."))
        return 1
    save = json.loads(json_file.read_text(encoding="utf-8"))
    issues, ctx = validate(save.get("ObjectStates", []),
                           require_map_tags=args.require_map_tags)
    print(term.bold(f"Validating {len(ctx.cards)} manifest-listed map cards in {json_file.name}..."))
    n_err, n_warn = report(issues, ctx)
    report_zone_versions(ctx)
    print(term.dim(f"  {n_err} error(s), {n_warn} warning(s)."))
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
