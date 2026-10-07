import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.services.ai_takeoff_pdf_source import (
    PageCachePdfSource,
)
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from tests.presentation.services.ai_takeoff_pdf_support import write_takeoff_pdf


class PageCachePdfSourceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.pdf = write_takeoff_pdf(
            self.directory / "S-101.pdf",
            lines=[(72, 720, 272, 720), (72, 720, 72, 520)],
            texts=[(100, 700, 12, "SLAB 8 IN")],
        )
        self.cache = PageCache()
        self.addCleanup(self.cache.clear)
        self.source = PageCachePdfSource(self.cache)

    def test_page_info_for_a_real_pdf(self):
        info = self.source.get_page_info(str(self.pdf), 0)
        self.assertEqual(info.status, "ok")
        self.assertEqual(
            (info.effective_width_pts, info.effective_height_pts), (612.0, 792.0)
        )
        self.assertEqual((info.crop_width_pts, info.crop_height_pts), (612.0, 792.0))
        self.assertEqual(info.intrinsic_rotation, 0)

    def test_page_info_status_for_missing_and_non_pdf_files(self):
        self.assertEqual(
            self.source.get_page_info(str(self.directory / "missing.pdf"), 0).status,
            "missing",
        )
        raster = self.directory / "scan.tif"
        raster.write_bytes(b"not an image")
        self.assertEqual(self.source.get_page_info(str(raster), 0).status, "not_pdf")
        self.assertEqual(self.source.get_page_info("", 0).status, "not_configured")

    def test_text_runs_are_extracted_in_raw_pdf_space(self):
        runs = self.source.get_text_runs(str(self.pdf), 0)
        texts = [run.text for run in runs]
        self.assertIn("SLAB", texts)
        slab = runs[texts.index("SLAB")]
        self.assertAlmostEqual(slab.left, 100.0, delta=2.0)
        self.assertGreater(slab.top, slab.bottom)
        self.assertAlmostEqual(slab.bottom, 700.0, delta=4.0)

    def test_vector_segments_are_extracted(self):
        segments = self.source.get_vector_segments(str(self.pdf), 0)
        coordinates = {
            tuple(round(value) for value in (s.x1, s.y1, s.x2, s.y2)) for s in segments
        }
        self.assertIn((72, 720, 272, 720), coordinates)
        self.assertIn((72, 720, 72, 520), coordinates)

    def test_raw_coordinates_start_at_the_visible_box_origin(self):
        cases = {
            "crop box offset": "/MediaBox [0 0 612 792] /CropBox [100 100 512 692]",
            "media box origin": "/MediaBox [100 100 712 892]",
        }
        for label, boxes in cases.items():
            with self.subTest(label=label):
                pdf = write_takeoff_pdf(
                    self.directory / f"{label}.pdf",
                    lines=[(150, 600, 350, 600)],
                    texts=[(150, 500, 12, "GRID")],
                    page_boxes=boxes,
                )
                segments = self.source.get_vector_segments(str(pdf), 0)
                self.assertEqual(
                    [
                        tuple(round(v) for v in (s.x1, s.y1, s.x2, s.y2))
                        for s in segments
                    ],
                    [(50, 500, 250, 500)],
                )
                run = self.source.get_text_runs(str(pdf), 0)[0]
                self.assertAlmostEqual(run.left, 50.0, delta=2.0)
                self.assertAlmostEqual(run.bottom, 400.0, delta=4.0)
                self.assertTrue(0.0 < run.top - run.bottom < 20.0)
                self.assertTrue(0.0 < run.right - run.left < 60.0)

    def test_missing_pdfs_give_no_runs_or_segments(self):
        missing = str(self.directory / "missing.pdf")
        self.assertEqual(self.source.get_text_runs(missing, 0), [])
        self.assertEqual(self.source.get_vector_segments(missing, 0), [])


if __name__ == "__main__":
    unittest.main()
