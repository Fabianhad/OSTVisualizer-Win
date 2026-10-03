import os
import re
import unittest
from tests.paths import REPO_ROOT

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.application_info import APPLICATION_VERSION


class MsiVersionDatabaseDescriptorTests(unittest.TestCase):
    def test_msi_script_extracts_version_from_application_info(self):
        root = REPO_ROOT
        script = (root / "build-msi.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("ost_visualizer\\application\\dtos\\application_info.py", script)
        pattern_match = re.search(
            r"\$VersionPattern = '([^']+)'",
            script,
        )
        self.assertIsNotNone(pattern_match)
        application_info = (
            root / "ost_visualizer/application/dtos/application_info.py"
        ).read_text(encoding="utf-8")
        version_match = re.search(pattern_match.group(1), application_info)
        self.assertIsNotNone(version_match)
        self.assertEqual(version_match.group(1), APPLICATION_VERSION)
        self.assertNotIn("Get-Command python", script)
