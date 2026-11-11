"""The tower crane asset tool: every kit is exactly what it builds from its source."""

import json
import struct
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock
from tools import prepare_tower_crane_asset as prepare
from tools import tower_crane_kit as kit


def _metadata(data):
    length = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20 : 20 + length])["asset"]["extras"]["kit"]


class KitBuildGuardTests(unittest.TestCase):
    def test_every_shipped_kit_is_exactly_what_the_tool_builds_from_its_source(self):
        # The shipped file was built in an earlier run, so matching it also
        # shows that the build gives the same bytes every time.
        self.assertEqual(sorted(prepare.PROFILES), ["classic", "liebherr"])
        for model, profile in sorted(prepare.PROFILES.items()):
            with self.subTest(model=model), tempfile.TemporaryDirectory() as folder:
                missing = prepare.missing_source(model)
                if missing:
                    self.skipTest(missing)
                target = Path(folder) / "kit.glb"
                report = prepare.build_kit(model, target=target)
                self.assertEqual(target.read_bytes(), profile.TARGET.read_bytes())
                self.assertEqual(report["model"], model)
                self.assertLess(report["bytes"], kit.MAX_BYTES)
                self.assertEqual(
                    [p["name"] for p in report["parts"]], list(profile.PART_ORDER)
                )
                metadata = _metadata(target.read_bytes())
                self.assertEqual(metadata["version"], kit.KIT_VERSION)
                self.assertEqual(
                    metadata["model"], {"id": model, "label": profile.LABEL}
                )
                self.assertEqual(metadata["credit"], profile.CREDIT)
                self.assertEqual(list(metadata["parts"]), list(profile.PART_ORDER))

    def test_the_metadata_starts_with_the_model_and_its_credit(self):
        data = prepare.kit_metadata(prepare.PROFILES["liebherr"], {"mast": {}})
        self.assertEqual(list(data), ["version", "model", "credit", "mast"])
        self.assertEqual(data["model"]["id"], "liebherr")

    def test_a_missing_source_stops_the_build_and_says_where_to_download_it(self):
        profile = prepare.PROFILES["liebherr"]
        with tempfile.TemporaryDirectory() as folder:
            absent = Path(folder) / "liebherr_tower_crane.source.glb"
            target = Path(folder) / "kit.glb"
            error = StringIO()
            with mock.patch.object(profile, "SOURCE", absent):
                with redirect_stdout(StringIO()), redirect_stderr(error):
                    code = prepare.main(
                        ["--model", "liebherr", "--target", str(target)]
                    )
            self.assertEqual(code, 1)
            self.assertFalse(target.exists())
            message = error.getvalue()
            self.assertIn(str(absent), message)
            self.assertIn(profile.CREDIT["source_url"], message)
            self.assertIn("assets/models/README.md", message)
            # An explicit --source is checked the same way.
            self.assertIn(str(absent), prepare.missing_source("classic", absent))
            absent.write_bytes(b"glTF")
            self.assertIsNone(prepare.missing_source("classic", absent))

    def test_source_and_target_need_a_single_model(self):
        with redirect_stdout(StringIO()), self.assertRaises(SystemExit):
            prepare.main(["--target", "x.glb"])
        with redirect_stdout(StringIO()), self.assertRaises(SystemExit):
            prepare.main(["--model", "potain"])


if __name__ == "__main__":
    unittest.main()
