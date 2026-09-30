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
        self.assertTrue(has_slope)
        self.assertEqual(
            [point[2] for point in top_negative],
            [point[2] for point in top_positive],
        )
        self.assertLess(top_positive[0][2], top_positive[1][2])
        self.assertGreater(top_rotated[0][2], top_rotated[1][2])
