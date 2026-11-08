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


class OverlayErrorContractTests(unittest.TestCase):
    """The validation messages are user-facing: match them exactly, not by substring."""

    def _message(self, function, *args):
        with self.assertRaises(ValueError) as raised:
            function(*args)
        return raised.exception

    def test_rect_validation_messages_are_exact(self):
        for function, args, message in (
            (
                parse_overlay_rect_storage,
                ("0,0,2688",),
                "OverlayRect must contain exactly four values",
            ),
            (
                parse_overlay_rect_storage,
                ("0,0,x,1",),
                "OverlayRect values must be numeric",
            ),
            (
                parse_overlay_rect_storage,
                ("0,0,nan,1",),
                "OverlayRect values must be finite",
            ),
            (
                parse_overlay_rect_storage,
                ("0,0,-1,1",),
                "OverlayRect width and height cannot be negative",
            ),
            (
                serialize_overlay_rect_storage,
                ((0, 0, 1),),
                "OverlayRect must contain exactly four values",
            ),
            (
                serialize_overlay_rect_storage,
                ((0, 0, "x", 1),),
                "OverlayRect values must be numeric",
            ),
            (
                serialize_overlay_rect_storage,
                ((0, 0, float("inf"), 1),),
                "OverlayRect values must be finite",
            ),
            (
                serialize_overlay_rect_storage,
                ((0, 0, 1, -1),),
                "OverlayRect width and height cannot be negative",
            ),
        ):
            with self.subTest(function=function.__name__, args=args):
                self.assertEqual(str(self._message(function, *args)), message)

    def test_full_page_validation_messages_are_exact(self):
        for args, message in (
            (
                (42.0, 30.0, 0.0, 12.0),
                "Overlay calibration must contain finite positive values",
            ),
            ((float("nan"), 30.0, 0.125, 12.0), "Page dimensions must be finite"),
            ((42.0, float("inf"), 0.125, 12.0), "Page dimensions must be finite"),
            ((0.0, 30.0, 0.125, 12.0), "Page dimensions must be positive"),
            ((42.0, -2.0, 0.125, 12.0), "Page dimensions must be positive"),
        ):
            with self.subTest(args=args):
                self.assertEqual(
                    str(self._message(full_page_overlay_rect, *args)), message
                )

    def test_a_non_numeric_value_keeps_the_original_conversion_error_as_its_cause(
        self,
    ):
        parse_error = self._message(parse_overlay_rect_storage, "0,0,invalid,1920")
        self.assertIsInstance(parse_error.__cause__, ValueError)
        # None is not convertible at all (TypeError), still reported as "numeric".
        serialize_error = self._message(serialize_overlay_rect_storage, (0, 0, None, 5))
        self.assertEqual(str(serialize_error), "OverlayRect values must be numeric")
        self.assertIsInstance(serialize_error.__cause__, TypeError)

    def test_non_string_paths_are_converted_to_text(self):
        class _Named:
            def __str__(self):
                return "Dir/Sub/File.PDF"

        self.assertEqual(overlay_path_storage_identity(_Named()), "dir\\sub\\file.pdf")
        self.assertEqual(overlay_path_storage_identity(42), "42")
        values = replacement_overlay_storage_values(
            _Named(), 42.0, 30.0, 0.125, 12.0, original_image_path="plan.pdf"
        )
        self.assertIs(type(values["OverlayImagePath"]), str)
        self.assertEqual(values["OverlayImagePath"], "Dir/Sub/File.PDF")


class OverlayConversionAndShowTypeTests(unittest.TestCase):
    def test_an_unexpected_error_from_float_conversion_propagates_unchanged(self):
        class _Unconvertible:
            def __float__(self):
                raise RuntimeError("boom")

        with self.assertRaisesRegex(RuntimeError, "^boom$"):
            serialize_overlay_rect_storage((0, 0, _Unconvertible(), 1))
        with self.assertRaisesRegex(RuntimeError, "^boom$"):
            full_page_overlay_rect(_Unconvertible(), 30.0, 0.125, 12.0)

    def test_an_int_too_large_for_float_is_rejected_like_other_unusable_numbers(self):
        huge = 10**400
        with self.assertRaisesRegex(ValueError, "^OverlayRect values must be numeric$"):
            serialize_overlay_rect_storage((huge, 0, 10, 1))
        with self.assertRaisesRegex(ValueError, "^OverlayRect values must be numeric$"):
            serialize_overlay_rect_storage((0, 0, 10, -huge))
        with self.assertRaisesRegex(
            ValueError, "^OverlayRect values must be numeric$"
        ) as raised:
            serialize_overlay_rect_storage((0, 0, huge, 1))
        self.assertIsInstance(raised.exception.__cause__, OverflowError)
        for width, height in ((huge, 30.0), (42.0, huge), (-huge, 30.0)):
            with self.assertRaisesRegex(
                ValueError, "^Page dimensions must be finite$"
            ) as raised:
                full_page_overlay_rect(width, height, 0.125, 12.0)
            self.assertIsInstance(raised.exception.__cause__, OverflowError)

    def test_characterisation_a_non_numeric_page_dimension_leaks_the_raw_error(self):
        # CHARACTERISATION of current behaviour, not an endorsement (owner question:
        # should these become ValueError like in serialize_overlay_rect_storage?).
        # Only OverflowError is converted in full_page_overlay_rect.
        with self.assertRaises(TypeError):
            full_page_overlay_rect(None, 30.0, 0.125, 12.0)
        with self.assertRaises(TypeError):
            full_page_overlay_rect(42.0, None, 0.125, 12.0)
        with self.assertRaises(ValueError) as raised:
            full_page_overlay_rect("abc", 30.0, 0.125, 12.0)
        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn("Page dimensions", str(raised.exception))
        with self.assertRaises(ValueError) as raised:
            full_page_overlay_rect(42.0, "abc", 0.125, 12.0)
        self.assertNotIn("Page dimensions", str(raised.exception))

    def test_an_oversized_number_in_stored_text_is_rejected_as_not_finite(self):
        # float("1" * 400) is inf (no OverflowError for text), so the finite check applies.
        with self.assertRaisesRegex(ValueError, "must be finite"):
            parse_overlay_rect_storage("0,0," + "1" * 400 + ",1")

    def test_show_is_a_real_int_because_a_bool_is_stored_as_minus_one_by_access(self):
        shown_alone = replacement_overlay_storage_values(
            "o.pdf", 42.0, 30.0, 0.125, 12.0, original_image_path=""
        )
        hidden = replacement_overlay_storage_values(
            "", 42.0, 30.0, 0.125, 12.0, original_image_path="plan.pdf"
        )
        self.assertIs(type(shown_alone["Show"]), int)
        self.assertEqual(shown_alone["Show"], 1)
        self.assertIs(type(hidden["Show"]), int)
        self.assertEqual(hidden["Show"], 0)


class OverlayPartStrippingCharacterisationTests(unittest.TestCase):
    def test_characterisation_each_part_is_stripped_with_str_strip_semantics(self):
        # CHARACTERISATION: control separators (U+001C..U+001F) are never stored in
        # practice. str.strip removes them although float() alone rejects them, so
        # this pins that every comma-separated part is stripped before conversion.
        self.assertEqual(
            parse_overlay_rect_storage("0,\x1f0,10\x1d,\x1e10"),
            (0.0, 0.0, 10.0, 10.0),
        )
        self.assertEqual(
            parse_overlay_rect_storage("1,\x1c2.5\x1f,3,\x1d4"),
            (1.0, 2.5, 3.0, 4.0),
        )
