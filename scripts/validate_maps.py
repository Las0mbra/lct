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
from collections import Counter, namedtuple
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

# Mission objective marker tags expected inside each baked map payload. This is
# intentionally advisory: missing markers make deployment/objective automation
# suspect, but should not block test/release builds while legacy maps are being
# cleaned up.
OBJECTIVE_HOME_TAGS = ("obj_home_red", "obj_home_blue")
OBJECTIVE_NEUTRAL_TAG = "obj_neutral"
OBJECTIVE_CENTER_TAGS = ("obj_center", "obj_central")
OBJECTIVE_TRIANGLE_TAG = "obj_triangle"
OBJECTIVE_CENTER1_TAGS = ("obj_center1", "obj_center 1", "obj_center_1")
OBJECTIVE_CENTER2_TAGS = ("obj_center2", "obj_center 2", "obj_center_2")

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
# Logical card name "... - Sweeping Engagement" -> "Sweeping Engagement"
# (mirrors the Lua suffix match the Load Map auto-deploy uses).
_NAME_SUFFIX_RE = re.compile(r'^.*-\s*(.*?)\s*$')

# startMenu.ttslua holds the mission matrix and the deployment-zone names that a
# couple of cross-checks need. Read best-effort; checks skip if it isn't found.
STARTMENU_LUA = Path(__file__).parent.parent / "TTSLUA" / "startMenu.ttslua"
MAP_MANIFEST = Path(__file__).parent.parent / "data" / "map_manifest.csv"
# The one canonical load/clear machinery every map card's head must match (the
# text before its `objectJSONs = {` blob). Foreign loaders (e.g. the Battlemaster
# system) are normalized to this -- see scripts/normalize_map_card.py.
MAP_CARD_MACHINERY = Path(__file__).parent.parent / "data" / "map_card_machinery.lua"
MAP_MANIFEST_COLUMNS = {"deck_guid", "deck_name", "card_guid", "card_name", "map_creator_tag", "map_type_tag", "creator_display", "eligible"}
REQUIRED_MAP_TAG = "map"
MAP_CREATOR_TAG_PREFIX = "map_crt"
MAP_TYPE_TAG_PREFIX = "map_type"
# Thematic (narrative/crusade) maps don't use the standard mission objective
# layout, so the advisory objective-marker-tag check is skipped for them.
MAP_TYPE_THEMATIC_TAG = "map_type_thematic"
MAP_CREATOR_DISPLAY_NAMES = {
    "map_crt_cr5sh": "Cra5hNatural",
    "map_crt_belgium": "Team Belgium",
    "map_crt_izar": "Izar",
    "map_crt_battlemaster_bttf": "BTTF",
    "map_crt_battlemaster_bttf_ruins": "Battlemaster - BTTF Ruins",
    "map_crt_battlemaster_armageddon_desert": "Battlemaster - Desert",
    "map_crt_alvaricus": "Alvaricus",
    "map_crt_zim": "Zim",
    "map_crt_t5s2": "T5S2",
}
LAYOUT_ART_DECK_GUID = "fb4b5d"
# A matchup map source may be a Deck or a standard Bag. Bags are the preferred
# form: a Deck collapses once it drops below two cards, but a Bag keeps its GUID
# and never collapses, so cards can be taken/returned by GUID across generations.
MAP_SOURCE_CONTAINER_NAMES = {"Deck", "Bag"}
# Containers whose map cards are a self-contained game-mode pool (e.g. Combat
# Patrol), NOT part of the Generate Mission map system. Cards held directly in
# one of these are skipped by map-card detection entirely: they are not in
# map_manifest.csv, carry no publishing tags, and are never wired into the
# disposition matrix, so the standard checks would (correctly, for a real map)
# flag them. They still ship their own canonical load/clear machinery; they are
# simply outside the validated map inventory.
MAP_VALIDATION_IGNORE_CONTAINER_GUIDS = {
    "fdf6e7": "Combat Patrol Maps",
}
_GUID_RE = re.compile(r"^[0-9a-fA-F]{6}$")
_MATRIX_GUID_RE = re.compile(r'guid\s*=\s*"([0-9a-fA-F]{6})"')
_MATCHUP_KEY_RE = re.compile(r'\["([1-5]_[1-5])"\]')
_DEPLOY_ZONE_NAME_RE = re.compile(r'\{name = "([^"]+)",\s*draw')
# A container/source-bag GUID appears as `guid = "xxxxxx"` at the start of a line
# (deck level); a card GUID is inline as `{guid = "xxxxxx"`. Anchoring to the line
# start picks out only the deck/bag GUIDs.
_DECK_LEVEL_GUID_RE = re.compile(r'^\s*guid\s*=\s*"([0-9a-fA-F]{6})"', re.M)
_ALL_MATRIX_KEYS = {f"{red}_{blue}" for red in range(1, 6) for blue in range(1, 6)}


def map_logical_name(name: str) -> str:
    """Remove a recognized trailing creator credit from a visible map name."""
    name = (name or "").rstrip()
    folded = name.casefold()
    for creator in MAP_CREATOR_DISPLAY_NAMES.values():
        suffix = f" - {creator}"
        if folded.endswith(suffix.casefold()):
            return name[:-len(suffix)].rstrip()
    return name


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
        self.gmnotes = obj.get("GMNotes") or ""
        lua = obj.get("LuaScript", "") or ""
        self.lua = lua
        # The load/clear machinery is everything before the terrain blob.
        self.head = lua.split("objectJSONs = {", 1)[0]

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
        self.objective_tag_counts = objective_tag_counts(self.terrain_entries)
        self.logical_name = map_logical_name(self.name)
        sm = _NAME_SUFFIX_RE.match(self.logical_name)
        self.suffix = sm.group(1) if sm and sm.group(1) else None

    @property
    def where(self) -> str:
        return f"card {self.guid} {self.name!r}"

    @property
    def is_thematic(self) -> bool:
        """Narrative/crusade map outside the competitive Generate Mission system."""
        return MAP_TYPE_THEMATIC_TAG in self.tags


def objective_tag_counts(terrain_entries):
    """Count map-object tags in spawned terrain payloads.

    ChildObjects are present on the table with their parent, so they count.
    Alternate States are ignored because only one state exists at a time and
    counting them can make an incomplete map look complete by accident.
    """
    counts = Counter()

    def visit(obj):
        if not isinstance(obj, dict):
            return
        for tag in obj.get("Tags") or []:
            counts[tag] += 1
        for child in obj.get("ChildObjects") or []:
            visit(child)

    for entry in terrain_entries:
        try:
            visit(json.loads(entry))
        except (json.JSONDecodeError, ValueError):
            continue
    return counts


class MapContext:
    def __init__(self, cards, scene_guids, startmenu_lua=None, inventory_issues=None,
                 require_map_tags=False, manifest_path=MAP_MANIFEST, layout_art_cards=None):
        self.cards = cards
        self.scene_guids = scene_guids
        self.startmenu_lua = startmenu_lua
        self.inventory_issues = inventory_issues or []
        self.require_map_tags = require_map_tags
        self.manifest_path = manifest_path
        self.layout_art_cards = layout_art_cards or []

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

    def deployment_matrix_keys(self):
        """Disposition matchup keys with dedicated map sources, or None."""
        lua = self.startmenu_lua
        if not lua:
            return None
        try:
            seg = lua[lua.index("deploymentMatrixDecks"):lua.index("randomDeploymentDecks")]
        except ValueError:
            return None
        return set(_MATCHUP_KEY_RE.findall(seg))

    def deploy_zone_names(self):
        """All deployment-zone names defined in startMenu, or None if unavailable."""
        if not self.startmenu_lua:
            return None
        return set(_DEPLOY_ZONE_NAME_RE.findall(self.startmenu_lua))

    def _segment(self, start, end):
        """Text between two startMenu markers, or None if either is missing."""
        lua = self.startmenu_lua
        if not lua:
            return None
        try:
            return lua[lua.index(start):lua.index(end, lua.index(start))]
        except ValueError:
            return None

    def matrix_deck_guids(self):
        """Source-bag GUIDs wired into the disposition matrix, or None."""
        seg = self._segment("deploymentMatrixDecks", "randomDeploymentDecks")
        return set(_DECK_LEVEL_GUID_RE.findall(seg)) if seg is not None else None

    def random_deck_guids(self):
        """Source-bag GUIDs registered for return-to-bag / random selection, or None."""
        seg = self._segment("randomDeploymentDecks", "deploymentCardSourceDeckByGuid")
        return set(_DECK_LEVEL_GUID_RE.findall(seg)) if seg is not None else None

    def game_mode_object_guids(self):
        """GUIDs shown/hidden with game mode and snapshotted for BACK TO SELECTION,
        or None if the list isn't found."""
        seg = self._segment("GAME_MODE_OBJECTS = {", "function hideStartupMapCards")
        return set(_MATRIX_GUID_RE.findall(seg)) if seg is not None else None


def map_statistics(ctx):
    """High-signal inventory statistics shared by reports and compile summaries."""
    creator_counts = Counter()
    type_counts = Counter()
    for card in ctx.cards:
        for tag in card.tags:
            if tag.startswith(MAP_CREATOR_TAG_PREFIX + "_"):
                creator_counts[MAP_CREATOR_DISPLAY_NAMES.get(tag, tag)] += 1
            elif tag.startswith(MAP_TYPE_TAG_PREFIX + "_"):
                type_counts[tag.removeprefix(MAP_TYPE_TAG_PREFIX + "_")] += 1

    payloads = [len(card.terrain_entries) for card in ctx.cards]
    matchup_keys = ctx.deployment_matrix_keys()
    return {
        "cards": len(ctx.cards),
        "logical_layouts": len({card.logical_name.casefold() for card in ctx.cards}),
        "source_containers": len({card.deck_guid for card in ctx.cards if card.deck_guid}),
        "creators": creator_counts,
        "map_types": type_counts,
        "mapped_matchups": len(matchup_keys) if matchup_keys is not None else None,
        "total_matchups": 25,
        "terrain_min": min(payloads) if payloads else 0,
        "terrain_max": max(payloads) if payloads else 0,
        "terrain_total": sum(payloads),
    }


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
            if not row["map_type_tag"].startswith(MAP_TYPE_TAG_PREFIX + "_"):
                issues.append(Issue(ERROR, where,
                                    f"invalid map_type_tag {row['map_type_tag']!r}"))
            if not row["creator_display"]:
                issues.append(Issue(ERROR, where, "creator_display is empty"))
            if row["eligible"] not in ("true", "false"):
                issues.append(Issue(ERROR, where,
                                    f"eligible must be 'true' or 'false', got {row['eligible']!r}"))
            seen_cards.add(row["card_guid"])
            rows.append(row)

    # creator_display must be consistent for a given creator tag, or one creator
    # would split into two filter buttons later.
    display_by_tag = {}
    for row in rows:
        tag, disp = row["map_creator_tag"], row["creator_display"]
        if not disp:
            continue
        if tag in display_by_tag and display_by_tag[tag] != disp:
            issues.append(Issue(ERROR, "map manifest",
                                f"creator_display for {tag} is inconsistent: "
                                f"{display_by_tag[tag]!r} vs {disp!r}"))
        else:
            display_by_tag.setdefault(tag, disp)

    # Every deck x layout must keep at least one eligible map, or generation can
    # no longer fill that slot. Layout is the number before " - " in the name,
    # matching the Lua deploymentCardLayoutIndex parse.
    layouts_seen, eligible_seen = set(), set()
    for row in rows:
        m = re.search(r"\s(\d+)\s*-", row["card_name"])
        if not m:
            continue
        slot = (row["deck_guid"], int(m.group(1)))
        layouts_seen.add(slot)
        if row["eligible"] == "true":
            eligible_seen.add(slot)
    for deck_guid, layout in sorted(layouts_seen - eligible_seen):
        issues.append(Issue(ERROR, "map manifest",
                            f"deck {deck_guid} layout {layout} has no eligible map"))

    return rows, issues


def build_context(object_states, require_map_tags=False, manifest_path=MAP_MANIFEST) -> MapContext:
    scene_guids, objects_by_guid, detected_cards = set(), {}, {}

    def walk(objs, parent_deck_guid=None):
        for o in objs:
            g = o.get("GUID")
            if g:
                scene_guids.add(g)
                objects_by_guid.setdefault(g, []).append((o, parent_deck_guid))
            if _is_map_card(o) and parent_deck_guid not in MAP_VALIDATION_IGNORE_CONTAINER_GUIDS:
                detected_cards[g] = MapCard(o, parent_deck_guid)
            if "ContainedObjects" in o:
                child_parent = g if o.get("Name") in MAP_SOURCE_CONTAINER_NAMES else parent_deck_guid
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
        elif not any(obj.get("Name") in MAP_SOURCE_CONTAINER_NAMES for obj, _ in deck_matches):
            inventory_issues.append(Issue(ERROR, "map manifest",
                                          f"deck {deck_guid} is not a Deck or Bag object"))

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
            inventory_issues.append(Issue(ERROR, card.where,
                                          f"manifest card_name is {row['card_name']!r}"))
        if row["map_creator_tag"] not in card.tags:
            inventory_issues.append(Issue(ERROR, card.where,
                                          f"manifest map_creator_tag is {row['map_creator_tag']!r}, "
                                          f"but save tags are {card.tags}"))
        if row["map_type_tag"] not in card.tags:
            inventory_issues.append(Issue(ERROR, card.where,
                                          f"manifest map_type_tag is {row['map_type_tag']!r}, "
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

    layout_art_cards = []
    layout_matches = objects_by_guid.get(LAYOUT_ART_DECK_GUID, [])
    if not layout_matches:
        inventory_issues.append(Issue(ERROR, "layout art deck",
                                      f"deck {LAYOUT_ART_DECK_GUID} is missing from the save"))
    else:
        layout_deck = layout_matches[0][0]
        if layout_deck.get("Name") != "Deck":
            inventory_issues.append(Issue(ERROR, "layout art deck",
                                          f"{LAYOUT_ART_DECK_GUID} is not a Deck object"))
        for card in layout_deck.get("ContainedObjects", []):
            layout_art_cards.append({
                "guid": card.get("GUID") or "??????",
                "name": card.get("Nickname") or card.get("Name") or "",
            })

    startmenu = STARTMENU_LUA.read_text(encoding="utf-8") if STARTMENU_LUA.exists() else None
    return MapContext(cards, scene_guids, startmenu, inventory_issues,
                      require_map_tags, Path(manifest_path), layout_art_cards)


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
    """Test/release builds require generic, creator, and map-type tags."""
    if not ctx.require_map_tags:
        return
    for card in ctx.cards:
        missing = []
        if REQUIRED_MAP_TAG not in card.tags:
            missing.append(REQUIRED_MAP_TAG)
        if not any(tag.startswith(MAP_CREATOR_TAG_PREFIX) for tag in card.tags):
            missing.append(MAP_CREATOR_TAG_PREFIX + "*")
        if not any(tag.startswith(MAP_TYPE_TAG_PREFIX + "_") for tag in card.tags):
            missing.append(MAP_TYPE_TAG_PREFIX + "_*")
        if missing:
            yield Issue(ERROR, card.where,
                        f"missing required publishing tag(s): {', '.join(missing)}; "
                        f"current tags: {card.tags}")


@check
def creator_name_suffix_matches_tag(ctx):
    """Visible map-card credit must agree with its authoritative creator tag."""
    for card in ctx.cards:
        creator_tags = [tag for tag in card.tags if tag.startswith(MAP_CREATOR_TAG_PREFIX + "_")]
        if len(creator_tags) != 1:
            yield Issue(ERROR, card.where,
                        f"expected exactly one creator tag, found {creator_tags}")
            continue
        creator_tag = creator_tags[0]
        display_name = MAP_CREATOR_DISPLAY_NAMES.get(creator_tag)
        if not display_name:
            yield Issue(ERROR, card.where,
                        f"creator tag {creator_tag!r} has no configured display name")
            continue
        expected_suffix = f" - {display_name}"
        if not card.name.endswith(expected_suffix):
            yield Issue(ERROR, card.where,
                        f"nickname must end with {expected_suffix!r} for creator tag {creator_tag}")


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
def objective_marker_tags_present(ctx):
    """Advisory check for mission/objective marker tags inside spawned terrain.

    Compile always reports these warnings, but they never block builds. Thematic
    maps use bespoke objective layouts, so they are skipped entirely.
    """
    for card in ctx.cards:
        if card.is_thematic:
            continue
        counts = card.objective_tag_counts
        missing = []
        missing_count = 0

        missing_home = [tag for tag in OBJECTIVE_HOME_TAGS if counts[tag] < 1]
        if missing_home:
            missing_count += len(missing_home)
            missing.append("missing " + ", ".join(missing_home))

        if counts[OBJECTIVE_NEUTRAL_TAG] < 2:
            missing_count += 2 - counts[OBJECTIVE_NEUTRAL_TAG]
            missing.append(f"needs at least 2 {OBJECTIVE_NEUTRAL_TAG} "
                           f"(found {counts[OBJECTIVE_NEUTRAL_TAG]})")

        center_count = sum(counts[tag] for tag in OBJECTIVE_CENTER_TAGS)
        triangle_count = counts[OBJECTIVE_TRIANGLE_TAG]
        center1_count = sum(counts[tag] for tag in OBJECTIVE_CENTER1_TAGS)
        center2_count = sum(counts[tag] for tag in OBJECTIVE_CENTER2_TAGS)
        if not (center_count >= 1 or triangle_count >= 2
                or (center1_count >= 1 and center2_count >= 1)):
            missing_count += 1
            missing.append("needs obj_center/obj_central, or 2 obj_triangle, "
                           "or an obj_center1 + obj_center2 pair")

        if missing:
            relevant = {
                tag: counts[tag]
                for tag in (
                    *OBJECTIVE_HOME_TAGS,
                    OBJECTIVE_NEUTRAL_TAG,
                    *OBJECTIVE_CENTER_TAGS,
                    OBJECTIVE_TRIANGLE_TAG,
                    *OBJECTIVE_CENTER1_TAGS,
                    *OBJECTIVE_CENTER2_TAGS,
                )
                if counts[tag]
            }
            found = ", ".join(f"{tag}={count}" for tag, count in relevant.items()) or "none"
            yield Issue(WARN, card.where,
                        f"missing {missing_count} obj_tags: " + "; ".join(missing)
                        + f"; found {found}")


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
    map card must be reachable through a matrix source bag.

    Historical startMenu tables list individual card GUIDs. Runtime generation now
    prefers the live contents of each source bag, so imported cards only need to be
    inside a source bag whose GUID is present in deploymentMatrixDecks.
    """
    refs = ctx.matrix_referenced_guids()
    matrix_decks = ctx.matrix_deck_guids()
    if refs is None:
        return
    for g in sorted(refs):
        if g not in ctx.scene_guids:
            yield Issue(ERROR, "startMenu matrix",
                        f"references GUID {g} but no such deck/card exists in the save")
    # Unreachable maps are tolerated in dev builds but block test/release.
    unreachable_level = ERROR if ctx.require_map_tags else WARN
    for card in ctx.cards:
        reachable_by_card_ref = card.guid in refs
        reachable_by_source_bag = matrix_decks is not None and card.deck_guid in matrix_decks
        if not reachable_by_card_ref and not reachable_by_source_bag:
            yield Issue(unreachable_level, card.where,
                        "not referenced by card GUID and not inside a deploymentMatrixDecks source bag")


@check
def layout_art_names_resolve(ctx):
    """Each logical map name needs exactly one matching card in the helper-art deck."""
    helper_by_name = {}
    for card in ctx.layout_art_cards:
        helper_by_name.setdefault(card["name"].strip().casefold(), []).append(card)

    maps_by_name = {}
    competitive_names = set()
    for card in ctx.cards:
        normalized = card.logical_name.strip().casefold()
        maps_by_name.setdefault(normalized, card.logical_name.strip())
        if not card.is_thematic:
            competitive_names.add(normalized)

    # Missing layout art breaks Generate Mission / Random Layout, so block
    # test/release builds; warn only in dev. Thematic-only names don't drive
    # Generate Mission, so a missing helper there is advisory regardless.
    missing_level = ERROR if ctx.require_map_tags else WARN
    for normalized, map_name in sorted(maps_by_name.items(), key=lambda item: item[1]):
        matches = helper_by_name.get(normalized, [])
        if not matches:
            level = missing_level if normalized in competitive_names else WARN
            yield Issue(level, "layout art deck",
                        f"no helper card matches map name {map_name!r}")
        elif len(matches) > 1:
            guids = ", ".join(card["guid"] for card in matches)
            yield Issue(ERROR, "layout art deck",
                        f"multiple helper cards match map name {map_name!r}: {guids}")


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


@check
def loader_card_not_self_excluded(ctx):
    """A map loader card tagged with the wipe opt-out spares itself from every
    wipe, so it (and stale copies) never clear off the mat -- the exact BTTF bug.
    The opt-out is for terrain/markers, never the loader card."""
    for card in ctx.cards:
        if card.gmnotes == EXPECTED_GM_EXCLUDE:
            yield Issue(ERROR, card.where,
                        f'loader card has GMNotes "{EXPECTED_GM_EXCLUDE}"; the wipe '
                        "will spare it, so it never clears off the mat")


@check
def card_head_is_canonical(ctx):
    """Every card must use the one canonical load/clear machinery. A card whose
    head differs runs a foreign load system (the Battlemaster cards did) and will
    behave differently from the rest -- normalize it. Enforced on test/release."""
    if not ctx.require_map_tags:
        return
    template = _read_machinery_template()
    if template is None:
        yield Issue(ERROR, "map machinery",
                    f"canonical head template missing: {MAP_CARD_MACHINERY}")
        return
    for card in ctx.cards:
        if card.head != template:
            yield Issue(ERROR, card.where,
                        f"load/clear machinery differs from {MAP_CARD_MACHINERY.name}; "
                        "run normalize_map_card.py to standardize it")


@check
def source_bag_in_matrix(ctx):
    """Every source bag must be wired into the disposition matrix, else its maps
    are unreachable via Generate Mission. Enforced on test/release."""
    if not ctx.require_map_tags:
        return
    guids = ctx.matrix_deck_guids()
    if guids is None:
        return
    for deck_guid in sorted({c.deck_guid for c in ctx.cards if c.deck_guid}):
        if deck_guid not in guids:
            yield Issue(ERROR, f"deck {deck_guid}",
                        "source bag is not in deploymentMatrixDecks; its maps are "
                        "unreachable via Generate Mission")


@check
def source_bag_in_random_decks(ctx):
    """Every source bag must be registered in randomDeploymentDecks, which powers
    return-to-bag on disposition change and card-source resolution. test/release."""
    if not ctx.require_map_tags:
        return
    guids = ctx.random_deck_guids()
    if guids is None:
        return
    for deck_guid in sorted({c.deck_guid for c in ctx.cards if c.deck_guid}):
        if deck_guid not in guids:
            yield Issue(ERROR, f"deck {deck_guid}",
                        "source bag is not in randomDeploymentDecks; its cards won't "
                        "return to it when the disposition changes")


@check
def source_bag_in_game_mode_objects(ctx):
    """Every source bag must be in GAME_MODE_OBJECTS so it hides until game mode is
    chosen AND its JSON (with contained cards) is snapshotted for BACK TO
    SELECTION. test/release."""
    if not ctx.require_map_tags:
        return
    guids = ctx.game_mode_object_guids()
    if guids is None:
        return
    for deck_guid in sorted({c.deck_guid for c in ctx.cards if c.deck_guid}):
        if deck_guid not in guids:
            yield Issue(ERROR, f"deck {deck_guid}",
                        "source bag is not in GAME_MODE_OBJECTS; it won't hide "
                        "pre-game and won't be restored by BACK TO SELECTION")


@check
def matchup_matrix_complete(ctx):
    """All 25 disposition matchups must have a dedicated source, so generation
    never falls back to a random mission. test/release."""
    if not ctx.require_map_tags:
        return
    keys = ctx.deployment_matrix_keys()
    if keys is None:
        return
    missing = sorted(_ALL_MATRIX_KEYS - keys)
    if missing:
        yield Issue(ERROR, "startMenu matrix",
                    f"matchup(s) without a dedicated deck (random-mission fallback): "
                    f"{', '.join(missing)}")


_MACHINERY_TEMPLATE = False  # sentinel: not yet read


def _read_machinery_template():
    """Canonical head text, read once. None if the template file is absent."""
    global _MACHINERY_TEMPLATE
    if _MACHINERY_TEMPLATE is False:
        _MACHINERY_TEMPLATE = (MAP_CARD_MACHINERY.read_text(encoding="utf-8")
                               if MAP_CARD_MACHINERY.exists() else None)
    return _MACHINERY_TEMPLATE


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
