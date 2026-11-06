import math
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    CLOUD_SCALLOP_SIZE_SCALE,
    _arc_to_bezier,
    _compute_centers_from_samples,
    _ensure_clockwise,
    _length,
    _midpoint,
    _normalize,
    _polygon_perimeter_edges,
    _sample_along_perimeter,
    calculate_annotation_geometry,
    calculate_cloud_scallop_radius,
    calculate_dimension_geometry,
    calculate_dimension_segments,
    calculate_highlight_quad_path,
    canonical_highlight_quads,
    create_cloud_path_points,
    format_dimension_distance,
    highlight_position_coordinates,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
)


class BidDimensionAnnotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dimension_distance_uses_existing_feet_inches_rounding(self):
        self.assertEqual(format_dimension_distance(255.0), "21' - 3\"")
        self.assertEqual(format_dimension_distance(18.0), "1' - 6\"")
        self.assertEqual(format_dimension_distance(6.0), '6"')
        self.assertEqual(format_dimension_distance(12.0), "1' - 0\"")
        self.assertEqual(format_dimension_distance(255.5), "21' - 3 1/2\"")
        self.assertEqual(format_dimension_distance(0.4), '3/8"')
        self.assertEqual(format_dimension_distance(0.0), "")

    def test_cloud_scallop_radius_is_quarter_of_legacy_size(self):
        self.assertEqual(CLOUD_SCALLOP_SIZE_SCALE, 0.25)
        self.assertAlmostEqual(calculate_cloud_scallop_radius(30.0, 2.0), 5.0)
        self.assertAlmostEqual(calculate_cloud_scallop_radius(300.0, 2.0), 12.5)
        # Legacy radius is clamped to [15, 50] before the quarter scale is applied.
        self.assertAlmostEqual(calculate_cloud_scallop_radius(1.0, 2.0), 3.75)

    def test_cloud_path_uses_quarter_size_scallop_density(self):
        segments = create_cloud_path_points(
            [(0.0, 0.0), (400.0, 0.0), (400.0, 400.0), (0.0, 400.0)]
        )
        self.assertEqual(len(segments), 80)
        # The scalloped outline starts on the first polygon vertex and only the
        # first arc carries the start point.
        self.assertEqual(segments[0][0], (0.0, 0.0))
        self.assertTrue(all(segment[0] is None for segment in segments[2:]))
        # Closed rings and open rings yield the same cloud.
        closed = create_cloud_path_points(
            [(0.0, 0.0), (400.0, 0.0), (400.0, 400.0), (0.0, 400.0), (0.0, 0.0)]
        )
        self.assertEqual(closed, segments)

    def test_renderer_uses_annotation_color_not_global_default_style(self):
        from ost_visualizer.presentation.utils.annotation_defaults import (
            get_annotation_style_for_tool,
            set_annotation_style_for_tool,
        )

        annotation = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            position=[1.0, 2.0, 13.0, 14.0],
            color="#336699",
            width=4.0,
        )
        previous_style = get_annotation_style_for_tool("rect")
        set_annotation_style_for_tool("rect", color="#ff0000", line_width=9.0)
        self.addCleanup(
            set_annotation_style_for_tool,
            "rect",
            color=previous_style.color,
            line_width=previous_style.line_width,
        )
        geometry = calculate_annotation_geometry(
            annotation,
            lambda position: list(position),
        )
        self.assertEqual(get_annotation_style_for_tool("rect").line_width, 9.0)
        self.assertEqual(geometry["color"], "#336699")
        self.assertEqual(geometry["width"], 4.0)

    def test_renderer_ignores_unpaired_polygon_coordinate(self):
        annotation = BidAnnotation(
            uid="polygon-1",
            annotation_type="polygon",
            position=[0.0, 0.0, 10.0, 0.0, 5.0],
        )
        geometry = calculate_annotation_geometry(
            annotation,
            lambda position: list(position),
        )
        self.assertEqual(geometry["type"], "polygon")
        self.assertEqual(geometry["points"], [(0.0, 0.0), (10.0, 0.0)])

    def test_dimension_geometry_is_ignored_when_position_is_invalid(self):
        geometry = calculate_annotation_geometry(
            BidAnnotation(uid="bad", annotation_type="dimension", position=[0.0, 0.0]),
            lambda values: values,
        )
        self.assertEqual(geometry["type"], "dimension")
        self.assertNotIn("dimension", geometry)

    def test_dimension_geometry_reports_label_and_transformed_endpoints(self):
        geometry = calculate_annotation_geometry(
            BidAnnotation(
                uid="dimension",
                annotation_type="dimension",
                position=[0.0, 0.0, 255.0, 0.0],
            ),
            lambda values: [value * 2.0 for value in values],
        )
        dimension = geometry["dimension"]
        self.assertEqual(
            (dimension["x1"], dimension["y1"], dimension["x2"], dimension["y2"]),
            (0.0, 0.0, 510.0, 0.0),
        )
        self.assertEqual(dimension["label"], "21' - 3\"")


def _scale2(values):
    return [value * 2.0 for value in values]


def _identity(values):
    return list(values)


def _bezier_midpoint(start, cp1, cp2, end):
    return tuple(
        (start[axis] + 3.0 * cp1[axis] + 3.0 * cp2[axis] + end[axis]) / 8.0
        for axis in (0, 1)
    )


def _outside_distance(point, side):
    # Distance beyond the nearest edge of an axis-aligned [0, side] square.
    return max(-point[0], point[0] - side, -point[1], point[1] - side)


def _distance_to_polygon(point, polygon):
    best = float("inf")
    for index, (ax, ay) in enumerate(polygon):
        bx, by = polygon[(index + 1) % len(polygon)]
        dx, dy = bx - ax, by - ay
        t = ((point[0] - ax) * dx + (point[1] - ay) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        best = min(best, math.hypot(point[0] - ax - t * dx, point[1] - ay - t * dy))
    return best


def _perimeter_position(point, side):
    x, y = point
    if abs(y) < 1e-6:
        return x
    if abs(x - side) < 1e-6:
        return side + y
    if abs(y - side) < 1e-6:
        return 3 * side - x
    return 4 * side - y


class HighlightQuadGeometryTests(unittest.TestCase):
    def test_coordinates_drop_a_trailing_unpaired_value_and_short_lists(self):
        self.assertEqual(highlight_position_coordinates([1, 2, 3, 4]), [1, 2, 3, 4])
        self.assertEqual(highlight_position_coordinates([1, 2, 3, 4, 5]), [1, 2, 3, 4])
        self.assertEqual(
            highlight_position_coordinates([1, 2, 3, 4, 5, 6]), [1, 2, 3, 4, 5, 6]
        )
        self.assertEqual(highlight_position_coordinates([1, 2, 3]), [])
        self.assertEqual(highlight_position_coordinates([]), [])

    def test_two_points_become_their_axis_aligned_bounds_in_any_order(self):
        expected = [((1, 2), (5, 2), (1, 6), (5, 6))]
        self.assertEqual(canonical_highlight_quads([(5, 6), (1, 2)]), expected)
        self.assertEqual(canonical_highlight_quads([(1, 6), (5, 2)]), expected)
        self.assertEqual(canonical_highlight_quads([(1, 2), (5, 6)]), expected)

    def test_point_counts_that_are_not_a_whole_number_of_quads_yield_nothing(self):
        self.assertEqual(canonical_highlight_quads([]), [])
        self.assertEqual(canonical_highlight_quads([(1, 1)]), [])
        self.assertEqual(canonical_highlight_quads([(1, 1), (2, 2), (3, 3)]), [])
        self.assertEqual(canonical_highlight_quads([(0, 0)] * 5), [])
        self.assertEqual(canonical_highlight_quads([(0, 0)] * 6), [])

    def test_wide_rectangle_is_ordered_top_left_top_right_bottom_left_bottom_right(self):
        corners = [(0, 0), (80, 0), (80, 40), (0, 40)]
        expected = [((0, 0), (80, 0), (0, 40), (80, 40))]
        self.assertEqual(canonical_highlight_quads(corners), expected)
        # The result does not depend on the order the corners were stored in.
        self.assertEqual(canonical_highlight_quads(corners[2:] + corners[:2]), expected)
        self.assertEqual(canonical_highlight_quads(corners[::-1]), expected)

    def test_tall_rectangle_starts_along_its_long_axis(self):
        corners = [(0, 0), (40, 0), (40, 80), (0, 80)]
        expected = [((40, 0), (40, 80), (0, 0), (0, 80))]
        self.assertEqual(canonical_highlight_quads(corners), expected)
        self.assertEqual(canonical_highlight_quads(corners[::-1]), expected)

    def test_skewed_quad_keeps_its_corners_with_the_long_edges_first(self):
        corners = [(30.0, 20.0), (100.0, 40.0), (90.0, 70.0), (20.0, 50.0)]
        expected = [((30.0, 20.0), (100.0, 40.0), (20.0, 50.0), (90.0, 70.0))]
        self.assertEqual(canonical_highlight_quads(corners), expected)
        self.assertEqual(canonical_highlight_quads(corners[::-1]), expected)

    def test_each_group_of_four_points_is_ordered_independently(self):
        first = [(0, 0), (80, 0), (80, 40), (0, 40)]
        second = [(100, 0), (140, 0), (140, 80), (100, 80)]
        self.assertEqual(
            canonical_highlight_quads(first + second),
            [
                ((0, 0), (80, 0), (0, 40), (80, 40)),
                ((140, 0), (140, 80), (100, 0), (100, 80)),
            ],
        )

    def test_quad_path_places_bluebeam_controls_a_fixed_fraction_beyond_each_corner(
        self,
    ):
        quad = ((0.0, 0.0), (80.0, 0.0), (0.0, 40.0), (80.0, 40.0))
        c = 40.0 / 4.2426  # short-edge length over Bluebeam's curve divisor
        path = calculate_highlight_quad_path(quad)
        expected = [
            (0.0, 0.0),
            (80.0, 0.0),
            (80.0 + c, -c),
            (80.0 + c, 40.0 + c),
            (80.0, 40.0),
            (0.0, 40.0),
            (-c, 40.0 + c),
            (-c, -c),
        ]
        self.assertEqual(len(path), 8)
        for actual, wanted in zip(path, expected):
            self.assertAlmostEqual(actual[0], wanted[0], places=9)
            self.assertAlmostEqual(actual[1], wanted[1], places=9)

    def test_quad_path_controls_rotate_with_the_quad(self):
        quad = ((0.0, 0.0), (80.0, 0.0), (0.0, 40.0), (80.0, 40.0))
        rotated = tuple((-y, x) for x, y in quad)  # 90 degrees about the origin
        base = calculate_highlight_quad_path(quad)
        turned = calculate_highlight_quad_path(rotated)
        for actual, original in zip(turned, base):
            self.assertAlmostEqual(actual[0], -original[1], places=9)
            self.assertAlmostEqual(actual[1], original[0], places=9)

    def test_quad_path_handles_coincident_corners_without_dividing_by_zero(self):
        quad = ((5.0, 5.0), (5.0, 5.0), (5.0, 45.0), (5.0, 45.0))
        self.assertEqual(
            calculate_highlight_quad_path(quad),
            (
                (5.0, 5.0),
                (5.0, 5.0),
                (5.0, 5.0),
                (5.0, 45.0),
                (5.0, 45.0),
                (5.0, 45.0),
                (5.0, 45.0),
                (5.0, 5.0),
            ),
        )


class DimensionSegmentTests(unittest.TestCase):
    def test_segments_are_the_line_then_a_centred_perpendicular_tick_at_each_end(self):
        self.assertEqual(
            calculate_dimension_segments(0.0, 0.0, 3.0, 4.0, 10.0),
            [
                (0.0, 0.0, 3.0, 4.0),
                (4.0, -3.0, -4.0, 3.0),
                (7.0, 1.0, -1.0, 7.0),
            ],
        )

    def test_tick_length_is_the_full_tick_and_ticks_stay_perpendicular(self):
        for tick_length in (2.0, 7.5, 24.0):
            line, tick1, tick2 = calculate_dimension_segments(
                10.0, -5.0, 10.0, 25.0, tick_length
            )
            self.assertEqual(line, (10.0, -5.0, 10.0, 25.0))
            for tick, anchor in ((tick1, (10.0, -5.0)), (tick2, (10.0, 25.0))):
                self.assertAlmostEqual(
                    math.hypot(tick[2] - tick[0], tick[3] - tick[1]), tick_length
                )
                self.assertAlmostEqual((tick[0] + tick[2]) / 2.0, anchor[0])
                self.assertAlmostEqual((tick[1] + tick[3]) / 2.0, anchor[1])
                self.assertAlmostEqual(tick[1], tick[3])

    def test_reversed_direction_flips_the_tick_orientation(self):
        _line, tick1, _tick2 = calculate_dimension_segments(0.0, 0.0, 10.0, 0.0, 4.0)
        _line, rtick1, _rtick2 = calculate_dimension_segments(10.0, 0.0, 0.0, 0.0, 4.0)
        self.assertEqual(tick1, (0.0, -2.0, 0.0, 2.0))
        self.assertEqual(rtick1, (10.0, 2.0, 10.0, -2.0))

    def test_zero_and_tiny_lengths_have_no_segments(self):
        self.assertEqual(calculate_dimension_segments(3.0, 3.0, 3.0, 3.0, 10.0), [])
        self.assertEqual(calculate_dimension_segments(0.0, 0.0, 1e-10, 0.0, 10.0), [])
        self.assertEqual(len(calculate_dimension_segments(0.0, 0.0, 1e-8, 0.0, 10.0)), 3)


class DimensionGeometryTests(unittest.TestCase):
    def _annotation(self, position, **properties):
        return BidAnnotation(
            uid="d",
            annotation_type="dimension",
            position=position,
            properties=properties,
        )

    def test_too_short_positions_and_transforms_give_no_dimension(self):
        self.assertIsNone(
            calculate_dimension_geometry(
                self._annotation([1, 2, 3]), [1, 2, 3], _identity
            )
        )
        self.assertIsNone(
            calculate_dimension_geometry(
                self._annotation([1, 2, 3, 4]), [1, 2, 3, 4], lambda _values: [1, 2, 3]
            )
        )

    def test_label_measures_the_untransformed_distance_and_endpoints_are_transformed(
        self,
    ):
        annotation = self._annotation([0.0, 0.0, 30.0, 40.0])
        geometry = calculate_dimension_geometry(annotation, annotation.position, _scale2)
        self.assertEqual(
            (geometry["x1"], geometry["y1"], geometry["x2"], geometry["y2"]),
            (0.0, 0.0, 60.0, 80.0),
        )
        self.assertEqual(geometry["label"], "4' - 2\"")  # 50 inches, not 100

    def test_font_properties_default_and_are_read_from_the_annotation(self):
        annotation = self._annotation([0.0, 0.0, 6.0, 0.0])
        defaults = calculate_dimension_geometry(
            annotation, annotation.position, _identity
        )
        self.assertEqual(
            {key: defaults[key] for key in defaults if key.startswith("font")},
            {
                "font_name": "Arial",
                "font_size": 10,
                "font_bold": False,
                "font_italic": False,
                "font_underline": False,
            },
        )
        styled = self._annotation(
            [0.0, 0.0, 6.0, 0.0],
            FontName="Courier",
            FontSize=14,
            FontBold=True,
            FontItalic=True,
            FontUnderline=True,
        )
        geometry = calculate_dimension_geometry(styled, styled.position, _identity)
        self.assertEqual(
            {key: geometry[key] for key in geometry if key.startswith("font")},
            {
                "font_name": "Courier",
                "font_size": 14,
                "font_bold": True,
                "font_italic": True,
                "font_underline": True,
            },
        )
        self.assertEqual(geometry["label"], '6"')


class AnnotationGeometryTests(unittest.TestCase):
    def _geometry(self, annotation_type, position, transform=_scale2, **kwargs):
        annotation = BidAnnotation(
            uid="g1",
            annotation_type=annotation_type,
            position=position,
            color="#123456",
            width=2.5,
            **kwargs,
        )
        return calculate_annotation_geometry(annotation, transform)

    def test_annotations_without_a_position_have_no_geometry(self):
        self.assertIsNone(self._geometry("rect", []))

    def test_every_geometry_carries_type_style_and_transformed_position(self):
        geometry = self._geometry("rect", [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(geometry["type"], "rect")
        self.assertEqual(geometry["color"], "#123456")
        self.assertEqual(geometry["width"], 2.5)
        self.assertEqual(geometry["transformed_position"], [2.0, 4.0, 6.0, 8.0])

    def test_unrecognised_types_report_only_the_common_fields(self):
        geometry = self._geometry("mystery", [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(
            sorted(geometry), ["color", "transformed_position", "type", "width"]
        )

    def test_polygon_and_cloud_points_are_the_transformed_coordinate_pairs(self):
        for kind in ("polygon", "cloud"):
            geometry = self._geometry(kind, [0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 7.0])
            self.assertEqual(
                geometry["points"], [(0.0, 0.0), (20.0, 0.0), (20.0, 10.0)], kind
            )

    def test_ink_with_an_odd_count_skips_the_leading_angle_value(self):
        transformed = []

        def spy(values):
            transformed.append(list(values))
            return _scale2(values)

        geometry = self._geometry("ink", [99.0, 1.0, 2.0, 3.0, 4.0], spy)
        self.assertEqual(geometry["points"], [(2.0, 4.0), (6.0, 8.0)])
        self.assertIn([1.0, 2.0, 3.0, 4.0], transformed)

    def test_ink_with_an_even_count_uses_every_value(self):
        geometry = self._geometry("ink", [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(geometry["points"], [(2.0, 4.0), (6.0, 8.0)])

    def test_highlight_points_are_the_transformed_coordinates(self):
        geometry = self._geometry(
            "highlight", [0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 0.0, 5.0, 3.0]
        )
        self.assertEqual(
            geometry["highlight"]["points"],
            [(0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)],
        )

    def test_highlight_needs_two_points(self):
        self.assertNotIn("highlight", self._geometry("highlight", [1.0, 2.0, 3.0]))
        geometry = self._geometry("highlight", [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(geometry["highlight"]["points"], [(2.0, 4.0), (6.0, 8.0)])

    def test_unrotated_oval_is_centred_between_its_corners(self):
        oval = self._geometry("oval", [0.0, 0.0, 10.0, 4.0])["oval"]
        self.assertEqual(
            oval, {"cx": 10.0, "cy": 4.0, "w": 20.0, "h": 8.0, "rotation_deg": 0.0}
        )

    def test_rotated_oval_unrotates_its_corners_to_find_width_and_height(self):
        # Stored corners p0=(0,0), p1=(10,4) with a 90 degree rotation. About the
        # centre (5, 2) the unrotated corners are (3, 7) and (7, -3).
        oval = self._geometry(
            "oval", [0.0, 0.0, 10.0, 4.0, math.pi / 2], _identity
        )["oval"]
        self.assertAlmostEqual(oval["cx"], 5.0)
        self.assertAlmostEqual(oval["cy"], 2.0)
        self.assertAlmostEqual(oval["w"], 4.0)
        self.assertAlmostEqual(oval["h"], 10.0)
        self.assertAlmostEqual(oval["rotation_deg"], 90.0)

    def test_rotation_value_is_not_passed_through_the_transform(self):
        seen = []

        def spy(values):
            seen.append(len(values))
            return _scale2(values)

        self._geometry("oval", [0.0, 0.0, 10.0, 4.0, 0.5], spy)
        self.assertEqual(seen[-1], 4)

    def test_oval_needs_two_points(self):
        geometry = self._geometry("oval", [0.0, 0.0, 10.0])
        self.assertNotIn("oval", geometry)
        self.assertNotIn("bounds", geometry)

    def test_rect_with_two_points_reports_bounds_in_any_corner_order(self):
        geometry = self._geometry("rect", [10.0, 8.0, 2.0, 1.0])
        self.assertEqual(
            geometry["bounds"],
            {"min_x": 4.0, "max_x": 20.0, "min_y": 2.0, "max_y": 16.0},
        )
        self.assertNotIn("shape", geometry)

    def test_rect_with_a_trailing_rotation_and_two_points_still_reports_bounds(self):
        geometry = self._geometry("rect", [1.0, 2.0, 3.0, 4.0, 0.5])
        self.assertEqual(
            geometry["bounds"],
            {"min_x": 2.0, "max_x": 6.0, "min_y": 4.0, "max_y": 8.0},
        )

    def test_rect_with_four_points_reports_corners_and_rotation_in_degrees(self):
        corners = [1.0, 2.0, 5.0, 2.0, 5.0, 4.0, 1.0, 4.0]
        flat = self._geometry("rect", corners)["shape"]
        self.assertEqual(
            flat,
            {
                "corners": [(2.0, 4.0), (10.0, 4.0), (10.0, 8.0), (2.0, 8.0)],
                "rotation": 0.0,
            },
        )
        turned = self._geometry("rect", corners + [math.pi / 3])["shape"]
        self.assertEqual(turned["corners"], flat["corners"])
        self.assertAlmostEqual(turned["rotation"], 60.0)

    def test_rect_with_three_points_falls_back_to_bounds(self):
        geometry = self._geometry("rect", [1.0, 2.0, 3.0, 4.0, 9.0, 1.0])
        self.assertNotIn("shape", geometry)
        self.assertEqual(
            geometry["bounds"],
            {"min_x": 2.0, "max_x": 18.0, "min_y": 2.0, "max_y": 8.0},
        )

    def test_rect_needs_at_least_two_points(self):
        geometry = self._geometry("rect", [1.0, 2.0, 3.0])
        self.assertNotIn("bounds", geometry)
        self.assertNotIn("shape", geometry)

    def test_line_and_arrow_report_transformed_end_points(self):
        for kind in ("line", "arrow"):
            geometry = self._geometry(kind, [1.0, 2.0, 3.0, 4.0])
            self.assertEqual(
                geometry["line"], {"x1": 2.0, "y1": 4.0, "x2": 6.0, "y2": 8.0}, kind
            )
            self.assertNotIn("line", self._geometry(kind, [1.0, 2.0, 3.0]), kind)

    def test_dimension_geometry_is_embedded_only_when_valid(self):
        geometry = self._geometry("dimension", [0.0, 0.0, 6.0, 0.0])
        self.assertEqual(geometry["dimension"]["x2"], 12.0)
        self.assertEqual(geometry["dimension"]["label"], '6"')
        self.assertNotIn("dimension", self._geometry("dimension", [0.0, 0.0, 6.0]))

    def test_text_geometry_keeps_the_stored_box_and_text_properties(self):
        text = self._geometry(
            "text",
            [60.0, 80.0, 40.0, 20.0, math.pi / 2],
            properties={
                "Text": "Hello",
                "FontName": "Courier",
                "FontSize": 9,
                "FontBold": True,
                "FontItalic": True,
                "FontUnderline": True,
                "TextAlign": 2,
            },
        )["text"]
        self.assertEqual(text["content"], "Hello")
        self.assertEqual(
            (text["center_x"], text["center_y"], text["box_width"], text["box_height"]),
            (60.0, 80.0, 40.0, 20.0),
        )
        self.assertAlmostEqual(text["rotation"], 90.0)
        self.assertEqual(
            (
                text["font_name"],
                text["font_size"],
                text["font_bold"],
                text["font_italic"],
                text["font_underline"],
                text["text_align"],
            ),
            ("Courier", 9, True, True, True, 2),
        )

    def test_text_geometry_defaults_and_requires_a_box(self):
        text = self._geometry("text", [1.0, 2.0, 3.0, 4.0])["text"]
        self.assertEqual(
            text,
            {
                "content": "",
                "center_x": 1.0,
                "center_y": 2.0,
                "box_width": 3.0,
                "box_height": 4.0,
                "rotation": 0,
                "font_name": "Arial",
                "font_size": 12,
                "font_bold": False,
                "font_italic": False,
                "font_underline": False,
                "text_align": 0,
            },
        )
        self.assertNotIn("text", self._geometry("text", [1.0, 2.0, 3.0]))

    def test_named_view_geometry_is_the_bounding_box_of_its_four_corners(self):
        position = [10.0, 5.0, 30.0, 5.0, 30.0, 25.0, 10.0, 25.0]
        view = self._geometry("namedview", position, properties={"Text": "Roof"})[
            "namedview"
        ]
        self.assertEqual(
            view,
            {
                "content": "Roof",
                "min_x": 20.0,
                "min_y": 10.0,
                "max_x": 60.0,
                "max_y": 50.0,
                "width": 40.0,
                "height": 40.0,
            },
        )
        self.assertNotIn("namedview", self._geometry("namedview", position[:6]))
        self.assertEqual(
            self._geometry("namedview", position, _identity)["namedview"]["content"],
            "",
        )

    def test_hotlink_geometry_uses_the_transformed_centre_and_the_annotation_ids(self):
        annotation = BidAnnotation(
            uid="hl1",
            annotation_type="hotlink",
            page_uid="page-7",
            position=[3.0, 4.0],
            color="#abcdef",
            width=3.0,
            properties={"BidPageViewUID": "view-9"},
        )
        geometry = calculate_annotation_geometry(annotation, _scale2)
        self.assertEqual(
            geometry["hotlink"],
            {
                "uid": "hl1",
                "bid_page_uid": "page-7",
                "center_x": 6.0,
                "center_y": 8.0,
                "target_view_uid": "view-9",
                "color": "#abcdef",
                "width": 3.0,
            },
        )

    def test_hotlink_needs_a_point(self):
        annotation = BidAnnotation(uid="hl2", annotation_type="hotlink", position=[3.0])
        self.assertNotIn("hotlink", calculate_annotation_geometry(annotation, _scale2))


class CloudPathGeometryTests(unittest.TestCase):
    SQUARE_400 = [(0.0, 0.0), (400.0, 0.0), (400.0, 400.0), (0.0, 400.0)]

    def test_each_scallop_is_two_quarter_arcs_that_bulge_outward_by_the_radius(self):
        # side 400 -> radius 12.5, 40 scallops of chord 40: half circles of radius 20
        # whose apex sits 20 outside the edge (they start and end on the outline).
        segments = create_cloud_path_points(self.SQUARE_400)
        self.assertEqual(len(segments), 80)
        for index, segment in enumerate(segments):
            end = segment[3]
            if index % 2 == 0:
                self.assertAlmostEqual(_outside_distance(end, 400.0), 20.0, places=6)
            else:
                self.assertAlmostEqual(_outside_distance(end, 400.0), 0.0, places=6)
                self.assertAlmostEqual(
                    _perimeter_position(end, 400.0),
                    (40.0 * (index // 2 + 1)) % 1600.0,
                    places=6,
                )
        self.assertEqual(segments[0][0], (0.0, 0.0))
        self.assertEqual(segments[1][0], (0.0, 0.0))

    def test_scallop_orientation_does_not_depend_on_vertex_winding(self):
        for polygon in (self.SQUARE_400, self.SQUARE_400[::-1]):
            segments = create_cloud_path_points(polygon)
            self.assertEqual(len(segments), 80)
            for segment in segments[0::2]:
                self.assertAlmostEqual(
                    _outside_distance(segment[3], 400.0), 20.0, places=6
                )

    def test_intensity_scales_the_scallop_size_through_the_clamped_radius(self):
        square = [(0.0, 0.0), (30.0, 0.0), (30.0, 30.0), (0.0, 30.0)]
        # intensity 2 -> radius 5 -> step 16.25 -> 8 scallops of 2 curves each;
        # intensity 1 -> legacy radius clamped to 15 -> 3.75 -> step 12.19 -> 10.
        self.assertEqual(len(create_cloud_path_points(square)), 16)
        self.assertEqual(len(create_cloud_path_points(square, 2.0)), 16)
        self.assertEqual(len(create_cloud_path_points(square, 1.0)), 20)

    def test_a_small_shape_gets_six_minor_scallops_bulging_away_from_its_centre(self):
        square = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
        radius = 3.75
        for polygon in (square, square[::-1]):
            segments = create_cloud_path_points(polygon)
            self.assertEqual(len(segments), 6)
            self.assertEqual(segments[0][0], polygon[0])
            for segment in segments:
                self.assertLess(_distance_to_polygon(segment[3], polygon), 1e-9)
            self.assertAlmostEqual(segments[-1][3][0], polygon[0][0], places=9)
            self.assertAlmostEqual(segments[-1][3][1], polygon[0][1], places=9)
            for index, segment in enumerate(segments):
                start = segments[index - 1][3] if index else segment[0]
                end = segment[3]
                chord = math.hypot(end[0] - start[0], end[1] - start[1])
                mid = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
                apex = _bezier_midpoint(start, segment[1], segment[2], end)
                sagitta = radius - math.sqrt(radius * radius - (chord / 2.0) ** 2)
                self.assertAlmostEqual(
                    math.hypot(apex[0] - mid[0], apex[1] - mid[1]), sagitta, places=3
                )
                outward = (mid[0] - 2.0, mid[1] - 2.0)
                self.assertGreater(
                    (apex[0] - mid[0]) * outward[0] + (apex[1] - mid[1]) * outward[1],
                    0.0,
                )

    def test_scallops_trace_a_closed_loop(self):
        segments = create_cloud_path_points(self.SQUARE_400)
        self.assertAlmostEqual(segments[-1][3][0], 0.0, places=6)
        self.assertAlmostEqual(segments[-1][3][1], 0.0, places=6)

    def test_unequal_edges_use_the_average_edge_length_for_the_radius(self):
        triangle = [(0.0, 0.0), (60.0, 0.0), (0.0, 30.0)]
        perimeter = 60.0 + 30.0 + math.hypot(60.0, 30.0)
        radius = calculate_cloud_scallop_radius(perimeter / 3.0, 2.0)
        expected_samples = math.ceil(perimeter / (3.25 * radius))
        segments = create_cloud_path_points(triangle)
        # Every scallop ends on the outline; apexes are off it.
        on_outline = [
            segment
            for segment in segments
            if _distance_to_polygon(segment[3], triangle) < 1e-9
        ]
        self.assertEqual(expected_samples, 6)
        self.assertEqual(len(on_outline), expected_samples)
        self.assertEqual(len(segments), 12)

    def test_degenerate_inputs_give_no_cloud(self):
        self.assertEqual(create_cloud_path_points([]), [])
        self.assertEqual(create_cloud_path_points([(1.0, 1.0)]), [])
        self.assertEqual(create_cloud_path_points([(1.0, 1.0), (1.0, 1.0)]), [])

    def test_a_two_point_cloud_wraps_a_scalloped_loop_around_the_segment(self):
        segments = create_cloud_path_points([(0.0, 0.0), (10.0, 0.0)])
        self.assertEqual(len(segments), 6)
        ys = [segment[1][1] for segment in segments]
        self.assertTrue(all(y < 0.0 for y in ys[:3]))
        self.assertTrue(all(y > 0.0 for y in ys[3:]))


class ArcBezierTests(unittest.TestCase):
    def test_a_quarter_arc_is_one_curve_with_the_standard_circle_constant(self):
        ((cp1, cp2, end),) = _arc_to_bezier((0.0, 0.0), 10.0, 0.0, math.pi / 2)
        self.assertAlmostEqual(cp1[0], 10.0)
        self.assertAlmostEqual(cp1[1], 5.522847498, places=8)
        self.assertAlmostEqual(cp2[0], 5.522847498, places=8)
        self.assertAlmostEqual(cp2[1], 10.0)
        self.assertAlmostEqual(end[0], 0.0)
        self.assertAlmostEqual(end[1], 10.0)

    def test_arcs_split_into_quarter_turns_and_end_where_asked(self):
        for span, count in ((math.pi, 2), (3 * math.pi / 2, 3), (2 * math.pi, 4)):
            segments = _arc_to_bezier((3.0, -2.0), 5.0, 0.3, 0.3 + span)
            self.assertEqual(len(segments), count)
            self.assertAlmostEqual(segments[-1][2][0], 3.0 + 5.0 * math.cos(0.3 + span))
            self.assertAlmostEqual(
                segments[-1][2][1], -2.0 + 5.0 * math.sin(0.3 + span)
            )

    def test_every_curve_follows_the_circle_for_any_sweep(self):
        # A cubic with 4/3*tan(phi/4) handles stays within ~3e-4 of the radius at
        # its midpoint for sweeps up to 90 degrees.
        center = (1.0, 2.0)
        radius = 8.0
        for span in (0.2, 0.7, 1.2, math.pi / 2, 2.0, 3.0):
            start_angle = 0.4
            previous = (
                center[0] + radius * math.cos(start_angle),
                center[1] + radius * math.sin(start_angle),
            )
            for cp1, cp2, end in _arc_to_bezier(
                center, radius, start_angle, start_angle + span
            ):
                mid = _bezier_midpoint(previous, cp1, cp2, end)
                self.assertAlmostEqual(
                    math.hypot(mid[0] - center[0], mid[1] - center[1]),
                    radius,
                    delta=radius * 5e-4,
                    msg=f"span {span}",
                )
                self.assertAlmostEqual(
                    math.hypot(end[0] - center[0], end[1] - center[1]), radius
                )
                self.assertAlmostEqual(
                    math.hypot(cp1[0] - previous[0], cp1[1] - previous[1]),
                    math.hypot(cp2[0] - end[0], cp2[1] - end[1]),
                )
                previous = end

    def test_handle_length_follows_four_thirds_tan_quarter_sweep(self):
        radius = 6.0
        for sweep in (0.5, 1.0):
            ((cp1, _cp2, _end),) = _arc_to_bezier((0.0, 0.0), radius, 0.0, sweep)
            handle = math.hypot(cp1[0] - radius, cp1[1])
            self.assertAlmostEqual(
                handle, 4.0 / 3.0 * math.tan(sweep / 4.0) * radius, places=6
            )

    def test_an_end_angle_before_the_start_wraps_forward(self):
        segments = _arc_to_bezier((0.0, 0.0), 10.0, 3 * math.pi / 2, 0.0)
        self.assertEqual(len(segments), 1)
        self.assertAlmostEqual(segments[0][2][0], 10.0)
        self.assertAlmostEqual(segments[0][2][1], 0.0)
        self.assertAlmostEqual(segments[0][0][0], 5.522847498, places=8)
        self.assertAlmostEqual(segments[0][0][1], -10.0)

    def test_a_zero_sweep_is_one_degenerate_curve_at_the_start_point(self):
        ((cp1, cp2, end),) = _arc_to_bezier((0.0, 0.0), 4.0, 1.0, 1.0)
        for point in (cp1, cp2, end):
            self.assertAlmostEqual(point[0], 4.0 * math.cos(1.0))
            self.assertAlmostEqual(point[1], 4.0 * math.sin(1.0))


class CloudHelperTests(unittest.TestCase):
    def test_normalize_returns_a_unit_vector_or_zero(self):
        self.assertEqual(_normalize(3.0, 4.0), (0.6, 0.8))
        self.assertEqual(_normalize(0.0, -2.0), (0.0, -1.0))
        self.assertEqual(_normalize(0.0, 0.0), (0.0, 0.0))

    def test_midpoint_and_length(self):
        self.assertEqual(_midpoint((0.0, 2.0), (4.0, -6.0)), (2.0, -2.0))
        self.assertEqual(_length((1.0, 1.0), (4.0, 5.0)), 5.0)

    def test_ensure_clockwise_reverses_only_negative_area_rings(self):
        ring = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
        self.assertEqual(_ensure_clockwise(ring), ring)
        self.assertEqual(_ensure_clockwise(ring[::-1]), ring)
        short = [(0.0, 0.0), (1.0, 1.0)]
        self.assertIs(_ensure_clockwise(short), short)
        degenerate = [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]
        self.assertEqual(_ensure_clockwise(degenerate), degenerate)

    def test_perimeter_edges_close_the_ring_and_skip_zero_length_edges(self):
        ring = [(0.0, 0.0), (3.0, 0.0), (3.0, 4.0)]
        self.assertEqual(
            _polygon_perimeter_edges(ring),
            [
                ((0.0, 0.0), (3.0, 0.0), 3.0),
                ((3.0, 0.0), (3.0, 4.0), 4.0),
                ((3.0, 4.0), (0.0, 0.0), 5.0),
            ],
        )
        repeated = [(0.0, 0.0), (0.0, 0.0), (3.0, 0.0), (3.0, 0.0)]
        self.assertEqual(
            [edge[2] for edge in _polygon_perimeter_edges(repeated)], [3.0, 3.0]
        )
        self.assertEqual(_polygon_perimeter_edges([(1.0, 1.0)]), [])
        self.assertEqual(_polygon_perimeter_edges([(1.0, 1.0), (1.0, 1.0)]), [])

    def test_perimeter_samples_are_evenly_spaced_from_the_first_vertex(self):
        ring = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
        samples = _sample_along_perimeter(ring, 8)
        self.assertEqual(len(samples), 8)
        expected = [(0, 0), (2, 0), (4, 0), (4, 2), (4, 4), (2, 4), (0, 4), (0, 2)]
        for actual, wanted in zip(samples, expected):
            self.assertAlmostEqual(actual[0], wanted[0])
            self.assertAlmostEqual(actual[1], wanted[1])
        self.assertEqual(_sample_along_perimeter([(1.0, 1.0)], 5), [])

    def test_arc_centres_sit_on_the_inner_normal_of_each_chord(self):
        samples = [(0.0, 0.0), (6.0, 0.0), (6.0, 6.0), (0.0, 6.0)]
        # chord half-length 3, radius 5 -> centre 4 units off the chord.
        centers = _compute_centers_from_samples(samples, 5.0, invert=False)
        # Entry i+1 holds the centre of chord i -> i+1.
        self.assertEqual(centers[1], (3.0, 4.0))
        self.assertEqual(centers[2], (2.0, 3.0))
        self.assertEqual(centers[3], (3.0, 2.0))
        self.assertEqual(centers[0], (4.0, 3.0))
        inverted = _compute_centers_from_samples(samples, 5.0, invert=True)
        self.assertEqual(inverted[1], (3.0, -4.0))
        self.assertEqual(inverted[2], (10.0, 3.0))
        # A chord longer than the diameter puts the centre on the chord itself.
        flat = _compute_centers_from_samples([(0.0, 0.0), (20.0, 0.0)], 5.0, False)
        self.assertEqual(flat[1], (10.0, 0.0))
