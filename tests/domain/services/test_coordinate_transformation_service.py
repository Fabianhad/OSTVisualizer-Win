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


def _close(testcase, actual, expected, places=6):
    actual = [
        tuple(point) if isinstance(point, (list, tuple)) else point for point in actual
    ]
    testcase.assertEqual(len(actual), len(expected))
    for got, want in zip(actual, expected):
        if isinstance(want, tuple):
            testcase.assertEqual(len(got), len(want))
            for g, w in zip(got, want):
                testcase.assertAlmostEqual(g, w, places=places)
        else:
            testcase.assertAlmostEqual(got, want, places=places)


class OSTCoordinateSystemStateTests(unittest.TestCase):
    def test_defaults_describe_a_letter_page_at_unit_scale(self):
        system = OSTCoordinateSystem()
        self.assertEqual(
            system.page_info,
            {
                "scale_factor1": 1.0,
                "scale_factor2": 1.0,
                "rotation": 0,
                "flip_x": False,
                "flip_y": False,
                "width": 612.0,
                "height": 792.0,
                "view_scale": 1.0,
            },
        )
        self.assertEqual(
            (system.sf1, system.sf2, system.rotation, system.flip_x, system.flip_y),
            (1.0, 1.0, 0, False, False),
        )
        self.assertEqual(
            (system.width, system.height, system.view_scale), (612.0, 792.0, 1.0)
        )
        self.assertEqual(OSTCoordinateSystem.PDF_POINTS_PER_INCH, 72.0)

    def test_constructor_page_info_is_applied_and_instances_do_not_share_state(self):
        configured = OSTCoordinateSystem({"scale_factor2": 4.0, "width": 100.0})
        plain = OSTCoordinateSystem()
        self.assertEqual((configured.sf2, configured.width), (4.0, 100.0))
        self.assertEqual((plain.sf2, plain.width), (1.0, 612.0))
        self.assertEqual(OSTCoordinateSystem({}).page_info, plain.page_info)

    def test_update_merges_partial_info_and_keeps_other_values(self):
        system = OSTCoordinateSystem({"scale_factor1": 2.0, "scale_factor2": 8.0})
        system.update_page_info({"view_scale": 1.5, "flip_x": True})
        self.assertEqual(
            (system.sf1, system.sf2, system.view_scale, system.flip_x),
            (2.0, 8.0, 1.5, True),
        )

    def test_update_coerces_types_and_replaces_blank_values_with_defaults(self):
        system = OSTCoordinateSystem(
            {
                "scale_factor1": "2",
                "scale_factor2": "6",
                "rotation": "90",
                "flip_x": 1,
                "flip_y": 0,
                "width": "100",
                "height": "200",
                "view_scale": "0.5",
            }
        )
        self.assertEqual(
            system.page_info,
            {
                "scale_factor1": 2.0,
                "scale_factor2": 6.0,
                "rotation": 90,
                "flip_x": True,
                "flip_y": False,
                "width": 100.0,
                "height": 200.0,
                "view_scale": 0.5,
            },
        )
        system.update_page_info(
            {
                "scale_factor1": 0,
                "scale_factor2": None,
                "rotation": None,
                "width": 0,
                "height": "",
                "view_scale": 0.0,
            }
        )
        self.assertEqual(
            (
                system.sf1,
                system.sf2,
                system.rotation,
                system.width,
                system.height,
                system.view_scale,
            ),
            (1.0, 1.0, 0, 612.0, 792.0, 1.0),
        )

    def test_validation_restores_a_default_for_every_key_removed_from_the_live_page_info(
        self,
    ):
        system = OSTCoordinateSystem(
            {
                "scale_factor1": 2.0,
                "scale_factor2": 6.0,
                "rotation": 90,
                "flip_x": True,
                "flip_y": True,
                "width": 100.0,
                "height": 200.0,
                "view_scale": 3.0,
            }
        )
        for key in list(system.page_info):
            del system.page_info[key]
        system.update_page_info({})
        self.assertEqual(
            system.page_info,
            {
                "scale_factor1": 1.0,
                "scale_factor2": 1.0,
                "rotation": 0,
                "flip_x": False,
                "flip_y": False,
                "width": 612.0,
                "height": 792.0,
                "view_scale": 1.0,
            },
        )

    def test_rotation_is_reduced_modulo_a_full_turn(self):
        for given, expected in ((360, 0), (450, 90), (-90, 270), (720, 0), (270, 270)):
            with self.subTest(rotation=given):
                self.assertEqual(
                    OSTCoordinateSystem({"rotation": given}).rotation, expected
                )

    def test_property_access_returns_the_live_page_info(self):
        system = OSTCoordinateSystem()
        self.assertIs(system.page_info, system.page_info)
        system.page_info["scale_factor1"] = 0
        self.assertEqual(system.scale_ratio, 1.0)
        system.page_info["scale_factor1"] = 2.0
        system.page_info["scale_factor2"] = 6.0
        self.assertEqual(system.scale_ratio, 3.0)


class OSTCoordinateSystemUnitConversionTests(unittest.TestCase):
    def setUp(self):
        # ratio = 6 / 2 = 3 sheet-units per inch, view scale 2.
        self.system = OSTCoordinateSystem(
            {"scale_factor1": 2.0, "scale_factor2": 6.0, "view_scale": 2.0}
        )

    def test_real_units_points_and_pixels_chain_through_the_scale_ratio(self):
        self.assertAlmostEqual(self.system.ost_to_real_units(12.0), 4.0)
        self.assertAlmostEqual(self.system.ost_to_pdf_points(12.0), 4.0 * 72.0)
        self.assertAlmostEqual(self.system.ost_to_screen_pixels(12.0), 4.0 * 72.0 * 2.0)
        self.assertAlmostEqual(self.system.pdf_points_to_screen_pixels(10.0), 20.0)
        self.assertAlmostEqual(self.system.ost_to_real_units(0.0), 0.0)
        self.assertAlmostEqual(self.system.ost_to_real_units(-3.0), -1.0)

    def test_zero_ratio_leaves_ost_units_unscaled(self):
        self.system.page_info["scale_factor2"] = 0.0
        self.assertEqual(self.system.scale_ratio, 0.0)
        self.assertEqual(self.system.ost_to_real_units(12.0), 12.0)

    def test_to_2d_scales_both_axes_by_points_per_unit_and_view_scale(self):
        _close(
            self,
            [self.system.transform_to_2d(6.0, 12.0)],
            [(6.0 / 3 * 72 * 2, 12.0 / 3 * 72 * 2)],
        )
        _close(
            self, [self.system.transform_to_2d(-3.0, 0.0)], [(-3.0 / 3 * 72 * 2, 0.0)]
        )

    def test_vertices_to_2d_scales_flat_coordinate_lists_and_passes_short_input_through(
        self,
    ):
        _close(
            self,
            self.system.transform_vertices_to_2d([6.0, 12.0, 3.0, 9.0]),
            [288.0, 576.0, 144.0, 432.0],
        )
        short = [5.0]
        self.assertIs(self.system.transform_vertices_to_2d(short), short)
        empty = []
        self.assertIs(self.system.transform_vertices_to_2d(empty), empty)
        self.assertIsNone(self.system.transform_vertices_to_2d(None))


class OSTCoordinateSystemThreeDTests(unittest.TestCase):
    def setUp(self):
        # ratio 2; 600x800 pt page (8.333 x 11.111 in).
        self.info = {
            "scale_factor1": 1.0,
            "scale_factor2": 2.0,
            "width": 600.0,
            "height": 800.0,
        }

    def test_unrotated_3d_maps_x_to_negative_inches_and_y_to_inches(self):
        system = OSTCoordinateSystem(self.info)
        _close(self, [system.transform_to_3d(10.0, 20.0)], [(-5.0, 10.0)])
        _close(
            self,
            system.transform_vertices_to_3d([(10.0, 20.0), (1.0, 2.0)]),
            [(-5.0, 10.0), (-0.5, 1.0)],
        )
        _close(
            self,
            system.transform_holes_to_3d([[(10.0, 20.0), (1.0, 2.0)], [(4.0, 6.0)]])[0],
            [(-5.0, 10.0), (-0.5, 1.0)],
        )
        holes = system.transform_holes_to_3d([[(10.0, 20.0)], [(4.0, 6.0)]])
        self.assertEqual(len(holes), 2)
        _close(self, holes[1], [(-2.0, 3.0)])

    def test_empty_holes_are_none_and_empty_vertices_are_empty(self):
        for rotation in (0, 90):
            with self.subTest(rotation=rotation):
                system = OSTCoordinateSystem({**self.info, "rotation": rotation})
                self.assertIsNone(system.transform_holes_to_3d(None))
                self.assertIsNone(system.transform_holes_to_3d([]))
                self.assertEqual(list(system.transform_vertices_to_3d([])), [])

    def test_rotation_90_projects_onto_the_rotated_page(self):
        system = OSTCoordinateSystem({**self.info, "rotation": 90})
        # PDF point of OST (10,20): (360, 80) unrotated -> (720, 360) on the 800x600 page.
        _close(
            self,
            [system.transform_to_3d(10.0, 20.0)],
            [(-720.0 / 72.0, (600.0 - 360.0) / 72.0)],
        )
        _close(
            self,
            system.transform_vertices_to_3d([(10.0, 20.0), (1.0, 2.0)]),
            [(-10.0, 240.0 / 72.0), (-72.0 / 72.0, (600.0 - 36.0) / 72.0)],
        )

    def test_each_flip_mirrors_within_the_page_before_projection(self):
        flipped_x = OSTCoordinateSystem({**self.info, "flip_x": True})
        # PDF (360, 80) -> flip X -> (240, 80); page height stays 800.
        _close(
            self,
            [flipped_x.transform_to_3d(10.0, 20.0)],
            [(-240.0 / 72.0, (800.0 - 80.0) / 72.0)],
        )
        flipped_y = OSTCoordinateSystem({**self.info, "flip_y": True})
        # PDF (360, 80) -> flip Y -> (360, 720).
        _close(
            self,
            [flipped_y.transform_to_3d(10.0, 20.0)],
            [(-360.0 / 72.0, (800.0 - 720.0) / 72.0)],
        )
        both = OSTCoordinateSystem({**self.info, "flip_x": True, "flip_y": True})
        _close(
            self,
            [both.transform_to_3d(10.0, 20.0)],
            [(-240.0 / 72.0, (800.0 - 720.0) / 72.0)],
        )

    def test_transformed_holes_use_the_same_rotated_projection_per_hole(self):
        system = OSTCoordinateSystem({**self.info, "rotation": 90})
        holes = system.transform_holes_to_3d(
            [[(10.0, 20.0)], [(10.0, 20.0), (1.0, 2.0)]]
        )
        self.assertEqual([len(hole) for hole in holes], [1, 2])
        expected = system.transform_vertices_to_3d([(10.0, 20.0), (1.0, 2.0)])
        _close(self, holes[1], [tuple(point) for point in expected])
        _close(self, holes[0], [tuple(expected[0])])


class OSTCoordinateSystemParsingTests(unittest.TestCase):
    def test_parse_position_accepts_text_sequences_and_nothing(self):
        parse = OSTCoordinateSystem.parse_position
        self.assertEqual(parse(None), [])
        self.assertEqual(parse([1, "2.5", 3.0]), [1.0, 2.5, 3.0])
        self.assertEqual(parse((4, 5)), [4.0, 5.0])
        self.assertEqual(parse("1.5;2.5; 3"), [1.5, 2.5, 3.0])
        self.assertEqual(parse(""), [])
        self.assertEqual(parse("1;oops"), [])
        self.assertEqual(parse(12), [])
        self.assertEqual(parse({"x": 1}), [])
        self.assertIsInstance(parse([1])[0], float)

    def test_parse_position_rejects_non_numeric_sequence_members(self):
        with self.assertRaises(ValueError):
            OSTCoordinateSystem.parse_position(["1", "bad"])

    def test_pdf_coordinates_require_a_point_and_use_page_defaults(self):
        convert = OSTCoordinateSystem.ost_to_pdf_coordinates
        self.assertEqual(convert([], {}), [])
        self.assertEqual(convert([5.0], {}), [])
        # Without a full point there is nothing to convert, so even an invalid page
        # contract is not reported (no point reaches the native transform).
        self.assertEqual(convert([], {"width": 0.0}), [])
        self.assertEqual(convert([5.0], {"width": 0.0}), [])
        with self.assertRaises(ValueError):
            convert([5.0, 6.0], {"width": 0.0})
        # No keys: letter page, ratio 1, rotation 0, no flips.
        _close(self, convert([1.0, 2.0], {}), [(72.0, 792.0 - 144.0)])
        _close(self, convert([1.0, 2.0, 0.5, 1.0], {}), [(72.0, 648.0), (36.0, 720.0)])

    def test_pdf_coordinates_honour_rotation_and_flips_on_a_scaled_page(self):
        base = {
            "width": 600.0,
            "height": 800.0,
            "scale_factor1": 1.0,
            "scale_factor2": 2.0,
        }
        convert = OSTCoordinateSystem.ost_to_pdf_coordinates
        _close(self, convert([10.0, 20.0], base), [(360.0, 80.0)])
        _close(self, convert([10.0, 20.0], {**base, "rotation": 90}), [(720.0, 360.0)])
        _close(
            self,
            convert([10.0, 20.0], {**base, "rotation": 180, "flip_x": True}),
            [(360.0, 720.0)],
        )
        _close(
            self,
            convert([10.0, 20.0], {**base, "rotation": 270, "flip_y": True}),
            [(720.0, 240.0)],
        )


class OSTCoordinateSystemEdgeTests(unittest.TestCase):
    def test_boolean_flip_flags_are_real_booleans(self):
        system = OSTCoordinateSystem({"flip_x": 1, "flip_y": "yes"})
        self.assertIs(system.flip_x, True)
        self.assertIs(system.flip_y, True)
        system.update_page_info({"flip_x": 0, "flip_y": ""})
        self.assertIs(system.flip_x, False)
        self.assertIs(system.flip_y, False)

    def test_a_single_point_is_converted_to_2d_like_any_longer_list(self):
        system = OSTCoordinateSystem({"scale_factor2": 2.0, "view_scale": 2.0})
        _close(self, system.transform_vertices_to_2d([6.0, 12.0]), [432.0, 864.0])

    def test_flips_alone_select_the_page_aware_path_for_vertices_and_holes(self):
        info = {"scale_factor2": 2.0, "width": 600.0, "height": 800.0}
        flipped = OSTCoordinateSystem({**info, "flip_x": True})
        _close(
            self,
            flipped.transform_vertices_to_3d([(10.0, 20.0)]),
            [(-240.0 / 72.0, 10.0)],
        )
        _close(
            self,
            flipped.transform_holes_to_3d([[(10.0, 20.0)]])[0],
            [(-240.0 / 72.0, 10.0)],
        )
        flipped = OSTCoordinateSystem({**info, "flip_y": True})
        _close(
            self,
            flipped.transform_vertices_to_3d([(10.0, 20.0)]),
            [(-5.0, 80.0 / 72.0)],
        )
        _close(
            self,
            flipped.transform_holes_to_3d([[(10.0, 20.0)]])[0],
            [(-5.0, 80.0 / 72.0)],
        )
        unflipped = OSTCoordinateSystem(info)
        _close(self, unflipped.transform_vertices_to_3d([(10.0, 20.0)]), [(-5.0, 10.0)])

    def test_pdf_coordinates_default_to_a_letter_width_when_flipping(self):
        convert = OSTCoordinateSystem.ost_to_pdf_coordinates
        _close(self, convert([1.0, 2.0], {"flip_x": True}), [(612.0 - 72.0, 648.0)])
        _close(self, convert([1.0, 2.0], {"flip_y": True}), [(72.0, 144.0)])
        _close(self, convert([1.0, 2.0], {"rotation": 90}), [(792.0 - 648.0, 72.0)])


class OSTCoordinateSystemNonIntegralAndTinyPageTests(unittest.TestCase):
    def test_scale_ratio_and_real_units_use_true_division_for_non_divisible_values(
        self,
    ):
        system = OSTCoordinateSystem({"scale_factor1": 4.0, "scale_factor2": 3.0})
        self.assertAlmostEqual(system.scale_ratio, 0.75)
        self.assertAlmostEqual(system.ost_to_real_units(10.0), 40.0 / 3.0)
        self.assertAlmostEqual(system.ost_to_pdf_points(10.0), 40.0 / 3.0 * 72.0)
        system = OSTCoordinateSystem({"scale_factor1": 1.0, "scale_factor2": 0.5})
        self.assertAlmostEqual(system.scale_ratio, 0.5)
        self.assertAlmostEqual(system.ost_to_real_units(3.0), 6.0)

    def test_the_centre_of_a_rotated_page_smaller_than_one_ost_unit_stays_the_centre(
        self,
    ):
        # A 36 pt square page at ratio 1 is only half an OST unit wide. Its centre
        # (0.25, 0.25) is the centre of the page whatever the rotation, i.e. 18 pt in
        # both pdf axes, so the 3D point is (-18/72, (36 - 18)/72) = (-0.25, 0.25).
        # This needs the page-corner box (0 .. width/72*ratio) to be computed exactly.
        for rotation in (90, 180, 270):
            with self.subTest(rotation=rotation):
                system = OSTCoordinateSystem(
                    {"width": 36.0, "height": 36.0, "rotation": rotation}
                )
                x, y = system.transform_to_3d(0.25, 0.25)
                self.assertAlmostEqual(x, -0.25)
                self.assertAlmostEqual(y, 0.25)
        flipped = OSTCoordinateSystem({"width": 36.0, "height": 36.0, "flip_x": True})
        x, y = flipped.transform_to_3d(0.25, 0.25)
        self.assertAlmostEqual(x, -0.25)
        self.assertAlmostEqual(y, 0.25)
