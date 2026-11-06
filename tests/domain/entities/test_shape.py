import math
import unittest
from ost_visualizer.domain.entities.shape import (
    CIRCLE,
    HEXAGON,
    RECTANGLE,
    ShapeSpec,
    create_isosceles_triangle_points,
    create_polygon_points,
    create_rectangle_points,
    create_rhombus_points,
)


class ShapeSpecTests(unittest.TestCase):
    def test_shape_families_and_half_dimensions_are_distinct(self):
        circle = ShapeSpec(CIRCLE, 8, 4)
        self.assertTrue(circle.is_ellipse)
        self.assertFalse(circle.is_polygon)
        self.assertIsNone(circle.polygon_params)
        polygon = ShapeSpec(HEXAGON, 8, 4)
        self.assertTrue(polygon.is_polygon)
        self.assertFalse(polygon.is_ellipse)
        self.assertEqual(polygon.polygon_params, (6, 0))
        rectangle = ShapeSpec(RECTANGLE, 8, 4)
        self.assertFalse(rectangle.is_ellipse)
        self.assertFalse(rectangle.is_polygon)
        self.assertEqual((rectangle.half_width, rectangle.half_depth), (4, 2))
        self.assertIsNone(rectangle.polygon_params)


class ShapePointTests(unittest.TestCase):
    def assert_points(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for actual_point, expected_point in zip(actual, expected):
            self.assertAlmostEqual(actual_point[0], expected_point[0])
            self.assertAlmostEqual(actual_point[1], expected_point[1])

    def test_rectangular_polygon_rotates_about_its_center_once(self):
        self.assert_points(
            create_polygon_points(10, 20, 4, 4, 0, math.pi / 2, half_depth=2),
            [(10, 24), (8, 20), (10, 16), (12, 20)],
        )

    def test_rectangle_and_triangle_rotation_keep_unequal_dimensions(self):
        self.assert_points(
            create_rectangle_points(10, 20, 4, 2, math.pi / 2),
            [(12, 16), (12, 24), (8, 24), (8, 16)],
        )
        self.assert_points(
            create_isosceles_triangle_points(10, 20, 4, 2, math.pi / 2),
            [(12, 20), (8, 24), (8, 16)],
        )

    def test_rhombus_keeps_legacy_width_derived_aspect_ratio(self):
        self.assert_points(
            create_rhombus_points(10, 20, 4, half_depth=99),
            [(10, 16), (12.3, 20), (10, 24), (7.7, 20)],
        )


class ShapeConstantTests(unittest.TestCase):
    def test_shape_ids_are_the_stored_access_codes(self):
        from ost_visualizer.domain.entities import shape

        self.assertEqual(
            (
                shape.SQUARE,
                shape.CIRCLE,
                shape.TRIANGLE,
                shape.RECTANGLE,
                shape.RHOMBUS,
                shape.ELLIPSE,
                shape.HEXAGON,
                shape.OCTAGON,
            ),
            (0, 1, 2, 3, 12, 13, 14, 15),
        )
        self.assertEqual(shape.ELLIPSE_SHAPES, frozenset({1, 13}))
        self.assertEqual(
            shape.POLYGON_SHAPES,
            {2: (3, math.pi / 6), 14: (6, 0), 15: (8, math.pi / 8)},
        )

    def test_every_shape_id_belongs_to_at_most_one_family(self):
        from ost_visualizer.domain.entities import shape

        expected = {
            shape.SQUARE: (False, False),
            shape.CIRCLE: (True, False),
            shape.ELLIPSE: (True, False),
            shape.TRIANGLE: (False, True),
            shape.HEXAGON: (False, True),
            shape.OCTAGON: (False, True),
            shape.RECTANGLE: (False, False),
            shape.RHOMBUS: (False, False),
            99: (False, False),
        }
        for shape_id, (ellipse, polygon) in expected.items():
            with self.subTest(shape_id=shape_id):
                spec = ShapeSpec(shape_id, 6, 2)
                self.assertIs(spec.is_ellipse, ellipse)
                self.assertIs(spec.is_polygon, polygon)
                self.assertEqual(spec.polygon_params is not None, polygon)
        self.assertEqual(ShapeSpec(shape.TRIANGLE, 1, 1).polygon_params, (3, math.pi / 6))
        self.assertEqual(ShapeSpec(shape.OCTAGON, 1, 1).polygon_params, (8, math.pi / 8))

    def test_spec_is_frozen_halves_dimensions_and_defaults_to_no_rotation(self):
        from dataclasses import FrozenInstanceError

        spec = ShapeSpec(RECTANGLE, 7, 3)
        self.assertEqual((spec.rotation, spec.half_width, spec.half_depth), (0.0, 3.5, 1.5))
        with self.assertRaises(FrozenInstanceError):
            spec.width = 1
        self.assertEqual(ShapeSpec(RECTANGLE, 7, 3, 0.5).rotation, 0.5)


class ShapeUnrotatedAndRotatedPointTests(unittest.TestCase):
    def assert_points(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for actual_point, expected_point in zip(actual, expected):
            self.assertAlmostEqual(actual_point[0], expected_point[0])
            self.assertAlmostEqual(actual_point[1], expected_point[1])

    def test_unrotated_rectangle_triangle_and_rhombus_are_axis_aligned_around_the_center(self):
        self.assert_points(
            create_rectangle_points(10, 20, 4, 2),
            [(6, 18), (14, 18), (14, 22), (6, 22)],
        )
        self.assert_points(
            create_isosceles_triangle_points(10, 20, 4, 2),
            [(10, 18), (14, 22), (6, 22)],
        )
        self.assert_points(
            create_rhombus_points(10, 20, 4),
            [(10, 16), (12.3, 20), (10, 24), (7.7, 20)],
        )

    def test_half_turn_rotation_mirrors_every_corner_through_the_center(self):
        self.assert_points(
            create_rectangle_points(10, 20, 4, 2, math.pi),
            [(14, 22), (6, 22), (6, 18), (14, 18)],
        )
        self.assert_points(
            create_isosceles_triangle_points(10, 20, 4, 2, math.pi),
            [(10, 22), (6, 18), (14, 18)],
        )
        self.assert_points(
            create_rhombus_points(10, 20, 4, rotation=math.pi),
            [(10, 24), (7.7, 20), (10, 16), (12.3, 20)],
        )

    def test_rhombus_quarter_turn_and_arbitrary_angle_use_the_rotation_matrix(self):
        self.assert_points(
            create_rhombus_points(10, 20, 4, rotation=math.pi / 2),
            [(14, 20), (10, 22.3), (6, 20), (10, 17.7)],
        )
        angle = math.radians(30)
        rotated = create_rhombus_points(0, 0, 2, rotation=angle)
        top = (0.0, -2.0)
        self.assert_points(
            rotated[:1],
            [(top[0] * math.cos(angle) - top[1] * math.sin(angle),
              top[0] * math.sin(angle) + top[1] * math.cos(angle))],
        )
        self.assertAlmostEqual(rotated[1][0], 2 * 0.575 * math.cos(angle))
        self.assertAlmostEqual(rotated[1][1], 2 * 0.575 * math.sin(angle))

    def test_unrotated_polygon_points_start_at_the_angle_offset_and_run_counter_clockwise(self):
        self.assert_points(
            create_polygon_points(0, 0, 2, 4, 0),
            [(2, 0), (0, 2), (-2, 0), (0, -2)],
        )
        self.assert_points(
            create_polygon_points(1, 1, 2, 3, math.pi / 6),
            [(1 + math.sqrt(3), 2), (1 - math.sqrt(3), 2), (1, -1)],
        )

    def test_polygon_without_half_depth_is_regular_and_with_it_is_stretched_on_y(self):
        regular = create_polygon_points(0, 0, 2, 4, 0)
        stretched = create_polygon_points(0, 0, 2, 4, 0, half_depth=1)
        self.assert_points(stretched, [(2, 0), (0, 1), (-2, 0), (0, -1)])
        self.assertNotEqual(
            [round(v, 6) for point in regular for v in point],
            [round(v, 6) for point in stretched for v in point],
        )

    def test_octagon_and_hexagon_parameters_give_equal_radius_vertices(self):
        from ost_visualizer.domain.entities.shape import HEXAGON, OCTAGON

        for shape_id in (HEXAGON, OCTAGON):
            sides, offset = ShapeSpec(shape_id, 4, 4).polygon_params
            points = create_polygon_points(5, -3, 2, sides, offset)
            with self.subTest(shape_id=shape_id):
                self.assertEqual(len(points), sides)
                for x, y in points:
                    self.assertAlmostEqual(math.hypot(x - 5, y + 3), 2.0)
        sides, offset = ShapeSpec(OCTAGON, 4, 4).polygon_params
        first = create_polygon_points(0, 0, 2, sides, offset)[0]
        self.assertAlmostEqual(first[0], 2 * math.cos(math.pi / 8))
        self.assertAlmostEqual(first[1], 2 * math.sin(math.pi / 8))

    def test_polygon_rotation_turns_the_whole_figure_about_its_center(self):
        self.assert_points(
            create_polygon_points(1, 2, 2, 4, 0, math.pi / 2),
            [(1, 4), (-1, 2), (1, 0), (3, 2)],
        )
        angle = math.radians(30)
        points = create_polygon_points(0, 0, 2, 4, 0, angle, half_depth=1)
        self.assertAlmostEqual(points[0][0], 2 * math.cos(angle))
        self.assertAlmostEqual(points[0][1], 2 * math.sin(angle))
        self.assertAlmostEqual(points[1][0], -1 * math.sin(angle))
        self.assertAlmostEqual(points[1][1], 1 * math.cos(angle))
        self.assertEqual(create_polygon_points(0, 0, 2, 0, 0), [])
