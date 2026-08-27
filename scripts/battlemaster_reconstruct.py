#!/usr/bin/env python3
"""Pure-Python Battlemaster lite-payload to TTS object reconstruction.

This is a deliberately close port of the reconstruction section in
TTSLUA/battlemasterDynamicSpawner.ttslua.  Keeping the transformation here lets
the release map cards be generated without asking Tabletop Simulator to fetch,
decode, reconstruct, and then serialize hundreds of large Lua strings.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable


BATTLEMAT_MESH_URL = (
    "https://steamusercontent-a.akamaihd.net/ugc/879750610978796176/"
    "4A5A65543B98BCFBF57E910D06EC984208223D38/"
)
BATTLEMAT_POS_Y = -10.13
TERRAIN_PLATE_MESH_BASE_URL = "https://assets.battlemaster.online/tts/terrain-plates/v1/"
TERRAIN_PLATE_DIFFUSE_URL = (
    "https://steamusercontent-a.akamaihd.net/ugc/14317051875219621305/"
    "1CE22364BD2806ED074668B14EC64816FDB94AFF/"
)

# Footprint state layouts are a theme-family contract, not a cosmetic mesh
# toggle.  Ordinary Battlemaster themes expose the two assetbundle terrains
# directly (rugged as state 1, smooth as state 2).  LCT themes add their custom
# bordered floor as state 1 and move those same terrains to states 2 and 3.
FOOTPRINT_PROFILE_BATTLEMASTER = "battlemaster-two-state"
FOOTPRINT_PROFILE_LCT = "lct-three-state"
FOOTPRINT_PROFILES = frozenset({FOOTPRINT_PROFILE_BATTLEMASTER, FOOTPRINT_PROFILE_LCT})

TERRAIN_ASSETS = (
    {
        "id": "big-rect",
        "plate": "04-bigrect",
        "width": 11.503,
        "height": 7.003,
        "rugged": "https://steamusercontent-a.akamaihd.net/ugc/17340806108804505934/4B46C3DBA9709342C6038E6C339E9183773F7F4F/",
        "smooth": "https://steamusercontent-a.akamaihd.net/ugc/18109999757297310215/5DB2EDC94302F2260A40CDE398054AB73C583B2D/",
    },
    {
        "id": "long-line",
        "plate": "03-longline",
        "width": 10.003,
        "height": 2.503,
        "rugged": "https://steamusercontent-a.akamaihd.net/ugc/14084050877596722482/ED735D1BA2BA036645A039BBE2884DC6097D52FF/",
        "smooth": "https://steamusercontent-a.akamaihd.net/ugc/12173066766016705494/E81DD809081B33CC73B332024FC1D4672A2EE2BC/",
    },
    {
        "id": "short-line",
        "plate": "01-shortline",
        "width": 6.003,
        "height": 2.003,
        "rugged": "https://steamusercontent-a.akamaihd.net/ugc/15633617285222415204/5306AA649D2877AFEF7FEBDFCE3052F6E9977E98/",
        "smooth": "https://steamusercontent-a.akamaihd.net/ugc/16079218023307560393/A11A66EA4B73E650059F86573FCA12C91492E2B0/",
    },
    {
        "id": "small-rect",
        "plate": "02-smallrect",
        "width": 6.003,
        "height": 4.003,
        "rugged": "https://steamusercontent-a.akamaihd.net/ugc/12322865955445680032/0919B948C303AE084AD0661B3EDE36FCCBF28FCF/",
        "smooth": "https://steamusercontent-a.akamaihd.net/ugc/16918139172926584908/8C6BC64D270CD20FEEA73D40FBD80633CC72A532/",
    },
    {
        "id": "triangle",
        "plate": "05-triangle",
        "width": 11.503,
        "height": 8.003,
        "rugged": "https://steamusercontent-a.akamaihd.net/ugc/13344184635215212518/9E3478CBEB46A6B7D03864CCC680D7E37F14B660/",
        "smooth": "https://steamusercontent-a.akamaihd.net/ugc/10828923269080544043/F6E563E60C9A956892D734DEA30B43B38BB83B50/",
    },
)

OBJECTIVE_TAGS = {
    "hb": "obj_home_blue",
    "hr": "obj_home_red",
    "n": "obj_neutral",
    "c": "obj_center",
    "c1": "obj_center1",
    "c2": "obj_center2",
    "t": "obj_triangle",
}


class ReconstructionError(ValueError):
    """The compact catalogs or payload have an invalid shape."""


@dataclass(frozen=True)
class ReconstructionResult:
    objects: list[dict[str, Any]]
    spawned: int
    skipped: int

    def compact_json_entries(self) -> list[str]:
        return [
            json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            for obj in self.objects
        ]


class GuidAllocator:
    """Allocate repeatable six-hex TTS GUIDs for one map."""

    def __init__(self, seed: str, reserved: Iterable[str] = ()):
        self.seed = seed
        self.used = {str(value).lower() for value in reserved if value}
        self.counter = 0

    def next(self) -> str:
        while True:
            candidate = hashlib.sha1(
                f"{self.seed}|terrain|{self.counter}".encode("utf-8")
            ).hexdigest()[:6]
            self.counter += 1
            if candidate not in self.used:
                self.used.add(candidate)
                return candidate


def _is_table(value: Any) -> bool:
    return isinstance(value, (dict, list))


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _number_optional(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _index(value: Any) -> int | None:
    number = _number_optional(value)
    if number is None or number < 0 or not number.is_integer():
        return None
    return int(number)


def _at(values: Any, zero_index: Any) -> Any:
    index = _index(zero_index)
    if not isinstance(values, list) or index is None or index >= len(values):
        return None
    return values[index]


def _item(values: Any, index: int, default: Any = None) -> Any:
    if not isinstance(values, list) or index < 0 or index >= len(values):
        return default
    return values[index]


def round6(value: Any) -> float:
    """Match Lua's math.floor(value * 1e6 + 0.5) rounding exactly."""
    return math.floor(_number(value) * 1_000_000 + 0.5) / 1_000_000


def normalize_rotation(value: Any) -> float:
    return round6(_number(value) % 360)


def rotate_point(x: Any, y: Any, degrees: Any) -> dict[str, float]:
    radians = _number(degrees) * math.pi / 180
    cosine, sine = math.cos(radians), math.sin(radians)
    x_value, y_value = _number(x), _number(y)
    return {
        "x": x_value * cosine - y_value * sine,
        "y": x_value * sine + y_value * cosine,
    }


class Reconstructor:
    def __init__(
        self,
        template_catalog: dict[str, Any],
        theme_catalog: dict[str, Any],
        guid_seed: str,
        *,
        footprint_profile: str = FOOTPRINT_PROFILE_BATTLEMASTER,
        include_battlemat: bool = True,
        reserved_guids: Iterable[str] = (),
    ):
        if not isinstance(template_catalog, dict):
            raise ReconstructionError("template catalog must be an object")
        if not isinstance(theme_catalog, dict):
            raise ReconstructionError("theme catalog must be an object")
        if footprint_profile not in FOOTPRINT_PROFILES:
            raise ReconstructionError(f"unknown footprint profile {footprint_profile!r}")
        self.template_catalog = template_catalog
        self.theme_catalog = theme_catalog
        self.footprint_profile = footprint_profile
        self.include_battlemat = include_battlemat
        self.guids = GuidAllocator(guid_seed, reserved_guids)
        self.templates_by_id = self._build_template_lookup()
        self.theme_by_ref, self.theme_by_hint = self._build_theme_mapping_lookup()

    def _build_template_lookup(self) -> dict[str, list[Any]]:
        lookup: dict[str, list[Any]] = {}
        for template in self.template_catalog.get("t") or []:
            if isinstance(template, list) and template:
                lookup[str(template[0])] = template
        return lookup

    @staticmethod
    def _hint_key(hint: Any) -> str | None:
        if not isinstance(hint, list):
            return None
        first = str(_item(hint, 0, "") or "").lower()
        second = str(_item(hint, 1, "") or "")
        third = str(_item(hint, 2, "") or "")
        return f"{first}|{second}|{third}"

    def _build_theme_mapping_lookup(self) -> tuple[dict[str, list[Any]], dict[str, list[Any]]]:
        by_ref: dict[str, list[Any]] = {}
        by_hint: dict[str, list[Any]] = {}
        for mapping in self.theme_catalog.get("m") or []:
            if not isinstance(mapping, list):
                continue
            part_index = _item(mapping, 0)
            part_ref = _at(self.theme_catalog.get("p"), part_index)
            if part_ref is not None:
                by_ref[str(part_ref)] = mapping
            key = self._hint_key(_at(self.theme_catalog.get("q"), part_index))
            if key is not None:
                by_hint[key] = mapping
        return by_ref, by_hint

    def _mapping_for_part(self, catalog_part_index: Any) -> list[Any] | None:
        part_ref = _at(self.template_catalog.get("p"), catalog_part_index)
        if part_ref is not None and str(part_ref) in self.theme_by_ref:
            return self.theme_by_ref[str(part_ref)]
        key = self._hint_key(_at(self.template_catalog.get("q"), catalog_part_index))
        return self.theme_by_hint.get(key) if key is not None else None

    @staticmethod
    def _find_terrain_asset(width: Any, height: Any) -> dict[str, Any] | None:
        width_value, height_value = _number(width), _number(height)
        for asset in TERRAIN_ASSETS:
            if abs(width_value - asset["width"]) < 0.02 and abs(height_value - asset["height"]) < 0.02:
                return asset
        return None

    def _theme_url(self, index: Any) -> str:
        value = _at(self.theme_catalog.get("u"), index)
        return "" if value is None else str(value)

    def _footprint_diffuse_url(self) -> str:
        floor = self.theme_catalog.get("t")
        if isinstance(floor, list):
            url = self._theme_url(_item(floor, 0))
            if url:
                return url
        return TERRAIN_PLATE_DIFFUSE_URL

    @staticmethod
    def _objective_tags(instance: Any) -> list[str]:
        code = _item(instance, 5, "")
        return [OBJECTIVE_TAGS[token] for token in str(code or "").split("+") if token in OBJECTIVE_TAGS]

    def _common_object(self, name: str, transform: dict[str, float], nickname: str = "") -> dict[str, Any]:
        return {
            "GUID": self.guids.next(),
            "Name": name,
            "Transform": transform,
            "Nickname": nickname,
            "Description": "",
            "GMNotes": "",
            "AltLookAngle": {"x": 0, "y": 0, "z": 0},
            "ColorDiffuse": {"r": 1, "g": 1, "b": 1},
            "LayoutGroupSortIndex": 0,
            "Value": 0,
            "Locked": True,
            "Grid": True,
            "Snap": True,
            "IgnoreFoW": False,
            "MeasureMovement": False,
            "DragSelectable": True,
            "Autoraise": True,
            "Sticky": True,
            "Tooltip": True,
            "GridProjection": False,
            "HideWhenFaceDown": False,
            "Hands": False,
            "Tags": [],
            "LuaScript": "",
            "LuaScriptState": "",
            "XmlUI": "",
        }

    @staticmethod
    def _transform(
        pos_x: Any,
        pos_y: Any,
        pos_z: Any,
        rot_y: Any,
        scale: dict[str, Any] | None = None,
        extra_rotation: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        scale = scale or {"x": 1, "y": 1, "z": 1}
        rotation = extra_rotation or {}
        return {
            "posX": round6(pos_x),
            "posY": round6(pos_y),
            "posZ": round6(pos_z),
            "rotX": round6(rotation.get("x", 0)),
            "rotY": round6(rot_y),
            "rotZ": round6(rotation.get("z", 0)),
            "scaleX": round6(scale.get("x", 1)),
            "scaleY": round6(scale.get("y", 1)),
            "scaleZ": round6(scale.get("z", 1)),
        }

    @staticmethod
    def _shader() -> dict[str, Any]:
        return {
            "SpecularColor": {"r": 1, "g": 1, "b": 1},
            "SpecularIntensity": 0,
            "SpecularSharpness": 2,
            "FresnelStrength": 0,
        }

    def _build_battlemat(self) -> dict[str, Any] | None:
        battlemat = self.theme_catalog.get("b")
        if not isinstance(battlemat, list):
            return None
        diffuse_url = self._theme_url(_item(battlemat, 1))
        if not diffuse_url:
            return None
        width = _number(_item(battlemat, 2), 60)
        height = _number(_item(battlemat, 3), 44)
        obj = self._common_object(
            "Custom_Model",
            self._transform(0, BATTLEMAT_POS_Y, 0, 0, {"x": width / 36, "y": 1.06, "z": height / 36.046}),
        )
        obj.update({
            "GridProjection": True,
            "DragSelectable": False,
            "Tooltip": False,
            "Interactable": False,
            "Tags": ["battlemaster_battlemat"],
            "CustomMesh": {
                "MeshURL": BATTLEMAT_MESH_URL,
                "DiffuseURL": diffuse_url,
                "NormalURL": "",
                "ColliderURL": "",
                "Convex": True,
                "MaterialIndex": 3,
                "TypeIndex": 4,
                "CustomShader": self._shader(),
                "CastShadows": True,
            },
        })
        return obj

    def _apply_tags(self, obj: dict[str, Any], tags: list[str]) -> dict[str, Any]:
        if not tags:
            return obj
        obj["Tags"] = list(tags)
        states = obj.get("States")
        if isinstance(states, dict):
            for state in states.values():
                if isinstance(state, dict):
                    state["Tags"] = list(tags)
        return obj

    def _build_terrain_asset_state(
        self,
        asset: dict[str, Any],
        style: str,
        transform: dict[str, float],
    ) -> dict[str, Any]:
        state = self._common_object("Custom_Assetbundle", copy.deepcopy(transform))
        state["CustomAssetbundle"] = {
            "AssetbundleURL": str(asset[style]),
            "AssetbundleSecondaryURL": "",
            "MaterialIndex": 0,
            "TypeIndex": 0,
            "LoopingEffectIndex": 0,
        }
        return state

    def _build_terrain_plate(self, instance: list[Any], template: list[Any]) -> dict[str, Any] | None:
        width = _number(_item(template, 1), 1)
        height = _number(_item(template, 2), 1)
        asset = self._find_terrain_asset(width, height)
        if asset is None:
            return None
        center_x = _number(_item(instance, 1))
        center_y = _number(_item(instance, 2))
        rotation = _number(_item(instance, 3))
        mirror_raw = _item(instance, 4)
        mirror_code = _number(mirror_raw) if isinstance(mirror_raw, (int, float)) and not isinstance(mirror_raw, bool) else 0
        pivot_local = {"x": -width / 2, "y": -height / 2}
        if mirror_code == 1:
            pivot_local = {"x": width / 2, "y": -height / 2}
        if mirror_code == 2:
            pivot_local = {"x": -width / 2, "y": height / 2}
        pivot = rotate_point(pivot_local["x"], pivot_local["y"], rotation)
        extra_rotation = {"x": 180 if mirror_code == 2 else 0, "z": 180 if mirror_code == 1 else 0}
        pos_y = 1.02 if mirror_code in (1, 2) else 0.980388
        transform = self._transform(
            center_x + pivot["x"], pos_y, center_y + pivot["y"],
            normalize_rotation(360 - rotation), {"x": 1, "y": 1, "z": 1}, extra_rotation,
        )
        rugged = self._build_terrain_asset_state(asset, "rugged", transform)
        smooth = self._build_terrain_asset_state(asset, "smooth", transform)

        if self.footprint_profile == FOOTPRINT_PROFILE_LCT:
            obj = self._common_object("Custom_Model", transform)
            obj["CustomMesh"] = {
                "MeshURL": (
                    f"{TERRAIN_PLATE_MESH_BASE_URL}"
                    f"battlemaster-rugged-{asset['plate']}-5mm-border.obj"
                ),
                "DiffuseURL": self._footprint_diffuse_url(),
                "NormalURL": "",
                "ColliderURL": "",
                "Convex": False,
                "MaterialIndex": 3,
                "TypeIndex": 4,
                "CustomShader": self._shader(),
                "CastShadows": True,
            }
            obj["States"] = {"2": rugged, "3": smooth}
        else:
            # Legacy/qq2.json -- a live TTS capture of Battlemaster's own spawner
            # output (GMNotes="BattlemasterSpawned" on every piece) -- confirms the
            # ordinary Battlemaster ordering across all 5 known footprint shapes:
            # rugged is the top-level/default state and smooth is state 2. See
            # BattlemasterReconstructionTest.test_terrain_assets_match_live_battlemaster_two_state_capture.
            obj = rugged
            obj["States"] = {"2": smooth}
        return self._apply_tags(obj, self._objective_tags(instance))

    @staticmethod
    def _mapping_options(mapping: list[Any]) -> dict[str, Any]:
        kind = str(_item(mapping, 1, "") or "")
        candidate = _item(mapping, 6) if kind == "m" else _item(mapping, 4) if kind == "a" else None
        return candidate if isinstance(candidate, dict) else {}

    def _part_hint(self, part: list[Any]) -> list[Any] | None:
        hint = _at(self.template_catalog.get("q"), _item(part, 0))
        return hint if isinstance(hint, list) else None

    def _part_label(self, part: list[Any]) -> str:
        hint = self._part_hint(part)
        if hint is not None and _item(hint, 0) is not None and str(_item(hint, 0)) != "":
            return str(_item(hint, 0))
        part_ref = _at(self.template_catalog.get("p"), _item(part, 0))
        if part_ref is not None and str(part_ref) != "":
            return str(part_ref)
        return "Battlemaster Ruin Part"

    def _apply_part_metadata(self, obj: dict[str, Any], part: list[Any]) -> dict[str, Any]:
        label = self._part_label(part)
        material_code = str(_item(part, 5, "") or "")
        if material_code == "l":
            material = "Light"
        elif material_code == "d":
            material = "Dense"
        else:
            material = "Light" if "light" in label.lower() else "Dense"
        obj.update({"Nickname": label, "Description": material, "Tags": [label]})
        return obj

    @staticmethod
    def _option_scale(options: dict[str, Any]) -> dict[str, float]:
        scale = options.get("sc")
        if isinstance(scale, list):
            return {
                "x": _number(_item(scale, 0), 1),
                "y": _number(_item(scale, 1), 1),
                "z": _number(_item(scale, 2), 1),
            }
        return {"x": 1, "y": 1, "z": 1}

    @staticmethod
    def _option_origin(options: dict[str, Any]) -> dict[str, float]:
        origin = options.get("o")
        if isinstance(origin, list):
            return {"x": _number(_item(origin, 0)), "y": _number(_item(origin, 1))}
        return {"x": 0, "y": 0}

    def _normalize_nested_list(self, value: Any, depth: int) -> list[dict[str, Any]]:
        if not _is_table(value) or depth > 6:
            return []
        if isinstance(value, dict) and (isinstance(value.get("Name"), str) or isinstance(value.get("GUID"), str)):
            normalized = self._normalize_nested_state(value, depth)
            return [normalized] if normalized is not None else []
        if isinstance(value, list):
            return [
                normalized
                for child in value
                if (normalized := self._normalize_nested_state(child, depth)) is not None
            ]
        result = []
        for key in sorted(value, key=str):
            child = value[key]
            if isinstance(child, dict):
                normalized = self._normalize_nested_state(child, depth)
                if normalized is not None:
                    result.append(normalized)
        return result

    def _normalize_nested_state(self, value: Any, depth: int) -> dict[str, Any] | None:
        if not isinstance(value, dict) or depth > 6:
            return None
        obj = copy.deepcopy(value)
        obj.update({"GUID": self.guids.next(), "GMNotes": "", "Locked": True})
        child_source = obj.get("ChildObjects")
        if not _is_table(child_source) and _is_table(obj.get("ContainedObjects")):
            child_source = obj.get("ContainedObjects")
        children = self._normalize_nested_list(child_source, depth + 1)
        if children:
            obj["ChildObjects"] = children
        else:
            obj.pop("ChildObjects", None)
        obj.pop("ContainedObjects", None)
        states = obj.get("States")
        if isinstance(states, dict):
            normalized_states = {}
            for key in sorted(states, key=str):
                normalized = self._normalize_nested_state(states[key], depth + 1)
                if normalized is not None:
                    normalized_states[str(key)] = normalized
            obj["States"] = normalized_states
        return obj

    def _children_from_options(self, options: dict[str, Any]) -> list[dict[str, Any]] | None:
        for key in ("ch", "ChildObjects", "childObjects", "ContainedObjects", "containedObjects"):
            children = self._normalize_nested_list(options.get(key), 1)
            if children:
                return children
        return None

    def _normalize_alternate(self, source: Any, base: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(source, dict):
            return None
        obj = copy.deepcopy(source)
        obj.update({
            "GUID": self.guids.next(),
            "Transform": copy.deepcopy(base["Transform"]),
            "Nickname": base.get("Nickname", ""),
            "Description": base.get("Description", ""),
            "Tags": copy.deepcopy(base.get("Tags") or []),
            "GMNotes": "",
            "Locked": True,
            "LuaScript": "",
            "LuaScriptState": "",
            "XmlUI": "",
        })
        child_source = obj.get("ChildObjects")
        if not _is_table(child_source) and _is_table(obj.get("ContainedObjects")):
            child_source = obj.get("ContainedObjects")
        children = self._normalize_nested_list(child_source, 1)
        if children:
            obj["ChildObjects"] = children
        else:
            obj.pop("ChildObjects", None)
        obj.pop("ContainedObjects", None)
        obj.pop("States", None)
        if obj.get("Name") is None or obj.get("Name") is False:
            obj["Name"] = base.get("Name")
        for key, fallback in (
            ("AltLookAngle", {"x": 0, "y": 0, "z": 0}),
            ("ColorDiffuse", {"r": 1, "g": 1, "b": 1}),
        ):
            if obj.get(key) is None or obj.get(key) is False:
                obj[key] = copy.deepcopy(base.get(key, fallback))
        for key in ("LayoutGroupSortIndex", "Value"):
            number = _number_optional(obj.get(key))
            if number is None:
                number = _number_optional(base.get(key))
            # TTS deserializes these as integers; a bare JSON float like 0.0
            # (e.g. "States.2.LayoutGroupSortIndex") raises a Lua load error and
            # aborts the terrain spawn loop partway through, which is why only
            # the plates spawned before the first alternate state show up.
            obj[key] = int(round(number)) if number is not None else 0
        for key in (
            "Grid", "Snap", "IgnoreFoW", "MeasureMovement", "DragSelectable",
            "Autoraise", "Sticky", "Tooltip", "GridProjection", "HideWhenFaceDown", "Hands",
        ):
            if key not in obj or obj[key] is None:
                obj[key] = base.get(key)
        return obj

    def _apply_options(self, obj: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
        children = self._children_from_options(options)
        if children is not None:
            obj["ChildObjects"] = children
        state_sources = options.get("st")
        if isinstance(state_sources, dict):
            states = {}
            for key in sorted(state_sources, key=str):
                state = self._normalize_alternate(state_sources[key], obj)
                if state is not None:
                    states[str(key)] = state
            if states:
                obj["States"] = states
        return obj

    def _build_ruin_part(self, instance: list[Any], part: list[Any], mapping: list[Any]) -> dict[str, Any] | None:
        center_x, center_y = _number(_item(instance, 1)), _number(_item(instance, 2))
        layout_rotation = _number(_item(instance, 3))
        local_x, local_y = _number(_item(part, 1)), _number(_item(part, 2))
        part_rotation = _number(_item(part, 3))
        options = self._mapping_options(mapping)
        origin = self._option_origin(options)
        rotated_origin = rotate_point(origin["x"], origin["y"], part_rotation)
        world_local = rotate_point(local_x + rotated_origin["x"], local_y + rotated_origin["y"], layout_rotation)
        pos_x, pos_z = center_x + world_local["x"], center_y + world_local["y"]
        pos_y = _number(options.get("y"), 1.08)
        rot_y = normalize_rotation(360 - layout_rotation - part_rotation + _number(options.get("ro")))
        extra_rotation = {"x": _number(options.get("rx")), "z": _number(options.get("rz"))}
        transform = self._transform(pos_x, pos_y, pos_z, rot_y, self._option_scale(options), extra_rotation)
        kind = str(_item(mapping, 1, "") or "")
        if kind == "m":
            mesh_url = self._theme_url(_item(mapping, 2))
            if not mesh_url:
                return None
            obj = self._apply_part_metadata(self._common_object("Custom_Model", transform, "Battlemaster Ruin Part"), part)
            obj["CustomMesh"] = {
                "MeshURL": mesh_url,
                "DiffuseURL": self._theme_url(_item(mapping, 3)),
                "NormalURL": self._theme_url(_item(mapping, 4)),
                "ColliderURL": self._theme_url(_item(mapping, 5)),
                "Convex": options.get("cv") is True,
                "MaterialIndex": int(_number(options.get("mi"), 3)),
                "TypeIndex": int(_number(options.get("ti"), 4)),
                "CustomShader": self._shader(),
                "CastShadows": options.get("cs") is not False,
            }
            return self._apply_options(obj, options)
        if kind == "a":
            asset_url = self._theme_url(_item(mapping, 2))
            if not asset_url:
                return None
            obj = self._apply_part_metadata(self._common_object("Custom_Assetbundle", transform, "Battlemaster Ruin Part"), part)
            obj["CustomAssetbundle"] = {
                "AssetbundleURL": asset_url,
                "AssetbundleSecondaryURL": self._theme_url(_item(mapping, 3)),
                "MaterialIndex": 0,
                "TypeIndex": 0,
                "LoopingEffectIndex": 0,
            }
            return self._apply_options(obj, options)
        return None

    def reconstruct(self, lite_payload: dict[str, Any]) -> ReconstructionResult:
        if not isinstance(lite_payload, dict) or not isinstance(lite_payload.get("i"), list):
            raise ReconstructionError("layout lite payload must include i[] instances")
        objects: list[dict[str, Any]] = []
        spawned = skipped = 0
        if self.include_battlemat:
            battlemat = self._build_battlemat()
            if battlemat is not None:
                objects.append(battlemat)
                spawned += 1
        template_ids = lite_payload.get("t")
        templates = self.template_catalog.get("t")
        for instance in lite_payload["i"]:
            if not isinstance(instance, list):
                skipped += 1
                continue
            if _is_table(template_ids):
                template_id = _at(template_ids, _item(instance, 0))
                template = self.templates_by_id.get(str(template_id)) if template_id is not None else None
            else:
                template = _at(templates, _item(instance, 0))
            if not isinstance(template, list):
                skipped += 1
                continue
            plate = self._build_terrain_plate(instance, template)
            if plate is None:
                skipped += 1
            else:
                objects.append(plate)
                spawned += 1
            parts = _item(template, 3, [])
            if not isinstance(parts, list):
                parts = []
            for part in parts:
                if not isinstance(part, list):
                    skipped += 1
                    continue
                mapping = self._mapping_for_part(_item(part, 0))
                ruin = self._build_ruin_part(instance, part, mapping) if mapping is not None else None
                if ruin is None:
                    skipped += 1
                else:
                    objects.append(ruin)
                    spawned += 1
        return ReconstructionResult(objects=objects, spawned=spawned, skipped=skipped)


def reconstruct_objects(
    template_catalog: dict[str, Any],
    theme_catalog: dict[str, Any],
    lite_payload: dict[str, Any],
    guid_seed: str,
    *,
    footprint_profile: str = FOOTPRINT_PROFILE_BATTLEMASTER,
    include_battlemat: bool = True,
    reserved_guids: Iterable[str] = (),
) -> ReconstructionResult:
    return Reconstructor(
        template_catalog,
        theme_catalog,
        guid_seed,
        footprint_profile=footprint_profile,
        include_battlemat=include_battlemat,
        reserved_guids=reserved_guids,
    ).reconstruct(lite_payload)
