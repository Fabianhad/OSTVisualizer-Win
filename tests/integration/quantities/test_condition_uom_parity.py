import os
import unittest
from unittest.mock import Mock

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
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.condition_quantity_service import (
    compute_page_quantities,
)
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
from ost_visualizer.presentation.components.condition_summary import ConditionSummaryTab
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.dialogs.edit_condition_dialog import (
    EditConditionDialog,
)
from tests.helpers.workspace_state import make_workspace_state_model
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
        condition = normalize_condition_uoms_for_system(
            _uom_support__condition(), metric=True
        )
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
        condition = normalize_condition_uoms_for_system(
            _uom_support__condition(), metric=False
        )
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
