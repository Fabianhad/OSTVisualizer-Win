import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    CLOUD_SCALLOP_SIZE_SCALE,
    calculate_annotation_geometry,
    calculate_cloud_scallop_radius,
    calculate_highlight_quad_path,
    create_cloud_path_points,
    format_dimension_distance,
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
