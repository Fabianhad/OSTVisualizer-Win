import math
import unittest
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.services.uom_service import (
    CALC_LINEAR_LENGTH,
    UOM_INCHES,
    calculate_condition_quantities,
)
from ost_visualizer.domain.services.uom_service import (
    UOM_SQUARE_FEET,
    calculate_condition_quantities,
)


class UomServiceTests(unittest.TestCase):
    def test_axis_aligned_circular_curve_uses_its_arc_length(self):
        quantity, _quantity2, _quantity3 = calculate_condition_quantities(
            condition_type=Condition.TYPE_LINEAR,
            calc_type1=CALC_LINEAR_LENGTH,
            calc_type2=0,
            calc_type3=0,
            uom1=UOM_INCHES,
            uom2=UOM_INCHES,
            uom3=UOM_INCHES,
            width=0.0,
            height=0.0,
            depth=0.0,
            thickness=0.0,
            position=[1.0, 0.0, 0.0, 1.0, 1.0, 1.0],
            curve=0,
        )
        self.assertAlmostEqual(quantity, math.pi / math.sqrt(2.0), delta=0.03)


class AreaSlopeBehaviorTests(unittest.TestCase):
    def test_area_quantity_retains_fractional_origin_precision(self):
        q1, _q2, _q3 = calculate_condition_quantities(
            Condition.TYPE_AREA,
            11,
            0,
            0,
            UOM_SQUARE_FEET,
            0,
            0,
            width=0,
            height=0,
            depth=0,
            thickness=0,
            position=[
                891.672,
                507.397,
                435.672,
                507.397,
                435.672,
                860.397,
                593.672,
                860.397,
                593.672,
                702.397,
                893.672,
                702.397,
            ],
        )
        self.assertAlmostEqual(q1, 792.2152777777782, places=10)

    def test_area_quantity_uses_absolute_slope_magnitude(self):
        q1, _q2, _q3 = calculate_condition_quantities(
            Condition.TYPE_AREA,
            11,
            0,
            0,
            UOM_SQUARE_FEET,
            0,
            0,
            width=0,
            height=0,
            depth=0,
            thickness=0,
            position=[0, 0, 120, 0, 120, 120, 0, 120],
            rise=-3,
            run=4,
        )
        self.assertAlmostEqual(q1, 125.0)
