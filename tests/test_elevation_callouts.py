import re
import tempfile
import unittest
import zlib
from dataclasses import fields
from pathlib import Path
from unittest import mock
from ost_visualizer.application.dtos.annotation_caption_dto import (
    AnnotationCaptionSettingsDto,
)
from ost_visualizer.application.dtos.page_export_data_dto import PageExportData
from ost_visualizer.application.services.annotation_caption_resolver import (
    AnnotationCaptionResolver,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.elevation_callout import ElevationCallout
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.domain.services.elevation_callout_service import (
    resolve_elevation_callout,
)
from ost_visualizer.domain.services.takeoff_service_impl import TakeoffDomainService
from ost_visualizer.domain.services.uom_service_impl import UOMDomainService
from ost_visualizer.infrastructure.persistence.repositories.json_config_repository import (
    JsonConfigRepository,
)
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)

_EXPECTED_PDF_CALLOUT_LINES = ["F9", "10' - 0\"", "8' - 0\"", "5.14 CY"]


def _outer_ring(outer_ring=None):
    if outer_ring is None:
        outer_ring = (
            (10.0, 20.0),
            (50.0, 20.0),
            (50.0, 60.0),
            (10.0, 60.0),
        )
    return tuple(outer_ring)


def _area_condition(**overrides):
    values = {
        "uid": "condition-1",
        "name": "F9 @T 10' 0\"",
        "condition_type": Condition.TYPE_AREA,
        "thickness": 24.0,
        "z_value": 120.0,
        "is_top": True,
    }
    values.update(overrides)
    return Condition(**values)


def _area_takeoff(**overrides):
    values = {
        "uid": "takeoff-1",
        "condition_uid": "condition-1",
        "page_uid": "page-1",
        "area_uid": "area-1",
        "position": [0.0, 0.0, 100.0, 0.0, 100.0, 100.0, 0.0, 100.0],
    }
    values.update(overrides)
    return Takeoff(**values)


class ElevationCalloutResolverTests(unittest.TestCase):
    def test_resolves_exact_lines_and_transformed_center(self):
        result = resolve_elevation_callout(
            _area_condition(name="F9 @T 410' 3\"", thickness=48.0, z_value=4923.0),
            _area_takeoff(),
            [],
            _outer_ring(),
        )
        self.assertEqual(
            result,
            ElevationCallout(
                x=30.0,
                y=40.0,
                lines=("F9", "410' - 3\"", "406' - 3\"", "10.29 CY"),
            ),
        )

    def test_quantity_variants_remain_owned_by_canonical_quantity_logic(self):
        hole = Takeoff(
            uid="hole-1",
            condition_uid="condition-1",
            parent_uid="takeoff-1",
            position=[25.0, 25.0, 75.0, 25.0, 75.0, 75.0, 25.0, 75.0],
        )
        cases = (
            ("hole", _area_condition(), _area_takeoff(), [hole], "3.86 CY"),
            (
                "slope",
                _area_condition(rise=6.0, run=12.0),
                _area_takeoff(),
                [],
                "5.75 CY",
            ),
            (
                "rounding",
                _area_condition(round_quantity=True, round_up=1.0),
                _area_takeoff(),
                [],
                "5.14 CY",
            ),
            (
                "negative",
                _area_condition(),
                _area_takeoff(is_negative=True),
                [],
                "-5.14 CY",
            ),
        )
        for name, condition, takeoff, holes, expected in cases:
            with self.subTest(name=name):
                result = resolve_elevation_callout(
                    condition, takeoff, holes, _outer_ring()
                )
                self.assertIsNotNone(result)
                self.assertEqual(result.lines[-1], expected)

    def test_bottom_reference_uses_existing_condition_elevation_direction(self):
        condition = Condition(
            uid="condition-1",
            name="Footing @B 8' 0\"",
            condition_type=Condition.TYPE_COUNT,
            width=54.0,
            height=24.0,
            depth=45.0,
            z_value=96.0,
            is_top=False,
        )
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-1",
            position=[30.0, 40.0],
        )
        result = resolve_elevation_callout(condition, takeoff, [], _outer_ring())
        self.assertEqual(
            result.lines,
            ("Footing", "10' - 0\"", "8' - 0\"", "1.25 CY"),
        )

    def test_inapplicable_elevation_or_invalid_outer_ring_is_omitted(self):
        self.assertIsNone(
            resolve_elevation_callout(
                _area_condition(name="F9"),
                _area_takeoff(),
                [],
                _outer_ring(),
            )
        )
        self.assertIsNone(
            resolve_elevation_callout(
                _area_condition(),
                _area_takeoff(),
                [],
                _outer_ring(()),
            )
        )

    def test_resolved_dto_contains_only_rendered_content_and_center(self):
        self.assertEqual(
            {field.name for field in fields(ElevationCallout)},
            {"x", "y", "lines"},
        )


class ElevationCalloutConfigTests(unittest.TestCase):
    def test_defaults_preserve_html_behavior_and_leave_pdf_unchanged(self):
        config = Config()
        self.assertTrue(config.html_elevation_callouts_enabled)
        self.assertFalse(config.pdf_elevation_callouts_enabled)

    def test_legacy_config_uses_canonical_callout_defaults(self):
        config = Config.from_dict({"show_toolbar_text": False})
        self.assertTrue(config.html_elevation_callouts_enabled)
        self.assertFalse(config.pdf_elevation_callouts_enabled)

    def test_independent_callout_settings_round_trip_in_existing_config_payload(self):
        expected = Config(
            html_elevation_callouts_enabled=False,
            pdf_elevation_callouts_enabled=True,
        )
        loaded = Config.from_dict(expected.to_dict())
        self.assertEqual(loaded, expected)

    def test_callout_settings_persist_through_existing_json_repository(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = JsonConfigRepository(
                config_path=Path(temp_dir) / "config.json"
            )
            expected = Config(
                html_elevation_callouts_enabled=False,
                pdf_elevation_callouts_enabled=True,
            )
            repository.save(expected)
            self.assertEqual(repository.load(), expected)


class _CapturingPdfWriter:
    def __init__(self):
        self.pages = []

    def merge_pages_with_annotations(self, pages, _output_path):
        self.pages = list(pages)
        return True

    def get_last_error(self):
        return ""


class PdfElevationCalloutTests(unittest.TestCase):
    def setUp(self):
        uom_service = UOMDomainService()
        self.exporter = PDFExporter(
            OSTCoordinateSystem(),
            ColorService(),
            TakeoffDomainService(),
            uom_service,
            AnnotationCaptionResolver(uom_service),
        )
        self.condition = _area_condition(layer_uid="layer-1")
        self.takeoff = _area_takeoff()
        self.page_info = {
            "scale_factor1": 1.0,
            "scale_factor2": 1.0,
            "rotation": 0,
            "flip_x": False,
            "flip_y": False,
            "width": 612.0,
            "height": 792.0,
            "view_scale": 2.0,
        }

    def test_disabled_pdf_callouts_add_no_text_and_skip_resolution(self):
        with mock.patch.object(
            self.exporter, "_build_elevation_callout_text"
        ) as callout_adapter:
            polygons, callouts = self.exporter._collect_takeoffs(
                [self.takeoff],
                {self.condition.uid: self.condition},
                self.page_info,
                caption_settings=AnnotationCaptionSettingsDto(False, ()),
                elevation_callouts_enabled=False,
            )
        self.assertEqual(len(polygons), 1)
        self.assertEqual(callouts, [])
        callout_adapter.assert_not_called()

    def test_enabled_pdf_callout_uses_existing_textbox_data_with_shared_lines(self):
        polygons, callouts = self.exporter._collect_takeoffs(
            [self.takeoff],
            {self.condition.uid: self.condition},
            self.page_info,
            caption_settings=AnnotationCaptionSettingsDto(False, ()),
            elevation_callouts_enabled=True,
        )
        self.assertEqual(len(polygons), 1)
        self.assertEqual(len(callouts), 1)
        callout = callouts[0]
        self.assertIsInstance(callout, ost_pdf_writer.TextAnnotationData)
        self.assertEqual(
            callout.content.splitlines(),
            _EXPECTED_PDF_CALLOUT_LINES,
        )
        self.assertEqual(callout.text_align, "center")
        self.assertEqual(callout.font_size, 10.0)
        vertices = polygons[0].vertices
        center_x = (
            min(point[0] for point in vertices) + max(point[0] for point in vertices)
        ) / 2.0
        center_y = (
            min(point[1] for point in vertices) + max(point[1] for point in vertices)
        ) / 2.0
        self.assertEqual((callout.min_x + callout.max_x) / 2.0, center_x)
        self.assertEqual((callout.min_y + callout.max_y) / 2.0, center_y)

    def test_export_adds_resolved_callout_to_existing_page_text_pipeline(self):
        writer = _CapturingPdfWriter()
        self.exporter._writer = writer
        page = Page(
            uid="page-1",
            name="Page 1",
            width_pts=612.0,
            height_pts=792.0,
        )
        result = self.exporter.export(
            [
                PageExportData(
                    page=page,
                    bid_takeoffs=[self.takeoff],
                    bid_conditions={self.condition.uid: self.condition},
                )
            ],
            "out.pdf",
            Config.DISPLAY_MODE_ORIGINAL,
            False,
            AnnotationCaptionSettingsDto(False, ()),
            True,
        )
        self.assertTrue(result.success)
        self.assertEqual(len(writer.pages), 1)
        self.assertEqual(len(writer.pages[0].texts), 1)
        self.assertEqual(
            writer.pages[0].texts[0].content.splitlines(),
            _EXPECTED_PDF_CALLOUT_LINES,
        )

    def test_native_textbox_pipeline_writes_all_four_callout_lines(self):
        _polygons, callouts = self.exporter._collect_takeoffs(
            [self.takeoff],
            {self.condition.uid: self.condition},
            self.page_info,
            caption_settings=AnnotationCaptionSettingsDto(False, ()),
            elevation_callouts_enabled=True,
        )
        page = ost_pdf_writer.PageExportData()
        page.is_blank = True
        page.page_width = 612.0
        page.page_height = 792.0
        page.rotation = 0
        page.texts = callouts
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = str(Path(temp_dir) / "callout.pdf")
            writer = ost_pdf_writer.PDFWriter()
            self.assertTrue(writer.merge_pages_with_annotations([page], output_path))
            pdf_bytes = Path(output_path).read_bytes()
        self.assertIn(b"/Subtype /FreeText", pdf_bytes)
        appearance_streams = []
        for match in re.finditer(rb"stream\r?\n(.*?)endstream", pdf_bytes, re.S):
            stream = match.group(1)
            try:
                stream = zlib.decompress(stream)
            except zlib.error:
                pass
            if b"F9" in stream:
                appearance_streams.append(stream)
        self.assertEqual(len(appearance_streams), 1)
        for expected_line in _EXPECTED_PDF_CALLOUT_LINES:
            self.assertIn(expected_line.encode("ascii"), appearance_streams[0])


if __name__ == "__main__":
    unittest.main()
