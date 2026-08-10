import unittest
from ost_visualizer.presentation.visualization.core.geometry import ost_earcut
from ost_visualizer.presentation.visualization.core.geometry import ost_linear_geom


class NativeGeometryBoundaryTests(unittest.TestCase):
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
