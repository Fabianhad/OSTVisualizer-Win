import unittest
from ost_visualizer.presentation.components.plan_view.components import ost_geom_utils
from ost_visualizer.presentation.visualization.core.geometry import (
    ost_earcut,
    ost_linear_geom,
)


class NativeGeometryBoundaryTests(unittest.TestCase):
    def test_polygon_rejects_degenerate_and_self_touching_boundaries(self):
        invalid = (
            [(0, 0), (1, 0), (2, 0)],
            [(0, 0), (2, 0), (2, 0), (0, 2)],
            [(0, 0), (4, 0), (4, 4), (2, 0), (0, 4)],
            [(0, 0), (4, 0), (2, 0), (2, 4), (0, 4)],
            [(0, 0), (float("nan"), 0), (0, 2)],
            [(0, 0), (float("inf"), 0), (0, 2)],
        )
        for points in invalid:
            with self.subTest(points=points):
                self.assertFalse(ost_geom_utils.polygon_is_valid(points))

    def test_polygon_preserves_small_slivers_concavity_and_collinear_edge_vertices(
        self,
    ):
        valid = (
            [(0, 0), (0.001, 0), (0, 0.001)],
            [(10000, 10000), (10001, 10000), (10001, 10000.000001)],
            [(0, 0), (2, 0), (4, 0), (4, 4), (0, 4)],
            [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)],
        )
        for points in valid:
            with self.subTest(points=points):
                self.assertTrue(ost_geom_utils.polygon_is_valid(points))
                self.assertTrue(ost_geom_utils.polygon_is_valid(list(reversed(points))))

    def test_earcut_rejects_partial_coordinate(self):
        with self.assertRaises(ValueError):
            ost_earcut.earcut([0.0, 0.0, 1.0], [], 2)

    def test_earcut_rejects_out_of_range_hole(self):
        with self.assertRaises(ValueError):
            ost_earcut.earcut([0.0, 0.0, 1.0, 0.0, 0.0, 1.0], [4], 2)

    def test_earcut_rejects_unsorted_holes(self):
        coordinates = [
            0.0,
            0.0,
            4.0,
            0.0,
            0.0,
            4.0,
            1.0,
            1.0,
            2.0,
            1.0,
            1.0,
            2.0,
            2.0,
            2.0,
            3.0,
            2.0,
            2.0,
            3.0,
        ]
        with self.assertRaises(ValueError):
            ost_earcut.earcut(coordinates, [6, 3], 2)

    def test_linear_curve_rejects_nonpositive_segments(self):
        with self.assertRaises(ValueError):
            ost_linear_geom.gen_curve_pts(0, 0, 1, 1, 0.5, 1, 0)
        with self.assertRaises(ValueError):
            ost_linear_geom.gen_adv_curve_pts(0, 0, 1, 1, 0.5, 1, -1)
        with self.assertRaises(ValueError):
            ost_linear_geom.calc_curve_segs(0, 0, 1, 1, 0.5, 1, 0)

    def test_curved_mesh_indices_require_two_points(self):
        with self.assertRaises(ValueError):
            ost_linear_geom.get_curved_mesh_faces(1)
        with self.assertRaises(ValueError):
            ost_linear_geom.get_curved_mesh_edges(0)


if __name__ == "__main__":
    unittest.main()
