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

    def test_cloud_scallop_radius_is_quarter_of_legacy_size(self):
        self.assertEqual(CLOUD_SCALLOP_SIZE_SCALE, 0.25)
        self.assertAlmostEqual(calculate_cloud_scallop_radius(30.0, 2.0), 5.0)
        self.assertAlmostEqual(calculate_cloud_scallop_radius(300.0, 2.0), 12.5)

    def test_cloud_path_uses_quarter_size_scallop_density(self):
        segments = create_cloud_path_points(
            [(0.0, 0.0), (400.0, 0.0), (400.0, 400.0), (0.0, 400.0)]
        )
        self.assertEqual(len(segments), 80)

    def test_renderer_uses_annotation_color_not_global_default_style(self):
        from ost_visualizer.presentation.utils.annotation_defaults import (
            set_annotation_style_for_tool,
        )

        annotation = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            position=[1.0, 2.0, 13.0, 14.0],
            color="#336699",
            width=4.0,
        )
        set_annotation_style_for_tool("rect", color="#ff0000", line_width=9.0)
        try:
            geometry = calculate_annotation_geometry(
                annotation,
                lambda position: list(position),
            )
            self.assertEqual(geometry["color"], "#336699")
            self.assertEqual(geometry["width"], 4.0)
        finally:
            set_annotation_style_for_tool("rect", color="#ff0000", line_width=4.0)

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
        self.assertEqual(geometry["points"], [(0.0, 0.0), (10.0, 0.0)])

    def test_dimension_geometry_is_ignored_when_position_is_invalid(self):
        geometry = calculate_annotation_geometry(
            BidAnnotation(uid="bad", annotation_type="dimension", position=[0.0, 0.0]),
            lambda values: values,
        )
        self.assertNotIn("dimension", geometry)
