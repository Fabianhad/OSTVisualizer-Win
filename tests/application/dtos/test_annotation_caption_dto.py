import unittest
from dataclasses import fields
from ost_visualizer.application.dtos.annotation_caption_dto import (
    ANNOTATION_CAPTION_SPECS,
    ResolvedAnnotationCaptionDto,
)
from ost_visualizer.domain.entities.annotation_caption import (
    ANNOTATION_CAPTION_ORDER,
)


class AnnotationCaptionDtoTests(unittest.TestCase):
    def test_every_polygon_caption_has_one_exact_bluebeam_ui_title(self):
        self.assertEqual(
            frozenset(ANNOTATION_CAPTION_SPECS),
            frozenset(ANNOTATION_CAPTION_ORDER),
        )
        self.assertEqual(
            tuple(
                ANNOTATION_CAPTION_SPECS[caption_id].title
                for caption_id in ANNOTATION_CAPTION_ORDER
            ),
            (
                "Label",
                "Length",
                "Area",
                "Volume",
                "Depth",
                "Wall Area",
                "Width",
                "Height",
                "Slope",
            ),
        )
        self.assertEqual(
            {
                key.value: (spec.measurement_type, spec.prefix)
                for key, spec in ANNOTATION_CAPTION_SPECS.items()
            },
            {
                "label": (128, ""),
                "length": (2, "L"),
                "area": (1, "A"),
                "volume": (4, "V"),
                "depth": (8, "D"),
                "wall_area": (16, "WA"),
                "width": (32, "W"),
                "height": (64, "H"),
                "slope": (2048, "Slope"),
            },
        )

    def test_resolved_caption_dto_has_no_geometry_or_filesystem_fields(self):
        self.assertEqual(
            {field.name for field in fields(ResolvedAnnotationCaptionDto)},
            {"lines", "label", "measurement_types"},
        )
