import os
import tempfile
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.file_results import FileLoadResult
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.infrastructure.mdb.components.bid_data_reader import (
    BidDataReaderMixin,
)
from ost_visualizer.infrastructure.persistence.repositories import (
    file_project_repository,
)
from ost_visualizer.infrastructure.persistence.repositories.file_project_repository import (
    FileProjectRepository,
    _LoadedFileCache,
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
        self.assertIn(
            "unloaded, reopened, or refreshed", reload_results[0].error_message
        )
        hierarchy = repository.current_hierarchy_data
        self.assertEqual(len(hierarchy.loaded_files), 1)
        self.assertEqual(hierarchy.loaded_files[0].display_name, "Replacement")
        self.assertEqual(repository.active_file_path, "same-path.mdb")

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
        self.assertIn(
            "unloaded, reopened, or refreshed", older_results[0].error_message
        )
        hierarchy = repository.current_hierarchy_data
        self.assertEqual(len(hierarchy.loaded_files), 1)
        self.assertEqual(hierarchy.loaded_files[0].display_name, "Newer refresh")

    def _bid_reader(self, hydrates, connection, cover_sheet):
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
                return hydrates

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
            def _parse_page_area_selections_for_bid(
                _connection, _bid_uid, _bid_pages, _schema
            ):
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

        return Reader()

    def test_sql_bid_read_hydrates_cover_sheet_snapshots_in_navigation_result(self):
        cover_sheet = object()
        connection = object()
        reader = self._bid_reader(True, connection, cover_sheet)
        result = reader.get_bid_data("sql-database", "bid-1")
        self.assertIs(result[-2], cover_sheet)
        self.assertEqual(result[-1], frozenset({"page-1"}))

    def test_bid_read_without_navigation_snapshots_leaves_them_unhydrated(self):
        cover_sheet = object()
        connection = object()
        reader = self._bid_reader(False, connection, cover_sheet)
        result = reader.get_bid_data("access-database", "bid-1")
        self.assertIsNone(result[-2])
        self.assertIsNone(result[-1])

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
        self.assertIsNone(hierarchy.find_file_path_for_project(""))

    def test_project_file_lookup_resolves_unique_ids_without_context(self):
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path="first-id",
                    bid_projects={"1": HierarchyProjectInfo(name="First")},
                ),
                HierarchyFileEntry(
                    file_path="second-id",
                    bid_projects={"2": HierarchyProjectInfo(name="Second")},
                ),
            ]
        )
        self.assertEqual(hierarchy.find_file_path_for_project("2"), "second-id")
        self.assertEqual(
            hierarchy.find_file_path_for_project("2", "second-id"), "second-id"
        )
        self.assertIsNone(hierarchy.find_file_path_for_project("2", "first-id"))
        self.assertIsNone(hierarchy.find_file_path_for_project("3"))

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
        self.assertEqual(len(repository._loaded_files), 1)
        self.assertEqual(repository.active_file_path, "sql-id")

    def test_reconciling_same_sql_hierarchy_replaces_its_condition_types(self):
        repository = FileProjectRepository(FakeLifecycleParser())
        repository.register_loaded_hierarchy(
            HierarchyFileEntry(file_path="sql-id"),
            {"1": CdnType(uid="1", name="Original")},
        )
        repository.register_loaded_hierarchy(
            HierarchyFileEntry(file_path="sql-id"),
            {"2": CdnType(uid="2", name="Updated")},
        )
        self.assertEqual(list(repository.get_cdn_types("sql-id")), ["2"])

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
        self.assertEqual(repository.get_cdn_types("unknown-id"), {})

    def test_bid_load_keeps_core_data_when_optional_layers_fail(self):
        parser = MdbFileParser(parser=FakeMdbReaderWithLayerFailure())
        with self.assertLogs(parser.logger, level="WARNING") as logs:
            result = parser.load_bid_data("demo.mdb", "bid-1")
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(
            logs.records[0].getMessage(),
            "Failed to load bid layers for bid-1 in demo.mdb: bad layer sequence",
        )
        self.assertEqual(result.bid_layers, [])
        self.assertEqual(result.bid_conditions, {})
        self.assertEqual(result.bid_takeoffs, [])
        self.assertEqual(result.bid_pages, {})
        self.assertEqual(result.pages, {})

    def test_bid_load_does_not_swallow_unexpected_layer_failures(self):
        class _Reader(FakeMdbReaderWithLayerFailure):
            def get_bid_layers_for_sidebar(self, file_path, bid_uid):
                raise RuntimeError("unexpected layer failure")

        parser = MdbFileParser(parser=_Reader())
        with self.assertRaisesRegex(RuntimeError, "unexpected layer failure"):
            parser.load_bid_data("demo.mdb", "bid-1")

    def test_unload_closes_all_connections_owned_for_database(self):
        parser = FakeLifecycleParser()
        repository = FileProjectRepository(parser)
        repository._loaded_files["old.mdb"] = SimpleNamespace()
        repository._active_file_path = "old.mdb"
        self.assertTrue(repository.unload_file("old.mdb"))
        self.assertEqual(parser.closed, ["old.mdb"])
        self.assertEqual(repository._loaded_files, {})
        self.assertIsNone(repository.active_file_path)
        self.assertEqual(repository.current_hierarchy_data.loaded_files, [])

    def test_unload_of_unknown_database_closes_nothing_and_changes_nothing(self):
        parser = FakeLifecycleParser()
        repository = FileProjectRepository(parser)
        repository.register_loaded_hierarchy(
            HierarchyFileEntry(file_path="kept.mdb"), {}
        )
        self.assertFalse(repository.unload_file("missing.mdb"))
        self.assertEqual(parser.closed, [])
        self.assertEqual(repository.active_file_path, "kept.mdb")
        self.assertEqual(
            [
                entry.file_path
                for entry in repository.current_hierarchy_data.loaded_files
            ],
            ["kept.mdb"],
        )

    def test_unload_of_active_database_activates_remaining_one_and_rebuilds_hierarchy(
        self,
    ):
        parser = FakeLifecycleParser()
        repository = FileProjectRepository(parser)
        repository.register_loaded_hierarchy(HierarchyFileEntry(file_path="a-id"), {})
        repository.register_loaded_hierarchy(HierarchyFileEntry(file_path="b-id"), {})
        self.assertEqual(repository.active_file_path, "a-id")
        self.assertTrue(repository.unload_file())
        self.assertEqual(parser.closed, ["a-id"])
        self.assertEqual(repository.active_file_path, "b-id")
        self.assertEqual(
            [
                entry.file_path
                for entry in repository.current_hierarchy_data.loaded_files
            ],
            ["b-id"],
        )

    def test_bid_load_for_unloaded_file_returns_empty_result(self):
        repository = FileProjectRepository(FakeLifecycleParser())
        with self.assertLogs(repository.logger, level="WARNING") as logs:
            result = repository.load_bid("bid-1", "missing.mdb")
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "File not loaded: missing.mdb (bid_uid=bid-1)",
                "Discarding bid load for an unloaded file: missing.mdb "
                "(bid_uid=bid-1)",
            ],
        )
        self.assertEqual(result.bid_pages, {})
        self.assertEqual(result.bid_takeoffs, [])
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
        self.assertEqual(result.error_message, "stop after refresh")
        self.assertEqual(parser.refreshed, ["active.mdb"])
        self.assertEqual(parser.closed, [])
        self.assertIn("active.mdb", repository._loaded_files)

    def test_reload_can_skip_connection_refresh_and_still_reparses(self):
        class _Parser(FakeLifecycleParser):
            def parse(self, file_path):
                return FileLoadResult(
                    success=True,
                    parsed_hierarchy=HierarchyFileEntry(
                        file_path=file_path, display_name="Reparsed"
                    ),
                )

        parser = _Parser()
        repository = FileProjectRepository(parser)
        repository.register_loaded_hierarchy(
            HierarchyFileEntry(file_path="active-id", display_name="Original"), {}
        )
        result = repository.reload_database("active-id", close_connections=False)
        self.assertTrue(result.success)
        self.assertEqual(parser.refreshed, [])
        self.assertEqual(parser.closed, [])
        self.assertEqual(
            repository.current_hierarchy_data.loaded_files[0].display_name,
            "Reparsed",
        )
        self.assertIs(result.hierarchy, repository.current_hierarchy_data)

    def test_reload_requires_a_loaded_database_path(self):
        parser = FakeLifecycleParser()
        repository = FileProjectRepository(parser)
        with self.assertLogs(repository.logger, level="ERROR"):
            missing_path = repository.reload_database()
            unknown_path = repository.reload_database("unknown.mdb")
        self.assertFalse(missing_path.success)
        self.assertEqual(
            missing_path.error_message, "file_path is required for reload_database"
        )
        self.assertFalse(unknown_path.success)
        self.assertEqual(
            unknown_path.error_message, "File not found in loaded files: unknown.mdb"
        )
        self.assertEqual(parser.refreshed, [])


class RepositoryDetailTests(unittest.TestCase):
    class SuccessfulParser(FakeLifecycleParser):
        def __init__(self, events=None):
            super().__init__()
            self.events = events if events is not None else []

        def refresh_connection(self, file_path):
            self.events.append("refresh")
            super().refresh_connection(file_path)

        def close_connection(self, file_path=None):
            self.events.append("close")
            super().close_connection(file_path)

        def parse(self, file_path):
            self.events.append("parse")
            return FileLoadResult(
                success=True,
                parsed_hierarchy=HierarchyFileEntry(file_path=file_path),
            )

    def test_bid_load_requires_a_file_path_and_says_which_bid(self):
        repository = FileProjectRepository(FakeLifecycleParser())
        for missing in (None, ""):
            with self.subTest(file_path=missing):
                with self.assertLogs(repository.logger, level="ERROR") as logs:
                    result = repository.load_bid("bid-9", missing)
                self.assertEqual(
                    [record.getMessage() for record in logs.records],
                    ["file_path is required for load_bid (bid_uid=bid-9)"],
                )
                self.assertEqual(result.bid_pages, {})
                self.assertEqual(result.bid_takeoffs, [])

    def test_prepare_bid_load_reads_loaded_files_only_and_changes_no_state(self):
        calls = []
        parser = FakeLifecycleParser()
        data = file_project_repository.BidLoadResult()
        parser.load_bid_data = lambda path, uid: calls.append((path, uid)) or data
        repository = FileProjectRepository(parser)
        repository.register_loaded_hierarchy(HierarchyFileEntry(file_path="a.mdb"), {})
        repository.register_loaded_hierarchy(HierarchyFileEntry(file_path="b.mdb"), {})
        repository._active_file_path = "b.mdb"
        with self.assertLogs(repository.logger, level="WARNING") as logs:
            unloaded = repository.prepare_bid_load("bid-1", "missing.mdb")
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["File not loaded: missing.mdb (bid_uid=bid-1)"],
        )
        self.assertIsInstance(unloaded, file_project_repository.BidLoadResult)
        self.assertIsNot(unloaded, data)
        self.assertEqual(unloaded.bid_pages, {})
        self.assertEqual(calls, [])
        self.assertIs(repository.prepare_bid_load("bid-2", "a.mdb"), data)
        self.assertEqual(calls, [("a.mdb", "bid-2")])
        self.assertEqual(repository.active_file_path, "b.mdb")

    def test_reload_reports_each_missing_path_with_its_own_log(self):
        repository = FileProjectRepository(FakeLifecycleParser())
        with self.assertLogs(repository.logger, level="ERROR") as logs:
            repository.reload_database()
            repository.reload_database("unknown.mdb")
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "file_path is required for reload_database",
                "File not found in loaded files: unknown.mdb",
            ],
        )

    def test_position_caches_are_cleared_between_refresh_and_reparse(self):
        events = []
        parser = self.SuccessfulParser(events)
        repository = FileProjectRepository(parser)
        repository.register_loaded_hierarchy(HierarchyFileEntry(file_path="a.mdb"), {})
        with patch.object(
            file_project_repository,
            "_clear_position_caches",
            lambda: events.append("clear"),
        ):
            self.assertTrue(repository.reload_database("a.mdb").success)
            self.assertEqual(events, ["refresh", "clear", "parse"])
            events.clear()
            self.assertTrue(repository.unload_file("a.mdb"))
            self.assertEqual(events, ["clear", "close"])
            events.clear()
            self.assertFalse(repository.unload_file("a.mdb"))
            self.assertEqual(events, [])

    def test_creation_time_orders_only_existing_mdb_files(self):
        with tempfile.TemporaryDirectory() as folder:
            existing_mdb = os.path.join(folder, "Plans.MDB")
            other_file = os.path.join(folder, "plans.sqlite")
            for path in (existing_mdb, other_file):
                with open(path, "wb") as handle:
                    handle.write(b"x")
            cases = {
                "existing mdb with upper-case suffix": (
                    existing_mdb,
                    os.path.getctime(existing_mdb),
                ),
                "existing file that is not an mdb": (other_file, 123.5),
                "mdb that does not exist": (os.path.join(folder, "gone.mdb"), 123.5),
            }
            for label, (path, expected) in cases.items():
                with self.subTest(case=label):
                    repository = FileProjectRepository(self.SuccessfulParser())
                    with patch.object(
                        file_project_repository.time, "time", lambda: 123.5
                    ):
                        self.assertTrue(repository.load_file(path).success)
                    self.assertEqual(
                        repository._loaded_files[path].created_at, expected
                    )

    def test_display_names_prefer_the_registry_then_the_database_then_the_file(self):
        class Registry:
            def __init__(self, display_name):
                self.display_name = display_name

            def resolve(self, _path):
                if self.display_name is None:
                    return None
                return SimpleNamespace(display_name=self.display_name)

        class FakeHierarchy:
            def set(self, data):
                self.data = data

        def display_name(entry, registry):
            repository = FileProjectRepository.__new__(FileProjectRepository)
            repository._current_hierarchy = FakeHierarchy()
            repository._descriptor_registry = registry
            repository._loaded_files = {
                entry.file_path: _LoadedFileCache(
                    file_path=entry.file_path, created_at=1.0, parsed_hierarchy=entry
                )
            }
            FileProjectRepository._rebuild_merged_hierarchy(repository)
            return repository._current_hierarchy.data.loaded_files[0].display_name

        path = os.path.join("C:\\", "plans", "Level 1.mdb")
        named = HierarchyFileEntry(file_path=path, database_name="Tower Bid")
        self.assertEqual(display_name(named, None), "Tower Bid")
        self.assertEqual(
            display_name(
                HierarchyFileEntry(file_path=path, database_name="Tower Bid"),
                Registry("Registered"),
            ),
            "Registered",
        )
        self.assertEqual(
            display_name(
                HierarchyFileEntry(file_path=path, database_name="Tower Bid"),
                Registry(None),
            ),
            "Tower Bid",
        )
        self.assertEqual(
            display_name(HierarchyFileEntry(file_path=path), None), "Level 1.mdb"
        )
        self.assertEqual(
            display_name(
                HierarchyFileEntry(
                    file_path=path, database_name="Tower Bid", display_name="Kept"
                ),
                Registry("Registered"),
            ),
            "Kept",
        )


class HierarchyImportOrderTests(unittest.TestCase):
    def test_loaded_databases_have_path_tiebreaker_when_file_times_match(self):
        repository = FileProjectRepository.__new__(FileProjectRepository)

        class FakeHierarchy:
            def set(self, data):
                self.data = data

        repository._current_hierarchy = FakeHierarchy()
        repository._descriptor_registry = None
        repository._loaded_files = {
            "z.mdb": _LoadedFileCache(
                file_path="z.mdb",
                created_at=1.0,
                parsed_hierarchy=HierarchyFileEntry(file_path="z.mdb"),
            ),
            "a.mdb": _LoadedFileCache(
                file_path="a.mdb",
                created_at=1.0,
                parsed_hierarchy=HierarchyFileEntry(file_path="a.mdb"),
            ),
        }
        FileProjectRepository._rebuild_merged_hierarchy(repository)
        self.assertEqual(
            [
                entry.file_path
                for entry in repository._current_hierarchy.data.loaded_files
            ],
            ["a.mdb", "z.mdb"],
        )
