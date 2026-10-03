import logging
import re
import sqlite3
import tempfile
import unittest
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pyodbc
from ost_visualizer.infrastructure.database.master_data_identity import (
    AmbiguousMasterDataIdentityError,
    DuplicateMasterDataUidError,
)
from ost_visualizer.infrastructure.mdb.components.import_operations import (
    ImportOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.importers.ost_importer import OstImporter
from ost_visualizer.infrastructure.mdb.schema_compatibility import (
    UnsupportedMdbSchemaError,
)
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter
from tests.helpers.mdb.import_export_support import (
    _Rows as _import_export_support__Rows,
    _SqliteConnection as _import_export_support__SqliteConnection,
    _SqliteCursor as _import_export_support__SqliteCursor,
    _SqliteMdbWriter as _import_export_support__SqliteMdbWriter,
    _SqliteSchema as _import_export_support__SqliteSchema,
    _create_import_schema as _import_export_support__create_import_schema,
    _named_row as _import_export_support__named_row,
)

_OST_XML = """
<XML_ROOT>
  <Bid UID="1" JobStatusUID="90" JobName="Imported">
    <BidAreas/>
    <BidPages/>
  </Bid>
  <CdnTypes>
    <CdnType UID="70" Name="Brand New Type" ExpandState="0"/>
  </CdnTypes>
  <JobStatuses>
    <JobStatuse UID="90" Name="Open" Locked="0" Sequence="1"/>
  </JobStatuses>
</XML_ROOT>
"""


class MasterDataReconciliationRelationshipTests(unittest.TestCase):
    def _import(self, connection, existing_job_statuses):
        _import_export_support__create_import_schema(connection)
        connection.executemany(
            "INSERT INTO JobStatuses (UID, Name, Locked, Sequence) "
            "VALUES (?, 'Open', ?, ?)",
            existing_job_statuses,
        )
        connection.commit()
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "master.ost"
            ost_path.write_text(_OST_XML, encoding="utf-8")
            return OstImporter(writer).import_ost(str(ost_path), "target.mdb")

    def test_access_import_rolls_back_ambiguous_master_reconciliation(self):
        connection = sqlite3.connect(":memory:")
        # Two stored statuses share the imported name 'Open' (UIDs 10 and 11).
        # CdnTypes are reconciled before JobStatuses, so the new condition type
        # is already inserted when the ambiguity is detected; it must be rolled
        # back together with the (never written) Bid.
        with self.assertLogs("test", level="ERROR") as logs:
            imported = self._import(connection, ((10, 0, 1), (11, 1, 2)))
        self.assertFalse(imported)
        self.assertIn("Imported master-data identity is ambiguous", logs.output[0])
        self.assertIn("JobStatuses.Name", logs.output[0])
        self.assertIn("matching UIDs 10, 11", logs.output[0])
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM CdnTypes").fetchone()[0], 0
        )
        self.assertEqual(
            connection.execute(
                "SELECT UID, Locked, Sequence FROM JobStatuses ORDER BY UID"
            ).fetchall(),
            [(10, 0, 1), (11, 1, 2)],
        )

    def test_access_import_reuses_single_matching_master_row(self):
        # Positive control for the rollback test: the same file against a
        # database with exactly one 'Open' status commits, reuses UID 10 for the
        # Bid and still inserts the genuinely new condition type.
        connection = sqlite3.connect(":memory:")
        self.assertTrue(self._import(connection, ((10, 0, 1),)))
        self.assertEqual(
            connection.execute("SELECT UID, Name FROM JobStatuses").fetchall(),
            [(10, "Open")],
        )
        self.assertEqual(
            connection.execute("SELECT JobStatusUID, JobName FROM Bids").fetchall(),
            [(10, "Imported")],
        )
        self.assertEqual(
            connection.execute("SELECT Name FROM CdnTypes").fetchall(),
            [("Brand New Type",)],
        )


class _SqlMasterDataCursor:
    """Answers the writer's `SELECT [UID], [col] FROM [dbo].[Table]` lookups."""

    _LOOKUP = re.compile(r"^SELECT \[UID\], \[(\w+)\] FROM \[dbo\]\.\[(\w+)\]$")

    def __init__(self, existing):
        self._existing = existing
        self._rows = []

    def execute(self, sql, *_params):
        match = self._LOOKUP.match(sql)
        if match is None:
            raise AssertionError(f"unexpected SQL in master-data reconciliation: {sql}")
        self._rows = list(self._existing.get(match.group(2), ()))

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _SqlMasterDataConnection:
    def __init__(self, existing):
        self._existing = existing

    def cursor(self):
        return _SqlMasterDataCursor(self._existing)


class SqlMasterDataReconciliationTests(unittest.TestCase):
    """SQL counterpart of the Access reconciliation tests above.
    The real SqlProjectWriter reconciliation, identity-graph writer and the
    shared master-data identity helpers run against a fake SQL connection that
    serves the existing master rows; nothing here proves server behaviour.
    """

    def _import(self, existing):
        events = {"inserted": [], "rolled_back": False}
        connection = _SqlMasterDataConnection(existing)

        @contextmanager
        def sql_connection(_database_id):
            try:
                yield connection
            except BaseException:
                events["rolled_back"] = True
                raise

        def insert(_connection, table, row, _table_info):
            events["inserted"].append((table, dict(row)))
            return 200 + len(events["inserted"])

        writer = SqlProjectWriter.__new__(SqlProjectWriter)
        recorded = []
        recorder = SimpleNamespace(record=lambda *args, **kwargs: recorded.append(args))
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(writer, "_connection", sql_connection),
            patch.object(writer, "_resolve_sql_employees", return_value={}),
            patch.object(writer, "_assign_next_bid_no"),
            patch.object(
                writer,
                "_get_table_info",
                return_value=({"UID", "Name", "JobStatusUID", "JobName"}, {}),
            ),
            patch.object(writer, "_insert_identity_raw", side_effect=insert),
        ):
            ost_path = Path(temp_dir) / "master.ost"
            ost_path.write_text(_OST_XML, encoding="utf-8")
            try:
                value = OstImporter(writer).import_ost_mutation(
                    str(ost_path), "target-db", None, recorder
                )
            except Exception as exc:
                return exc, events
        return value, events

    def test_sql_import_rejects_ambiguous_master_reconciliation_before_the_bid(self):
        outcome, events = self._import({"JobStatuses": ((10, "Open"), (11, "Open"))})
        self.assertIsInstance(outcome, AmbiguousMasterDataIdentityError)
        self.assertIn("Imported master-data identity is ambiguous", str(outcome))
        self.assertIn("JobStatuses.Name", str(outcome))
        self.assertIn("matching UIDs 10, 11", str(outcome))
        # CdnTypes are reconciled first (as on Access); the error then escapes
        # the connection scope so the mutation transaction rolls everything back
        # and the Bid itself is never written.
        self.assertEqual([table for table, _row in events["inserted"]], ["CdnTypes"])
        self.assertTrue(events["rolled_back"])

    def test_sql_import_reuses_single_matching_master_row(self):
        value, events = self._import({"JobStatuses": ((10, "Open"),)})
        self.assertNotIsInstance(value, Exception)
        self.assertFalse(events["rolled_back"])
        self.assertEqual(
            [table for table, _row in events["inserted"]], ["CdnTypes", "Bids"]
        )
        bid_row = events["inserted"][1][1]
        self.assertEqual(
            (bid_row["JobStatusUID"], bid_row["JobName"]), ("10", "Imported")
        )
        self.assertEqual(value["global_uid_maps"]["job_statuses"], {"90": "10"})
        self.assertEqual(value["global_uid_maps"]["condition_types"], {"70": "201"})

    def test_sql_import_detects_duplicate_stored_master_uids(self):
        outcome, events = self._import({"JobStatuses": ((10, "Open"), ("10", "Open"))})
        self.assertIsInstance(outcome, DuplicateMasterDataUidError)
        self.assertIn("JobStatuses contains duplicate UID 10", str(outcome))
        self.assertTrue(events["rolled_back"])
        self.assertNotIn("Bids", [table for table, _row in events["inserted"]])
