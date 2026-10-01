import math
import unittest
from ost_visualizer.presentation.visualization.core.geometry.area import (
    calc_area_mesh_verts,
)


class AreaSlopeBehaviorTests(unittest.TestCase):
    def test_area_mesh_slope_direction_uses_rotation_not_rise_run_signs(self):
        vertices = [(0, 0), (10, 0), (10, 10), (0, 10)]
        _bv, top_positive, _bh, _th, has_slope = calc_area_mesh_verts(
            vertices,
            thickness=1,
            rise=1,
            run=1,
            rotation=0,
        )
        _bv, top_negative, _bh, _th, _has_slope = calc_area_mesh_verts(
            vertices,
            thickness=1,
            rise=-1,
            run=1,
            rotation=0,
        )
        _bv, top_rotated, _bh, _th, _has_slope = calc_area_mesh_verts(
            vertices,
            thickness=1,
            rise=1,
            run=1,
            rotation=math.pi,
        )
        _bv, top_quarter_turn, _bh, _th, _has_slope = calc_area_mesh_verts(
            vertices,
            thickness=1,
            rise=1,
            run=1,
            rotation=math.pi / 2,
        )
        self.assertTrue(has_slope)
        # Slope = abs(rise) / abs(run) = 1 over a 10 unit span starting at thickness 1.
        self.assertEqual(
            [point[2] for point in top_positive],
            [1.0, 11.0, 11.0, 1.0],
        )
        self.assertEqual(
            [point[2] for point in top_negative],
            [point[2] for point in top_positive],
        )
        self.assertLess(top_positive[0][2], top_positive[1][2])
        self.assertGreater(top_rotated[0][2], top_rotated[1][2])
        self.assertEqual(
            [round(point[2], 9) for point in top_rotated], [11.0, 1.0, 1.0, 11.0]
        )
        self.assertEqual(
            [point[:2] for point in top_rotated],
            [[0, 0], [10, 0], [10, 10], [0, 10]],
        )
        self.assertEqual(
            [round(point[2], 9) for point in top_quarter_turn], [11.0, 11.0, 1.0, 1.0]
        )
