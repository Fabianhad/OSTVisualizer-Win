import unittest
from ost_visualizer.presentation.components.plan_view.components.geometry_utils import (
    polygon_centroid,
    rotate_position_coords,
    signed_area,
)


class TakeoffLifecyclePrecisionTests(unittest.TestCase):
    def test_native_winding_and_concave_rotation_pivot_preserve_translation(self):
        offset = 1e8
        points = [(0, 0), (4, 0), (4, 1), (1, 1), (1, 3), (0, 3)]
        position = [coordinate + offset for point in points for coordinate in point]
        reversed_position = [
            coordinate + offset for point in reversed(points) for coordinate in point
        ]
        with self.subTest(operation="winding"):
            self.assertEqual(signed_area(position), 12)
        with self.subTest(operation="reversed winding"):
            self.assertEqual(signed_area(reversed_position), -12)
        with self.subTest(operation="rotation pivot"):
            self.assertEqual(polygon_centroid(position, 6), (offset + 1.5, offset + 1))
        with self.subTest(operation="rotation pivot reversed winding"):
            self.assertEqual(
                polygon_centroid(reversed_position, 6), (offset + 1.5, offset + 1)
            )
        with self.subTest(operation="area rotation about centroid"):
            rotated = rotate_position_coords(position, 180.0, is_area=True)
            # A half turn about the centroid (1.5, 1) maps p to (3, 2) - p, which
            # differs from the bounding-box pivot (2, 1.5) for this concave shape.
            expected = [
                coordinate
                for x, y in points
                for coordinate in (offset + 3 - x, offset + 2 - y)
            ]
            self.assertEqual(len(rotated), len(expected))
            for actual_value, expected_value in zip(rotated, expected):
                self.assertAlmostEqual(actual_value, expected_value, delta=1e-6)
