import logging
import sqlite3
import tempfile
import unittest
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import pyodbc
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
from tests.helpers.mdb.import_export_support import (
    _Rows as _import_export_support__Rows,
    _SqliteConnection as _import_export_support__SqliteConnection,
    _SqliteCursor as _import_export_support__SqliteCursor,
    _SqliteMdbWriter as _import_export_support__SqliteMdbWriter,
    _SqliteSchema as _import_export_support__SqliteSchema,
    _create_import_schema as _import_export_support__create_import_schema,
    _named_row as _import_export_support__named_row,
)


class MasterDataReconciliationRelationshipTests(unittest.TestCase):
    def test_access_import_rolls_back_ambiguous_master_reconciliation(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.executemany(
            "INSERT INTO JobStatuses (UID, Name, Locked, Sequence) "
            "VALUES (?, 'Open', ?, ?)",
            ((10, 0, 1), (11, 1, 2)),
        )
        connection.commit()
        writer = _import_export_support__SqliteMdbWriter(connection)
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobStatusUID="90" JobName="Imported">
            <BidAreas/>
            <BidPages/>
          </Bid>
          <JobStatuses>
            <JobStatuse UID="90" Name="Open" Locked="0" Sequence="1"/>
          </JobStatuses>
        </XML_ROOT>
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "ambiguous.ost"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertFalse(
                OstImporter(writer).import_ost(str(ost_path), "target.mdb")
            )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 0
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM JobStatuses").fetchone()[0], 2
        )
