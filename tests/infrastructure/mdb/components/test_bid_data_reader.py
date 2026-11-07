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
    UOM_CUBIC_YARDS,
    UOM_EACH,
    UOM_INCHES,
    UOM_SQUARE_INCHES,
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
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.infrastructure.parsers.position_parser import (
    extract_z_value_from_name,
)
from ost_visualizer.infrastructure.mdb.components.constants import (
    PAGE_DELETE_CONFIRMATION_TABLES,
)
from ost_visualizer.infrastructure.mdb.schema_contract import (
    PAGE_SECTIONS,
    RAW_BID_TABLES,
    RAW_GLOBAL_TABLES,
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
                    "BidAreas.UID=7 references missing BidAreas.UID=99 "
                    r"through ParentUID\.$",
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
            "BidTakeoffs.UID=7 references missing BidConditions.UID=99 "
            r"through BidConditionUID\.$",
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
            "BidTakeoffs.UID=7 references missing BidPages.UID=99 "
            r"through BidPageUID\.$",
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
            "BidTakeoffs.UID=7 references missing BidTakeoffs.UID=99 "
            r"through ParentUID\.$",
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
        self.assertIn("BidPages contains duplicate UID 1", logs.output[0])

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
    @staticmethod
    def _selected_page_reader(execute):
        class Cursor:
            def __init__(self):
                self._rows = [("20",)]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, *params):
                return execute(sql, *params)

            def fetchone(self):
                return self._rows.pop(0) if self._rows else None

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

        return Reader(), Connection()

    def test_failed_selected_page_read_is_logged_and_yields_no_saved_page(self):
        def fail(_sql, *_params):
            raise pyodbc.Error("HY000", "transient lock error")

        reader, connection = self._selected_page_reader(fail)
        with self.assertLogs(reader.logger, level="WARNING") as logged:
            self.assertIsNone(reader._parse_bid_selected_page(connection, "7"))
        self.assertEqual(len(logged.records), 1)
        message = logged.records[0].getMessage()
        self.assertIn("bid 7", message)
        self.assertIn("transient lock error", message)
        self.assertIs(logged.records[0].exc_info[0], pyodbc.Error)

    def test_successful_selected_page_read_does_not_log(self):
        reader, connection = self._selected_page_reader(lambda _sql, *_params: None)
        with self.assertNoLogs(reader.logger, level="WARNING"):
            self.assertEqual(reader._parse_bid_selected_page(connection, "7"), "20")

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


class _FailingTableCursor(_SqliteCursorWrapper):
    """Raises a pyodbc error for any statement that reads one of fail_tables."""

    def __init__(self, connection, fail_tables):
        super().__init__(connection)
        self._fail_tables = fail_tables

    def execute(self, query, *params):
        if any(f"[{table}]" in query for table in self._fail_tables):
            raise pyodbc.Error("HY000", "injected read failure")
        try:
            return super().execute(query, *params)
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            # Access reports an absent optional table as a pyodbc error.
            raise pyodbc.Error("42S02", str(exc)) from exc


class _FailingTableConnection(_SqliteConnectionWrapper):
    def __init__(self, connection, fail_tables):
        super().__init__(connection)
        self._fail_tables = fail_tables

    def cursor(self):
        return _FailingTableCursor(self._connection, self._fail_tables)


class _SqliteFullReader(MdbReader):
    """Real MdbReader (all mixins) over sqlite; read errors tolerated unless strict."""

    def __init__(self, connection, strict=False, fail_tables=()):
        self.logger = logging.getLogger("test.full_reader")
        self._connection_ref = connection
        self._schema_ref = _SqliteSchema(connection)
        self._strict = strict
        self._fail_tables = tuple(fail_tables)

    def _connection(self, _file_path):
        return _FailingTableConnection(self._connection_ref, self._fail_tables)

    def _schema(self, _connection):
        return self._schema_ref

    def _record_caught_read_error(self, _exc, _file_path=None):
        return self._strict


def _db(*ddl):
    conn = sqlite3.connect(":memory:")
    for statement in ddl:
        conn.execute(statement)
    return conn


def _insert(conn, table, columns, rows):
    marks = ", ".join("?" for _c in columns)
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({marks})", rows
    )


class DatabaseStatisticsTests(unittest.TestCase):
    def test_statistics_count_every_table_under_its_own_key(self):
        conn = _db(
            "CREATE TABLE BidProjects (UID INTEGER)",
            "CREATE TABLE Bids (UID INTEGER)",
            "CREATE TABLE BidTakeoffs (UID INTEGER)",
            "CREATE TABLE BidConditions (UID INTEGER)",
            "CREATE TABLE BidPages (UID INTEGER)",
        )
        for table, count in (
            ("BidProjects", 2),
            ("Bids", 3),
            ("BidTakeoffs", 5),
            ("BidConditions", 7),
            ("BidPages", 11),
        ):
            _insert(conn, table, ("UID",), [(i + 1,) for i in range(count)])
        self.assertEqual(
            _SqliteBidReader(conn).get_database_statistics("x.mdb"),
            {"projects": 2, "bids": 3, "takeoffs": 5, "conditions": 7, "pages": 11},
        )

    def test_statistics_report_zero_for_tables_a_legacy_file_lacks(self):
        conn = _db("CREATE TABLE Bids (UID INTEGER)")
        _insert(conn, "Bids", ("UID",), [(1,), (2,)])
        self.assertEqual(
            _SqliteBidReader(conn).get_database_statistics("x.mdb"),
            {"projects": 0, "bids": 2, "takeoffs": 0, "conditions": 0, "pages": 0},
        )


class BidFamilyReaderTests(unittest.TestCase):
    def _family_db(self):
        conn = _db(
            "CREATE TABLE Bids (UID INTEGER, MeasureBase INTEGER)",
            "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT, Show INTEGER)",
            "CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)",
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "Type INTEGER, CdnTypeUID INTEGER, BidLayerUID INTEGER)",
            "CREATE TABLE BidConditionFolders (UID INTEGER, BidUID INTEGER, "
            "Name TEXT, ParentUID INTEGER)",
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "Sequence INTEGER)",
        )
        _insert(conn, "Bids", ("UID", "MeasureBase"), [(1, 0), (2, 0)])
        _insert(
            conn,
            "BidLayers",
            ("UID", "BidUID", "Name", "Show"),
            [(5, 1, "Walls", 0), (6, 2, "Other", -1)],
        )
        _insert(conn, "CdnTypes", ("UID", "Name"), [(3, "Concrete")])
        _insert(
            conn,
            "BidConditions",
            ("UID", "BidUID", "Name", "Type", "CdnTypeUID", "BidLayerUID"),
            [(7, 1, "Wall", 2, 3, 5), (8, 2, "Foreign", 1, None, 6)],
        )
        _insert(
            conn,
            "BidConditionFolders",
            ("UID", "BidUID", "Name", "ParentUID"),
            [(10, 1, "Root", None), (11, 1, "Child", 10), (12, 2, "Foreign", None)],
        )
        _insert(
            conn,
            "BidAreas",
            ("UID", "BidUID", "Name", "Sequence"),
            [(21, 1, "Second", 2), (20, 1, "First", 1), (22, 2, "Foreign", 1)],
        )
        return conn

    def test_condition_family_returns_only_the_bids_conditions_and_folders(self):
        reader = _SqliteFullReader(self._family_db())
        conditions, folders = reader.get_condition_family("x.mdb", "1")
        self.assertEqual(list(conditions), ["7"])
        wall = conditions["7"]
        self.assertEqual(
            (wall.name, wall.cdn_type_name, wall.layer_uid, wall.layer_visible),
            ("Wall", "Concrete", "5", False),
        )
        self.assertEqual(
            {uid: (f.name, f.parent_uid, f.bid_uid) for uid, f in folders.items()},
            {"10": ("Root", None, "1"), "11": ("Child", "10", "1")},
        )

    def test_condition_family_of_a_missing_bid_is_a_missing_owner_error(self):
        reader = _SqliteFullReader(self._family_db())
        with self.assertRaisesRegex(RuntimeError, "Bids has no row for UID 99"):
            reader.get_condition_family("x.mdb", "99")

    def test_condition_family_requires_a_complete_folder_read_even_when_tolerant(
        self,
    ):
        reader = _SqliteFullReader(
            self._family_db(), strict=False, fail_tables=("BidConditionFolders",)
        )
        with self.assertRaises(pyodbc.Error):
            reader.get_condition_family("x.mdb", "1")

    def test_bid_load_tolerates_a_failed_folder_read_unless_errors_are_recorded(self):
        conn = self._family_db()
        schema = _SqliteSchema(conn)
        tolerant = _SqliteFullReader(conn, fail_tables=("BidConditionFolders",))
        self.assertEqual(
            tolerant._parse_bid_condition_folders_for_bid(
                _FailingTableConnection(conn, ("BidConditionFolders",)), "1", schema
            ),
            {},
        )
        strict = _SqliteFullReader(
            conn, strict=True, fail_tables=("BidConditionFolders",)
        )
        with self.assertRaises(pyodbc.Error):
            strict._parse_bid_condition_folders_for_bid(
                _FailingTableConnection(conn, ("BidConditionFolders",)), "1", schema
            )

    def test_area_family_returns_the_bids_areas_in_sequence_order(self):
        reader = _SqliteFullReader(self._family_db())
        areas = reader.get_area_family("x.mdb", "1")
        self.assertEqual(
            [(a.uid, a.name, a.sequence) for a in areas],
            [
                ("20", "First", 1),
                ("21", "Second", 2),
            ],
        )

    def test_area_family_of_a_missing_bid_is_a_missing_owner_error(self):
        reader = _SqliteFullReader(self._family_db())
        with self.assertRaisesRegex(RuntimeError, "Bids has no row for UID 99"):
            reader.get_area_family("x.mdb", "99")

    def test_area_family_requires_a_complete_read_even_when_tolerant(self):
        reader = _SqliteFullReader(
            self._family_db(), strict=False, fail_tables=("BidAreas",)
        )
        with self.assertRaises(pyodbc.Error):
            reader.get_area_family("x.mdb", "1")

    def test_bid_load_tolerates_a_failed_area_read_unless_errors_are_recorded(self):
        conn = self._family_db()
        schema = _SqliteSchema(conn)
        failing = _FailingTableConnection(conn, ("BidAreas",))
        self.assertEqual(
            _SqliteFullReader(conn)._parse_bid_areas_for_bid(failing, "1", schema), {}
        )
        with self.assertRaises(pyodbc.Error):
            _SqliteFullReader(conn, strict=True)._parse_bid_areas_for_bid(
                failing, "1", schema
            )
        with self.assertRaises(pyodbc.Error):
            _SqliteFullReader(conn)._parse_bid_areas_for_bid(
                failing, "1", schema, require_complete=True
            )


class BidAreaMappingTests(unittest.TestCase):
    def test_every_area_column_is_mapped_and_ordered_by_sequence(self):
        conn = _db(
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, ParentUID INTEGER, "
            "Name TEXT, Sequence INTEGER, GUID TEXT)"
        )
        _insert(
            conn,
            "BidAreas",
            ("UID", "BidUID", "ParentUID", "Name", "Sequence", "GUID"),
            [
                (9, 1, 8, "Leaf", 3, "{G-9}"),
                (8, 1, None, "Root", 5, "{G-8}"),
                (7, 2, None, "Foreign", 1, "{G-7}"),
            ],
        )
        reader = _SqliteBidReader(conn)
        areas = reader._parse_bid_areas_for_bid(
            _SqliteConnectionWrapper(conn), "1", reader._schema_ref
        )
        self.assertEqual(list(areas), ["9", "8"])
        self.assertEqual(
            [
                (a.uid, a.bid_uid, a.parent_uid, a.name, a.sequence, a.guid)
                for a in areas.values()
            ],
            [
                ("9", "1", "8", "Leaf", 3, "{G-9}"),
                ("8", "1", "", "Root", 5, "{G-8}"),
            ],
        )

    def test_missing_optional_area_columns_use_blank_defaults_ordered_by_uid(self):
        conn = _db("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
        _insert(conn, "BidAreas", ("UID", "BidUID"), [(9, 1), (8, 1)])
        reader = _SqliteBidReader(conn)
        areas = reader._parse_bid_areas_for_bid(
            _SqliteConnectionWrapper(conn), "1", reader._schema_ref
        )
        self.assertEqual(list(areas), ["8", "9"])
        self.assertEqual(
            [(a.parent_uid, a.name, a.sequence, a.guid) for a in areas.values()],
            [("", "", 0, ""), ("", "", 0, "")],
        )

    def test_null_and_empty_area_values_read_as_defaults(self):
        conn = _db(
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, ParentUID INTEGER, "
            "Name TEXT, Sequence INTEGER, GUID TEXT)"
        )
        _insert(
            conn,
            "BidAreas",
            ("UID", "BidUID", "ParentUID", "Name", "Sequence", "GUID"),
            [(7, 1, None, None, None, None), (8, 1, None, "", 0, "")],
        )
        reader = _SqliteBidReader(conn)
        areas = reader._parse_bid_areas_for_bid(
            _SqliteConnectionWrapper(conn), "1", reader._schema_ref
        )
        self.assertEqual(
            [(a.name, a.sequence, a.guid) for a in areas.values()],
            [("", 0, ""), ("", 0, "")],
        )

    def test_a_bid_without_an_area_table_has_no_areas(self):
        conn = _db("CREATE TABLE Bids (UID INTEGER)")
        reader = _SqliteBidReader(conn)
        self.assertEqual(
            reader._parse_bid_areas_for_bid(
                _SqliteConnectionWrapper(conn), "1", reader._schema_ref
            ),
            {},
        )

    def test_folder_reader_handles_a_missing_table_and_requires_its_columns(self):
        conn = _db("CREATE TABLE Bids (UID INTEGER)")
        reader = _SqliteBidReader(conn)
        self.assertEqual(
            reader._parse_bid_condition_folders_for_bid(
                _SqliteConnectionWrapper(conn), "1", reader._schema_ref
            ),
            {},
        )
        for column in ("UID", "BidUID", "Name"):
            with self.subTest(missing=column):
                remaining = [c for c in ("UID", "BidUID", "Name") if c != column]
                conn = _db(f"CREATE TABLE BidConditionFolders ({', '.join(remaining)})")
                reader = _SqliteBidReader(conn)
                with self.assertRaisesRegex(
                    RuntimeError, f"Missing BidConditionFolders.{column}$"
                ):
                    reader._parse_bid_condition_folders_for_bid(
                        _SqliteConnectionWrapper(conn), "1", reader._schema_ref
                    )

    def test_area_reader_requires_uid_and_bid_columns(self):
        for dropped, remaining in (("UID", "BidUID"), ("BidUID", "UID")):
            with self.subTest(missing=dropped):
                conn = _db(f"CREATE TABLE BidAreas ({remaining} INTEGER)")
                reader = _SqliteBidReader(conn)
                with self.assertRaisesRegex(
                    RuntimeError, f"Missing BidAreas.{dropped}$"
                ):
                    reader._parse_bid_areas_for_bid(
                        _SqliteConnectionWrapper(conn), "1", reader._schema_ref
                    )


class RawBidDataReaderTests(unittest.TestCase):
    def _raw_db(self):
        conn = _db(
            "CREATE TABLE Bids (UID INTEGER, Name TEXT, Notes BLOB)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT)",
            "CREATE TABLE BidTakeoffTotals (UID INTEGER, BidUID INTEGER, Total REAL)",
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)",
            "CREATE TABLE BidLegends (UID INTEGER, BidPageUID INTEGER)",
            "CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)",
        )
        _insert(
            conn,
            "Bids",
            ("UID", "Name", "Notes"),
            [(1, "First", b"hello\x00"), (2, "Second", None)],
        )
        _insert(
            conn,
            "BidPages",
            ("UID", "BidUID", "Name"),
            [(10, 1, "Page"), (20, 2, "Foreign page")],
        )
        _insert(
            conn,
            "BidTakeoffTotals",
            ("UID", "BidUID", "Total"),
            [(1, 1, 12.5), (2, 2, 3.0)],
        )
        _insert(
            conn,
            "BidTakeoffs",
            ("UID", "BidUID", "BidPageUID"),
            [(30, 1, 10), (31, 2, 20)],
        )
        _insert(conn, "BidLegends", ("UID", "BidPageUID"), [(40, 10), (41, 20)])
        _insert(conn, "CdnTypes", ("UID", "Name"), [(3, "Concrete"), (4, "Steel")])
        return conn

    def test_raw_bid_data_collects_the_bid_page_and_global_sections(self):
        raw = _SqliteBidReader(self._raw_db()).get_raw_bid_data("x.mdb", "1")
        self.assertEqual(raw.bid_row, {"Name": "First", "Notes": "hello", "UID": "1"})
        self.assertEqual(
            raw.bid_tables["BidPages"],
            [{"BidUID": "1", "Name": "Page", "UID": "10"}],
        )
        self.assertEqual(
            raw.bid_tables["BidTakeoffTotals"],
            [{"BidUID": "1", "Total": "12.5", "UID": "1"}],
        )
        self.assertEqual(
            raw.page_tables["BidTakeoffs"],
            [{"BidPageUID": "10", "BidUID": "1", "UID": "30"}],
        )
        self.assertEqual(
            raw.page_tables["BidLegends"], [{"BidPageUID": "10", "UID": "40"}]
        )
        self.assertEqual(
            raw.global_tables["CdnTypes"],
            [
                {"Name": "Concrete", "UID": "3"},
                {"Name": "Steel", "UID": "4"},
            ],
        )

    def test_raw_bid_data_has_an_entry_for_every_contract_table(self):
        raw = _SqliteBidReader(self._raw_db()).get_raw_bid_data("x.mdb", "1")
        self.assertEqual(
            set(raw.bid_tables), set(RAW_BID_TABLES) | {"BidTakeoffTotals"}
        )
        self.assertEqual(set(raw.page_tables), set(PAGE_SECTIONS))
        self.assertEqual(set(raw.global_tables), set(RAW_GLOBAL_TABLES))
        built = {"Bids", "BidPages", "BidTakeoffTotals", "BidTakeoffs", "CdnTypes"}
        for table, rows in raw.bid_tables.items():
            if table not in built:
                self.assertEqual(rows, [], table)
        self.assertEqual(raw.global_tables["Employees"], [])
        self.assertEqual(raw.global_tables["JobStatuses"], [])

    def test_raw_bid_data_for_an_unknown_bid_is_empty_not_an_error(self):
        raw = _SqliteBidReader(self._raw_db()).get_raw_bid_data("x.mdb", "99")
        self.assertEqual(raw.bid_row, {})
        self.assertEqual(raw.bid_tables["BidPages"], [])
        self.assertEqual(raw.page_tables["BidLegends"], [])

    def test_single_row_reader_returns_the_first_row_or_nothing(self):
        conn = self._raw_db()
        reader = _SqliteBidReader(conn)
        wrapper = _SqliteConnectionWrapper(conn)
        self.assertEqual(
            reader._select_all_single(wrapper, "Bids", "UID", "2"),
            {"Name": "Second", "Notes": "NULL", "UID": "2"},
        )
        self.assertEqual(reader._select_all_single(wrapper, "Bids", "UID", "9"), {})
        self.assertEqual(reader._select_all_single(wrapper, "Absent", "UID", "1"), {})
        self.assertEqual(reader._select_all_single(wrapper, "Bids", "Nope", "1"), {})

    def test_filtered_reader_needs_the_table_and_the_key_column(self):
        conn = self._raw_db()
        reader = _SqliteBidReader(conn)
        wrapper = _SqliteConnectionWrapper(conn)
        self.assertEqual(
            [
                r["UID"]
                for r in reader._select_all_filtered(wrapper, "BidPages", "BidUID", "1")
            ],
            ["10"],
        )
        self.assertEqual(
            reader._select_all_filtered(wrapper, "Absent", "BidUID", "1"), []
        )
        self.assertEqual(
            reader._select_all_filtered(wrapper, "Bids", "BidUID", "1"), []
        )

    def test_unfiltered_reader_returns_every_row_or_nothing_for_a_missing_table(self):
        conn = self._raw_db()
        reader = _SqliteBidReader(conn)
        wrapper = _SqliteConnectionWrapper(conn)
        self.assertEqual(
            [r["UID"] for r in reader._select_all_unfiltered(wrapper, "BidPages")],
            ["10", "20"],
        )
        self.assertEqual(reader._select_all_unfiltered(wrapper, "Absent"), [])

    def test_unfiltered_reader_orders_rows_by_uid_regardless_of_insertion_order(self):
        conn = _db("CREATE TABLE Statuses (UID INTEGER, Name TEXT, Sequence INTEGER)")
        _insert(
            conn,
            "Statuses",
            ("UID", "Name", "Sequence"),
            [(30, "c", 1), (20, "b", None), (10, "a", 0)],
        )
        reader = _SqliteBidReader(conn)
        wrapper = _SqliteConnectionWrapper(conn)
        self.assertEqual(
            [r["UID"] for r in reader._select_all_unfiltered(wrapper, "Statuses")],
            ["10", "20", "30"],
        )

    def test_unfiltered_reader_issues_a_plain_uid_ordered_select(self):
        conn = _db("CREATE TABLE Statuses (UID INTEGER, Name TEXT)")
        reader = _SqliteBidReader(conn)
        statements = []
        conn.set_trace_callback(statements.append)
        reader._select_all_unfiltered(_SqliteConnectionWrapper(conn), "Statuses")
        selects = [s for s in statements if s.startswith("SELECT [Name], [UID]")]
        self.assertEqual(
            selects, ["SELECT [Name], [UID] FROM [Statuses] ORDER BY [UID]"]
        )

    def test_unfiltered_reader_adds_no_ordering_to_a_table_without_a_uid_column(self):
        conn = _db("CREATE TABLE Plain (Name TEXT)")
        _insert(conn, "Plain", ("Name",), [("b",), ("a",)])
        reader = _SqliteBidReader(conn)
        statements = []
        conn.set_trace_callback(statements.append)
        rows = reader._select_all_unfiltered(_SqliteConnectionWrapper(conn), "Plain")
        self.assertEqual([r["Name"] for r in rows], ["b", "a"])
        self.assertEqual(
            [s for s in statements if s.startswith("SELECT [Name]")],
            ["SELECT [Name] FROM [Plain]"],
        )

    def test_raw_readers_swallow_read_errors_unless_the_policy_records_them(self):
        conn = self._raw_db()
        schema = _SqliteSchema(conn)
        failing = _FailingTableConnection(conn, ("Bids", "BidPages", "CdnTypes"))
        tolerant = _SqliteFullReader(conn)
        calls = (
            (lambda r: r._select_all_single(failing, "Bids", "UID", "1"), {}),
            (lambda r: r._select_all_filtered(failing, "BidPages", "BidUID", "1"), []),
            (lambda r: r._select_all_unfiltered(failing, "CdnTypes"), []),
            (
                lambda r: r._select_all_by_bid_or_page(
                    failing, "BidPages", "1", ["10"]
                ),
                [],
            ),
        )
        del schema
        for index, (call, expected) in enumerate(calls):
            with self.subTest(call=index):
                self.assertEqual(call(tolerant), expected)
                with self.assertRaises(pyodbc.Error):
                    call(_SqliteFullReader(conn, strict=True))

    def test_filtered_rows_keep_every_row_not_only_the_first(self):
        conn = _db("CREATE TABLE T (UID INTEGER, BidUID INTEGER)")
        _insert(conn, "T", ("UID", "BidUID"), [(1, 5), (2, 5), (3, 6)])
        reader = _SqliteBidReader(conn)
        self.assertEqual(
            [
                r["UID"]
                for r in reader._select_all_filtered(
                    _SqliteConnectionWrapper(conn), "T", "BidUID", "5"
                )
            ],
            ["1", "2"],
        )
        self.assertEqual(
            [
                r["UID"]
                for r in reader._select_all_by_bid_or_page(
                    _SqliteConnectionWrapper(conn), "T", "5", []
                )
            ],
            ["1", "2"],
        )


class PagesWithTakeoffsTests(unittest.TestCase):
    def _takeoff_db(self):
        conn = _db(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)"
        )
        _insert(
            conn,
            "BidTakeoffs",
            ("UID", "BidUID", "BidPageUID"),
            [(1, 7, 10), (2, 7, 10), (3, 7, 11), (4, 7, None), (5, 8, 12)],
        )
        return conn

    def test_pages_with_takeoffs_are_distinct_ids_of_this_bid_without_nulls(self):
        reader = _SqliteBidReader(self._takeoff_db())
        self.assertEqual(reader.get_pages_with_takeoffs("x.mdb", "7"), {"10", "11"})
        self.assertEqual(reader.get_pages_with_takeoffs("x.mdb", "8"), {"12"})
        self.assertEqual(reader.get_pages_with_takeoffs("x.mdb", "9"), set())

    def test_a_file_without_a_takeoff_table_has_no_pages_with_takeoffs(self):
        reader = _SqliteBidReader(_db("CREATE TABLE Bids (UID INTEGER)"))
        self.assertEqual(reader.get_pages_with_takeoffs("x.mdb", "7"), set())

    def test_the_takeoff_table_must_carry_its_owner_columns(self):
        for dropped, remaining in (("BidUID", "BidPageUID"), ("BidPageUID", "BidUID")):
            with self.subTest(missing=dropped):
                reader = _SqliteBidReader(
                    _db(f"CREATE TABLE BidTakeoffs (UID INTEGER, {remaining} INTEGER)")
                )
                with self.assertRaisesRegex(
                    RuntimeError, f"Missing BidTakeoffs.{dropped}$"
                ):
                    reader.get_pages_with_takeoffs("x.mdb", "7")

    def test_a_failed_takeoff_read_is_swallowed_unless_the_policy_records_it(self):
        conn = self._takeoff_db()
        self.assertEqual(
            _SqliteFullReader(
                conn, fail_tables=("BidTakeoffs",)
            ).get_pages_with_takeoffs("x.mdb", "7"),
            set(),
        )
        with self.assertRaises(pyodbc.Error):
            _SqliteFullReader(
                conn, strict=True, fail_tables=("BidTakeoffs",)
            ).get_pages_with_takeoffs("x.mdb", "7")


class DeleteContentScanTests(unittest.TestCase):
    def test_every_confirmation_table_marks_its_page_and_legends_do_not(self):
        for table in PAGE_DELETE_CONFIRMATION_TABLES:
            with self.subTest(table=table):
                conn = _db(
                    "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
                    f"CREATE TABLE {table} (UID INTEGER, BidPageUID INTEGER)",
                )
                _insert(conn, "BidPages", ("UID", "BidUID"), [(1, 7), (2, 7)])
                _insert(conn, table, ("UID", "BidPageUID"), [(50, 2)])
                self.assertEqual(
                    _SqliteBidReader(conn).get_pages_with_delete_content("x.mdb", "7"),
                    {"2"},
                )
        self.assertNotIn("BidLegends", PAGE_DELETE_CONFIRMATION_TABLES)

    def test_tables_without_a_page_column_are_skipped_without_error(self):
        conn = _db(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "CREATE TABLE BidTakeoffs (UID INTEGER)",
            "CREATE TABLE BidTexts (UID INTEGER, BidPageUID INTEGER)",
        )
        _insert(conn, "BidPages", ("UID", "BidUID"), [(1, 7)])
        _insert(conn, "BidTexts", ("UID", "BidPageUID"), [(2, 1)])
        with self.assertNoLogs("test.bid_reader", "WARNING"):
            self.assertEqual(
                _SqliteBidReader(conn).get_pages_with_delete_content("x.mdb", "7"),
                {"1"},
            )

    def test_a_bid_without_pages_scans_no_content_tables(self):
        conn = _db(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "CREATE TABLE BidTexts (UID INTEGER, BidPageUID INTEGER)",
        )
        _insert(conn, "BidPages", ("UID", "BidUID"), [(1, 8)])
        _insert(conn, "BidTexts", ("UID", "BidPageUID"), [(2, 1)])
        reader = _SqliteBidReader(conn)
        self.assertEqual(reader.get_pages_with_delete_content("x.mdb", "7"), set())

    def test_a_file_without_pages_has_no_delete_content(self):
        reader = _SqliteBidReader(_db("CREATE TABLE Bids (UID INTEGER)"))
        self.assertEqual(reader.get_pages_with_delete_content("x.mdb", "7"), set())

    def test_the_page_table_must_carry_uid_and_bid_columns(self):
        for dropped, remaining in (("UID", "BidUID"), ("BidUID", "UID")):
            with self.subTest(missing=dropped):
                reader = _SqliteBidReader(
                    _db(f"CREATE TABLE BidPages ({remaining} INTEGER)")
                )
                with self.assertLogs("test.bid_reader", "WARNING") as logs:
                    self.assertIsNone(
                        reader.get_pages_with_delete_content("x.mdb", "7")
                    )
                self.assertIn(f"Missing BidPages.{dropped}", logs.output[0])


class BidLayerReaderTests(unittest.TestCase):
    def test_bid_layers_map_uid_name_and_visibility_for_this_bid_only(self):
        conn = _db(
            "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT, Show INTEGER)"
        )
        _insert(
            conn,
            "BidLayers",
            ("UID", "BidUID", "Name", "Show"),
            [
                (1, 7, "On -1", -1),
                (2, 7, "On 1", 1),
                (3, 7, "Off 0", 0),
                (4, 7, "Off 2", 2),
                (5, 7, "Unset", None),
                (6, 7, None, -1),
                (9, 8, "Foreign", -1),
            ],
        )
        layers = _SqliteBidReader(conn)._parse_bid_layers_for_bid(
            _SqliteConnectionWrapper(conn), "7"
        )
        self.assertEqual(list(layers), ["1", "2", "3", "4", "5", "6"])
        self.assertEqual(
            [(l.uid, l.name, l.visible) for l in layers.values()],
            [
                ("1", "On -1", True),
                ("2", "On 1", True),
                ("3", "Off 0", False),
                ("4", "Off 2", False),
                ("5", "Unset", False),
                ("6", "", True),
            ],
        )

    def test_a_layer_table_without_a_show_column_shows_every_layer(self):
        conn = _db("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT)")
        _insert(conn, "BidLayers", ("UID", "BidUID", "Name"), [(1, 7, "A")])
        layers = _SqliteBidReader(conn)._parse_bid_layers_for_bid(
            _SqliteConnectionWrapper(conn), "7"
        )
        self.assertTrue(layers["1"].visible)

    def test_a_file_without_layers_has_none(self):
        conn = _db("CREATE TABLE Bids (UID INTEGER)")
        self.assertEqual(
            _SqliteBidReader(conn)._parse_bid_layers_for_bid(
                _SqliteConnectionWrapper(conn), "7"
            ),
            {},
        )

    def test_layer_readers_need_their_identity_columns(self):
        for column in ("UID", "BidUID", "Name"):
            with self.subTest(missing=column):
                remaining = [c for c in ("UID", "BidUID", "Name") if c != column]
                conn = _db(f"CREATE TABLE BidLayers ({', '.join(remaining)})")
                reader = _SqliteBidReader(conn)
                with self.assertRaisesRegex(
                    RuntimeError, f"Missing BidLayers.{column}$"
                ):
                    reader._parse_bid_layers_for_bid(
                        _SqliteConnectionWrapper(conn), "7"
                    )
                with self.assertRaisesRegex(
                    RuntimeError, f"Missing BidLayers.{column}$"
                ):
                    reader._parse_bid_layers_for_sidebar(
                        _SqliteConnectionWrapper(conn), "7"
                    )
                if column != "BidUID":
                    with self.assertRaisesRegex(
                        RuntimeError, f"Missing BidLayers.{column}$"
                    ):
                        reader._parse_default_layers(_SqliteConnectionWrapper(conn))

    def _layer_db(self):
        conn = _db(
            "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "Show INTEGER, Sequence INTEGER, IsTemplate INTEGER, IsLocked INTEGER)"
        )
        _insert(
            conn,
            "BidLayers",
            ("UID", "BidUID", "Name", "Show", "Sequence", "IsTemplate", "IsLocked"),
            [
                (1, 7, "Bid layer", -1, 2, 0, 0),
                (2, 7, "Locked bid layer", 0, 1, 0, -1),
                (3, 8, "Foreign layer", -1, 1, 0, 0),
                (30, None, "Shared B", 1, 6, -1, -1),
                (31, None, "Shared A", 0, 5, -1, -1),
                (32, None, "Template not locked", -1, 4, -1, 0),
                (33, 7, "Template owned", -1, 3, -1, 0),
            ],
        )
        return conn

    def test_sidebar_layers_are_the_bids_layers_plus_locked_templates(self):
        conn = self._layer_db()
        layers = _SqliteBidReader(conn).get_bid_layers_for_sidebar("x.mdb", "7")
        self.assertEqual(
            sorted(
                (
                    l.uid,
                    l.bid_uid,
                    l.name,
                    l.show,
                    l.sequence,
                    l.is_template,
                    l.is_locked,
                )
                for l in layers
            ),
            [
                ("1", "7", "Bid layer", True, 2, False, False),
                ("2", "7", "Locked bid layer", False, 1, False, True),
                ("30", "", "Shared B", True, 6, True, True),
                ("31", "", "Shared A", False, 5, True, True),
                ("33", "7", "Template owned", True, 3, True, False),
            ],
        )

    def test_sidebar_layers_without_template_columns_are_only_the_bids_layers(self):
        conn = _db(
            "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT, IsTemplate INTEGER)"
        )
        _insert(
            conn,
            "BidLayers",
            ("UID", "BidUID", "Name", "IsTemplate"),
            [(1, 7, "Bid", 0), (30, None, "Shared", -1)],
        )
        layers = _SqliteBidReader(conn).get_bid_layers_for_sidebar("x.mdb", "7")
        self.assertEqual(
            [(l.uid, l.show, l.sequence, l.is_locked) for l in layers],
            [("1", True, 0, False)],
        )

    def test_sidebar_of_a_file_without_layers_is_empty(self):
        reader = _SqliteBidReader(_db("CREATE TABLE Bids (UID INTEGER)"))
        self.assertEqual(reader.get_bid_layers_for_sidebar("x.mdb", "7"), [])

    def test_sidebar_rejects_duplicate_layer_uids(self):
        conn = _db("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT)")
        _insert(
            conn, "BidLayers", ("UID", "BidUID", "Name"), [(1, 7, "A"), (1, 7, "B")]
        )
        with self.assertRaisesRegex(RuntimeError, "BidLayers contains duplicate UID 1"):
            _SqliteBidReader(conn).get_bid_layers_for_sidebar("x.mdb", "7")

    def test_default_layers_are_the_template_layers_in_sequence_order(self):
        layers = _SqliteBidReader(self._layer_db()).get_default_layers("x.mdb")
        self.assertEqual(
            [
                (
                    l.uid,
                    l.bid_uid,
                    l.name,
                    l.show,
                    l.sequence,
                    l.is_template,
                    l.is_locked,
                )
                for l in layers
            ],
            [
                ("33", "7", "Template owned", True, 3, True, False),
                ("32", "", "Template not locked", True, 4, True, False),
                ("31", "", "Shared A", False, 5, True, True),
                ("30", "", "Shared B", True, 6, True, True),
            ],
        )

    def test_default_layers_without_a_sequence_column_are_ordered_by_uid(self):
        conn = _db(
            "CREATE TABLE BidLayers (UID INTEGER, Name TEXT, IsTemplate INTEGER)"
        )
        _insert(
            conn,
            "BidLayers",
            ("UID", "Name", "IsTemplate"),
            [(9, "B", -1), (8, "A", -1), (7, "Bid", 0)],
        )
        layers = _SqliteBidReader(conn).get_default_layers("x.mdb")
        self.assertEqual(
            [
                (l.uid, l.name, l.bid_uid, l.show, l.sequence, l.is_locked)
                for l in layers
            ],
            [("8", "A", "", True, 0, False), ("9", "B", "", True, 0, False)],
        )

    def test_a_layer_table_without_templates_has_no_default_layers(self):
        conn = _db("CREATE TABLE BidLayers (UID INTEGER, Name TEXT)")
        _insert(conn, "BidLayers", ("UID", "Name"), [(1, "A")])
        self.assertEqual(_SqliteBidReader(conn).get_default_layers("x.mdb"), [])
        self.assertEqual(
            _SqliteBidReader(_db("CREATE TABLE Bids (UID INTEGER)")).get_default_layers(
                "x.mdb"
            ),
            [],
        )

    def test_default_layers_reject_duplicate_template_uids(self):
        conn = _db(
            "CREATE TABLE BidLayers (UID INTEGER, Name TEXT, IsTemplate INTEGER)"
        )
        _insert(
            conn,
            "BidLayers",
            ("UID", "Name", "IsTemplate"),
            [(1, "A", -1), (1, "B", -1)],
        )
        with self.assertRaisesRegex(RuntimeError, "BidLayers contains duplicate UID 1"):
            _SqliteBidReader(conn).get_default_layers("x.mdb")

    def test_layer_row_flags_treat_only_zero_and_null_as_false(self):
        Row = namedtuple("Row", "UID BidUID Name Show Sequence IsTemplate IsLocked")
        layer = BidDataReaderMixin._bid_layer_from_row(
            Row(5, 0, None, 2, None, 1, None)
        )
        self.assertEqual(
            (
                layer.uid,
                layer.bid_uid,
                layer.name,
                layer.show,
                layer.sequence,
                layer.is_template,
                layer.is_locked,
            ),
            ("5", "", "", False, 0, True, False),
        )
        layer = BidDataReaderMixin._bid_layer_from_row(Row(6, 7, b"Walls", 1, 3, 0, 2))
        self.assertEqual(
            (
                layer.bid_uid,
                layer.name,
                layer.show,
                layer.sequence,
                layer.is_template,
                layer.is_locked,
            ),
            ("7", "Walls", True, 3, False, True),
        )
        self.assertTrue(
            BidDataReaderMixin._bid_layer_from_row(Row(7, 1, "n", -1, 0, -1, -1)).show
        )


class BidPageReaderTests(unittest.TestCase):
    _COLUMNS = (
        "UID INTEGER, BidUID INTEGER, Name TEXT, BidPageFolderUID INTEGER, SheetNo TEXT, "
        "Sequence INTEGER, ImagePath TEXT, Width REAL, Height REAL, ScaleFactor1 REAL, "
        "ScaleFactor2 REAL, Rotation INTEGER, FlipX INTEGER, FlipY INTEGER, Index1 INTEGER, "
        "Show INTEGER, OverlayImagePath TEXT, OverlayOffsetX REAL, OverlayOffsetY REAL, "
        "OverlayRotation REAL, OverlayRect TEXT, OverlayResized INTEGER, "
        "DeskewRotationOverlay REAL, ZoomFac REAL, CurrentX REAL, CurrentY REAL, "
        "Invert INTEGER, Bitonal INTEGER"
    )

    def _read(self, conn, bid_layers=None):
        reader = _SqliteBidReader(conn)
        return reader._parse_bid_pages_for_bid(
            _SqliteConnectionWrapper(conn), "1", bid_layers or {}, reader._schema_ref
        )

    def test_every_page_column_is_mapped_from_its_own_field(self):
        conn = _db(f"CREATE TABLE BidPages ({self._COLUMNS})")
        conn.execute(
            "INSERT INTO BidPages VALUES (7, 1, 'Plan A', 11, 'A-101', 4, 'a.png', "
            "42.0, 30.0, 0.25, 0.5, 450, -1, 1, 3, 2, 'o.png', 1.5, 2.5, 3.5, "
            "'1,2,3,4', -1, 0.75, 1.25, 10.5, 20.5, -1, 1)"
        )
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (8, 2)")
        pages = self._read(conn)
        self.assertEqual(list(pages), ["7"])
        page = pages["7"]
        self.assertEqual(
            (
                page.name,
                page.folder_uid,
                page.sheet_no,
                page.sequence,
                page.image_path,
                page.width_pts,
                page.height_pts,
                page.scale_factor1,
                page.scale_factor2,
                page.rotation,
                page.flip_x,
                page.flip_y,
                page.page_index,
                page.image_show_mode,
            ),
            (
                "Plan A",
                "11",
                "A-101",
                4,
                "a.png",
                42.0 * 72.0,
                30.0 * 72.0,
                0.25,
                0.5,
                90,
                True,
                True,
                2,
                2,
            ),
        )
        self.assertEqual(
            (
                page.overlay_image_path,
                page.overlay_offset_x,
                page.overlay_offset_y,
                page.overlay_rotation,
                page.overlay_resized,
                page.deskew_rotation_overlay,
                page.zoom_fac,
                page.current_x,
                page.current_y,
                page.invert,
                page.bitonal,
            ),
            ("o.png", 1.5, 2.5, 3.5, True, 0.75, 1.25, 10.5, 20.5, True, True),
        )
        self.assertEqual(page.overlay_rect, (1.0, 2.0, 3.0, 4.0))

    def test_a_page_with_only_identity_columns_reads_with_documented_defaults(self):
        conn = _db("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        _insert(conn, "BidPages", ("UID", "BidUID"), [(7, 1)])
        page = self._read(conn)["7"]
        self.assertEqual(
            (
                page.name,
                page.folder_uid,
                page.sheet_no,
                page.sequence,
                page.image_path,
                page.width_pts,
                page.height_pts,
                page.scale_factor1,
                page.scale_factor2,
                page.rotation,
                page.flip_x,
                page.flip_y,
                page.page_index,
                page.image_show_mode,
                page.overlay_image_path,
                page.overlay_offset_x,
                page.overlay_offset_y,
                page.overlay_rotation,
                page.overlay_resized,
                page.deskew_rotation_overlay,
                page.zoom_fac,
                page.current_x,
                page.current_y,
                page.invert,
                page.bitonal,
                page.overlay_rect,
            ),
            (
                "",
                None,
                "",
                0,
                None,
                0.0,
                0.0,
                1.0,
                1.0,
                0,
                False,
                False,
                0,
                0,
                None,
                0.0,
                0.0,
                0.0,
                False,
                0.0,
                0.0,
                0.0,
                0.0,
                False,
                False,
                EMPTY_OVERLAY_RECT,
            ),
        )

    def test_null_and_zero_page_values_fall_back_to_the_same_defaults(self):
        conn = _db(f"CREATE TABLE BidPages ({self._COLUMNS})")
        conn.execute(
            "INSERT INTO BidPages (UID, BidUID, Sequence, Rotation, Index1, Show, "
            "FlipX, FlipY, Invert, Bitonal, OverlayResized, BidPageFolderUID, "
            "ImagePath, OverlayImagePath) "
            "VALUES (7, 1, NULL, NULL, 0, NULL, 0, 0, 0, 0, 0, 0, '', '')"
        )
        page = self._read(conn)["7"]
        self.assertEqual(
            (
                page.sequence,
                page.rotation,
                page.page_index,
                page.image_show_mode,
                page.flip_x,
                page.flip_y,
                page.invert,
                page.bitonal,
                page.overlay_resized,
                page.folder_uid,
                page.image_path,
                page.overlay_image_path,
            ),
            (0, 0, 0, 0, False, False, False, False, False, None, None, None),
        )

    def test_rotation_wraps_and_page_index_is_zero_based_and_never_negative(self):
        conn = _db(f"CREATE TABLE BidPages ({self._COLUMNS})")
        _insert(
            conn,
            "BidPages",
            ("UID", "BidUID", "Rotation", "Index1"),
            [(1, 1, 360, 1), (2, 1, 359, 2), (3, 1, 725, 10), (4, 1, 0, -4)],
        )
        pages = self._read(conn)
        self.assertEqual(
            [(p.rotation, p.page_index) for p in pages.values()],
            [(0, 0), (359, 1), (5, 9), (0, 0)],
        )

    def test_flip_flags_accept_only_minus_one_and_true(self):
        conn = _db(f"CREATE TABLE BidPages ({self._COLUMNS})")
        _insert(
            conn,
            "BidPages",
            ("UID", "BidUID", "FlipX", "FlipY", "OverlayResized", "Invert", "Bitonal"),
            [(1, 1, -1, 0, -1, -1, -1), (2, 1, 1, 2, 1, 1, 1), (3, 1, 0, -1, 0, 0, 0)],
        )
        pages = self._read(conn)
        self.assertEqual(
            [
                (p.flip_x, p.flip_y, p.overlay_resized, p.invert, p.bitonal)
                for p in pages.values()
            ],
            [
                (True, False, True, True, True),
                (True, False, True, True, True),
                (False, True, False, False, False),
            ],
        )

    def test_pages_are_ordered_by_sequence_then_name_then_uid(self):
        conn = _db(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT, Sequence INTEGER)"
        )
        _insert(
            conn,
            "BidPages",
            ("UID", "BidUID", "Name", "Sequence"),
            [
                (5, 1, "A", 2),
                (4, 1, "B", 2),
                (3, 1, "B", 2),
                (2, 1, "Z", 1),
                (1, 2, "Foreign", 0),
            ],
        )
        self.assertEqual(list(self._read(conn)), ["2", "5", "3", "4"])

    def test_pages_without_ordering_columns_are_ordered_by_uid(self):
        conn = _db("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        _insert(conn, "BidPages", ("UID", "BidUID"), [(9, 1), (8, 1)])
        self.assertEqual(list(self._read(conn)), ["8", "9"])

    def test_the_image_layer_visibility_applies_to_every_page(self):
        conn = _db("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        _insert(conn, "BidPages", ("UID", "BidUID"), [(1, 1)])
        hidden = {"4": Layer(uid="4", name="Image", visible=False)}
        shown = {"4": Layer(uid="4", name="IMAGE ", visible=True)}
        other = {"4": Layer(uid="4", name="Walls", visible=False)}
        self.assertFalse(self._read(conn, hidden)["1"].layer_visible)
        self.assertTrue(self._read(conn, shown)["1"].layer_visible)
        self.assertTrue(self._read(conn, other)["1"].layer_visible)
        self.assertTrue(self._read(conn)["1"].layer_visible)

    def test_a_page_folder_reference_of_zero_or_null_means_no_folder(self):
        conn = _db(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, BidPageFolderUID INTEGER)"
        )
        _insert(
            conn,
            "BidPages",
            ("UID", "BidUID", "BidPageFolderUID"),
            [(1, 1, 0), (2, 1, None), (3, 1, 12)],
        )
        self.assertEqual(
            [p.folder_uid for p in self._read(conn).values()], [None, None, "12"]
        )


class BidConditionReaderTests(unittest.TestCase):
    _FULL = (
        "UID INTEGER, BidUID INTEGER, Name TEXT, Type INTEGER, Thickness REAL, "
        "Height REAL, Width REAL, Depth REAL, Rise REAL, Run REAL, Shape INTEGER, "
        "ColorFill INTEGER, CdnTypeUID INTEGER, Pattern INTEGER, Spacing REAL, "
        "BidLayerUID INTEGER, UOM1 INTEGER, UOM2 INTEGER, UOM3 INTEGER, "
        "Quantity1 INTEGER, Quantity2 INTEGER, Quantity3 INTEGER, RefNo INTEGER, "
        "DisplaySize REAL, DropRun INTEGER, DropValue REAL, BidConditionFolderUID INTEGER, "
        "Notes BLOB, RoundQuantity INTEGER, RoundUp REAL, Trim INTEGER, "
        "IsCurvedSegment INTEGER, Grid INTEGER, GridSize1 REAL, GridSize2 REAL, "
        "Gap REAL, DisplayDimension INTEGER, DisplayName INTEGER, "
        "DisplayGridWhileDrawing INTEGER"
    )

    def _read(self, conn, bid_layers=None, cdn_types=None):
        reader = _SqliteBidReader(conn)
        return reader._parse_bid_conditions_for_bid(
            _SqliteConnectionWrapper(conn),
            "1",
            bid_layers or {},
            cdn_types or {},
            reader._schema_ref,
        )

    def test_every_condition_column_is_mapped_from_its_own_field(self):
        conn = _db(f"CREATE TABLE BidConditions ({self._FULL})")
        conn.execute(
            "INSERT INTO BidConditions VALUES (7, 1, 'Slab @T 9'' 6\"', 4, 0.5, 1.5, 2.5, "
            "3.5, 4.5, 5.5, 6, 7, 3, 8, 9.5, 5, ?, ?, ?, ?, ?, ?, 12, 150.0, 1, "
            "6.5, 11, ?, -1, 0.25, -1, -1, -1, 1.5, 2.5, 3.5, -1, -1, -1)",
            (
                UOM_LINEAR_FEET,
                UOM_SQUARE_FEET,
                UOM_CUBIC_FEET,
                CALC_LINEAR_LENGTH,
                CALC_LINEAR_BOTH_SIDES,
                CALC_VOLUME,
                b"memo",
            ),
        )
        condition = self._read(
            conn,
            {"5": Layer(uid="5", name="Walls", visible=False)},
            {"3": CdnType(uid="3", name="Concrete")},
        )["7"]
        self.assertEqual(
            (
                condition.condition_type,
                condition.thickness,
                condition.height,
                condition.width,
                condition.depth,
                condition.rise,
                condition.run,
                condition.shape,
                condition.color_fill,
                condition.pattern,
                condition.spacing,
            ),
            (4, 0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6, 7, 8, 9.5),
        )
        self.assertEqual(
            (
                condition.cdn_type_uid,
                condition.cdn_type_name,
                condition.layer_uid,
                condition.layer_visible,
                condition.folder_uid,
                condition.uom1,
                condition.uom2,
                condition.uom3,
                condition.calc_type1,
                condition.calc_type2,
                condition.calc_type3,
                condition.ref_no,
                condition.display_size,
                condition.drop_run,
                condition.drop_value,
                condition.notes,
            ),
            (
                "3",
                "Concrete",
                "5",
                False,
                "11",
                UOM_LINEAR_FEET,
                UOM_SQUARE_FEET,
                UOM_CUBIC_FEET,
                CALC_LINEAR_LENGTH,
                CALC_LINEAR_BOTH_SIDES,
                CALC_VOLUME,
                12,
                150.0,
                True,
                6.5,
                "memo",
            ),
        )
        self.assertEqual(
            (
                condition.round_quantity,
                condition.round_up,
                condition.trim,
                condition.is_curved_segment,
                condition.grid,
                condition.grid_size1,
                condition.grid_size2,
                condition.gap,
                condition.display_dimension,
                condition.display_name,
                condition.display_grid_while_drawing,
            ),
            (True, 0.25, True, True, True, 1.5, 2.5, 3.5, True, True, True),
        )
        self.assertEqual((condition.z_value, condition.is_top), (114.0, True))

    def test_a_condition_with_an_unreadable_elevation_is_reported_and_the_rest_still_load(
        self,
    ):
        conn = _db(f"CREATE TABLE BidConditions ({self._FULL})")
        _insert(
            conn,
            "BidConditions",
            ("UID", "BidUID", "Name"),
            [
                (6, 1, "Before @T 9' 6\""),
                (7, 1, 'Broken @B 1/0"'),
                (8, 1, 'After @B 6 1/0"'),
                (9, 1, "Last @T 8' 0\""),
            ],
        )
        with self.assertLogs("test.bid_reader", level="WARNING") as logged:
            conditions = self._read(conn)
        self.assertEqual(sorted(conditions), ["6", "7", "8", "9"])
        self.assertEqual(
            [
                (conditions[uid].z_value, conditions[uid].is_top)
                for uid in ("6", "7", "8", "9")
            ],
            [(114.0, True), (0.0, False), (0.0, False), (96.0, True)],
        )
        self.assertEqual(conditions["7"].name, 'Broken @B 1/0"')
        messages = [record.getMessage() for record in logged.records]
        self.assertEqual(len(messages), 2)
        self.assertIn("7", messages[0])
        self.assertIn('Broken @B 1/0"', messages[0])
        self.assertIn("8", messages[1])

    def test_stored_units_are_kept_when_no_calculation_is_selected(self):
        conn = _db(f"CREATE TABLE BidConditions ({self._FULL})")
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, Name, UOM1, UOM2, UOM3, "
            "Quantity1, Quantity2, Quantity3) VALUES (7, 1, 'Units', ?, ?, ?, 0, 0, 0)",
            (UOM_INCHES, UOM_SQUARE_INCHES, UOM_CUBIC_YARDS),
        )
        condition = self._read(conn)["7"]
        self.assertEqual(
            (condition.uom1, condition.uom2, condition.uom3),
            (UOM_INCHES, UOM_SQUARE_INCHES, UOM_CUBIC_YARDS),
        )

    def test_null_condition_columns_read_as_neutral_defaults(self):
        conn = _db(f"CREATE TABLE BidConditions ({self._FULL})")
        _insert(conn, "BidConditions", ("UID", "BidUID", "Name"), [(7, 1, "Bare")])
        condition = self._read(conn)["7"]
        self.assertEqual(
            (
                condition.condition_type,
                condition.thickness,
                condition.height,
                condition.width,
                condition.depth,
                condition.rise,
                condition.run,
                condition.shape,
                condition.color_fill,
                condition.pattern,
                condition.spacing,
                condition.cdn_type_uid,
                condition.cdn_type_name,
                condition.layer_uid,
                condition.layer_visible,
                condition.folder_uid,
                condition.uom1,
                condition.uom2,
                condition.uom3,
                condition.calc_type1,
                condition.calc_type2,
                condition.calc_type3,
                condition.ref_no,
                condition.display_size,
                condition.drop_run,
                condition.drop_value,
                condition.notes,
                condition.round_quantity,
                condition.round_up,
                condition.trim,
                condition.is_curved_segment,
                condition.grid,
                condition.grid_size1,
                condition.grid_size2,
                condition.gap,
                condition.display_dimension,
                condition.display_name,
                condition.display_grid_while_drawing,
            ),
            (
                0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0,
                0,
                0,
                0.0,
                None,
                "Unknown",
                None,
                True,
                None,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                100.0,
                False,
                0.0,
                "",
                False,
                0.0,
                False,
                False,
                False,
                0.0,
                0.0,
                0.0,
                False,
                False,
                False,
            ),
        )

    def test_a_condition_table_with_only_core_columns_uses_sql_defaults(self):
        conn = _db(
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, Type INTEGER)"
        )
        _insert(
            conn,
            "BidConditions",
            ("UID", "BidUID", "Name", "Type"),
            [(7, 1, "Core", 3)],
        )
        condition = self._read(conn)["7"]
        self.assertEqual(
            (
                condition.condition_type,
                condition.thickness,
                condition.shape,
                condition.cdn_type_uid,
                condition.layer_uid,
                condition.folder_uid,
                condition.display_size,
                condition.round_quantity,
                condition.trim,
                condition.is_curved_segment,
                condition.grid,
                condition.display_name,
                condition.display_grid_while_drawing,
                condition.notes,
            ),
            (
                3,
                0.0,
                0,
                None,
                None,
                None,
                100.0,
                False,
                False,
                False,
                False,
                False,
                False,
                "",
            ),
        )

    def test_every_zero_valued_flag_column_reads_false_and_nonzero_reads_true(self):
        flags = (
            "RoundQuantity",
            "Trim",
            "IsCurvedSegment",
            "Grid",
            "DisplayDimension",
            "DisplayName",
            "DisplayGridWhileDrawing",
        )
        conn = _db(f"CREATE TABLE BidConditions ({self._FULL})")
        _insert(
            conn,
            "BidConditions",
            ("UID", "BidUID", "Name"),
            [(1, 1, "off"), (2, 1, "on")],
        )
        for flag in flags:
            conn.execute(f"UPDATE BidConditions SET {flag} = 0 WHERE UID = 1")
            conn.execute(f"UPDATE BidConditions SET {flag} = -1 WHERE UID = 2")
        conditions = self._read(conn)
        attributes = (
            "round_quantity",
            "trim",
            "is_curved_segment",
            "grid",
            "display_dimension",
            "display_name",
            "display_grid_while_drawing",
        )
        for attribute in attributes:
            with self.subTest(attribute=attribute):
                self.assertIs(getattr(conditions["1"], attribute), False)
                self.assertIs(getattr(conditions["2"], attribute), True)

    def test_measure_base_one_normalizes_the_unit_system_to_metric(self):
        for measure_base, expected in (
            (1, UOM_M),
            (0, UOM_LINEAR_FEET),
            (None, UOM_LINEAR_FEET),
        ):
            with self.subTest(measure_base=measure_base):
                conn = _db(
                    "CREATE TABLE Bids (UID INTEGER, MeasureBase INTEGER)",
                    "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, "
                    "Type INTEGER, UOM1 INTEGER, Quantity1 INTEGER)",
                )
                _insert(conn, "Bids", ("UID", "MeasureBase"), [(1, measure_base)])
                _insert(
                    conn,
                    "BidConditions",
                    ("UID", "BidUID", "Name", "Type", "UOM1", "Quantity1"),
                    [(7, 1, "Wall", 2, UOM_LINEAR_FEET, CALC_LINEAR_LENGTH)],
                )
                self.assertEqual(self._read(conn)["7"].uom1, expected)

    def test_a_missing_bid_row_reads_as_imperial(self):
        conn = _db(
            "CREATE TABLE Bids (UID INTEGER, MeasureBase INTEGER)",
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "Type INTEGER, UOM1 INTEGER, Quantity1 INTEGER)",
        )
        _insert(conn, "Bids", ("UID", "MeasureBase"), [(2, 1)])
        _insert(
            conn,
            "BidConditions",
            ("UID", "BidUID", "Name", "Type", "UOM1", "Quantity1"),
            [(7, 1, "Wall", 2, UOM_LINEAR_FEET, CALC_LINEAR_LENGTH)],
        )
        self.assertEqual(self._read(conn)["7"].uom1, UOM_LINEAR_FEET)

    def test_conditions_of_other_bids_and_unknown_layers_are_handled(self):
        conn = _db(
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "Type INTEGER, BidLayerUID INTEGER, CdnTypeUID INTEGER)"
        )
        _insert(
            conn,
            "BidConditions",
            ("UID", "BidUID", "Name", "Type", "BidLayerUID", "CdnTypeUID"),
            [(7, 1, "Mine", 1, 99, 98), (8, 2, "Foreign", 1, None, None)],
        )
        conditions = self._read(conn, {"5": Layer(uid="5", name="X", visible=False)})
        self.assertEqual(list(conditions), ["7"])
        self.assertEqual(
            (
                conditions["7"].layer_uid,
                conditions["7"].layer_visible,
                conditions["7"].cdn_type_uid,
                conditions["7"].cdn_type_name,
            ),
            ("99", True, "98", "Unknown"),
        )


class BidTakeoffReaderTests(unittest.TestCase):
    _COLUMNS = (
        "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, BidPageUID INTEGER, "
        "BidAreaUID INTEGER, Position BLOB, Rotation REAL, Curve INTEGER, "
        "ParentUID INTEGER, IsNegativeQuantity INTEGER, FontName TEXT, FontColor INTEGER, "
        "FontSize INTEGER, FontBold INTEGER, FontItalic INTEGER, FontUnderline INTEGER, "
        "NameFontName TEXT, NameFontColor INTEGER, NameFontSize INTEGER, "
        "NameFontBold INTEGER, NameFontItalic INTEGER, NameFontUnderline INTEGER, Tag TEXT"
    )

    def _read(self, conn):
        reader = _SqliteBidReader(conn)
        return reader._parse_bid_takeoffs_for_bid(
            _SqliteConnectionWrapper(conn), "1", reader._schema_ref
        )

    def test_every_takeoff_column_is_mapped_from_its_own_field(self):
        conn = _db(f"CREATE TABLE BidTakeoffs ({self._COLUMNS})")
        conn.execute(
            "INSERT INTO BidTakeoffs VALUES (4, 1, 10, 20, 30, ?, 15.5, 2, 3, -1, 'Arial', "
            "255, -72, 1, 0, 1, 'Calibri', 128, -48, 0, 1, 0, 'extra')",
            (b"1;2;3;4\n",),
        )
        conn.execute(
            "INSERT INTO BidTakeoffs (UID, BidUID, BidConditionUID, BidPageUID, Position) "
            "VALUES (5, 2, 10, 20, ?)",
            (b"1;2;3;4\n",),
        )
        conn.execute(
            "INSERT INTO BidTakeoffs (UID, BidUID, BidConditionUID, BidPageUID, ParentUID, Position) "
            "VALUES (3, 1, 10, 20, NULL, ?)",
            (b"9;8;7;6\n",),
        )
        takeoffs, extras = self._read(conn)
        by_uid = {t.uid: t for t in takeoffs}
        self.assertEqual(sorted(by_uid), ["3", "4"])
        takeoff = by_uid["4"]
        self.assertEqual(
            (
                takeoff.condition_uid,
                takeoff.page_uid,
                takeoff.area_uid,
                takeoff.position,
                takeoff.rotation,
                takeoff.curve,
                takeoff.parent_uid,
                takeoff.is_negative,
            ),
            ("10", "20", "30", [1.0, 2.0, 3.0, 4.0], 15.5, 2, "3", True),
        )
        self.assertEqual(
            (
                takeoff.dimension_font_name,
                takeoff.dimension_font_color,
                takeoff.dimension_font_size,
                takeoff.dimension_font_bold,
                takeoff.dimension_font_italic,
                takeoff.dimension_font_underline,
            ),
            ("Arial", 255, 72, True, False, True),
        )
        self.assertEqual(
            (
                takeoff.name_font_name,
                takeoff.name_font_color,
                takeoff.name_font_size,
                takeoff.name_font_bold,
                takeoff.name_font_italic,
                takeoff.name_font_underline,
            ),
            ("Calibri", 128, 48, False, True, False),
        )
        self.assertEqual(extras["4"]["Tag"], "extra")
        for typed in (
            "UID",
            "BidUID",
            "BidConditionUID",
            "BidPageUID",
            "BidAreaUID",
            "Position",
            "Rotation",
            "Curve",
            "ParentUID",
            "IsNegativeQuantity",
        ):
            self.assertNotIn(typed, extras["4"])
        self.assertEqual(sorted(extras), ["3", "4"])
        sparse = by_uid["3"]
        self.assertEqual(
            (
                sparse.area_uid,
                sparse.rotation,
                sparse.curve,
                sparse.parent_uid,
                sparse.is_negative,
                sparse.dimension_font_name,
                sparse.dimension_font_color,
                sparse.dimension_font_size,
                sparse.dimension_font_bold,
                sparse.name_font_name,
                sparse.name_font_color,
                sparse.name_font_size,
                sparse.name_font_bold,
                sparse.name_font_italic,
                sparse.name_font_underline,
                sparse.dimension_font_italic,
                sparse.dimension_font_underline,
            ),
            (
                "0",
                0.0,
                -1,
                "0",
                False,
                None,
                None,
                None,
                False,
                None,
                None,
                None,
                False,
                False,
                False,
                False,
                False,
            ),
        )

    def test_each_font_flag_is_read_from_its_own_column(self):
        conn = _db(f"CREATE TABLE BidTakeoffs ({self._COLUMNS})")
        flags = (
            "FontBold",
            "FontItalic",
            "FontUnderline",
            "NameFontBold",
            "NameFontItalic",
            "NameFontUnderline",
        )
        for index, flag in enumerate(flags):
            conn.execute(
                "INSERT INTO BidTakeoffs (UID, BidUID, BidConditionUID, BidPageUID, "
                f"Position, {flag}) VALUES (?, 1, 10, 20, ?, 1)",
                (index + 1, b"1;2;3;4\n"),
            )
        takeoffs, _extras = self._read(conn)
        attributes = (
            "dimension_font_bold",
            "dimension_font_italic",
            "dimension_font_underline",
            "name_font_bold",
            "name_font_italic",
            "name_font_underline",
        )
        for takeoff, own in zip(takeoffs, attributes):
            with self.subTest(attribute=own):
                self.assertEqual(
                    {a for a in attributes if getattr(takeoff, a) is True}, {own}
                )

    def test_zero_font_sizes_and_colors_distinguish_unset_from_black(self):
        conn = _db(f"CREATE TABLE BidTakeoffs ({self._COLUMNS})")
        conn.execute(
            "INSERT INTO BidTakeoffs (UID, BidUID, BidConditionUID, BidPageUID, Position, "
            "FontColor, FontSize, NameFontColor, NameFontSize, FontName, NameFontName) "
            "VALUES (4, 1, 10, 20, ?, 0, 0, 0, 0, '', '')",
            (b"1;2;3;4\n",),
        )
        (takeoff,), _extras = self._read(conn)
        self.assertEqual(
            (
                takeoff.dimension_font_name,
                takeoff.dimension_font_color,
                takeoff.dimension_font_size,
                takeoff.name_font_name,
                takeoff.name_font_color,
                takeoff.name_font_size,
            ),
            (None, 0, None, None, 0, None),
        )

    def test_a_takeoff_table_without_optional_columns_uses_documented_defaults(self):
        conn = _db(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
            "BidPageUID INTEGER, Position BLOB)"
        )
        _insert(
            conn,
            "BidTakeoffs",
            ("UID", "BidUID", "BidConditionUID", "BidPageUID", "Position"),
            [(4, 1, 10, 20, b"1;2;3;4\n")],
        )
        (takeoff,), extras = self._read(conn)
        self.assertEqual(
            (
                takeoff.area_uid,
                takeoff.rotation,
                takeoff.curve,
                takeoff.parent_uid,
                takeoff.is_negative,
            ),
            ("0", 0.0, -1, "0", False),
        )
        self.assertEqual(extras, {"4": {}})
        self.assertEqual(
            (
                takeoff.dimension_font_name,
                takeoff.dimension_font_color,
                takeoff.dimension_font_size,
                takeoff.dimension_font_bold,
                takeoff.dimension_font_italic,
                takeoff.dimension_font_underline,
                takeoff.name_font_name,
                takeoff.name_font_color,
                takeoff.name_font_size,
                takeoff.name_font_bold,
                takeoff.name_font_italic,
                takeoff.name_font_underline,
            ),
            (
                None,
                None,
                None,
                False,
                False,
                False,
                None,
                None,
                None,
                False,
                False,
                False,
            ),
        )

    def test_a_failed_takeoff_read_is_always_raised_after_the_policy_is_told(self):
        conn = _db(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
            "BidPageUID INTEGER, Position BLOB)"
        )
        failing = _FailingTableConnection(conn, ("BidTakeoffs",))
        reader = _SqliteFullReader(conn)
        with self.assertRaises(pyodbc.Error):
            reader._parse_bid_takeoffs_for_bid(failing, "1", _SqliteSchema(conn))


class SelectedPageSchemaTests(unittest.TestCase):
    def test_a_bid_settings_table_without_a_bid_column_is_a_schema_error(self):
        conn = _db("CREATE TABLE BidSettings (UID INTEGER, BidPageSelectedUID INTEGER)")
        reader = _SqliteBidReader(conn)
        with self.assertRaisesRegex(RuntimeError, "Missing BidSettings.BidUID$"):
            reader._parse_bid_selected_page(_SqliteConnectionWrapper(conn), "1")

    def test_a_pyodbc_error_while_reading_is_raised_when_the_policy_records_it(self):
        conn = _db(
            "CREATE TABLE BidSettings (UID INTEGER, BidUID INTEGER, BidPageSelectedUID INTEGER)"
        )
        failing = _FailingTableConnection(conn, ("BidSettings",))
        with self.assertRaises(pyodbc.Error):
            _SqliteFullReader(conn, strict=True)._parse_bid_selected_page(failing, "1")
        with self.assertLogs("test.full_reader", "WARNING") as logs:
            self.assertIsNone(
                _SqliteFullReader(conn)._parse_bid_selected_page(failing, "1")
            )
        self.assertTrue(logs.records[0].exc_info)
        self.assertIs(logs.records[0].exc_info[0], pyodbc.Error)


class BidLoadAssemblyTests(unittest.TestCase):
    """get_bid_data over a real sqlite database through the full MdbReader."""

    def _bid_db(self):
        conn = _db(
            "CREATE TABLE Bids (UID INTEGER, MeasureBase INTEGER)",
            "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT, Show INTEGER)",
            "CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT, Sequence INTEGER)",
            "CREATE TABLE BidPageSettings (UID INTEGER, BidPageUID INTEGER, "
            "BidAreaUID INTEGER, BidAreaSelected INTEGER)",
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, Name TEXT)",
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "Type INTEGER, CdnTypeUID INTEGER)",
            "CREATE TABLE BidConditionFolders (UID INTEGER, BidUID INTEGER, Name TEXT)",
            "CREATE TABLE BidSettings (UID INTEGER, BidUID INTEGER, BidPageSelectedUID INTEGER)",
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
            "BidPageUID INTEGER, ParentUID INTEGER, Position BLOB)",
        )
        _insert(conn, "Bids", ("UID", "MeasureBase"), [(1, 0), (2, 0)])
        _insert(
            conn, "BidLayers", ("UID", "BidUID", "Name", "Show"), [(5, 1, "Image", 0)]
        )
        _insert(conn, "CdnTypes", ("UID", "Name"), [(3, "Concrete")])
        _insert(
            conn,
            "BidPages",
            ("UID", "BidUID", "Name", "Sequence"),
            [(10, 1, "Second", 2), (11, 1, "First", 1), (20, 2, "Foreign", 1)],
        )
        _insert(
            conn,
            "BidPageSettings",
            ("UID", "BidPageUID", "BidAreaUID", "BidAreaSelected"),
            [(1, 10, 40, 1)],
        )
        _insert(conn, "BidAreas", ("UID", "BidUID", "Name"), [(40, 1, "Area")])
        _insert(
            conn,
            "BidConditions",
            ("UID", "BidUID", "Name", "Type", "CdnTypeUID"),
            [(30, 1, "Wall", 2, 3)],
        )
        _insert(
            conn, "BidConditionFolders", ("UID", "BidUID", "Name"), [(50, 1, "Folder")]
        )
        _insert(
            conn, "BidSettings", ("UID", "BidUID", "BidPageSelectedUID"), [(1, 1, 11)]
        )
        _insert(
            conn,
            "BidTakeoffs",
            ("UID", "BidUID", "BidConditionUID", "BidPageUID", "ParentUID", "Position"),
            [
                (60, 1, 30, 10, None, b"1;2;3;4\n"),
                (61, 1, 30, 10, 60, b"1;2;3;4\n"),
                (62, 2, 30, 20, None, b"1;2;3;4\n"),
            ],
        )
        return conn

    def test_a_bid_load_assembles_every_section_for_that_bid(self):
        reader = _SqliteFullReader(self._bid_db())
        (
            conditions,
            takeoffs,
            areas,
            pages,
            area_selections,
            cdn_types,
            annotations,
            folders,
            selected_page,
            extras,
            cover_sheet,
            delete_content,
        ) = reader.get_bid_data("x.mdb", "1")
        self.assertEqual(list(conditions), ["30"])
        self.assertEqual(conditions["30"].cdn_type_name, "Concrete")
        self.assertEqual([t.uid for t in takeoffs], ["60", "61"])
        self.assertEqual(list(areas), ["40"])
        self.assertEqual(list(pages), ["11", "10"])
        self.assertEqual(area_selections, {"11": None, "10": "40"})
        self.assertEqual(list(cdn_types), ["3"])
        self.assertEqual(annotations, [])
        self.assertEqual(list(folders), ["50"])
        self.assertEqual(selected_page, "11")
        self.assertEqual(sorted(extras), ["60", "61"])
        self.assertIsNone(cover_sheet)
        self.assertIsNone(delete_content)

    def test_the_image_layer_hides_the_bids_pages(self):
        reader = _SqliteFullReader(self._bid_db())
        pages = reader.get_bid_data("x.mdb", "1")[3]
        self.assertEqual([p.layer_visible for p in pages.values()], [False, False])

    def test_navigation_snapshots_are_hydrated_only_when_the_reader_asks(self):
        class _Hydrating(_SqliteFullReader):
            def _hydrates_bid_navigation_snapshots(self):
                return True

            def _parse_cover_sheet_data(self, _connection, bid_uid):
                return ("cover", bid_uid)

        result = _Hydrating(self._bid_db()).get_bid_data("x.mdb", "1")
        self.assertEqual(result[10], ("cover", "1"))
        self.assertEqual(result[11], frozenset({"10"}))
        self.assertIsInstance(result[11], frozenset)

    def test_a_bid_load_refuses_to_start_without_each_required_column(self):
        required = (
            ("BidPages", "UID"),
            ("BidPages", "BidUID"),
            ("BidTakeoffs", "UID"),
            ("BidTakeoffs", "BidUID"),
            ("BidTakeoffs", "BidConditionUID"),
            ("BidTakeoffs", "BidPageUID"),
            ("BidTakeoffs", "Position"),
            ("BidConditions", "UID"),
            ("BidConditions", "BidUID"),
            ("BidConditions", "Name"),
            ("BidConditions", "Type"),
        )
        for table, column in required:
            with self.subTest(table=table, column=column):
                conn = self._bid_db()
                conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
                reader = _SqliteFullReader(conn)
                with self.assertRaisesRegex(RuntimeError, f"Missing {table}.{column}$"):
                    reader.get_bid_data("x.mdb", "1")

    def test_a_takeoff_hole_must_point_at_an_existing_takeoff(self):
        conn = self._bid_db()
        conn.execute("UPDATE BidTakeoffs SET ParentUID = 99 WHERE UID = 61")
        with self.assertRaisesRegex(
            RuntimeError, "BidTakeoffs.UID=61 references missing BidTakeoffs.UID=99"
        ):
            _SqliteFullReader(conn).get_bid_data("x.mdb", "1")

    def test_takeoffs_may_not_reference_conditions_or_pages_of_another_bid(self):
        conn = self._bid_db()
        conn.execute("UPDATE BidTakeoffs SET BidConditionUID = 31 WHERE UID = 60")
        with self.assertRaisesRegex(
            RuntimeError, "BidTakeoffs.UID=60 references missing BidConditions.UID=31"
        ):
            _SqliteFullReader(conn).get_bid_data("x.mdb", "1")
        conn = self._bid_db()
        conn.execute("UPDATE BidTakeoffs SET BidPageUID = 20 WHERE UID = 60")
        with self.assertRaisesRegex(
            RuntimeError, "BidTakeoffs.UID=60 references missing BidPages.UID=20"
        ):
            _SqliteFullReader(conn).get_bid_data("x.mdb", "1")

    def test_a_cyclic_hole_chain_reports_its_smallest_uid(self):
        conn = self._bid_db()
        conn.execute("UPDATE BidTakeoffs SET ParentUID = 61 WHERE UID = 60")
        with self.assertRaisesRegex(
            RuntimeError, "BidTakeoffs.UID=60 participates in a ParentUID cycle"
        ):
            _SqliteFullReader(conn).get_bid_data("x.mdb", "1")


class _OptionalColumnRecordingSchema(_SqliteSchema):
    """Records which optional columns a reader asked the schema about."""

    def __init__(self, connection):
        super().__init__(connection)
        self.optional_calls = []

    def optional_column(self, table_name, column_name, default_sql):
        self.optional_calls.append((table_name, column_name, default_sql))
        return super().optional_column(table_name, column_name, default_sql)


class _QueryRecordingCursor(_SqliteCursorWrapper):
    def __init__(self, connection, queries):
        super().__init__(connection)
        self._queries = queries

    def execute(self, query, *params):
        self._queries.append(" ".join(query.split()))
        return super().execute(query, *params)


class _QueryRecordingConnection(_SqliteConnectionWrapper):
    def __init__(self, connection, queries):
        super().__init__(connection)
        self._queries = queries

    def cursor(self):
        return _QueryRecordingCursor(self._connection, self._queries)


class _PolicyRecordingReader(_SqliteBidReader):
    def __init__(self, connection):
        super().__init__(connection)
        self.recorded = []

    def _record_caught_read_error(self, exc, _file_path=None):
        self.recorded.append(exc)
        return False


class ReaderSchemaInteractionTests(unittest.TestCase):
    def test_a_missing_selected_page_column_is_reported_to_the_schema_once(self):
        conn = _db("CREATE TABLE BidSettings (UID INTEGER, BidUID INTEGER)")
        reader = _SqliteBidReader(conn)
        reader._schema_ref = _OptionalColumnRecordingSchema(conn)
        self.assertIsNone(
            reader._parse_bid_selected_page(_SqliteConnectionWrapper(conn), "1")
        )
        self.assertEqual(
            reader._schema_ref.optional_calls,
            [("BidSettings", "BidPageSelectedUID", "NULL")],
        )

    def test_a_present_selected_page_column_is_not_reported_as_missing(self):
        conn = _db(
            "CREATE TABLE BidSettings (UID INTEGER, BidUID INTEGER, BidPageSelectedUID INTEGER)"
        )
        reader = _SqliteBidReader(conn)
        reader._schema_ref = _OptionalColumnRecordingSchema(conn)
        reader._parse_bid_selected_page(_SqliteConnectionWrapper(conn), "1")
        self.assertEqual(reader._schema_ref.optional_calls, [])

    def test_missing_optional_takeoff_columns_are_each_reported_with_their_default(
        self,
    ):
        conn = _db(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
            "BidPageUID INTEGER, Position BLOB)"
        )
        reader = _SqliteBidReader(conn)
        reader._schema_ref = _OptionalColumnRecordingSchema(conn)
        reader._parse_bid_takeoffs_for_bid(
            _SqliteConnectionWrapper(conn), "1", reader._schema_ref
        )
        self.assertEqual(
            reader._schema_ref.optional_calls,
            [
                ("BidTakeoffs", "BidAreaUID", "0"),
                ("BidTakeoffs", "Rotation", "0"),
                ("BidTakeoffs", "Curve", "-1"),
                ("BidTakeoffs", "ParentUID", "0"),
                ("BidTakeoffs", "IsNegativeQuantity", "0"),
            ],
        )

    def test_present_optional_takeoff_columns_are_not_reported(self):
        conn = _db(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
            "BidPageUID INTEGER, Position BLOB, BidAreaUID INTEGER, Rotation REAL, "
            "Curve INTEGER, ParentUID INTEGER, IsNegativeQuantity INTEGER)"
        )
        reader = _SqliteBidReader(conn)
        reader._schema_ref = _OptionalColumnRecordingSchema(conn)
        reader._parse_bid_takeoffs_for_bid(
            _SqliteConnectionWrapper(conn), "1", reader._schema_ref
        )
        self.assertEqual(reader._schema_ref.optional_calls, [])

    def test_a_failed_takeoff_read_is_reported_to_the_read_policy_before_raising(self):
        conn = _db(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
            "BidPageUID INTEGER, Position BLOB)"
        )
        reader = _PolicyRecordingReader(conn)
        failing = _FailingTableConnection(conn, ("BidTakeoffs",))
        with self.assertRaises(pyodbc.Error) as raised:
            reader._parse_bid_takeoffs_for_bid(failing, "1", reader._schema_ref)
        self.assertEqual(reader.recorded, [raised.exception])

    def test_the_sidebar_template_clause_needs_both_template_columns(self):
        for columns, expect_clause in (
            ("IsTemplate INTEGER", False),
            ("IsLocked INTEGER", False),
            ("IsTemplate INTEGER, IsLocked INTEGER", True),
            ("", False),
        ):
            with self.subTest(columns=columns):
                extra = f", {columns}" if columns else ""
                conn = _db(
                    f"CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT{extra})"
                )
                queries = []
                reader = _SqliteBidReader(conn)
                reader._parse_bid_layers_for_sidebar(
                    _QueryRecordingConnection(conn, queries), "7"
                )
                (query,) = queries
                self.assertEqual(
                    " OR ([IsTemplate] <> 0 AND [IsLocked] <> 0)" in query,
                    expect_clause,
                )


class ReaderNullAndCoercionTests(unittest.TestCase):
    """Access hands back NULLs and (for some drivers) numeric text; the reader must type them."""

    def test_a_text_none_parent_reads_as_a_root_that_is_never_reference_checked(self):
        conn = _db(
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, ParentUID TEXT)"
        )
        _insert(conn, "BidAreas", ("UID", "BidUID", "ParentUID"), [(5, 1, "None")])
        reader = _SqliteBidReader(conn)
        areas = reader._parse_bid_areas_for_bid(
            _SqliteConnectionWrapper(conn), "1", reader._schema_ref
        )
        self.assertEqual(list(areas), ["5"])
        self.assertEqual(areas["5"].parent_uid, "None")

    def test_null_real_page_columns_read_with_their_documented_defaults(self):
        conn = _db(f"CREATE TABLE BidPages ({BidPageReaderTests._COLUMNS})")
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (7, 1)")
        reader = _SqliteBidReader(conn)
        page = reader._parse_bid_pages_for_bid(
            _SqliteConnectionWrapper(conn), "1", {}, reader._schema_ref
        )["7"]
        floats = (
            page.width_pts,
            page.height_pts,
            page.scale_factor1,
            page.scale_factor2,
            page.overlay_offset_x,
            page.overlay_offset_y,
            page.overlay_rotation,
            page.deskew_rotation_overlay,
            page.zoom_fac,
            page.current_x,
            page.current_y,
        )
        self.assertEqual(
            floats, (0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        )
        for value in floats:
            self.assertIsInstance(value, float)

    def test_a_null_template_marker_reads_false_like_a_null_lock_marker(self):
        Row = namedtuple("Row", "UID BidUID Name Show Sequence IsTemplate IsLocked")
        layer = BidDataReaderMixin._bid_layer_from_row(Row(5, 0, "x", 1, 1, None, None))
        self.assertIs(layer.is_template, False)
        self.assertIs(layer.is_locked, False)

    def test_page_reader_numeric_text_is_typed_by_the_reader(self):
        conn = _db(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Sequence, Rotation, Index1, Show)"
        )
        conn.execute("INSERT INTO BidPages VALUES (7, 1, '3', '450', '4', '2')")
        reader = _SqliteBidReader(conn)
        page = reader._parse_bid_pages_for_bid(
            _SqliteConnectionWrapper(conn), "1", {}, reader._schema_ref
        )["7"]
        self.assertEqual(
            (page.sequence, page.rotation, page.page_index, page.image_show_mode),
            (3, 90, 3, 2),
        )
        for value in (
            page.sequence,
            page.rotation,
            page.page_index,
            page.image_show_mode,
        ):
            self.assertIsInstance(value, int)

    def test_condition_reader_numeric_text_is_typed_by_the_reader(self):
        conn = _db(
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, Type, "
            "Thickness, Height, Width, Depth, Rise, Run, Shape, ColorFill, Pattern, Spacing, "
            "UOM1, UOM2, UOM3, Quantity1, Quantity2, Quantity3, RefNo, DropRun, DropValue, "
            "RoundUp, GridSize1, GridSize2, Gap)"
        )
        conn.execute(
            "INSERT INTO BidConditions VALUES (1, 1, 'C', '2', '1.5', '2.5', '3.5', '4.5', "
            "'5.5', '6.5', '3', '7', '8', '9.5', '1', '4', '9', '0', '0', '0', '12', '0', "
            "'6.25', '0.25', '1.25', '2.25', '3.25')"
        )
        reader = _SqliteBidReader(conn)
        cond = reader._parse_bid_conditions_for_bid(
            _SqliteConnectionWrapper(conn), "1", {}, {}, reader._schema_ref
        )["1"]
        ints = (
            cond.condition_type,
            cond.shape,
            cond.color_fill,
            cond.pattern,
            cond.uom1,
            cond.uom2,
            cond.uom3,
            cond.calc_type1,
            cond.calc_type2,
            cond.calc_type3,
            cond.ref_no,
        )
        self.assertEqual(ints, (2, 3, 7, 8, 1, 4, 9, 0, 0, 0, 12))
        for value in ints:
            self.assertIsInstance(value, int)
        floats = (
            cond.thickness,
            cond.height,
            cond.width,
            cond.depth,
            cond.rise,
            cond.run,
            cond.spacing,
            cond.drop_value,
            cond.round_up,
            cond.grid_size1,
            cond.grid_size2,
            cond.gap,
        )
        self.assertEqual(
            floats, (1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 9.5, 6.25, 0.25, 1.25, 2.25, 3.25)
        )
        for value in floats:
            self.assertIsInstance(value, float)
        self.assertIs(cond.drop_run, False)

    def test_takeoff_reader_numeric_text_is_typed_by_the_reader(self):
        conn = _db(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
            "BidPageUID INTEGER, Position BLOB, Rotation, Curve, FontColor, FontSize, "
            "NameFontColor, NameFontSize)"
        )
        conn.execute(
            "INSERT INTO BidTakeoffs VALUES (4, 1, 10, 20, ?, '15.5', '2', '255', '-72', '128', '-48')",
            (b"1;2;3;4\n",),
        )
        reader = _SqliteBidReader(conn)
        (takeoff,), _extras = reader._parse_bid_takeoffs_for_bid(
            _SqliteConnectionWrapper(conn), "1", reader._schema_ref
        )
        self.assertEqual(
            (
                takeoff.rotation,
                takeoff.curve,
                takeoff.dimension_font_color,
                takeoff.dimension_font_size,
                takeoff.name_font_color,
                takeoff.name_font_size,
            ),
            (15.5, 2, 255, 72, 128, 48),
        )
        self.assertIsInstance(takeoff.rotation, float)
        for value in (
            takeoff.curve,
            takeoff.dimension_font_color,
            takeoff.dimension_font_size,
            takeoff.name_font_color,
            takeoff.name_font_size,
        ):
            self.assertIsInstance(value, int)

    def test_read_failures_report_the_error_and_the_file_to_the_policy_in_that_order(
        self,
    ):
        class Recording(_SqliteFullReader):
            def __init__(self, connection, **kwargs):
                super().__init__(connection, **kwargs)
                self.calls = []

            def _record_caught_read_error(self, exc, file_path=None):
                self.calls.append((type(exc).__name__, file_path))
                return False

        conn = _db(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
        )
        reader = Recording(conn, fail_tables=("BidTakeoffs",))
        reader.get_pages_with_takeoffs("the.mdb", "1")
        self.assertEqual(reader.calls, [("Error", "the.mdb")])
        reader = Recording(conn, fail_tables=("BidPages",))
        self.assertIsNone(reader.get_pages_with_delete_content("the.mdb", "1"))
        self.assertEqual(reader.calls, [("Error", "the.mdb")])

    def test_the_area_family_is_a_list_of_areas(self):
        conn = _db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, Name TEXT)",
            "INSERT INTO BidAreas VALUES (7, 1, 'A')",
        )
        areas = _SqliteFullReader(conn).get_area_family("x.mdb", "1")
        self.assertIsInstance(areas, list)
        self.assertEqual([a.name for a in areas], ["A"])


class ReaderTextValueTests(unittest.TestCase):
    def test_area_and_layer_sequences_reported_as_text_are_integers(self):
        conn = _db(
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, Sequence)",
            "INSERT INTO BidAreas VALUES (5, 1, '7')",
        )
        reader = _SqliteBidReader(conn)
        areas = reader._parse_bid_areas_for_bid(
            _SqliteConnectionWrapper(conn), "1", reader._schema_ref
        )
        self.assertEqual(areas["5"].sequence, 7)
        self.assertIsInstance(areas["5"].sequence, int)
        Row = namedtuple("Row", "UID BidUID Name Show Sequence IsTemplate IsLocked")
        layer = BidDataReaderMixin._bid_layer_from_row(Row(5, 1, "x", 1, "3", 0, 0))
        self.assertEqual(layer.sequence, 3)
        self.assertIsInstance(layer.sequence, int)

    def test_a_count_reported_as_text_is_returned_as_an_integer(self):
        class Cursor:
            @staticmethod
            def execute(_sql):
                pass

            @staticmethod
            def fetchone():
                return ("3",)

        class Schema:
            @staticmethod
            def optional_table_missing(_table):
                return False

        count = BidDataReaderMixin()._count_table(Cursor(), Schema(), "Bids")
        self.assertEqual(count, 3)
        self.assertIsInstance(count, int)

    def test_a_measure_base_reported_as_text_selects_the_metric_system(self):
        for stored, expected in (
            ("1", UOM_M),
            ("0", UOM_LINEAR_FEET),
            ("2", UOM_LINEAR_FEET),
        ):
            with self.subTest(measure_base=stored):
                conn = _db(
                    "CREATE TABLE Bids (UID INTEGER, MeasureBase)",
                    "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, "
                    "Type INTEGER, UOM1 INTEGER, Quantity1 INTEGER)",
                )
                _insert(conn, "Bids", ("UID", "MeasureBase"), [(1, stored)])
                _insert(
                    conn,
                    "BidConditions",
                    ("UID", "BidUID", "Name", "Type", "UOM1", "Quantity1"),
                    [(7, 1, "Wall", 2, UOM_LINEAR_FEET, CALC_LINEAR_LENGTH)],
                )
                reader = _SqliteBidReader(conn)
                conditions = reader._parse_bid_conditions_for_bid(
                    _SqliteConnectionWrapper(conn), "1", {}, {}, reader._schema_ref
                )
                self.assertEqual(conditions["7"].uom1, expected)
