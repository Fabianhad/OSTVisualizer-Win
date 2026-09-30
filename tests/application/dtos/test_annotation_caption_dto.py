import unittest
from dataclasses import fields
from ost_visualizer.application.dtos.annotation_caption_dto import (
    ANNOTATION_CAPTION_SPECS,
    AnnotationCaptionSettingsDto,
    ResolvedAnnotationCaptionDto,
)
from ost_visualizer.application.services.annotation_caption_resolver import (
    AnnotationCaptionResolver,
)
from ost_visualizer.domain.entities.annotation_caption import (
    ANNOTATION_CAPTION_ORDER,
    DEFAULT_ANNOTATION_CAPTION_IDS,
    AnnotationCaptionId,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.uom_service_impl import UOMDomainService
from tests.application.services.caption_support import (
    _RecordingUomService as _caption_support__RecordingUomService,
    _area_fixture as _caption_support__area_fixture,
)


class PdfAnnotationCaptionResolverTests(unittest.TestCase):
    def setUp(self):
        self.uom_service = _caption_support__RecordingUomService()
        self.resolver = AnnotationCaptionResolver(self.uom_service)
        self.condition, self.takeoff = _caption_support__area_fixture()

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

    def test_resolved_caption_dto_has_no_geometry_or_filesystem_fields(self):
        self.assertEqual(
            {field.name for field in fields(ResolvedAnnotationCaptionDto)},
            {"lines", "label", "measurement_types"},
        )
