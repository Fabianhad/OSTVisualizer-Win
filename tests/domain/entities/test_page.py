import os
import unittest
from pathlib import Path
from ost_visualizer.domain.entities.page import Page, build_pages_from_bid_data
from ost_visualizer.domain.entities.page_info import BidPageInfo
from PySide6 import QtCore, QtGui, QtWidgets
from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.infrastructure.mdb.components.overlay_rect import (
    EMPTY_OVERLAY_RECT,
    full_page_overlay_rect,
    parse_overlay_rect_storage,
)
from tests.integration.geometry.overlay_calibration_support import (
    CALIBRATED_64_RECT as _overlay_calibration_support_CALIBRATED_64_RECT,
    CALIBRATED_96_RECT as _overlay_calibration_support_CALIBRATED_96_RECT,
    _page as _overlay_calibration_support__page,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class PagePreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_page_view_state_conversion_handles_invalid_page_dimensions(self):
        page = Page(uid="bad", name="Bad Page", width_pts=0.0, height_pts=100.0)
        self.assertIsNone(
            page.ost_page_pixels_to_canvas_point(10.0, 20.0, 100.0, 100.0)
        )
        self.assertIsNone(
            page.canvas_point_to_ost_page_pixels(10.0, 20.0, 100.0, 100.0)
        )
        self.assertEqual(
            page.overlay_rect_canvas(100.0, 100.0),
            (0.0, 0.0, 0.0, 0.0),
        )

    def test_bid_page_info_sequence_populates_page_label_source(self):
        pages = build_pages_from_bid_data(
            {
                "p1": BidPageInfo(
                    name="A101",
                    sheet_no="S1",
                    sequence=12,
                    page_index=0,
                )
            },
            [],
        )
        self.assertEqual(pages["p1"].sequence, 12)
        self.assertEqual(pages["p1"].page_index, 0)


class OverlayCoordinateContractTests(unittest.TestCase):
    def test_persisted_rect_converts_once_to_page_points(self):
        rect = _overlay_calibration_support__page(
            _overlay_calibration_support_CALIBRATED_64_RECT
        ).overlay_rect_page_points()
        self.assertAlmostEqual(rect[0], -1.24103925)
        self.assertAlmostEqual(rect[1], 0.0)
        self.assertAlmostEqual(rect[2], 3021.931600875)
        self.assertAlmostEqual(rect[3], 2159.4090285)

    def test_current_bid_uses_its_96_unit_page_calibration(self):
        rect = _overlay_calibration_support__page(
            _overlay_calibration_support_CALIBRATED_96_RECT,
            scale_factor1=0.125,
            scale_factor2=12.0,
        ).overlay_rect_page_points()
        self.assertAlmostEqual(rect[0], 0.0)
        self.assertAlmostEqual(rect[1], 0.0)
        self.assertAlmostEqual(rect[2], 3023.5276305)
        self.assertAlmostEqual(rect[3], 2159.662593)

    def test_page_rotation_uses_effective_destination_dimensions_once(self):
        page = _overlay_calibration_support__page(
            (0.0, 0.0, 1920.0, 2688.0),
            width_pts=3024.0,
            height_pts=2160.0,
            rotation=90,
        )
        self.assertEqual(page.effective_width_pts, 2160.0)
        self.assertEqual(page.effective_height_pts, 3024.0)
        self.assertEqual(page.overlay_rect_page_points(), (0.0, 0.0, 2160.0, 3024.0))

    def test_nonuniform_scale_and_negative_offsets_are_preserved(self):
        page = _overlay_calibration_support__page((-64.0, -32.0, 1344.0, 1280.0))
        self.assertEqual(
            page.overlay_rect_page_points(),
            (-72.0, -36.0, 1512.0, 1440.0),
        )

    def test_non_finite_page_conversion_inputs_produce_no_geometry(self):
        for width_pts, height_pts in (
            (float("nan"), 2160.0),
            (3024.0, float("inf")),
        ):
            with self.subTest(width_pts=width_pts, height_pts=height_pts):
                page = _overlay_calibration_support__page(
                    _overlay_calibration_support_CALIBRATED_64_RECT,
                    width_pts=width_pts,
                    height_pts=height_pts,
                )
                self.assertIsNone(
                    page.ost_page_pixels_to_canvas_point(1.0, 1.0, 100.0, 100.0)
                )
                self.assertEqual(
                    page.overlay_rect_canvas(100.0, 100.0),
                    EMPTY_OVERLAY_RECT,
                )
        page = _overlay_calibration_support__page(
            _overlay_calibration_support_CALIBRATED_64_RECT
        )
        for invalid in (float("nan"), float("inf")):
            with self.subTest(canvas_dimension=invalid):
                self.assertIsNone(
                    page.canvas_point_to_overlay_rect_units(
                        1.0,
                        1.0,
                        invalid,
                        100.0,
                    )
                )
            with self.subTest(point_coordinate=invalid):
                self.assertIsNone(
                    page.canvas_point_to_ost_page_pixels(
                        invalid,
                        1.0,
                        100.0,
                        100.0,
                    )
                )

    def test_overlay_move_delta_is_saved_in_calibrated_units(self):
        page = _overlay_calibration_support__page(
            _overlay_calibration_support_CALIBRATED_64_RECT
        )
        delta = page.canvas_point_to_overlay_rect_units(
            72.0,
            36.0,
            3024.0,
            2160.0,
        )
        self.assertEqual(delta, (64.0, 32.0))

    def test_overlay_move_uses_current_page_calibration(self):
        page = _overlay_calibration_support__page(
            _overlay_calibration_support_CALIBRATED_96_RECT,
            scale_factor1=0.125,
            scale_factor2=12.0,
        )
        delta = page.canvas_point_to_overlay_rect_units(
            72.0,
            36.0,
            3024.0,
            2160.0,
        )
        self.assertEqual(delta, (96.0, 48.0))
