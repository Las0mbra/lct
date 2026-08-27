#!/usr/bin/env python3
"""Fetch Battlemaster maps and install them as canonical static LCT cards.

The command is preview-only unless --write is supplied.  It fetches the public
Battlemaster catalogs, reconstructs terrain in Python, validates the complete
prospective map inventory, and only then replaces the selected creator sets in
TTSJSON/ftc_base.json, data/map_manifest.csv, and data/maps/*.lua.

Examples:
  python3 scripts/sync_battlemaster_maps.py --desert
  python3 scripts/sync_battlemaster_maps.py --desert --bttf --write
  python3 scripts/sync_battlemaster_maps.py --all --snapshot-out /tmp/bm.json
  python3 scripts/sync_battlemaster_maps.py --all --snapshot-in /tmp/bm.json --write
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import battlemaster_reconstruct as reconstruction
import import_battlemaster_static_maps as legacy


API_BASE = "https://battlemaster.onrender.com"
OWNER = "8a72d680-3166-44e1-aa3c-2f7264f92202"
TARGET_PATH = ROOT / "TTSJSON" / "ftc_base.json"
MANIFEST_PATH = ROOT / "data" / "map_manifest.csv"
PAYLOAD_DIR = ROOT / "data" / "maps"
MACHINERY_PATH = ROOT / "data" / "map_card_machinery.lua"
SNAPSHOT_SCHEMA_VERSION = 1
EXPECTED_PAIR_COUNT = 15
EXPECTED_LAYOUTS_PER_PACK = 45
GUID_RE = re.compile(r"^[0-9a-f]{6}$")


class SyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class ThemeSlice:
    theme_id: str
    slots: tuple[int, ...]
    label: str


@dataclass(frozen=True)
class PackSpec:
    key: str
    creator_tag: str
    creator_display: str
    themes: tuple[ThemeSlice, ...]
    footprint_profile: str = reconstruction.FOOTPRINT_PROFILE_BATTLEMASTER


ALL_SLOTS = (1, 2, 3)
PACKS: dict[str, PackSpec] = {
    "bttf-ruins": PackSpec(
        "bttf-ruins",
        "map_crt_battlemaster_bttf_ruins",
        "Battlemaster - BTTF Ruins",
        (ThemeSlice("tts-theme-0c82349e-6c8d-4ef6-95ba-4ee3c2d6a5a5", ALL_SLOTS, "BTTF Ruins"),),
    ),
    "desert": PackSpec(
        "desert",
        "map_crt_battlemaster_armageddon_desert",
        "Battlemaster - Desert",
        (ThemeSlice("tts-theme-6c414c7a-9827-48cf-a89e-aa8ddff66491", ALL_SLOTS, "Armageddon Desert"),),
    ),
    "bttf": PackSpec(
        "bttf",
        "map_crt_battlemaster_bttf",
        "BTTF",
        (ThemeSlice("tts-theme-grimdark-calibrated-v1", ALL_SLOTS, "Grimdark Ruins"),),
    ),
    "armageddon-ruins": PackSpec(
        "armageddon-ruins",
        "map_crt_battlemaster_armageddon_ruins",
        "Battlemaster - Armageddon Ruins",
        (ThemeSlice("tts-theme-7b9218bb-b614-4225-9789-570836525e6a", ALL_SLOTS, "Armageddon Ruins"),),
    ),
    "lct-pack-1": PackSpec(
        "lct-pack-1",
        "map_crt_lct1",
        "LCT - Pack 1",
        (
            ThemeSlice("tts-theme-36235f46-c306-4738-b33d-cca12bee9cfc", (1,), "LCT - Ice Colony"),
            ThemeSlice("tts-theme-5d7d19f2-af5d-4c1c-b2b2-d839b3a8ea8f", (2,), "LCT - Lava Temple v2.1"),
            ThemeSlice("tts-theme-5933b001-4acd-453e-af37-acf01356429b", (3,), "LCT - Mars Base"),
        ),
        footprint_profile=reconstruction.FOOTPRINT_PROFILE_LCT,
    ),
}
ALL_FOUR_KEYS = ("bttf-ruins", "desert", "bttf", "armageddon-ruins")


@dataclass(frozen=True)
class MapRecord:
    pack: PackSpec
    theme: ThemeSlice
    layout: dict[str, Any]
    lite_payload: dict[str, Any]

    @property
    def pair(self) -> str:
        return str(self.layout.get("forcePairKey") or "")

    @property
    def slot(self) -> int:
        return legacy.layout_slot(self.layout)

    @property
    def identity(self) -> tuple[str, str, int]:
        return self.pack.creator_tag, self.pair, self.slot


@dataclass
class InstallPlan:
    target: dict[str, Any]
    manifest_rows: list[dict[str, str]]
    payloads: dict[str, str]
    obsolete_payload_guids: set[str]
    selected_pack_keys: tuple[str, ...]
    replaced_cards: int
    preserved_card_guids: int
    changed_cards: int
    changed_payloads: int
    reused_equivalent_payloads: int
    terrain_objects: int
    target_bytes: bytes
    manifest_bytes: bytes


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def snapshot_digest(snapshot: dict[str, Any]) -> str:
    stable = dict(snapshot)
    stable.pop("fetchedAt", None)
    return hashlib.sha256(_canonical_json(stable)).hexdigest()


def _url(base: str, path: str, **params: Any) -> str:
    query = urlencode([(key, value) for key, value in params.items() if value is not None])
    return f"{base.rstrip('/')}{path}" + (f"?{query}" if query else "")


class HttpClient:
    def __init__(self, timeout: float, retries: int = 3):
        self.timeout = timeout
        self.retries = retries
        self._print_lock = threading.Lock()

    def _retry_message(self, label: str, attempt: int, reason: str) -> None:
        with self._print_lock:
            print(f"  retry {attempt}/{self.retries}: {label}: {reason}", flush=True)

    def get_json(self, url: str, label: str) -> dict[str, Any]:
        for attempt in range(1, self.retries + 1):
            try:
                request = Request(
                    url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "lst-tts-battlemaster-sync/1",
                    },
                )
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                value = json.loads(raw.decode("utf-8"))
                if not isinstance(value, dict):
                    raise SyncError(f"{label} returned a non-object JSON value")
                if value.get("error") is not None:
                    raise SyncError(f"{label} API error: {value.get('error')}")
                return value
            except HTTPError as exc:
                body = exc.read(500).decode("utf-8", errors="replace").replace("\n", " ")
                reason = f"HTTP {exc.code}: {body or exc.reason}"
                retryable = exc.code == 429 or exc.code >= 500
                if attempt == self.retries or not retryable:
                    raise SyncError(f"{label} failed: {reason}") from exc
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                reason = str(getattr(exc, "reason", exc))
                if attempt == self.retries:
                    raise SyncError(f"{label} failed after {attempt} attempts: {reason}") from exc
            self._retry_message(label, attempt + 1, reason)
            time.sleep(min(2 ** (attempt - 1), 4))
        raise AssertionError("unreachable")


def theme_slots_for_packs(pack_keys: Iterable[str]) -> dict[str, set[int]]:
    result: dict[str, set[int]] = {}
    for key in pack_keys:
        for theme in PACKS[key].themes:
            result.setdefault(theme.theme_id, set()).update(theme.slots)
    return result


def _manifest_theme_items(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    themes = manifest.get("themes")
    if isinstance(themes, dict):
        themes = themes.get("items")
    if not isinstance(themes, list):
        raise SyncError("sync manifest did not contain themes.items[]")
    return [item for item in themes if isinstance(item, dict)]


def _selected_layouts(
    layouts: Any,
    slots: Iterable[int],
    expected_pairs: set[str],
    label: str,
) -> list[dict[str, Any]]:
    if not isinstance(layouts, list):
        raise SyncError(f"{label} layout catalog did not contain layouts[]")
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for layout in layouts:
        if not isinstance(layout, dict):
            continue
        try:
            slot = legacy.layout_slot(layout)
        except (KeyError, TypeError, ValueError):
            continue
        if slot not in slots:
            continue
        pair = str(layout.get("forcePairKey") or "")
        if not pair:
            raise SyncError(f"{label} layout slot {slot} is missing forcePairKey")
        identity = pair, slot
        if identity in seen:
            raise SyncError(f"{label} repeats {pair} slot {slot}")
        seen.add(identity)
        selected.append(layout)
    for slot in sorted(set(slots)):
        actual_pairs = {str(layout.get("forcePairKey")) for layout in selected if legacy.layout_slot(layout) == slot}
        if actual_pairs != expected_pairs:
            missing = ", ".join(sorted(expected_pairs - actual_pairs)) or "none"
            extra = ", ".join(sorted(actual_pairs - expected_pairs)) or "none"
            raise SyncError(
                f"{label} slot {slot} is not a complete {len(expected_pairs)}-pair set "
                f"(missing: {missing}; unexpected: {extra})"
            )
    return sorted(selected, key=lambda layout: (str(layout.get("forcePairKey") or ""), legacy.layout_slot(layout)))


def _payload_key(pair: str, slot: int) -> str:
    return f"{pair}|slot:{slot}"


def _check_declared_count(response: dict[str, Any], field: str, actual: int, label: str) -> None:
    declared = response.get(field)
    if declared is None:
        return
    try:
        declared_count = int(declared)
    except (TypeError, ValueError) as exc:
        raise SyncError(f"{label} has invalid {field}={declared!r}") from exc
    if declared_count != actual:
        raise SyncError(f"{label} declares {field}={declared_count}, but contains {actual}")


def _check_no_upstream_skips(response: dict[str, Any], field: str, label: str) -> None:
    skipped = response.get(field)
    if skipped in (None, 0, False, ""):
        return
    if isinstance(skipped, (list, dict)) and not skipped:
        return
    count = len(skipped) if isinstance(skipped, (list, dict)) else skipped
    raise SyncError(f"{label} reports {count} item(s) in {field}; refusing a lossy snapshot")


def fetch_snapshot(
    pack_keys: tuple[str, ...],
    expected_pairs: set[str],
    *,
    api_base: str,
    timeout: float,
    workers: int,
) -> dict[str, Any]:
    client = HttpClient(timeout=timeout)
    print("Fetching Battlemaster manifest (community themes included)...", flush=True)
    manifest = client.get_json(
        _url(api_base, "/v1/public/tts/sync-manifest", owner=OWNER, approvedOnly="false"),
        "sync manifest",
    )
    metadata_by_id = {
        str(item.get("id")): item
        for item in _manifest_theme_items(manifest)
        if item.get("id") is not None
    }
    required_theme_slots = theme_slots_for_packs(pack_keys)
    missing_themes = sorted(set(required_theme_slots) - set(metadata_by_id))
    if missing_themes:
        raise SyncError("requested themes are absent from the public manifest: " + ", ".join(missing_themes))

    print(f"Fetching template catalog plus {len(required_theme_slots)} theme/layout catalogs...", flush=True)
    jobs: dict[Any, tuple[str, str | None]] = {}
    results: dict[tuple[str, str | None], dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future = executor.submit(
            client.get_json,
            _url(api_base, "/v1/public/tts/template-catalog"),
            "template catalog",
        )
        jobs[future] = ("template", None)
        for theme_id in sorted(required_theme_slots):
            metadata = metadata_by_id[theme_id]
            theme_owner = str(metadata.get("ownerUserId") or "")
            if not theme_owner:
                raise SyncError(f"theme {theme_id} has no ownerUserId")
            theme_url = _url(
                api_base,
                f"/v1/public/tts/themes/{quote(theme_id, safe='')}/catalog",
                owner=theme_owner,
            )
            layout_url = _url(
                api_base,
                "/v1/public/tts/chapter-approved-layouts",
                owner=OWNER,
                themeId=theme_id,
                themeOwner=theme_owner,
            )
            jobs[executor.submit(client.get_json, theme_url, f"theme catalog {theme_id}")] = ("theme", theme_id)
            jobs[executor.submit(client.get_json, layout_url, f"layout catalog {theme_id}")] = ("layouts", theme_id)
        for future in as_completed(jobs):
            results[jobs[future]] = future.result()

    template_response = results[("template", None)]
    template_catalog = template_response.get("templateCatalog")
    if not isinstance(template_catalog, dict) or not isinstance(template_catalog.get("t"), list):
        raise SyncError("template-catalog response did not contain templateCatalog.t[]")
    _check_declared_count(template_response, "templateCount", len(template_catalog["t"]), "template catalog")
    _check_no_upstream_skips(template_response, "skippedParts", "template catalog")
    manifest_template_key = str((manifest.get("templateCatalog") or {}).get("templateCatalogKey") or "")
    response_template_key = str(template_response.get("templateCatalogKey") or template_response.get("catalogId") or "")
    if manifest_template_key and response_template_key and manifest_template_key != response_template_key:
        raise SyncError("template catalog changed while the snapshot was being fetched; rerun the command")

    snapshot_themes: dict[str, dict[str, Any]] = {}
    required_payload_layouts: dict[tuple[str, int], set[str]] = {}
    manifest_layout_key = str((manifest.get("layouts") or {}).get("layoutCatalogKey") or "")
    for theme_id, slots in sorted(required_theme_slots.items()):
        theme_response = results[("theme", theme_id)]
        layout_response = results[("layouts", theme_id)]
        theme_catalog = theme_response.get("themeCatalog")
        if not isinstance(theme_catalog, dict) or not isinstance(theme_catalog.get("m"), list):
            raise SyncError(f"theme {theme_id} response did not contain themeCatalog.m[]")
        _check_declared_count(theme_response, "mappingCount", len(theme_catalog["m"]), f"theme {theme_id}")
        _check_no_upstream_skips(theme_response, "skippedMappings", f"theme {theme_id}")
        metadata_theme_key = str(metadata_by_id[theme_id].get("themeKey") or "")
        response_theme_key = str(theme_response.get("themeKey") or "")
        if metadata_theme_key and response_theme_key and metadata_theme_key != response_theme_key:
            raise SyncError(f"theme {theme_id} changed while the snapshot was being fetched; rerun the command")
        layouts = layout_response.get("layouts")
        if isinstance(layouts, list):
            _check_declared_count(layout_response, "layoutCount", len(layouts), f"layout catalog {theme_id}")
        response_layout_key = str(layout_response.get("catalogKey") or "")
        if manifest_layout_key and response_layout_key and manifest_layout_key != response_layout_key:
            raise SyncError(f"layout catalog changed while fetching theme {theme_id}; rerun the command")
        selected = _selected_layouts(layouts, slots, expected_pairs, theme_id)
        for layout in selected:
            payload_identity = str(layout["forcePairKey"]), legacy.layout_slot(layout)
            required_payload_layouts.setdefault(payload_identity, set()).add(str(layout.get("id") or ""))
        snapshot_themes[theme_id] = {
            "metadata": metadata_by_id[theme_id],
            "themeKey": str(theme_response.get("themeKey") or metadata_by_id[theme_id].get("themeKey") or theme_id),
            "themeCatalog": theme_catalog,
            "catalogKey": str(layout_response.get("catalogKey") or ""),
            "layouts": layouts,
        }

    inconsistent_layouts = {
        identity: ids
        for identity, ids in required_payload_layouts.items()
        if len(ids) != 1 or "" in ids
    }
    if inconsistent_layouts:
        first_identity, ids = next(iter(inconsistent_layouts.items()))
        raise SyncError(f"theme catalogs disagree on layout identity for {first_identity}: {sorted(ids)}")

    print(f"Fetching {len(required_payload_layouts)} shared layout payloads...", flush=True)
    payload_responses: dict[str, dict[str, Any]] = {}
    jobs = {}
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for pair, slot in sorted(required_payload_layouts):
            parts = pair.split("|", 1)
            if len(parts) != 2 or not all(parts):
                raise SyncError(f"invalid forcePairKey {pair!r}")
            payload_url = _url(
                api_base,
                "/v1/public/tts/chapter-approved-layout-lite",
                owner=OWNER,
                archetypeA=parts[0],
                archetypeB=parts[1],
                slot=slot,
            )
            future = executor.submit(client.get_json, payload_url, f"layout payload {pair} slot {slot}")
            jobs[future] = pair, slot
        for future in as_completed(jobs):
            pair, slot = jobs[future]
            response = future.result()
            lite_payload = response.get("litePayload")
            if not isinstance(lite_payload, dict) or not isinstance(lite_payload.get("i"), list):
                raise SyncError(f"layout payload {pair} slot {slot} did not contain litePayload.i[]")
            _check_declared_count(response, "instanceCount", len(lite_payload["i"]), f"layout payload {pair} slot {slot}")
            _check_no_upstream_skips(response, "skippedRuins", f"layout payload {pair} slot {slot}")
            response_layout = response.get("layout") if isinstance(response.get("layout"), dict) else {}
            expected_layout_id = next(iter(required_payload_layouts[(pair, slot)]))
            response_layout_id = str(response_layout.get("id") or lite_payload.get("id") or "")
            if response_layout_id != expected_layout_id:
                raise SyncError(
                    f"layout payload {pair} slot {slot} returned id {response_layout_id!r}; "
                    f"catalog expected {expected_layout_id!r}"
                )
            response_slot = (response_layout.get("chapterApprovedSlot") or {}).get("slotIndex")
            if response_slot is not None:
                try:
                    response_slot_number = int(response_slot)
                except (TypeError, ValueError) as exc:
                    raise SyncError(f"layout payload {pair} slot {slot} returned invalid slot {response_slot!r}") from exc
                if response_slot_number != slot:
                    raise SyncError(f"layout payload {pair} slot {slot} returned slot {response_slot!r}")
            payload_responses[_payload_key(pair, slot)] = {
                "layoutId": response_layout_id,
                "layoutKey": str(response_layout.get("layoutKey") or ""),
                "litePayload": lite_payload,
            }
            completed += 1
            if completed % 10 == 0 or completed == len(jobs):
                print(f"  payloads {completed}/{len(jobs)}", flush=True)

    snapshot = {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "apiBase": api_base.rstrip("/"),
        "owner": OWNER,
        "selectedPacks": list(pack_keys),
        "manifestKeys": {
            "templateCatalogKey": str((manifest.get("templateCatalog") or {}).get("templateCatalogKey") or ""),
            "themeListKey": str((manifest.get("themes") or {}).get("themeListKey") or ""),
            "layoutCatalogKey": manifest_layout_key,
        },
        "templateCatalogKey": str(template_response.get("templateCatalogKey") or template_response.get("catalogId") or ""),
        "templateCatalog": template_catalog,
        "themes": snapshot_themes,
        "layoutPayloads": payload_responses,
    }
    validate_snapshot(snapshot, pack_keys, expected_pairs)
    return snapshot


def validate_snapshot(snapshot: Any, pack_keys: tuple[str, ...], expected_pairs: set[str]) -> None:
    if not isinstance(snapshot, dict):
        raise SyncError("snapshot root must be a JSON object")
    if snapshot.get("schemaVersion") != SNAPSHOT_SCHEMA_VERSION:
        raise SyncError(
            f"unsupported snapshot schemaVersion {snapshot.get('schemaVersion')!r}; "
            f"expected {SNAPSHOT_SCHEMA_VERSION}"
        )
    if snapshot.get("owner") != OWNER:
        raise SyncError(f"snapshot owner is {snapshot.get('owner')!r}; expected {OWNER!r}")
    template_catalog = snapshot.get("templateCatalog")
    if not isinstance(template_catalog, dict) or not isinstance(template_catalog.get("t"), list):
        raise SyncError("snapshot has no templateCatalog.t[]")
    themes = snapshot.get("themes")
    payloads = snapshot.get("layoutPayloads")
    if not isinstance(themes, dict) or not isinstance(payloads, dict):
        raise SyncError("snapshot must contain themes{} and layoutPayloads{}")
    manifest_keys = snapshot.get("manifestKeys") if isinstance(snapshot.get("manifestKeys"), dict) else {}
    manifest_template_key = str(manifest_keys.get("templateCatalogKey") or "")
    snapshot_template_key = str(snapshot.get("templateCatalogKey") or "")
    if manifest_template_key and snapshot_template_key and manifest_template_key != snapshot_template_key:
        raise SyncError("snapshot template catalog key does not match its manifest key")
    for theme_id, slots in theme_slots_for_packs(pack_keys).items():
        archive = themes.get(theme_id)
        if not isinstance(archive, dict):
            raise SyncError(f"snapshot does not contain requested theme {theme_id}")
        if not isinstance(archive.get("themeCatalog"), dict):
            raise SyncError(f"snapshot theme {theme_id} has no themeCatalog")
        metadata = archive.get("metadata") if isinstance(archive.get("metadata"), dict) else {}
        metadata_theme_key = str(metadata.get("themeKey") or "")
        archive_theme_key = str(archive.get("themeKey") or "")
        if metadata_theme_key and archive_theme_key and metadata_theme_key != archive_theme_key:
            raise SyncError(f"snapshot theme {theme_id} key does not match its manifest metadata")
        manifest_layout_key = str(manifest_keys.get("layoutCatalogKey") or "")
        archive_layout_key = str(archive.get("catalogKey") or "")
        if manifest_layout_key and archive_layout_key and manifest_layout_key != archive_layout_key:
            raise SyncError(f"snapshot theme {theme_id} layout catalog key does not match its manifest key")
        selected = _selected_layouts(archive.get("layouts"), slots, expected_pairs, theme_id)
        for layout in selected:
            key = _payload_key(str(layout.get("forcePairKey")), legacy.layout_slot(layout))
            payload = payloads.get(key)
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("litePayload"), dict)
                or not isinstance(payload["litePayload"].get("i"), list)
            ):
                raise SyncError(f"snapshot is missing {key}")
            layout_id = str(layout.get("id") or "")
            payload_layout_id = str(payload.get("layoutId") or payload["litePayload"].get("id") or "")
            if payload_layout_id and layout_id and payload_layout_id != layout_id:
                raise SyncError(
                    f"snapshot mismatch for {key}: catalog layout id {layout_id!r}, "
                    f"payload layout id {payload_layout_id!r}"
                )


def records_from_snapshot(
    snapshot: dict[str, Any],
    pack_keys: tuple[str, ...],
    expected_pairs: set[str],
) -> list[MapRecord]:
    validate_snapshot(snapshot, pack_keys, expected_pairs)
    records: list[MapRecord] = []
    identities: set[tuple[str, str, int]] = set()
    for pack_key in pack_keys:
        pack = PACKS[pack_key]
        pack_records: list[MapRecord] = []
        for theme in pack.themes:
            archive = snapshot["themes"][theme.theme_id]
            layouts = _selected_layouts(archive["layouts"], theme.slots, expected_pairs, theme.label)
            for layout in layouts:
                pair = str(layout.get("forcePairKey"))
                slot = legacy.layout_slot(layout)
                payload_entry = snapshot["layoutPayloads"][_payload_key(pair, slot)]
                payload_layout_key = str(payload_entry.get("layoutKey") or "")
                layout_key = str(layout.get("layoutKey") or "")
                if payload_layout_key and layout_key and payload_layout_key != layout_key:
                    raise SyncError(
                        f"snapshot mismatch for {pair} slot {slot}: catalog layoutKey {layout_key!r}, "
                        f"payload layoutKey {payload_layout_key!r}"
                    )
                record = MapRecord(pack, theme, layout, payload_entry["litePayload"])
                if record.identity in identities:
                    raise SyncError(f"duplicate selected map identity {record.identity}")
                identities.add(record.identity)
                pack_records.append(record)
        if len(pack_records) != EXPECTED_LAYOUTS_PER_PACK:
            raise SyncError(
                f"{pack.creator_display} resolved to {len(pack_records)} maps; "
                f"expected {EXPECTED_LAYOUTS_PER_PACK}"
            )
        records.extend(sorted(pack_records, key=lambda record: (record.pair, record.slot)))
    return records


def _deck_id(card: dict[str, Any]) -> int | None:
    card_id = card.get("CardID")
    if isinstance(card_id, int) and card_id >= 100 and card_id % 100 == 0:
        return card_id // 100
    keys = list((card.get("CustomDeck") or {}).keys())
    if len(keys) == 1 and str(keys[0]).isdigit():
        return int(keys[0])
    return None


def _used_deck_ids(target: dict[str, Any]) -> set[str]:
    used = set()
    for obj in legacy.walk(target.get("ObjectStates") or []):
        used.update(str(key) for key in (obj.get("CustomDeck") or {}).keys())
    return used


def _remove_creator_cards(target: dict[str, Any], creator_tags: set[str]) -> list[dict[str, Any]]:
    removed = []
    for obj in legacy.walk(target.get("ObjectStates") or []):
        children = obj.get("ContainedObjects")
        if not isinstance(children, list):
            continue
        kept = []
        for child in children:
            if creator_tags.intersection(child.get("Tags") or []):
                removed.append(child)
            else:
                kept.append(child)
        obj["ContainedObjects"] = kept
    return removed


def _manifest_bytes(rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "deck_guid", "deck_name", "card_guid", "card_name",
            "map_creator_tag", "map_type_tag", "creator_display", "eligible",
        ],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _payload_text(entries: list[str]) -> str:
    lines = [legacy.OBJECTJSONS_MARKER]
    for entry in entries:
        if "]]" in entry:
            raise SyncError("reconstructed object JSON contains Lua long-string terminator ]]")
        json.loads(entry)
        lines.append(f"  [[{entry}]],")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _without_guids(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("<GUID>" if key == "GUID" else _without_guids(child))
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_without_guids(child) for child in value]
    return value


def _reuse_equivalent_payload(
    old_payload: str | None,
    reconstructed_objects: list[dict[str, Any]],
) -> str | None:
    """Keep existing bytes when only generated terrain GUIDs differ.

    Lua's JSON encoder and Python choose different object-key ordering.  Reusing
    a semantically identical payload avoids a multi-megabyte diff on a no-op API
    refresh while the Python reconstruction still proves structural parity.
    """
    if not old_payload:
        return None
    try:
        entries = legacy.objectjson_entries_from_cached_script(old_payload)
        old_objects = [json.loads(entry) for entry in entries]
    except (ValueError, json.JSONDecodeError):
        return None
    # Compare canonical JSON bytes, not Python equality: `==` treats 0 and 0.0
    # as equal, which would let a payload with a stale float-typed field (e.g.
    # a LayoutGroupSortIndex TTS requires as an integer) get silently reused
    # forever, even after the reconstruction code that produced it is fixed.
    if _canonical_json(_without_guids(old_objects)) == _canonical_json(_without_guids(reconstructed_objects)):
        return old_payload
    return None


def _make_card(
    guid: str,
    name: str,
    face_url: str,
    deck_id: int,
    creator_tag: str,
    machinery: str,
) -> dict[str, Any]:
    return {
        "GUID": guid,
        "Name": "CardCustom",
        "Transform": {
            "posX": 0, "posY": 1, "posZ": 0,
            "rotX": 0, "rotY": 180, "rotZ": 0,
            "scaleX": 1.5, "scaleY": 1, "scaleZ": 1.5,
        },
        "Nickname": name,
        "Description": "Battlemaster imported static LCT map card.",
        "GMNotes": "",
        "Tags": ["map", creator_tag, legacy.TYPE_TAG],
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
        "CustomDeck": legacy.card_custom_deck(face_url, face_url or legacy.DEFAULT_BACK_URL, deck_id, 1),
        "LuaScript": machinery,
        "LuaScriptState": "",
        "XmlUI": "",
    }


def _all_object_guid_values(objects: Iterable[dict[str, Any]]) -> list[str]:
    found = []
    stack = list(objects)
    while stack:
        obj = stack.pop()
        if not isinstance(obj, dict):
            continue
        guid = obj.get("GUID")
        if isinstance(guid, str):
            found.append(guid.lower())
        stack.extend(child for child in obj.get("ChildObjects") or [] if isinstance(child, dict))
        stack.extend(child for child in obj.get("ContainedObjects") or [] if isinstance(child, dict))
        states = obj.get("States")
        if isinstance(states, dict):
            stack.extend(child for child in states.values() if isinstance(child, dict))
    return found


def _validate_footprint_contract(
    objects: Iterable[dict[str, Any]],
    footprint_profile: str,
    expected_count: int,
    label: str,
) -> None:
    rugged_to_smooth = {
        str(asset["rugged"]): str(asset["smooth"])
        for asset in reconstruction.TERRAIN_ASSETS
    }
    plate_prefix = reconstruction.TERRAIN_PLATE_MESH_BASE_URL
    candidates = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        top_asset_url = str((obj.get("CustomAssetbundle") or {}).get("AssetbundleURL") or "")
        mesh_url = str((obj.get("CustomMesh") or {}).get("MeshURL") or "")
        if top_asset_url in rugged_to_smooth or mesh_url.startswith(plate_prefix):
            candidates.append(obj)

    if len(candidates) != expected_count:
        raise SyncError(
            f"{label} reconstructed {len(candidates)} recognizable footprint(s); "
            f"expected {expected_count}"
        )

    for index, obj in enumerate(candidates, 1):
        states = obj.get("States")
        if not isinstance(states, dict):
            raise SyncError(f"{label} footprint {index} has no TTS States table")
        top_asset_url = str((obj.get("CustomAssetbundle") or {}).get("AssetbundleURL") or "")
        mesh_url = str((obj.get("CustomMesh") or {}).get("MeshURL") or "")

        if footprint_profile == reconstruction.FOOTPRINT_PROFILE_BATTLEMASTER:
            if obj.get("Name") != "Custom_Assetbundle" or top_asset_url not in rugged_to_smooth:
                raise SyncError(f"{label} footprint {index} is not a rugged Battlemaster state 1")
            if set(states) != {"2"}:
                raise SyncError(f"{label} footprint {index} must contain only Battlemaster state 2")
            if not isinstance(states["2"], dict):
                raise SyncError(f"{label} footprint {index} state 2 is not an object")
            expected_smooth = rugged_to_smooth[top_asset_url]
            actual_smooth = str((states["2"].get("CustomAssetbundle") or {}).get("AssetbundleURL") or "")
            if actual_smooth != expected_smooth:
                raise SyncError(f"{label} footprint {index} state 2 is not the matching smooth terrain")
        elif footprint_profile == reconstruction.FOOTPRINT_PROFILE_LCT:
            if obj.get("Name") != "Custom_Model" or not mesh_url.endswith("-5mm-border.obj"):
                raise SyncError(f"{label} footprint {index} is not an LCT custom bordered state 1")
            if set(states) != {"2", "3"}:
                raise SyncError(f"{label} footprint {index} must contain LCT states 2 and 3")
            if not isinstance(states["2"], dict) or not isinstance(states["3"], dict):
                raise SyncError(f"{label} footprint {index} states 2/3 are not objects")
            rugged_url = str((states["2"].get("CustomAssetbundle") or {}).get("AssetbundleURL") or "")
            smooth_url = str((states["3"].get("CustomAssetbundle") or {}).get("AssetbundleURL") or "")
            if rugged_url not in rugged_to_smooth or smooth_url != rugged_to_smooth[rugged_url]:
                raise SyncError(f"{label} footprint {index} states 2/3 are not matching rugged/smooth terrains")
        else:
            raise SyncError(f"{label} uses unknown footprint profile {footprint_profile!r}")

        for state_key, state in states.items():
            if not isinstance(state, dict):
                raise SyncError(f"{label} footprint {index} state {state_key} is not an object")
            if state.get("Transform") != obj.get("Transform"):
                raise SyncError(f"{label} footprint {index} state {state_key} transform differs from state 1")
            if state.get("Tags") != obj.get("Tags"):
                raise SyncError(f"{label} footprint {index} state {state_key} objective tags differ from state 1")


def build_install_plan(
    snapshot: dict[str, Any],
    pack_keys: tuple[str, ...],
    *,
    allow_missing_layout_art: bool = False,
) -> InstallPlan:
    original_target = json.loads(TARGET_PATH.read_text(encoding="utf-8"))
    manifest_rows = legacy.load_manifest(MANIFEST_PATH)
    source_bags = legacy.source_bags_by_pair(manifest_rows)
    expected_pairs = set(source_bags)
    if len(expected_pairs) != EXPECTED_PAIR_COUNT:
        raise SyncError(f"manifest exposes {len(expected_pairs)} source pairs; expected {EXPECTED_PAIR_COUNT}")
    records = records_from_snapshot(snapshot, pack_keys, expected_pairs)
    selected_tags = {PACKS[key].creator_tag for key in pack_keys}
    original_index = {
        obj.get("GUID"): obj
        for obj in legacy.walk(original_target.get("ObjectStates") or [])
        if obj.get("GUID")
    }

    old_rows: dict[tuple[str, str, int], dict[str, str]] = {}
    selected_rows = []
    for row in manifest_rows:
        creator_tag = row.get("map_creator_tag")
        if creator_tag not in selected_tags:
            continue
        try:
            pair, slot = legacy.manifest_row_pair_slot(row)
        except (KeyError, TypeError, ValueError) as exc:
            raise SyncError(f"cannot derive pair/slot from existing row {row}") from exc
        identity = creator_tag, pair, slot
        if identity in old_rows:
            raise SyncError(f"manifest repeats existing map identity {identity}")
        old_rows[identity] = row
        selected_rows.append(row)

    target = copy.deepcopy(original_target)
    removed_cards = _remove_creator_cards(target, selected_tags)
    removed_by_guid = {str(card.get("GUID")): card for card in removed_cards if card.get("GUID")}
    selected_manifest_guids = {row["card_guid"] for row in selected_rows}
    unexpected_removed = sorted(set(removed_by_guid) - selected_manifest_guids)
    missing_removed = sorted(selected_manifest_guids - set(removed_by_guid))
    if unexpected_removed or missing_removed:
        raise SyncError(
            "selected creator cards disagree between save and manifest "
            f"(unmanifested cards: {unexpected_removed[:5]}; missing cards: {missing_removed[:5]})"
        )

    target_by_guid = {
        obj.get("GUID"): obj
        for obj in legacy.walk(target.get("ObjectStates") or [])
        if obj.get("GUID")
    }
    used_card_guids = legacy.all_guids(target)
    used_deck_ids = _used_deck_ids(target)
    logical_names = legacy.manifest_logical_names_by_pair_slot(manifest_rows)
    layout_art = legacy.existing_layout_art_names(original_target)
    machinery = MACHINERY_PATH.read_text(encoding="utf-8")
    if not machinery.endswith("\n"):
        raise SyncError(f"canonical machinery {MACHINERY_PATH} must end with a newline")

    identities: dict[tuple[str, str, int], tuple[str, int, dict[str, Any] | None]] = {}
    preserved = 0
    for record in records:
        old_row = old_rows.get(record.identity)
        old_card = original_index.get(old_row["card_guid"]) if old_row else None
        if old_row and not isinstance(old_card, dict):
            raise SyncError(f"existing manifest card {old_row['card_guid']} is missing from the source save")
        if old_card is not None:
            card_guid = str(old_card["GUID"])
            deck_id = _deck_id(old_card)
            if deck_id is None:
                raise SyncError(f"existing card {card_guid} has no usable deck id")
            if card_guid in used_card_guids:
                raise SyncError(f"preserved card GUID {card_guid} collides after removing selected packs")
            if str(deck_id) in used_deck_ids:
                raise SyncError(f"preserved deck id {deck_id} collides after removing selected packs")
            used_card_guids.add(card_guid)
            used_deck_ids.add(str(deck_id))
            preserved += 1
        else:
            seed = f"{record.pack.creator_tag}|{record.pair}|slot:{record.slot}"
            card_guid = legacy.stable_guid("card|" + seed, used_card_guids)
            deck_id = legacy.stable_deck_id("deck|" + seed, used_deck_ids)
        identities[record.identity] = card_guid, deck_id, old_card

    terrain_reserved = {guid.lower() for guid in legacy.all_guids(original_target)}
    terrain_reserved.update(guid.lower() for guid, _deck, _card in identities.values())
    payloads: dict[str, str] = {}
    additions: list[dict[str, str]] = []
    planned_cards_by_bag: dict[str, list[tuple[str | None, dict[str, Any]]]] = {}
    changed_cards = changed_payloads = terrain_objects = reused_payloads = 0
    missing_art = []
    seen_terrain_guids: set[str] = set()

    for record in records:
        source_info = source_bags.get(record.pair)
        if source_info is None:
            raise SyncError(f"no source bag exists for API pair {record.pair!r}")
        logical_name = legacy.logical_name_for(record.layout, source_info["deck_name"], logical_names)
        deployment_key = record.layout.get("chapterApprovedDeploymentKey")
        try:
            deployment_name = legacy.DEPLOYMENT_NAMES[int(deployment_key)]
        except (KeyError, TypeError, ValueError) as exc:
            raise SyncError(f"{record.pair} slot {record.slot} has invalid deployment key {deployment_key!r}") from exc
        if not logical_name.endswith(" - " + deployment_name):
            raise SyncError(
                f"{record.pair} slot {record.slot} API deployment is {deployment_name!r}, "
                f"but the existing logical map is {logical_name!r}"
            )
        if logical_name.strip().casefold() not in layout_art:
            missing_art.append(logical_name)
        card_guid, deck_id, old_card = identities[record.identity]
        result = reconstruction.reconstruct_objects(
            snapshot["templateCatalog"],
            snapshot["themes"][record.theme.theme_id]["themeCatalog"],
            record.lite_payload,
            f"{record.pack.creator_tag}|{record.pair}|slot:{record.slot}",
            footprint_profile=record.pack.footprint_profile,
            reserved_guids=terrain_reserved | seen_terrain_guids,
        )
        if result.skipped:
            raise SyncError(
                f"{record.pack.creator_display} {record.pair} slot {record.slot} "
                f"skipped {result.skipped} terrain object(s); refusing a lossy import"
            )
        if not result.objects:
            raise SyncError(f"{record.pack.creator_display} {record.pair} slot {record.slot} reconstructed no objects")
        map_label = f"{record.pack.creator_display} {record.pair} slot {record.slot}"
        _validate_footprint_contract(
            result.objects,
            record.pack.footprint_profile,
            len(record.lite_payload["i"]),
            map_label,
        )
        object_guid_values = _all_object_guid_values(result.objects)
        object_guids = set(object_guid_values)
        if len(object_guids) != len(object_guid_values):
            raise SyncError(f"{record.pack.creator_display} {record.pair} slot {record.slot} contains duplicate terrain GUIDs")
        seen_terrain_guids.update(object_guids)
        terrain_objects += result.spawned
        old_payload_path = PAYLOAD_DIR / f"{card_guid}.lua"
        if old_payload_path.exists():
            with old_payload_path.open("r", encoding="utf-8", newline="") as handle:
                old_payload = handle.read()
        else:
            old_payload = None
        payload = _reuse_equivalent_payload(old_payload, result.objects)
        if payload is None:
            payload = _payload_text(result.compact_json_entries())
        else:
            reused_payloads += 1
        payloads[card_guid] = payload
        if old_payload != payload:
            changed_payloads += 1

        card_name = f"{logical_name} - {record.pack.creator_display}"
        face_url = str(record.layout.get("previewUrl") or legacy.DEFAULT_FACE_URL)
        card = _make_card(
            card_guid,
            card_name,
            face_url,
            deck_id,
            record.pack.creator_tag,
            machinery,
        )
        if old_card != card:
            changed_cards += 1
        bag = target_by_guid.get(source_info["deck_guid"])
        if not isinstance(bag, dict):
            raise SyncError(f"source bag {source_info['deck_guid']} is missing from {TARGET_PATH}")
        old_guid = str(old_card.get("GUID")) if old_card is not None else None
        existing_row = old_rows.get(record.identity)
        if existing_row and existing_row.get("deck_guid") != source_info["deck_guid"]:
            raise SyncError(
                f"existing card {card_guid} is assigned to {existing_row.get('deck_guid')}, "
                f"but API pair {record.pair} resolves to {source_info['deck_guid']}"
            )
        planned_cards_by_bag.setdefault(source_info["deck_guid"], []).append((old_guid, card))
        additions.append({
            "deck_guid": source_info["deck_guid"],
            "deck_name": source_info["deck_name"],
            "card_guid": card_guid,
            "card_name": card_name,
            "map_creator_tag": record.pack.creator_tag,
            "map_type_tag": legacy.TYPE_TAG,
            "creator_display": record.pack.creator_display,
            "eligible": "true",
        })

    if missing_art and not allow_missing_layout_art:
        raise SyncError(
            f"{len(missing_art)} selected maps have no layout-art match; first: "
            + ", ".join(missing_art[:5])
        )
    if missing_art:
        print(f"WARNING: {len(missing_art)} selected maps have no matching layout art.")

    # Replace existing cards and rows in place.  A no-op refresh must not move a
    # creator block to the end of every source bag or reorder the manifest.
    for bag_guid, planned_cards in planned_cards_by_bag.items():
        original_bag = original_index.get(bag_guid)
        target_bag = target_by_guid.get(bag_guid)
        if not isinstance(original_bag, dict) or not isinstance(target_bag, dict):
            raise SyncError(f"cannot rebuild source bag {bag_guid}")
        replacements = {old_guid: card for old_guid, card in planned_cards if old_guid is not None}
        rebuilt = []
        consumed = set()
        for original_child in original_bag.get("ContainedObjects") or []:
            original_guid = original_child.get("GUID")
            if original_guid in replacements:
                rebuilt.append(replacements[original_guid])
                consumed.add(original_guid)
            elif original_guid in removed_by_guid:
                continue
            else:
                rebuilt.append(copy.deepcopy(original_child))
        rebuilt.extend(
            card
            for old_guid, card in planned_cards
            if old_guid is None or old_guid not in consumed
        )
        target_bag["ContainedObjects"] = rebuilt

    addition_by_identity = {}
    for row in additions:
        pair, slot = legacy.manifest_row_pair_slot(row)
        identity = row["map_creator_tag"], pair, slot
        addition_by_identity[identity] = row
    final_rows = []
    consumed_identities = set()
    for row in manifest_rows:
        if row.get("map_creator_tag") not in selected_tags:
            final_rows.append(row)
            continue
        pair, slot = legacy.manifest_row_pair_slot(row)
        identity = row["map_creator_tag"], pair, slot
        replacement = addition_by_identity.get(identity)
        if replacement is not None:
            final_rows.append(replacement)
            consumed_identities.add(identity)
    final_rows.extend(
        row
        for identity, row in addition_by_identity.items()
        if identity not in consumed_identities
    )
    new_guids = set(payloads)
    obsolete = set(removed_by_guid) - new_guids
    counts = {}
    for row in additions:
        counts[row["map_creator_tag"]] = counts.get(row["map_creator_tag"], 0) + 1
    for key in pack_keys:
        spec = PACKS[key]
        if counts.get(spec.creator_tag) != EXPECTED_LAYOUTS_PER_PACK:
            raise SyncError(f"plan contains {counts.get(spec.creator_tag, 0)} rows for {spec.creator_display}; expected 45")
    guids = [row["card_guid"] for row in final_rows]
    if len(guids) != len(set(guids)) or not all(GUID_RE.fullmatch(guid) for guid in guids):
        raise SyncError("planned manifest contains duplicate or invalid card GUIDs")
    json.dumps(target, ensure_ascii=False)
    target_bytes = (json.dumps(target, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return InstallPlan(
        target=target,
        manifest_rows=final_rows,
        payloads=payloads,
        obsolete_payload_guids=obsolete,
        selected_pack_keys=pack_keys,
        replaced_cards=len(removed_cards),
        preserved_card_guids=preserved,
        changed_cards=changed_cards,
        changed_payloads=changed_payloads,
        reused_equivalent_payloads=reused_payloads,
        terrain_objects=terrain_objects,
        target_bytes=target_bytes,
        manifest_bytes=_manifest_bytes(final_rows),
    )


def validate_plan_with_project_validator(plan: InstallPlan) -> tuple[int, int]:
    """Run the normal full-map validator against a temporary payload overlay."""
    import validate_maps

    with tempfile.TemporaryDirectory(prefix="lst-bm-validate-") as temp_name:
        temp_root = Path(temp_name)
        temp_payload_dir = temp_root / "maps"
        temp_payload_dir.mkdir()
        for source in PAYLOAD_DIR.glob("*.lua"):
            (temp_payload_dir / source.name).symlink_to(source.resolve())
        for guid, payload in plan.payloads.items():
            destination = temp_payload_dir / f"{guid}.lua"
            if destination.exists() or destination.is_symlink():
                destination.unlink()
            destination.write_text(payload, encoding="utf-8", newline="")
        for guid in plan.obsolete_payload_guids:
            destination = temp_payload_dir / f"{guid}.lua"
            if destination.exists() or destination.is_symlink():
                destination.unlink()
        temp_manifest = temp_root / "map_manifest.csv"
        temp_manifest.write_bytes(plan.manifest_bytes)
        original_payload_dir = validate_maps.MAP_PAYLOAD_DIR
        try:
            validate_maps.MAP_PAYLOAD_DIR = temp_payload_dir
            issues, _context = validate_maps.validate(
                plan.target.get("ObjectStates") or [],
                require_map_tags=True,
                manifest_path=temp_manifest,
            )
        finally:
            validate_maps.MAP_PAYLOAD_DIR = original_payload_dir
    errors = [issue for issue in issues if issue.level == validate_maps.ERROR]
    warnings = [issue for issue in issues if issue.level != validate_maps.ERROR]
    if errors:
        details = "\n".join(f"  [{issue.where}] {issue.message}" for issue in errors[:20])
        suffix = f"\n  ... {len(errors) - 20} more" if len(errors) > 20 else ""
        raise SyncError(f"prospective source failed map validation with {len(errors)} error(s):\n{details}{suffix}")
    return len(errors), len(warnings)


def _stage_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        os.chmod(temporary, mode)
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = _stage_bytes(path, data)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class SourceTransaction:
    def __init__(self, plan: InstallPlan):
        self.plan = plan
        desired_writes = {
            **{PAYLOAD_DIR / f"{guid}.lua": payload.encode("utf-8") for guid, payload in plan.payloads.items()},
            TARGET_PATH: plan.target_bytes,
            MANIFEST_PATH: plan.manifest_bytes,
        }
        self.writes = {
            path: data
            for path, data in desired_writes.items()
            if not path.exists() or path.read_bytes() != data
        }
        affected = set(self.writes)
        affected.update(PAYLOAD_DIR / f"{guid}.lua" for guid in plan.obsolete_payload_guids)
        self.before = {path: path.read_bytes() if path.exists() else None for path in affected}
        self.applied = False

    def apply(self) -> None:
        staged: dict[Path, Path] = {}
        try:
            for path, data in self.writes.items():
                staged[path] = _stage_bytes(path, data)
            for path in sorted(staged, key=lambda value: (value in {TARGET_PATH, MANIFEST_PATH}, str(value))):
                os.replace(staged[path], path)
            for guid in self.plan.obsolete_payload_guids:
                (PAYLOAD_DIR / f"{guid}.lua").unlink(missing_ok=True)
            self.applied = True
        except BaseException:
            self.rollback()
            raise
        finally:
            for temporary in staged.values():
                temporary.unlink(missing_ok=True)

    def rollback(self) -> None:
        for path, content in self.before.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                _atomic_write(path, content)
        self.applied = False


def run_post_write_checks(*, compile_test: bool) -> None:
    commands = [
        [sys.executable, "scripts/validate_maps.py", "--require-map-tags"],
        [sys.executable, "-m", "unittest", "scripts.test_validate_maps", "scripts.test_sync_battlemaster_maps"],
        [sys.executable, "scripts/audit_map_payloads.py", "--strict"],
    ]
    if compile_test:
        commands.append([sys.executable, "scripts/compile.py", "--test"])
    for command in commands:
        print("+ " + " ".join(command), flush=True)
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode:
            raise SyncError(f"post-write check failed with exit code {result.returncode}: {' '.join(command)}")


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    data = (json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(path, data)


def _selected_pack_keys(args: argparse.Namespace, parser: argparse.ArgumentParser) -> tuple[str, ...]:
    individual = {
        "bttf-ruins": args.bttf_ruins,
        "desert": args.desert,
        "bttf": args.bttf,
        "armageddon-ruins": args.armageddon_ruins,
        "lct-pack-1": args.lct_pack_1,
    }
    if args.all and (args.all_four or any(individual.values())):
        parser.error("--all cannot be combined with another pack selector")
    selected = set(PACKS) if args.all else {key for key, enabled in individual.items() if enabled}
    if args.all_four:
        selected.update(ALL_FOUR_KEYS)
    if not selected:
        parser.error("select at least one pack (for example --desert, --all-four, or --all)")
    return tuple(key for key in PACKS if key in selected)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch, reconstruct, validate, and install Battlemaster map packs outside TTS.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    selectors = parser.add_argument_group("pack selectors")
    selectors.add_argument("--all", action="store_true", help="All Four plus LCT Pack 1 (225 cards).")
    selectors.add_argument("--all-four", action="store_true", help="The four Battlemaster debug-button packs (180 cards).")
    selectors.add_argument("--bttf-ruins", action="store_true", help="Update Battlemaster BTTF Ruins (45 cards).")
    selectors.add_argument("--desert", action="store_true", help="Update Battlemaster Armageddon Desert (45 cards).")
    selectors.add_argument("--bttf", action="store_true", help="Update Battlemaster Grimdark/BTTF (45 cards).")
    selectors.add_argument("--armageddon-ruins", action="store_true", help="Update Battlemaster Armageddon Ruins (45 cards).")
    selectors.add_argument(
        "--lct-pack-1", "--lct-p1", dest="lct_pack_1", action="store_true",
        help="Update atomic Ice/Lava/Mars LCT Pack 1 (45 cards).",
    )
    parser.add_argument("--write", action="store_true", help="Apply the validated plan. Without this flag, preview only.")
    parser.add_argument("--snapshot-in", type=Path, help="Read API data from a prior snapshot instead of using the network.")
    parser.add_argument("--snapshot-out", type=Path, help="Write normalized fetched API data for a reproducible later apply.")
    parser.add_argument("--workers", type=int, default=6, help="Maximum concurrent public API requests.")
    parser.add_argument("--timeout", type=float, default=90, help="Timeout in seconds for each API request attempt.")
    parser.add_argument("--api-base", default=API_BASE, help="Battlemaster public API base URL.")
    parser.add_argument("--allow-missing-layout-art", action="store_true", help="Permit maps without a matching static layout-art card.")
    parser.add_argument(
        "--skip-compile-test", action="store_true",
        help="Skip compile.py --test after a write; all other checks still run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    pack_keys = _selected_pack_keys(args, parser)
    if args.workers < 1 or args.workers > 32:
        parser.error("--workers must be between 1 and 32")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.snapshot_in and args.snapshot_out and args.snapshot_in.resolve() == args.snapshot_out.resolve():
        parser.error("--snapshot-in and --snapshot-out must not be the same path")

    manifest_rows = legacy.load_manifest(MANIFEST_PATH)
    expected_pairs = set(legacy.source_bags_by_pair(manifest_rows))
    selection = ", ".join(PACKS[key].creator_display for key in pack_keys)
    print(f"Selected packs: {selection}")
    try:
        if args.snapshot_in:
            print(f"Reading API snapshot: {args.snapshot_in}")
            snapshot = json.loads(args.snapshot_in.read_text(encoding="utf-8"))
            validate_snapshot(snapshot, pack_keys, expected_pairs)
        else:
            snapshot = fetch_snapshot(
                pack_keys,
                expected_pairs,
                api_base=args.api_base,
                timeout=args.timeout,
                workers=args.workers,
            )
        digest = snapshot_digest(snapshot)
        print(f"Snapshot content SHA-256: {digest}")
        if args.snapshot_out:
            write_snapshot(args.snapshot_out, snapshot)
            print(f"Wrote snapshot: {args.snapshot_out}")

        print("Reconstructing maps and building an in-memory source update...", flush=True)
        plan = build_install_plan(
            snapshot,
            pack_keys,
            allow_missing_layout_art=args.allow_missing_layout_art,
        )
        print("Validating the complete prospective map inventory...", flush=True)
        _errors, warnings = validate_plan_with_project_validator(plan)
        print(
            f"Plan OK: {len(plan.payloads)} cards, {plan.terrain_objects:,} top-level terrain objects, "
            f"{plan.preserved_card_guids} card GUIDs preserved."
        )
        print(
            f"Changes: {plan.changed_cards} card records, {plan.changed_payloads} terrain payloads, "
            f"{len(plan.obsolete_payload_guids)} obsolete payloads; "
            f"{plan.reused_equivalent_payloads} byte-identical payloads retained; validator warnings: {warnings}."
        )
        if not args.write:
            print("[preview] No project files written. Re-run with --write to apply this exact selection.")
            if not args.snapshot_in and not args.snapshot_out:
                print("Tip: add --snapshot-out PATH, then use --snapshot-in PATH --write to apply identical API data.")
            return 0

        transaction = SourceTransaction(plan)
        try:
            print("Applying source transaction...", flush=True)
            transaction.apply()
            run_post_write_checks(compile_test=not args.skip_compile_test)
        except BaseException:
            if transaction.applied:
                print("A post-write check failed; restoring every affected source file...", file=sys.stderr)
                transaction.rollback()
            raise
        print(
            f"Installed {len(plan.payloads)} maps into {TARGET_PATH.relative_to(ROOT)}, "
            f"{MANIFEST_PATH.relative_to(ROOT)}, and {PAYLOAD_DIR.relative_to(ROOT)}/."
        )
        print("All automated checks passed; the compiled debug save is ready for the manual TTS smoke test.")
        return 0
    except (
        SyncError,
        reconstruction.ReconstructionError,
        OSError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
