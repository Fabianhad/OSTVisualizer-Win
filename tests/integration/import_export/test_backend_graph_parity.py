"""Tests for the corresponding production package."""

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.infrastructure.mdb.importers.ost_importer import OstImporter
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter
from tests.helpers.mdb.import_export_support import (
    _CapturingImportWriter as _import_export_support__CapturingImportWriter,
)

_TAKEOFF_GRAPH_XML = """
<XML_ROOT>
  <Bid UID="1" JobName="Imported">
    <BidConditions><BidCondition UID="10" BidUID="1"/></BidConditions>
    <BidPages>
      <BidPage UID="20" BidUID="1" Name="Sheet">
        <BidTakeoffs>
          <BidTakeoff UID="31" BidUID="1" BidPageUID="20"
                      BidConditionUID="10" ParentUID="30" Name="Child"/>
          <BidTakeoff UID="30" BidUID="1" BidPageUID="20"
                      BidConditionUID="10" Name="Parent"/>
          <BidTakeoff UID="32" BidUID="1" BidPageUID="20"
                      BidConditionUID="10" ParentUID="999" Name="Orphan"/>
          <BidTakeoff UID="33" BidUID="1" BidPageUID="20"
                      BidConditionUID="10" ParentUID="32" Name="Descendant"/>
          <BidTakeoff UID="34" BidUID="1" BidPageUID="20"
                      BidConditionUID="10" Name="Early"/>
          <BidTakeoff UID="35" BidUID="1" BidPageUID="20"
                      BidConditionUID="10" ParentUID="34" Name="Late"/>
        </BidTakeoffs>
      </BidPage>
    </BidPages>
  </Bid>
</XML_ROOT>
"""
_IMPORTER_LOGGER = "ost_visualizer.infrastructure.mdb.importers.ost_importer"


def _parent_names(rows):
    """Return {takeoff name: parent takeoff name or None} from (uid, parent, name)."""
    names = {uid: name for uid, _parent, name in rows}
    return {
        name: (names[parent] if parent is not None else None)
        for _uid, parent, name in rows
    }


def _import_through_access_writer(ost_path):
    """Run the real MdbWriter.import_ost_data with its Access connection stubbed.
    Only the Access database boundary (connection, master-data resolution, bid
    number allocation and the final row writer) is replaced; the writer's own
    import_ost_data, the importer's transform and the UID remapping are real.
    Returns the (UID, ParentUID, Name) tuples handed to the row writer.
    """
    written = []

    @contextmanager
    def connection(_db_path):
        yield object()

    writer = MdbWriter.__new__(MdbWriter)
    with (
        patch.object(writer, "_connection", connection),
        patch.object(writer, "_get_max_uid", return_value=100),
        patch.object(writer, "_resolve_cdn_types", return_value=({}, 100)),
        patch.object(writer, "_resolve_job_statuses", return_value=({}, 100)),
        patch.object(writer, "_resolve_access_levels", return_value={}),
        patch.object(writer, "_resolve_pay_classes", return_value={}),
        patch.object(writer, "_resolve_employees", return_value={}),
        patch.object(writer, "_assign_next_bid_no"),
        patch.object(
            writer,
            "_write_to_db",
            side_effect=lambda _conn, remapped: written.append(remapped),
        ),
    ):
        imported = OstImporter(writer).import_ost(str(ost_path), "target.mdb")
    return imported, [
        (row["UID"], row.get("ParentUID"), row["Name"])
        for remapped in written
        for row in remapped.page_tables["BidTakeoffs"]
    ]


class _SqlCursor:
    def __init__(self, deferred_updates):
        self._deferred_updates = deferred_updates

    def execute(self, query, *params):
        self._deferred_updates.append((query, params))

    def close(self):
        pass


class _SqlConnection:
    def __init__(self):
        self.deferred_updates = []

    def cursor(self):
        return _SqlCursor(self.deferred_updates)


def _import_through_sql_writer(ost_path):
    """Run the real SqlProjectWriter.import_ost_data against a recording fake.
    SQL Server is replaced by a fake connection whose identity inserts hand out
    sequential UIDs; the writer's import_ost_data and the identity-graph writer
    (deferred parent fix-ups included) are real. Returns the imported flag and
    (UID, ParentUID, Name) tuples reconstructed from the INSERTs and UPDATEs.
    """
    inserted = []
    fake_connection = _SqlConnection()
    table_columns = {"UID", "BidUID", "BidPageUID", "BidConditionUID", "ParentUID"}

    def insert(_connection, table, row, _table_info):
        inserted.append((table, dict(row)))
        return 500 + len(inserted)

    writer = SqlProjectWriter.__new__(SqlProjectWriter)
    with (
        patch.object(
            writer,
            "_connection",
            return_value=_NullContext(fake_connection),
        ),
        patch.object(writer, "_resolve_global_by_column", return_value={}),
        patch.object(writer, "_resolve_sql_employees", return_value={}),
        patch.object(writer, "_assign_next_bid_no"),
        patch.object(
            writer,
            "_get_table_info",
            side_effect=lambda _connection, table: (
                {"UID", "JobName"} if table == "Bids" else table_columns | {"Name"},
                {},
            ),
        ),
        patch.object(writer, "_insert_identity_raw", side_effect=insert),
    ):
        imported = OstImporter(writer).import_ost(str(ost_path), "target-db")
    parents = {
        params[1]: params[0]
        for query, params in fake_connection.deferred_updates
        if query == "UPDATE [dbo].[BidTakeoffs] SET [ParentUID]=? WHERE [UID]=?"
    }
    rows = []
    for position, (table, row) in enumerate(inserted, start=1):
        if table != "BidTakeoffs":
            continue
        uid = 500 + position
        rows.append((uid, row.get("ParentUID") or parents.get(uid), row["Name"]))
    return imported, rows


class _NullContext:
    def __init__(self, value):
        self._value = value

    def __enter__(self):
        return self._value

    def __exit__(self, *_exc):
        return False


class BackendGraphParityRelationshipTests(unittest.TestCase):
    def test_access_and_sql_writers_receive_same_pruned_takeoff_graph(self):
        results = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "backend_neutral_graph.ost"
            ost_path.write_text(_TAKEOFF_GRAPH_XML, encoding="utf-8")
            for label, importer in (
                ("access", _import_through_access_writer),
                ("sql", _import_through_sql_writer),
            ):
                with self.subTest(backend=label), self.assertLogs(
                    _IMPORTER_LOGGER, level="WARNING"
                ) as logs:
                    imported, rows = importer(ost_path)
                    self.assertTrue(imported)
                    results[label] = rows
                    # Orphan (missing parent 999) and its dependent Descendant
                    # are the pruned rows; both must be named in the diagnostic.
                    self.assertEqual(len(logs.records), 1)
                    message = logs.records[0].getMessage()
                    self.assertIn("Skipping 2 invalid takeoff(s)", message)
        # Access remaps UIDs from MAX(UID)+1 (=101 here: bid, condition, page,
        # then takeoffs in file order), SQL takes database-generated identities;
        # the stored parent/child relation is what must agree, per backend.
        # Child precedes its Parent in the file (forward reference, deferred on
        # SQL); Late follows its Early parent (already-remapped reference).
        expected_parents = {
            "Child": "Parent",
            "Parent": None,
            "Early": None,
            "Late": "Early",
        }
        self.assertEqual(_parent_names(results["access"]), expected_parents)
        self.assertEqual(_parent_names(results["sql"]), expected_parents)
        # Concrete identities: Access allocates MAX(UID)+1 (stubbed to 100) in
        # file order after the Bid (101), condition (102) and page (103); the
        # fake SQL identity inserts hand out 501.. in the same order.
        self.assertEqual(
            results["access"],
            [
                ("104", "105", "Child"),
                ("105", None, "Parent"),
                ("106", None, "Early"),
                ("107", "106", "Late"),
            ],
        )
        self.assertEqual(
            results["sql"],
            [
                (504, 505, "Child"),
                (505, None, "Parent"),
                (506, None, "Early"),
                (507, 506, "Late"),
            ],
        )
        self.assertEqual(
            [name for _uid, _parent, name in results["access"]],
            [name for _uid, _parent, name in results["sql"]],
        )
        self.assertEqual(
            [name for _uid, _parent, name in results["access"]],
            ["Child", "Parent", "Early", "Late"],
        )

    def test_importer_prunes_orphan_takeoff_branch_before_any_writer(self):
        # Writer-independent half of the contract: the importer itself drops the
        # missing-parent root and its descendant and hands the writer exactly
        # the surviving rows in file order, with the original source UIDs.
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "backend_neutral_graph.ost"
            ost_path.write_text(_TAKEOFF_GRAPH_XML, encoding="utf-8")
            captured = _import_export_support__CapturingImportWriter()
            with self.assertLogs(_IMPORTER_LOGGER, level="WARNING"):
                self.assertTrue(
                    OstImporter(captured).import_ost(str(ost_path), "target")
                )
        self.assertTrue(captured.called)
        self.assertEqual(
            captured.takeoffs,
            (
                ("31", "30", "Child"),
                ("30", "0", "Parent"),
                ("34", "0", "Early"),
                ("35", "34", "Late"),
            ),
        )
