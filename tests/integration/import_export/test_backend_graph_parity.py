import tempfile
import unittest
from pathlib import Path
from ost_visualizer.infrastructure.mdb.importers.ost_importer import OstImporter
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter
from tests.helpers.mdb.import_export_support import (
    _CapturingImportWriter as _import_export_support__CapturingImportWriter,
)


class BackendGraphParityRelationshipTests(unittest.TestCase):
    def test_access_and_sql_writers_receive_same_pruned_takeoff_graph(self):
        xml = """
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
                </BidTakeoffs>
              </BidPage>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        captured_graphs = []
        with tempfile.TemporaryDirectory() as temp_dir:
            ost_path = Path(temp_dir) / "backend_neutral_graph.ost"
            ost_path.write_text(xml, encoding="utf-8")
            for writer_type in (MdbWriter, SqlProjectWriter):
                with self.subTest(writer_type=writer_type.__name__), self.assertLogs(
                    "ost_visualizer.infrastructure.mdb.importers.ost_importer",
                    level="WARNING",
                ):
                    writer = writer_type.__new__(writer_type)
                    captured = _import_export_support__CapturingImportWriter()
                    writer.import_ost_data = captured.import_ost_data
                    self.assertTrue(
                        OstImporter(writer).import_ost(
                            str(ost_path), f"{writer_type.__name__}-target"
                        )
                    )
                    captured_graphs.append(captured.takeoffs)
        self.assertEqual(captured_graphs[0], captured_graphs[1])
        self.assertEqual(
            captured_graphs[0],
            (("31", "30", "Child"), ("30", "0", "Parent")),
        )
