import tempfile
import unittest
from dataclasses import fields
from pathlib import Path
from ost_visualizer.application.dtos.annotation_caption_dto import (
    ANNOTATION_CAPTION_SPECS,
    AnnotationCaptionSettingsDto,
    ResolvedAnnotationCaptionDto,
)
from ost_visualizer.application.services.annotation_caption_resolver import (
    AnnotationCaptionResolver,
)
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.annotation_caption import (
    ANNOTATION_CAPTION_ORDER,
    DEFAULT_ANNOTATION_CAPTION_IDS,
    AnnotationCaptionId,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.uom_service_impl import UOMDomainService
from ost_visualizer.infrastructure.persistence.repositories.json_config_repository import (
    JsonConfigRepository,
)


class _RecordingUomService(UOMDomainService):
    def __init__(self):
        self.quantity_calls = []

    def calculate_condition_quantities(self, *args, **kwargs):
        self.quantity_calls.append((args, kwargs))
        return super().calculate_condition_quantities(*args, **kwargs)


def _area_fixture(thickness=12.0):
    condition = Condition(
        uid="c1",
        name="Concrete",
        condition_type=Condition.TYPE_AREA,
        thickness=thickness,
        ref_no=7,
    )
    takeoff = Takeoff(
        uid="t1",
        condition_uid="c1",
        position=[0.0, 0.0, 144.0, 0.0, 144.0, 144.0, 0.0, 144.0],
    )
    return condition, takeoff


class PdfAnnotationCaptionSettingsTests(unittest.TestCase):
    def test_missing_caption_configuration_uses_canonical_defaults(self):
        config = Config.from_dict({"show_toolbar_text": False})
        self.assertFalse(config.pdf_annotation_captions_enabled)
        self.assertEqual(
            config.pdf_annotation_caption_ids,
            DEFAULT_ANNOTATION_CAPTION_IDS,
        )

    def test_caption_configuration_round_trips_through_existing_json_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            repository = JsonConfigRepository(config_path=config_path)
            expected = Config(
                pdf_annotation_captions_enabled=True,
                pdf_annotation_caption_ids=("area", "volume"),
            )
            repository.save(expected)
            loaded = repository.load()
            self.assertEqual(loaded, expected)
            self.assertEqual(repository.config_path, config_path)
            self.assertEqual(list(Path(temp_dir).iterdir()), [config_path])

    def test_each_caption_identifier_loads_and_saves_independently(self):
        for caption_id in ANNOTATION_CAPTION_ORDER:
            with self.subTest(caption_id=caption_id.value):
                expected = Config(
                    pdf_annotation_captions_enabled=True,
                    pdf_annotation_caption_ids=(caption_id.value,),
                )
                self.assertEqual(Config.from_dict(expected.to_dict()), expected)

    def test_aggregate_preserves_selections_when_master_is_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonConfigRepository(
                config_path=Path(temp_dir) / "config.json"
            )
            repository.save(
                Config(
                    pdf_annotation_captions_enabled=True,
                    pdf_annotation_caption_ids=("area", "volume"),
                )
            )
            aggregate = ConfigAggregate(repository)
            aggregate.update_options(
                Config(
                    pdf_annotation_captions_enabled=False,
                    pdf_annotation_caption_ids=("area", "volume"),
                )
            )
            config = aggregate.snapshot()
            self.assertFalse(config.pdf_annotation_captions_enabled)
            self.assertEqual(
                config.pdf_annotation_caption_ids,
                ("area", "volume"),
            )
            self.assertEqual(
                repository.load().pdf_annotation_caption_ids,
                ("area", "volume"),
            )

    def test_aggregate_canonicalizes_supported_caption_identifiers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonConfigRepository(
                config_path=Path(temp_dir) / "config.json"
            )
            repository.save(
                Config(
                    pdf_annotation_caption_ids=(
                        "volume",
                        "unknown",
                        "area",
                        "volume",
                    )
                )
            )
            aggregate = ConfigAggregate(repository)
            self.assertEqual(
                aggregate.snapshot().pdf_annotation_caption_ids,
                ("area", "volume"),
            )

    def test_aggregate_preserves_empty_caption_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonConfigRepository(
                config_path=Path(temp_dir) / "config.json"
            )
            repository.save(Config(pdf_annotation_caption_ids=()))
            aggregate = ConfigAggregate(repository)
            self.assertEqual(aggregate.snapshot().pdf_annotation_caption_ids, ())


class PdfAnnotationCaptionResolverTests(unittest.TestCase):
    def setUp(self):
        self.uom_service = _RecordingUomService()
        self.resolver = AnnotationCaptionResolver(self.uom_service)
        self.condition, self.takeoff = _area_fixture()

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


if __name__ == "__main__":
    unittest.main()
