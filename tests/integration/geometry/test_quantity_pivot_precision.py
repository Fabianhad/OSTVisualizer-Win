import unittest
from ost_visualizer.domain.services.uom_service import calculate_polygon_area
from ost_visualizer.presentation.components.plan_view.components.geometry_utils import (
    polygon_centroid,
    signed_area,
)


class TakeoffLifecyclePrecisionTests(unittest.TestCase):
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

    def test_asymmetric_polygon_pivot_is_translation_independent_for_slivers(self):
        # A right trapezoid whose centroid differs from its vertex mean, so a
        # centroid that fell back to the vertex mean (as the zero-area path does
        # after catastrophic cancellation) cannot satisfy the exact expectation.
        for size in (0.1, 0.0001):
            for offset in (0.0, 1e8):
                with self.subTest(size=size, offset=offset):
                    position = [
                        offset,
                        offset,
                        offset + 4,
                        offset,
                        offset + 4,
                        offset + size,
                        offset + 2,
                        offset + size,
                    ]
                    cx, cy = polygon_centroid(position, 4)
                    # Rectangle x 2..4 (centroid 3) plus triangle (centroid 4/3).
                    self.assertAlmostEqual(cx, offset + 22 / 9, places=6)
                    self.assertAlmostEqual(cy, offset + 4 * size / 9, places=6)
