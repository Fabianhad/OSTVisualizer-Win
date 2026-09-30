import os
import re
import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.annotation_caption_dto import (
    AnnotationCaptionSettingsDto,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.services.annotation_caption_resolver import (
    AnnotationCaptionResolver,
)
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.annotation_caption import AnnotationCaptionId
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.layer import Layer
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.domain.services.uom_service_impl import UOMDomainService
from ost_visualizer.infrastructure.mdb.components.annotation_operations import (
    AnnotationOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.annotation_reader import (
    AnnotationReaderMixin,
)
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    AccessBulkWriteMixin,
)
from ost_visualizer.infrastructure.mdb.components.serialization import (
    encode_position,
    parse_position_storage,
    serialize_position_for_table,
)
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
)
from ost_visualizer.presentation.components.plan_view.components.selection_manager import (
    SelectionManagerMixin,
)
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    CLOUD_SCALLOP_SIZE_SCALE,
    calculate_annotation_geometry,
    calculate_cloud_scallop_radius,
    calculate_highlight_quad_path,
    create_cloud_path_points,
    format_dimension_distance,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
)


class _FakeCursor:
    def __init__(self, rows_by_table):
        self.rows_by_table = rows_by_table
        self.last_query = ""

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def execute(self, query, *_params):
        self.last_query = query

    def fetchall(self):
        for table, rows in self.rows_by_table.items():
            if table in self.last_query:
                return rows
        return []


class _FakeConnection:
    def __init__(self, rows_by_table):
        self.rows_by_table = rows_by_table

    def cursor(self):
        return _FakeCursor(self.rows_by_table)


class _FakeSchema:
    def __init__(self, columns_by_table=None):
        self.columns_by_table = columns_by_table or {}

    def column_exists(self, table_name, column_name):
        return column_name in self.columns_by_table.get(table_name, set())

    def optional_column(self, table_name, column_name, default_sql, alias=None):
        alias_name = alias or column_name
        if self.column_exists(table_name, column_name):
            return f"[{column_name}]"
        return f"{default_sql} AS [{alias_name}]"


class _SelectionHarness(SelectionManagerMixin):
    def __init__(self, annotation, items):
        self._current_annotations = {annotation.uid: annotation}
        self._uid_to_items = {annotation.uid: items}
        self._scene_builder = SimpleNamespace(
            get_coordinate_system=lambda: OSTCoordinateSystem()
        )


class _Reader(AnnotationReaderMixin):
    def _record_caught_read_error(self, _exc):
        return False


def _annotation_reader_schema(*, named_view_has_color=True):
    named_view_columns = {"UID", "BidUID", "BidPageUID", "Name", "Position"}
    if named_view_has_color:
        named_view_columns.add("Color")
    return _FakeSchema({"BidNamedViews": named_view_columns})


class _Schema:
    def optional_table_missing(self, _table):
        return False

    def column_exists(self, _table, _column):
        return True


class _Logger:
    def exception(self, *_args, **_call_options):
        pass


class _SqliteCursorWrapper:
    def __init__(self, conn):
        self._conn = conn
        self._cursor = None

    def execute(self, query, *params):
        if len(params) == 1 and isinstance(params[0], (list, tuple)):
            params = tuple(params[0])
        self._cursor = self._conn.execute(query, params)

    def fetchone(self):
        if self._cursor is None:
            return None
        return self._cursor.fetchone()

    def fetchall(self):
        if self._cursor is None:
            return []
        return self._cursor.fetchall()


class _SqliteConnectionWrapper:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc, _tb):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return False

    def cursor(self):
        return _SqliteCursorWrapper(self._conn)


class _DimensionWriteOps(AccessBulkWriteMixin, AnnotationOperationsMixin):
    logger = _Logger()

    def __init__(self, conn):
        self._conn = conn

    def _connection(self, _db_path):
        return _SqliteConnectionWrapper(self._conn)

    def _schema(self, _conn):
        return _Schema()

    def _require_write_columns(self, _schema, _table, _columns):
        pass

    @staticmethod
    def _record_caught_mutation_error(_exc):
        return False

    def _execute_insert_values(
        self,
        cursor,
        _schema,
        table,
        values,
        required_columns,
        _operation,
    ):
        missing = [column for column in required_columns if column not in values]
        if missing:
            raise AssertionError(f"missing required columns: {missing}")
        col_list = ", ".join(f"[{column}]" for column in values)
        placeholders = ", ".join("?" for _ in values)
        cursor.execute(
            f"INSERT INTO [{table}] ({col_list}) VALUES ({placeholders})",
            list(values.values()),
        )


class _ColorService:
    def hex_to_rgb_int(self, color):
        text = color.lstrip("#")
        return [int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)]

    def get_2d_color_for_takeoff(
        self,
        _takeoff,
        condition,
        color_map,
        _page_area_selections=None,
        *,
        inactive_object_color,
    ):
        _ = inactive_object_color
        return color_map[condition.uid]


def _page_info():
    return {
        "scale_factor1": 1.0,
        "scale_factor2": 72.0,
        "rotation": 0,
        "flip_x": False,
        "flip_y": False,
        "width": 612.0,
        "height": 792.0,
        "view_scale": 1.0,
    }
