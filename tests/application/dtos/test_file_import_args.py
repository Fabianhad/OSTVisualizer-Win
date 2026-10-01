from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
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
            root = Path(tmp)
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
            root = Path(tmp)
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
