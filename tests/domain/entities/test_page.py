import unittest
from ost_visualizer.domain.entities.page import Page, build_pages_from_bid_data
from ost_visualizer.domain.entities.page_info import BidPageInfo

CALIBRATED_64_RECT = (-1.103146, 0.0, 2686.161423, 1919.474692)
CALIBRATED_96_RECT = (0.0, 0.0, 4031.370174, 2879.550124)


def _page(overlay_rect, **changes):
    values = dict(
        uid="page",
        name="Sheet",
        width_pts=3024.0,
        height_pts=2160.0,
        scale_factor1=0.1875,
        scale_factor2=12.0,
        overlay_rect=overlay_rect,
    )
    values.update(changes)
    return Page(**values)


class PagePreferenceTests(unittest.TestCase):
    def test_page_view_state_conversion_handles_invalid_page_dimensions(self):
        valid = Page(uid="valid", name="Valid", width_pts=72.0, height_pts=144.0)
        self.assertEqual(
            valid.ost_page_pixels_to_canvas_point(48.0, 96.0, 100.0, 200.0),
            (50.0, 100.0),
        )
        self.assertEqual(
            valid.canvas_point_to_ost_page_pixels(50.0, 100.0, 100.0, 200.0),
            (48.0, 96.0),
        )
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
                    folder_uid="folder-1",
                )
            },
            [],
        )
        self.assertEqual(pages["p1"].sequence, 12)
        self.assertEqual(pages["p1"].page_index, 0)
        self.assertEqual(
            (
                pages["p1"].uid,
                pages["p1"].name,
                pages["p1"].sheet_no,
                pages["p1"].folder_uid,
            ),
            ("p1", "A101", "S1", "folder-1"),
        )


class OverlayCoordinateContractTests(unittest.TestCase):
    def test_persisted_rect_converts_once_to_page_points(self):
        rect = _page(CALIBRATED_64_RECT).overlay_rect_page_points()
        self.assertAlmostEqual(rect[0], -1.24103925)
        self.assertAlmostEqual(rect[1], 0.0)
        self.assertAlmostEqual(rect[2], 3021.931600875)
        self.assertAlmostEqual(rect[3], 2159.4090285)

    def test_current_bid_uses_its_96_unit_page_calibration(self):
        rect = _page(
            CALIBRATED_96_RECT,
            scale_factor1=0.125,
            scale_factor2=12.0,
        ).overlay_rect_page_points()
        self.assertAlmostEqual(rect[0], 0.0)
        self.assertAlmostEqual(rect[1], 0.0)
        self.assertAlmostEqual(rect[2], 3023.5276305)
        self.assertAlmostEqual(rect[3], 2159.662593)

    def test_page_rotation_uses_effective_destination_dimensions_once(self):
        page = _page(
            (0.0, 0.0, 1920.0, 2688.0),
            width_pts=3024.0,
            height_pts=2160.0,
            rotation=90,
        )
        self.assertEqual(page.effective_width_pts, 2160.0)
        self.assertEqual(page.effective_height_pts, 3024.0)
        self.assertEqual(page.overlay_rect_page_points(), (0.0, 0.0, 2160.0, 3024.0))

    def test_nonuniform_scale_and_negative_offsets_are_preserved(self):
        page = _page((-64.0, -32.0, 1344.0, 1280.0))
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
                page = _page(
                    CALIBRATED_64_RECT,
                    width_pts=width_pts,
                    height_pts=height_pts,
                )
                self.assertIsNone(
                    page.ost_page_pixels_to_canvas_point(1.0, 1.0, 100.0, 100.0)
                )
                self.assertEqual(
                    page.overlay_rect_canvas(100.0, 100.0),
                    (0.0, 0.0, 0.0, 0.0),
                )
        page = _page(CALIBRATED_64_RECT)
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
        page = _page(CALIBRATED_64_RECT)
        delta = page.canvas_point_to_overlay_rect_units(
            72.0,
            36.0,
            3024.0,
            2160.0,
        )
        self.assertEqual(delta, (64.0, 32.0))

    def test_overlay_move_uses_current_page_calibration(self):
        page = _page(
            CALIBRATED_96_RECT,
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
