import unittest
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

    def _resolve(self, *selected_ids, enabled=True, label="07 - Concrete"):
        return self.resolver.resolve(
            self.condition,
            self.takeoff,
            [],
            AnnotationCaptionSettingsDto(
                enabled=enabled,
                selected_ids=tuple(selected_ids),
            ),
            label,
        )

    def test_disabled_captions_resolve_to_empty_without_quantity_work(self):
        resolved = self._resolve(*ANNOTATION_CAPTION_ORDER, enabled=False)
        self.assertEqual(resolved, ResolvedAnnotationCaptionDto())
        self.assertEqual(self.uom_service.quantity_calls, [])

    def test_area_only_preserves_existing_sf_text(self):
        resolved = self._resolve(AnnotationCaptionId.AREA)
        self.assertEqual(resolved.lines, ("144.00 sf",))
        self.assertEqual(resolved.measurement_types, 1)

    def test_area_only_requests_only_canonical_area_quantity(self):
        self._resolve(AnnotationCaptionId.AREA)
        self.assertEqual(len(self.uom_service.quantity_calls), 1)
        _args, call = self.uom_service.quantity_calls[0]
        self.assertEqual(
            (call["calc_type1"], call["calc_type2"], call["calc_type3"]),
            (11, 0, 0),
        )

    def test_volume_only_uses_bluebeam_prefix_and_unit(self):
        resolved = self._resolve(AnnotationCaptionId.VOLUME)
        self.assertEqual(resolved.lines, ("V = 5.33 cu yd",))
        self.assertEqual(resolved.measurement_types, 4)

    def test_multiple_captions_use_bluebeam_order_labels_and_formatting(self):
        resolved = self._resolve(*reversed(ANNOTATION_CAPTION_ORDER))
        self.assertEqual(
            resolved.lines,
            (
                "07 - Concrete",
                "L = 14,630.40 mm",
                "A = 144.00 sf",
                "V = 5.33 cu yd",
                "D = 1' - 0\"",
                "WA = 48 sf",
                "W = 3,657.60 mm",
                "H = 3,657.60 mm",
            ),
        )
        self.assertEqual(resolved.label, "07 - Concrete")
        self.assertEqual(resolved.measurement_types, 2303)
        self.assertGreater(len(self.uom_service.quantity_calls), 0)

    def test_inapplicable_depth_caption_is_omitted_but_selection_mask_is_explicit(self):
        self.condition.thickness = 0.0
        resolved = self._resolve(
            AnnotationCaptionId.AREA,
            AnnotationCaptionId.DEPTH,
        )
        self.assertEqual(resolved.lines, ("144.00 sf",))
        self.assertEqual(resolved.measurement_types, 9)

    def test_unavailable_volume_avoids_quantity_work(self):
        self.condition.thickness = 0.0
        resolved = self._resolve(AnnotationCaptionId.VOLUME)
        self.assertEqual(resolved.lines, ())
        self.assertEqual(resolved.measurement_types, 4)
        self.assertEqual(self.uom_service.quantity_calls, [])

    def test_slope_uses_bluebeam_pitch_text_and_compact_precision(self):
        self.condition.rise = 3.125
        self.condition.run = 12.0
        resolved = self._resolve(AnnotationCaptionId.SLOPE)
        self.assertEqual(resolved.lines, ("Slope = 3.12/12 Pitch",))
        self.assertEqual(resolved.measurement_types, 2048)
