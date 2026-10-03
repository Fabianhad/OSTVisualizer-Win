import unittest
from ost_visualizer.domain.services.dimension_format_service import (
    MM_PER_INCH,
    display_to_inches,
    display_to_mm,
    inches_to_display,
    inches_to_mm,
    mm_to_display,
    mm_to_inches,
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
    convert_to_uom,
)


class UnitDimensionConversionContractTests(unittest.TestCase):
    def test_shared_unit_constant_preserves_scalar_conversion_precision(self):
        self.assertEqual(MM_PER_INCH, 25.4)
        for inches in (-1234.5, -1.0, 0.0, 1.0, 1234.5):
            with self.subTest(inches=inches):
                millimetres = inches * 25.4
                self.assertEqual(inches_to_mm(inches), millimetres)
                self.assertEqual(mm_to_inches(millimetres), inches)
                self.assertIsInstance(inches_to_mm(int(inches)), float)
        # Literal anchors, independent of any multiplication in the test itself.
        self.assertEqual(inches_to_mm(1.0), 25.4)
        self.assertAlmostEqual(inches_to_mm(1234.5), 31356.3)
        self.assertEqual(mm_to_inches(25.4), 1.0)
        # One square/cubic inch in metres: 645.16 mm2 and 16387.064 mm3.
        self.assertAlmostEqual(convert_to_uom(1.0, UOM_M2), 0.00064516)
        self.assertAlmostEqual(convert_to_uom(1.0, UOM_M3), 0.000016387064)
        expected = {
            UOM_MM: 25.4,
            UOM_M: 0.0254,
            UOM_MM2: 25.4**2,
            UOM_M2: 25.4**2 / 1_000_000.0,
            UOM_MM3: 25.4**3,
            UOM_M3: 25.4**3 / 1_000_000_000.0,
        }
        for uom, converted in expected.items():
            with self.subTest(uom=uom):
                self.assertAlmostEqual(convert_to_uom(1.0, uom), converted)
                self.assertAlmostEqual(convert_to_uom(-1.0, uom), -converted)
