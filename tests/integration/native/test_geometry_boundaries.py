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

    @staticmethod
    def _triangulated_area(coordinates, indices):
        total = 0.0
        for offset in range(0, len(indices), 3):
            (x1, y1), (x2, y2), (x3, y3) = (
                (coordinates[2 * index], coordinates[2 * index + 1])
                for index in indices[offset : offset + 3]
            )
            total += abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2.0
        return total

    def test_valid_earcut_and_curve_inputs_are_accepted(self):
        # Positive controls for the rejection tests above: the same entry
        # points succeed for well-formed input.
        square = [0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
        triangles = ost_earcut.earcut(square, [], 2)
        self.assertEqual(len(triangles), 6)
        self.assertAlmostEqual(self._triangulated_area(square, triangles), 1.0)
        with_hole = [
            0.0, 0.0, 4.0, 0.0, 4.0, 4.0, 0.0, 4.0,
            1.0, 1.0, 2.0, 1.0, 2.0, 2.0, 1.0, 2.0,
        ]  # fmt: skip
        triangles = ost_earcut.earcut(with_hole, [4], 2)
        self.assertEqual(len(triangles), 24)
        # 4 x 4 outer square minus the 1 x 1 hole.
        self.assertAlmostEqual(self._triangulated_area(with_hole, triangles), 15.0)
        points = ost_linear_geom.gen_curve_pts(0, 0, 1, 1, 0.5, 1, 2)
        self.assertEqual(len(points), 3)
        self.assertEqual(
            (tuple(points[0]), tuple(points[-1])), ((0.0, 0.0), (1.0, 1.0))
        )
        # Two cross-section points make an 8-vertex box: 6 faces, 2 triangles each.
        faces = ost_linear_geom.get_curved_mesh_faces(2)
        self.assertEqual(len(faces), 12)
        self.assertTrue(all(0 <= index < 8 for face in faces for index in face))
        edges = ost_linear_geom.get_curved_mesh_edges(2)
        self.assertTrue(
            edges and all(0 <= index < 8 for edge in edges for index in edge)
        )


if __name__ == "__main__":
    unittest.main()
