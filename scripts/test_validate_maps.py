#!/usr/bin/env python3
import contextlib
import copy
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
import validate_maps
import compile as compile_script


ROOT = SCRIPT_DIR.parent
SAVE_PATH = ROOT / "TTSJSON" / "ftc_base.json"
MANIFEST_PATH = ROOT / "data" / "map_manifest.csv"


def find_guid(objects, guid):
    for obj in objects:
        if obj.get("GUID") == guid:
            return obj
        found = find_guid(obj.get("ContainedObjects", []), guid)
        if found:
            return found
    return None


class ValidateMapsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.object_states = json.loads(SAVE_PATH.read_text())["ObjectStates"]

    def test_strict_manifest_and_publishing_tags_pass(self):
        issues, ctx = validate_maps.validate(self.object_states, require_map_tags=True)
        manifest_rows, manifest_issues = validate_maps.load_map_manifest(MANIFEST_PATH)
        self.assertEqual([], manifest_issues)
        self.assertEqual(len(manifest_rows), len(ctx.cards))
        self.assertEqual([], [i for i in issues if i.level == validate_maps.ERROR])

    def test_creator_variant_decks_cover_all_layouts(self):
        for deck_guid in ("6e0d78", "109a6b", "1e6711", "cfeba5", "eae80b"):
            deck = find_guid(self.object_states, deck_guid)
            variants = {1: [], 2: [], 3: []}
            for card in deck["ContainedObjects"]:
                match = re.search(r"\s([123])\s*-\s*", card["Nickname"])
                self.assertIsNotNone(match, card["Nickname"])
                variants[int(match.group(1))].append(card)

            self.assertEqual({1: 2, 2: 2, 3: 2},
                             {layout: len(cards) for layout, cards in variants.items()})
            for cards in variants.values():
                creators = {tag for card in cards for tag in card.get("Tags", [])
                            if tag.startswith("map_crt_")}
                self.assertEqual({"map_crt_belgium", "map_crt_cr5sh"}, creators)

    def test_duplicate_layout_art_name_is_an_error(self):
        states = copy.deepcopy(self.object_states)
        deck = find_guid(states, validate_maps.LAYOUT_ART_DECK_GUID)
        duplicate = copy.deepcopy(find_guid(states, "061a28"))
        duplicate["GUID"] = "ffffff"
        deck["ContainedObjects"].append(duplicate)

        issues, _ = validate_maps.validate(states)
        matching = [i for i in issues if "multiple helper cards match" in i.message]
        self.assertEqual(1, len(matching))
        self.assertEqual(validate_maps.ERROR, matching[0].level)

    def test_back_to_selection_snapshots_loose_maps_worldwide(self):
        lua = (ROOT / "TTSLUA" / "startMenu.ttslua").read_text()
        start = lua.index("function captureRestorePoint()")
        end = lua.index("function backToSelection()", start)
        capture = lua[start:end]
        self.assertIn("for _, obj in ipairs(getAllObjects()) do", capture)
        self.assertIn('obj.hasTag("map")', capture)
        self.assertNotIn('slot.role == "deployment"', capture)

    def test_runtime_creator_suffix_parser_preserves_separator(self):
        lua = (ROOT / "TTSLUA" / "startMenu.ttslua").read_text()
        self.assertIn('local normalizedSuffix = suffix:lower()', lua)
        self.assertIn('normalized:sub(-#normalizedSuffix) == normalizedSuffix', lua)

    def test_creator_suffix_is_removed_from_logical_name(self):
        self.assertEqual(
            "TnH vs Rec 1 - Tipping Point",
            validate_maps.map_logical_name(
                "TnH vs Rec 1 - Tipping Point - Cra5shnatural"
            ),
        )
        self.assertEqual(
            "TnH vs Rec 1 - Tipping Point",
            validate_maps.map_logical_name(
                "TnH vs Rec 1 - Tipping Point - Team Belgium"
            ),
        )

    def test_creator_suffix_must_match_creator_tag(self):
        states = copy.deepcopy(self.object_states)
        card = find_guid(states, "c1d1af")
        card["Nickname"] = card["Nickname"].replace("Team Belgium", "Cra5shnatural")

        issues, _ = validate_maps.validate(states)
        matching = [i for i in issues if "c1d1af" in i.where and "nickname must end with" in i.message]
        self.assertEqual(1, len(matching))
        self.assertEqual(validate_maps.ERROR, matching[0].level)

    def test_manifest_creator_tag_mismatch_reports_card_guid(self):
        lines = MANIFEST_PATH.read_text().splitlines()
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "map_manifest.csv"
            manifest.write_text("\n".join(
                line.replace("map_crt_belgium", "map_crt_wrong") if ",c1d1af," in line else line
                for line in lines
            ) + "\n")
            issues, _ = validate_maps.validate(self.object_states, manifest_path=manifest)

        matching = [i for i in issues if "c1d1af" in i.where and "map_creator_tag" in i.message]
        self.assertEqual(1, len(matching))
        self.assertEqual(validate_maps.ERROR, matching[0].level)

    def test_map_type_tag_is_required_and_matches_manifest(self):
        states = copy.deepcopy(self.object_states)
        card = find_guid(states, "c1d1af")
        card["Tags"].remove("map_type_comp")

        issues, _ = validate_maps.validate(states, require_map_tags=True)
        matching = [i for i in issues if "c1d1af" in i.where and "map_type" in i.message]
        self.assertTrue(matching)
        self.assertTrue(all(i.level == validate_maps.ERROR for i in matching))

    def test_map_statistics_describe_current_inventory(self):
        _, ctx = validate_maps.validate(self.object_states, require_map_tags=True)
        stats = validate_maps.map_statistics(ctx)
        self.assertEqual(48, stats["cards"])
        self.assertEqual(33, stats["logical_layouts"])
        self.assertEqual(11, stats["source_containers"])
        self.assertEqual({"comp": 48}, dict(stats["map_types"]))
        self.assertEqual(19, stats["mapped_matchups"])
        self.assertEqual(25, stats["total_matchups"])
        self.assertGreater(stats["terrain_total"], 0)

    def test_compile_summary_includes_map_statistics(self):
        issues, ctx = validate_maps.validate(self.object_states, require_map_tags=True)
        output = io.StringIO()
        old_warnings = list(compile_script.WARNINGS)
        compile_script.WARNINGS.clear()
        try:
            with contextlib.redirect_stdout(output):
                compile_script.print_summary(
                    "test", True, [], [], ctx, issues, 48, Path("preview.json"), None
                )
        finally:
            compile_script.WARNINGS[:] = old_warnings

        report = output.getvalue()
        self.assertIn("Map inventory", report)
        self.assertIn("Map creators", report)
        self.assertIn("Map types", report)
        self.assertIn("Map matchups", report)
        self.assertIn("Terrain payload", report)

    def test_missing_creator_tag_reports_card_guid(self):
        states = copy.deepcopy(self.object_states)
        card = find_guid(states, "c1d1af")
        card["Tags"] = ["map"]

        issues, _ = validate_maps.validate(states, require_map_tags=True)
        matching = [i for i in issues if "c1d1af" in i.where and "map_crt*" in i.message]
        self.assertEqual(1, len(matching))
        self.assertEqual(validate_maps.ERROR, matching[0].level)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            validate_maps.report(matching, None)
        self.assertIn("c1d1af", output.getvalue())

    def test_unlisted_map_card_is_manifest_error(self):
        lines = MANIFEST_PATH.read_text().splitlines()
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "map_manifest.csv"
            manifest.write_text("\n".join(line for line in lines if ",c1d1af," not in line) + "\n")
            issues, _ = validate_maps.validate(self.object_states, manifest_path=manifest)

        matching = [i for i in issues if "c1d1af" in i.where and "missing from map_manifest.csv" in i.message]
        self.assertEqual(1, len(matching))
        self.assertEqual(validate_maps.ERROR, matching[0].level)


if __name__ == "__main__":
    unittest.main()
