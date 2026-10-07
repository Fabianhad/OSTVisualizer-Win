import os
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.services.ai_planar_regions import point_in_ring, ring_area
from ost_visualizer.presentation.services.ai_region_raster import (
    RASTER_MAX_SIDE_PX,
    raster_fill_region,
)
from ost_visualizer.presentation.visualization.utils.image_bands import BAND_PIXELS
from PySide6 import QtWidgets
from tests.presentation.visualization.utils.image_op_spy import (
    largest_operation,
    recorded_image_operations,
)


def _rect(x1, y1, x2, y2):
    return [(x1, y1, x2, y1), (x2, y1, x2, y2), (x2, y2, x1, y2), (x1, y2, x1, y1)]


class RasterFillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_a_closed_outline_is_filled_from_the_seed_to_its_lines(self):
        region = raster_fill_region(
            _rect(100, 100, 460, 370), (50, 50, 510, 420), (200, 200), 1.0
        )
        self.assertFalse(region.leak)
        self.assertAlmostEqual(
            abs(ring_area(region.ring)), 360 * 270, delta=360 * 270 * 0.01
        )
        self.assertTrue(point_in_ring((200, 200), region.ring))
        xs = [x for x, _y in region.ring]
        self.assertAlmostEqual(min(xs), 100, delta=1.0)
        self.assertAlmostEqual(max(xs), 460, delta=1.0)

    def test_gaps_up_to_the_pen_width_are_closed_and_wider_gaps_leak(self):
        outline = [
            (0, 0, 400, 0),
            (400, 0, 400, 300),
            (400, 300, 0, 300),
            (0, 300, 0, 6),
        ]
        closed = raster_fill_region(outline, (-50, -50, 450, 350), (200, 150), 8.0)
        self.assertFalse(closed.leak)
        self.assertAlmostEqual(
            abs(ring_area(closed.ring)), 400 * 300, delta=400 * 300 * 0.02
        )
        leaking = raster_fill_region(outline, (-50, -50, 450, 350), (200, 150), 2.0)
        self.assertTrue(leaking.leak)

    def test_a_seed_on_a_line_or_outside_the_box_finds_nothing(self):
        self.assertIsNone(
            raster_fill_region(
                _rect(0, 0, 100, 100), (-10, -10, 110, 110), (0, 50), 2.0
            )
        )
        self.assertIsNone(
            raster_fill_region(
                _rect(0, 0, 100, 100), (-10, -10, 110, 110), (500, 50), 2.0
            )
        )

    def test_large_boxes_are_capped_and_no_image_operation_exceeds_a_band(self):
        with recorded_image_operations() as operations:
            region = raster_fill_region(
                _rect(0, 0, 5000, 4000), (-100, -100, 5100, 4100), (2500, 2000), 4.0
            )
        self.assertIsNotNone(region)
        self.assertLessEqual(region.width_px, RASTER_MAX_SIDE_PX)
        self.assertLessEqual(largest_operation(operations), BAND_PIXELS)

    def test_runs_on_a_worker_thread(self):
        results = []
        worker = threading.Thread(
            target=lambda: results.append(
                raster_fill_region(
                    _rect(0, 0, 100, 100), (-10, -10, 110, 110), (50, 50), 1.0
                )
            )
        )
        worker.start()
        worker.join(30)
        self.assertFalse(results[0].leak)


if __name__ == "__main__":
    unittest.main()
