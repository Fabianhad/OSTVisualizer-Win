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
from tests.workspace_state_test_support import make_workspace_state_model


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


class ConditionUomConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls.quit_on_close = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls.quit_on_close)

    def tearDown(self):
        self.app.processEvents()

    def _sidebar_texts(self, condition):
        sidebar = ConditionsSidebar(None, uom_label_fn=get_uom_label)
        self.addCleanup(sidebar.close)
        sidebar.load_conditions({condition.uid: condition}, {}, "Project")
        sidebar.update_quantities({condition.uid: (1.25, 2.5, 3.75)})
        item = sidebar._condition_items[condition.uid]
        return tuple(item.text(column) for column in (2, 3, 4))

    def _properties_uom_texts(self, condition, *, metric):
        dialog = EditConditionDialog(
            None,
            None,
            condition,
            [condition.uid],
            {condition.uid: condition},
            {},
            {},
            lambda _uid: False,
            lambda _uid, _dto: True,
            make_workspace_state_model(),
            read_service=ProjectReadService(Mock()),
            metric=metric,
        )
        try:
            return tuple(combo.currentText() for combo in dialog._uom_combos)
        finally:
            dialog._dirty = False
            dialog.close()
            delete(dialog)

    def _summary_uom_texts(self, condition):
        tab = ConditionSummaryTab(None, uom_label_fn=get_uom_label)
        self.addCleanup(tab.close)
        root = ConditionSummaryNode(
            kind="root",
            children=[
                ConditionSummaryNode(
                    kind=SUMMARY_NODE_CONDITION,
                    condition_uid=condition.uid,
                    values=ConditionSummaryValues(
                        number="1",
                        name=condition.name,
                        quantity1=1.25,
                        uom1=condition.uom1,
                        quantity2=2.5,
                        uom2=condition.uom2,
                        quantity3=3.75,
                        uom3=condition.uom3,
                    ),
                )
            ],
        )
        tab.load_summary(root, ConditionSummaryGrouping(), False)
        item = tab._condition_items[condition.uid][0]
        return tuple(
            item.text(tab.column_keys.index(key))
            for key in (SUMMARY_COLUMN_UOM1, SUMMARY_COLUMN_UOM2, SUMMARY_COLUMN_UOM3)
        )

    def test_metric_sidebar_properties_and_summary_use_same_uoms(self):
        condition = normalize_condition_uoms_for_system(_condition(), metric=True)
        self.assertEqual(
            (condition.uom1, condition.uom2, condition.uom3),
            (UOM_M, UOM_M2, UOM_M3),
        )
        self.assertEqual(
            self._sidebar_texts(condition), ("1.25 m", "2.50 m²", "3.75 m³")
        )
        self.assertEqual(
            self._properties_uom_texts(condition, metric=True),
            ("m", "m²", "m³"),
        )
        self.assertEqual(self._summary_uom_texts(condition), ("m", "m²", "m³"))

    def test_imperial_sidebar_properties_and_summary_are_unchanged(self):
        condition = normalize_condition_uoms_for_system(_condition(), metric=False)
        self.assertEqual(self._sidebar_texts(condition), ("1 LF", "2 SF", "4 CF"))
        self.assertEqual(
            self._properties_uom_texts(condition, metric=False),
            ("LF", "SF", "CF"),
        )
        self.assertEqual(self._summary_uom_texts(condition), ("LF", "SF", "CF"))

    def test_count_keeps_existing_each_convention_in_both_systems(self):
        for metric in (False, True):
            with self.subTest(metric=metric):
                condition = Condition(
                    uid=f"count-{metric}",
                    name="Count",
                    condition_type=Condition.TYPE_COUNT,
                    calc_type1=CALC_COUNT,
                    uom1=UOM_EACH,
                )
                normalize_condition_uoms_for_system(condition, metric)
                self.assertEqual(condition.uom1, UOM_EACH)
                self.assertEqual(self._sidebar_texts(condition)[0], "1 EA")

    def test_incompatible_persisted_count_uom_normalizes_to_each_before_calculation(
        self,
    ):
        condition = Condition(
            uid="count",
            name="Count",
            condition_type=Condition.TYPE_COUNT,
            calc_type1=CALC_COUNT,
            uom1=UOM_LINEAR_FEET,
        )
        normalize_condition_uoms_for_system(condition, metric=True)
        quantity = compute_page_quantities(
            {condition.uid: condition},
            [
                Takeoff(
                    uid="takeoff-count",
                    condition_uid=condition.uid,
                    page_uid="page-1",
                    position=[0.0, 0.0],
                )
            ],
        )[condition.uid][0]
        self.assertEqual(condition.uom1, UOM_EACH)
        self.assertEqual(quantity, 1.0)
        self.assertEqual(self._sidebar_texts(condition)[0], "1 EA")
        self.assertEqual(self._properties_uom_texts(condition, metric=True)[0], "EA")

    def test_imperial_roofing_uom_remains_available_and_quantity_is_not_rescaled(self):
        condition = Condition(
            uid="roofing",
            name="Roofing",
            condition_type=Condition.TYPE_AREA,
            calc_type1=CALC_AREA,
            uom1=UOM_SQUARE_ROOFING,
        )
        normalize_condition_uoms_for_system(condition, metric=False)
        quantity = compute_page_quantities(
            {condition.uid: condition},
            [
                Takeoff(
                    uid="takeoff-roofing",
                    condition_uid=condition.uid,
                    page_uid="page-1",
                    position=[
                        0.0,
                        0.0,
                        120.0,
                        0.0,
                        120.0,
                        120.0,
                        0.0,
                        120.0,
                    ],
                )
            ],
        )[condition.uid][0]
        self.assertEqual(condition.uom1, UOM_SQUARE_ROOFING)
        self.assertEqual(quantity, 1.0)
        self.assertEqual(self._sidebar_texts(condition)[0], "1 SQ")
        self.assertEqual(self._properties_uom_texts(condition, metric=False)[0], "SQ")

    def test_quantity_calculation_uses_normalized_linear_area_volume_uoms(self):
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-1",
            position=[0.0, 0.0, 120.0, 0.0],
        )
        imperial_condition = _condition()
        metric_condition = normalize_condition_uoms_for_system(
            _condition(), metric=True
        )
        imperial = compute_page_quantities(
            {imperial_condition.uid: imperial_condition}, [takeoff]
        )[imperial_condition.uid]
        metric = compute_page_quantities(
            {metric_condition.uid: metric_condition}, [takeoff]
        )[metric_condition.uid]
        self.assertEqual(imperial, (10.0, 20.0, 5.0))
        self.assertAlmostEqual(metric[0], 3.048)
        self.assertAlmostEqual(metric[1], 1.8580608)
        self.assertAlmostEqual(metric[2], 0.14158423296)

    def test_repeated_normalize_refresh_reload_cycle_has_no_quantity_drift(self):
        condition = _condition()
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid=condition.uid,
            page_uid="page-1",
            position=[0.0, 0.0, 120.0, 0.0],
        )
        normalize_condition_uoms_for_system(condition, metric=True)
        first_codes = (condition.uom1, condition.uom2, condition.uom3)
        first_quantities = compute_page_quantities(
            {condition.uid: condition}, [takeoff]
        )[condition.uid]
        for _iteration in range(3):
            normalize_condition_uoms_for_system(condition, metric=True)
        self.assertEqual((condition.uom1, condition.uom2, condition.uom3), first_codes)
        self.assertEqual(
            compute_page_quantities({condition.uid: condition}, [takeoff])[
                condition.uid
            ],
            first_quantities,
        )

    def test_bid_load_reconstruction_normalizes_metric_condition_uoms(self):
        condition = _condition()
        bid_info = HierarchyBidInfo(uid="42", name="Metric", measure_base=1)
        model = SimpleNamespace(
            find_bid_info=lambda _bid_ref: bid_info,
            set_pages=lambda _pages: None,
            set_annotations=lambda _annotations: None,
            deselect_pages=lambda: None,
        )
        project_data = SimpleNamespace(
            replace_cover_sheet_data=lambda *_args: None,
            replace_page_delete_content_uids=lambda *_args: None,
            set_bid_layer_visibility=lambda _layers: None,
        )
        use_case = LoadBidUseCase(
            model,
            project_data,
            SimpleNamespace(apply_bid_load=lambda _database_id: None),
            SimpleNamespace(load_bid=lambda *_args: None),
            SimpleNamespace(uses_sql_workspace=lambda *_args: False),
        )
        self.assertTrue(
            use_case.apply_prepared(
                BidRef("metric.mdb", "42"),
                PreparedBidLoad(
                    BidLoadResult(bid_conditions={condition.uid: condition}), None
                ),
            )
        )
        self.assertEqual(
            (condition.uom1, condition.uom2, condition.uom3),
            (UOM_M, UOM_M2, UOM_M3),
        )

    def test_shared_mdb_sql_reader_reconstructs_uoms_from_bid_measure_base(self):
        reader = BidDataReaderMixin()
        schema = _ReaderSchema()
        metric = reader._parse_bid_conditions_for_bid(
            _ReaderConnection(True), "42", {}, {}, schema
        )["1"]
        imperial = reader._parse_bid_conditions_for_bid(
            _ReaderConnection(False), "42", {}, {}, schema
        )["1"]
        self.assertEqual(
            (metric.uom1, metric.uom2, metric.uom3), (UOM_M, UOM_M2, UOM_M3)
        )
        self.assertEqual(
            (imperial.uom1, imperial.uom2, imperial.uom3),
            (UOM_LINEAR_FEET, UOM_SQUARE_FEET, UOM_CUBIC_FEET),
        )

    def test_metric_raw_ost_export_normalizes_stale_condition_uom_and_quantity(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Metric", "MeasureBase": "1"},
            bid_tables={
                "BidConditions": [
                    {
                        "UID": "10",
                        "BidUID": "1",
                        "Name": "Line",
                        "Type": str(Condition.TYPE_LINEAR),
                        "Height": "12",
                        "Thickness": "6",
                        "Quantity1": str(CALC_LINEAR_LENGTH),
                        "UOM1": str(UOM_LINEAR_FEET),
                    }
                ],
                "BidPages": [
                    {
                        "UID": "20",
                        "BidUID": "1",
                        "Name": "Sheet",
                        "Sequence": "1",
                    }
                ],
            },
            page_tables={
                "BidTakeoffs": [
                    {
                        "UID": "30",
                        "BidUID": "1",
                        "BidConditionUID": "10",
                        "BidPageUID": "20",
                        "Position": "0;0;120;0",
                    }
                ]
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "metric.ost"
            result = OstExporter(UOMDomainService()).export(raw_data, str(output_path))
            condition_element = (
                ET.parse(output_path).getroot().find("./Bid/BidConditions/BidCondition")
            )
        self.assertTrue(result.success, result.error_message)
        self.assertIsNotNone(condition_element)
        self.assertEqual(condition_element.get("UOM1"), str(UOM_M))
        self.assertEqual(
            raw_data.bid_tables["BidConditions"][0]["UOM1"],
            str(UOM_LINEAR_FEET),
        )
        quantity_element = condition_element.find(
            "./BidAreaConditions/BidAreaCondition"
        )
        self.assertAlmostEqual(float(quantity_element.get("Quantity1")), 3.048)

    def test_same_condition_uid_in_another_bid_cannot_replace_active_family(self):
        active_ref = BidRef("active.mdb", "2")
        other_ref = BidRef("other.mdb", "1")
        active_condition = _condition(uid="shared")
        model = SimpleNamespace(
            current_bid_ref=active_ref,
            current_bid=Bid(uid="2", name="Imperial", measure_base=0),
            bid_conditions={active_condition.uid: active_condition},
            bid_condition_folders={},
        )
        service = ProjectDataService(model)
        other_condition = normalize_condition_uoms_for_system(
            _condition(uid="shared"), metric=True
        )
        self.assertFalse(
            service.replace_condition_family(
                other_ref, {other_condition.uid: other_condition}, {}
            )
        )
        self.assertIs(model.bid_conditions["shared"], active_condition)
        self.assertTrue(
            service.replace_condition_family(
                active_ref, {other_condition.uid: other_condition}, {}
            )
        )
        self.assertEqual(
            (other_condition.uom1, other_condition.uom2, other_condition.uom3),
            (UOM_LINEAR_FEET, UOM_SQUARE_FEET, UOM_CUBIC_FEET),
        )

    def test_targeted_unit_refresh_and_later_condition_refresh_stay_metric(self):
        condition = _condition()
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
        reconstructed_after_rename = _condition()
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


if __name__ == "__main__":
    unittest.main()
