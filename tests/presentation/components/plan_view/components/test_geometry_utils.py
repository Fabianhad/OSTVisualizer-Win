import math
import unittest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainterPath
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.presentation.components.plan_view.components import geometry_utils
from ost_visualizer.presentation.components.plan_view.components.geometry_utils import (
    attachment_fits_area,
    closed_polygon_path,
    cursor_for_direction,
    mirror_points_around,
    mirror_position_coords,
    path_fits_inside_excluding,
    path_intersects_any,
    path_is_inside,
    polygon_centroid,
    position_polygon_path,
    resize_cursor_for_edge,
    rotate_points_around,
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


class _ScalingCoordinates:
    """Minimal coordinate system: scales every coordinate and records calls."""

    def __init__(self, factor=1.0):
        self.factor = factor
        self.calls = []

    def transform_vertices_to_2d(self, position):
        self.calls.append(list(position))
        return [value * self.factor for value in position]


class _CurvedGeometry:
    """Returns a fixed processed curve and records the arguments it received."""

    def __init__(self, processed):
        self.processed = processed
        self.calls = []

    def proc_curved_pos(self, *args):
        self.calls.append(args)
        return self.processed


def _rect_path(left, top, right, bottom):
    return closed_polygon_path([left, top, right, top, right, bottom, left, bottom])


class PolygonPathHelperTests(unittest.TestCase):
    def test_closed_polygon_path_keeps_point_order_and_closes_the_subpath(self):
        path = closed_polygon_path([0.0, 0.0, 10.0, 0.0, 10.0, 4.0])
        self.assertEqual(path.boundingRect(), QRectF(0.0, 0.0, 10.0, 4.0))
        # (9, 1) is inside the (0,0)-(10,0)-(10,4) triangle; x/y swapped it is not.
        self.assertTrue(path.contains(QPointF(9.0, 1.0)))
        self.assertFalse(path.contains(QPointF(1.0, 3.0)))
        # moveTo + two lineTo + the closing line back to the first vertex.
        self.assertEqual(path.elementCount(), 4)
        closing = path.elementAt(3)
        self.assertEqual((closing.x, closing.y), (0.0, 0.0))

    def test_closed_polygon_path_rejects_short_or_odd_coordinate_lists(self):
        for points in (
            [],
            [0.0, 0.0],
            [0.0, 0.0, 1.0, 1.0],
            [0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 5.0],
        ):
            with self.subTest(points=points):
                self.assertTrue(closed_polygon_path(points).isEmpty())
        self.assertFalse(closed_polygon_path([0.0, 0.0, 1.0, 0.0, 1.0, 1.0]).isEmpty())

    def test_position_polygon_path_transforms_before_building_the_path(self):
        coordinates = _ScalingCoordinates(2.0)
        path = position_polygon_path(
            coordinates, [1.0, 1.0, 6.0, 1.0, 6.0, 3.0, 1.0, 3.0]
        )
        self.assertEqual(path.boundingRect(), QRectF(2.0, 2.0, 10.0, 4.0))
        self.assertEqual(coordinates.calls, [[1.0, 1.0, 6.0, 1.0, 6.0, 3.0, 1.0, 3.0]])

    def test_position_polygon_path_rejects_invalid_positions_without_transforming(self):
        coordinates = _ScalingCoordinates()
        for position in (
            [],
            [0.0, 0.0, 1.0, 1.0],
            [0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 5.0],
        ):
            with self.subTest(position=position):
                self.assertTrue(position_polygon_path(coordinates, position).isEmpty())
        self.assertEqual(coordinates.calls, [])
        self.assertFalse(
            position_polygon_path(coordinates, [0.0, 0.0, 1.0, 0.0, 1.0, 1.0]).isEmpty()
        )

    def test_path_is_inside_requires_two_non_empty_paths_and_full_containment(self):
        parent = _rect_path(0, 0, 100, 100)
        self.assertTrue(path_is_inside(_rect_path(10, 10, 20, 20), parent))
        self.assertTrue(path_is_inside(parent, parent))
        self.assertFalse(path_is_inside(_rect_path(90, 90, 110, 110), parent))
        self.assertFalse(path_is_inside(_rect_path(200, 200, 210, 210), parent))
        self.assertFalse(path_is_inside(QPainterPath(), parent))
        self.assertFalse(path_is_inside(_rect_path(10, 10, 20, 20), QPainterPath()))
        self.assertFalse(path_is_inside(QPainterPath(), QPainterPath()))

    def test_path_intersects_any_ignores_empty_paths_and_accepts_generators(self):
        candidate = _rect_path(0, 0, 10, 10)
        near = _rect_path(5, 5, 15, 15)
        far = _rect_path(50, 50, 60, 60)
        self.assertTrue(path_intersects_any(candidate, [far, near]))
        self.assertTrue(path_intersects_any(candidate, (path for path in [far, near])))
        self.assertIs(path_intersects_any(candidate, [far]), False)
        self.assertIs(path_intersects_any(candidate, []), False)
        self.assertIs(path_intersects_any(candidate, [QPainterPath()]), False)
        self.assertIs(path_intersects_any(QPainterPath(), [near]), False)

    def test_path_fits_inside_excluding_needs_containment_and_no_exclusion_hit(self):
        parent = _rect_path(0, 0, 100, 100)
        candidate = _rect_path(10, 10, 20, 20)
        hole = _rect_path(15, 15, 30, 30)
        elsewhere = _rect_path(60, 60, 70, 70)
        self.assertTrue(path_fits_inside_excluding(candidate, parent, []))
        self.assertTrue(path_fits_inside_excluding(candidate, parent, [elsewhere]))
        self.assertFalse(
            path_fits_inside_excluding(candidate, parent, [elsewhere, hole])
        )
        self.assertFalse(
            path_fits_inside_excluding(_rect_path(90, 90, 110, 110), parent, [])
        )


class AttachmentFitTests(unittest.TestCase):
    PARENT = [0.0, 0.0, 100.0, 0.0, 100.0, 100.0, 0.0, 100.0]

    @staticmethod
    def _condition(condition_type=Condition.TYPE_ATTACHMENT):
        return Condition(
            uid="attachment",
            condition_type=condition_type,
            shape=shapes.RECTANGLE,
            width=10.0,
            depth=4.0,
        )

    def _footprint(self, coordinates, position, rotation=0.0, condition=None):
        # attachment_fits_area exposes the footprint only through its verdict, so the
        # private builder is exercised directly for the exact footprint geometry.
        return geometry_utils._attachment_footprint_path(
            coordinates, condition or self._condition(), position, rotation
        )

    def test_footprint_is_the_condition_rectangle_centred_on_the_position(self):
        coordinates = _ScalingCoordinates()
        path = self._footprint(coordinates, [50.0, 30.0])
        self.assertEqual(path.boundingRect(), QRectF(45.0, 28.0, 10.0, 4.0))
        self.assertEqual(
            coordinates.calls,
            [[45.0, 28.0, 55.0, 28.0, 55.0, 32.0, 45.0, 32.0]],
        )

    def test_footprint_rotation_is_in_radians_and_swaps_the_extents(self):
        path = self._footprint(_ScalingCoordinates(), [50.0, 30.0], math.pi / 2)
        rect = path.boundingRect()
        self.assertAlmostEqual(rect.x(), 48.0, places=6)
        self.assertAlmostEqual(rect.y(), 25.0, places=6)
        self.assertAlmostEqual(rect.width(), 4.0, places=6)
        self.assertAlmostEqual(rect.height(), 10.0, places=6)

    def test_footprint_goes_through_the_coordinate_system(self):
        path = self._footprint(_ScalingCoordinates(2.0), [50.0, 30.0])
        self.assertEqual(path.boundingRect(), QRectF(90.0, 56.0, 20.0, 8.0))

    def test_footprint_is_empty_for_non_attachments_or_malformed_positions(self):
        coordinates = _ScalingCoordinates()
        for condition_type in (
            Condition.TYPE_LINEAR,
            Condition.TYPE_AREA,
            Condition.TYPE_COUNT,
        ):
            with self.subTest(condition_type=condition_type):
                path = self._footprint(
                    coordinates,
                    [50.0, 30.0],
                    condition=self._condition(condition_type),
                )
                self.assertTrue(path.isEmpty())
        for position in ([], [50.0], [50.0, 30.0, 1.0]):
            with self.subTest(position=position):
                self.assertTrue(self._footprint(coordinates, position).isEmpty())
        self.assertEqual(coordinates.calls, [])

    def test_attachment_fits_area_checks_containment_and_backout_exclusions(self):
        coordinates = _ScalingCoordinates()
        condition = self._condition()
        backout = [40.0, 20.0, 60.0, 20.0, 60.0, 40.0, 40.0, 40.0]
        far_backout = [80.0, 80.0, 90.0, 80.0, 90.0, 90.0, 80.0, 90.0]
        cases = [
            ("inside, no backouts", [50.0, 60.0], [], True),
            ("inside, distant backout", [50.0, 60.0], [far_backout], True),
            ("overlaps a backout", [50.0, 30.0], [far_backout, backout], False),
            ("overlaps generator backout", [50.0, 30.0], (b for b in [backout]), False),
            ("sticks out of the area", [97.0, 60.0], [], False),
            ("entirely outside", [300.0, 300.0], [], False),
        ]
        for label, position, backouts, expected in cases:
            with self.subTest(label):
                self.assertIs(
                    attachment_fits_area(
                        coordinates, condition, position, 0.0, self.PARENT, backouts
                    ),
                    expected,
                )

    def test_attachment_fits_area_is_false_for_non_attachment_or_empty_parent(self):
        coordinates = _ScalingCoordinates()
        self.assertFalse(
            attachment_fits_area(
                coordinates,
                self._condition(Condition.TYPE_AREA),
                [50.0, 60.0],
                0.0,
                self.PARENT,
                [],
            )
        )
        self.assertFalse(
            attachment_fits_area(
                coordinates, self._condition(), [50.0, 60.0], 0.0, [0.0, 0.0], []
            )
        )


class ResizeCursorTests(unittest.TestCase):
    H = Qt.CursorShape.SizeHorCursor
    F = Qt.CursorShape.SizeFDiagCursor
    V = Qt.CursorShape.SizeVerCursor
    B = Qt.CursorShape.SizeBDiagCursor
    ALL = Qt.CursorShape.SizeAllCursor

    @staticmethod
    def _vector(degrees):
        return math.cos(math.radians(degrees)), math.sin(math.radians(degrees))

    def test_cursor_for_direction_bands_follow_the_direction_angle(self):
        H, F, V, B = self.H, self.F, self.V, self.B
        table = [
            (0, H),
            (10, H),
            (22, H),
            (23, F),
            (45, F),
            (67, F),
            (68, V),
            (90, V),
            (112, V),
            (113, B),
            (135, B),
            (157, B),
            (158, H),
            (170, H),
            (180, H),
            (-10, H),
            (-22, H),
            (-23, B),
            (-45, B),
            (-67, B),
            (-68, V),
            (-90, V),
            (-112, V),
            (-113, F),
            (-135, F),
            (-157, F),
            (-158, H),
        ]
        for degrees, expected in table:
            with self.subTest(degrees=degrees):
                self.assertEqual(cursor_for_direction(*self._vector(degrees)), expected)

    def test_resize_cursor_for_edge_uses_the_edge_perpendicular(self):
        H, F, V, B = self.H, self.F, self.V, self.B
        # Edge direction angle -> cursor for the perpendicular (edge angle + 90).
        table = [
            (0, V),
            (10, V),
            (20, V),
            (25, B),
            (45, B),
            (60, B),
            (70, H),
            (90, H),
            (110, H),
            (115, F),
            (135, F),
            (150, F),
            (160, V),
            (180, V),
            (-20, V),
            (-25, F),
            (-45, F),
            (-65, F),
            (-70, H),
            (-90, H),
            (112.6, F),
            (-112, H),
        ]
        for degrees, expected in table:
            with self.subTest(degrees=degrees):
                self.assertEqual(
                    resize_cursor_for_edge(*self._vector(degrees)), expected
                )

    def test_zero_length_vectors_use_the_move_cursor_below_a_nanounit_threshold(self):
        for function in (cursor_for_direction, resize_cursor_for_edge):
            with self.subTest(function=function.__name__):
                self.assertEqual(function(0.0, 0.0), self.ALL)
                self.assertEqual(function(5e-10, -5e-10), self.ALL)
                self.assertNotEqual(function(1.5e-9, 0.0), self.ALL)
                self.assertNotEqual(function(0.0, 1.5e-9), self.ALL)
                self.assertNotEqual(function(5e-10, 1.0), self.ALL)
                self.assertNotEqual(function(1.0, 5e-10), self.ALL)
                # The threshold is strict: a component of exactly 1e-9 is a direction.
                self.assertNotEqual(function(1e-9, 0.0), self.ALL)
                self.assertNotEqual(function(0.0, 1e-9), self.ALL)


class PolygonCentroidTests(unittest.TestCase):
    def test_centroid_of_trapezoid_with_unit_area_differs_from_vertex_mean(self):
        # Area exactly 1.0; centroid y = 5/12 while the vertex mean y is 0.5.
        pos = [0.0, 0.0, 1.5, 0.0, 1.0, 1.0, 0.5, 1.0]
        x, y = polygon_centroid(pos, 4)
        self.assertAlmostEqual(x, 0.75, places=9)
        self.assertAlmostEqual(y, 5.0 / 12.0, places=9)

    def test_centroid_is_independent_of_winding(self):
        clockwise = [0.0, 0.0, 6.0, 0.0, 6.0, 2.0, 0.0, 2.0]
        counter = [0.0, 2.0, 6.0, 2.0, 6.0, 0.0, 0.0, 0.0]
        self.assertEqual(polygon_centroid(clockwise, 4), (3.0, 1.0))
        self.assertEqual(polygon_centroid(counter, 4), (3.0, 1.0))

    def test_degenerate_polygon_falls_back_to_the_vertex_mean(self):
        # Collinear vertices have zero area; the mean of (0,0),(1,2),(5,10) is (2,4).
        self.assertEqual(
            polygon_centroid([0.0, 0.0, 1.0, 2.0, 5.0, 10.0], 3), (2.0, 4.0)
        )

    def test_degenerate_fallback_averages_only_the_first_n_vertices(self):
        pos = [0.0, 0.0, 1.0, 2.0, 5.0, 10.0, 100.0, 100.0]
        self.assertEqual(polygon_centroid(pos, 3), (2.0, 4.0))

    def test_only_the_first_n_vertices_are_used(self):
        pos = [0.0, 0.0, 4.0, 0.0, 4.0, 4.0, 0.0, 4.0, 999.0, 999.0]
        self.assertEqual(polygon_centroid(pos, 4), (2.0, 2.0))


class RotatePositionCoordsTests(unittest.TestCase):
    def assertCoords(self, actual, expected):
        self.assertEqual(len(actual), len(expected), msg=repr(actual))
        for index, (a, e) in enumerate(zip(actual, expected)):
            self.assertAlmostEqual(
                a, e, places=9, msg="index %d: %r vs %r" % (index, actual, expected)
            )

    def test_empty_position_returns_an_empty_copy(self):
        pos = []
        result = rotate_position_coords(pos, 45.0)
        self.assertEqual(result, [])
        self.assertIsNot(result, pos)

    def test_points_rotate_about_the_bounding_box_centre_by_default(self):
        pos = [0.0, 0.0, 4.0, 0.0, 4.0, 2.0]
        self.assertCoords(
            rotate_position_coords(pos, 90.0), [3.0, -1.0, 3.0, 3.0, 1.0, 3.0]
        )
        self.assertCoords(
            rotate_position_coords(pos, 180.0), [4.0, 2.0, 0.0, 2.0, 0.0, 0.0]
        )

    def test_rotation_follows_the_standard_matrix_for_an_oblique_angle(self):
        root3 = math.sqrt(3.0)
        pos = [0.0, 0.0, 4.0, 0.0, 4.0, 2.0]
        expected = [
            2.5 - root3,
            -root3 / 2.0,
            2.5 + root3,
            2.0 - root3 / 2.0,
            1.5 + root3,
            2.0 + root3 / 2.0,
        ]
        self.assertCoords(rotate_position_coords(pos, 30.0), expected)

    def test_trailing_values_beyond_complete_points_are_preserved(self):
        pos = [0.0, 0.0, 4.0, 0.0, 4.0, 2.0, 9.5]
        result = rotate_position_coords(pos, 90.0)
        self.assertCoords(result, [3.0, -1.0, 3.0, 3.0, 1.0, 3.0, 9.5])
        self.assertEqual(pos, [0.0, 0.0, 4.0, 0.0, 4.0, 2.0, 9.5])

    def test_linear_rotation_moves_only_the_two_end_points_about_their_midpoint(self):
        pos = [0.0, 0.0, 4.0, 0.0, 100.0, 100.0]
        self.assertCoords(
            rotate_position_coords(pos, 90.0, is_linear=True),
            [2.0, -2.0, 2.0, 2.0, 100.0, 100.0],
        )
        self.assertCoords(
            rotate_position_coords([0.0, 0.0, 4.0, 0.0], 90.0, is_linear=True),
            [2.0, -2.0, 2.0, 2.0],
        )
        # Midpoint (3, 5) with every coordinate distinct, so an x/y mix-up shows.
        self.assertCoords(
            rotate_position_coords(
                [1.0, 2.0, 5.0, 8.0, 100.0, 100.0], 90.0, is_linear=True
            ),
            [6.0, 3.0, 0.0, 7.0, 100.0, 100.0],
        )

    def test_single_point_linear_rotation_falls_back_to_the_bounding_box(self):
        self.assertCoords(
            rotate_position_coords([3.0, 4.0], 90.0, is_linear=True), [3.0, 4.0]
        )

    def test_area_rotation_pivots_on_the_centroid_but_other_shapes_on_the_box(self):
        triangle = [0.0, 0.0, 6.0, 0.0, 0.0, 3.0]
        # centroid (2, 1) vs bounding-box centre (3, 1.5): half turn maps p to 2*c - p.
        self.assertCoords(
            rotate_position_coords(triangle, 180.0, is_area=True),
            [4.0, 2.0, -2.0, 2.0, 4.0, -1.0],
        )
        self.assertCoords(
            rotate_position_coords(triangle, 180.0),
            [6.0, 3.0, 0.0, 3.0, 6.0, 0.0],
        )

    def test_two_point_area_rotates_like_a_segment_about_its_midpoint(self):
        self.assertCoords(
            rotate_position_coords([0.0, 0.0, 4.0, 0.0], 180.0, is_area=True),
            [4.0, 0.0, 0.0, 0.0],
        )

    def test_curved_rotation_pivots_on_the_processed_curve_centre_and_moves_two_points(
        self,
    ):
        geometry = _CurvedGeometry((10.0, 20.0, 30.0, 40.0, 3.0, 6.0))
        pos = [1.0, 2.0, 7.0, 4.0, 5.0, 9.0, 0.5]
        result = rotate_position_coords(pos, 90.0, is_curved=True, linear_geom=geometry)
        self.assertEqual(geometry.calls, [(pos, 1.0, 2.0, 7.0, 4.0, 5.0, 9.0)])
        # Only the first two points rotate about the processed centre (3, 6); the
        # control point (5, 9) and the trailing bulge value are untouched.
        self.assertCoords(result, [7.0, 4.0, 5.0, 10.0, 5.0, 9.0, 0.5])

    def test_curved_rotation_uses_the_full_rotation_matrix(self):
        root3 = math.sqrt(3.0)
        geometry = _CurvedGeometry((10.0, 20.0, 30.0, 40.0, 3.0, 6.0))
        pos = [1.0, 2.0, 7.0, 4.0, 5.0, 9.0]
        result = rotate_position_coords(pos, 30.0, is_curved=True, linear_geom=geometry)
        self.assertCoords(
            result,
            [5.0 - root3, 5.0 - 2.0 * root3, 4.0 + 2.0 * root3, 8.0 - root3, 5.0, 9.0],
        )

    def test_curved_rotation_requires_the_curved_flag(self):
        geometry = _CurvedGeometry((10.0, 20.0, 30.0, 40.0, 3.0, 6.0))
        pos = [1.0, 2.0, 7.0, 4.0, 5.0, 9.0]
        result = rotate_position_coords(pos, 180.0, linear_geom=geometry)
        self.assertEqual(geometry.calls, [])
        # Bounding-box pivot (4, 5.5), not the processed curve centre.
        self.assertCoords(result, [7.0, 9.0, 1.0, 7.0, 3.0, 2.0])
        self.assertCoords(
            rotate_position_coords(pos, 180.0, is_curved=False, linear_geom=geometry),
            [7.0, 9.0, 1.0, 7.0, 3.0, 2.0],
        )

    def test_curved_rotation_takes_precedence_over_linear(self):
        geometry = _CurvedGeometry((0.0, 0.0, 0.0, 0.0, 2.0, 3.0))
        pos = [0.0, 0.0, 4.0, 0.0, 2.0, 3.0]
        result = rotate_position_coords(
            pos, 90.0, is_curved=True, is_linear=True, linear_geom=geometry
        )
        self.assertCoords(result, [5.0, 1.0, 5.0, 5.0, 2.0, 3.0])

    def test_curved_flag_without_geometry_or_enough_values_is_ignored(self):
        geometry = _CurvedGeometry((0.0, 0.0, 0.0, 0.0, 9.0, 9.0))
        four = [0.0, 0.0, 4.0, 0.0]
        five = [0.0, 0.0, 4.0, 0.0, 7.0]
        self.assertCoords(
            rotate_position_coords(four, 180.0, is_curved=True, linear_geom=geometry),
            [4.0, 0.0, 0.0, 0.0],
        )
        self.assertCoords(
            rotate_position_coords(five, 180.0, is_curved=True, linear_geom=geometry),
            [4.0, 0.0, 0.0, 0.0, 7.0],
        )
        self.assertEqual(geometry.calls, [])
        triangle = [0.0, 0.0, 4.0, 0.0, 2.0, 3.0]
        self.assertCoords(
            rotate_position_coords(triangle, 180.0, is_curved=True, linear_geom=None),
            [4.0, 3.0, 0.0, 3.0, 2.0, 0.0],
        )


class RotateAndMirrorPointsTests(unittest.TestCase):
    def test_rotate_points_around_an_explicit_centre(self):
        result = rotate_points_around([3.0, 2.0, 1.0, 0.0, 7.0], 90.0, 1.0, 1.0)
        self.assertEqual(len(result), 5)
        for actual, expected in zip(result, [0.0, 3.0, 2.0, 1.0, 7.0]):
            self.assertAlmostEqual(actual, expected, places=9)

    def test_rotate_points_around_oblique_angle_uses_both_trig_terms(self):
        root3 = math.sqrt(3.0)
        result = rotate_points_around([3.0, 1.0], 30.0, 1.0, 0.0)
        self.assertAlmostEqual(result[0], 0.5 + root3, places=9)
        self.assertAlmostEqual(result[1], 1.0 + root3 / 2.0, places=9)

    def test_rotate_points_around_empty_input_returns_an_empty_copy(self):
        pos = []
        result = rotate_points_around(pos, 90.0, 0.0, 0.0)
        self.assertEqual(result, [])
        self.assertIsNot(result, pos)

    def test_mirror_points_around_reflects_only_the_requested_axis(self):
        pos = [1.0, 2.0, 5.0, 6.0, 9.0]
        self.assertEqual(
            mirror_points_around(pos, 3.0, 4.0, True), [5.0, 2.0, 1.0, 6.0, 9.0]
        )
        self.assertEqual(
            mirror_points_around(pos, 3.0, 4.0, False), [1.0, 6.0, 5.0, 2.0, 9.0]
        )
        self.assertEqual(pos, [1.0, 2.0, 5.0, 6.0, 9.0])

    def test_mirror_points_around_empty_input_returns_an_empty_copy(self):
        pos = []
        result = mirror_points_around(pos, 3.0, 4.0, True)
        self.assertEqual(result, [])
        self.assertIsNot(result, pos)

    def test_mirror_position_coords_negates_the_curve_bulge_only_when_curved(self):
        pos = [0.0, 0.0, 2.0, 0.0, 1.0, 1.0, 0.5]
        self.assertEqual(
            mirror_position_coords(pos, 1.0, 0.0, True, is_curved=True),
            [2.0, 0.0, 0.0, 0.0, 1.0, 1.0, -0.5],
        )
        self.assertEqual(
            mirror_position_coords(pos, 1.0, 0.0, True),
            [2.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.5],
        )
        self.assertEqual(
            mirror_position_coords(pos, 1.0, 0.0, False, is_curved=True),
            [0.0, 0.0, 2.0, 0.0, 1.0, -1.0, -0.5],
        )

    def test_mirror_position_coords_curved_without_a_bulge_value_is_just_a_mirror(self):
        pos = [0.0, 0.0, 2.0, 0.0, 1.0, 1.0]
        self.assertEqual(
            mirror_position_coords(pos, 1.0, 0.0, True, is_curved=True),
            [2.0, 0.0, 0.0, 0.0, 1.0, 1.0],
        )


class MirrorSinglePointTests(unittest.TestCase):
    def test_mirror_points_around_mirrors_a_lone_point_on_each_axis(self):
        # One complete point is still mirrored; only an empty list is returned as-is.
        pos = [1.0, 2.0]
        self.assertEqual(mirror_points_around(pos, 3.0, 4.0, True), [5.0, 2.0])
        self.assertEqual(mirror_points_around(pos, 3.0, 4.0, False), [1.0, 6.0])
        self.assertEqual(pos, [1.0, 2.0])
        # A dangling coordinate without its partner is not a point and stays put.
        self.assertEqual(mirror_points_around([1.0], 3.0, 4.0, True), [1.0])
