"""CLI routing and defaults without modifying the Windows registry."""

import io
import unittest
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.infrastructure.windows.file_associations import (
    FileAssociationRegistryError,
)
from tools import register_file_associations as cli


class FileAssociationCliTests(unittest.TestCase):
    def test_explicit_registration_and_unregistration_keep_requested_paths(self):
        for unregister in (False, True):
            with self.subTest(unregister=unregister):
                args = ["--exe", "custom.exe", "--script", "entry.py"]
                if unregister:
                    args.append("--unregister")
                with patch.object(cli, "FileAssociationRegistrar") as factory:
                    with patch("sys.stdout", new=io.StringIO()) as output:
                        self.assertEqual(cli.main(args), 0)
                    self.assertEqual(
                        output.getvalue(),
                        (
                            "Removed OST Visualizer file associations.\n"
                            if unregister
                            else "Registered OST Visualizer file associations for custom.exe.\n"
                        ),
                    )
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

    def test_registry_errors_of_both_kinds_are_reported_on_stderr_only(self):
        failures = (
            (OSError("denied"), "File association registration failed: denied\n"),
            (
                FileAssociationRegistryError("not windows"),
                "File association registration failed: not windows\n",
            ),
        )
        for unregister in (False, True):
            for error, message in failures:
                with self.subTest(unregister=unregister, error=type(error).__name__):
                    args = ["--exe", "custom.exe"] + (
                        ["--unregister"] if unregister else []
                    )
                    with patch.object(cli, "FileAssociationRegistrar") as factory:
                        action = factory.return_value
                        (
                            action.unregister if unregister else action.register
                        ).side_effect = error
                        with patch("sys.stdout", new=io.StringIO()) as output:
                            with patch(
                                "sys.stderr", new_callable=io.StringIO
                            ) as errors:
                                self.assertEqual(cli.main(args), 1)
                    self.assertEqual(output.getvalue(), "")
                    self.assertEqual(errors.getvalue(), message)

    def test_defaults_are_resolved_only_for_arguments_that_were_not_given(self):
        default_exe = Path("default-python.exe")
        default_script = Path("default-entry.py")
        cases = (
            ([], default_exe, default_script),
            (["--exe", "custom.exe"], Path("custom.exe"), default_script),
            (["--script", "entry.py"], default_exe, Path("entry.py")),
            (
                ["--exe", "custom.exe", "--script", "entry.py"],
                Path("custom.exe"),
                Path("entry.py"),
            ),
        )
        for args, expected_exe, expected_script in cases:
            with self.subTest(args=args):
                with (
                    patch.object(cli, "_default_executable", return_value=default_exe),
                    patch.object(
                        cli, "_default_script_path", return_value=default_script
                    ) as script,
                    patch.object(cli, "FileAssociationRegistrar") as factory,
                    patch("sys.stdout", new=io.StringIO()),
                ):
                    self.assertEqual(cli.main(args), 0)
                factory.assert_called_once_with(
                    executable_path=expected_exe, app_script_path=expected_script
                )
                if "--script" in args:
                    script.assert_not_called()
                else:
                    script.assert_called_once_with(expected_exe)

    def test_no_script_default_means_a_packaged_executable_is_registered_alone(self):
        with (
            patch.object(cli, "_default_script_path", return_value=None),
            patch.object(cli, "FileAssociationRegistrar") as factory,
            patch("sys.stdout", new=io.StringIO()),
        ):
            self.assertEqual(cli.main(["--exe", "Visualizer.exe"]), 0)
        factory.assert_called_once_with(
            executable_path=Path("Visualizer.exe"), app_script_path=None
        )

    def test_unknown_options_are_rejected_before_any_registration(self):
        with patch.object(cli, "FileAssociationRegistrar") as factory:
            with patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as raised:
                    cli.main(["--all-users"])
        self.assertEqual(raised.exception.code, 2)
        factory.assert_not_called()

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
        with patch.object(cli.sys, "executable", "PYTHON.EXE"):
            with patch.object(Path, "exists", return_value=True):
                self.assertEqual(
                    cli._default_executable(),
                    cli.ROOT / "dist_visualizer" / "Visualizer.dist" / "Visualizer.exe",
                )

    def test_script_default_belongs_only_to_development_python_invocation(self):
        with patch.object(Path, "exists", return_value=True):
            self.assertEqual(
                cli._default_script_path(Path("python.exe")), cli.ROOT / "Visualizer.py"
            )
            self.assertIsNone(cli._default_script_path(Path("Visualizer.exe")))
        with patch.object(Path, "exists", return_value=False):
            self.assertIsNone(cli._default_script_path(Path("python.exe")))
        with patch.object(Path, "exists", return_value=True):
            self.assertEqual(
                cli._default_script_path(Path("PYTHON.EXE")), cli.ROOT / "Visualizer.py"
            )
