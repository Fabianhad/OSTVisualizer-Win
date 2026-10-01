import unittest
from copy import deepcopy
from ost_visualizer.application.dtos.annotation_caption_dto import (
    AnnotationCaptionSettingsDto,
    ResolvedAnnotationCaptionDto,
)
from ost_visualizer.application.services.annotation_caption_resolver import (
    AnnotationCaptionResolver,
)
from ost_visualizer.domain.entities.annotation_caption import (
    ANNOTATION_CAPTION_ORDER,
    AnnotationCaptionId,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.uom_service import UOM_EACH, UOM_SQUARE_FEET
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

    def test_area_only_requests_only_canonical_area_quantity(self):
        self.assertEqual(
            self._resolve(AnnotationCaptionId.AREA),
            ResolvedAnnotationCaptionDto(("144.00 sf",), "", 1),
        )
        self.assertEqual(len(self.uom_service.quantity_calls), 1)
        _args, call = self.uom_service.quantity_calls[0]
        self.assertEqual(
            (call["calc_type1"], call["calc_type2"], call["calc_type3"]),
            (11, 0, 0),
        )
        self.assertEqual(
            (call["uom1"], call["uom2"], call["uom3"]),
            (UOM_SQUARE_FEET, UOM_EACH, UOM_EACH),
        )
        self.assertIs(call["round_quantity"], False)
        self.assertEqual(call["round_up"], 0.0)

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
        self.assertEqual(len(self.uom_service.quantity_calls), 1)

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
        self.assertEqual(self.uom_service.quantity_calls, [])

    def test_linear_captions_use_height_thickness_and_unrounded_geometry(self):
        self.condition = Condition(
            "linear", condition_type=Condition.TYPE_LINEAR, height=24, thickness=6
        )
        self.takeoff = Takeoff(
            "line", condition_uid="linear", position=[0.0, 0.0, 120.0, 0.0]
        )
        before = deepcopy((self.condition, self.takeoff))
        resolved = self._resolve(*ANNOTATION_CAPTION_ORDER, label="Wall")
        self.assertEqual(
            resolved,
            ResolvedAnnotationCaptionDto(
                (
                    "Wall",
                    "L = 3,048.00 mm",
                    "A = 5.00 sf",
                    "V = 0.37 cu yd",
                    "D = 2' - 0\"",
                    "WA = 42 sf",
                    "W = 3,048.00 mm",
                    "H = 152.40 mm",
                ),
                "Wall",
                2303,
            ),
        )
        self.assertEqual(len(self.uom_service.quantity_calls), 2)
        self.assertEqual((self.condition, self.takeoff), before)

    def test_count_and_attachment_captions_use_condition_footprint_dimensions(self):
        for kind in (Condition.TYPE_COUNT, Condition.TYPE_ATTACHMENT):
            with self.subTest(kind=kind):
                self.uom_service.quantity_calls.clear()
                self.condition = Condition(
                    "count", condition_type=kind, width=24, depth=36, height=12
                )
                self.takeoff = Takeoff(
                    "point", condition_uid="count", position=[900.0, 500.0]
                )
                resolved = self._resolve(*ANNOTATION_CAPTION_ORDER, label="Column")
                self.assertEqual(
                    resolved,
                    ResolvedAnnotationCaptionDto(
                        (
                            "Column",
                            "A = 6.00 sf",
                            "V = 0.22 cu yd",
                            "D = 1' - 0\"",
                            "WA = 10 sf",
                            "W = 609.60 mm",
                            "H = 914.40 mm",
                        ),
                        "Column",
                        2303,
                    ),
                )
                self.assertEqual(len(self.uom_service.quantity_calls), 1)

    def test_area_holes_change_net_quantity_without_mutating_geometry(self):
        holes = [[12.0, 12.0, 36.0, 12.0, 36.0, 36.0, 12.0, 36.0]]
        original = deepcopy((self.condition, self.takeoff, holes))
        resolved = self.resolver.resolve(
            self.condition,
            self.takeoff,
            holes,
            AnnotationCaptionSettingsDto(
                True, (AnnotationCaptionId.AREA, AnnotationCaptionId.VOLUME)
            ),
            "",
        )
        self.assertEqual(
            resolved,
            ResolvedAnnotationCaptionDto(("A = 140.00 sf", "V = 5.19 cu yd"), "", 5),
        )
        self.assertEqual((self.condition, self.takeoff, holes), original)
        self.assertEqual(len(self.uom_service.quantity_calls), 1)
        self.assertEqual(self.uom_service.quantity_calls[0][1]["hole_positions"], holes)

    def test_empty_and_label_only_selection_do_not_calculate_quantities(self):
        self.assertEqual(self._resolve(), ResolvedAnnotationCaptionDto())
        self.assertEqual(
            self._resolve(AnnotationCaptionId.LABEL),
            ResolvedAnnotationCaptionDto(("07 - Concrete",), "07 - Concrete", 128),
        )
        self.assertEqual(
            self._resolve(AnnotationCaptionId.LABEL, label=""),
            ResolvedAnnotationCaptionDto((), "", 128),
        )
        self.assertEqual(self.uom_service.quantity_calls, [])

    def test_duplicate_caption_selection_does_not_duplicate_text_or_work(self):
        self.assertEqual(
            self._resolve(
                AnnotationCaptionId.AREA,
                AnnotationCaptionId.LABEL,
                AnnotationCaptionId.AREA,
                AnnotationCaptionId.LABEL,
            ),
            ResolvedAnnotationCaptionDto(
                ("07 - Concrete", "144.00 sf"), "07 - Concrete", 129
            ),
        )
        self.assertEqual(len(self.uom_service.quantity_calls), 1)

    def test_depth_formats_quarter_inches_and_carries_into_feet(self):
        for inches, expected in (
            (0.25, 'D = 0 1/4"'),
            (6.5, 'D = 6 1/2"'),
            (6.75, 'D = 6 3/4"'),
            (11.99, "D = 1' - 0\""),
        ):
            with self.subTest(inches=inches):
                self.condition.thickness = inches
                self.assertEqual(
                    self._resolve(AnnotationCaptionId.DEPTH),
                    ResolvedAnnotationCaptionDto((expected,), "", 8),
                )
        self.assertEqual(self.uom_service.quantity_calls, [])

    def test_nonpositive_slope_and_dimensions_are_omitted_with_selected_mask(self):
        for rise, run in ((0, 12), (3, 0), (-1, 12), (3, -1)):
            with self.subTest(rise=rise, run=run):
                self.condition.rise, self.condition.run = rise, run
                self.assertEqual(
                    self._resolve(AnnotationCaptionId.SLOPE),
                    ResolvedAnnotationCaptionDto((), "", 2048),
                )
        self.condition.thickness = -1
        self.takeoff.position = [0, 0]
        self.assertEqual(
            self._resolve(
                AnnotationCaptionId.DEPTH,
                AnnotationCaptionId.WIDTH,
                AnnotationCaptionId.HEIGHT,
            ),
            ResolvedAnnotationCaptionDto((), "", 104),
        )
        self.assertEqual(self.uom_service.quantity_calls, [])
