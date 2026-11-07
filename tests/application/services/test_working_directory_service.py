import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.application.services.working_directory_service import (
    WorkingDirectoryService,
)


class _DatabaseCreator:
    def __init__(self):
        self.calls = []
        self.result = True

    def create_database(self, path, name, progress_callback=None):
        self.calls.append((path, name, progress_callback))
        return self.result


class WorkingDirectoryServiceTests(unittest.TestCase):
    def test_create_database_rejects_names_that_escape_working_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            creator = _DatabaseCreator()
            service = WorkingDirectoryService(creator, Path(temp_dir) / "working")
            for name in (
                "../outside",
                r"..\outside",
                "nested/name",
                r"C:\outside",
                "white\x00space",
                "  ",
                "bad?name",
            ):
                with self.subTest(name=name):
                    self.assertIsNone(service.create_database(name))
            self.assertEqual(creator.calls, [])

    def test_create_database_rejects_windows_reserved_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            creator = _DatabaseCreator()
            service = WorkingDirectoryService(creator, Path(temp_dir) / "working")
            for name in ("CON", "nul.txt", "LPT9", "com1.data", "trailing."):
                with self.subTest(name=name):
                    self.assertIsNone(service.create_database(name))
            self.assertEqual(creator.calls, [])

    def test_create_database_trims_and_forwards_valid_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            creator = _DatabaseCreator()
            service = WorkingDirectoryService(creator, Path(temp_dir) / "working")
            result = service.create_database("  Estimate  ")
            self.assertEqual(result, service.working_dir / "Estimate.mdb")
            self.assertEqual(
                creator.calls,
                [(service.working_dir / "Estimate.mdb", "Estimate", None)],
            )
            self.assertTrue(service.working_dir.is_dir())

    def test_discovery_and_merge_ignore_directories_with_database_extension(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            working = Path(temp_dir) / "working"
            service = WorkingDirectoryService(_DatabaseCreator(), working)
            self.assertEqual(service.discover_databases(), [])
            service.ensure_working_dir()
            service.ensure_working_dir()
            (working / "folder.mdb").mkdir()
            (working / "notes.txt").touch()
            (working / "z.mdb").touch()
            (working / "a.mdb").touch()
            self.assertEqual(
                service.discover_databases(), [working / "a.mdb", working / "z.mdb"]
            )
            self.assertEqual(
                [
                    entry.file_path
                    for entry in service.merge_discovered_into_file_state([])
                ],
                [str(working / "a.mdb"), str(working / "z.mdb")],
            )

    def test_merge_preserves_existing_state_and_does_not_mutate_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            working = Path(temp_dir)
            known = working / "known.mdb"
            new = working / "new.mdb"
            known.touch()
            new.touch()
            original = FileEntry(str(known).upper(), is_checked=False)
            entries = [original]
            service = WorkingDirectoryService(_DatabaseCreator(), working)
            merged = service.merge_discovered_into_file_state(entries)
            self.assertEqual(entries, [original])
            self.assertIsNot(merged, entries)
            self.assertEqual(len(merged), 2)
            self.assertIs(merged[0], original)
            self.assertFalse(merged[0].is_checked)
            self.assertEqual(merged[1], FileEntry(str(new), is_checked=True))
            self.assertEqual(service.merge_discovered_into_file_state(merged), merged)

    def test_creation_collision_failure_and_progress_forwarding(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            creator = _DatabaseCreator()
            service = WorkingDirectoryService(creator, Path(temp_dir))
            path = Path(temp_dir) / "Existing.mdb"
            path.write_bytes(b"existing data")
            self.assertIsNone(service.create_database("Existing"))
            self.assertEqual(creator.calls, [])
            self.assertEqual(path.read_bytes(), b"existing data")
            creator.result = False
            progress = lambda _message: None
            self.assertIsNone(service.create_database("Rejected", progress))
            self.assertEqual(
                creator.calls, [(Path(temp_dir) / "Rejected.mdb", "Rejected", progress)]
            )
            creator.result = True
            with patch.object(
                service, "_generate_default_name", return_value="Generated"
            ) as name:
                self.assertEqual(
                    service.create_database(), Path(temp_dir) / "Generated.mdb"
                )
            name.assert_called_once_with()


class WorkingDirectoryNameRuleTests(unittest.TestCase):
    def test_database_names_must_be_valid_windows_file_names(self):
        from ost_visualizer.application.services.working_directory_service import (
            _validated_database_name as validate,
        )

        for name in (
            "Plan A",
            "Xavier plan XX",
            "  trimmed  ",
            "a.b",
            "name.with.dots.mdb",
            "CONSOLE",
            "COM10",
            "LPT10",
            "COM0",
            "LPT0",
            "A" * 200,
            "naïve",
            "con_x",
        ):
            self.assertEqual(validate(name), str(name).strip(), name)
        invalid = [
            "",
            "   ",
            "name.",
            "a<b",
            "a>b",
            "a:b",
            'a"b',
            "a/b",
            "a\\b",
            "a|b",
            "a?b",
            "a*b",
            "a\x00b",
            "a\x1fb",
            "a\tb",
        ]
        invalid += [
            "CON",
            "con",
            "PRN",
            "AUX",
            "NUL",
            "nul.txt",
            "Aux.mdb",
            "COM1",
            "com9.x",
            "LPT1",
            "lpt9",
            "LPT5.log",
            "COM5.mdb",
        ]
        for name in invalid:
            with self.subTest(name=name):
                self.assertIsNone(validate(name))
        self.assertEqual(validate(12), "12")
        self.assertEqual(validate("a b"), "a b")
        self.assertEqual(validate("a\x7fb"), "a\x7fb")

    def test_every_reserved_device_name_is_rejected_with_any_extension(self):
        from ost_visualizer.application.services.working_directory_service import (
            _validated_database_name as validate,
        )

        devices = (
            ["CON", "PRN", "AUX", "NUL"]
            + [f"COM{n}" for n in range(1, 10)]
            + [f"LPT{n}" for n in range(1, 10)]
        )
        for device in devices:
            for variant in (
                device,
                device.lower(),
                device + ".mdb",
                device.title() + ".x.y",
            ):
                with self.subTest(variant=variant):
                    self.assertIsNone(validate(variant))
        self.assertEqual(validate("COM"), "COM")
        self.assertEqual(validate("LPT"), "LPT")

    def test_default_names_have_the_unpadded_numeric_shape_and_directory_is_created_with_parents(
        self,
    ):
        import re
        import tempfile
        from pathlib import Path
        from ost_visualizer.application.services.working_directory_service import (
            WorkingDirectoryService,
        )

        class Creator:
            def __init__(self):
                self.names = []

            def create_database(self, path, name, progress_callback=None):
                self.names.append(name)
                return True

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "a" / "b" / "work"
            creator = Creator()
            service = WorkingDirectoryService(creator, root)
            self.assertEqual(service.working_dir, root)
            created = service.create_database()
            self.assertTrue(root.is_dir())
            self.assertEqual(created, root / f"{creator.names[0]}.mdb")
            self.assertRegex(
                creator.names[0], r"^\d{1,2}-\d{1,2}-\d{4} \d{1,2}-\d{1,2}-\d{1,2}$"
            )
            service.ensure_working_dir()
            service.ensure_working_dir()
            self.assertIsInstance(service._generate_default_name(), str)

    def test_discovered_databases_are_ordered_whatever_order_the_filesystem_lists_them_in(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            working = Path(tmp)
            for name in ("z.mdb", "a.mdb", "m.mdb"):
                (working / name).touch()
            service = WorkingDirectoryService(object(), working)
            enumerated_in_reverse = [
                working / "z.mdb",
                working / "m.mdb",
                working / "a.mdb",
            ]
            with patch.object(Path, "glob", return_value=iter(enumerated_in_reverse)):
                self.assertEqual(
                    service.discover_databases(),
                    [working / "a.mdb", working / "m.mdb", working / "z.mdb"],
                )

    def test_merging_discovered_files_returns_the_same_list_object_when_nothing_was_found(
        self,
    ):
        import tempfile
        from pathlib import Path
        from ost_visualizer.application.services.working_directory_service import (
            WorkingDirectoryService,
        )

        with tempfile.TemporaryDirectory() as tmp:
            service = WorkingDirectoryService(object(), Path(tmp))
            existing = [FileEntry("C:/x.mdb")]
            self.assertIs(service.merge_discovered_into_file_state(existing), existing)
            self.assertEqual(service.merge_discovered_into_file_state([]), [])

    def test_a_missing_working_directory_has_no_databases_and_a_custom_logger_is_kept(
        self,
    ):
        import logging
        from pathlib import Path
        from ost_visualizer.application.services.working_directory_service import (
            WorkingDirectoryService,
        )

        custom = logging.getLogger("custom-working-dir")
        service = WorkingDirectoryService(
            object(), Path("Z:/definitely/not/here"), custom
        )
        self.assertIs(service._logger, custom)
        self.assertEqual(service.discover_databases(), [])
        default = WorkingDirectoryService(object(), Path("Z:/x"))
        self.assertEqual(
            default._logger.name,
            "ost_visualizer.application.services.working_directory_service",
        )


@unittest.skipUnless(
    sys.platform == "win32",
    "production formats the default name with the Windows-only %#m/%#d/%#H/%#M/%#S strftime flags",
)
class WorkingDirectoryDefaultNameFormatTests(unittest.TestCase):
    _CLOCK_TARGET = (
        "ost_visualizer.application.services.working_directory_service.datetime"
    )

    @staticmethod
    def _clock(moment):
        return SimpleNamespace(now=lambda: moment)

    def test_default_name_is_month_day_year_then_24_hour_clock_with_no_zero_padding(
        self,
    ):
        service = WorkingDirectoryService(object(), Path("unused"))
        cases = (
            (datetime(2026, 3, 7, 14, 9, 8), "3-7-2026 14-9-8"),
            (datetime(2026, 11, 25, 0, 0, 0), "11-25-2026 0-0-0"),
            (datetime(2026, 1, 31, 23, 59, 58), "1-31-2026 23-59-58"),
            (datetime(2026, 12, 2, 12, 30, 1), "12-2-2026 12-30-1"),
            (datetime(2026, 4, 30, 1, 2, 3), "4-30-2026 1-2-3"),
        )
        for moment, expected in cases:
            with self.subTest(expected=expected):
                with patch(self._CLOCK_TARGET, self._clock(moment)):
                    self.assertEqual(service._generate_default_name(), expected)

    def test_an_unnamed_database_is_created_under_the_default_name_for_the_current_time(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            creator = _DatabaseCreator()
            service = WorkingDirectoryService(creator, Path(temp_dir))
            with patch(self._CLOCK_TARGET, self._clock(datetime(2026, 3, 7, 14, 9, 8))):
                created = service.create_database()
            self.assertEqual(created, Path(temp_dir) / "3-7-2026 14-9-8.mdb")
            self.assertEqual(creator.calls, [(created, "3-7-2026 14-9-8", None)])


if __name__ == "__main__":
    unittest.main()
