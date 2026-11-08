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


class ProjectFileArgumentContractTests(unittest.TestCase):
    def test_supported_extensions_are_exactly_ost_and_osp(self):
        from ost_visualizer.application.dtos.file_import_args import (
            SUPPORTED_PROJECT_IMPORT_EXTENSIONS,
        )

        self.assertEqual(SUPPORTED_PROJECT_IMPORT_EXTENSIONS, {".ost", ".osp"})
        self.assertIs(type(SUPPORTED_PROJECT_IMPORT_EXTENSIONS), frozenset)
        message = "Unsupported file type. Only .ost and .osp files can be imported."
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            names = ("plan.ostx", "plan.ost.bak", "ost", "plan.exe", "plan.OST.txt")
            for name in names:
                (root / name).write_text("x")
            result = parse_project_file_args([str(root / name) for name in names])
            self.assertEqual(result.files, [])
            self.assertEqual(
                [(item.value, item.reason) for item in result.rejected],
                [(str(root / name), message) for name in names],
            )

    def test_args_container_defaults_are_independent_and_report_what_they_hold(self):
        from ost_visualizer.application.dtos.file_import_args import (
            ParsedProjectFileArg,
            ProjectFileArgs,
            RejectedProjectFileArg,
        )

        empty = ProjectFileArgs()
        self.assertIs(type(empty.rejected), list)
        self.assertEqual(empty.rejected, [])
        self.assertIsNot(empty.rejected, ProjectFileArgs().rejected)
        self.assertIs(empty.has_file_args, False)
        parsed = ParsedProjectFileArg(path="a.ost", extension=".ost")
        rejected = RejectedProjectFileArg(value="b.txt", reason="why")
        self.assertEqual((parsed.path, parsed.extension), ("a.ost", ".ost"))
        self.assertEqual((rejected.value, rejected.reason), ("b.txt", "why"))
        self.assertIs(ProjectFileArgs(files=[parsed]).has_file_args, True)
        self.assertIs(ProjectFileArgs(rejected=[rejected]).has_file_args, True)
        self.assertEqual(ProjectFileArgs(files=[parsed]).rejected, [])
        self.assertEqual(ProjectFileArgs(rejected=[rejected]).files, [])


class ProjectFileArgumentDuplicateAndSnapshotTests(unittest.TestCase):
    def test_duplicate_arguments_are_each_reported_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            good = root / "a.ost"
            other = root / "b.osp"
            good.write_text("x")
            other.write_text("x")
            missing = root / "missing.ost"
            result = parse_project_file_args(
                [
                    str(good),
                    str(other),
                    str(good),
                    str(missing),
                    str(missing),
                    "plan.txt",
                    "plan.txt",
                ]
            )
            self.assertEqual(
                [(item.path, item.extension) for item in result.files],
                [
                    (str(good), ".ost"),
                    (str(other), ".osp"),
                    (str(good), ".ost"),
                ],
            )
            self.assertEqual(
                [item.value for item in result.rejected],
                [str(missing), str(missing), "plan.txt", "plan.txt"],
            )

    def test_characterisation_the_argument_list_is_read_completely_before_any_file_is_checked(
        self,
    ):
        # Characterisation of the eager snapshot (list(argv)): a file that comes
        # into existence while the argument iterable is still being consumed is
        # already visible when the arguments are checked afterwards.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            late = root / "late.ost"
            first = root / "first.ost"
            first.write_text("x")

            def arguments():
                yield str(late)
                late.write_text("created while the arguments are still being read")
                yield str(first)

            result = parse_project_file_args(arguments())
            self.assertEqual(
                [item.path for item in result.files], [str(late), str(first)]
            )
            self.assertEqual(result.rejected, [])
