#!/usr/bin/env python3
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
import validate_maps


ROOT = SCRIPT_DIR.parent
SAVE_PATH = ROOT / "TTSJSON" / "ftc_base.json"
MANIFEST_PATH = ROOT / "TTSJSON" / "map_manifest.csv"


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
        self.assertEqual(15, len(ctx.cards))
        self.assertEqual([], [i for i in issues if i.level == validate_maps.ERROR])

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
