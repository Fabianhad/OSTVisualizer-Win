import tempfile
import unittest
from pathlib import Path
from ost_visualizer.application.services.working_directory_service import (
    WorkingDirectoryService,
)


class _DatabaseCreator:
    def __init__(self):
        self.calls = []

    def create_database(self, path, name, progress_callback=None):
        self.calls.append((path, name, progress_callback))
        return True


class WorkingDirectoryServiceTests(unittest.TestCase):
    def test_create_database_rejects_names_that_escape_working_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            creator = _DatabaseCreator()
            service = WorkingDirectoryService(creator, Path(temp_dir) / "working")
            for name in ("../outside", r"..\outside", "nested/name", r"C:\outside"):
                with self.subTest(name=name):
                    self.assertIsNone(service.create_database(name))
            self.assertEqual(creator.calls, [])

    def test_create_database_rejects_windows_reserved_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            creator = _DatabaseCreator()
            service = WorkingDirectoryService(creator, Path(temp_dir) / "working")
            for name in ("CON", "nul.txt", "LPT9", "trailing."):
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


if __name__ == "__main__":
    unittest.main()
