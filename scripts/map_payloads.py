"""Shared helpers for extracted map terrain payloads.

Cards in ftc_base.json keep the loader machinery head in `LuaScript`; the heavy
`objectJSONs = { ... }` terrain blob lives in data/maps/<card_guid>.lua and is
re-injected by compile.py.
"""

import csv
from pathlib import Path

ROOT = Path(__file__).parent.parent
PAYLOAD_DIR = ROOT / "data" / "maps"
MANIFEST = ROOT / "data" / "map_manifest.csv"
TERRAIN_MARKER = "objectJSONs = {"

# Map-loader pools outside data/map_manifest.csv.
EXTRA_MAP_POOL_CONTAINER_GUIDS = {"fdf6e7"}  # Combat Patrol Maps


def payload_path(guid, payload_dir=PAYLOAD_DIR):
    return Path(payload_dir) / f"{guid}.lua"


def split_lua(lua):
    idx = (lua or "").find(TERRAIN_MARKER)
    if idx == -1:
        return None
    return lua[:idx], lua[idx:]


def read_payload(guid, payload_dir=PAYLOAD_DIR):
    path = payload_path(guid, payload_dir)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write_payload(guid, payload, payload_dir=PAYLOAD_DIR):
    path = payload_path(guid, payload_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(payload)
    return path


def strip_card_to_payload(card, payload_dir=PAYLOAD_DIR):
    """Write a card's inline terrain payload and strip LuaScript to its head.

    Returns True when a payload was extracted, False when the card was already
    stripped or has no terrain marker.
    """
    lua = card.get("LuaScript", "") or ""
    split = split_lua(lua)
    if split is None:
        return False
    head, payload = split
    guid = card.get("GUID")
    if not guid:
        raise ValueError("cannot write map payload for card without GUID")
    write_payload(guid, payload, payload_dir)
    card["LuaScript"] = head
    return True


def remove_payload(guid, payload_dir=PAYLOAD_DIR):
    path = payload_path(guid, payload_dir)
    if path.exists():
        path.unlink()
        return True
    return False


def load_manifest_rows(path=MANIFEST):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def manifest_card_guids(path=MANIFEST):
    return {row["card_guid"].strip() for row in load_manifest_rows(path)}


def walk_objects(objs, parent_container_guid=None):
    for obj in objs or []:
        yield obj, parent_container_guid
        child_parent = obj.get("GUID") if obj.get("Name") in {"Deck", "Bag"} else parent_container_guid
        yield from walk_objects(obj.get("ContainedObjects") or [], child_parent)
        states = obj.get("States") or {}
        if isinstance(states, dict):
            yield from walk_objects(states.values(), parent_container_guid)


def expected_payload_guids(save, manifest_guids=None):
    manifest_guids = set(manifest_guids or ())
    expected = set()
    for obj, parent_guid in walk_objects(save.get("ObjectStates", [])):
        guid = obj.get("GUID")
        if not guid:
            continue
        lua = obj.get("LuaScript", "") or ""
        if guid in manifest_guids or parent_guid in EXTRA_MAP_POOL_CONTAINER_GUIDS:
            if "function loadMap" in lua or split_lua(lua) is not None:
                expected.add(guid)
    return expected
