import tempfile
import unittest
from pathlib import Path
from ost_visualizer.domain.entities.overlay import overlay_units_per_sheet_inch
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.visualization.pdf.renderers.page_renderer import (
    PageRenderer,
)
from tests.integration.geometry.overlay_calibration_support import (
    _page as _overlay_calibration_support__page,
    _write_box_pdf as _overlay_calibration_support__write_box_pdf,
)


class OverlayCoordinateContractTests(unittest.TestCase):
    def test_pdf_boxes_and_intrinsic_rotation_are_normalized_upstream(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "boxes.pdf"
            _overlay_calibration_support__write_box_pdf(pdf_path)
            renderer = PageRenderer()
            try:
                info = renderer.get_page_info(str(pdf_path), 0)
            finally:
                renderer.close()
        self.assertEqual(info["media_width_pts"], 80.0)
        self.assertEqual(info["media_height_pts"], 180.0)
        self.assertEqual(info["crop_width_pts"], 180.0)
        self.assertEqual(info["crop_height_pts"], 80.0)
        self.assertEqual(info["intrinsic_rotation"], 90)
        coordinate_ratio = overlay_units_per_sheet_inch(0.1875, 12.0)
        rect = (
            0.0,
            0.0,
            info["pdf_width"] / 72.0 * coordinate_ratio,
            info["pdf_height"] / 72.0 * coordinate_ratio,
        )
        page = _overlay_calibration_support__page(
            rect,
            width_pts=info["pdf_width"],
            height_pts=info["pdf_height"],
        )
        self.assertEqual(page.overlay_rect_page_points(), (0.0, 0.0, 80.0, 180.0))
