import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.infrastructure import app_paths


class AppPathsTests(unittest.TestCase):
    def test_default_working_directory_prefers_configured_ost_location(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preferred = root / "OCS Documents" / "OST"
            preferred.mkdir(parents=True)
            fallback = root / "Documents" / "OST"
            with patch.object(app_paths, "_OST_WORKING_DIR", preferred), patch.object(
                app_paths,
                "_FALLBACK_WORKING_DIR",
                fallback,
            ):
                self.assertEqual(app_paths.get_default_working_dir(), preferred)

    def test_default_working_directory_uses_fallback_when_preferred_is_unavailable(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            preferred = Path("__unavailable_ost_working_directory__") / "OST"
            fallback = root / "Documents" / "OST"
            with patch.object(app_paths, "_OST_WORKING_DIR", preferred), patch.object(
                app_paths,
                "_FALLBACK_WORKING_DIR",
                fallback,
            ):
                self.assertEqual(app_paths.get_default_working_dir(), fallback)


if __name__ == "__main__":
    unittest.main()
