import unittest
from ost_visualizer.infrastructure.mdb.components.overlay_rect import (
    EMPTY_OVERLAY_RECT,
    full_page_overlay_rect,
    overlay_path_storage_identity,
    replacement_overlay_storage_values,
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
                with self.assertRaisesRegex(ValueError, message + "$"):
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


class OverlayStorageIdentityAndReplacementTests(unittest.TestCase):
    def test_blank_paths_have_an_empty_identity(self):
        for path in (None, "", 0):
            with self.subTest(path=path):
                self.assertEqual(overlay_path_storage_identity(path), "")

    def test_path_identity_ignores_case_separator_style_and_dot_segments(self):
        expected = "dir\\sub\\file.pdf"
        for path in (
            "Dir/Sub/File.PDF",
            "dir\\sub\\file.pdf",
            "DIR\\\\Sub/./File.Pdf",
            "dir\\other\\..\\sub\\file.pdf",
        ):
            with self.subTest(path=path):
                self.assertEqual(overlay_path_storage_identity(path), expected)
        self.assertNotEqual(
            overlay_path_storage_identity("dir/a.pdf"),
            overlay_path_storage_identity("dir/b.pdf"),
        )

    def test_page_dimensions_must_be_finite_and_positive_with_a_specific_reason(self):
        for args, message in (
            ((float("inf"), 30.0, 0.125, 12.0), "Page dimensions must be finite"),
            ((42.0, float("nan"), 0.125, 12.0), "Page dimensions must be finite"),
            ((0.0, 30.0, 0.125, 12.0), "Page dimensions must be positive"),
            ((42.0, 0.0, 0.125, 12.0), "Page dimensions must be positive"),
            ((-1.0, 30.0, 0.125, 12.0), "Page dimensions must be positive"),
            (
                (42.0, 30.0, 0.0, 12.0),
                "Overlay calibration must contain finite positive values",
            ),
        ):
            with self.subTest(args=args):
                with self.assertRaisesRegex(ValueError, message + "$"):
                    full_page_overlay_rect(*args)

    def test_replacement_values_for_a_new_overlay_reset_placement_and_keep_the_show_mode(
        self,
    ):
        self.assertEqual(
            replacement_overlay_storage_values(
                "a/overlay.pdf", 42.0, 30.0, 0.125, 12.0, original_image_path="plan.pdf"
            ),
            {
                "OverlayImagePath": "a/overlay.pdf",
                "OverlayRect": "0.000000,0.000000,4032.000000,2880.000000",
                "OverlayOffsetX": 0.0,
                "OverlayOffsetY": 0.0,
                "OverlayRotation": 0.0,
                "OverlayResized": 0,
                "DeskewRotationOverlay": 0.0,
            },
        )

    def test_an_overlay_without_an_original_image_is_shown_alone(self):
        for original in ("", None):
            with self.subTest(original=original):
                values = replacement_overlay_storage_values(
                    "o.pdf", 42.0, 30.0, 0.125, 12.0, original_image_path=original
                )
                self.assertEqual(values["Show"], 1)
                self.assertEqual(values["OverlayImagePath"], "o.pdf")
                self.assertNotEqual(values["OverlayRect"], "")

    def test_removing_the_overlay_clears_geometry_and_hides_the_overlay_mode(self):
        for path in ("", None):
            with self.subTest(path=path):
                values = replacement_overlay_storage_values(
                    path, 42.0, 30.0, 0.125, 12.0, original_image_path="plan.pdf"
                )
                self.assertEqual(
                    values,
                    {
                        "OverlayImagePath": "",
                        "OverlayRect": "",
                        "OverlayOffsetX": 0.0,
                        "OverlayOffsetY": 0.0,
                        "OverlayRotation": 0.0,
                        "OverlayResized": 0,
                        "DeskewRotationOverlay": 0.0,
                        "Show": 0,
                    },
                )

    def test_pages_smaller_than_one_inch_still_produce_a_rectangle(self):
        self.assertEqual(
            full_page_overlay_rect(0.5, 0.5, 0.125, 12.0),
            "0.000000,0.000000,48.000000,48.000000",
        )
        self.assertEqual(
            full_page_overlay_rect(1.0, 0.25, 0.125, 12.0),
            "0.000000,0.000000,96.000000,24.000000",
        )
        self.assertEqual(
            full_page_overlay_rect(0.25, 1.0, 0.125, 12.0),
            "0.000000,0.000000,24.000000,96.000000",
        )


class OverlayDecimalPageSizeTests(unittest.TestCase):
    def test_page_sizes_reported_as_decimals_or_text_are_converted_to_floats(self):
        from decimal import Decimal

        expected = "0.000000,0.000000,4032.000000,2880.000000"
        for width, height in (
            (Decimal("42.0"), Decimal("30")),
            ("42", "30"),
            (42, 30),
        ):
            with self.subTest(width=width):
                self.assertEqual(
                    full_page_overlay_rect(width, height, 0.125, 12.0), expected
                )
