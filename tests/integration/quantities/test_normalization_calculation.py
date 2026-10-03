import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
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

    def test_quantity_calculation_uses_normalized_linear_area_volume_uoms(self):
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-1",
            position=[0.0, 0.0, 120.0, 0.0],
        )
        imperial_condition = _uom_support__condition()
        metric_condition = normalize_condition_uoms_for_system(
            _uom_support__condition(), metric=True
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
        condition = _uom_support__condition()
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid=condition.uid,
            page_uid="page-1",
            position=[0.0, 0.0, 120.0, 0.0],
        )
        # Precondition: the fixture starts imperial, so normalizing is a real change.
        self.assertEqual(
            (condition.uom1, condition.uom2, condition.uom3),
            (UOM_LINEAR_FEET, UOM_SQUARE_FEET, UOM_CUBIC_FEET),
        )
        normalize_condition_uoms_for_system(condition, metric=True)
        first_codes = (condition.uom1, condition.uom2, condition.uom3)
        self.assertEqual(first_codes, (UOM_M, UOM_M2, UOM_M3))
        first_quantities = compute_page_quantities(
            {condition.uid: condition}, [takeoff]
        )[condition.uid]
        # 120 in = 10 ft = 3.048 m; 20 sq ft = 1.8580608 m2; 5 cu ft = 0.14158423296 m3.
        expected_quantities = (3.048, 1.8580608, 0.14158423296)
        for actual, expected in zip(first_quantities, expected_quantities):
            self.assertAlmostEqual(actual, expected)
        for _iteration in range(3):
            normalize_condition_uoms_for_system(condition, metric=True)
        self.assertEqual((condition.uom1, condition.uom2, condition.uom3), first_codes)
        self.assertEqual(
            compute_page_quantities({condition.uid: condition}, [takeoff])[
                condition.uid
            ],
            first_quantities,
        )
