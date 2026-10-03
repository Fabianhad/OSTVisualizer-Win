import re
import tempfile
import unittest
import zlib
from pathlib import Path
from ost_visualizer.application.dtos.annotation_caption_dto import (
    AnnotationCaptionSettingsDto,
)
from ost_visualizer.application.services.annotation_caption_resolver import (
    AnnotationCaptionResolver,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.domain.services.takeoff_service_impl import TakeoffDomainService
from ost_visualizer.domain.services.uom_service_impl import UOMDomainService
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)
from tests.domain.services.elevation_support import (
    _EXPECTED_PDF_CALLOUT_LINES as _elevation_support__EXPECTED_PDF_CALLOUT_LINES,
    _area_condition as _elevation_support__area_condition,
    _area_takeoff as _elevation_support__area_takeoff,
)


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
        self.condition = _elevation_support__area_condition(layer_uid="layer-1")
        self.takeoff = _elevation_support__area_takeoff()
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

    def test_native_textbox_pipeline_writes_all_four_callout_lines(self):
        _polygons, callouts = self.exporter._collect_takeoffs(
            [self.takeoff],
            {self.condition.uid: self.condition},
            self.page_info,
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            caption_settings=AnnotationCaptionSettingsDto(False, ()),
            elevation_callouts_enabled=True,
        )
        self.assertEqual(len(callouts), 1)
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
        for expected_line in _elevation_support__EXPECTED_PDF_CALLOUT_LINES:
            self.assertIn(expected_line.encode("ascii"), appearance_streams[0])
        # The four lines are separate text-show operators in the given order,
        # not one joined string.
        shown_lines = [
            text.replace(b"'", b"'")
            for text in re.findall(rb"\((.*?)\) Tj", appearance_streams[0])
        ]
        self.assertEqual(
            shown_lines,
            [
                line.encode("ascii")
                for line in _elevation_support__EXPECTED_PDF_CALLOUT_LINES
            ],
        )
        # Centered 180 x 52 pt callout box (_ELEVATION_CALLOUT_BOX_WIDTH/HEIGHT).
        self.assertIn(b"/Q 1", pdf_bytes)
        rect = [
            float(value)
            for value in re.search(rb"/Rect \[\s*([^\]]+)\]", pdf_bytes)
            .group(1)
            .split()
        ]
        self.assertEqual((rect[2] - rect[0], rect[3] - rect[1]), (180.0, 52.0))
