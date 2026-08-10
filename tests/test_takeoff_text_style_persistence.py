import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import pyodbc
from PySide6.QtWidgets import QApplication, QGraphicsTextItem
from ost_visualizer.application.dtos.color_dtos import ColorWithOpacity
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_TEXT,
    hex_color_to_int,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.font_definition import FontDefinition
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
from ost_visualizer.infrastructure.mdb.database_creator import DatabaseCreator
from ost_visualizer.infrastructure.mdb.components.takeoff_operations import (
    TakeoffOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.presentation.visualization.pdf.renderers.takeoff_renderer import (
    TakeoffRenderer,
)
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)

try:
    import win32com.client as _win32_client
except ImportError:
    _win32_client = None
_ACCESS_DRIVER = "Microsoft Access Driver (*.mdb, *.accdb)"


def _access_available() -> bool:
    return _ACCESS_DRIVER in pyodbc.drivers() and _win32_client is not None


def _project_settings_snapshot(path: Path) -> dict[str, tuple[tuple, ...]]:
    connection = pyodbc.connect(
        f"DRIVER={{{_ACCESS_DRIVER}}};DBQ={path};",
        autocommit=True,
    )
    try:
        cursor = connection.cursor()
        snapshots = {}
        for table in ("Settings", "BidSettings"):
            cursor.execute(f"SELECT * FROM [{table}]")
            snapshots[table] = tuple(tuple(row) for row in cursor.fetchall())
        return snapshots
    finally:
        connection.close()


class _IdentityCoordinateSystem:
    def __init__(self):
        self.page_info = {}

    @staticmethod
    def parse_position(position):
        return position

    @staticmethod
    def transform_vertices_to_2d(vertices):
        return list(vertices)

    @staticmethod
    def ost_to_pdf_points(value):
        return float(value)

    def update_page_info(self, page_info):
        self.page_info = page_info


class _FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def cursor(self):
        return object()


class _TakeoffTextStyleWriter(TakeoffOperationsMixin):
    def __init__(self):
        self.calls = []
        self.logger = logging.getLogger(__name__)

    def _connection(self, _db_path):
        return _FakeConnection()

    def _schema(self, _conn):
        return object()

    @staticmethod
    def _record_caught_mutation_error(_exc):
        return False

    def _execute_update_values(
        self,
        cursor,
        _schema,
        table,
        values,
        required_columns,
        where_sql,
        params,
        operation,
        _allow_empty=False,
    ):
        self.calls.append(
            (table, dict(values), required_columns, where_sql, list(params), operation)
        )
        return True


class TakeoffTextStylePersistenceTests(unittest.TestCase):
    def test_takeoff_text_styles_write_bid_takeoff_font_columns(self):
        writer = _TakeoffTextStyleWriter()
        self.assertTrue(
            writer.save_takeoff_text_properties(
                "bid.mdb",
                [
                    (
                        "9200",
                        {
                            "dimension_font_name": "Arial",
                            "dimension_font_color": 16711680,
                            "dimension_font_size": 72,
                            "dimension_font_bold": True,
                            "dimension_font_italic": False,
                            "dimension_font_underline": False,
                            "name_font_name": "Arial",
                            "name_font_color": 8388608,
                            "name_font_size": 48,
                            "name_font_bold": True,
                            "name_font_italic": False,
                            "name_font_underline": False,
                        },
                    )
                ],
            )
        )
        self.assertEqual(len(writer.calls), 1)
        table, values, required_columns, where_sql, params, operation = writer.calls[0]
        self.assertEqual(table, "BidTakeoffs")
        self.assertEqual(required_columns, ("UID",))
        self.assertEqual(where_sql, "[UID]=?")
        self.assertEqual(params, [9200])
        self.assertEqual(operation, "save_takeoff_text_properties")
        self.assertEqual(values["FontName"], "Arial")
        self.assertEqual(values["FontColor"], 16711680)
        self.assertEqual(values["FontSize"], 72)
        self.assertTrue(values["FontBold"])
        self.assertEqual(values["NameFontName"], "Arial")
        self.assertEqual(values["NameFontColor"], 8388608)
        self.assertEqual(values["NameFontSize"], 48)
        self.assertTrue(values["NameFontBold"])

    @unittest.skipUnless(
        _access_available(),
        "Microsoft Access ODBC and ADOX are required for the live MDB contract",
    )
    def test_live_mdb_creation_and_explicit_text_styles_survive_reload(self):
        # The Access ODBC driver has a process-wide client-task ceiling. Run this
        # end-to-end contract in a clean process so the complete suite cannot
        # exhaust it with earlier, deliberately long-lived manager tests.
        if os.environ.get("OSTV_LIVE_MDB_STYLE_CHILD") != "1":
            environment = os.environ.copy()
            environment["OSTV_LIVE_MDB_STYLE_CHILD"] = "1"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    (
                        "tests.test_takeoff_text_style_persistence."
                        "TakeoffTextStylePersistenceTests."
                        "test_live_mdb_creation_and_explicit_text_styles_survive_reload"
                    ),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                env=environment,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"isolated Access contract failed:\n{result.stdout}\n{result.stderr}",
            )
            return
        self._app = QApplication.instance() or QApplication([])
        creation_config = Config(
            default_text_font=FontDefinition(
                "Arial", "Bold Italic", 14, 700, True, True
            ),
            default_area_label_font=FontDefinition(
                "Arial", "Bold", 10, 700, False, False
            ),
            default_style_label_font=FontDefinition(
                "Arial", "Regular", 12, 400, False, True
            ),
            default_text_color="#123456",
            default_area_label_color="#112233",
            default_style_label_color="#445566",
            inactive_object_color="#2468ac",
        )
        label_extras = {
            "FontName": creation_config.default_area_label_font.family,
            "FontColor": hex_color_to_int(creation_config.default_area_label_color),
            "FontSize": creation_config.default_area_label_font.point_size,
            "FontBold": True,
            "FontItalic": False,
            "FontUnderline": False,
            "NameFontName": creation_config.default_style_label_font.family,
            "NameFontColor": hex_color_to_int(
                creation_config.default_style_label_color
            ),
            "NameFontSize": creation_config.default_style_label_font.point_size,
            "NameFontBold": False,
            "NameFontItalic": False,
            "NameFontUnderline": True,
        }
        text_properties = {
            "Text": "Configured text",
            "FontName": creation_config.default_text_font.family,
            "FontColor": hex_color_to_int(creation_config.default_text_color),
            "FontSize": creation_config.default_text_font.point_size,
            "FontBold": True,
            "FontItalic": True,
            "FontUnderline": True,
            "TextAlign": 0,
        }
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            path = Path(temp_dir) / "font_color_contract.mdb"
            self.assertTrue(DatabaseCreator().create_database(path, "Font Contract"))
            connections = MdbConnectionManager()
            writer = MdbWriter(connections)
            reader = MdbReader(connections)
            try:
                bid_uid = writer.create_bid(
                    str(path),
                    None,
                    {
                        "job_name": "Font Contract",
                        "pages": [
                            {
                                "name": "Page 1",
                                "width": 42.0,
                                "height": 30.0,
                                "scale_factor1": 1.0,
                                "scale_factor2": 1.0,
                            }
                        ],
                    },
                )
                self.assertIsNotNone(bid_uid)
                connection = pyodbc.connect(
                    f"DRIVER={{{_ACCESS_DRIVER}}};DBQ={path};",
                    autocommit=True,
                )
                try:
                    cursor = connection.cursor()
                    cursor.execute(
                        "SELECT [UID] FROM [BidPages] WHERE [BidUID]=?", bid_uid
                    )
                    page_uid = str(cursor.fetchone()[0])
                finally:
                    connection.close()
                settings_before = _project_settings_snapshot(path)
                condition_uid = writer.insert_condition(
                    str(path),
                    bid_uid,
                    CreateConditionSpec(
                        name="Configured area",
                        condition_type=Condition.TYPE_AREA,
                        display_dimension=True,
                        display_name=True,
                        calc_type1=11,
                        uom1=4,
                    ),
                )
                self.assertIsNotNone(condition_uid)
                takeoff_uids = writer.insert_takeoffs(
                    str(path),
                    bid_uid,
                    [
                        InsertTakeoffSpec(
                            condition_uid=condition_uid,
                            page_uid=page_uid,
                            area_uid=None,
                            position=[
                                0.0,
                                0.0,
                                12.0,
                                0.0,
                                12.0,
                                12.0,
                                0.0,
                                12.0,
                            ],
                            raw_extras=label_extras,
                        )
                    ],
                )
                annotation_uids = writer.insert_annotations(
                    str(path),
                    bid_uid,
                    [
                        InsertAnnotationSpec(
                            page_uid=page_uid,
                            annotation_type=ANNOTATION_TYPE_TEXT,
                            position=[10.0, 10.0, 200.0, 60.0],
                            color=creation_config.default_text_color,
                            width=0.0,
                            properties=text_properties,
                        )
                    ],
                )
                self.assertEqual(len(takeoff_uids), 1)
                self.assertEqual(len(annotation_uids), 1)
                first_load = reader.get_bid_data(str(path), bid_uid)
                created_takeoff = first_load[1][0]
                self.assertEqual(
                    (
                        created_takeoff.dimension_font_name,
                        created_takeoff.dimension_font_color,
                        created_takeoff.dimension_font_size,
                        created_takeoff.dimension_font_bold,
                        created_takeoff.dimension_font_italic,
                        created_takeoff.dimension_font_underline,
                    ),
                    ("Arial", 0x332211, 10, True, False, False),
                )
                self.assertEqual(
                    (
                        created_takeoff.name_font_name,
                        created_takeoff.name_font_color,
                        created_takeoff.name_font_size,
                        created_takeoff.name_font_bold,
                        created_takeoff.name_font_italic,
                        created_takeoff.name_font_underline,
                    ),
                    ("Arial", 0x665544, 12, False, False, True),
                )
                created_text = next(
                    annotation
                    for annotation in first_load[6]
                    if annotation.uid == annotation_uids[0]
                )
                self.assertEqual(created_text.color, creation_config.default_text_color)
                self.assertEqual(
                    (
                        created_text.properties["FontName"],
                        created_text.properties["FontColor"],
                        created_text.properties["FontSize"],
                        created_text.properties["FontBold"],
                        created_text.properties["FontItalic"],
                        created_text.properties["FontUnderline"],
                    ),
                    ("Arial", 0x563412, 14, True, True, True),
                )
                self.assertTrue(
                    writer.save_takeoff_text_properties(
                        str(path),
                        [
                            (
                                takeoff_uids[0],
                                {
                                    "dimension_font_name": "Arial",
                                    "dimension_font_color": 0xCCBBAA,
                                    "dimension_font_size": 18,
                                    "dimension_font_bold": False,
                                    "dimension_font_italic": True,
                                    "dimension_font_underline": True,
                                    "name_font_name": "Arial",
                                    "name_font_color": 0xFFEEDD,
                                    "name_font_size": 16,
                                    "name_font_bold": True,
                                    "name_font_italic": False,
                                    "name_font_underline": False,
                                },
                            )
                        ],
                    )
                )
                current_config = Config(
                    default_area_label_color="#abcdef",
                    default_style_label_color="#fedcba",
                    inactive_object_color="#0a0b0c",
                )
                reloaded = reader.get_bid_data(str(path), bid_uid)
                persisted_takeoff = reloaded[1][0]
                self.assertEqual(
                    (
                        persisted_takeoff.dimension_font_color,
                        persisted_takeoff.dimension_font_size,
                        persisted_takeoff.dimension_font_bold,
                        persisted_takeoff.dimension_font_italic,
                        persisted_takeoff.dimension_font_underline,
                    ),
                    (0xCCBBAA, 18, False, True, True),
                )
                self.assertEqual(
                    (
                        persisted_takeoff.name_font_color,
                        persisted_takeoff.name_font_size,
                        persisted_takeoff.name_font_bold,
                        persisted_takeoff.name_font_italic,
                        persisted_takeoff.name_font_underline,
                    ),
                    (0xFFEEDD, 16, True, False, False),
                )
                persisted_text = next(
                    annotation
                    for annotation in reloaded[6]
                    if annotation.uid == annotation_uids[0]
                )
                self.assertEqual(
                    persisted_text.color, creation_config.default_text_color
                )
                renderer = TakeoffRenderer(_IdentityCoordinateSystem(), ColorService())
                rendered = renderer.create_all_path_items(
                    [persisted_takeoff],
                    reloaded[0],
                    {condition_uid: ColorWithOpacity("#778899", 0.65)},
                    inactive_object_color=current_config.inactive_object_color,
                )
                graphics_items = rendered[0][1]
                if not isinstance(graphics_items, list):
                    graphics_items = [graphics_items]
                dimension_label = next(
                    item
                    for item in graphics_items
                    if isinstance(item, QGraphicsTextItem)
                    and item.data(3) == "display_dimension"
                )
                name_label = next(
                    item
                    for item in graphics_items
                    if isinstance(item, QGraphicsTextItem)
                    and item.data(3) == "display_name"
                )
                self.assertEqual(dimension_label.defaultTextColor().name(), "#aabbcc")
                self.assertEqual(dimension_label.font().pointSize(), 18)
                self.assertTrue(dimension_label.font().italic())
                self.assertEqual(name_label.defaultTextColor().name(), "#ddeeff")
                self.assertEqual(name_label.font().pointSize(), 16)
                self.assertTrue(name_label.font().bold())
                self.assertEqual(_project_settings_snapshot(path), settings_before)
            finally:
                connections.close_database(str(path))


if __name__ == "__main__":
    unittest.main()
