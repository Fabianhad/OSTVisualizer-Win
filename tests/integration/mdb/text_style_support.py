import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import pyodbc
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
from ost_visualizer.infrastructure.mdb.components.takeoff_operations import (
    TakeoffOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
from ost_visualizer.infrastructure.mdb.database_creator import DatabaseCreator
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.presentation.visualization.pdf.renderers.takeoff_renderer import (
    TakeoffRenderer,
)
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)
from PySide6.QtWidgets import QApplication, QGraphicsTextItem

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


class _FakeCursor:
    def __init__(self):
        self.rows = []

    def execute(self, sql, *params):
        if sql.startswith("SELECT [UID], [BidUID] FROM ["):
            self.rows = [(param, 1) for param in params]
        else:
            self.rows = [(param,) for param in params]

    def fetchall(self):
        return list(self.rows)


class _FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def cursor(self):
        return _FakeCursor()


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
