import unittest
from ost_visualizer.infrastructure.mdb.components.overlay_rect import (
    EMPTY_OVERLAY_RECT,
    full_page_overlay_rect,
    parse_overlay_rect_storage,
)


class OverlayCoordinateContractTests(unittest.TestCase):
    def test_numeric_and_string_zero_parse_identically(self):
        self.assertEqual(
            parse_overlay_rect_storage("0,0,2688,1920"),
            (0.0, 0.0, 2688.0, 1920.0),
        )
        self.assertEqual(
            parse_overlay_rect_storage("0.0,0.0,0.0,0.0"),
            EMPTY_OVERLAY_RECT,
        )

    def test_absent_storage_values_produce_no_geometry(self):
        for stored_rect in (None, "", "  ", "*", " * "):
            with self.subTest(stored_rect=stored_rect):
                self.assertEqual(
                    parse_overlay_rect_storage(stored_rect),
                    EMPTY_OVERLAY_RECT,
                )

    def test_malformed_storage_rect_is_rejected_without_inference(self):
        for stored_rect in (
            "0,0,2688",
            "0,0,2688,1920,extra",
            "0,0,invalid,1920",
            "0,0,-1,1920",
            "0,0,nan,1920",
        ):
            with self.subTest(stored_rect=stored_rect):
                with self.assertRaises(ValueError):
                    parse_overlay_rect_storage(stored_rect)
