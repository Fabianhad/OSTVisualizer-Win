from ost_visualizer.infrastructure import app_paths
from unittest.mock import patch
from pathlib import Path
import os
import string
import unittest
import tempfile
import pywintypes
from win32com.shell import shellcon
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

    def test_default_working_directory_uses_fallback_when_drive_is_absent(self):
        absent_drive = next(
            f"{letter}:"
            for letter in reversed(string.ascii_uppercase)
            if not os.path.exists(f"{letter}:\\")
        )
        preferred = Path(f"{absent_drive}/OCS Documents/OST")
        fallback = Path("C:/fallback-working-directory/OST")
        with patch.object(app_paths, "_OST_WORKING_DIR", preferred), patch.object(
            app_paths,
            "_FALLBACK_WORKING_DIR",
            fallback,
        ):
            self.assertEqual(app_paths.get_default_working_dir(), fallback)

    def test_default_working_directory_keeps_preferred_when_drive_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            drive = Path(temp_dir).drive
            preferred = Path(f"{drive}/__missing_ost_folder__/OST")
            self.assertFalse(preferred.exists())
            with patch.object(app_paths, "_OST_WORKING_DIR", preferred), patch.object(
                app_paths,
                "_FALLBACK_WORKING_DIR",
                Path(temp_dir) / "Documents" / "OST",
            ):
                self.assertEqual(app_paths.get_default_working_dir(), preferred)


class HwidV1Tests(unittest.TestCase):
    def test_machine_data_path_uses_programdata_known_folder(self):
        with patch(
            "win32com.shell.shell.SHGetKnownFolderPath",
            return_value=r"C:\ProgramData",
        ) as known_folder:
            path = get_machine_app_data_dir()
        self.assertEqual(path, Path(r"C:\ProgramData\OST Visualizer"))
        known_folder.assert_called_once_with(shellcon.FOLDERID_ProgramData, 0, None)

    def test_machine_data_path_resolves_real_programdata_folder(self):
        self.assertEqual(
            get_machine_app_data_dir(),
            Path(os.environ["ProgramData"]) / "OST Visualizer",
        )

    def test_machine_data_path_failure_has_no_user_scoped_fallback(self):
        with patch(
            "win32com.shell.shell.SHGetKnownFolderPath",
            side_effect=pywintypes.com_error(-1, "unavailable", None, None),
        ):
            with self.assertRaisesRegex(OSError, "machine data directory") as raised:
                get_machine_app_data_dir()
        self.assertIsInstance(raised.exception.__cause__, pywintypes.com_error)

    def test_machine_data_path_os_error_has_no_user_scoped_fallback(self):
        failure = OSError("known folder blocked")
        with patch("win32com.shell.shell.SHGetKnownFolderPath", side_effect=failure):
            with self.assertRaisesRegex(OSError, "machine data directory") as raised:
                get_machine_app_data_dir()
        self.assertIs(raised.exception.__cause__, failure)

    def test_machine_data_path_empty_result_is_unavailable(self):
        for empty in ("", None):
            with self.subTest(result=empty):
                with patch(
                    "win32com.shell.shell.SHGetKnownFolderPath", return_value=empty
                ):
                    with self.assertRaisesRegex(OSError, "machine data directory"):
                        get_machine_app_data_dir()
