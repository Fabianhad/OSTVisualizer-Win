import unittest
from ost_visualizer.application.utils.quantity_display import (
    format_quantity_number,
    format_quantity_with_uom,
)
from ost_visualizer.domain.services.uom_service import (
    UOM_CUBIC_YARDS,
    UOM_LINEAR_FEET,
    UOM_M,
    UOM_M2,
    UOM_M3,
    UOM_MM,
    UOM_MM2,
    UOM_MM3,
)


class QuantityDisplayFormattingTests(unittest.TestCase):
    def test_quantity_display_facade_replacement_preserves_exact_formatting(self):
        cases = (
            (0.0, UOM_LINEAR_FEET, ""),
            (12.4, UOM_LINEAR_FEET, "12"),
            (12.6, UOM_LINEAR_FEET, "13"),
            (-12.6, UOM_LINEAR_FEET, "-13"),
            (12.345, UOM_M, "12.35"),
            (-12.345, UOM_M, "-12.35"),
            (100.0, UOM_M, "100"),
            (1234.0, UOM_CUBIC_YARDS, "1,234"),
        )
        for value, uom, expected in cases:
            with self.subTest(value=value, uom=uom):
                self.assertEqual(format_quantity_number(value, uom), expected)
        labels = {UOM_LINEAR_FEET: "LF", UOM_M: "M"}
        label = labels.get
        self.assertEqual(format_quantity_with_uom(0.0, UOM_LINEAR_FEET, label), "0 LF")
        self.assertEqual(format_quantity_with_uom(12.345, UOM_M, label), "12.35 M")
        self.assertEqual(format_quantity_with_uom(-12.6, 999, label), "-13")

    def test_all_metric_dimensions_share_precision_and_absolute_threshold(self):
        for uom in (UOM_M, UOM_M2, UOM_M3, UOM_MM, UOM_MM2, UOM_MM3):
            for value, expected in (
                (12.345, "12.35"),
                (-12.345, "-12.35"),
                (99.99, "99.99"),
                (-99.99, "-99.99"),
                (100.0, "100"),
                (-100.0, "-100"),
                (1234.6, "1,235"),
            ):
                with self.subTest(uom=uom, value=value):
                    self.assertEqual(format_quantity_number(value, uom), expected)

    def test_zero_placeholder_and_missing_label_do_not_invent_units(self):
        for value in (0.0, -0.0):
            with self.subTest(value=value):
                self.assertEqual(
                    format_quantity_number(value, UOM_M, zero_text="none"), "none"
                )
                self.assertEqual(format_quantity_with_uom(value, 999, {}.get), "")
