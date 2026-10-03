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
                    # Positive control: 1:48 to 1:96 doubles every coordinate, so
                    # the label checks below are about a genuinely rescaled line.
                    self.assertEqual(position, [2 * v for v in original])
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

    def test_dimension_label_follows_exact_length_and_page_scale(self):
        # (length in inches along +x, label at 1:48, label after the 1:96 rescale
        # doubles the stored length), written out independently of the formatter.
        cases = (
            (1, '1"', '2"'),
            (12, "1' - 0\"", "2' - 0\""),
            (100000.125, "8333' - 4 1/8\"", "16666' - 8 1/4\""),
        )
        for length, label, scaled_label in cases:
            with self.subTest(length=length):
                ann = BidAnnotation("1", "dimension", position=[-12.0, -7.0])
                position = [-12.0, -7.0, -12.0 + length, -7.0]
                self.assertEqual(
                    calculate_dimension_geometry(ann, position, list)["label"], label
                )
                scaled = rescale_annotation_position_between_page_scales(
                    "dimension", position, (1, 48), (1, 96)
                )
                self.assertEqual(
                    calculate_dimension_geometry(ann, scaled, list)["label"],
                    scaled_label,
                )


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
                # Independent oracle: which stored values a translation moves for
                # this kind (text moves only its anchor; ink skips its leading
                # rotation; every other kind moves each x/y pair, not rotation).
                if kind == "text":
                    moved_indices = {0: 1 / 64, 1: -1 / 32}
                else:
                    first = 1 if kind == "ink" else 0
                    last = len(position) - (len(position) - first) % 2
                    moved_indices = {
                        i: (1 / 64 if (i - first) % 2 == 0 else -1 / 32)
                        for i in range(first, last)
                    }
                self.assertEqual(
                    moved,
                    [
                        value + moved_indices.get(index, 0.0)
                        for index, value in enumerate(position)
                    ],
                )
                annotation.position = moved
                self.assertEqual(
                    translate_annotation_position(annotation, -1 / 64, 1 / 32), position
                )
                scaled = rescale_annotation_position_between_page_scales(
                    kind, position, (1, 48), (1, 96)
                )
                # 1:48 to 1:96 doubles every coordinate except the rotation value.
                self.assertEqual(
                    scaled,
                    [
                        value if index == rotation else 2 * value
                        for index, value in enumerate(position)
                    ],
                )
                if rotation is not None:
                    self.assertEqual(scaled[rotation], position[rotation])
                self.assertEqual(
                    rescale_annotation_position_between_page_scales(
                        kind, scaled, (1, 96), (1, 48)
                    ),
                    position,
                )
