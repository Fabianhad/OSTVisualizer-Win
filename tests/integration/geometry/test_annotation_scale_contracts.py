import math
import unittest
from PySide6 import QtCore, QtWidgets
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.services.page_scale_transform import (
    rescale_annotation_position_between_page_scales,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    calculate_dimension_geometry,
    format_dimension_distance,
)
import tests.integration.placement.test_annotation_keyboard as qt_fixtures
from tests.integration.annotations.family_support import (
    _PlanFixture as _family_support__PlanFixture,
)
from tests.integration.annotations.family_support import (
    AnnotationFamilyGeometry as _family_support_AnnotationFamilyGeometry,
)


class DimensionLifecycleTests(_family_support__PlanFixture, unittest.TestCase):
    def test_dimension_measurement_and_scale_do_not_depend_on_render_transform(self):
        for length in (1 / 64, 1 / 25.4, 1, 12, 100000.125):
            for angle in (0, math.pi / 2, 0.37):
                position = [
                    -12.0,
                    -7.0,
                    -12 + length * math.cos(angle),
                    -7 + length * math.sin(angle),
                ]
                original = list(position)
                ann = BidAnnotation("1", "dimension", position=position)
                for factor in (0.1, 1, 8):
                    for flip in (-1, 1):
                        transform = lambda points: [factor * flip * v for v in points]
                        geometry = calculate_dimension_geometry(
                            ann, position, transform
                        )
                        self.assertEqual(
                            geometry["label"],
                            format_dimension_distance(
                                math.hypot(
                                    position[2] - position[0], position[3] - position[1]
                                )
                            ),
                        )
                        self.assertEqual(
                            [geometry[k] for k in ("x1", "y1", "x2", "y2")],
                            transform(position),
                        )
                for _ in range(20):
                    position = rescale_annotation_position_between_page_scales(
                        "dimension", position, (1, 48), (1, 96)
                    )
                    geometry = calculate_dimension_geometry(ann, position, list)
                    self.assertEqual(
                        geometry["label"],
                        format_dimension_distance(
                            math.hypot(
                                position[2] - position[0], position[3] - position[1]
                            )
                        ),
                    )
                    position = rescale_annotation_position_between_page_scales(
                        "dimension", position, (1, 96), (1, 48)
                    )
                self.assertEqual(position, original)


class AnnotationFamilyGeometryTests(
    _family_support_AnnotationFamilyGeometry, unittest.TestCase
):
    def test_copy_translation_and_scale_preserve_angles_and_dimensions(self):
        from ost_visualizer.domain.entities.annotation import annotation_rotation_index
        from ost_visualizer.presentation.utils.annotation_paste import (
            translate_annotation_position,
        )

        for kind, position in self.POSITIONS.items():
            with self.subTest(kind=kind):
                annotation = BidAnnotation("1", kind, position=list(position))
                moved = translate_annotation_position(annotation, 1 / 64, -1 / 32)
                rotation = annotation_rotation_index(kind, position)
                if rotation is not None:
                    self.assertEqual(moved[rotation], position[rotation])
                if kind == "text":
                    self.assertEqual(moved[2:], position[2:])
                annotation.position = moved
                self.assertEqual(
                    translate_annotation_position(annotation, -1 / 64, 1 / 32), position
                )
                scaled = rescale_annotation_position_between_page_scales(
                    kind, position, (1, 48), (1, 96)
                )
                if rotation is not None:
                    self.assertEqual(scaled[rotation], position[rotation])
                self.assertEqual(
                    rescale_annotation_position_between_page_scales(
                        kind, scaled, (1, 96), (1, 48)
                    ),
                    position,
                )
