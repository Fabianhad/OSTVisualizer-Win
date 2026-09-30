from ost_visualizer.infrastructure import app_paths
from unittest.mock import patch
from pathlib import Path
import unittest
import tempfile
import pywintypes
from ost_visualizer.infrastructure.app_paths import get_machine_app_data_dir


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


class HwidV1Tests(unittest.TestCase):
    def test_machine_data_path_uses_programdata_known_folder(self):
        with patch(
            "win32com.shell.shell.SHGetKnownFolderPath",
            return_value=r"C:\ProgramData",
        ):
            path = get_machine_app_data_dir()
        self.assertEqual(path, Path(r"C:\ProgramData\OST Visualizer"))

    def test_machine_data_path_failure_has_no_user_scoped_fallback(self):
        with patch(
            "win32com.shell.shell.SHGetKnownFolderPath",
            side_effect=pywintypes.com_error(-1, "unavailable", None, None),
        ):
            with self.assertRaisesRegex(OSError, "machine data directory"):
                get_machine_app_data_dir()
