#!/usr/bin/env python3
import copy
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import battlemaster_reconstruct as reconstruct
import import_battlemaster_static_maps as legacy
import sync_battlemaster_maps as sync
import validate_maps


def synthetic_catalogs():
    child = {
        "GUID": "abcdef",
        "Name": "Custom_Model",
        "Transform": {
            "posX": 1, "posY": 2, "posZ": 3,
            "rotX": 0, "rotY": 0, "rotZ": 0,
            "scaleX": 1, "scaleY": 1, "scaleZ": 1,
        },
        "GMNotes": "BattlemasterCalibrationAsset",
        "Locked": False,
    }
    alternate = {
        "GUID": "fedcba",
        "Name": "Custom_Model",
        "Transform": {
            "posX": 99, "posY": 99, "posZ": 99,
            "rotX": 99, "rotY": 99, "rotZ": 99,
            "scaleX": 9, "scaleY": 9, "scaleZ": 9,
        },
        "GMNotes": "BattlemasterCalibrationAsset",
        "LuaScript": "old",
        "LuaScriptState": "old",
        "XmlUI": "old",
        "ContainedObjects": [copy.deepcopy(child)],
    }
    template_catalog = {
        "p": ["wall-ref"],
        "q": [["Light Wall", "dense", "corner"]],
        "t": [[
            "template-1",
            6.003,
            2.003,
            [[0, 0, 0, 0, 0, "l", "wall"]],
        ]],
    }
    theme_catalog = {
        "u": ["mesh-url", "diffuse-url", "normal-url", "collider-url", "mat-url", "floor-url"],
        "p": ["wall-ref"],
        "q": [["Light Wall", "dense", "corner"]],
        "m": [[
            0, "m", 0, 1, 2, 3,
            {
                "o": [1, 0],
                "sc": [2, 1, 2],
                "y": 1.25,
                "ro": 180,
                "ch": [child],
                "st": {"2": alternate},
            },
        ]],
        "b": ["Synthetic Mat", 4, 60, 44],
        "t": [5, -1, 1],
    }
    payload = {"i": [[0, 10, 20, 90, 0, "hb+c1"]]}
    return template_catalog, theme_catalog, payload


def synthetic_lct_snapshot(pairs):
    themes = {}
    payloads = {}
    for theme_slice in sync.PACKS["lct-pack-1"].themes:
        slot = theme_slice.slots[0]
        layouts = []
        for pair in sorted(pairs):
            layout_key = f"layout-{pair}-{slot}"
            layouts.append({
                "forcePairKey": pair,
                "layoutKey": layout_key,
                "chapterApprovedSlot": {"slotIndex": slot},
                "chapterApprovedDeploymentKey": 1,
                "previewUrl": "https://example.invalid/card.png",
            })
            payloads[sync._payload_key(pair, slot)] = {
                "layoutKey": layout_key,
                "litePayload": {"i": []},
            }
        themes[theme_slice.theme_id] = {
            "metadata": {"id": theme_slice.theme_id},
            "themeKey": theme_slice.theme_id + "@1",
            "themeCatalog": {"m": [], "u": []},
            "catalogKey": "catalog@1",
            "layouts": layouts,
        }
    return {
        "schemaVersion": sync.SNAPSHOT_SCHEMA_VERSION,
        "fetchedAt": "2026-08-27T00:00:00+00:00",
        "apiBase": sync.API_BASE,
        "owner": sync.OWNER,
        "selectedPacks": ["lct-pack-1"],
        "templateCatalogKey": "templates@1",
        "templateCatalog": {"t": []},
        "themes": themes,
        "layoutPayloads": payloads,
    }


class BattlemasterReconstructionTest(unittest.TestCase):
    def test_reconstruction_is_deterministic_and_preserves_lua_contracts(self):
        template_catalog, theme_catalog, payload = synthetic_catalogs()
        first = reconstruct.reconstruct_objects(
            template_catalog,
            theme_catalog,
            payload,
            "synthetic-map",
        )
        second = reconstruct.reconstruct_objects(
            template_catalog,
            theme_catalog,
            payload,
            "synthetic-map",
        )

        self.assertEqual(first, second)
        self.assertEqual(3, first.spawned)
        self.assertEqual(0, first.skipped)
        battlemat, plate, ruin = first.objects
        self.assertEqual(["battlemaster_battlemat"], battlemat["Tags"])
        self.assertFalse(battlemat["Interactable"])
        short_line = next(asset for asset in reconstruct.TERRAIN_ASSETS if asset["id"] == "short-line")
        self.assertEqual("Custom_Assetbundle", plate["Name"])
        self.assertNotIn("CustomMesh", plate)
        self.assertEqual(short_line["rugged"], plate["CustomAssetbundle"]["AssetbundleURL"])
        self.assertEqual({"2"}, set(plate["States"]))
        self.assertEqual(short_line["smooth"], plate["States"]["2"]["CustomAssetbundle"]["AssetbundleURL"])
        self.assertEqual(["obj_home_blue", "obj_center1"], plate["Tags"])
        self.assertEqual(plate["Tags"], plate["States"]["2"]["Tags"])
        sync._validate_footprint_contract(
            first.objects,
            reconstruct.FOOTPRINT_PROFILE_BATTLEMASTER,
            expected_count=1,
            label="synthetic standard map",
        )
        self.assertEqual("Light Wall", ruin["Nickname"])
        self.assertEqual("Light", ruin["Description"])
        self.assertEqual("", ruin["ChildObjects"][0]["GMNotes"])
        self.assertTrue(ruin["ChildObjects"][0]["Locked"])
        self.assertEqual(ruin["Transform"], ruin["States"]["2"]["Transform"])
        self.assertEqual("", ruin["States"]["2"]["LuaScript"])
        guid_values = sync._all_object_guid_values(first.objects)
        self.assertEqual(len(guid_values), len(set(guid_values)))

    def test_lct_profile_adds_custom_bordered_state_before_battlemaster_terrains(self):
        template_catalog, theme_catalog, payload = synthetic_catalogs()
        result = reconstruct.reconstruct_objects(
            template_catalog,
            theme_catalog,
            payload,
            "synthetic-map",
            footprint_profile=reconstruct.FOOTPRINT_PROFILE_LCT,
        )
        plate = result.objects[1]
        short_line = next(asset for asset in reconstruct.TERRAIN_ASSETS if asset["id"] == "short-line")
        self.assertEqual("Custom_Model", plate["Name"])
        self.assertTrue(plate["CustomMesh"]["MeshURL"].endswith("01-shortline-5mm-border.obj"))
        self.assertEqual("floor-url", plate["CustomMesh"]["DiffuseURL"])
        self.assertEqual({"2", "3"}, set(plate["States"]))
        self.assertEqual(short_line["rugged"], plate["States"]["2"]["CustomAssetbundle"]["AssetbundleURL"])
        self.assertEqual(short_line["smooth"], plate["States"]["3"]["CustomAssetbundle"]["AssetbundleURL"])
        self.assertEqual(plate["Tags"], plate["States"]["2"]["Tags"])
        self.assertEqual(plate["Tags"], plate["States"]["3"]["Tags"])
        sync._validate_footprint_contract(
            result.objects,
            reconstruct.FOOTPRINT_PROFILE_LCT,
            expected_count=1,
            label="synthetic LCT map",
        )

    def test_footprint_preflight_rejects_wrong_state_count(self):
        template_catalog, theme_catalog, payload = synthetic_catalogs()
        result = reconstruct.reconstruct_objects(
            template_catalog,
            theme_catalog,
            payload,
            "synthetic-map",
        )
        result.objects[1]["States"]["3"] = copy.deepcopy(result.objects[1]["States"]["2"])
        with self.assertRaisesRegex(sync.SyncError, "must contain only Battlemaster state 2"):
            sync._validate_footprint_contract(
                result.objects,
                reconstruct.FOOTPRINT_PROFILE_BATTLEMASTER,
                expected_count=1,
                label="broken map",
            )

    def test_unknown_footprint_profile_is_rejected(self):
        template_catalog, theme_catalog, payload = synthetic_catalogs()
        with self.assertRaisesRegex(reconstruct.ReconstructionError, "unknown footprint profile"):
            reconstruct.reconstruct_objects(
                template_catalog,
                theme_catalog,
                payload,
                "synthetic-map",
                footprint_profile="typo",
            )

    def test_missing_theme_mapping_is_counted_as_loss(self):
        template_catalog, theme_catalog, payload = synthetic_catalogs()
        theme_catalog["m"] = []
        result = reconstruct.reconstruct_objects(template_catalog, theme_catalog, payload, "lossy")
        self.assertEqual(2, result.spawned)
        self.assertEqual(1, result.skipped)

    def test_lua_rounding_behavior_is_used_for_negative_values(self):
        self.assertEqual(-0.000001, reconstruct.round6(-0.0000006))
        self.assertEqual(0.0, reconstruct.round6(-0.0000004))

    def test_compact_entries_are_valid_json(self):
        template_catalog, theme_catalog, payload = synthetic_catalogs()
        result = reconstruct.reconstruct_objects(template_catalog, theme_catalog, payload, "json")
        entries = result.compact_json_entries()
        self.assertEqual(result.objects, [json.loads(entry) for entry in entries])

    def test_terrain_assets_match_live_battlemaster_two_state_capture(self):
        """Golden data verified against Legacy/qq2.json, a live TTS capture of
        Battlemaster's own spawner output (every piece tagged
        GMNotes="BattlemasterSpawned"). All 16 footprint plates in that capture,
        across all 5 known shapes, were rugged-as-default/smooth-as-state-2 with
        these exact asset URLs -- confirming the battlemaster-two-state profile
        matches what Battlemaster actually ships, not just this repo's guess.
        Legacy/ is not tracked in git, so the pairs are pinned here rather than
        read from that file at test time.
        """
        verified_pairs = {
            "big-rect": (
                "https://steamusercontent-a.akamaihd.net/ugc/17340806108804505934/4B46C3DBA9709342C6038E6C339E9183773F7F4F/",
                "https://steamusercontent-a.akamaihd.net/ugc/18109999757297310215/5DB2EDC94302F2260A40CDE398054AB73C583B2D/",
            ),
            "long-line": (
                "https://steamusercontent-a.akamaihd.net/ugc/14084050877596722482/ED735D1BA2BA036645A039BBE2884DC6097D52FF/",
                "https://steamusercontent-a.akamaihd.net/ugc/12173066766016705494/E81DD809081B33CC73B332024FC1D4672A2EE2BC/",
            ),
            "short-line": (
                "https://steamusercontent-a.akamaihd.net/ugc/15633617285222415204/5306AA649D2877AFEF7FEBDFCE3052F6E9977E98/",
                "https://steamusercontent-a.akamaihd.net/ugc/16079218023307560393/A11A66EA4B73E650059F86573FCA12C91492E2B0/",
            ),
            "small-rect": (
                "https://steamusercontent-a.akamaihd.net/ugc/12322865955445680032/0919B948C303AE084AD0661B3EDE36FCCBF28FCF/",
                "https://steamusercontent-a.akamaihd.net/ugc/16918139172926584908/8C6BC64D270CD20FEEA73D40FBD80633CC72A532/",
            ),
            "triangle": (
                "https://steamusercontent-a.akamaihd.net/ugc/13344184635215212518/9E3478CBEB46A6B7D03864CCC680D7E37F14B660/",
                "https://steamusercontent-a.akamaihd.net/ugc/10828923269080544043/F6E563E60C9A956892D734DEA30B43B38BB83B50/",
            ),
        }
        self.assertEqual({asset["id"] for asset in reconstruct.TERRAIN_ASSETS}, set(verified_pairs))
        for asset in reconstruct.TERRAIN_ASSETS:
            rugged, smooth = verified_pairs[asset["id"]]
            self.assertEqual(rugged, asset["rugged"], f"{asset['id']} rugged URL diverged from the verified capture")
            self.assertEqual(smooth, asset["smooth"], f"{asset['id']} smooth URL diverged from the verified capture")


class BattlemasterSyncTest(unittest.TestCase):
    def _parse_selection(self, *arguments):
        parser = sync.build_parser()
        args = parser.parse_args(list(arguments))
        return sync._selected_pack_keys(args, parser)

    def test_all_selector_includes_every_configured_pack(self):
        self.assertEqual(tuple(sync.PACKS), self._parse_selection("--all"))

    def test_all_battlemaster_can_be_combined_with_lct_pack_one(self):
        self.assertEqual(tuple(sync.PACKS), self._parse_selection("--all-battlemaster", "--lct-p1"))

    def test_deprecated_all_four_alias_still_selects_current_battlemaster_packs(self):
        self.assertEqual(sync.BATTLEMASTER_PACK_KEYS, self._parse_selection("--all-four"))

    def test_granular_selectors_can_be_combined(self):
        self.assertEqual(("bttf", "armageddon-ruins"), self._parse_selection("--bttf", "--armageddon-ruins"))

    def test_generic_pack_selector_tracks_pack_configuration(self):
        self.assertEqual(
            ("bttf-ruins", "armageddon-ruins"),
            self._parse_selection("--pack", "armageddon-ruins", "--pack", "bttf-ruins"),
        )

    def test_pack_configuration_matches_legacy_fallback(self):
        new_standalone = [sync.PACKS[key] for key in sync.BATTLEMASTER_PACK_KEYS]
        self.assertEqual(
            [config["theme_id"] for config in legacy.KNOWN_BATTLEMASTER_THEMES],
            [pack.themes[0].theme_id for pack in new_standalone],
        )
        self.assertEqual(
            [config["creator_tag"] for config in legacy.KNOWN_BATTLEMASTER_THEMES],
            [pack.creator_tag for pack in new_standalone],
        )
        self.assertEqual(
            [(config["theme_id"], config["slot"]) for config in legacy.LCT_PACK_1_SLOT_THEMES],
            [(theme.theme_id, theme.slots[0]) for theme in sync.PACKS["lct-pack-1"].themes],
        )
        self.assertTrue(all(
            pack.footprint_profile == reconstruct.FOOTPRINT_PROFILE_BATTLEMASTER
            for pack in new_standalone
        ))
        self.assertEqual(
            reconstruct.FOOTPRINT_PROFILE_LCT,
            sync.PACKS["lct-pack-1"].footprint_profile,
        )

    def test_all_rejects_redundant_selector(self):
        parser = sync.build_parser()
        args = parser.parse_args(["--all", "--bttf"])
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                sync._selected_pack_keys(args, parser)

    def test_lct_snapshot_composes_exact_theme_by_slot(self):
        pairs = {f"force-{index}|force-{index}" for index in range(sync.EXPECTED_PAIR_COUNT)}
        snapshot = synthetic_lct_snapshot(pairs)
        records = sync.records_from_snapshot(snapshot, ("lct-pack-1",), pairs)
        self.assertEqual(45, len(records))
        theme_by_slot = {
            theme.slots[0]: theme.theme_id
            for theme in sync.PACKS["lct-pack-1"].themes
        }
        counts = {}
        for record in records:
            counts[record.slot] = counts.get(record.slot, 0) + 1
            self.assertEqual(theme_by_slot[record.slot], record.theme.theme_id)
        self.assertEqual({1: 15, 2: 15, 3: 15}, counts)

    def test_lct_snapshot_rejects_an_incomplete_theme_before_install(self):
        pairs = {f"force-{index}|force-{index}" for index in range(sync.EXPECTED_PAIR_COUNT)}
        snapshot = synthetic_lct_snapshot(pairs)
        ice_id = sync.PACKS["lct-pack-1"].themes[0].theme_id
        snapshot["themes"][ice_id]["layouts"].pop()
        with self.assertRaisesRegex(sync.SyncError, "not a complete 15-pair set"):
            sync.records_from_snapshot(snapshot, ("lct-pack-1",), pairs)

    def test_snapshot_rejects_catalog_payload_version_mismatch(self):
        pairs = {f"force-{index}|force-{index}" for index in range(sync.EXPECTED_PAIR_COUNT)}
        snapshot = synthetic_lct_snapshot(pairs)
        first_key = sorted(snapshot["layoutPayloads"])[0]
        snapshot["layoutPayloads"][first_key]["layoutKey"] = "different-layout"
        with self.assertRaisesRegex(sync.SyncError, "snapshot mismatch"):
            sync.records_from_snapshot(snapshot, ("lct-pack-1",), pairs)

    def test_snapshot_rejects_catalog_payload_id_mismatch(self):
        pairs = {f"force-{index}|force-{index}" for index in range(sync.EXPECTED_PAIR_COUNT)}
        snapshot = synthetic_lct_snapshot(pairs)
        ice_id = sync.PACKS["lct-pack-1"].themes[0].theme_id
        layout = snapshot["themes"][ice_id]["layouts"][0]
        layout["id"] = "catalog-layout"
        key = sync._payload_key(layout["forcePairKey"], 1)
        snapshot["layoutPayloads"][key]["layoutId"] = "payload-layout"
        with self.assertRaisesRegex(sync.SyncError, "catalog layout id"):
            sync.validate_snapshot(snapshot, ("lct-pack-1",), pairs)

    def test_declared_count_must_match_response_contents(self):
        with self.assertRaisesRegex(sync.SyncError, "declares instanceCount=2, but contains 1"):
            sync._check_declared_count({"instanceCount": 2}, "instanceCount", 1, "payload")

    def test_upstream_skips_are_rejected(self):
        with self.assertRaisesRegex(sync.SyncError, "refusing a lossy snapshot"):
            sync._check_no_upstream_skips({"skippedRuins": [{"id": "ruin"}]}, "skippedRuins", "payload")

    def test_snapshot_digest_ignores_fetch_timestamp(self):
        pairs = {f"force-{index}|force-{index}" for index in range(sync.EXPECTED_PAIR_COUNT)}
        first = synthetic_lct_snapshot(pairs)
        second = copy.deepcopy(first)
        second["fetchedAt"] = "2099-01-01T00:00:00+00:00"
        self.assertEqual(sync.snapshot_digest(first), sync.snapshot_digest(second))

    def test_payload_builder_rejects_lua_long_string_terminator(self):
        with self.assertRaisesRegex(sync.SyncError, "long-string terminator"):
            sync._payload_text(['{"bad":"]]"}'])

    def test_semantically_unchanged_payload_keeps_existing_bytes_and_guids(self):
        old = 'objectJSONs = {\r\n  [[{"Name":"BlockSquare","GUID":"abcdef"}]],\r\n}\r\n'
        reconstructed = [{"GUID": "123456", "Name": "BlockSquare"}]
        self.assertIs(old, sync._reuse_equivalent_payload(old, reconstructed))

    def test_payload_reuse_detects_real_content_change(self):
        old = 'objectJSONs = {\n  [[{"GUID":"abcdef","Name":"BlockSquare"}]],\n}\n'
        reconstructed = [{"GUID": "123456", "Name": "Custom_Model"}]
        self.assertIsNone(sync._reuse_equivalent_payload(old, reconstructed))

    def test_temporary_validation_overlay_is_python_39_compatible(self):
        payload = "objectJSONs = {\r\n}\r\n"
        plan = sync.InstallPlan(
            target={"ObjectStates": []},
            manifest_rows=[],
            payloads={"abcdef": payload},
            obsolete_payload_guids=set(),
            selected_pack_keys=("bttf",),
            replaced_cards=0,
            preserved_card_guids=0,
            changed_cards=0,
            changed_payloads=1,
            reused_equivalent_payloads=0,
            terrain_objects=0,
            target_bytes=b"{}\n",
            manifest_bytes=b"deck_guid,deck_name,card_guid,card_name,map_creator_tag,map_type_tag,creator_display,eligible\n",
        )
        observed = {}

        def inspect_overlay(*_args, **_kwargs):
            observed["payload"] = (validate_maps.MAP_PAYLOAD_DIR / "abcdef.lua").read_bytes()
            return [], None

        original_payload_dir = validate_maps.MAP_PAYLOAD_DIR
        with tempfile.TemporaryDirectory() as temp_name:
            empty_payload_dir = Path(temp_name) / "source-maps"
            empty_payload_dir.mkdir()
            with (
                mock.patch.object(sync, "PAYLOAD_DIR", empty_payload_dir),
                mock.patch.object(validate_maps, "validate", side_effect=inspect_overlay),
            ):
                self.assertEqual((0, 0), sync.validate_plan_with_project_validator(plan))

        self.assertEqual(payload.encode("utf-8"), observed["payload"])
        self.assertIs(original_payload_dir, validate_maps.MAP_PAYLOAD_DIR)

    def test_source_transaction_can_restore_replacements_and_deletions(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            target = root / "ftc_base.json"
            manifest = root / "map_manifest.csv"
            payload_dir = root / "maps"
            payload_dir.mkdir()
            target.write_bytes(b"old-target")
            manifest.write_bytes(b"old-manifest")
            (payload_dir / "aaaaaa.lua").write_bytes(b"old-obsolete")
            plan = sync.InstallPlan(
                target={},
                manifest_rows=[],
                payloads={"bbbbbb": "new-payload"},
                obsolete_payload_guids={"aaaaaa"},
                selected_pack_keys=("bttf",),
                replaced_cards=45,
                preserved_card_guids=45,
                changed_cards=1,
                changed_payloads=1,
                reused_equivalent_payloads=0,
                terrain_objects=1,
                target_bytes=b"new-target",
                manifest_bytes=b"new-manifest",
            )
            with (
                mock.patch.object(sync, "TARGET_PATH", target),
                mock.patch.object(sync, "MANIFEST_PATH", manifest),
                mock.patch.object(sync, "PAYLOAD_DIR", payload_dir),
            ):
                transaction = sync.SourceTransaction(plan)
                transaction.apply()
                self.assertEqual(b"new-target", target.read_bytes())
                self.assertEqual(b"new-manifest", manifest.read_bytes())
                self.assertEqual(b"new-payload", (payload_dir / "bbbbbb.lua").read_bytes())
                self.assertFalse((payload_dir / "aaaaaa.lua").exists())
                transaction.rollback()
                self.assertEqual(b"old-target", target.read_bytes())
                self.assertEqual(b"old-manifest", manifest.read_bytes())
                self.assertEqual(b"old-obsolete", (payload_dir / "aaaaaa.lua").read_bytes())
                self.assertFalse((payload_dir / "bbbbbb.lua").exists())


if __name__ == "__main__":
    unittest.main()
