import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.pdf import ost_pdf


class PdfRendererNativeValidationTests(unittest.TestCase):
    def setUp(self):
        source_path = (
            Path(__file__).parents[1]
            / "cpp_extensions"
            / "src"
            / "pdf"
            / "pdf_renderer.cpp"
        )
        binary_path = Path(ost_pdf.__file__)
        if source_path.stat().st_mtime > binary_path.stat().st_mtime:
            self.skipTest("ost_pdf must be rebuilt for native source changes")

    def _create_blank_pdf(self, directory: str) -> Path:
        pdf_path = Path(directory) / "blank.pdf"
        writer = ost_pdf_writer.PDFWriter()
        page = ost_pdf_writer.PageExportData()
        page.is_blank = True
        page.page_width = 72.0
        page.page_height = 72.0
        self.assertTrue(writer.merge_pages_with_annotations([page], str(pdf_path)))
        return pdf_path

    def test_render_rejects_invalid_scales_and_frame_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = self._create_blank_pdf(temp_dir)
            renderer = ost_pdf.PDFRenderer()
            self.assertTrue(renderer.open(str(pdf_path)))

            for scale in (0.0, -1.0, math.nan, math.inf, 1.0e30):
                with self.subTest(scale=scale):
                    self.assertIsNone(renderer.render_page(0, scale, 0))

            self.assertIsNone(
                renderer.render_page_frame(0, math.inf, 0.0, 0.0, 10.0, 10.0, 0)
            )
            self.assertIsNone(
                renderer.render_page_frame(0, 1.0, math.nan, 0.0, 10.0, 10.0, 0)
            )
            self.assertIsNone(
                renderer.render_page_frame(0, 1.0, 0.0, 0.0, math.inf, 10.0, 0)
            )

            page = renderer.render_page(0, 0.25, 0)
            self.assertIsNotNone(page)
            self.assertEqual((page.width, page.height, page.stride), (18, 18, 72))
            renderer.close()

    def test_pdfium_can_reinitialize_after_explicit_shutdown(self):
        repo = Path(__file__).parents[1]
        code = """
import tempfile
from pathlib import Path
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.pdf import ost_pdf

with tempfile.TemporaryDirectory() as temp_dir:
    path = Path(temp_dir) / "blank.pdf"
    writer = ost_pdf_writer.PDFWriter()
    page = ost_pdf_writer.PageExportData()
    page.is_blank = True
    page.page_width = 72.0
    page.page_height = 72.0
    assert writer.merge_pages_with_annotations([page], str(path))
    renderer = ost_pdf.PDFRenderer()
    assert renderer.open(str(path))
    renderer.close()
    del renderer
    ost_pdf.shutdown()
    ost_pdf.initialize()
    renderer = ost_pdf.PDFRenderer()
    assert renderer.open(str(path))
    assert renderer.page_count() == 1
    renderer.close()
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
