import random
import tempfile
import unittest
from pathlib import Path
from ost_visualizer.presentation.visualization.pdf import ost_pdf
from tests.presentation.services.ai_takeoff_pdf_support import write_content_pdf


def _write_two_page_pdf(path: Path) -> Path:
    first = "0 0 0 RG 1 w 10 10 m 190 90 l S\n0 0 1 rg 20 20 30 30 re f\n"
    second = "1 0 0 RG 2 w 10 90 m 190 10 l S\n"
    data = bytearray(b"%PDF-1.4\n")
    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Contents 5 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Rotate 90 /Contents 6 0 R >>",
    ]
    for content in (first, second):
        encoded = content.encode("latin-1")
        bodies.append(
            f"<< /Length {len(encoded)} >>\nstream\n".encode("latin-1")
            + encoded
            + b"endstream"
        )
    offsets = []
    for number, body in enumerate(bodies, start=1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(data)
    data += f"xref\n0 {len(bodies) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        data += f"{offset:010d} 00000 n \n".encode()
    data += (
        f"trailer\n<< /Size {len(bodies) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    path.write_bytes(bytes(data))
    return path


def _random_page_content(rng: random.Random) -> str:
    commands = ["0 0 0 RG 0.6 w"]
    for _index in range(rng.randint(50, 400)):
        x = rng.uniform(0.0, 600.0)
        y = rng.uniform(0.0, 400.0)
        commands.append(
            f"{x:.2f} {y:.2f} m {x + rng.uniform(-80, 80):.2f} "
            f"{y + rng.uniform(-80, 80):.2f} l S"
        )
    for _index in range(rng.randint(0, 20)):
        commands.append(
            f"BT /F1 8 Tf {rng.uniform(0, 560):.1f} {rng.uniform(0, 390):.1f} Td "
            f"(T{_index}) Tj ET"
        )
    return "\n".join(commands) + "\n"


def _fresh(path: Path) -> ost_pdf.PDFRenderer:
    renderer = ost_pdf.PDFRenderer()
    if not renderer.open(str(path)):
        raise AssertionError(f"could not open {path}")
    return renderer


def _render_bytes(rendered) -> bytes:
    return bytes(rendered.to_bytes())


class PdfPageReuseTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.directory = Path(temp_dir.name)

    def test_repeated_page_work_loads_the_page_once(self):
        path = _write_two_page_pdf(self.directory / "two.pdf")
        renderer = _fresh(path)
        self.addCleanup(renderer.close)
        self.assertEqual(renderer.page_loads(), 0)
        renderer.page_size(0)
        renderer.page_info(0)
        renderer.render_page(0, 1.0, 0)
        for _frame in range(3):
            renderer.render_page_frame(0, 2.0, 10.0, 10.0, 50.0, 40.0, 0)
        renderer.extract_path_segments(0)
        renderer.extract_path_items(0, 1000)
        renderer.extract_text_runs(0)
        self.assertEqual(renderer.page_loads(), 1)

    def test_alternating_pages_stay_loaded_within_capacity(self):
        path = _write_two_page_pdf(self.directory / "two.pdf")
        renderer = _fresh(path)
        self.addCleanup(renderer.close)
        for _round in range(4):
            renderer.render_page_frame(0, 1.0, 0.0, 0.0, 100.0, 100.0, 0)
            renderer.render_page_frame(1, 1.0, 0.0, 0.0, 100.0, 100.0, 0)
        self.assertEqual(renderer.page_loads(), 2)

    def test_reopen_discards_pages_of_the_previous_document(self):
        first = _write_two_page_pdf(self.directory / "first.pdf")
        second = write_content_pdf(
            self.directory / "second.pdf",
            "0 0 0 RG 5 w 0 0 m 300 300 l S\n",
            width=300.0,
            height=300.0,
        )
        renderer = _fresh(first)
        self.addCleanup(renderer.close)
        renderer.page_info(0)
        self.assertTrue(renderer.open(str(second)))
        info = renderer.page_info(0)
        self.assertEqual(
            (info.effective_width_pts, info.effective_height_pts), (300.0, 300.0)
        )
        self.assertEqual(renderer.page_loads(), 2)
        renderer.close()
        self.assertEqual(renderer.page_loads(), 2)
        self.assertIsNone(renderer.page_info(0))

    def test_cancelled_render_leaves_the_reused_page_renderable(self):
        path = _write_two_page_pdf(self.directory / "two.pdf")
        renderer = _fresh(path)
        self.addCleanup(renderer.close)
        token = ost_pdf.RenderCancelToken()
        token.cancel()
        self.assertIsNone(
            renderer.render_page_frame_cancellable(
                0, 2.0, 0.0, 0.0, 100.0, 100.0, 0, token
            )
        )
        reused = renderer.render_page_frame(0, 2.0, 0.0, 0.0, 100.0, 100.0, 0)
        fresh = _fresh(path)
        self.addCleanup(fresh.close)
        expected = fresh.render_page_frame(0, 2.0, 0.0, 0.0, 100.0, 100.0, 0)
        self.assertEqual(_render_bytes(reused), _render_bytes(expected))

    def test_reused_pages_match_fresh_renderers_on_random_pages(self):
        rng = random.Random(20261009)
        for seed in range(6):
            path = write_content_pdf(
                self.directory / f"random_{seed}.pdf",
                _random_page_content(rng),
                width=600.0,
                height=400.0,
            )
            reused = _fresh(path)
            self.addCleanup(reused.close)
            for _query in range(4):
                scale = rng.choice((0.5, 1.0, 2.5, 4.0))
                frame = (
                    rng.uniform(0.0, 300.0),
                    rng.uniform(0.0, 200.0),
                    rng.uniform(20.0, 300.0),
                    rng.uniform(20.0, 200.0),
                )
                rotation = rng.choice((0, 90, 180, 270))
                fresh = _fresh(path)
                with self.subTest(seed=seed, scale=scale, frame=frame):
                    self.assertEqual(
                        _render_bytes(
                            reused.render_page_frame(0, scale, *frame, rotation)
                        ),
                        _render_bytes(
                            fresh.render_page_frame(0, scale, *frame, rotation)
                        ),
                    )
                    self.assertEqual(
                        list(reused.extract_path_segments(0)),
                        list(fresh.extract_path_segments(0)),
                    )
                    self.assertEqual(
                        [
                            (run.text, run.left, run.top)
                            for run in reused.extract_text_runs(0)
                        ],
                        [
                            (run.text, run.left, run.top)
                            for run in fresh.extract_text_runs(0)
                        ],
                    )
                fresh.close()
            self.assertEqual(reused.page_loads(), 1)


if __name__ == "__main__":
    unittest.main()
