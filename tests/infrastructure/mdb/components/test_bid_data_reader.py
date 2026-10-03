from tests.helpers.mdb.operations import (
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteMdbOps,
    _SqliteRow,
    _SqliteSchema,
)
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.components.takeoff_operations import (
    TakeoffOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.settings_operations import (
    SettingsOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.project_operations import (
    ProjectOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.layer_operations import (
    LayerOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_operations import (
    ConditionOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_folder_operations import (
    ConditionFolderOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    AccessBulkWriteMixin,
)
from ost_visualizer.infrastructure.mdb.components.bid_operations import (
    BidOperationsMixin,
)
import unittest
import sqlite3
import logging
from collections import namedtuple
from contextlib import contextmanager
from types import SimpleNamespace
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.infrastructure.mdb.components.bid_data_reader import (
    BidDataReaderMixin,
)
from tests.infrastructure.mdb.components.bid_reader_support import (
    _FailingContentConnection,
    _LimitedReadConnection,
    _LimitedReadCursor,
    _Reader,
    _Schema,
    _SelectiveSchema,
    _StrictReadPolicyReader,
    _TolerantReadPolicyReader,
    _owner_validation_reader,
)
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    CyclicBidOwnedReferenceError,
    DanglingBidOwnedReferenceError,
    IncoherentBidOwnedScopeError,
)
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.layer import Layer
from ost_visualizer.infrastructure.mdb.bid_settings_contract import (
    BidSettingsCardinalityError,
)
import pyodbc
from ost_visualizer.infrastructure.mdb.schema_compatibility import (
    UnsupportedMdbSchemaError,
)
from tests.helpers.mdb.import_export_support import (
    _Rows as _import_export_support__Rows,
    _SqliteConnection as _import_export_support__SqliteConnection,
    _SqliteCursor as _import_export_support__SqliteCursor,
    _SqliteSchema as _import_export_support__SqliteSchema,
    _create_import_schema as _import_export_support__create_import_schema,
    _named_row as _import_export_support__named_row,
)
from tests.infrastructure.mdb.components.takeoff_hydration_support import (
    _Connection as _takeoff_hydration_support__Connection,
    _Cursor as _takeoff_hydration_support__Cursor,
    _Schema as _takeoff_hydration_support__Schema,
    _hydrate as _takeoff_hydration_support__hydrate,
)
from unittest.mock import Mock
from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyFolderInfo,
    HierarchyPageInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page, build_pages_from_bid_data
from ost_visualizer.domain.entities.project_factory import build_bid
from tests.infrastructure.mdb.components.bid_reader_support import (
    _LimitedReadConnection,
)
from tests.infrastructure.mdb.components.test_hierarchy_reader import (
    _SqliteHierarchySchema,
)
import os
from PySide6 import QtWidgets
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.services.uom_service import (
    CALC_COUNT,
    CALC_AREA,
    CALC_LINEAR_BOTH_SIDES,
    CALC_LINEAR_LENGTH,
    CALC_VOLUME,
    UOM_CUBIC_FEET,
    UOM_EACH,
    UOM_LINEAR_FEET,
    UOM_M,
    UOM_M2,
    UOM_M3,
    UOM_SQUARE_FEET,
    UOM_SQUARE_ROOFING,
    get_uom_label,
    normalize_condition_uoms_for_system,
)
from tests.integration.quantities.uom_support import (
    _ReaderConnection as _uom_support__ReaderConnection,
    _ReaderCursor as _uom_support__ReaderCursor,
    _ReaderSchema as _uom_support__ReaderSchema,
    _app as _uom_support__app,
)
from ost_visualizer.infrastructure.mdb.components.overlay_rect import (
    EMPTY_OVERLAY_RECT,
    full_page_overlay_rect,
    parse_overlay_rect_storage,
)
from tests.integration.geometry.overlay_calibration_support import (
    CALIBRATED_64_RECT as _overlay_calibration_support_CALIBRATED_64_RECT,
    _AllPageColumnsSchema as _overlay_calibration_support__AllPageColumnsSchema,
    _RecordingLogger as _overlay_calibration_support__RecordingLogger,
    _RowsConnection as _overlay_calibration_support__RowsConnection,
    _RowsCursor as _overlay_calibration_support__RowsCursor,
    _page_row as _overlay_calibration_support__page_row,
)
from tests.infrastructure.mdb.components.bid_reader_support import (
    _owner_validation_reader,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _SqliteBidReader(BidDataReaderMixin):
    logger = logging.getLogger("test.bid_reader")

    def __init__(self, connection):
        self._connection_ref = connection
        self._schema_ref = _SqliteSchema(connection)

    def _connection(self, _file_path):
        return _SqliteConnectionWrapper(self._connection_ref)

    def _schema(self, _connection):
        return self._schema_ref

    @staticmethod
    def _record_caught_read_error(_exc, _file_path=None):
        return False


class BidDataReaderPersistenceTests(unittest.TestCase):
    def test_bid_dictionary_readers_reject_duplicate_authoritative_uids(self):
        fixtures = (
            (
                "BidLayers",
                "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT, Show INTEGER)",
                "INSERT INTO BidLayers VALUES (7, 1, ?, -1)",
                lambda ops, connection, schema: MdbReader._parse_bid_layers_for_bid(
                    ops, connection, "1"
                ),
            ),
            (
                "BidAreas",
                "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, Name TEXT)",
                "INSERT INTO BidAreas (UID, BidUID, Name) VALUES (7, 1, ?)",
                lambda ops, connection, schema: MdbReader._parse_bid_areas_for_bid(
                    ops, connection, "1", schema
                ),
            ),
            (
                "BidConditionFolders",
                "CREATE TABLE BidConditionFolders (UID INTEGER, BidUID INTEGER, Name TEXT)",
                "INSERT INTO BidConditionFolders VALUES (7, 1, ?)",
                lambda ops, connection, schema: MdbReader._parse_bid_condition_folders_for_bid(
                    ops, connection, "1", schema
                ),
            ),
            (
                "BidPages",
                "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT)",
                "INSERT INTO BidPages (UID, BidUID, Name) VALUES (7, 1, ?)",
                lambda ops, connection, schema: MdbReader._parse_bid_pages_for_bid(
                    ops, connection, "1", {}, schema
                ),
            ),
            (
                "BidConditions",
                "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, Type INTEGER)",
                "INSERT INTO BidConditions (UID, BidUID, Name, Type) VALUES (7, 1, ?, 1)",
                lambda ops, connection, schema: MdbReader._parse_bid_conditions_for_bid(
                    ops, connection, "1", {}, {}, schema
                ),
            ),
        )
        for table, ddl, insert_sql, load in fixtures:
            with self.subTest(table=table):
                conn = sqlite3.connect(":memory:")
                conn.execute(ddl)
                conn.executemany(insert_sql, (("First",), ("Conflicting",)))
                ops = _SqliteMdbOps(conn)
                connection = _SqliteConnectionWrapper(conn)
                with self.assertRaisesRegex(
                    RuntimeError,
                    f"{table} contains duplicate UID 7",
                ):
                    load(ops, connection, ops._schema_ref)

    def test_condition_folder_reader_rejects_parent_cycles(self):
        fixtures = (
            ((7, 7),),
            ((7, 8), (8, 7)),
            ((7, 8), (8, 9), (9, 7)),
        )
        for rows in fixtures:
            with self.subTest(rows=rows):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    "CREATE TABLE BidConditionFolders "
                    "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
                )
                conn.executemany(
                    "INSERT INTO BidConditionFolders VALUES (?, 1, 'Folder', ?)",
                    rows,
                )
                with self.assertRaisesRegex(
                    RuntimeError,
                    "BidConditionFolders.UID=7 participates in a ParentUID cycle",
                ):
                    MdbReader._parse_bid_condition_folders_for_bid(
                        _SqliteMdbOps(conn),
                        _SqliteConnectionWrapper(conn),
                        "1",
                        _SqliteSchema(conn),
                    )

    def test_bid_area_reader_rejects_missing_or_cross_bid_parent(self):
        for other_bid_rows in ((), ((99, 2, "Other bid", None),)):
            with self.subTest(other_bid_rows=other_bid_rows):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    "CREATE TABLE BidAreas "
                    "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
                )
                conn.executemany(
                    "INSERT INTO BidAreas VALUES (?, ?, ?, ?)",
                    ((7, 1, "Missing parent", 99), *other_bid_rows),
                )
                with self.assertRaisesRegex(
                    DanglingBidOwnedReferenceError,
                    "BidAreas.UID=7 references missing BidAreas.UID=99",
                ):
                    MdbReader._parse_bid_areas_for_bid(
                        _SqliteMdbOps(conn),
                        _SqliteConnectionWrapper(conn),
                        "1",
                        _SqliteSchema(conn),
                    )

    def test_bid_area_reader_rejects_parent_cycles(self):
        for rows in (
            ((7, 7),),
            ((7, 8), (8, 7)),
            ((7, 8), (8, 9), (9, 7)),
        ):
            with self.subTest(rows=rows):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    "CREATE TABLE BidAreas "
                    "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
                )
                conn.executemany("INSERT INTO BidAreas VALUES (?, 1, 'Area', ?)", rows)
                with self.assertRaisesRegex(
                    RuntimeError,
                    "BidAreas.UID=7 participates in a ParentUID cycle",
                ):
                    MdbReader._parse_bid_areas_for_bid(
                        _SqliteMdbOps(conn),
                        _SqliteConnectionWrapper(conn),
                        "1",
                        _SqliteSchema(conn),
                    )

    def test_bid_area_reader_accepts_valid_nested_hierarchy(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidAreas "
            "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidAreas VALUES (?, 1, ?, ?)",
            ((7, "Root", None), (8, "Middle", 7), (9, "Leaf", 8)),
        )
        areas = MdbReader._parse_bid_areas_for_bid(
            _SqliteMdbOps(conn),
            _SqliteConnectionWrapper(conn),
            "1",
            _SqliteSchema(conn),
        )
        self.assertEqual(list(areas), ["7", "8", "9"])
        self.assertEqual(
            [(area.name, area.parent_uid, area.bid_uid) for area in areas.values()],
            [("Root", "", "1"), ("Middle", "7", "1"), ("Leaf", "8", "1")],
        )

    def test_bid_area_reader_normalizes_zero_parent_to_root(self):
        for stored_parent in (0, None, "0", ""):
            with self.subTest(stored_parent=stored_parent):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    "CREATE TABLE BidAreas "
                    "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID)"
                )
                conn.execute(
                    "INSERT INTO BidAreas VALUES (7, 1, 'Root', ?)", (stored_parent,)
                )
                areas = MdbReader._parse_bid_areas_for_bid(
                    _SqliteMdbOps(conn),
                    _SqliteConnectionWrapper(conn),
                    "1",
                    _SqliteSchema(conn),
                )
                self.assertEqual(list(areas), ["7"])
                self.assertEqual(areas["7"].parent_uid, "")

    def test_condition_folder_reader_preserves_orphan_and_valid_chain_contracts(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidConditionFolders "
            "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, ?, ?, ?)",
            (
                (7, 1, "Root", None),
                (8, 1, "Middle", 7),
                (9, 1, "Leaf", 8),
                (10, 1, "Missing parent", 99),
                (99, 2, "Other bid", None),
                (11, 1, "Cross-bid parent", 99),
            ),
        )
        folders = MdbReader._parse_bid_condition_folders_for_bid(
            _SqliteMdbOps(conn),
            _SqliteConnectionWrapper(conn),
            "1",
            _SqliteSchema(conn),
        )
        self.assertEqual(sorted(folders), ["10", "11", "7", "8", "9"])
        self.assertIsNone(folders["7"].parent_uid)
        self.assertEqual(folders["8"].parent_uid, "7")
        self.assertEqual(folders["9"].parent_uid, "8")
        self.assertEqual(folders["10"].parent_uid, "99")
        self.assertEqual(folders["11"].parent_uid, "99")
        self.assertEqual({folder.bid_uid for folder in folders.values()}, {"1"})
        self.assertEqual(folders["9"].name, "Leaf")

    def test_bid_layer_reader_rejects_null_zero_and_whitespace_uids(self):
        for malformed_uid in (None, 0, "0", "   "):
            with self.subTest(uid=malformed_uid):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    "CREATE TABLE BidLayers (UID, BidUID INTEGER, Name TEXT, Show INTEGER)"
                )
                conn.execute(
                    "INSERT INTO BidLayers VALUES (?, 1, 'Malformed', -1)",
                    (malformed_uid,),
                )
                with self.assertRaisesRegex(
                    RuntimeError,
                    "BidLayers contains malformed UID",
                ):
                    MdbReader._parse_bid_layers_for_bid(
                        _SqliteMdbOps(conn), _SqliteConnectionWrapper(conn), "1"
                    )


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
        self.assertEqual(len(connection.queries), 1)
        self.assertIn("SELECT [UID] FROM [BidPages]", connection.queries[0][0])
        database.close()

    def test_page_owned_reader_returns_nothing_without_bid_or_page_scope(self):
        database = sqlite3.connect(":memory:")
        database.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        database.execute("CREATE TABLE Orphans (UID INTEGER)")
        database.execute("CREATE TABLE PageOwned (UID INTEGER, BidPageUID INTEGER)")
        database.execute("INSERT INTO Orphans VALUES (1)")
        database.execute("INSERT INTO PageOwned VALUES (2, 10)")
        schema = _SelectiveSchema(
            {
                "BidPages": ("UID", "BidUID"),
                "Orphans": ("UID",),
                "PageOwned": ("UID", "BidPageUID"),
            }
        )
        connection = _LimitedReadConnection(database, schema)
        reader = _StrictReadPolicyReader()
        self.assertEqual(
            reader._select_all_by_bid_or_page(connection, "Orphans", "7", ["10"]), []
        )
        self.assertEqual(
            reader._select_all_by_bid_or_page(connection, "PageOwned", "7", []), []
        )
        self.assertEqual(
            reader._select_all_by_bid_or_page(connection, "Missing", "7", ["10"]), []
        )
        self.assertEqual(connection.queries, [])
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
        takeoff = Takeoff(
            uid="7",
            condition_uid="99",
            page_uid="3",
            position=[0.0, 0.0, 1.0, 1.0],
        )
        with self.assertRaisesRegex(
            DanglingBidOwnedReferenceError,
            "BidTakeoffs.UID=7 references missing BidConditions.UID=99",
        ):
            _owner_validation_reader([takeoff]).get_bid_data("malformed.mdb", "1")

    def test_bid_load_rejects_takeoff_with_missing_page_owner(self):
        takeoff = Takeoff(
            uid="7",
            condition_uid="5",
            page_uid="99",
            position=[0.0, 0.0, 1.0, 1.0],
        )
        with self.assertRaisesRegex(
            DanglingBidOwnedReferenceError,
            "BidTakeoffs.UID=7 references missing BidPages.UID=99",
        ):
            _owner_validation_reader([takeoff]).get_bid_data("malformed.mdb", "1")

    def test_bid_load_rejects_takeoff_with_missing_parent(self):
        takeoff = Takeoff(
            uid="7",
            condition_uid="5",
            page_uid="3",
            parent_uid="99",
            position=[0.0, 0.0, 1.0, 1.0],
        )
        with self.assertRaisesRegex(
            DanglingBidOwnedReferenceError,
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
            CyclicBidOwnedReferenceError,
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
        with self.assertRaisesRegex(
            CyclicBidOwnedReferenceError,
            "BidTakeoffs.UID=7 participates in a ParentUID cycle",
        ):
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
        self.assertEqual([takeoff.parent_uid for takeoff in loaded[1]], ["0", "7", "8"])

    def test_delete_content_scan_discards_partial_results_after_failure(self):
        reader = _Reader()
        with self.assertLogs(__name__.rsplit(".", 1)[0], level="WARNING") as logs:
            self.assertIsNone(
                reader.get_pages_with_delete_content("project.mdb", "bid-1")
            )
        self.assertIn(
            "Failed to load pages with delete-sensitive content", logs.output[0]
        )
        self.assertIn("content scan failed", logs.output[0])
        self.assertEqual(reader.connection.query_count, 3)

    def test_delete_content_scan_reports_only_this_bids_pages_with_user_content(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        for table in ("BidTakeoffs", "BidLegends", "BidTexts", "BidComments"):
            conn.execute(f"CREATE TABLE {table} (UID INTEGER, BidPageUID INTEGER)")
        conn.executemany(
            "INSERT INTO BidPages VALUES (?, ?)", ((1, 7), (2, 7), (3, 7), (4, 8))
        )
        conn.execute("INSERT INTO BidTakeoffs VALUES (10, 1)")
        conn.execute("INSERT INTO BidLegends VALUES (11, 2)")
        conn.execute("INSERT INTO BidComments VALUES (12, 4)")
        conn.execute("INSERT INTO BidTexts VALUES (13, NULL)")
        reader = _SqliteBidReader(conn)
        self.assertEqual(reader.get_pages_with_delete_content("x.mdb", "7"), {"1"})
        conn.execute("INSERT INTO BidTexts VALUES (14, 3)")
        self.assertEqual(reader.get_pages_with_delete_content("x.mdb", "7"), {"1", "3"})
        self.assertEqual(reader.get_pages_with_delete_content("x.mdb", "8"), {"4"})
        self.assertEqual(reader.get_pages_with_delete_content("x.mdb", "99"), set())

    def test_delete_content_scan_rejects_duplicate_page_uids(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.executemany("INSERT INTO BidPages VALUES (?, 7)", ((1,), (1,)))
        with self.assertLogs("test.bid_reader", level="WARNING") as logs:
            self.assertIsNone(
                _SqliteBidReader(conn).get_pages_with_delete_content("x.mdb", "7")
            )
        self.assertIn("duplicate UID 1", logs.output[0])

    def test_page_area_selection_reader_picks_highest_flag_and_leaves_unselected_none(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidPageSettings (UID INTEGER, BidPageUID INTEGER, "
            "BidAreaUID INTEGER, BidAreaSelected INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidPages VALUES (?, ?)",
            ((20, 1), (21, 1), (22, 1), (23, 1), (30, 2)),
        )
        conn.executemany(
            "INSERT INTO BidPageSettings VALUES (?, ?, ?, ?)",
            (
                (1, 20, 10, 1),
                (2, 20, 11, 2),
                (3, 20, 12, 0),
                (4, 21, 13, 0),
                (5, 22, None, 1),
                (6, 30, 14, 1),
            ),
        )
        reader = _SqliteBidReader(conn)
        pages = {uid: object() for uid in ("20", "21", "22", "23")}
        self.assertEqual(
            reader._parse_page_area_selections_for_bid(
                _SqliteConnectionWrapper(conn), "1", pages, reader._schema_ref
            ),
            {"20": "11", "21": None, "22": "0", "23": None},
        )
        self.assertEqual(
            reader._parse_page_area_selections_for_bid(
                _SqliteConnectionWrapper(conn), "1", {}, reader._schema_ref
            ),
            {},
        )
        conn.execute("DROP TABLE BidPageSettings")
        self.assertEqual(
            reader._parse_page_area_selections_for_bid(
                _SqliteConnectionWrapper(conn), "1", pages, reader._schema_ref
            ),
            {uid: None for uid in pages},
        )

    def test_selected_page_reader_returns_text_uid_or_none(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidSettings (UID INTEGER, BidUID INTEGER, BidPageSelectedUID)"
        )
        conn.executemany(
            "INSERT INTO BidSettings VALUES (?, ?, ?)",
            ((1, 1, 20), (2, 2, None), (3, 3, 0)),
        )
        reader = _SqliteBidReader(conn)
        wrapper = _SqliteConnectionWrapper(conn)
        for bid_uid, expected in (("1", "20"), ("2", None), ("3", None), ("4", None)):
            with self.subTest(bid_uid=bid_uid):
                self.assertEqual(
                    reader._parse_bid_selected_page(wrapper, bid_uid), expected
                )
        conn.execute(
            "ALTER TABLE BidSettings RENAME COLUMN BidPageSelectedUID TO Other"
        )
        self.assertIsNone(reader._parse_bid_selected_page(wrapper, "1"))
        conn.execute("DROP TABLE BidSettings")
        self.assertIsNone(reader._parse_bid_selected_page(wrapper, "1"))

    def test_condition_reader_maps_columns_with_defaults_and_layer_visibility(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "Type INTEGER, CdnTypeUID INTEGER, BidLayerUID INTEGER, "
            "BidConditionFolderUID INTEGER, DisplaySize REAL, Notes BLOB, "
            "RoundQuantity INTEGER, Trim INTEGER, DropRun INTEGER, RefNo INTEGER, "
            "UOM1 INTEGER, Quantity1 INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidConditions VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    7,
                    "Wall @ 9'",
                    2,
                    3,
                    5,
                    11,
                    0,
                    "note \u00e9".encode("utf-8"),
                    -1,
                    0,
                    -1,
                    4,
                    UOM_LINEAR_FEET,
                    CALC_LINEAR_LENGTH,
                ),
                (8, "Bare", 1, None, None, None, 80.5, None, 0, -1, 0, 0, 0, 0),
            ),
        )
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, Name, Type) VALUES (9, 2, 'Other', 1)"
        )
        reader = _SqliteBidReader(conn)
        conditions = reader._parse_bid_conditions_for_bid(
            _SqliteConnectionWrapper(conn),
            "1",
            {"5": Layer(uid="5", name="Walls", visible=False)},
            {"3": CdnType(uid="3", name="Concrete")},
            reader._schema_ref,
        )
        self.assertEqual(list(conditions), ["7", "8"])
        wall, bare = conditions["7"], conditions["8"]
        self.assertEqual(
            (
                wall.name,
                wall.condition_type,
                wall.cdn_type_uid,
                wall.cdn_type_name,
                wall.layer_uid,
                wall.layer_visible,
                wall.folder_uid,
                wall.display_size,
                wall.notes,
                wall.round_quantity,
                wall.trim,
                wall.drop_run,
                wall.ref_no,
                wall.uom1,
                wall.calc_type1,
            ),
            (
                "Wall @ 9'",
                2,
                "3",
                "Concrete",
                "5",
                False,
                "11",
                100.0,
                "note \u00e9",
                True,
                False,
                True,
                4,
                UOM_LINEAR_FEET,
                CALC_LINEAR_LENGTH,
            ),
        )
        self.assertEqual(
            (
                bare.cdn_type_uid,
                bare.cdn_type_name,
                bare.layer_uid,
                bare.layer_visible,
                bare.folder_uid,
                bare.display_size,
                bare.notes,
                bare.round_quantity,
                bare.trim,
                bare.thickness,
                bare.uom2,
            ),
            (None, "Unknown", None, True, None, 80.5, "", False, True, 0.0, 0),
        )


class ConditionDisplaySizeTests(unittest.TestCase):
    def test_non_positive_display_size_reads_as_default_percent(self):
        self.assertEqual(BidDataReaderMixin._normalize_display_size(None), 100.0)
        self.assertEqual(BidDataReaderMixin._normalize_display_size(0), 100.0)
        self.assertEqual(BidDataReaderMixin._normalize_display_size("0"), 100.0)
        self.assertEqual(BidDataReaderMixin._normalize_display_size(-5), 100.0)

    def test_positive_display_size_reads_unchanged(self):
        self.assertEqual(BidDataReaderMixin._normalize_display_size(75), 75.0)
        self.assertEqual(BidDataReaderMixin._normalize_display_size("125"), 125.0)
        self.assertEqual(BidDataReaderMixin._normalize_display_size(0.5), 0.5)


class BidDataReaderCompatibilityTests(unittest.TestCase):
    def test_bid_reader_rejects_multiple_bid_settings_rows(self):
        class Cursor:
            def __init__(self):
                self._index = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def execute(_sql, *_params):
                pass

            def fetchone(self):
                rows = ((10,), (11,))
                if self._index < len(rows):
                    row = rows[self._index]
                    self._index += 1
                    return row
                return None

        class Connection:
            @staticmethod
            def cursor():
                return Cursor()

        class Schema:
            @staticmethod
            def optional_table_missing(_table):
                return False

            @staticmethod
            def require_column(_table, _column):
                pass

            @staticmethod
            def column_exists(_table, _column):
                return True

        class Reader(MdbReader):
            @staticmethod
            def _schema(_connection):
                return Schema()

        with self.assertRaisesRegex(
            BidSettingsCardinalityError,
            "BidSettings has multiple rows for Bids.UID=1",
        ):
            Reader()._parse_bid_selected_page(Connection(), "1")


class BidDataReaderRelationshipTests(unittest.TestCase):
    def test_page_area_reader_uses_import_export_duplicate_row_precedence(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute(
            "INSERT INTO BidPages (UID, BidUID, Name, Sequence) "
            "VALUES (20, 1, 'Page', 1)"
        )
        connection.execute(
            "INSERT INTO BidPageSettings "
            "(UID, BidPageUID, BidAreaUID, BidAreaSelected) VALUES (30, 20, 10, 2)"
        )
        connection.execute(
            "INSERT INTO BidPageSettings "
            "(UID, BidPageUID, BidAreaUID, BidAreaSelected) VALUES (31, 20, 11, 2)"
        )
        selected = MdbReader()._parse_page_area_selections_for_bid(
            _import_export_support__SqliteConnection(connection),
            "1",
            {"20": object()},
            _import_export_support__SqliteSchema(connection),
        )
        self.assertEqual(selected["20"], "11")


class TakeoffHydrationContractTests(unittest.TestCase):
    def test_access_reader_builds_complete_takeoff_contract(self):
        takeoff = _takeoff_hydration_support__hydrate(BidDataReaderMixin())
        self.assertTrue(takeoff.has_valid_contract())
        self.assertEqual(takeoff.uid, "4485")
        self.assertEqual(takeoff.parent_uid, "0")
        self.assertEqual(takeoff.position, [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(takeoff.dimension_font_size, 72)
        self.assertEqual(takeoff.name_font_size, 48)
        self.assertEqual(
            (
                takeoff.condition_uid,
                takeoff.page_uid,
                takeoff.area_uid,
                takeoff.rotation,
                takeoff.curve,
                takeoff.is_negative,
            ),
            ("10", "20", "0", 15.0, 0, True),
        )
        self.assertEqual(
            (
                takeoff.dimension_font_name,
                takeoff.dimension_font_color,
                takeoff.dimension_font_bold,
                takeoff.dimension_font_italic,
                takeoff.dimension_font_underline,
            ),
            ("Arial", 255, True, False, True),
        )
        self.assertEqual(
            (
                takeoff.name_font_name,
                takeoff.name_font_color,
                takeoff.name_font_bold,
                takeoff.name_font_italic,
                takeoff.name_font_underline,
            ),
            ("Calibri", 128, False, True, False),
        )

    def test_access_reader_keeps_untyped_takeoff_columns_as_extras(self):
        columns = ("UID", "BidUID", "BidConditionUID", "BidPageUID", "Position", "Tag")
        rows = [
            (1, 7, 10, 20, b"1;2;3;4\n", "first"),
            (2, 7, 10, 20, b"5;6;7;8\n", None),
        ]
        takeoffs, extras = BidDataReaderMixin()._parse_bid_takeoffs_for_bid(
            _takeoff_hydration_support__Connection(columns, rows),
            "7",
            _takeoff_hydration_support__Schema(columns),
        )
        self.assertEqual([takeoff.uid for takeoff in takeoffs], ["1", "2"])
        self.assertEqual(takeoffs[1].position, [5.0, 6.0, 7.0, 8.0])
        self.assertEqual(takeoffs[0].area_uid, "0")
        self.assertEqual(takeoffs[0].curve, -1)
        self.assertEqual(extras, {"1": {"Tag": "first"}, "2": {"Tag": None}})

    def test_access_reader_rejects_duplicate_and_contract_violating_takeoffs(self):
        columns = ("UID", "BidUID", "BidConditionUID", "BidPageUID", "Position")
        schema = _takeoff_hydration_support__Schema(columns)
        reader = BidDataReaderMixin()
        duplicate = [(1, 7, 10, 20, b"1;2;3;4\n"), (1, 7, 10, 20, b"1;2;3;4\n")]
        with self.assertRaisesRegex(
            RuntimeError, "BidTakeoffs contains duplicate UID 1"
        ):
            reader._parse_bid_takeoffs_for_bid(
                _takeoff_hydration_support__Connection(columns, duplicate), "7", schema
            )
        non_finite_position = [(2, 7, 10, 20, b"nan;2;3;4\n")]
        with self.assertRaisesRegex(
            ValueError, "BidTakeoffs.UID=2 does not satisfy the Takeoff domain contract"
        ):
            reader._parse_bid_takeoffs_for_bid(
                _takeoff_hydration_support__Connection(columns, non_finite_position),
                "7",
                schema,
            )


class PageFolderOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.execute(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT, Sequence INTEGER, BidPageFolderUID INTEGER)"
        )
        self.connection.executemany(
            "INSERT INTO BidPages VALUES (?, ?, ?, ?, ?)",
            [
                (1, 8, "Nested second", 20, 11),
                (2, 8, "Nested first", 10, 11),
                (3, 8, "Root", 30, None),
                (4, 8, "Parent", 5, 10),
                (5, 9, "Other bid", 1, 11),
            ],
        )
        self.bid_ref = BidRef("database", "8")
        self.info = HierarchyBidInfo(
            uid="8",
            name="Bid",
            folders={
                "10": HierarchyFolderInfo(
                    name="Parent",
                    pages=[HierarchyPageInfo(uid="4", name="Parent")],
                    subfolders={
                        "11": HierarchyFolderInfo(
                            name="Nested",
                            pages=[
                                HierarchyPageInfo(uid="1", name="Nested second"),
                                HierarchyPageInfo(uid="2", name="Nested first"),
                            ],
                        )
                    },
                )
            },
            pages_without_folder=[HierarchyPageInfo(uid="3", name="Root")],
        )
        self.model = OstAggregate(Mock())
        self.model.set_hierarchy(
            HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(file_path="database", orphan_bids=[self.info])
                ]
            )
        )
        self.model.current_bid_ref = self.bid_ref
        self.model.current_bid = build_bid(self.info)

    def read(self):
        reader = BidDataReaderMixin()
        reader.logger = logging.getLogger(__name__)
        schema = _SqliteHierarchySchema(self.connection)
        infos = reader._parse_bid_pages_for_bid(
            _LimitedReadConnection(self.connection, schema), "8", {}, schema
        )
        return BidLoadResult(
            bid_pages=infos, pages=build_pages_from_bid_data(infos, [])
        )

    def test_reader_returns_only_this_bids_pages_with_folder_assignments(self):
        infos = self.read().bid_pages
        self.assertEqual(sorted(infos), ["1", "2", "3", "4"])
        self.assertEqual(
            {uid: info.folder_uid for uid, info in infos.items()},
            {"1": "11", "2": "11", "3": None, "4": "10"},
        )
        self.assertEqual(
            [info.name for info in infos.values()],
            ["Parent", "Nested first", "Nested second", "Root"],
        )

    def test_reader_rejects_duplicate_page_uids_before_projection(self):
        self.connection.execute(
            "INSERT INTO BidPages VALUES (1, 8, 'Duplicate', 99, 10)"
        )
        with self.assertRaisesRegex(RuntimeError, "duplicate UID 1"):
            self.read()


class ConditionUomConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _uom_support__app()
        cls.quit_on_close = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls.quit_on_close)

    def tearDown(self):
        self.app.processEvents()

    def test_shared_mdb_sql_reader_reconstructs_uoms_from_bid_measure_base(self):
        reader = BidDataReaderMixin()
        schema = _uom_support__ReaderSchema()
        metric = reader._parse_bid_conditions_for_bid(
            _uom_support__ReaderConnection(True), "42", {}, {}, schema
        )["1"]
        imperial = reader._parse_bid_conditions_for_bid(
            _uom_support__ReaderConnection(False), "42", {}, {}, schema
        )["1"]
        self.assertEqual(
            (metric.uom1, metric.uom2, metric.uom3), (UOM_M, UOM_M2, UOM_M3)
        )
        self.assertEqual(
            (imperial.uom1, imperial.uom2, imperial.uom3),
            (UOM_LINEAR_FEET, UOM_SQUARE_FEET, UOM_CUBIC_FEET),
        )
        for condition in (metric, imperial):
            self.assertEqual(
                (condition.calc_type1, condition.calc_type2, condition.calc_type3),
                (CALC_LINEAR_LENGTH, CALC_LINEAR_BOTH_SIDES, CALC_VOLUME),
            )


class OverlayCoordinateContractTests(unittest.TestCase):
    def test_mdb_reader_loads_overlay_rect_directly(self):
        connection = _overlay_calibration_support__RowsConnection(
            [
                _overlay_calibration_support__page_row(
                    _overlay_calibration_support_CALIBRATED_64_RECT
                )
            ]
        )
        pages = BidDataReaderMixin()._parse_bid_pages_for_bid(
            connection,
            "57895",
            {},
            _overlay_calibration_support__AllPageColumnsSchema(),
        )
        self.assertEqual(
            pages["58227"].overlay_rect, _overlay_calibration_support_CALIBRATED_64_RECT
        )
        page = pages["58227"]
        self.assertEqual(
            (
                page.overlay_offset_x,
                page.overlay_offset_y,
                page.image_show_mode,
                page.width_pts,
                page.height_pts,
            ),
            (
                _overlay_calibration_support_CALIBRATED_64_RECT[0],
                _overlay_calibration_support_CALIBRATED_64_RECT[1],
                2,
                42.0 * 72.0,
                30.0 * 72.0,
            ),
        )
        self.assertTrue(connection.statements)
        self.assertTrue(
            all(
                statement.lstrip().upper().startswith("SELECT")
                for statement in connection.statements
            )
        )

    def test_mdb_reader_rejects_page_uid_zero_instead_of_loading_a_page(self):
        # Decision D11: 0 can never be a Page UID (it is the "no page" spelling
        # that the page-area canonicalisation relies on), so a stored BidPages row
        # with UID 0 fails the Bid load rather than becoming a page "0".
        row = _overlay_calibration_support__page_row(
            _overlay_calibration_support_CALIBRATED_64_RECT
        )
        row.UID = 0
        with self.assertRaisesRegex(RuntimeError, "BidPages contains malformed UID 0"):
            BidDataReaderMixin()._parse_bid_pages_for_bid(
                _overlay_calibration_support__RowsConnection([row]),
                "57895",
                {},
                _overlay_calibration_support__AllPageColumnsSchema(),
            )

    def test_mdb_reader_exposes_malformed_rect_as_no_geometry(self):
        row = _overlay_calibration_support__page_row(
            _overlay_calibration_support_CALIBRATED_64_RECT
        )
        row.OverlayRect = "0,0,not-a-width,1920"
        connection = _overlay_calibration_support__RowsConnection([row])
        reader = BidDataReaderMixin()
        reader.logger = _overlay_calibration_support__RecordingLogger()
        pages = reader._parse_bid_pages_for_bid(
            connection,
            "57895",
            {},
            _overlay_calibration_support__AllPageColumnsSchema(),
        )
        self.assertEqual(pages["58227"].overlay_rect, EMPTY_OVERLAY_RECT)
        self.assertEqual(len(reader.logger.warnings), 1)
        self.assertTrue(
            reader.logger.warnings[0].startswith(
                "Ignoring invalid OverlayRect for page 58227:"
            )
        )

    def test_mdb_reader_accepts_native_empty_rect_marker_without_warning(self):
        row = _overlay_calibration_support__page_row(EMPTY_OVERLAY_RECT)
        row.OverlayRect = "*"
        connection = _overlay_calibration_support__RowsConnection([row])
        reader = BidDataReaderMixin()
        reader.logger = _overlay_calibration_support__RecordingLogger()
        pages = reader._parse_bid_pages_for_bid(
            connection,
            "57895",
            {},
            _overlay_calibration_support__AllPageColumnsSchema(),
        )
        self.assertEqual(pages["58227"].overlay_rect, EMPTY_OVERLAY_RECT)
        self.assertEqual(reader.logger.warnings, [])


class TakeoffLifecycleOwnershipTests(unittest.TestCase):
    def test_reader_rejects_parent_on_another_page(self):
        takeoffs = [
            Takeoff(uid="7", condition_uid="5", page_uid="3"),
            Takeoff(uid="8", condition_uid="5", page_uid="4", parent_uid="7"),
        ]
        reader = _owner_validation_reader(takeoffs)
        reader._parse_bid_pages_for_bid = lambda *_: {
            uid: SimpleNamespace(uid=uid) for uid in ("3", "4")
        }
        with self.assertRaisesRegex(
            IncoherentBidOwnedScopeError,
            "A Takeoff and its parent must belong to the same Page.",
        ):
            reader.get_bid_data("malformed.mdb", "1")
