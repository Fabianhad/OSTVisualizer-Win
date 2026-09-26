import unittest
from ost_visualizer.domain.services.uom_service import calculate_polygon_area
from ost_visualizer.presentation.components.plan_view.components.geometry_utils import (
    polygon_centroid,
    signed_area,
)


class TakeoffLifecyclePrecisionTests(unittest.TestCase):
    def test_native_winding_and_concave_rotation_pivot_preserve_translation(self):
        offset = 1e8
        points = [(0, 0), (4, 0), (4, 1), (1, 1), (1, 3), (0, 3)]
        position = [coordinate + offset for point in points for coordinate in point]
        with self.subTest(operation="winding"):
            self.assertEqual(signed_area(position), 12)
        with self.subTest(operation="rotation pivot"):
            self.assertEqual(polygon_centroid(position, 6), (offset + 1.5, offset + 1))

    def test_area_and_rotation_pivot_are_translation_independent_for_slivers(self):
        for size in (0.1, 0.0001):
            for offset in (0.0, 1e8):
                with self.subTest(size=size, offset=offset):
                    # Use exactly representable dimensions after translation as
                    # the reference: this tests cancellation, not input rounding.
                    left, right = offset, offset + 2
                    low, high = offset, offset + size
                    vertices = [(left, low), (right, low), (right, high), (left, high)]
                    position = [value for vertex in vertices for value in vertex]
                    expected = (right - left) * (high - low)
                    self.assertAlmostEqual(
                        calculate_polygon_area(vertices),
                        expected,
                        delta=expected * 1e-12,
                    )
                    self.assertAlmostEqual(
                        signed_area(position), 2 * expected, delta=expected * 1e-12
                    )
                    cx, cy = polygon_centroid(position, 4)
                    self.assertAlmostEqual(cx, (left + right) / 2)
                    self.assertAlmostEqual(cy, (low + high) / 2)
