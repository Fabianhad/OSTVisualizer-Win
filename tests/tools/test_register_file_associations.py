"""CLI routing and defaults without modifying the Windows registry."""

import io
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import register_file_associations as cli


class FileAssociationCliTests(unittest.TestCase):
    def test_explicit_registration_and_unregistration_keep_requested_paths(self):
        for unregister in (False, True):
            with self.subTest(unregister=unregister):
                args = ["--exe", "custom.exe", "--script", "entry.py"]
                if unregister:
                    args.append("--unregister")
                with patch.object(cli, "FileAssociationRegistrar") as factory:
                    with patch("sys.stdout", new=io.StringIO()):
                        self.assertEqual(cli.main(args), 0)
                    factory.assert_called_once_with(
                        executable_path=Path("custom.exe"),
                        app_script_path=Path("entry.py"),
                    )
                    if unregister:
                        factory.return_value.unregister.assert_called_once_with()
                        factory.return_value.register.assert_not_called()
                    else:
                        factory.return_value.register.assert_called_once_with()
                        factory.return_value.unregister.assert_not_called()

    def test_registry_failure_has_nonzero_exit_and_error_output(self):
        with patch.object(cli, "FileAssociationRegistrar") as factory:
            factory.return_value.register.side_effect = OSError("denied")
            with patch("sys.stderr", new_callable=io.StringIO) as errors:
                self.assertEqual(cli.main(["--exe", "custom.exe"]), 1)
            self.assertIn("denied", errors.getvalue())

    def test_packaged_executable_is_preferred_only_when_present(self):
        with patch.object(cli.sys, "executable", "python.exe"):
            with patch.object(Path, "exists", return_value=True):
                self.assertEqual(
                    cli._default_executable(),
                    cli.ROOT / "dist_visualizer" / "Visualizer.dist" / "Visualizer.exe",
                )
            with patch.object(Path, "exists", return_value=False):
                self.assertEqual(cli._default_executable(), Path("python.exe"))
        with patch.object(cli.sys, "executable", "custom.exe"):
            self.assertEqual(cli._default_executable(), Path("custom.exe"))

    def test_script_default_belongs_only_to_development_python_invocation(self):
        with patch.object(Path, "exists", return_value=True):
            self.assertEqual(
                cli._default_script_path(Path("python.exe")), cli.ROOT / "Visualizer.py"
            )
            self.assertIsNone(cli._default_script_path(Path("Visualizer.exe")))
        with patch.object(Path, "exists", return_value=False):
            self.assertIsNone(cli._default_script_path(Path("python.exe")))
