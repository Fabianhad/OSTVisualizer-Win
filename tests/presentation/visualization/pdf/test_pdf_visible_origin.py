import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from ost_visualizer.presentation.visualization.pdf.pdf_visible_origin import (
    read_visible_box_origin,
)
from tests.presentation.services.ai_takeoff_pdf_support import write_takeoff_pdf


class _FailingReader:
    def get_page_geometries(self, _file_path):
        raise RuntimeError("C:/private/plans.pdf cannot be parsed")


class _TwoPageReader:
    def get_page_geometries(self, _file_path):
        return [
            SimpleNamespace(visible_box=[10.0, 20.0, 110.0, 220.0]),
            SimpleNamespace(visible_box=[30.0, 5.0, 330.0, 405.0]),
        ]


class ReadVisibleBoxOriginTests(unittest.TestCase):
    def test_real_pdf_with_an_asymmetric_crop_box(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf = write_takeoff_pdf(
                Path(directory) / "asymmetric.pdf",
                page_boxes="/MediaBox [0 0 612 792] /CropBox [120 40 520 640]",
            )
            self.assertEqual(read_visible_box_origin(str(pdf), 0), (120.0, 40.0))

    def test_each_page_uses_its_own_box(self):
        self.assertEqual(
            read_visible_box_origin("x.pdf", 0, _TwoPageReader), (10.0, 20.0)
        )
        self.assertEqual(
            read_visible_box_origin("x.pdf", 1, _TwoPageReader), (30.0, 5.0)
        )

    def test_unreadable_geometry_falls_back_to_the_page_origin(self):
        self.assertEqual(
            read_visible_box_origin("x.pdf", 2, _TwoPageReader), (0.0, 0.0)
        )
        self.assertEqual(
            read_visible_box_origin("x.pdf", -1, _TwoPageReader), (0.0, 0.0)
        )
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / "missing.pdf")
            self.assertEqual(read_visible_box_origin(missing, 0), (0.0, 0.0))
        with self.assertLogs(
            "ost_visualizer.presentation.visualization.pdf.pdf_visible_origin",
            "WARNING",
        ) as logs:
            self.assertEqual(
                read_visible_box_origin("x.pdf", 0, _FailingReader), (0.0, 0.0)
            )
        self.assertIn("RuntimeError", logs.output[0])
        self.assertNotIn("private", logs.output[0])


if __name__ == "__main__":
    unittest.main()
