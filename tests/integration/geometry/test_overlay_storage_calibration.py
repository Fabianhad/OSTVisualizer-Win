import unittest
from ost_visualizer.domain.entities.overlay import overlay_units_per_sheet_inch
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.infrastructure.mdb.components.overlay_rect import (
    EMPTY_OVERLAY_RECT,
    full_page_overlay_rect,
    parse_overlay_rect_storage,
)
from tests.integration.geometry.overlay_calibration_support import (
    CALIBRATED_64_RECT as _overlay_calibration_support_CALIBRATED_64_RECT,
    _page as _overlay_calibration_support__page,
)


class OverlayCoordinateContractTests(unittest.TestCase):
    def test_overlay_units_follow_persisted_page_calibration(self):
        self.assertEqual(overlay_units_per_sheet_inch(0.1875, 12.0), 64.0)
        self.assertEqual(overlay_units_per_sheet_inch(0.125, 12.0), 96.0)
        self.assertEqual(overlay_units_per_sheet_inch(0.3, 15.0), 50.0)
        self.assertEqual(
            full_page_overlay_rect(42.0, 30.0, 0.1875, 12.0),
            "0.000000,0.000000,2688.000000,1920.000000",
        )
        self.assertEqual(
            full_page_overlay_rect(42.0, 30.0, 0.125, 12.0),
            "0.000000,0.000000,4032.000000,2880.000000",
        )

    def test_different_page_dimensions_preserve_full_page_size(self):
        rect = parse_overlay_rect_storage(
            full_page_overlay_rect(11.0, 8.5, 0.125, 12.0)
        )
        page = _overlay_calibration_support__page(
            rect,
            width_pts=792.0,
            height_pts=612.0,
            scale_factor1=0.125,
            scale_factor2=12.0,
        )
        self.assertEqual(page.overlay_rect_page_points(), (0.0, 0.0, 792.0, 612.0))

    def test_arbitrary_calibration_uses_the_same_full_page_path(self):
        rect = parse_overlay_rect_storage(full_page_overlay_rect(10.0, 5.0, 0.3, 15.0))
        page = _overlay_calibration_support__page(
            rect,
            width_pts=720.0,
            height_pts=360.0,
            scale_factor1=0.3,
            scale_factor2=15.0,
        )
        self.assertEqual(page.overlay_rect_page_points(), (0.0, 0.0, 720.0, 360.0))

    def test_invalid_calibration_produces_no_geometry_or_full_page_rect(self):
        for scale_factor1, scale_factor2 in (
            (0.0, 12.0),
            (0.125, 0.0),
            (-0.125, 12.0),
            (0.125, -12.0),
            (float("nan"), 12.0),
            (0.125, float("inf")),
            ("invalid", 12.0),
        ):
            with self.subTest(
                scale_factor1=scale_factor1,
                scale_factor2=scale_factor2,
            ):
                self.assertIsNone(
                    overlay_units_per_sheet_inch(scale_factor1, scale_factor2)
                )
                page = _overlay_calibration_support__page(
                    _overlay_calibration_support_CALIBRATED_64_RECT,
                    scale_factor1=scale_factor1,
                    scale_factor2=scale_factor2,
                )
                self.assertEqual(
                    page.overlay_rect_page_points(),
                    EMPTY_OVERLAY_RECT,
                )
                with self.assertRaises(ValueError):
                    full_page_overlay_rect(
                        42.0,
                        30.0,
                        scale_factor1,
                        scale_factor2,
                    )
