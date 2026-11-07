import math
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
        # C -> end is horizontal here, so the three points lie on a circle and the end points
        # are reproduced to rounding (cos/sin of the arc angles), not bit-exactly.
        for actual, expected in zip((points[0], points[-1]), ((0.0, 0.0), (1.0, 1.0))):
            self.assertAlmostEqual(actual[0], expected[0], places=12)
            self.assertAlmostEqual(actual[1], expected[1], places=12)
        # Two cross-section points make an 8-vertex box: 6 faces, 2 triangles each.
        faces = ost_linear_geom.get_curved_mesh_faces(2)
        self.assertEqual(len(faces), 12)
        self.assertTrue(all(0 <= index < 8 for face in faces for index in face))
        edges = ost_linear_geom.get_curved_mesh_edges(2)
        self.assertTrue(
            edges and all(0 <= index < 8 for edge in edges for index in edge)
        )


class NativeLinearAxisAlignedArcTests(unittest.TestCase):
    """A curve whose P1->C or C->P2 piece is exactly horizontal or vertical is still a circle."""

    SEGMENTS = 512
    RADIUS = 100.0

    # Integer points of the radius-100 circle around the origin (exact coordinates, so the
    # axis-aligned pieces are exactly horizontal or vertical in floating point).
    CIRCLE_POINTS = (
        (100, 0), (80, 60), (60, 80), (0, 100), (-60, 80), (-80, 60),
        (-100, 0), (-80, -60), (-60, -80), (0, -100), (60, -80), (80, -60),
    )  # fmt: skip
    @staticmethod
    def _polyline_length(points):
        return sum(
            math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
            for i in range(len(points) - 1)
        )

    def _axis_aligned_cases(self):
        """(start, control, end) triples on the circle with an exactly axis-aligned piece
        and a control point whose arc direction the legacy orientation rule gets right.
        """
        cases = []
        pts = self.CIRCLE_POINTS
        for p1 in pts:
            for c in pts:
                for p2 in pts:
                    if len({p1, c, p2}) != 3:
                        continue
                    first_axis = p1[0] == c[0] or p1[1] == c[1]
                    second_axis = c[0] == p2[0] or c[1] == p2[1]
                    if not (first_axis or second_axis):
                        continue
                    a1 = math.atan2(p1[1], p1[0])
                    ac = math.atan2(c[1], c[0])
                    a2 = math.atan2(p2[1], p2[0])
                    # Arc direction: the side of the chord P1->P2 that the control is on.
                    cross = (c[0] - p1[0]) * (p2[1] - p1[1]) - (c[1] - p1[1]) * (
                        p2[0] - p1[0]
                    )
                    direction = 1.0 if cross > 0 else -1.0
                    sweep = (direction * (a2 - a1)) % (2.0 * math.pi)
                    to_control = (direction * (ac - a1)) % (2.0 * math.pi)
                    to_end = sweep - to_control
                    # Keep only arcs where "control is far from both ends" (|a-b| well under
                    # 180 degrees): the orientation heuristic and the exact rule agree there,
                    # so this test pins the centre construction and nothing else.
                    if abs(to_control - to_end) < math.radians(150.0):
                        cases.append((p1, c, p2, direction * sweep))
        return cases

    def test_axis_aligned_cases_are_generated(self):
        cases = self._axis_aligned_cases()
        self.assertGreater(len(cases), 100)
        self.assertTrue(any(c[0][1] == c[1][1] for c in cases))  # P1->C horizontal
        self.assertTrue(any(c[0][0] == c[1][0] for c in cases))  # P1->C vertical
        self.assertTrue(any(c[1][1] == c[2][1] for c in cases))  # C->P2 horizontal
        self.assertTrue(any(c[1][0] == c[2][0] for c in cases))  # C->P2 vertical

    def test_the_semicircle_on_a_diagonal_chord_with_an_axis_aligned_control(self):
        # Chord (0, 0)-(100, 100), control (100, 0): P1->C is horizontal and C->P2 vertical.
        # The circle through the three points is centred on (50, 50) with radius 70.71 and
        # the arc through the control is a semicircle of length pi * 70.71 = 222.14.
        radius = math.hypot(50.0, 50.0)
        for generator in (
            lambda *a: ost_linear_geom.gen_curve_pts(*a, self.SEGMENTS),
            lambda *a: ost_linear_geom.gen_adv_curve_pts(*a, self.SEGMENTS),
        ):
            for ends in ((0, 0, 100, 100, 100, 0), (0, 0, 100, 100, 0, 100)):
                with self.subTest(ends=ends):
                    points = generator(*ends)
                    self.assertEqual(len(points), self.SEGMENTS + 1)
                    for x, y in points:
                        self.assertAlmostEqual(
                            math.hypot(x - 50.0, y - 50.0), radius, places=6
                        )
                    self.assertAlmostEqual(
                        self._polyline_length(points), math.pi * radius, delta=0.05
                    )

    def test_axis_aligned_pieces_keep_the_circle_through_all_three_points(self):
        for shift_x, shift_y in ((0, 0), (1000, -250)):
            for p1, c, p2, signed_sweep in self._axis_aligned_cases():
                x1, y1, x2, y2, cx, cy = (
                    p1[0] + shift_x, p1[1] + shift_y, p2[0] + shift_x,
                    p2[1] + shift_y, c[0] + shift_x, c[1] + shift_y,
                )  # fmt: skip
                for name, generator in (
                    ("gen_curve_pts", ost_linear_geom.gen_curve_pts),
                    ("gen_adv_curve_pts", ost_linear_geom.gen_adv_curve_pts),
                ):
                    with self.subTest(
                        fn=name, start=(x1, y1), control=(cx, cy), end=(x2, y2)
                    ):
                        points = generator(x1, y1, x2, y2, cx, cy, self.SEGMENTS)
                        self.assertEqual(len(points), self.SEGMENTS + 1)
                        self.assertAlmostEqual(points[0][0], x1, places=6)
                        self.assertAlmostEqual(points[0][1], y1, places=6)
                        self.assertAlmostEqual(points[-1][0], x2, places=6)
                        self.assertAlmostEqual(points[-1][1], y2, places=6)
                        for x, y in points:
                            self.assertAlmostEqual(
                                math.hypot(x - shift_x, y - shift_y),
                                self.RADIUS,
                                places=6,
                            )
                        expected = self.RADIUS * abs(signed_sweep)
                        self.assertAlmostEqual(
                            self._polyline_length(points) / expected, 1.0, delta=1e-3
                        )
                        # The arc runs through the control point (the right one of the two arcs).
                        nearest = min(math.hypot(x - cx, y - cy) for x, y in points)
                        self.assertLess(nearest, 1.5)


class NativeLinearArcSideAndStraightChordTests(unittest.TestCase):
    """The arc runs from the start through the control point to the end (whatever its
    sweep), and a control point equal to an end point is a straight chord. The same
    rules as uom_service._advanced_curve_points (the measured quantity)."""

    SEGMENTS = 256
    RADIUS = 100.0
    CENTER = (500.0, 500.0)
    GENERATORS = (
        ("gen_curve_pts", ost_linear_geom.gen_curve_pts),
        ("gen_adv_curve_pts", ost_linear_geom.gen_adv_curve_pts),
    )

    @staticmethod
    def _polyline_length(points):
        return sum(
            math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
            for i in range(len(points) - 1)
        )

    @staticmethod
    def _arc_sweep_degrees(start, through, end):
        # Independent oracle: the arc from start to end that passes through the middle angle.
        ccw_to_end = (end - start) % 360.0
        ccw_to_through = (through - start) % 360.0
        return ccw_to_end if ccw_to_through <= ccw_to_end else 360.0 - ccw_to_end

    def _at(self, degrees):
        angle = math.radians(degrees)
        return (
            self.CENTER[0] + self.RADIUS * math.cos(angle),
            self.CENTER[1] + self.RADIUS * math.sin(angle),
        )

    def _assert_arc(self, start, through, end):
        p1, pc, p2 = self._at(start), self._at(through), self._at(end)
        expected = self.RADIUS * math.radians(
            self._arc_sweep_degrees(start, through, end)
        )
        step = expected / self.SEGMENTS
        for name, generate in self.GENERATORS:
            with self.subTest(fn=name, arc=(start, through, end)):
                points = generate(*p1, *p2, *pc, self.SEGMENTS)
                self.assertEqual(len(points), self.SEGMENTS + 1)
                self.assertAlmostEqual(points[0][0], p1[0], places=6)
                self.assertAlmostEqual(points[0][1], p1[1], places=6)
                self.assertAlmostEqual(points[-1][0], p2[0], places=6)
                self.assertAlmostEqual(points[-1][1], p2[1], places=6)
                for x, y in points:
                    self.assertAlmostEqual(
                        math.hypot(x - self.CENTER[0], y - self.CENTER[1]),
                        self.RADIUS,
                        delta=1e-6,
                    )
                self.assertAlmostEqual(
                    self._polyline_length(points), expected, delta=expected * 0.001
                )
                nearest = min(math.hypot(x - pc[0], y - pc[1]) for x, y in points)
                self.assertLessEqual(nearest, step)

    def test_the_ost_confirmed_arc_follows_the_251_degree_route(self):
        # On-Screen Takeoff: start 0, control 250, end 251 degrees at R=100 -> 438.1 (not 190.2).
        p1, pc, p2 = self._at(0), self._at(250), self._at(251)
        for name, generate in self.GENERATORS:
            with self.subTest(fn=name):
                length = self._polyline_length(generate(*p1, *p2, *pc, self.SEGMENTS))
                self.assertAlmostEqual(
                    length, self.RADIUS * math.radians(251.0), delta=0.5
                )

    def test_reversed_direction_and_swapped_end_points(self):
        for arc in (
            (251, 250, 0),
            (0, -110, -251),
            (0, 110, 100),
            (100, 110, 0),
            (0, -250, -251),
        ):
            self._assert_arc(*arc)

    def test_major_arcs_with_the_control_point_near_either_end(self):
        for sweep in (200.0, 250.0, 300.0):
            for fraction in (0.01, 0.03, 0.05, 0.5, 0.95, 0.97, 0.99):
                for direction in (1.0, -1.0):
                    for start in (0.0, 100.0, 200.0, 310.0):
                        self._assert_arc(
                            start,
                            start + direction * sweep * fraction,
                            start + direction * sweep,
                        )

    def test_arcs_whose_angles_wrap_past_plus_or_minus_180_degrees(self):
        for start in (-175.0, 170.0, 175.0, 179.5, 180.0, 185.0, 359.5):
            for sweep in (90.0, 200.0, 260.0):
                for fraction in (0.04, 0.5, 0.96):
                    for direction in (1.0, -1.0):
                        self._assert_arc(
                            start,
                            start + direction * sweep * fraction,
                            start + direction * sweep,
                        )

    def test_sweeps_up_to_180_degrees_and_bisector_controls_are_unchanged(self):
        for sweep in (20.0, 60.0, 120.0, 170.0):
            for fraction in (0.05, 0.3, 0.5, 0.7, 0.95):
                for direction in (1.0, -1.0):
                    self._assert_arc(
                        30.0,
                        30.0 + direction * sweep * fraction,
                        30.0 + direction * sweep,
                    )
        for sweep in (30.0, 90.0, 179.0, 181.0, 250.0, 300.0, 350.0):
            for direction in (1.0, -1.0):
                self._assert_arc(
                    40.0, 40.0 + direction * sweep / 2.0, 40.0 + direction * sweep
                )

    def test_a_control_point_equal_to_an_end_point_is_a_straight_chord(self):
        for rotation in range(0, 360, 15):
            for chord in (0.5, 100.0, 5000.0):
                angle = math.radians(rotation)
                p1 = (500.0, -300.0)
                p2 = (p1[0] + chord * math.cos(angle), p1[1] + chord * math.sin(angle))
                for end_name, control in (("start", p1), ("end", p2)):
                    for name, generate in self.GENERATORS:
                        with self.subTest(
                            rotation=rotation, chord=chord, control=end_name, fn=name
                        ):
                            points = generate(*p1, *p2, *control, self.SEGMENTS)
                            self.assertEqual(len(points), self.SEGMENTS + 1)
                            self.assertEqual(tuple(points[0]), p1)
                            self.assertEqual(tuple(points[-1]), p2)
                            self.assertAlmostEqual(
                                self._polyline_length(points), chord, delta=chord * 1e-9
                            )
                            for i, (x, y) in enumerate(points):
                                t = i / self.SEGMENTS
                                self.assertAlmostEqual(
                                    x, p1[0] + t * (p2[0] - p1[0]), delta=chord * 1e-9
                                )
                                self.assertAlmostEqual(
                                    y, p1[1] + t * (p2[1] - p1[1]), delta=chord * 1e-9
                                )

    def test_a_control_point_within_a_tiny_relative_epsilon_of_an_end_is_still_that_end(
        self,
    ):
        for offset in (0.0, 1e-12, 1e-10):
            for name, generate in self.GENERATORS:
                for control in ((offset, -offset), (60 + offset, 80 - offset)):
                    with self.subTest(offset=offset, fn=name, control=control):
                        points = generate(0, 0, 60, 80, *control, self.SEGMENTS)
                        self.assertAlmostEqual(
                            self._polyline_length(points), 100.0, delta=1e-6
                        )

    def test_the_end_point_epsilon_is_relative_to_the_chord_length(self):
        # 1e-4 away from an end of a 1e6 chord is 1e-10 of it (inside the 1e-9 epsilon): the
        # points are the evenly spaced straight chord, not the quadratic fallback.
        p1, p2 = (0.0, 0.0), (6e5, 8e5)
        for control in ((1e-4, 0.0), (6e5 - 1e-4, 8e5)):
            for name, generate in self.GENERATORS:
                with self.subTest(control=control, fn=name):
                    points = generate(*p1, *p2, *control, self.SEGMENTS)
                    for i, (x, y) in enumerate(points):
                        self.assertAlmostEqual(x, p2[0] * i / self.SEGMENTS, delta=1e-3)
                        self.assertAlmostEqual(y, p2[1] * i / self.SEGMENTS, delta=1e-3)

    def test_a_control_point_that_is_near_but_not_equal_to_an_end_still_follows_the_arc(
        self,
    ):
        for arc in (
            (0, 0.2, 250),
            (0, 249.8, 250),
            (90, 90.2, 340),
            (0, -0.2, -250),
            (0, 0.01, 250),
            (0, 1e-5, 250),
            (0, 249.99999, 250),
            (0, -1e-5, -250),
        ):
            self._assert_arc(*arc)

    def test_collinear_controls_keep_the_quadratic_fallback(self):
        # (start, end, control, quadratic length): no circle exists, nothing changes.
        for ends, expected in (
            ((0, 0, 100, 0, 50, 0), 100.0),
            ((0, 0, 100, 0, 150, 0), 125.0),
            ((0, 0, 100, 0, -50, 0), 125.0),
        ):
            for name, generate in self.GENERATORS:
                with self.subTest(ends=ends, fn=name):
                    self.assertAlmostEqual(
                        self._polyline_length(generate(*ends, 512)),
                        expected,
                        delta=0.01,
                    )

    def test_the_native_arc_matches_the_python_measure_on_a_grid(self):
        from ost_visualizer.domain.services import uom_service

        checked = 0
        for center in ((0.0, 0.0), (500.0, 500.0), (-1234.5, 777.25)):
            for radius in (5.0, 100.0):
                for sweep in (40.0, 179.0, 181.0, 250.0, 330.0):
                    for fraction in (0.02, 0.2, 0.5, 0.8, 0.98):
                        for direction in (1.0, -1.0):
                            for start in (0.0, 135.0, 179.0, 270.0):
                                pts = [
                                    (
                                        center[0] + radius * math.cos(math.radians(a)),
                                        center[1] + radius * math.sin(math.radians(a)),
                                    )
                                    for a in (
                                        start,
                                        start + direction * sweep * fraction,
                                        start + direction * sweep,
                                    )
                                ]
                                p1, pc, p2 = pts
                                segments = uom_service._calc_curve_segments(
                                    *p1, *p2, *pc
                                )
                                python = uom_service._advanced_curve_points(
                                    *p1, *p2, *pc, segments
                                )
                                native = ost_linear_geom.gen_adv_curve_pts(
                                    *p1, *p2, *pc, segments
                                )
                                with self.subTest(
                                    center=center, radius=radius, arc=pts
                                ):
                                    self.assertAlmostEqual(
                                        self._polyline_length(native),
                                        self._polyline_length(python),
                                        delta=1e-6,
                                    )
                                checked += 1
        self.assertGreater(checked, 1000)


if __name__ == "__main__":
    unittest.main()
