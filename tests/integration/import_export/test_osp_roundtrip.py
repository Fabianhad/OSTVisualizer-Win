import logging
import sqlite3
import tempfile
import unittest
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import create_autospec, patch
import pyodbc
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.infrastructure.mdb.components.import_operations import (
    ImportOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.exporters.ost_exporter import OstExporter
from ost_visualizer.infrastructure.mdb.importers import (
    osp_importer as osp_importer_module,
)
from ost_visualizer.infrastructure.mdb.importers.osp_importer import OspImporter
from ost_visualizer.infrastructure.mdb.importers.ost_importer import OstImporter
from ost_visualizer.infrastructure.mdb.schema_compatibility import (
    UnsupportedMdbSchemaError,
)
from ost_visualizer.presentation.visualization.exporters import ost_cab
from ost_visualizer.presentation.visualization.exporters.osp_exporter import OspExporter
from tests.helpers.mdb.import_export_support import (
    _Rows as _import_export_support__Rows,
    _SqliteConnection as _import_export_support__SqliteConnection,
    _SqliteCursor as _import_export_support__SqliteCursor,
    _SqliteMdbWriter as _import_export_support__SqliteMdbWriter,
    _SqliteSchema as _import_export_support__SqliteSchema,
    _create_import_schema as _import_export_support__create_import_schema,
    _named_row as _import_export_support__named_row,
)


class OspRoundtripRelationshipTests(unittest.TestCase):
    def test_osp_export_import_preserves_valid_selected_page_reference(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        # The shared schema stand-in has no drawing column; the roundtrip must
        # show where each imported page's drawing ends up.
        connection.execute("ALTER TABLE BidPages ADD COLUMN ImagePath TEXT")
        writer = _import_export_support__SqliteMdbWriter(connection)
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            drawing_paths = []
            for directory_name, content in (
                ("first", b"%PDF-1.4 first"),
                ("second", b"%PDF-1.4 second"),
            ):
                drawing_dir = temp_path / directory_name
                drawing_dir.mkdir()
                drawing_path = drawing_dir / "sheet.pdf"
                drawing_path.write_bytes(content)
                drawing_paths.append(drawing_path)
            raw_data = RawBidData(
                bid_row={"UID": "1", "JobName": "Imported"},
                bid_tables={
                    "BidSettings": [
                        {"UID": "2", "BidUID": "1", "BidPageSelectedUID": "4"}
                    ],
                    "BidPages": [
                        {
                            "UID": "3",
                            "BidUID": "1",
                            "Name": "Sheet One",
                            "Sequence": "1",
                            "ImagePath": str(drawing_paths[0]),
                        },
                        {
                            "UID": "4",
                            "BidUID": "1",
                            "Name": "Sheet Two",
                            "Sequence": "2",
                            "ImagePath": str(drawing_paths[1]),
                        },
                    ],
                },
            )
            osp_path = temp_path / "roundtrip.osp"
            exporter = OspExporter(
                SimpleNamespace(),
                "test",
                lambda _uom_service: OstExporter(SimpleNamespace()),
            )
            result = exporter.export(raw_data, str(osp_path), bid_name="Roundtrip")
            self.assertTrue(result.success, result.error_message)
            archive_names = list(ost_cab.list_cab(str(osp_path)))
            image_members = [
                name for name in archive_names if name.startswith("TempImages!.tmp\\")
            ]
            self.assertEqual(len(image_members), 2)
            self.assertEqual(len(set(image_members)), 2)
            self.assertFalse(any(name.count("\\") > 1 for name in image_members))
            working_dir = temp_path / "working"
            with patch.object(
                osp_importer_module,
                "get_default_working_dir",
                return_value=working_dir,
            ):
                self.assertTrue(
                    OspImporter(OstImporter(writer)).import_osp(
                        str(osp_path), "target.mdb"
                    )
                )
            page_uid = connection.execute(
                "SELECT UID FROM BidPages WHERE Name='Sheet Two'"
            ).fetchone()[0]
            page_drawings = {
                name: Path(image_path)
                for name, image_path in connection.execute(
                    "SELECT Name, ImagePath FROM BidPages"
                )
            }
            self.assertEqual(set(page_drawings), {"Sheet One", "Sheet Two"})
            self.assertEqual(page_drawings["Sheet One"].read_bytes(), b"%PDF-1.4 first")
            self.assertEqual(
                page_drawings["Sheet Two"].read_bytes(), b"%PDF-1.4 second"
            )
            for drawing in page_drawings.values():
                self.assertEqual(drawing.parent, working_dir / "Roundtrip")
            imported_drawings = sorted((working_dir / "Roundtrip").glob("*.pdf"))
            self.assertEqual(len(imported_drawings), 2)
            self.assertEqual(
                {path.read_bytes() for path in imported_drawings},
                {b"%PDF-1.4 first", b"%PDF-1.4 second"},
            )
        selected_uid = connection.execute(
            "SELECT BidPageSelectedUID FROM BidSettings"
        ).fetchone()[0]
        self.assertEqual(selected_uid, page_uid)
