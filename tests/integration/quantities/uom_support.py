import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from shiboken6 import delete
from ost_visualizer.application.dtos.condition_summary_dtos import (
    SUMMARY_COLUMN_UOM1,
    SUMMARY_COLUMN_UOM2,
    SUMMARY_COLUMN_UOM3,
    SUMMARY_NODE_CONDITION,
    ConditionSummaryGrouping,
    ConditionSummaryNode,
    ConditionSummaryValues,
)
from ost_visualizer.application.services.project_read_service import ProjectReadService
from ost_visualizer.application.use_cases.project.load_bid_use_case import (
    LoadBidUseCase,
    PreparedBidLoad,
)
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.condition_quantity_service import (
    compute_page_quantities,
)
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.domain.services.uom_service import (
    CALC_COUNT,
    CALC_AREA,
    CALC_LINEAR_BOTH_SIDES,
    CALC_LINEAR_LENGTH,
    CALC_VOLUME,
    UOM_CUBIC_FEET,
    UOM_EACH,
    UOM_LINEAR_FEET,
    UOM_M,
    UOM_M2,
    UOM_M3,
    UOM_SQUARE_FEET,
    UOM_SQUARE_ROOFING,
    get_uom_label,
    normalize_condition_uoms_for_system,
)
from ost_visualizer.domain.services.uom_service_impl import UOMDomainService
from ost_visualizer.infrastructure.mdb.components.bid_data_reader import (
    BidDataReaderMixin,
)
from ost_visualizer.infrastructure.mdb.exporters.ost_exporter import OstExporter
from ost_visualizer.presentation.components.condition_summary import ConditionSummaryTab
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.dialogs.edit_condition_dialog import (
    EditConditionDialog,
)
from tests.helpers.workspace_state import make_workspace_state_model


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _condition(uid="condition-1"):
    return Condition(
        uid=uid,
        name="Measured work",
        condition_type=Condition.TYPE_LINEAR,
        ref_no=1,
        height=12.0,
        thickness=6.0,
        calc_type1=CALC_LINEAR_LENGTH,
        uom1=UOM_LINEAR_FEET,
        calc_type2=CALC_LINEAR_BOTH_SIDES,
        uom2=UOM_SQUARE_FEET,
        calc_type3=CALC_VOLUME,
        uom3=UOM_CUBIC_FEET,
    )


class _ReaderSchema:
    _columns = {
        "Bids": {"UID", "MeasureBase"},
        "BidConditions": {
            "UID",
            "BidUID",
            "Name",
            "Type",
            "UOM1",
            "UOM2",
            "UOM3",
            "Quantity1",
            "Quantity2",
            "Quantity3",
        },
    }

    def column_exists(self, table, column):
        return column in self._columns.get(table, ())

    def optional_column(self, table, column, default):
        if self.column_exists(table, column):
            return f"[{column}]"
        return f"{default} AS [{column}]"


class _ReaderCursor:
    def __init__(self, metric):
        self._metric = metric
        self._measure_query = False

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def execute(self, query, *_params):
        self._measure_query = "MeasureBase" in query
        return self

    def fetchone(self):
        return (1 if self._metric else 0,)

    def fetchall(self):
        if self._measure_query:
            return []
        defaults = {
            "UID": 1,
            "Name": "Measured work",
            "Type": Condition.TYPE_LINEAR,
            "Thickness": 0,
            "Height": 0,
            "Width": 0,
            "Depth": 0,
            "Rise": 0,
            "Run": 0,
            "Shape": 0,
            "ColorFill": 0,
            "CdnTypeUID": None,
            "Pattern": 0,
            "Spacing": 0,
            "BidLayerUID": None,
            "UOM1": UOM_LINEAR_FEET,
            "UOM2": UOM_SQUARE_FEET,
            "UOM3": UOM_CUBIC_FEET,
            "Quantity1": CALC_LINEAR_LENGTH,
            "Quantity2": CALC_LINEAR_BOTH_SIDES,
            "Quantity3": CALC_VOLUME,
            "RefNo": 1,
            "DisplaySize": 100,
            "DropRun": 0,
            "DropValue": 0,
            "BidConditionFolderUID": None,
            "Notes": None,
            "RoundQuantity": 0,
            "RoundUp": 0,
            "Trim": 0,
            "IsCurvedSegment": 0,
            "Grid": 0,
            "GridSize1": 0,
            "GridSize2": 0,
            "Gap": 0,
            "DisplayDimension": 0,
            "DisplayName": 0,
            "DisplayGridWhileDrawing": 0,
        }
        return [SimpleNamespace(**defaults)]


class _ReaderConnection:
    def __init__(self, metric):
        self.metric = metric

    def cursor(self):
        return _ReaderCursor(self.metric)
