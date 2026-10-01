import unittest
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)


class CanonicalCoordinateValidationTests(unittest.TestCase):
    def test_canonical_coordinate_transform_rejects_invalid_page_contracts(self):
        valid = {
            "width": 600.0,
            "height": 800.0,
            "scale_factor1": 1.0,
            "scale_factor2": 72.0,
            "rotation": 0,
            "flip_x": False,
            "flip_y": False,
        }
        # Ratio 72 maps OST units to points 1:1; PDF Y starts at the lower edge.
        self.assertEqual(
            OSTCoordinateSystem.ost_to_pdf_coordinates([100.0, 200.0], valid),
            [[100.0, 600.0]],
        )
        for overrides in (
            {"width": 0.0},
            {"height": float("nan")},
            {"scale_factor1": 0.0},
            {"scale_factor2": float("inf")},
            {"rotation": 45},
        ):
            with self.subTest(overrides=overrides):
                page_info = {**valid, **overrides}
                with self.assertRaises(ValueError):
                    OSTCoordinateSystem.ost_to_pdf_coordinates(
                        [100.0, 200.0], page_info
                    )
