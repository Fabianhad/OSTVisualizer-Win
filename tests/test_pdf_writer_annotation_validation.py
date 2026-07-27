import tempfile
import unittest
from pathlib import Path

from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer


class PdfWriterAnnotationValidationTests(unittest.TestCase):
    def setUp(self):
        source_path = (
            Path(__file__).parents[1]
            / "cpp_extensions"
            / "src"
            / "pdf"
            / "bluebeam_annotation.cpp"
        )
        binary_path = Path(ost_pdf_writer.__file__)
        if source_path.stat().st_mtime > binary_path.stat().st_mtime:
            self.skipTest("ost_pdf_writer must be rebuilt for native source changes")

    def test_empty_polygon_returns_failure_instead_of_accessing_missing_vertex(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "blank.pdf"
            writer = ost_pdf_writer.PDFWriter()
            page = ost_pdf_writer.PageExportData()
            page.is_blank = True
            page.page_width = 72.0
            page.page_height = 72.0
            self.assertTrue(writer.merge_pages_with_annotations([page], str(pdf_path)))

            self.assertFalse(
                writer.add_polygon_annotation(
                    str(pdf_path),
                    [],
                    "Empty",
                    [255, 0, 0],
                    0.5,
                )
            )

            self.assertIn("must contain vertices", writer.get_last_error())

    def test_empty_ink_strokes_return_failure_instead_of_accessing_missing_point(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "blank.pdf"
            writer = ost_pdf_writer.PDFWriter()
            page = ost_pdf_writer.PageExportData()
            page.is_blank = True
            page.page_width = 72.0
            page.page_height = 72.0
            ink = ost_pdf_writer.InkAnnotationData()
            ink.strokes = [[]]
            page.inks = [ink]

            self.assertFalse(writer.merge_pages_with_annotations([page], str(pdf_path)))

            self.assertIn("must contain points", writer.get_last_error())


if __name__ == "__main__":
    unittest.main()
