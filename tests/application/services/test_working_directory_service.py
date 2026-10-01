import tempfile
import unittest
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
