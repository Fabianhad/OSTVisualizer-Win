import base64
import os
import tempfile
import threading
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.ai_takeoff_dtos import CropPlan
from ost_visualizer.application.services.ai_takeoff_read_service import (
    AiTakeoffReadService,
)
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.services.ai_takeoff_crop_renderer import (
    encode_png,
    render_crop_png,
)
from ost_visualizer.presentation.services.ai_takeoff_pdf_source import (
    PageCachePdfSource,
)
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from ost_visualizer.presentation.visualization.utils.image_bands import BAND_PIXELS
from PySide6 import QtGui, QtWidgets
from tests.presentation.services.ai_takeoff_pdf_support import write_takeoff_pdf
from tests.presentation.visualization.utils.image_op_spy import (
    largest_operation,
    recorded_image_operations,
)

RED = (1, 0, 0)
GREEN = (0, 1, 0)


def _plan(path, frame, scale, k=None):
    left, top, width, height = frame
    return CropPlan(
        page_uid="p1",
        file_path=str(path),
        page_index=0,
        frame_pts=frame,
        scale=scale,
        width_px=round(width * scale),
        height_px=round(height * scale),
        px_to_page_pts=(1.0 / scale, 0.0, 0.0, 1.0 / scale, left, top),
        page_pts_to_ost=None if k is None else (k, 0.0, 0.0, k, 0.0, 0.0),
    )


def _decode(result):
    data = base64.b64decode(result["image"]["png_base64"])
    image = QtGui.QImage.fromData(data, "PNG")
    assert not image.isNull()
    return image


def _rgb(image, x, y):
    color = image.pixelColor(x, y)
    return color.red(), color.green(), color.blue()


class CropRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.pdf = write_takeoff_pdf(
            Path(directory.name) / "corners.pdf",
            width=200,
            height=100,
            rectangles=[(*RED, 0, 80, 20, 20), (*GREEN, 180, 80, 20, 20)],
        )
        self.cache = PageCache()
        self.addCleanup(self.cache.clear)
        self.source = PageCachePdfSource(self.cache)

    def test_png_has_the_planned_size_and_the_page_content(self):
        result = render_crop_png(
            self.source, _plan(self.pdf, (0.0, 0.0, 200.0, 100.0), 2.0)
        )
        image = _decode(result)
        self.assertEqual((image.width(), image.height()), (400, 200))
        self.assertEqual(result["image"]["width_px"], 400)
        self.assertEqual(result["image"]["height_px"], 200)
        self.assertEqual(_rgb(image, 10, 10), (255, 0, 0))
        self.assertEqual(_rgb(image, 390, 10), (0, 255, 0))
        self.assertEqual(_rgb(image, 200, 100), (255, 255, 255))

    def test_affine_locates_page_features_within_half_a_pixel(self):
        plan = _plan(self.pdf, (150.0, 0.0, 50.0, 50.0), 1.0, k=2.0)
        result = render_crop_png(self.source, plan)
        image = _decode(result)
        a, _b, _c, _d, e, _f = result["px_to_page_pts"]
        green_edge_px = (180.0 - e) / a
        self.assertAlmostEqual(green_edge_px, 30.0, delta=0.5)
        self.assertEqual(_rgb(image, 31, 1), (0, 255, 0))
        self.assertNotEqual(_rgb(image, 28, 1), (0, 255, 0))
        self.assertEqual(result["page_pts_to_ost"], [2.0, 0.0, 0.0, 2.0, 0.0, 0.0])
        self.assertEqual(result["frame_pts"], [150.0, 0.0, 50.0, 50.0])

    def test_large_crops_never_run_one_image_operation_over_a_band(self):
        plan = _plan(self.pdf, (0.0, 0.0, 200.0, 100.0), 8.0)
        self.assertGreater(plan.width_px * plan.height_px, 2 * BAND_PIXELS)
        with recorded_image_operations() as operations:
            image = _decode(render_crop_png(self.source, plan))
        self.assertEqual((image.width(), image.height()), (1600, 800))
        self.assertTrue(operations)
        self.assertLessEqual(largest_operation(operations), BAND_PIXELS)

    def test_rendering_works_on_a_worker_thread(self):
        results = []
        thread = threading.Thread(
            target=lambda: results.append(
                render_crop_png(self.source, _plan(self.pdf, (0, 0, 200, 100), 1.0))
            )
        )
        thread.start()
        thread.join(30)
        self.assertEqual(len(results), 1)
        self.assertEqual(_decode(results[0]).size().toTuple(), (200, 100))

    def test_missing_pdf_reports_unavailable(self):
        plan = _plan(Path(self.pdf).with_name("missing.pdf"), (0, 0, 200, 100), 1.0)
        result = render_crop_png(self.source, plan)
        self.assertIsNone(result["image"])
        self.assertEqual(result["render_status"], "unavailable")


class EncodePngTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_round_trip_keeps_pixels_and_alpha(self):
        image = QtGui.QImage(37, 5, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor(10, 20, 30, 255))
        image.setPixelColor(36, 4, QtGui.QColor(200, 100, 50, 128))
        decoded = QtGui.QImage.fromData(encode_png(image), "PNG")
        self.assertEqual((decoded.width(), decoded.height()), (37, 5))
        self.assertEqual(decoded.pixelColor(0, 0).getRgb(), (10, 20, 30, 255))
        self.assertEqual(decoded.pixelColor(36, 4).getRgb(), (200, 100, 50, 128))

    def test_null_image_is_rejected(self):
        with self.assertRaises(ValueError):
            encode_png(QtGui.QImage())


class _OnePageProject:
    def __init__(self, page):
        self.page = page

    def get_current_bid_ref(self):
        return BidRef("C:/jobs/a.mdb", "b1")

    def get_current_bid(self):
        return Bid(uid="b1", name="Bid")

    def get_all_pages(self):
        return [self.page]

    def get_page(self, page_uid):
        return self.page if page_uid == self.page.uid else None


class ReportedGeometryMatchesTheRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.cache = PageCache()
        self.addCleanup(self.cache.clear)
        self.source = PageCachePdfSource(self.cache)

    def test_reported_segments_land_on_drawn_pixels_for_offset_and_rotated_boxes(self):
        cases = {
            "crop box offset": (
                "/MediaBox [0 0 612 792] /CropBox [100 100 512 692]",
                412,
                592,
            ),
            "media box origin": ("/MediaBox [50 50 662 842]", 612, 792),
            "rotated crop box": (
                "/MediaBox [0 0 612 792] /CropBox [100 100 512 692] /Rotate 90",
                592,
                412,
            ),
        }
        for label, (boxes, width, height) in cases.items():
            with self.subTest(label=label):
                pdf = write_takeoff_pdf(
                    self.directory / f"{label}.pdf",
                    lines=[(200, 300, 400, 300)],
                    page_boxes=boxes,
                )
                page = Page(
                    uid="p1",
                    name="Plan",
                    sequence=1,
                    image_path=str(pdf),
                    page_index=0,
                    width_pts=float(width),
                    height_pts=float(height),
                    scale_factor1=0.25,
                    scale_factor2=12.0,
                )
                service = AiTakeoffReadService(
                    _OnePageProject(page), self.source, None, lambda _path: None
                )
                snapshot = service.page_snapshot("p1")
                segment = service.list_segments(snapshot)["data"]["segments"][0]
                plan = service.plan_crop(snapshot, dpi=72)
                image = _decode(render_crop_png(self.source, plan))
                a, _b, _c, d, e, f = plan.px_to_page_pts
                x = (segment["p1_pts"][0] + segment["p2_pts"][0]) / 2.0
                y = (segment["p1_pts"][1] + segment["p2_pts"][1]) / 2.0
                px, py = int((x - e) / a), int((y - f) / d)
                self.assertTrue(0 <= px < image.width() and 0 <= py < image.height())
                darkest = min(
                    image.pixelColor(px + dx, py + dy).lightness()
                    for dx in (-1, 0, 1)
                    for dy in (-1, 0, 1)
                    if 0 <= px + dx < image.width() and 0 <= py + dy < image.height()
                )
                self.assertLess(darkest, 128)


if __name__ == "__main__":
    unittest.main()
