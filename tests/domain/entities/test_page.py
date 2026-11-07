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


class PageEntityDefaultsTests(unittest.TestCase):
    def test_defaults_describe_a_blank_unrotated_unit_scale_visible_page(self):
        page = Page(uid="p", name="N")
        self.assertEqual(
            (
                page.sheet_no,
                page.sequence,
                page.takeoffs,
                page.folder_uid,
                page.image_path,
                page.width_pts,
                page.height_pts,
                page.scale_factor1,
                page.scale_factor2,
                page.rotation,
                page.flip_x,
                page.flip_y,
                page.page_index,
                page.layer_visible,
            ),
            ("", 0, [], None, None, 0.0, 0.0, 1.0, 1.0, 0, False, False, 0, True),
        )
        self.assertEqual(
            (
                page.overlay_image_path,
                page.overlay_offset_x,
                page.overlay_offset_y,
                page.overlay_rotation,
                page.overlay_resized,
                page.deskew_rotation_overlay,
                page.overlay_rect,
                page.image_show_mode,
                page.zoom_fac,
                page.current_x,
                page.current_y,
                page.invert,
                page.bitonal,
            ),
            (
                None,
                0.0,
                0.0,
                0.0,
                False,
                0.0,
                (0.0, 0.0, 0.0, 0.0),
                0,
                0.0,
                0.0,
                0.0,
                False,
                False,
            ),
        )
        page.takeoffs.append(object())
        self.assertEqual(Page(uid="q", name="Q").takeoffs, [])

    def test_image_and_overlay_flags_are_real_booleans(self):
        self.assertIs(Page(uid="p", name="N").has_image, False)
        self.assertIs(Page(uid="p", name="N", image_path="").has_image, False)
        self.assertIs(Page(uid="p", name="N", image_path="a.pdf").has_image, True)
        self.assertIs(Page(uid="p", name="N").has_overlay, False)
        self.assertIs(Page(uid="p", name="N", overlay_image_path="").has_overlay, False)
        self.assertIs(
            Page(uid="p", name="N", overlay_image_path="o.tif").has_overlay, True
        )

    def test_only_quarter_turns_of_90_and_270_swap_the_effective_dimensions(self):
        for rotation, swapped in (
            (0, False),
            (90, True),
            (180, False),
            (270, True),
            (45, False),
            (271, False),
            (89, False),
        ):
            with self.subTest(rotation=rotation):
                page = Page(
                    uid="p",
                    name="N",
                    width_pts=100.0,
                    height_pts=40.0,
                    rotation=rotation,
                )
                self.assertEqual(
                    (page.effective_width_pts, page.effective_height_pts),
                    (40.0, 100.0) if swapped else (100.0, 40.0),
                )

    def test_overlay_units_per_sheet_inch_uses_the_scale_ratio(self):
        self.assertEqual(
            Page(
                uid="p", name="N", scale_factor1=0.125, scale_factor2=12.0
            ).overlay_units_per_sheet_inch,
            96.0,
        )
        self.assertIsNone(
            Page(uid="p", name="N", scale_factor1=0.0).overlay_units_per_sheet_inch
        )


class PageCoordinateConversionTests(unittest.TestCase):
    def page(self, **changes):
        values = dict(
            uid="p",
            name="N",
            width_pts=72.0,
            height_pts=144.0,
            scale_factor1=1.0,
            scale_factor2=96.0,
        )
        values.update(changes)
        return Page(**values)

    METHODS = (
        "ost_page_pixels_to_canvas_point",
        "canvas_point_to_ost_page_pixels",
        "overlay_rect_units_to_canvas_point",
        "canvas_point_to_overlay_rect_units",
    )

    def test_each_conversion_uses_its_own_unit_system(self):
        # Page is 72 x 144 pt: 96 x 192 OST page pixels, and (ratio 96) 96 x 192 overlay units.
        page = self.page(scale_factor1=1.0, scale_factor2=192.0)
        self.assertEqual(
            page.ost_page_pixels_to_canvas_point(48.0, 96.0, 100.0, 200.0),
            (50.0, 100.0),
        )
        self.assertEqual(
            page.canvas_point_to_ost_page_pixels(50.0, 100.0, 100.0, 200.0),
            (48.0, 96.0),
        )
        # With a 192 units-per-inch overlay calibration the page spans 192 x 384 units.
        self.assertEqual(
            page.overlay_rect_units_to_canvas_point(96.0, 192.0, 100.0, 200.0),
            (50.0, 100.0),
        )
        self.assertEqual(
            page.canvas_point_to_overlay_rect_units(50.0, 100.0, 100.0, 200.0),
            (96.0, 192.0),
        )

    def test_each_conversion_scales_x_and_y_independently_and_keeps_the_sign(self):
        page = self.page()
        for method in self.METHODS:
            with self.subTest(method=method):
                convert = getattr(page, method)
                x_only = convert(10.0, 0.0, 200.0, 50.0)
                y_only = convert(0.0, 10.0, 200.0, 50.0)
                self.assertEqual(x_only[1], 0.0)
                self.assertEqual(y_only[0], 0.0)
                negative = convert(-10.0, -10.0, 200.0, 50.0)
                self.assertEqual(negative, (-x_only[0], -y_only[1]))
                self.assertNotEqual(x_only[0], y_only[1])

    def test_conversions_round_trip(self):
        page = self.page(scale_factor1=0.25, scale_factor2=24.0)
        for forward, back in (
            ("ost_page_pixels_to_canvas_point", "canvas_point_to_ost_page_pixels"),
            (
                "overlay_rect_units_to_canvas_point",
                "canvas_point_to_overlay_rect_units",
            ),
        ):
            point = getattr(page, forward)(33.0, 17.0, 800.0, 600.0)
            x, y = getattr(page, back)(*point, 800.0, 600.0)
            self.assertAlmostEqual(x, 33.0)
            self.assertAlmostEqual(y, 17.0)

    def test_invalid_canvas_sizes_and_points_produce_no_point(self):
        page = self.page()
        nan, inf = float("nan"), float("inf")
        for method in self.METHODS:
            convert = getattr(page, method)
            for canvas in (
                (0, 10),
                (10, 0),
                (-1, 10),
                (10, -1),
                (nan, 10),
                (10, nan),
                (inf, 10),
                (10, inf),
                ("x", 10),
                (10, None),
            ):
                with self.subTest(method=method, canvas=canvas):
                    self.assertIsNone(convert(1.0, 1.0, *canvas))
            for point in (
                (nan, 1.0),
                (1.0, nan),
                (inf, 1.0),
                (1.0, -inf),
                ("x", 1.0),
                (1.0, None),
            ):
                with self.subTest(method=method, point=point):
                    self.assertIsNone(convert(*point, 10.0, 10.0))
            self.assertIsNotNone(convert("1.5", "2", "10", "10"))

    def test_degenerate_pages_and_calibrations_produce_no_point(self):
        nan, inf = float("nan"), float("inf")
        for changes in (
            dict(width_pts=0.0),
            dict(height_pts=0.0),
            dict(width_pts=-1.0),
            dict(height_pts=-1.0),
            dict(width_pts=nan),
            dict(height_pts=inf),
        ):
            page = self.page(**changes)
            for method in self.METHODS:
                with self.subTest(changes=changes, method=method):
                    self.assertIsNone(getattr(page, method)(1.0, 1.0, 10.0, 10.0))
        for changes in (
            dict(scale_factor1=0.0),
            dict(scale_factor1=-1.0),
            dict(scale_factor2=0.0),
            dict(scale_factor2=-5.0),
        ):
            page = self.page(**changes)
            self.assertIsNone(
                page.overlay_rect_units_to_canvas_point(1.0, 1.0, 10.0, 10.0)
            )
            self.assertIsNone(
                page.canvas_point_to_overlay_rect_units(1.0, 1.0, 10.0, 10.0)
            )
            self.assertIsNotNone(
                page.ost_page_pixels_to_canvas_point(1.0, 1.0, 10.0, 10.0)
            )

    def test_tiny_but_positive_sizes_are_valid(self):
        page = self.page(width_pts=0.5, height_pts=0.25)
        self.assertIsNotNone(page.ost_page_pixels_to_canvas_point(0.1, 0.1, 0.5, 0.5))
        self.assertIsNotNone(
            self.page().ost_page_pixels_to_canvas_point(0.1, 0.1, 0.5, 0.25)
        )

    def test_overlay_rect_canvas_converts_origin_and_size_and_degrades_to_zeros(self):
        page = self.page(
            scale_factor1=1.0,
            scale_factor2=192.0,
            overlay_rect=(96.0, 192.0, 192.0, 384.0),
        )
        self.assertEqual(
            page.overlay_rect_canvas(100.0, 200.0), (50.0, 100.0, 100.0, 200.0)
        )
        self.assertEqual(page.overlay_rect_page_points(), (36.0, 72.0, 72.0, 144.0))
        page.overlay_rect = (1.0, 2.0)
        self.assertEqual(page.overlay_rect_canvas(100.0, 200.0), (0.0, 0.0, 0.0, 0.0))
        page.overlay_rect = ("x", 2.0, 3.0, 4.0)
        self.assertEqual(page.overlay_rect_canvas(100.0, 200.0), (0.0, 0.0, 0.0, 0.0))
        page.overlay_rect = (1.0, 2.0, float("nan"), 4.0)
        self.assertEqual(page.overlay_rect_canvas(100.0, 200.0), (0.0, 0.0, 0.0, 0.0))
        page.overlay_rect = (1.0, 2.0, 3.0, 4.0)
        self.assertEqual(
            self.page(scale_factor1=0.0, overlay_rect=(1, 2, 3, 4)).overlay_rect_canvas(
                10, 10
            ),
            (0.0, 0.0, 0.0, 0.0),
        )
        self.assertEqual(page.overlay_rect_canvas(0.0, 100.0), (0.0, 0.0, 0.0, 0.0))

    def test_overlay_rect_page_points_use_the_rotated_page_dimensions(self):
        page = self.page(
            scale_factor1=1.0,
            scale_factor2=192.0,
            rotation=90,
            overlay_rect=(0.0, 0.0, 384.0, 192.0),
        )
        # Rotated page is 144 x 72 pt (384 x 192 overlay units).
        self.assertEqual(page.overlay_rect_page_points(), (0.0, 0.0, 144.0, 72.0))


class BuildPagesFromBidDataTests(unittest.TestCase):
    def test_every_info_field_reaches_the_page_and_takeoffs_are_grouped_by_page(self):
        from ost_visualizer.domain.entities.takeoff import Takeoff

        info = BidPageInfo(
            name="A101",
            sheet_no="S1",
            sequence=4,
            image_path="a.pdf",
            width_pts=100.0,
            height_pts=50.0,
            scale_factor1=0.5,
            scale_factor2=6.0,
            rotation=90,
            flip_x=True,
            flip_y=True,
            page_index=3,
            layer_visible=False,
            overlay_image_path="o.tif",
            overlay_offset_x=1.5,
            overlay_offset_y=2.5,
            overlay_rotation=3.5,
            overlay_resized=True,
            deskew_rotation_overlay=4.5,
            overlay_rect=(1.0, 2.0, 3.0, 4.0),
            image_show_mode=2,
            zoom_fac=1.25,
            current_x=7.0,
            current_y=8.0,
            invert=True,
            bitonal=True,
            folder_uid="f1",
        )
        takeoffs = [
            Takeoff(uid="t1", condition_uid="c", page_uid="p1"),
            Takeoff(uid="t2", condition_uid="c", page_uid="p1"),
            Takeoff(uid="t3", condition_uid="c", page_uid="other"),
        ]
        pages = build_pages_from_bid_data({"p1": info}, takeoffs)
        page = pages["p1"]
        for name in (
            "name",
            "sheet_no",
            "sequence",
            "image_path",
            "width_pts",
            "height_pts",
            "scale_factor1",
            "scale_factor2",
            "rotation",
            "flip_x",
            "flip_y",
            "page_index",
            "layer_visible",
            "overlay_image_path",
            "overlay_offset_x",
            "overlay_offset_y",
            "overlay_rotation",
            "overlay_resized",
            "deskew_rotation_overlay",
            "overlay_rect",
            "image_show_mode",
            "zoom_fac",
            "current_x",
            "current_y",
            "invert",
            "bitonal",
            "folder_uid",
        ):
            with self.subTest(field=name):
                self.assertEqual(getattr(page, name), getattr(info, name))
        self.assertEqual(page.uid, "p1")
        self.assertEqual([t.uid for t in page.takeoffs], ["t1", "t2"])

    def test_takeoffs_for_unknown_pages_get_placeholder_pages_and_pageless_ones_the_no_page_bucket(
        self,
    ):
        from ost_visualizer.domain.entities.takeoff import Takeoff

        takeoffs = [
            Takeoff(uid="a", condition_uid="c", page_uid="ghost"),
            Takeoff(uid="b", condition_uid="c", page_uid=""),
            Takeoff(uid="c", condition_uid="c", page_uid="ghost"),
        ]
        pages = build_pages_from_bid_data({"p1": BidPageInfo(name="Real")}, takeoffs)
        self.assertEqual(sorted(pages), ["NO_PAGE_ID", "ghost", "p1"])
        self.assertEqual(pages["NO_PAGE_ID"].name, "Items Without Page")
        self.assertEqual(pages["NO_PAGE_ID"].uid, "NO_PAGE_ID")
        self.assertEqual([t.uid for t in pages["NO_PAGE_ID"].takeoffs], ["b"])
        self.assertEqual(pages["ghost"].name, "Page ghost")
        self.assertEqual([t.uid for t in pages["ghost"].takeoffs], ["a", "c"])
        self.assertEqual(pages["p1"].takeoffs, [])

    def test_no_synthetic_pages_without_orphan_takeoffs_and_input_infos_are_not_changed(
        self,
    ):
        info = BidPageInfo(name="Real", sequence=2)
        pages = build_pages_from_bid_data({"p1": info}, [])
        self.assertEqual(list(pages), ["p1"])
        self.assertEqual(build_pages_from_bid_data({}, []), {})
        self.assertEqual((info.name, info.sequence), ("Real", 2))

    def test_a_page_named_like_the_no_page_bucket_is_replaced_by_the_synthetic_bucket(
        self,
    ):
        from ost_visualizer.domain.entities.takeoff import Takeoff

        pages = build_pages_from_bid_data(
            {"NO_PAGE_ID": BidPageInfo(name="Imported")},
            [Takeoff(uid="x", condition_uid="c", page_uid="")],
        )
        self.assertEqual(pages["NO_PAGE_ID"].name, "Items Without Page")


class PageCoordinateSizeGuardTests(unittest.TestCase):
    def test_the_page_size_helper_rejects_unusable_coordinate_resolutions(self):
        page = Page(uid="p", name="N", width_pts=72.0, height_pts=144.0)
        self.assertEqual(page._page_coordinate_size(96.0), (96.0, 192.0))
        self.assertEqual(page._page_coordinate_size(1.0), (1.0, 2.0))
        self.assertEqual(page._page_coordinate_size(0.5), (0.5, 1.0))
        for bad in (0.0, -96.0, float("nan"), float("inf"), "x", None):
            with self.subTest(units_per_inch=bad):
                self.assertIsNone(page._page_coordinate_size(bad))
        self.assertEqual(page._page_coordinate_size("96"), (96.0, 192.0))

    def test_a_non_positive_resolution_is_refused_even_when_the_page_size_is_negative_too(
        self,
    ):
        # A negative page size times a negative resolution is a positive coordinate size,
        # so only the resolution check itself can refuse it.
        negative_page = Page(uid="p", name="N", width_pts=-612.0, height_pts=-792.0)
        self.assertIsNone(negative_page._page_coordinate_size(-96.0))
        self.assertIsNone(negative_page._page_coordinate_size(0.0))
        self.assertIsNone(negative_page._page_coordinate_size(96.0))
        self.assertIsNone(negative_page._page_coordinate_size(float("inf")))
        self.assertIsNone(negative_page._page_coordinate_size(float("-inf")))
        positive_page = Page(uid="p", name="N", width_pts=612.0, height_pts=792.0)
        self.assertIsNone(positive_page._page_coordinate_size(-96.0))
