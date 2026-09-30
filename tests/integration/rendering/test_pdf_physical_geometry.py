import tempfile
import unittest
from pathlib import Path
from ost_visualizer.application.render_quality import INTERACTIVE_PDF_RENDER_SCALE
from ost_visualizer.application.services.page_load_strategy_service import (
    PageLoadStrategyService,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.visualization.pdf.renderers.page_renderer import (
    PageRenderer,
)


def _write_vector_pdf(path: Path, width_pts: float, height_pts: float) -> None:
    stream = (
        f"0 0 m {width_pts} {height_pts} l S\n" f"0 {height_pts} m {width_pts} 0 l S\n"
    ).encode("ascii")
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            "3 0 obj\n"
            "<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {width_pts} {height_pts}] "
            "/Resources << >> /Contents 4 0 R >>\n"
            "endobj\n"
        ).encode("ascii"),
        (
            f"4 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"endstream\nendobj\n"
        ),
    ]
    content = b"%PDF-1.4\n"
    offsets = [0]
    for obj in objects:
        offsets.append(len(content))
        content += obj
    xref_offset = len(content)
    content += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    content += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        content += f"{offset:010d} 00000 n \n".encode("ascii")
    content += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    path.write_bytes(content)


class PlanViewPdfGeometryTests(unittest.TestCase):
    def test_mismatched_import_dimensions_use_native_pdf_physical_geometry(self):
        # Minimized equivalent of the affected 36x24 PDF imported as 42x30.
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "affected.pdf"
            _write_vector_pdf(pdf_path, 240.0, 160.0)
            renderer = PageRenderer()
            try:
                info = renderer.get_page_info(str(pdf_path), 0)
                strategy = PageLoadStrategyService(renderer).determine_load_strategy(
                    Page(
                        uid="affected",
                        name="Affected",
                        image_path=str(pdf_path),
                        width_pts=280.0,
                        height_pts=200.0,
                    )
                )
                low_resolution = renderer.render(str(pdf_path), 0, 1.25, 0)
                high_resolution = renderer.render_frame(
                    str(pdf_path),
                    0,
                    2.0,
                    0.0,
                    0.0,
                    strategy.pdf_width_pts,
                    strategy.pdf_height_pts,
                    0,
                )
            finally:
                renderer.close()
        self.assertEqual(info["media_width_pts"], 240.0)
        self.assertEqual(info["media_height_pts"], 160.0)
        self.assertEqual(info["pdf_width"], 240.0)
        self.assertEqual(info["pdf_height"], 160.0)
        self.assertEqual(info["intrinsic_rotation"], 0)
        self.assertEqual(strategy.pdf_width_pts, 240.0)
        self.assertEqual(strategy.pdf_height_pts, 160.0)
        self.assertEqual(
            strategy.placeholder_width,
            240.0 * INTERACTIVE_PDF_RENDER_SCALE,
        )
        self.assertEqual(
            strategy.placeholder_height,
            160.0 * INTERACTIVE_PDF_RENDER_SCALE,
        )
        self.assertIsNotNone(low_resolution)
        self.assertIsNotNone(high_resolution)
        self.assertEqual((low_resolution.width(), low_resolution.height()), (300, 200))
        self.assertEqual(
            (high_resolution.width(), high_resolution.height()),
            (480, 320),
        )
        self.assertEqual(
            (
                low_resolution.width() / 1.25,
                low_resolution.height() / 1.25,
            ),
            (
                high_resolution.width() / 2.0,
                high_resolution.height() / 2.0,
            ),
        )

    def test_matching_normal_pdf_geometry_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "normal.pdf"
            _write_vector_pdf(pdf_path, 280.0, 200.0)
            renderer = PageRenderer()
            try:
                strategy = PageLoadStrategyService(renderer).determine_load_strategy(
                    Page(
                        uid="normal",
                        name="Normal",
                        image_path=str(pdf_path),
                        width_pts=280.0,
                        height_pts=200.0,
                    )
                )
            finally:
                renderer.close()
        self.assertEqual(strategy.pdf_width_pts, 280.0)
        self.assertEqual(strategy.pdf_height_pts, 200.0)
        self.assertEqual(
            strategy.placeholder_width,
            280.0 * INTERACTIVE_PDF_RENDER_SCALE,
        )
        self.assertEqual(
            strategy.placeholder_height,
            200.0 * INTERACTIVE_PDF_RENDER_SCALE,
        )


if __name__ == "__main__":
    unittest.main()
