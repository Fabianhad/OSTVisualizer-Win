import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.services.ai_takeoff_pdf_source import (
    PageCachePdfSource,
)
from ost_visualizer.presentation.visualization.pdf import ost_pdf
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from tests.presentation.services.ai_takeoff_pdf_support import write_takeoff_pdf

OFFSET_BOXES = {
    "crop box offset": "/MediaBox [0 0 612 792] /CropBox [100 100 512 692]",
    "media box origin": "/MediaBox [100 100 712 892]",
    "rotated crop box offset": (
        "/MediaBox [0 0 612 792] /CropBox [100 100 512 692] /Rotate 90"
    ),
}


class _RecordingRenderer:
    def __init__(self, calls, open_result=None, open_error=None):
        self._calls = calls
        self._open_result = open_result
        self._open_error = open_error
        self._real = ost_pdf.PDFRenderer()

    def open(self, file_path):
        self._calls.append("open")
        if self._open_error is not None:
            raise self._open_error
        if self._open_result is not None:
            return self._open_result
        return self._real.open(file_path)

    def extract_path_segments(self, page_index):
        self._calls.append("extract")
        return self._real.extract_path_segments(page_index)

    def close(self):
        self._calls.append("close")
        self._real.close()


class _PartialInfoPageCache(PageCache):
    def __init__(self, info):
        super().__init__()
        self._info = info

    def get_page_info(self, file_path, page_index=0):
        return dict(self._info)


class _RecordingPageCache(PageCache):
    def __init__(self):
        super().__init__()
        self.requests = []

    def get_text_runs(self, file_path, page_index=0):
        self.requests.append(("text_runs", file_path))
        return super().get_text_runs(file_path, page_index)

    def get_frame(self, file_path, *args, **kwargs):
        self.requests.append(("frame", file_path))
        return super().get_frame(file_path, *args, **kwargs)


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
        for label, boxes in OFFSET_BOXES.items():
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

    def test_release_closes_cached_pdfs_so_the_file_can_be_removed(self):
        self.source.get_text_runs(str(self.pdf), 0)
        self.source.release()
        self.pdf.unlink()
        self.assertFalse(self.pdf.exists())

    def test_missing_pdfs_give_no_runs_or_segments(self):
        missing = str(self.directory / "missing.pdf")
        self.assertEqual(self.source.get_text_runs(missing, 0), [])
        self.assertEqual(self.source.get_vector_segments(missing, 0), [])

    def test_a_pdf_saved_under_a_raster_suffix_is_never_read(self):
        disguised = self.directory / "S-101.tif"
        shutil.copyfile(self.pdf, disguised)
        cache = _RecordingPageCache()
        self.addCleanup(cache.clear)
        source = PageCachePdfSource(cache)
        self.assertEqual(source.get_text_runs(str(disguised), 0), [])
        self.assertEqual(source.get_vector_segments(str(disguised), 0), [])
        self.assertIsNone(
            source.render_frame(str(disguised), 0, 1.0, (0.0, 0.0, 100.0, 50.0))
        )
        self.assertEqual(cache.requests, [])

    def test_page_info_reports_media_size_and_intrinsic_rotation(self):
        pdf = write_takeoff_pdf(
            self.directory / "rotated.pdf",
            page_boxes=OFFSET_BOXES["rotated crop box offset"],
        )
        info = self.source.get_page_info(str(pdf), 0)
        self.assertEqual(info.status, "ok")
        self.assertEqual(
            (info.effective_width_pts, info.effective_height_pts), (592.0, 412.0)
        )
        self.assertEqual((info.media_width_pts, info.media_height_pts), (592.0, 412.0))
        self.assertEqual((info.crop_width_pts, info.crop_height_pts), (412.0, 592.0))
        self.assertEqual(info.intrinsic_rotation, 90)

    def test_page_info_accepts_sub_point_pages_and_rejects_unreadable_ones(self):
        tiny = write_takeoff_pdf(
            self.directory / "tiny.pdf", page_boxes="/MediaBox [0 0 0.5 0.5]"
        )
        info = self.source.get_page_info(str(tiny), 0)
        self.assertEqual(info.status, "ok")
        self.assertEqual((info.effective_width_pts, info.media_height_pts), (0.5, 0.5))
        corrupt = self.directory / "corrupt.pdf"
        corrupt.write_bytes(b"not a pdf at all")
        self.assertEqual(
            self.source.get_page_info(str(corrupt), 0).status, "unavailable"
        )

    def test_page_info_with_partial_metadata(self):
        cases = {
            "no width": ({"pdf_height": 792.0}, "unavailable"),
            "no height": ({"pdf_width": 612.0}, "unavailable"),
            "only the page size": ({"pdf_width": 612.0, "pdf_height": 792.0}, "ok"),
        }
        for label, (info, status) in cases.items():
            with self.subTest(label=label):
                source = PageCachePdfSource(_PartialInfoPageCache(info))
                result = source.get_page_info(str(self.pdf), 0)
                self.assertEqual(result.status, status)
                if status == "ok":
                    self.assertEqual(
                        (
                            result.media_width_pts,
                            result.media_height_pts,
                            result.crop_width_pts,
                            result.crop_height_pts,
                            result.intrinsic_rotation,
                        ),
                        (0.0, 0.0, 0.0, 0.0, 0),
                    )

    def test_vector_extraction_closes_the_renderer_it_opened(self):
        calls = []
        source = PageCachePdfSource(
            self.cache, renderer_factory=lambda: _RecordingRenderer(calls)
        )
        self.assertEqual(len(source.get_vector_segments(str(self.pdf), 0)), 2)
        self.assertEqual(calls, ["open", "extract", "close"])

    def test_a_pdf_the_renderer_cannot_open_gives_no_segments(self):
        calls = []
        source = PageCachePdfSource(
            self.cache,
            renderer_factory=lambda: _RecordingRenderer(calls, open_result=False),
        )
        self.assertEqual(source.get_vector_segments(str(self.pdf), 0), [])
        self.assertEqual(calls, ["open"])

    def test_a_renderer_failure_is_logged_and_gives_no_segments(self):
        calls = []
        source = PageCachePdfSource(
            self.cache,
            renderer_factory=lambda: _RecordingRenderer(
                calls, open_error=OSError("locked")
            ),
        )
        with self.assertLogs(
            "ost_visualizer.presentation.services.ai_takeoff_pdf_source", "WARNING"
        ) as logs:
            self.assertEqual(source.get_vector_segments(str(self.pdf), 0), [])
        self.assertEqual(
            logs.output,
            [
                "WARNING:ost_visualizer.presentation.services.ai_takeoff_pdf_source:"
                "PDF vector extraction failed: OSError"
            ],
        )
        self.assertEqual(calls, ["open"])

    def test_render_frame_returns_the_unrotated_cached_frame(self):
        image = self.source.render_frame(
            str(self.pdf), 0, 2.0, (72.0, 72.0, 100.0, 50.0)
        )
        self.assertEqual((image.width(), image.height()), (200, 100))
        cached = self.cache.get_frame(str(self.pdf), 0, 2.0, 72.0, 72.0, 100.0, 50.0, 0)
        self.assertIs(cached, image)


if __name__ == "__main__":
    unittest.main()
