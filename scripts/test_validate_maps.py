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
