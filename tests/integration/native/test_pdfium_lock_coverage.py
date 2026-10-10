import gc
import logging
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from tests.paths import REPO_ROOT
from tests.presentation.services.ai_takeoff_pdf_support import write_content_pdf
from ost_visualizer.presentation.visualization.pdf import ost_pdf

_CONTENT = (
    "0 0 0 RG 1 w 10 10 m 190 90 l S\n"
    "0 0 1 rg 20 20 30 30 re f\n"
    "BT /F1 12 Tf 40 60 Td (A1) Tj ET\n"
)


class _PdfiumEntries:
    def __enter__(self):
        self._start = ost_pdf.pdfium_entry_counts()
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        end = ost_pdf.pdfium_entry_counts()
        self.entries = end[0] - self._start[0]
        self.unlocked = end[1] - self._start[1]


class _PdfiumLockCase(unittest.TestCase):
    def setUp(self):
        source_path = REPO_ROOT / "cpp_extensions" / "src" / "pdf" / "pdf_renderer.cpp"
        if source_path.stat().st_mtime > Path(ost_pdf.__file__).stat().st_mtime:
            self.skipTest("ost_pdf must be rebuilt for native source changes")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.pdf_path = str(
            write_content_pdf(Path(directory.name) / "sheet.pdf", _CONTENT, 200, 100)
        )

    def assertLockedEntries(self, probe):
        self.assertGreater(probe.entries, 0, "path never reached PDFium")
        self.assertEqual(probe.unlocked, 0, "PDFium entered without the lock")


class RendererMethodLockTests(_PdfiumLockCase):
    def test_every_renderer_method_enters_pdfium_under_the_lock(self):
        token = ost_pdf.RenderCancelToken()
        calls = {
            "page_count": lambda r: r.page_count(),
            "page_size": lambda r: r.page_size(0),
            "page_label": lambda r: r.page_label(0),
            "page_info": lambda r: r.page_info(0),
            "all_page_info": lambda r: r.all_page_info(),
            "extract_path_segments": lambda r: r.extract_path_segments(0),
            "extract_path_items": lambda r: r.extract_path_items(0, 100),
            "extract_text_runs": lambda r: r.extract_text_runs(0),
            "render_page": lambda r: r.render_page(0, 0.5, 0),
            "render_page_cancellable": lambda r: r.render_page_cancellable(
                0, 0.5, 0, token
            ),
            "render_page_frame": lambda r: r.render_page_frame(
                0, 0.5, 0.0, 0.0, 50.0, 50.0, 0
            ),
            "render_page_frame_cancellable": (
                lambda r: r.render_page_frame_cancellable(
                    0, 0.5, 0.0, 0.0, 50.0, 50.0, 0, token
                )
            ),
        }
        for name, call in calls.items():
            with self.subTest(method=name):
                renderer = ost_pdf.PDFRenderer()
                self.assertTrue(renderer.open(self.pdf_path))
                with _PdfiumEntries() as probe:
                    call(renderer)
                renderer.close()
                self.assertLockedEntries(probe)

    def test_open_and_close_enter_pdfium_under_the_lock(self):
        renderer = ost_pdf.PDFRenderer()
        with _PdfiumEntries() as opened:
            self.assertTrue(renderer.open(self.pdf_path))
        renderer.page_size(0)
        with _PdfiumEntries() as closed:
            renderer.close()
        self.assertLockedEntries(opened)
        self.assertLockedEntries(closed)

    def test_reopening_releases_the_parsed_pages_under_the_lock(self):
        renderer = ost_pdf.PDFRenderer()
        self.assertTrue(renderer.open(self.pdf_path))
        renderer.render_page(0, 0.5, 0)
        with _PdfiumEntries() as reopened:
            self.assertTrue(renderer.open(self.pdf_path))
        renderer.close()
        self.assertLockedEntries(reopened)

    def test_dropping_an_open_renderer_releases_pdfium_under_the_lock(self):
        renderer = ost_pdf.PDFRenderer()
        self.assertTrue(renderer.open(self.pdf_path))
        renderer.render_page(0, 0.5, 0)
        with _PdfiumEntries() as dropped:
            del renderer
            gc.collect()
        self.assertLockedEntries(dropped)

    def test_explicit_shutdown_and_initialize_hold_the_lock(self):
        code = f"""
from ost_visualizer.presentation.visualization.pdf import ost_pdf
renderer = ost_pdf.PDFRenderer()
assert renderer.open({self.pdf_path!r})
renderer.close()
del renderer
start = ost_pdf.pdfium_entry_counts()
ost_pdf.shutdown()
ost_pdf.initialize()
end = ost_pdf.pdfium_entry_counts()
print(end[0] - start[0], end[1] - start[1])
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        entries, unlocked = (int(value) for value in result.stdout.split())
        self.assertEqual((entries, unlocked), (2, 0))


class PythonCallerLockTests(_PdfiumLockCase):
    def test_provider_page_size_read_holds_the_lock(self):
        from ost_visualizer.infrastructure import providers

        service_provider = providers.InfrastructureServiceProvider(
            logger=logging.getLogger("test"),
            callback_bridge_factory=lambda: None,
            database_session_registry=object(),
        )
        with _PdfiumEntries() as probe:
            sizes = service_provider.get_pdf_page_sizes(self.pdf_path)
        self.assertEqual(sizes, [(200.0 / 72.0, 100.0 / 72.0, "")])
        self.assertLockedEntries(probe)

    def test_mcp_metadata_reads_hold_the_lock(self):
        from ost_visualizer.infrastructure.pdf_metadata_provider import (
            NativePdfMetadataProvider,
        )

        provider = NativePdfMetadataProvider(logger=logging.getLogger("test"))
        reads = {
            "page_info": provider.get_page_info,
            "text_runs": provider.get_text_runs,
            "vector_segments": provider.get_vector_segments,
        }
        for name, read in reads.items():
            with self.subTest(read=name):
                with _PdfiumEntries() as probe:
                    self.assertTrue(read(self.pdf_path, 0))
                self.assertLockedEntries(probe)

    def test_page_renderer_calls_hold_the_lock(self):
        from ost_visualizer.presentation.visualization.pdf.renderers.page_renderer import (
            PageRenderer,
        )

        renderer = PageRenderer()
        calls = {
            "render": lambda: renderer.render(self.pdf_path, 0, 0.5, 0),
            "render_frame": lambda: renderer.render_frame(
                self.pdf_path, 0, 0.5, 0.0, 0.0, 50.0, 50.0, 0
            ),
            "page_count": lambda: renderer.get_page_count(self.pdf_path),
            "page_size": lambda: renderer.get_page_size(self.pdf_path, 0),
            "page_info": lambda: renderer.get_page_info(self.pdf_path, 0),
            "text_runs": lambda: renderer.extract_text_runs(self.pdf_path, 0),
            "close": renderer.close,
        }
        for name, call in calls.items():
            with self.subTest(call=name):
                with _PdfiumEntries() as probe:
                    call()
                self.assertLockedEntries(probe)

    def test_worker_page_cache_dropped_without_clear_releases_under_the_lock(self):
        from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache

        cache = PageCache()
        sizes = []
        worker = threading.Thread(
            target=lambda: sizes.append(cache.get_page_size(self.pdf_path, 0))
        )
        with _PdfiumEntries() as probe:
            worker.start()
            worker.join()
            self.assertEqual(sizes, [(200.0, 100.0)])
            sizes.append(cache.get_page_size(self.pdf_path, 0))
            del cache
            gc.collect()
        self.assertLockedEntries(probe)

    def test_snap_vector_extraction_holds_the_lock(self):
        from ost_visualizer.presentation.components.plan_view.components import (
            placement_mode,
        )

        source = placement_mode.PdfSnapSource(
            cache_key=("sheet",),
            layer="base",
            file_path=self.pdf_path,
            page_index=0,
            fallback_width_pts=200.0,
            fallback_height_pts=100.0,
            overlay_rect=(0.0, 0.0, 0.0, 0.0),
            overlay_rotation=0.0,
            point_to_ost=1.0,
        )
        with _PdfiumEntries() as probe:
            segments = placement_mode.extract_pdf_snap_segments(source)
        self.assertTrue(segments)
        self.assertLockedEntries(probe)

    def test_ai_takeoff_path_extraction_holds_the_lock(self):
        from ost_visualizer.presentation.services.ai_takeoff_pdf_source import (
            PageCachePdfSource,
        )
        from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache

        source = PageCachePdfSource(PageCache())
        with _PdfiumEntries() as probe:
            extraction = source.get_path_segments(self.pdf_path, 0)
            source.release()
        self.assertTrue(extraction.segments)
        self.assertLockedEntries(probe)


if __name__ == "__main__":
    unittest.main()
