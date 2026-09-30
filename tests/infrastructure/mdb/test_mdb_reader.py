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
import os
import pyodbc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.write_schema import CurrentSqlWriteSchema


class MdbReaderPersistenceTests(unittest.TestCase):
    def test_condition_type_reader_rejects_duplicate_physical_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)")
        conn.executemany(
            "INSERT INTO CdnTypes VALUES (7, ?)",
            (("First",), ("Conflicting",)),
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "CdnTypes contains duplicate UID 7",
        ):
            MdbReader._parse_cdn_types(
                _SqliteMdbOps(conn), _SqliteConnectionWrapper(conn)
            )


class MdbReaderSqlCleanupTests(unittest.TestCase):
    def test_access_shared_annotation_reader_retains_optional_table_tolerance(self):
        class _FailingCursor:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

            @staticmethod
            def execute(_sql, *_params):
                raise pyodbc.Error("42S02", "optional Access table is missing")

        class _Connection:
            @staticmethod
            def cursor():
                return _FailingCursor()

        reader = MdbReader.__new__(MdbReader)
        reader.logger = logging.getLogger("tests.access_tolerant_shared_reader")
        annotations = reader._parse_bid_annotations_for_bid(
            _Connection(),
            "1",
            [],
            CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema),
        )
        self.assertEqual(annotations, [])
