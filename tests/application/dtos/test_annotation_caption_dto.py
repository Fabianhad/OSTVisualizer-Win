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


class AnnotationCaptionDtoValueTests(unittest.TestCase):
    def test_dtos_are_immutable_and_resolved_captions_default_to_empty(self):
        from dataclasses import FrozenInstanceError
        from ost_visualizer.application.dtos.annotation_caption_dto import (
            AnnotationCaptionSettingsDto,
            AnnotationCaptionSpec,
            ResolvedAnnotationCaptionDto,
        )

        resolved = ResolvedAnnotationCaptionDto()
        self.assertEqual(
            (resolved.lines, resolved.label, resolved.measurement_types), ((), "", 0)
        )
        with self.assertRaises(FrozenInstanceError):
            resolved.label = "x"
        with self.assertRaises(FrozenInstanceError):
            AnnotationCaptionSettingsDto(True, ()).enabled = False
        with self.assertRaises(FrozenInstanceError):
            AnnotationCaptionSpec("t", 1, "p").title = "x"
        self.assertEqual(
            AnnotationCaptionSettingsDto(True, ()),
            AnnotationCaptionSettingsDto(True, ()),
        )


class AnnotationCaptionDtoFieldNameTests(unittest.TestCase):
    def test_dtos_are_read_by_field_name_with_their_exact_types(self):
        from ost_visualizer.application.dtos.annotation_caption_dto import (
            AnnotationCaptionSettingsDto,
            AnnotationCaptionSpec,
        )
        from ost_visualizer.domain.entities.annotation_caption import (
            AnnotationCaptionId,
        )

        selected = (AnnotationCaptionId.LENGTH, AnnotationCaptionId.AREA)
        settings = AnnotationCaptionSettingsDto(enabled=True, selected_ids=selected)
        self.assertIs(settings.enabled, True)
        self.assertIs(settings.selected_ids, selected)
        self.assertEqual(
            {field.name for field in fields(AnnotationCaptionSettingsDto)},
            {"enabled", "selected_ids"},
        )
        spec = AnnotationCaptionSpec(title="T", measurement_type=5, prefix="P")
        self.assertEqual(
            (spec.title, spec.measurement_type, spec.prefix), ("T", 5, "P")
        )
        self.assertEqual(
            [field.name for field in fields(AnnotationCaptionSpec)],
            ["title", "measurement_type", "prefix"],
        )
        resolved = ResolvedAnnotationCaptionDto(
            lines=("L1", "L2"), label="lab", measurement_types=3
        )
        self.assertEqual(
            (resolved.lines, resolved.label, resolved.measurement_types),
            (("L1", "L2"), "lab", 3),
        )
