import tempfile
import unittest
from pathlib import Path
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer


class PdfWriterAnnotationValidationTests(unittest.TestCase):
    def setUp(self):
        source_root = Path(__file__).parents[1] / "cpp_extensions" / "src"
        source_paths = (
            source_root / "module_pdf_writer.cpp",
            source_root / "common" / "page_transform.hpp",
            source_root / "pdf" / "pdf_writer.cpp",
            source_root / "pdf" / "pdf_writer.hpp",
            source_root / "pdf" / "bluebeam_annotation.cpp",
            source_root / "pdf" / "bluebeam_annotation.hpp",
        )
        binary_path = Path(ost_pdf_writer.__file__)
        if any(
            path.stat().st_mtime > binary_path.stat().st_mtime for path in source_paths
        ):
            self.skipTest("ost_pdf_writer must be rebuilt for native source changes")

    def test_empty_polygon_returns_failure_instead_of_accessing_missing_vertex(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "blank.pdf"
            writer = ost_pdf_writer.PDFWriter()
            page = ost_pdf_writer.PageExportData()
            page.is_blank = True
            page.page_width = 72.0
            page.page_height = 72.0
            polygon = ost_pdf_writer.PolygonAnnotationData()
            polygon.vertices = []
            page.takeoffs = [polygon]
            self.assertFalse(writer.merge_pages_with_annotations([page], str(pdf_path)))
            self.assertIn("must contain vertices", writer.get_last_error())

    def test_page_export_contract_rejects_incomplete_or_conflicting_geometry(self):
        cases = []
        unconfigured = ost_pdf_writer.PageExportData()
        unconfigured.is_blank = True
        cases.append((unconfigured, "canonical dimensions"))
        missing_source = ost_pdf_writer.PageExportData()
        missing_source.page_width = 72.0
        missing_source.page_height = 72.0
        missing_source.source_width = 72.0
        missing_source.source_height = 72.0
        cases.append((missing_source, "require a source PDF"))
        conflicting_blank = ost_pdf_writer.PageExportData()
        conflicting_blank.is_blank = True
        conflicting_blank.source_pdf = "not-a-blank-page.pdf"
        conflicting_blank.page_width = 72.0
        conflicting_blank.page_height = 72.0
        cases.append((conflicting_blank, "must not specify a source PDF"))
        mismatched_rotation = ost_pdf_writer.PageExportData()
        mismatched_rotation.source_pdf = "not-opened-before-validation.pdf"
        mismatched_rotation.source_width = 72.0
        mismatched_rotation.source_height = 144.0
        mismatched_rotation.page_width = 72.0
        mismatched_rotation.page_height = 144.0
        mismatched_rotation.rotation = 90
        cases.append((mismatched_rotation, "do not match source dimensions"))
        invalid_rotation = ost_pdf_writer.PageExportData()
        invalid_rotation.is_blank = True
        invalid_rotation.page_width = 72.0
        invalid_rotation.page_height = 72.0
        invalid_rotation.rotation = 45
        cases.append((invalid_rotation, "multiple of 90"))
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "invalid.pdf"
            for page, message in cases:
                with self.subTest(message=message):
                    writer = ost_pdf_writer.PDFWriter()
                    self.assertFalse(
                        writer.merge_pages_with_annotations([page], str(output_path))
                    )
                    self.assertIn(message, writer.get_last_error())

    def test_page_export_requires_at_least_one_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = ost_pdf_writer.PDFWriter()
            output_path = Path(temp_dir) / "empty.pdf"
            self.assertFalse(writer.merge_pages_with_annotations([], str(output_path)))
            self.assertIn("at least one page", writer.get_last_error())

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

    def test_highlight_contract_rejects_empty_or_nonfinite_data(self):
        valid_path = [
            (0.0, 0.0),
            (0.0, 10.0),
            (0.0, 10.0),
            (10.0, 10.0),
            (10.0, 10.0),
            (10.0, 0.0),
            (10.0, 0.0),
            (0.0, 0.0),
        ]
        cases = []
        empty = ost_pdf_writer.HighlightAnnotationData()
        empty.paths = []
        cases.append((empty, "must contain paths"))
        nonfinite_coordinate = ost_pdf_writer.HighlightAnnotationData()
        nonfinite_coordinate.paths = [
            [
                (float("nan"), y) if index == 0 else (x, y)
                for index, (x, y) in enumerate(valid_path)
            ]
        ]
        cases.append((nonfinite_coordinate, "coordinates must be finite"))
        nonfinite_opacity = ost_pdf_writer.HighlightAnnotationData()
        nonfinite_opacity.paths = [valid_path]
        nonfinite_opacity.opacity = float("nan")
        cases.append((nonfinite_opacity, "opacity must be finite"))
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "invalid-highlight.pdf"
            for highlight, message in cases:
                with self.subTest(message=message):
                    writer = ost_pdf_writer.PDFWriter()
                    page = ost_pdf_writer.PageExportData()
                    page.is_blank = True
                    page.page_width = 72.0
                    page.page_height = 72.0
                    page.highlights = [highlight]
                    self.assertFalse(
                        writer.merge_pages_with_annotations([page], str(output_path))
                    )
                    self.assertIn(message, writer.get_last_error())


if __name__ == "__main__":
    unittest.main()
