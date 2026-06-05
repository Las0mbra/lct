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

# --- Model ------------------------------------------------------------------

ERROR = "ERROR"
WARN = "WARN"

Issue = namedtuple("Issue", ["level", "where", "message"])

# A card is identified by its wipe/spawn machinery rather than by GUID, so newly
# imported cards are picked up automatically.
_KEEP_GUID_RE = re.compile(r'getGUID\(\)\s*~=\s*"([0-9a-fA-F]{6})"')
_GM_EXCLUDE_RE = re.compile(r'getGMNotes\(\)\s*~=\s*"([^"]+)"')
_ZONE_SCALE_RE = re.compile(r'zoneScale\s*=\s*\{([^}]*)\}')
_TERRAIN_GUID_RE = re.compile(r'"GUID"\s*:')


class MapCard:
    """One parsed map card: its identity plus everything the checks read.

    The keep-list lives in `scriptzoneCallback`, which sits BEFORE the giant
    `objectJSONs` terrain blob. We scope GUID extraction to that head region so
    a terrain piece's own GUID can never be mistaken for a whitelist entry.
    """

    def __init__(self, obj):
        self.guid = obj.get("GUID") or "??????"
        self.name = obj.get("Nickname") or obj.get("Name") or ""
        lua = obj.get("LuaScript", "") or ""

        head, _, tail = lua.partition("objectJSONs")
        self.keep_guids = set(_KEEP_GUID_RE.findall(head))
        self.gm_excludes = set(_GM_EXCLUDE_RE.findall(head))
        m = _ZONE_SCALE_RE.search(lua)
        self.zone_scale = re.sub(r"\s+", "", m.group(1)) if m else None
        # Terrain pieces are counted in the blob region only.
        self.terrain_count = len(_TERRAIN_GUID_RE.findall(tail))

    @property
    def where(self) -> str:
        return f"card {self.guid} {self.name!r}"


class MapContext:
    def __init__(self, cards, scene_guids):
        self.cards = cards
        self.scene_guids = scene_guids


def _is_map_card(obj) -> bool:
    lua = obj.get("LuaScript", "") or ""
    return "scriptzoneCallback" in lua or "function loadMap" in lua


def build_context(object_states) -> MapContext:
    cards, scene_guids = [], set()

    def walk(objs):
        for o in objs:
            g = o.get("GUID")
            if g:
                scene_guids.add(g)
            if _is_map_card(o):
                cards.append(MapCard(o))
            if "ContainedObjects" in o:
                walk(o["ContainedObjects"])

    walk(object_states)
    return MapContext(cards, scene_guids)


# --- Check registry ---------------------------------------------------------

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


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


# --- Runner / reporting ------------------------------------------------------

def validate(object_states):
    """Return (issues, ctx). issues is sorted ERROR-first."""
    ctx = build_context(object_states)
    issues = []
    for fn in CHECKS:
        issues.extend(fn(ctx))
    issues.sort(key=lambda i: 0 if i.level == ERROR else 1)
    return issues, ctx


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
    json_file = Path(__file__).parent.parent / "TTSJSON" / "ftc_base.json"
    if not json_file.exists():
        print(term.red(f"ERROR: {json_file} not found."))
        return 1
    save = json.loads(json_file.read_text(encoding="utf-8"))
    issues, ctx = validate(save.get("ObjectStates", []))
    print(term.bold(f"Validating {len(ctx.cards)} map cards in {json_file.name}..."))
    n_err, n_warn = report(issues, ctx)
    print(term.dim(f"  {n_err} error(s), {n_warn} warning(s)."))
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
