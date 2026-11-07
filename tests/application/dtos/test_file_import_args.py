from __future__ import annotations
import contextlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from ost_visualizer.application.dtos.file_import_args import (
    PROJECT_IMPORT_EXTENSION_OSP,
    PROJECT_IMPORT_EXTENSION_OST,
    parse_project_file_args,
)


class ProjectFileArgumentTests(unittest.TestCase):
    def test_parse_project_file_args_with_no_files_keeps_startup_path_empty(self):
        result = parse_project_file_args([])
        self.assertFalse(result.has_file_args)
        self.assertEqual(result.files, [])
        self.assertEqual(result.rejected, [])

    def test_parse_project_file_args_accepts_ost_osp_and_preserves_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            ost = root / "project with spaces.ost"
            osp = root / "package.OSP"
            ost.write_text("ost")
            osp.write_text("osp")
            result = parse_project_file_args([str(ost), str(osp)])
            self.assertEqual(
                [item.extension for item in result.files],
                [".ost", ".osp"],
            )
            self.assertEqual([item.path for item in result.files], [str(ost), str(osp)])
            self.assertEqual(result.rejected, [])
            self.assertTrue(result.has_file_args)
            self.assertEqual(
                (PROJECT_IMPORT_EXTENSION_OST, PROJECT_IMPORT_EXTENSION_OSP),
                (".ost", ".osp"),
            )

    def test_parse_project_file_args_rejects_unsupported_and_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            unsupported = root / "notes.txt"
            missing = root / "missing.ost"
            unsupported.write_text("x")
            result = parse_project_file_args([str(unsupported), str(missing)])
            self.assertEqual(result.files, [])
            self.assertEqual(len(result.rejected), 2)
            self.assertIn("Unsupported file type", result.rejected[0].reason)
            self.assertEqual(result.rejected[1].reason, "File does not exist.")
            self.assertEqual(
                [item.value for item in result.rejected],
                [str(unsupported), str(missing)],
            )
            self.assertTrue(result.has_file_args)

    def test_flags_are_ignored_and_directories_cannot_be_imported_as_files(self):
        self.assertFalse(
            parse_project_file_args(iter(["--verbose", "-h"])).has_file_args
        )
        with tempfile.TemporaryDirectory(suffix=".ost") as directory:
            result = parse_project_file_args(iter(["--verbose", directory]))
            self.assertEqual(result.files, [])
            self.assertEqual(len(result.rejected), 1)
            self.assertEqual(result.rejected[0].value, str(Path(directory).resolve()))
            self.assertEqual(result.rejected[0].reason, "File does not exist.")
            self.assertTrue(result.has_file_args)


@contextlib.contextmanager
def _working_directory(path: Path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class ProjectFileArgumentNormalizationTests(unittest.TestCase):
    def test_relative_arguments_are_reported_as_absolute_resolved_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "sub").mkdir()
            (root / "rel.ost").write_text("x")
            (root / "sub" / "nested.OSP").write_text("x")
            with _working_directory(root):
                result = parse_project_file_args(
                    [
                        "rel.ost",
                        os.path.join("sub", "..", "sub", "nested.OSP"),
                        "missing.osp",
                    ]
                )
            self.assertEqual(
                [(item.path, item.extension) for item in result.files],
                [
                    (str(root / "rel.ost"), ".ost"),
                    (str(root / "sub" / "nested.OSP"), ".osp"),
                ],
            )
            self.assertEqual(
                [(item.value, item.reason) for item in result.rejected],
                [(str(root / "missing.osp"), "File does not exist.")],
            )

    def test_supported_extension_is_judged_on_the_resolved_target(self):
        # "." has no suffix as typed, but it resolves to the working directory
        # "plan.ost": the argument is then rejected as a missing file at its
        # resolved location, not as an unsupported type named ".".
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            project_directory = root / "plan.ost"
            project_directory.mkdir()
            with _working_directory(project_directory):
                result = parse_project_file_args(["."])
            self.assertEqual(result.files, [])
            self.assertEqual(
                [(item.value, item.reason) for item in result.rejected],
                [(str(project_directory), "File does not exist.")],
            )

    def test_home_shortcut_is_expanded_before_the_file_is_looked_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "home.ost").write_text("x")
            with mock.patch.dict(
                os.environ, {"HOME": str(root), "USERPROFILE": str(root)}
            ):
                result = parse_project_file_args(
                    [os.path.join("~", "home.ost"), os.path.join("~", "gone.ost")]
                )
            self.assertEqual(
                [item.path for item in result.files], [str(root / "home.ost")]
            )
            self.assertEqual(
                [(item.value, item.reason) for item in result.rejected],
                [(str(root / "gone.ost"), "File does not exist.")],
            )


class ProjectFileArgumentValueTests(unittest.TestCase):
    def test_rejection_text_and_immutability_of_the_parsed_values(self):
        from dataclasses import FrozenInstanceError
        from ost_visualizer.application.dtos.file_import_args import (
            ParsedProjectFileArg,
            ProjectFileArgs,
            RejectedProjectFileArg,
        )

        result = parse_project_file_args(["plan.txt", "--flag", "-x"])
        self.assertEqual(
            [(item.value, item.reason) for item in result.rejected],
            [
                (
                    "plan.txt",
                    "Unsupported file type. Only .ost and .osp files can be imported.",
                )
            ],
        )
        self.assertTrue(result.has_file_args)
        with self.assertRaises(FrozenInstanceError):
            ParsedProjectFileArg("a", ".ost").path = "b"
        with self.assertRaises(FrozenInstanceError):
            RejectedProjectFileArg("a", "b").value = "c"
        with self.assertRaises(FrozenInstanceError):
            ProjectFileArgs().files = []
        self.assertEqual(ProjectFileArgs().files, [])
        self.assertIsNot(ProjectFileArgs().files, ProjectFileArgs().files)
