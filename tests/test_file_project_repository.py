import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.file_results import FileLoadResult
from ost_visualizer.infrastructure.persistence.repositories import (
    file_project_repository,
)

FileProjectRepository = file_project_repository.FileProjectRepository
MdbFileParser = file_project_repository.MdbFileParser


class FakeMdbReaderWithLayerFailure:
    def get_bid_data(self, file_path, bid_uid):
        return ({}, [], {}, {}, {}, {}, [], {}, None, {})

    def get_bid_layers_for_sidebar(self, file_path, bid_uid):
        raise ValueError("bad layer sequence")


class FakeLifecycleParser:
    def __init__(self):
        self.closed = []
        self.refreshed = []

    def close_connection(self, file_path=None):
        self.closed.append(file_path)

    def refresh_connection(self, file_path):
        self.refreshed.append(file_path)

    def parse(self, _file_path):
        return FileLoadResult(success=False, error_message="stop after refresh")


class MdbFileParserTests(unittest.TestCase):
    def test_bid_load_keeps_core_data_when_optional_layers_fail(self):
        parser = MdbFileParser(parser=FakeMdbReaderWithLayerFailure())
        with self.assertLogs(parser.logger, level="WARNING") as logs:
            result = parser.load_bid_data("demo.mdb", "bid-1")
        self.assertIn("Failed to load bid layers", logs.output[0])
        self.assertEqual(result.bid_layers, [])
        self.assertEqual(result.bid_conditions, {})
        self.assertEqual(result.bid_takeoffs, [])

    def test_unload_closes_all_connections_owned_for_database(self):
        parser = FakeLifecycleParser()
        repository = FileProjectRepository(parser)
        repository._loaded_files["old.mdb"] = SimpleNamespace()
        repository._active_file_path = "old.mdb"
        self.assertTrue(repository.unload_file("old.mdb"))
        self.assertEqual(parser.closed, ["old.mdb"])

    def test_reload_refreshes_read_connection_without_closing_write_connection(self):
        parser = FakeLifecycleParser()
        repository = FileProjectRepository(parser)
        repository._loaded_files["active.mdb"] = SimpleNamespace()
        result = repository.reload_database("active.mdb")
        self.assertFalse(result.success)
        self.assertEqual(parser.refreshed, ["active.mdb"])
        self.assertEqual(parser.closed, [])


if __name__ == "__main__":
    unittest.main()
