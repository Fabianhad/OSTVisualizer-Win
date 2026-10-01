import unittest
from ost_visualizer.infrastructure.mdb.components.overlay_rect import (
    EMPTY_OVERLAY_RECT,
    full_page_overlay_rect,
    parse_overlay_rect_storage,
    serialize_overlay_rect_storage,
)


class OverlayCoordinateContractTests(unittest.TestCase):
    def test_storage_text_parses_to_float_rect_and_zero_text_equals_empty_rect(self):
        self.assertEqual(
            parse_overlay_rect_storage("0,0,2688,1920"),
            (0.0, 0.0, 2688.0, 1920.0),
        )
        self.assertEqual(
            parse_overlay_rect_storage(" -1.5 , 2.25,10,20 "),
            (-1.5, 2.25, 10.0, 20.0),
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
        for stored_rect, message in (
            ("0,0,2688", "exactly four values"),
            ("0,0,2688,1920,extra", "exactly four values"),
            ("0,0,invalid,1920", "must be numeric"),
            ("0,0,,1920", "must be numeric"),
            ("*,0,10,10", "must be numeric"),
            ("0,0,-1,1920", "cannot be negative"),
            ("0,0,1920,-1", "cannot be negative"),
            ("0,0,nan,1920", "must be finite"),
            ("0,0,inf,1920", "must be finite"),
            ("-inf,0,10,10", "must be finite"),
        ):
            with self.subTest(stored_rect=stored_rect):
                with self.assertRaisesRegex(ValueError, message):
                    parse_overlay_rect_storage(stored_rect)

    def test_serialized_rect_uses_six_decimals_and_rejects_invalid_geometry(self):
        self.assertEqual(
            serialize_overlay_rect_storage((-1.1031464, 0, 2686.1614, 1919.5)),
            "-1.103146,0.000000,2686.161400,1919.500000",
        )
        self.assertEqual(
            parse_overlay_rect_storage(
                serialize_overlay_rect_storage((-1.103146, 2.5, 10.25, 20.5))
            ),
            (-1.103146, 2.5, 10.25, 20.5),
        )
        for rect in ((0, 0, -1, 5), (0, 0, 5, -1), (0, 0, float("nan"), 5), (0, 0, 5)):
            with self.subTest(rect=rect):
                with self.assertRaises(ValueError):
                    serialize_overlay_rect_storage(rect)

    def test_full_page_rect_spans_page_in_calibrated_units_and_rejects_bad_inputs(self):
        self.assertEqual(
            full_page_overlay_rect(42.0, 30.0, 0.125, 12.0),
            "0.000000,0.000000,4032.000000,2880.000000",
        )
        for args in (
            (42.0, 30.0, 0.0, 12.0),
            (42.0, 30.0, -0.125, 12.0),
            (42.0, 30.0, 0.125, float("nan")),
            (0.0, 30.0, 0.125, 12.0),
            (42.0, -1.0, 0.125, 12.0),
            (float("inf"), 30.0, 0.125, 12.0),
        ):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    full_page_overlay_rect(*args)
