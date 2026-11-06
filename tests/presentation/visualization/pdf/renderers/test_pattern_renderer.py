import math
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.visualization.pdf.renderers import pattern_renderer
from PySide6 import QtCore, QtGui, QtWidgets


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class PatternRendererConditionBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls._quit_on_last_window_closed = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls._quit_on_last_window_closed)

    def tearDown(self):
        self.app.processEvents()

    def test_pattern_spacing_rejects_invalid_converted_values(self):
        class InvalidCoordinateSystem:
            def __init__(self, converted, view_scale=1.0):
                self.converted = converted
                self.page_info = {"view_scale": view_scale}

            def ost_to_pdf_points(self, _value):
                return self.converted

        for converted, view_scale in (
            (-2.0, 1.0),
            (0.0, 1.0),
            (float("nan"), 1.0),
            (2.0, float("inf")),
            (2.0, 0.0),
            (float("inf"), 1.0),
        ):
            with self.subTest(converted=converted, view_scale=view_scale):
                self.assertEqual(
                    pattern_renderer._convert_spacing(
                        2.0, InvalidCoordinateSystem(converted, view_scale)
                    ),
                    72.0,
                )
        coord_system = InvalidCoordinateSystem(3.0, 2.0)
        self.assertEqual(pattern_renderer._convert_spacing(2.0, coord_system), 6.0)
        self.assertEqual(pattern_renderer._convert_spacing(2.0, None), 2.0)
        for invalid_spacing in (0.0, -1.0, float("nan"), float("inf"), None, "abc"):
            with self.subTest(invalid_spacing=invalid_spacing):
                self.assertEqual(
                    pattern_renderer._convert_spacing(invalid_spacing, coord_system),
                    72.0,
                )

    def test_fixed_diagonal_intersections_count_shared_vertices_once(self):
        square = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]]
        backward = pattern_renderer._find_backward_diagonal_intersections(0.0, square)
        forward = pattern_renderer._find_forward_diagonal_intersections(10.0, square)
        self.assertEqual(backward, [(0.0, 0.0), (10.0, 10.0)])
        self.assertEqual(forward, [(0.0, 10.0), (10.0, 0.0)])
        self.assertEqual(
            pattern_renderer._find_backward_diagonal_intersections(3.0, square),
            [(3.0, 0.0), (10.0, 7.0)],
        )
        self.assertEqual(
            pattern_renderer._find_forward_diagonal_intersections(5.0, square),
            [(0.0, 5.0), (5.0, 0.0)],
        )
        self.assertEqual(
            pattern_renderer._find_backward_diagonal_intersections(20.0, square), []
        )


def _segments(items):
    """Each item's path as ((x1, y1), (x2, y2)); degenerate items are dropped."""
    result = []
    for item in items:
        path = item.path()
        points = [
            (path.elementAt(i).x, path.elementAt(i).y)
            for i in range(path.elementCount())
        ]
        if len(points) == 2:
            result.append(tuple(points))
    return result


def _rectangle(width, height, x=0.0, y=0.0):
    path = QtGui.QPainterPath()
    path.addRect(x, y, width, height)
    return path


class PatternRendererGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def assertSegments(self, actual, expected):
        self.assertEqual(len(actual), len(expected), actual)
        for got, want in zip(actual, expected):
            for got_point, want_point in zip(got, want):
                self.assertAlmostEqual(got_point[0], want_point[0], places=3)
                self.assertAlmostEqual(got_point[1], want_point[1], places=3)

    def items(self, path, pattern, spacing=20.0, **kwargs):
        return pattern_renderer.create_pattern_items(
            path, pattern, QtGui.QColor("red"), spacing, 1.0, **kwargs
        )

    def test_only_line_patterns_draw_line_items_and_only_others_get_a_brush(self):
        from ost_visualizer.domain.entities import pattern as pt

        for pattern in (pt.NONE, pt.SOLID, pt.TRANSPARENT):
            with self.subTest(pattern=pattern):
                self.assertEqual(self.items(_rectangle(100, 60), pattern), [])
        colour = QtGui.QColor(10, 20, 30)
        for pattern in pt.LINE_PATTERNS | {pt.NONE}:
            with self.subTest(brush_pattern=pattern):
                self.assertIsNone(pattern_renderer.get_pattern_fill_brush(pattern, colour))
        for pattern in (pt.SOLID, pt.TRANSPARENT):
            brush = pattern_renderer.get_pattern_fill_brush(pattern, colour, 0.25)
            self.assertEqual(
                (brush.color().red(), brush.color().green(), brush.color().blue()),
                (10, 20, 30),
            )
            self.assertAlmostEqual(brush.color().alphaF(), 0.25, places=2)
        self.assertEqual(colour.alpha(), 255)

    def test_horizontal_and_vertical_lines_span_the_shape_at_the_spacing(self):
        from ost_visualizer.domain.entities import pattern as pt

        path = _rectangle(100, 60)
        self.assertSegments(
            _segments(self.items(path, pt.HORIZONTAL, 20.0)),
            [((0, 20), (100, 20)), ((0, 40), (100, 40))],
        )
        self.assertSegments(
            _segments(self.items(path, pt.VERTICAL, 30.0)),
            [((30, 0), (30, 60)), ((60, 0), (60, 60)), ((90, 0), (90, 60))],
        )

    def test_offset_shapes_are_filled_relative_to_their_own_bounds(self):
        from ost_visualizer.domain.entities import pattern as pt

        self.assertSegments(
            _segments(self.items(_rectangle(100, 60, 200, 300), pt.HORIZONTAL, 25.0)),
            [((200, 325), (300, 325)), ((200, 350), (300, 350))],
        )

    def test_diagonal_lines_run_corner_to_corner_at_the_diagonal_spacing(self):
        from ost_visualizer.domain.entities import pattern as pt

        square = _rectangle(10, 10)
        # Spacing 5 is measured along an axis, so diagonals are 5*sqrt(2) apart.
        self.assertSegments(
            _segments(self.items(square, pt.BACKWARD_DIAG, 5.0)),
            [((0, 2.929), (7.071, 10)), ((4.142, 0), (10, 5.858))],
        )
        self.assertSegments(
            _segments(self.items(square, pt.FORWARD_DIAG, 5.0)),
            [((0, 7.071), (7.071, 0)), ((4.142, 10), (10, 4.142))],
        )

    def test_crosshatch_patterns_combine_both_line_directions(self):
        from ost_visualizer.domain.entities import pattern as pt

        path = _rectangle(100, 60)
        cross = _segments(self.items(path, pt.CROSSHATCH, 30.0))
        self.assertEqual(
            cross,
            _segments(self.items(path, pt.HORIZONTAL, 30.0))
            + _segments(self.items(path, pt.VERTICAL, 30.0)),
        )
        self.assertEqual(len(cross), 1 + 3)
        diag = _segments(self.items(path, pt.DIAG_CROSSHATCH, 30.0))
        self.assertEqual(
            diag,
            _segments(self.items(path, pt.BACKWARD_DIAG, 30.0))
            + _segments(self.items(path, pt.FORWARD_DIAG, 30.0)),
        )
        directions = {
            round((end[1] - start[1]) / (end[0] - start[0]))
            for start, end in diag
        }
        self.assertEqual(directions, {1, -1})

    def test_pen_is_a_flat_cosmetic_line_in_the_requested_colour_and_width(self):
        from ost_visualizer.domain.entities import pattern as pt

        items = pattern_renderer.create_pattern_items(
            _rectangle(100, 60), pt.HORIZONTAL, QtGui.QColor(1, 2, 3), 20.0, 2.5
        )
        self.assertEqual(len(items), 2)
        for item in items:
            pen = item.pen()
            self.assertEqual(pen.color().getRgb()[:3], (1, 2, 3))
            self.assertEqual(pen.widthF(), 2.5)
            self.assertTrue(pen.isCosmetic())
            self.assertEqual(pen.capStyle(), QtCore.Qt.PenCapStyle.FlatCap)

    def test_oriented_patterns_rotate_the_hatch_with_the_shape(self):
        from ost_visualizer.domain.entities import pattern as pt

        path = _rectangle(100, 60)
        self.assertSegments(
            _segments(self.items(path, pt.HORIZONTAL, 20.0, orientation_angle=0.0)),
            _segments(self.items(path, pt.HORIZONTAL, 20.0)),
        )
        vertical = _segments(
            self.items(path, pt.HORIZONTAL, 20.0, orientation_angle=math.pi / 2)
        )
        self.assertSegments(
            sorted(vertical),
            [((20, 0), (20, 60)), ((40, 0), (40, 60)), ((60, 0), (60, 60)), ((80, 0), (80, 60))],
        )
        quarter = _segments(
            self.items(path, pt.VERTICAL, 20.0, orientation_angle=math.pi / 2)
        )
        # Rotating by pi leaves a ~1e-14 rounding error, which puts one extra
        # line on the shape's own top edge (y ~ 0); that artifact is left out here.
        interior = [
            tuple(sorted(segment))
            for segment in quarter
            if min(segment[0][1], segment[1][1]) > 1e-6
        ]
        self.assertSegments(
            sorted(interior),
            [((0, 20), (100, 20)), ((0, 40), (100, 40))],
        )
        self.assertLessEqual(len(quarter) - len(interior), 1)

    def test_oriented_diagonals_and_crosshatches_use_the_documented_angles(self):
        from ost_visualizer.domain.entities import pattern as pt

        square = _rectangle(60, 60)
        expected_slopes = {
            pt.BACKWARD_DIAG: {1},
            pt.FORWARD_DIAG: {-1},
            pt.CROSSHATCH: {0, None},
            pt.DIAG_CROSSHATCH: {1, -1},
        }
        for pattern, slopes in expected_slopes.items():
            with self.subTest(pattern=pattern):
                segments = _segments(
                    self.items(square, pattern, 20.0, orientation_angle=0.0)
                )
                self.assertTrue(segments)
                found = set()
                for start, end in segments:
                    dx, dy = end[0] - start[0], end[1] - start[1]
                    found.add(None if abs(dx) < 1e-6 else round(dy / dx, 6) + 0.0)
                self.assertEqual(found, slopes)
        self.assertSegments(
            _segments(self.items(square, pt.BACKWARD_DIAG, 20.0, orientation_angle=0.0)),
            [
                ((31.716, 0), (60, 28.284)),
                ((3.431, 0), (60, 56.569)),
                ((0, 24.853), (35.147, 60)),
                ((0, 53.137), (6.863, 60)),
            ],
        )

    def test_grid_items_use_the_vertical_and_horizontal_spacings_separately(self):
        grid = pattern_renderer.create_grid_items(
            _rectangle(100, 60), QtGui.QColor("blue"), 30.0, 20.0, 1.5
        )
        self.assertSegments(
            _segments(grid),
            [
                ((0, 20), (100, 20)),
                ((0, 40), (100, 40)),
                ((30, 0), (30, 60)),
                ((60, 0), (60, 60)),
                ((90, 0), (90, 60)),
            ],
        )
        for item in grid:
            self.assertEqual(item.pen().widthF(), 1.5)
            self.assertTrue(item.pen().isCosmetic())
            self.assertEqual(
                item.pen().capStyle(), QtCore.Qt.PenCapStyle.FlatCap
            )
        self.assertEqual(
            pattern_renderer.create_grid_items(
                QtGui.QPainterPath(), QtGui.QColor("blue"), 30.0, 20.0, 1.0
            ),
            [],
        )

    def test_holes_split_hatch_lines_into_separate_segments(self):
        from ost_visualizer.domain.entities import pattern as pt

        path = _rectangle(100, 60)
        path.addRect(40, 10, 20, 40)
        self.assertSegments(
            _segments(self.items(path, pt.HORIZONTAL, 20.0)),
            [
                ((0, 20), (40, 20)),
                ((60, 20), (100, 20)),
                ((0, 40), (40, 40)),
                ((60, 40), (100, 40)),
            ],
        )

    def test_contours_drop_closing_duplicates_and_degenerate_subpaths(self):
        path = QtGui.QPainterPath()
        path.moveTo(0, 0)
        path.lineTo(10, 0)
        path.lineTo(10, 10)
        path.lineTo(0, 0)
        path.moveTo(20, 20)
        path.lineTo(30, 20)
        path.moveTo(40, 40)
        path.lineTo(50, 40)
        path.lineTo(50, 50)
        path.lineTo(40, 50)
        self.assertEqual(
            pattern_renderer._extract_path_contours(path),
            [
                [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)],
                [(40.0, 40.0), (50.0, 40.0), (50.0, 50.0), (40.0, 50.0)],
            ],
        )
        self.assertEqual(
            pattern_renderer._extract_path_contours(QtGui.QPainterPath()), []
        )
        self.assertTrue(pattern_renderer._same_point((1.0, 1.0), (1.0 + 5e-10, 1.0)))
        self.assertFalse(pattern_renderer._same_point((1.0, 1.0), (1.0 + 2e-9, 1.0)))
        self.assertFalse(pattern_renderer._same_point((1.0, 1.0), (1.0, 1.0 + 2e-9)))
        degenerate = QtGui.QPainterPath()
        degenerate.moveTo(0, 0)
        degenerate.lineTo(10, 0)
        self.assertEqual(self.items(degenerate, 2), [])

    def test_edge_iteration_closes_every_contour(self):
        contours = [[(0, 0), (4, 0), (4, 4)], [(10, 10), (12, 10), (12, 12)]]
        self.assertEqual(
            list(pattern_renderer._iter_contour_edges(contours)),
            [
                ((0, 0), (4, 0)),
                ((4, 0), (4, 4)),
                ((4, 4), (0, 0)),
                ((10, 10), (12, 10)),
                ((12, 10), (12, 12)),
                ((12, 12), (10, 10)),
            ],
        )

    def test_spacing_is_converted_from_ost_units_through_the_coordinate_system(self):
        class Coordinates:
            page_info = {"view_scale": 2.0}

            @staticmethod
            def ost_to_pdf_points(value):
                return value * 3.0

        # 5 OST units -> 15 pt -> 30 px at view scale 2.
        self.assertSegments(
            _segments(
                self.items(
                    _rectangle(100, 100),
                    2,
                    5.0,
                    coord_system=Coordinates(),
                )
            ),
            [((0, y), (100, y)) for y in (30, 60, 90)],
        )
        grid = pattern_renderer.create_grid_items(
            _rectangle(100, 100),
            QtGui.QColor("red"),
            50.0,
            25.0,
            1.0,
            Coordinates(),
        )
        # 25 OST -> 150 px (no horizontal line fits); 50 OST -> 300 px (none fits).
        self.assertEqual(grid, [])
        grid = pattern_renderer.create_grid_items(
            _rectangle(100, 100), QtGui.QColor("red"), 10.0, 5.0, 1.0, Coordinates()
        )
        self.assertSegments(
            _segments(grid),
            [((0, 30), (100, 30)), ((0, 60), (100, 60)), ((0, 90), (100, 90))]
            + [((60, 0), (60, 100))],
        )

    def test_a_degenerate_flat_shape_yields_no_parallel_lines(self):
        self.assertEqual(
            pattern_renderer._create_parallel_lines([], 0.0, 10.0, QtGui.QPen()), []
        )


def _polygon(points):
    path = QtGui.QPainterPath()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    path.closeSubpath()
    return path


class PatternRendererCoverageTests(unittest.TestCase):
    """Whole-shape coverage, holes, vertex handling and pens of every generator."""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def items(self, path, pattern, spacing=20.0, **kwargs):
        return pattern_renderer.create_pattern_items(
            path, pattern, QtGui.QColor("green"), spacing, 2.0, **kwargs
        )

    def test_every_generator_gives_each_item_the_requested_pen(self):
        from ost_visualizer.domain.entities import pattern as pt

        path = _rectangle(100, 60)
        for pattern in pt.LINE_PATTERNS:
            for angle in (None, 0.3):
                with self.subTest(pattern=pattern, orientation=angle):
                    items = self.items(path, pattern, 20.0, orientation_angle=angle)
                    self.assertTrue(items)
                    for item in items:
                        pen = item.pen()
                        self.assertEqual(pen.color().getRgb()[:3], (0, 128, 0))
                        self.assertEqual(pen.widthF(), 2.0)
                        self.assertTrue(pen.isCosmetic())
                        self.assertEqual(pen.capStyle(), QtCore.Qt.PenCapStyle.FlatCap)

    def test_diagonal_helpers_default_to_backward_lines(self):
        contours = pattern_renderer._extract_path_contours(_rectangle(60, 60))
        pen = QtGui.QPen()
        default = _segments(
            pattern_renderer._create_diagonal_lines(contours, 0, 0, 60, 60, 20.0, pen)
        )
        backward = _segments(
            pattern_renderer._create_diagonal_lines(
                contours, 0, 0, 60, 60, 20.0, pen, backward=True
            )
        )
        forward = _segments(
            pattern_renderer._create_diagonal_lines(
                contours, 0, 0, 60, 60, 20.0, pen, backward=False
            )
        )
        self.assertEqual(default, backward)
        self.assertNotEqual(default, forward)

    def test_diagonals_cover_the_whole_shape_at_an_even_spacing(self):
        from ost_visualizer.domain.entities import pattern as pt

        spacing = 10.0
        step = spacing * math.sqrt(2)
        x0, y0 = 7.0, 11.0
        for width, height in ((90, 30), (30, 90), (60, 60)):
            shape = _rectangle(width, height, x0, y0)
            # Diagonal families: (pattern, line parameter, its range over the shape).
            families = (
                (
                    pt.BACKWARD_DIAG,
                    lambda p: p[0] - p[1],
                    x0 - (y0 + height),
                    x0 + width - y0,
                ),
                (
                    pt.FORWARD_DIAG,
                    lambda p: p[0] + p[1],
                    x0 + y0,
                    x0 + width + y0 + height,
                ),
            )
            for pattern, parameter, lowest, highest in families:
                with self.subTest(size=(width, height), pattern=pattern):
                    segments = _segments(self.items(shape, pattern, spacing))
                    values = sorted(parameter(start) for start, _end in segments)
                    # The first and last lines lie within one step of the shape's
                    # extreme corners, so no part of the shape is left unhatched.
                    self.assertLess(values[0] - lowest, step + 1e-6)
                    self.assertLess(highest - values[-1], step + 1e-6)
                    for earlier, later in zip(values, values[1:]):
                        self.assertAlmostEqual(later - earlier, step, places=6)
                    for start, end in segments:
                        self.assertAlmostEqual(
                            abs(end[0] - start[0]), abs(end[1] - start[1]), places=6
                        )
                        for x, y in (start, end):
                            self.assertTrue(x0 - 1e-6 <= x <= x0 + width + 1e-6)
                            self.assertTrue(y0 - 1e-6 <= y <= y0 + height + 1e-6)

    def test_holes_split_every_generator_into_separate_segments(self):
        from ost_visualizer.domain.entities import pattern as pt

        path = _rectangle(100, 100)
        path.addRect(30, 30, 40, 40)
        counts = {}
        for pattern in (pt.HORIZONTAL, pt.VERTICAL, pt.BACKWARD_DIAG, pt.FORWARD_DIAG):
            for angle in (None, 0.0):
                segments = _segments(self.items(path, pattern, 20.0, orientation_angle=angle))
                counts[(pattern, angle)] = segments
        for (pattern, angle), segments in counts.items():
            with self.subTest(pattern=pattern, orientation=angle):
                crossing_hole = [
                    segment
                    for segment in segments
                    if any(
                        30 < (start[0] + end[0]) / 2 < 70 and 30 < (start[1] + end[1]) / 2 < 70
                        for start, end in (segment,)
                    )
                ]
                # No hatch segment may pass through the middle of the hole.
                self.assertEqual(crossing_hole, [])
        horizontal = counts[(pt.HORIZONTAL, None)]
        self.assertEqual(
            [segment for segment in horizontal if segment[0][1] == 40.0],
            [((0.0, 40.0), (30.0, 40.0)), ((70.0, 40.0), (100.0, 40.0))],
        )
        vertical = counts[(pt.VERTICAL, None)]
        self.assertEqual(
            [segment for segment in vertical if segment[0][0] == 40.0],
            [((40.0, 0.0), (40.0, 30.0)), ((40.0, 70.0), (40.0, 100.0))],
        )

    def test_hatch_lines_run_from_the_lower_to_the_higher_coordinate(self):
        from ost_visualizer.domain.entities import pattern as pt

        # A path wound the other way round yields edge crossings in descending
        # order; the lines must still run low to high.
        reverse = _polygon([(0, 0), (0, 60), (100, 60), (100, 0)])
        for pattern, check in (
            (pt.HORIZONTAL, lambda s, e: s[0] < e[0]),
            (pt.VERTICAL, lambda s, e: s[1] < e[1]),
            (pt.BACKWARD_DIAG, lambda s, e: s[0] < e[0]),
            (pt.FORWARD_DIAG, lambda s, e: s[0] < e[0]),
        ):
            with self.subTest(pattern=pattern):
                segments = _segments(self.items(reverse, pattern, 20.0))
                self.assertTrue(segments)
                self.assertTrue(all(check(s, e) for s, e in segments), segments)

    def test_lines_through_vertices_count_each_crossing_once(self):
        from ost_visualizer.domain.entities import pattern as pt

        shape = _polygon([(0, 0), (100, 0), (100, 20), (50, 20), (50, 60), (0, 60)])
        horizontal = _segments(self.items(shape, pt.HORIZONTAL, 20.0))
        self.assertEqual(
            horizontal,
            [((0.0, 20.0), (50.0, 20.0)), ((0.0, 40.0), (50.0, 40.0))],
        )
        transposed = _polygon([(0, 0), (0, 100), (20, 100), (20, 50), (60, 50), (60, 0)])
        self.assertEqual(
            _segments(self.items(transposed, pt.VERTICAL, 20.0)),
            [((20.0, 0.0), (20.0, 50.0)), ((40.0, 0.0), (40.0, 50.0))],
        )
        # The oriented generator follows the same half-open rule as the plain one.
        oriented = _segments(self.items(shape, pt.HORIZONTAL, 20.0, orientation_angle=0.0))
        self.assertEqual(
            sorted(tuple(sorted(segment)) for segment in oriented),
            [((0.0, 20.0), (50.0, 20.0)), ((0.0, 40.0), (50.0, 40.0))],
        )

    def test_oriented_vertical_hatch_runs_down_the_shape_from_the_right(self):
        from ost_visualizer.domain.entities import pattern as pt

        segments = _segments(
            self.items(_rectangle(100, 60), pt.VERTICAL, 20.0, orientation_angle=0.0)
        )
        self.assertEqual(
            [tuple((round(x, 6), round(y, 6)) for x, y in s) for s in segments],
            [
                ((80.0, 0.0), (80.0, 60.0)),
                ((60.0, 0.0), (60.0, 60.0)),
                ((40.0, 0.0), (40.0, 60.0)),
                ((20.0, 0.0), (20.0, 60.0)),
            ],
        )
        cross = _segments(
            self.items(_rectangle(100, 60), pt.CROSSHATCH, 20.0, orientation_angle=0.0)
        )
        self.assertEqual(len(cross), 2 + 4)

    def test_parallel_lines_through_a_notched_hole_are_paired_correctly(self):
        path = _rectangle(100, 100)
        path.addRect(30, 30, 40, 40)
        contours = pattern_renderer._extract_path_contours(path)
        lines = pattern_renderer._create_parallel_lines(contours, 0.0, 20.0, QtGui.QPen())
        by_row = {}
        for segment in _segments(lines):
            by_row.setdefault(round(segment[0][1]), []).append(
                tuple(sorted((round(segment[0][0]), round(segment[1][0]))))
            )
        self.assertEqual(sorted(by_row[40]), [(0, 30), (70, 100)])
        self.assertEqual(by_row[20], [(0, 100)])

    def test_spacing_conversion_accepts_small_positive_values_and_survives_errors(self):
        for value in (1.0, 0.5, 1e-3):
            with self.subTest(value=value):
                self.assertEqual(pattern_renderer._convert_spacing(value, None), value)

        class Scaled:
            page_info = {"view_scale": 1.0}

            def __init__(self, converted):
                self.converted = converted

            def ost_to_pdf_points(self, _value):
                return self.converted

        self.assertEqual(pattern_renderer._convert_spacing(2.0, Scaled(1.0)), 1.0)
        self.assertEqual(pattern_renderer._convert_spacing(2.0, Scaled(0.5)), 0.5)

        class NoPageInfo:
            def ost_to_pdf_points(self, _value):
                return 5.0

        class Raising:
            page_info = {"view_scale": 1.0}

            def __init__(self, error):
                self.error = error

            def ost_to_pdf_points(self, _value):
                raise self.error

        for coord_system in (
            NoPageInfo(),
            Raising(AttributeError()),
            Raising(TypeError()),
            Raising(ValueError()),
            Raising(OverflowError()),
        ):
            with self.subTest(coord_system=type(coord_system).__name__):
                self.assertEqual(pattern_renderer._convert_spacing(2.0, coord_system), 72.0)
        for spacing in ("3", 3):
            self.assertEqual(pattern_renderer._convert_spacing(spacing, None), 3.0)

    def test_a_contour_that_returns_to_its_start_after_one_edge_is_degenerate(self):
        path = QtGui.QPainterPath()
        path.moveTo(0, 0)
        path.lineTo(10, 0)
        path.lineTo(0, 0)
        self.assertEqual(pattern_renderer._extract_path_contours(path), [])
        path = QtGui.QPainterPath()
        path.moveTo(0, 0)
        path.lineTo(0, 0)
        self.assertEqual(pattern_renderer._extract_path_contours(path), [])

    def test_same_point_compares_each_coordinate_against_its_own_counterpart(self):
        same = pattern_renderer._same_point
        self.assertTrue(same((0.0, 0.0), (1e-9, 0.0)))
        self.assertTrue(same((0.0, 0.0), (0.0, 1e-9)))
        self.assertFalse(same((0.0, 0.0), (1.1e-9, 0.0)))
        self.assertFalse(same((0.0, 0.0), (0.0, 1.1e-9)))
        self.assertTrue(same((1.0, 5.0), (1.0 + 5e-10, 5.0)))
        self.assertFalse(same((1.0, 5.0), (5.0, 1.0)))
        self.assertFalse(same((1.0, 1.0), (1.0, 5.0)))


class PatternRendererSlantedEdgeTests(unittest.TestCase):
    """Slanted edges, tips touching a hatch line, anchoring and hole pairing."""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def items(self, path, pattern, spacing, **kwargs):
        return pattern_renderer.create_pattern_items(
            path, pattern, QtGui.QColor("green"), spacing, 1.0, **kwargs
        )

    def assertSegments(self, actual, expected):
        self.assertEqual(len(actual), len(expected), actual)
        for got, want in zip(actual, expected):
            for got_point, want_point in zip(got, want):
                self.assertAlmostEqual(got_point[0], want_point[0], places=6)
                self.assertAlmostEqual(got_point[1], want_point[1], places=6)

    def test_hatch_lines_meet_slanted_edges_at_the_exact_crossing(self):
        from ost_visualizer.domain.entities import pattern as pt

        triangle = _polygon([(0, 0), (100, 0), (0, 100)])
        self.assertSegments(
            _segments(self.items(triangle, pt.HORIZONTAL, 25.0)),
            [((0, 25), (75, 25)), ((0, 50), (50, 50)), ((0, 75), (25, 75))],
        )
        self.assertSegments(
            _segments(self.items(triangle, pt.VERTICAL, 25.0)),
            [((25, 0), (25, 75)), ((50, 0), (50, 50)), ((75, 0), (75, 25))],
        )
        self.assertSegments(
            sorted(
                tuple(sorted(s))
                for s in _segments(
                    self.items(triangle, pt.HORIZONTAL, 25.0, orientation_angle=0.0)
                )
            ),
            [((0, 25), (75, 25)), ((0, 50), (50, 50)), ((0, 75), (25, 75))],
        )

    def test_a_vertex_touching_a_hatch_line_counts_as_one_crossing(self):
        from ost_visualizer.domain.entities import pattern as pt

        diamond = _polygon([(50, 0), (100, 50), (50, 100), (0, 50)])
        self.assertSegments(
            _segments(self.items(diamond, pt.HORIZONTAL, 25.0)),
            [((25, 25), (75, 25)), ((0, 50), (100, 50)), ((25, 75), (75, 75))],
        )
        self.assertSegments(
            _segments(self.items(diamond, pt.VERTICAL, 25.0)),
            [((25, 25), (25, 75)), ((50, 0), (50, 100)), ((75, 25), (75, 75))],
        )
        for angle, expected in (
            (
                0.0,
                [((25, 25), (75, 25)), ((0, 50), (100, 50)), ((25, 75), (75, 75))],
            ),
            (
                math.pi / 2,
                [((25, 25), (25, 75)), ((50, 0), (50, 100)), ((75, 25), (75, 75))],
            ),
        ):
            with self.subTest(angle=angle):
                oriented = _segments(
                    self.items(diamond, pt.HORIZONTAL, 25.0, orientation_angle=angle)
                )
                self.assertEqual(len(oriented), 3)
                self.assertSegments(
                    sorted(
                        tuple(sorted((round(a, 6), round(b, 6)) for a, b in s))
                        for s in oriented
                    ),
                    sorted(expected),
                )

    def test_oriented_crosshatch_lists_the_horizontal_then_the_vertical_family(self):
        from ost_visualizer.domain.entities import pattern as pt

        segments = _segments(
            self.items(_rectangle(100, 60), pt.CROSSHATCH, 20.0, orientation_angle=0.0)
        )
        self.assertSegments(
            segments,
            [
                ((0, 20), (100, 20)),
                ((0, 40), (100, 40)),
                ((80, 0), (80, 60)),
                ((60, 0), (60, 60)),
                ((40, 0), (40, 60)),
                ((20, 0), (20, 60)),
            ],
        )

    def test_diagonal_hatch_is_anchored_to_the_shape_and_pairs_holes(self):
        from ost_visualizer.domain.entities import pattern as pt

        spacing = 10.0
        step = spacing * math.sqrt(2)
        path = _rectangle(100, 100, 7.0, 11.0)
        path.addRect(37.0, 41.0, 40.0, 40.0)
        box_diag = math.hypot(100.0, 100.0)
        for pattern, parameter, anchor, hole_low, hole_high in (
            (
                pt.BACKWARD_DIAG,
                lambda p: p[0] - p[1],
                7.0 - (11.0 + 100.0) - box_diag,
                (37.0 - (41.0 + 40.0)),
                (37.0 + 40.0 - 41.0),
            ),
            (
                pt.FORWARD_DIAG,
                lambda p: p[0] + p[1],
                7.0 + 11.0 - box_diag,
                37.0 + 41.0,
                37.0 + 40.0 + 41.0 + 40.0,
            ),
        ):
            with self.subTest(pattern=pattern):
                segments = _segments(self.items(path, pattern, spacing))
                groups = {}
                for start, _end in segments:
                    groups.setdefault(round(parameter(start), 6), []).append(start)
                for value, starts in groups.items():
                    # Lines are whole steps away from the bounding-box anchor.
                    self.assertAlmostEqual(
                        (value - anchor) / step,
                        round((value - anchor) / step),
                        places=5,
                    )
                    through_hole = hole_low + 1e-6 < value < hole_high - 1e-6
                    self.assertEqual(len(starts), 2 if through_hole else 1, value)

    def test_neighbouring_shapes_touching_one_hatch_line_stay_separate_segments(self):
        from ost_visualizer.domain.entities import pattern as pt

        diamond = [(50, 0), (100, 50), (50, 100), (0, 50)]

        horizontal_path = QtGui.QPainterPath()
        vertical_path = QtGui.QPainterPath()
        for offset in (0, 120):
            horizontal_path.addPolygon(
                QtGui.QPolygonF(
                    [QtCore.QPointF(x + offset, y) for x, y in diamond]
                )
            )
            horizontal_path.closeSubpath()
            vertical_path.addPolygon(
                QtGui.QPolygonF(
                    [QtCore.QPointF(x, y + offset) for x, y in diamond]
                )
            )
            vertical_path.closeSubpath()
        row = [((0, 50), (100, 50)), ((120, 50), (220, 50))]
        column = [((50, 0), (50, 100)), ((50, 120), (50, 220))]
        self.assertSegments(
            [
                s
                for s in _segments(self.items(horizontal_path, pt.HORIZONTAL, 50.0))
                if s[0][1] == 50
            ],
            row,
        )
        self.assertSegments(
            [
                s
                for s in _segments(self.items(vertical_path, pt.VERTICAL, 50.0))
                if s[0][0] == 50
            ],
            column,
        )
        oriented = [
            tuple(sorted((round(a, 6), round(b, 6)) for a, b in s))
            for s in _segments(
                self.items(horizontal_path, pt.HORIZONTAL, 50.0, orientation_angle=0.0)
            )
            if abs(s[0][1] - 50) < 1e-6
        ]
        self.assertSegments(sorted(oriented), row)
