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
