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


class PageAreaSelectionRelationshipTests(unittest.TestCase):
    def test_import_canonicalizes_duplicate_page_area_selection_then_save_succeeds(
        self,
    ):
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidAreas>
              <BidArea UID="10" BidUID="1" Name="Area 1" Sequence="1"/>
              <BidArea UID="11" BidUID="1" Name="Area 2" Sequence="2"/>
            </BidAreas>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1">
                <BidPageSettings>
                  <BidPageSetting UID="30" BidPageUID="20"
                                  BidAreaUID="10" BidAreaSelected="1"/>
                  <BidPageSetting UID="31" BidPageUID="20"
                                  BidAreaUID="11" BidAreaSelected="2"/>
                </BidPageSettings>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(
            connection, unique_page_selected=True
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "import.ost"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(OstImporter(writer).import_ost(str(ost_path), "target.mdb"))
        page_uid = connection.execute(
            "SELECT UID FROM BidPages WHERE Name='Sheet'"
        ).fetchone()[0]
        selected_count = connection.execute(
            "SELECT COUNT(*) FROM BidPageSettings "
            "WHERE BidPageUID=? AND BidAreaSelected > 0",
            (page_uid,),
        ).fetchone()[0]
        area_uid = connection.execute(
            "SELECT UID FROM BidAreas WHERE Name='Area 2'"
        ).fetchone()[0]
        self.assertEqual(selected_count, 1)
        self.assertTrue(
            writer.save_page_area("target.mdb", str(page_uid), str(area_uid))
        )
