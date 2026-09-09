import logging
import sqlite3
import unittest
from collections import namedtuple
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.infrastructure.mdb.components.bid_data_reader import (
    BidDataReaderMixin,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.handlers.cover_sheet_handler import CoverSheetHandler


class _Schema:
    @staticmethod
    def optional_table_missing(_table):
        return False

    @staticmethod
    def require_column(_table, _column):
        pass

    @staticmethod
    def column_exists(_table, _column):
        return True


class _SelectiveSchema:
    def __init__(self, columns_by_table):
        self._columns_by_table = {
            table: frozenset(columns) for table, columns in columns_by_table.items()
        }
        self.optional_table_calls = []
        self.column_exists_calls = []
        self.require_column_calls = []

    def optional_table_missing(self, table):
        self.optional_table_calls.append(table)
        return table not in self._columns_by_table

    def column_exists(self, table, column):
        self.column_exists_calls.append((table, column))
        return column in self._columns_by_table.get(table, ())

    def require_column(self, table, column):
        self.require_column_calls.append((table, column))
        if column not in self._columns_by_table.get(table, ()):
            raise AssertionError(f"Missing required column {table}.{column}")

    def get_columns(self, table):
        return self._columns_by_table.get(table, ())


class _LimitedReadCursor:
    def __init__(self, owner):
        self._owner = owner
        self._cursor = owner.connection.cursor()

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self._cursor.close()
        return False

    @property
    def description(self):
        return self._cursor.description

    def execute(self, query, *params):
        if len(params) > self._owner.parameter_limit:
            raise AssertionError(
                f"Query used {len(params)} parameters; "
                f"limit is {self._owner.parameter_limit}"
            )
        self._owner.queries.append((query, len(params)))
        self._cursor.execute(query, params)
        return self

    def fetchall(self):
        rows = self._cursor.fetchall()
        if self._cursor.description is None:
            return rows
        columns = [column[0] for column in self._cursor.description]
        row_type = namedtuple("LimitedReadRow", columns, rename=True)
        return [row_type(*row) for row in rows]


class _LimitedReadConnection:
    def __init__(self, connection, schema, parameter_limit=255):
        self.connection = connection
        self.schema = schema
        self.parameter_limit = parameter_limit
        self.queries = []

    def cursor(self):
        return _LimitedReadCursor(self)


class _StrictReadPolicyReader(BidDataReaderMixin):
    @staticmethod
    def _schema(connection):
        return connection.schema

    @staticmethod
    def _record_caught_read_error(_exc, _file_path=None):
        return True


class _TolerantReadPolicyReader(_StrictReadPolicyReader):
    @staticmethod
    def _record_caught_read_error(_exc, _file_path=None):
        return False


class _FailingContentConnection:
    def __init__(self):
        self.query_count = 0
        self.rows = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def execute(self, query, *_params):
        self.query_count += 1
        if self.query_count == 1:
            self.rows = [(1,), (2,)]
        elif self.query_count == 2:
            self.rows = [(1,)]
        else:
            raise RuntimeError(f"content scan failed: {query}")
        return self

    def fetchall(self):
        return list(self.rows)


class _Reader(BidDataReaderMixin):
    def __init__(self):
        self.connection = _FailingContentConnection()
        self.logger = logging.getLogger(__name__)

    @contextmanager
    def _connection(self, _file_path):
        yield self.connection

    @staticmethod
    def _schema(_connection):
        return _Schema()

    @staticmethod
    def _record_caught_read_error(_exc, _file_path=None):
        return False


def _owner_validation_reader(takeoffs):
    class OwnerValidationReader(BidDataReaderMixin):
        @contextmanager
        def _connection(self, _file_path):
            yield object()

        @staticmethod
        def _schema(_connection):
            return _Schema()

        @staticmethod
        def _parse_cdn_types(_connection):
            return {}

        @staticmethod
        def _parse_bid_layers_for_bid(_connection, _bid_uid):
            return {}

        @staticmethod
        def _parse_bid_pages_for_bid(_connection, _bid_uid, _layers, _schema):
            return {"3": SimpleNamespace(uid="3")}

        @staticmethod
        def _parse_bid_areas_for_bid(_connection, _bid_uid, _schema):
            return {}

        @staticmethod
        def _parse_page_area_selections_for_bid(_connection, _bid_uid, _pages, _schema):
            return {}

        @staticmethod
        def _parse_bid_conditions_for_bid(
            _connection, _bid_uid, _layers, _cdn_types, _schema
        ):
            return {"5": SimpleNamespace(uid="5")}

        @staticmethod
        def _parse_bid_takeoffs_for_bid(_connection, _bid_uid, _schema):
            return list(takeoffs), {}

        @staticmethod
        def _parse_bid_annotations_for_bid(_connection, _bid_uid, _layers, _schema):
            return []

        @staticmethod
        def _parse_bid_condition_folders_for_bid(_connection, _bid_uid, _schema):
            return {}

        @staticmethod
        def _parse_bid_selected_page(_connection, _bid_uid):
            return None

        @staticmethod
        def _hydrates_bid_navigation_snapshots():
            return False

    return OwnerValidationReader()


class BidDataReaderTests(unittest.TestCase):
    def test_page_owned_fallback_is_set_based_at_access_parameter_boundaries(self):
        for page_count in (50, 51, 254, 255, 256, 1000):
            with self.subTest(page_count=page_count):
                database = sqlite3.connect(":memory:")
                database.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
                database.execute(
                    "CREATE TABLE BidPageSettings ("
                    "UID INTEGER, BidPageUID INTEGER, BidAreaSelected INTEGER)"
                )
                database.executemany(
                    "INSERT INTO BidPages VALUES (?, 7)",
                    ((uid,) for uid in range(1, page_count + 1)),
                )
                database.executemany(
                    "INSERT INTO BidPageSettings VALUES (?, ?, 1)",
                    ((uid, uid) for uid in range(1, page_count + 1)),
                )
                database.execute("INSERT INTO BidPages VALUES (2000, 8)")
                database.execute("INSERT INTO BidPageSettings VALUES (2000, 2000, 1)")
                database.execute("INSERT INTO BidPageSettings VALUES (3000, 3000, 1)")
                schema = _SelectiveSchema(
                    {
                        "BidPages": ("UID", "BidUID"),
                        "BidPageSettings": (
                            "UID",
                            "BidPageUID",
                            "BidAreaSelected",
                        ),
                    }
                )
                connection = _LimitedReadConnection(database, schema)
                rows = _TolerantReadPolicyReader()._select_all_by_bid_or_page(
                    connection,
                    "BidPageSettings",
                    "7",
                    [str(uid) for uid in range(1, page_count + 1)],
                )
                self.assertEqual(
                    [row["UID"] for row in rows],
                    [str(uid) for uid in range(1, page_count + 1)],
                )
                self.assertEqual(len(connection.queries), 1)
                query, parameter_count = connection.queries[0]
                self.assertEqual(parameter_count, 1)
                self.assertIn("SELECT [UID] FROM [BidPages]", query)
                database.close()

    def test_page_owned_fallback_is_not_reported_as_a_sql_read_error(self):
        database = sqlite3.connect(":memory:")
        database.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        database.execute(
            "CREATE TABLE BidPageSettings (UID INTEGER, BidPageUID INTEGER)"
        )
        database.execute("INSERT INTO BidPages VALUES (10, 7)")
        database.execute("INSERT INTO BidPageSettings VALUES (20, 10)")
        schema = _SelectiveSchema(
            {
                "BidPages": ("UID", "BidUID"),
                "BidPageSettings": ("UID", "BidPageUID"),
            }
        )
        connection = _LimitedReadConnection(database, schema)
        rows = _StrictReadPolicyReader()._select_all_by_bid_or_page(
            connection, "BidPageSettings", "7", ["10"]
        )
        self.assertEqual([row["UID"] for row in rows], ["20"])
        database.close()

    def test_page_table_with_bid_uid_keeps_direct_reader_path(self):
        database = sqlite3.connect(":memory:")
        database.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        database.execute(
            "CREATE TABLE BidComments ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)"
        )
        database.executemany(
            "INSERT INTO BidComments VALUES (?, ?, ?)",
            ((1, 7, 10), (2, 8, 20)),
        )
        schema = _SelectiveSchema(
            {
                "BidPages": ("UID", "BidUID"),
                "BidComments": ("UID", "BidUID", "BidPageUID"),
            }
        )
        connection = _LimitedReadConnection(database, schema)
        rows = _StrictReadPolicyReader()._select_all_by_bid_or_page(
            connection, "BidComments", "7", ["10"]
        )
        self.assertEqual([row["UID"] for row in rows], ["1"])
        self.assertEqual(len(connection.queries), 1)
        query, parameter_count = connection.queries[0]
        self.assertEqual(parameter_count, 1)
        self.assertIn("WHERE [BidUID] = ?", query)
        self.assertNotIn("SELECT [UID] FROM [BidPages]", query)
        database.close()

    def test_page_area_selection_reader_uses_one_bid_scoped_query(self):
        page_count = 1000
        database = sqlite3.connect(":memory:")
        database.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        database.execute(
            "CREATE TABLE BidPageSettings ("
            "UID INTEGER, BidPageUID INTEGER, BidAreaUID INTEGER, "
            "BidAreaSelected INTEGER)"
        )
        database.executemany(
            "INSERT INTO BidPages VALUES (?, 7)",
            ((uid,) for uid in range(1, page_count + 1)),
        )
        database.executemany(
            "INSERT INTO BidPageSettings VALUES (?, ?, ?, 1)",
            ((uid, uid, 1000 + uid) for uid in range(1, page_count + 1)),
        )
        database.execute("INSERT INTO BidPageSettings VALUES (2001, 1, 9001, 2)")
        database.execute("INSERT INTO BidPageSettings VALUES (2002, 1, 9002, 2)")
        database.execute("INSERT INTO BidPages VALUES (3000, 8)")
        database.execute("INSERT INTO BidPageSettings VALUES (3000, 3000, 9999, 3)")
        schema = _SelectiveSchema(
            {
                "BidPages": ("UID", "BidUID"),
                "BidPageSettings": (
                    "UID",
                    "BidPageUID",
                    "BidAreaUID",
                    "BidAreaSelected",
                ),
            }
        )
        connection = _LimitedReadConnection(database, schema)
        selected = _StrictReadPolicyReader()._parse_page_area_selections_for_bid(
            connection,
            "7",
            {str(uid): object() for uid in range(1, page_count + 1)},
            schema,
        )
        self.assertEqual(len(selected), page_count)
        self.assertEqual(selected["1"], "9002")
        self.assertEqual(selected["1000"], "2000")
        self.assertNotIn("3000", selected)
        self.assertEqual(connection.queries[0][1], 1)
        self.assertEqual(len(connection.queries), 1)
        self.assertEqual(schema.optional_table_calls, ["BidPageSettings"])
        self.assertEqual(len(schema.require_column_calls), 3)
        self.assertEqual(schema.column_exists_calls, [("BidPageSettings", "UID")])
        database.close()

    def test_bid_load_rejects_takeoff_with_missing_required_owner(self):
        class OwnerValidationReader(BidDataReaderMixin):
            @contextmanager
            def _connection(self, _file_path):
                yield object()

            @staticmethod
            def _schema(_connection):
                return _Schema()

            @staticmethod
            def _parse_cdn_types(_connection):
                return {}

            @staticmethod
            def _parse_bid_layers_for_bid(_connection, _bid_uid):
                return {}

            @staticmethod
            def _parse_bid_pages_for_bid(_connection, _bid_uid, _layers, _schema):
                return {"3": SimpleNamespace(uid="3")}

            @staticmethod
            def _parse_bid_areas_for_bid(_connection, _bid_uid, _schema):
                return {}

            @staticmethod
            def _parse_page_area_selections_for_bid(
                _connection, _bid_uid, _pages, _schema
            ):
                return {}

            @staticmethod
            def _parse_bid_conditions_for_bid(
                _connection, _bid_uid, _layers, _cdn_types, _schema
            ):
                return {"5": SimpleNamespace(uid="5")}

            @staticmethod
            def _parse_bid_takeoffs_for_bid(_connection, _bid_uid, _schema):
                return (
                    [
                        Takeoff(
                            uid="7",
                            condition_uid="99",
                            page_uid="3",
                            position=[0.0, 0.0, 1.0, 1.0],
                        )
                    ],
                    {},
                )

            @staticmethod
            def _parse_bid_annotations_for_bid(_connection, _bid_uid, _layers, _schema):
                return []

            @staticmethod
            def _parse_bid_condition_folders_for_bid(_connection, _bid_uid, _schema):
                return {}

            @staticmethod
            def _parse_bid_selected_page(_connection, _bid_uid):
                return None

            @staticmethod
            def _hydrates_bid_navigation_snapshots():
                return False

        with self.assertRaisesRegex(
            RuntimeError,
            "BidTakeoffs.UID=7 references missing BidConditions.UID=99",
        ):
            OwnerValidationReader().get_bid_data("malformed.mdb", "1")

    def test_bid_load_rejects_takeoff_with_missing_parent(self):
        takeoff = Takeoff(
            uid="7",
            condition_uid="5",
            page_uid="3",
            parent_uid="99",
            position=[0.0, 0.0, 1.0, 1.0],
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "BidTakeoffs.UID=7 references missing BidTakeoffs.UID=99",
        ):
            _owner_validation_reader([takeoff]).get_bid_data("malformed.mdb", "1")

    def test_bid_load_rejects_self_parented_takeoff(self):
        takeoff = Takeoff(
            uid="7",
            condition_uid="5",
            page_uid="3",
            parent_uid="7",
            position=[0.0, 0.0, 1.0, 1.0],
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "BidTakeoffs.UID=7 participates in a ParentUID cycle",
        ):
            _owner_validation_reader([takeoff]).get_bid_data("malformed.mdb", "1")

    def test_bid_load_rejects_multi_takeoff_parent_cycle(self):
        takeoffs = [
            Takeoff(
                uid="7",
                condition_uid="5",
                page_uid="3",
                parent_uid="8",
                position=[0.0, 0.0, 1.0, 1.0],
            ),
            Takeoff(
                uid="8",
                condition_uid="5",
                page_uid="3",
                parent_uid="9",
                position=[0.0, 0.0, 1.0, 1.0],
            ),
            Takeoff(
                uid="9",
                condition_uid="5",
                page_uid="3",
                parent_uid="7",
                position=[0.0, 0.0, 1.0, 1.0],
            ),
        ]
        with self.assertRaisesRegex(RuntimeError, "participates in a ParentUID cycle"):
            _owner_validation_reader(takeoffs).get_bid_data("malformed.mdb", "1")

    def test_bid_load_accepts_valid_multi_level_takeoff_parent_chain(self):
        takeoffs = [
            Takeoff(
                uid="7",
                condition_uid="5",
                page_uid="3",
                position=[0.0, 0.0, 1.0, 1.0],
            ),
            Takeoff(
                uid="8",
                condition_uid="5",
                page_uid="3",
                parent_uid="7",
                position=[0.0, 0.0, 1.0, 1.0],
            ),
            Takeoff(
                uid="9",
                condition_uid="5",
                page_uid="3",
                parent_uid="8",
                position=[0.0, 0.0, 1.0, 1.0],
            ),
        ]
        loaded = _owner_validation_reader(takeoffs).get_bid_data("valid.mdb", "1")
        self.assertEqual([takeoff.uid for takeoff in loaded[1]], ["7", "8", "9"])

    def test_delete_content_scan_discards_partial_results_after_failure(self):
        reader = _Reader()
        self.assertIsNone(reader.get_pages_with_delete_content("project.mdb", "bid-1"))
        self.assertGreaterEqual(reader.connection.query_count, 3)

    def test_current_page_delete_stops_when_content_verification_is_unavailable(self):
        critical = Mock()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.can_delete_current_page = lambda: True
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="page-1",
            get_selected_bid_ref=lambda: BidRef("project.mdb", "bid-1"),
        )
        coordinator.project_data = SimpleNamespace(
            get_page=lambda _uid: object(),
        )
        coordinator._project_read_service = SimpleNamespace(
            get_pages_with_delete_content=lambda _file_path, _bid_uid: None
        )
        coordinator._stage_selection_after_page_delete = Mock()
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False,
            delete_pages=Mock(side_effect=AssertionError("delete must not run")),
        )
        coordinator.main_window = object()
        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator."
            "show_critical",
            critical,
        ):
            coordinator.delete_current_page()
        critical.assert_called_once()
        coordinator._stage_selection_after_page_delete.assert_not_called()
        coordinator._project_write_service.delete_pages.assert_not_called()

    def test_cover_sheet_stops_when_content_verification_is_unavailable(self):
        read_service = SimpleNamespace(
            get_cover_sheet_data=lambda _file_path, _bid_uid: object(),
            get_employee_uids_in_use=lambda _file_path: set(),
            get_pages_with_takeoffs=lambda _file_path, _bid_uid: set(),
            get_pages_with_delete_content=lambda _file_path, _bid_uid: None,
        )
        handler = CoverSheetHandler(
            window=object(),
            icon_provider=object(),
            project_data_service=object(),
            project_read_service=read_service,
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _file_path: False
            ),
            infrastructure_provider=object(),
            event_bus=object(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("project.mdb", "bid-1")
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            deferred_persistence_manager=object(),
            workspace_state_model=object(),
        )
        with patch(
            "ost_visualizer.presentation.handlers.cover_sheet_handler.show_critical"
        ) as critical, patch(
            "ost_visualizer.presentation.handlers.cover_sheet_handler.CoverSheetDialog",
            side_effect=AssertionError("dialog must not open"),
        ):
            handler.open_cover_sheet()
        critical.assert_called_once()


if __name__ == "__main__":
    unittest.main()
