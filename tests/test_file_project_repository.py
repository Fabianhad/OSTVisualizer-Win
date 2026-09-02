import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.file_results import FileLoadResult
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.infrastructure.persistence.repositories import (
    file_project_repository,
)
from ost_visualizer.infrastructure.mdb.components.bid_data_reader import (
    BidDataReaderMixin,
)

FileProjectRepository = file_project_repository.FileProjectRepository
MdbFileParser = file_project_repository.MdbFileParser


class FakeMdbReaderWithLayerFailure:
    def get_bid_data(self, file_path, bid_uid):
        return ({}, [], {}, {}, {}, {}, [], {}, None, {}, None, None)

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
    def test_stale_reload_cannot_overwrite_same_path_reopen(self):
        reload_started = threading.Event()
        release_reload = threading.Event()

        class BlockingParser(FakeLifecycleParser):
            def __init__(self):
                super().__init__()
                self._parse_lock = threading.Lock()
                self._parse_count = 0

            def parse(self, file_path):
                with self._parse_lock:
                    self._parse_count += 1
                    parse_count = self._parse_count
                if parse_count == 2:
                    reload_started.set()
                    if not release_reload.wait(2.0):
                        raise TimeoutError("test did not release the blocked reload")
                    display_name = "Stale reload"
                elif parse_count == 3:
                    display_name = "Replacement"
                else:
                    display_name = "Original"
                return FileLoadResult(
                    success=True,
                    parsed_hierarchy=HierarchyFileEntry(
                        file_path=file_path,
                        display_name=display_name,
                    ),
                )

        parser = BlockingParser()
        repository = FileProjectRepository(parser)
        self.assertTrue(repository.load_file("same-path.mdb").success)
        reload_results = []
        worker = threading.Thread(
            target=lambda: reload_results.append(
                repository.reload_database("same-path.mdb")
            )
        )
        worker.start()
        self.assertTrue(reload_started.wait(2.0))
        self.assertTrue(repository.unload_file("same-path.mdb"))
        self.assertTrue(repository.load_file("same-path.mdb").success)
        release_reload.set()
        worker.join(timeout=2.0)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(reload_results), 1)
        self.assertFalse(reload_results[0].success)
        hierarchy = repository.current_hierarchy_data
        self.assertEqual(len(hierarchy.loaded_files), 1)
        self.assertEqual(hierarchy.loaded_files[0].display_name, "Replacement")

    def test_older_reload_cannot_overwrite_newer_same_runtime_reload(self):
        older_reload_started = threading.Event()
        release_older_reload = threading.Event()

        class OutOfOrderParser(FakeLifecycleParser):
            def __init__(self):
                super().__init__()
                self._parse_lock = threading.Lock()
                self._parse_count = 0

            def parse(self, file_path):
                with self._parse_lock:
                    self._parse_count += 1
                    parse_count = self._parse_count
                if parse_count == 2:
                    older_reload_started.set()
                    if not release_older_reload.wait(2.0):
                        raise TimeoutError("test did not release the older reload")
                    display_name = "Older refresh"
                elif parse_count == 3:
                    display_name = "Newer refresh"
                else:
                    display_name = "Original"
                return FileLoadResult(
                    success=True,
                    parsed_hierarchy=HierarchyFileEntry(
                        file_path=file_path,
                        display_name=display_name,
                    ),
                )

        repository = FileProjectRepository(OutOfOrderParser())
        self.assertTrue(repository.load_file("active.mdb").success)
        older_results = []
        older_worker = threading.Thread(
            target=lambda: older_results.append(
                repository.reload_database("active.mdb")
            )
        )
        older_worker.start()
        self.assertTrue(older_reload_started.wait(2.0))
        newer_result = repository.reload_database("active.mdb")
        self.assertTrue(newer_result.success)
        release_older_reload.set()
        older_worker.join(timeout=2.0)
        self.assertFalse(older_worker.is_alive())
        self.assertEqual(len(older_results), 1)
        self.assertFalse(older_results[0].success)
        hierarchy = repository.current_hierarchy_data
        self.assertEqual(hierarchy.loaded_files[0].display_name, "Newer refresh")

    def test_sql_bid_read_hydrates_cover_sheet_snapshots_in_navigation_result(self):
        cover_sheet = object()
        connection = object()

        class Reader(BidDataReaderMixin):
            @contextmanager
            def _connection(self, _file_path):
                yield connection

            @staticmethod
            def _schema(_connection):
                return SimpleNamespace(
                    require_column=lambda _table_name, _column_name: None
                )

            @staticmethod
            def _hydrates_bid_navigation_snapshots():
                return True

            @staticmethod
            def _parse_cdn_types(_connection):
                return {}

            @staticmethod
            def _parse_bid_layers_for_bid(_connection, _bid_uid):
                return []

            @staticmethod
            def _parse_bid_pages_for_bid(_connection, _bid_uid, _bid_layers, _schema):
                return {}

            @staticmethod
            def _parse_bid_areas_for_bid(_connection, _bid_uid, _schema):
                return {}

            @staticmethod
            def _parse_page_area_selections_for_bid(_connection, _bid_pages, _schema):
                return {}

            @staticmethod
            def _parse_bid_conditions_for_bid(
                _connection, _bid_uid, _bid_layers, _cdn_types, _schema
            ):
                return {}

            @staticmethod
            def _parse_bid_takeoffs_for_bid(_connection, _bid_uid, _schema):
                return [], {}

            @staticmethod
            def _parse_bid_annotations_for_bid(
                _connection, _bid_uid, _bid_layers, _schema
            ):
                return []

            @staticmethod
            def _parse_bid_condition_folders_for_bid(_connection, _bid_uid, _schema):
                return {}

            @staticmethod
            def _parse_bid_selected_page(_connection, _bid_uid):
                return None

            @staticmethod
            def _parse_cover_sheet_data(actual_connection, bid_uid):
                self.assertIs(actual_connection, connection)
                self.assertEqual(bid_uid, "bid-1")
                return cover_sheet

            @staticmethod
            def _parse_pages_with_delete_content(actual_connection, bid_uid):
                self.assertIs(actual_connection, connection)
                self.assertEqual(bid_uid, "bid-1")
                return {"page-1"}

        result = Reader().get_bid_data("sql-database", "bid-1")
        self.assertIs(result[-2], cover_sheet)
        self.assertEqual(result[-1], frozenset({"page-1"}))

    def test_project_file_lookup_requires_context_when_local_ids_collide(self):
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path="first-id",
                    bid_projects={"1": HierarchyProjectInfo(name="First")},
                ),
                HierarchyFileEntry(
                    file_path="second-id",
                    bid_projects={"1": HierarchyProjectInfo(name="Second")},
                ),
            ]
        )
        self.assertIsNone(hierarchy.find_file_path_for_project("1"))
        self.assertEqual(
            hierarchy.find_file_path_for_project("1", "second-id"),
            "second-id",
        )
        self.assertIsNone(hierarchy.find_file_path_for_project("1", "missing-id"))

    def test_registering_late_sql_hierarchy_preserves_active_access_database(self):
        class _Parser(FakeLifecycleParser):
            def parse(self, file_path):
                return FileLoadResult(
                    success=True,
                    parsed_hierarchy=HierarchyFileEntry(
                        file_path=file_path,
                        display_name="Access",
                    ),
                )

        repository = FileProjectRepository(_Parser())
        self.assertTrue(repository.load_file("access.mdb").success)
        hierarchy = repository.register_loaded_hierarchy(
            HierarchyFileEntry(file_path="sql-id", display_name="SQL"),
            {},
        )
        self.assertEqual(repository.active_file_path, "access.mdb")
        self.assertEqual(
            [entry.file_path for entry in hierarchy.loaded_files],
            ["access.mdb", "sql-id"],
        )

    def test_reconciling_same_sql_hierarchy_updates_one_repository_entry(self):
        repository = FileProjectRepository(FakeLifecycleParser())
        repository.register_loaded_hierarchy(
            HierarchyFileEntry(file_path="sql-id", display_name="Original"),
            {},
        )
        hierarchy = repository.register_loaded_hierarchy(
            HierarchyFileEntry(file_path="sql-id", display_name="Updated"),
            {},
        )
        self.assertEqual(len(hierarchy.loaded_files), 1)
        self.assertEqual(hierarchy.loaded_files[0].display_name, "Updated")

    def test_condition_types_remain_scoped_to_their_database_identity(self):
        repository = FileProjectRepository(FakeLifecycleParser())
        repository.register_loaded_hierarchy(
            HierarchyFileEntry(file_path="first-id"),
            {"1": CdnType(uid="1", name="First type")},
        )
        repository.register_loaded_hierarchy(
            HierarchyFileEntry(file_path="second-id"),
            {"1": CdnType(uid="1", name="Second type")},
        )
        first = repository.get_cdn_types("first-id")
        second = repository.get_cdn_types("second-id")
        first.clear()
        self.assertEqual(second["1"].name, "Second type")
        self.assertEqual(repository.get_cdn_types("first-id")["1"].name, "First type")
        self.assertEqual(repository.get_cdn_types()["1"].name, "First type")

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

    def test_legacy_bid_load_for_unloaded_file_returns_empty_result(self):
        repository = FileProjectRepository(FakeLifecycleParser())
        with self.assertLogs(repository.logger, level="WARNING"):
            result = repository.load_bid("bid-1", "missing.mdb")
        self.assertEqual(result.bid_pages, {})
        self.assertIsNone(repository.active_file_path)

    def test_reload_refreshes_read_connection_without_closing_write_connection(self):
        parser = FakeLifecycleParser()
        repository = FileProjectRepository(parser)
        repository._loaded_files["active.mdb"] = (
            file_project_repository._LoadedFileCache(
                file_path="active.mdb",
                created_at=0.0,
                parsed_hierarchy=HierarchyFileEntry(file_path="active.mdb"),
            )
        )
        result = repository.reload_database("active.mdb")
        self.assertFalse(result.success)
        self.assertEqual(parser.refreshed, ["active.mdb"])
        self.assertEqual(parser.closed, [])


if __name__ == "__main__":
    unittest.main()
