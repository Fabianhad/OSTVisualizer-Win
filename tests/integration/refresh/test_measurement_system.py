import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
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
from tests.integration.quantities.uom_support import (
    _app as _uom_support__app,
    _condition as _uom_support__condition,
)


class ConditionUomConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _uom_support__app()
        cls.quit_on_close = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls.quit_on_close)

    def tearDown(self):
        self.app.processEvents()

    def test_targeted_unit_refresh_and_later_condition_refresh_stay_metric(self):
        condition = _uom_support__condition()
        bid_ref = BidRef("metric.mdb", "42")
        refreshed_info = HierarchyBidInfo(uid="42", name="Metric", measure_base=1)

        class Repository:
            active_file_path = bid_ref.file_path

            @staticmethod
            def get_cdn_types(_file_path):
                return {}

        class FileManager:
            project_repository = Repository()

            @staticmethod
            def register_loaded_hierarchy(_file_entry, _cdn_types):
                return HierarchyData()

        model = SimpleNamespace(
            file_manager=FileManager(),
            cdn_types={},
            current_bid_ref=bid_ref,
            current_bid=Bid(uid="42", name="Imperial", measure_base=0),
            bid_conditions={condition.uid: condition},
            find_bid_info=lambda _bid_ref: refreshed_info,
            set_hierarchy=lambda _hierarchy: None,
            get_all_pages=lambda: [],
            projects=[],
        )
        service = ProjectDataService(model)
        service.replace_database_hierarchy(
            HierarchyFileEntry(file_path=bid_ref.file_path), {}
        )
        self.assertEqual(model.current_bid.measure_base, 1)
        self.assertEqual(
            (condition.uom1, condition.uom2, condition.uom3),
            (UOM_M, UOM_M2, UOM_M3),
        )
        reconstructed_after_rename = _uom_support__condition()
        reconstructed_after_rename.name = "Renamed"
        self.assertTrue(
            service.replace_condition_family(
                bid_ref, {condition.uid: reconstructed_after_rename}, {}
            )
        )
        self.assertEqual(
            (
                reconstructed_after_rename.uom1,
                reconstructed_after_rename.uom2,
                reconstructed_after_rename.uom3,
            ),
            (UOM_M, UOM_M2, UOM_M3),
        )
