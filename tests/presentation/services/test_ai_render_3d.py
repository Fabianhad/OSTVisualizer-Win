import base64
import os
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.interfaces.i_mesh_generator import MeshData
from ost_visualizer.presentation.services.ai_render_3d import (
    TOP_VIEW_MAX_SIDE_PX,
    render_top_view,
)
from ost_visualizer.presentation.visualization.utils.image_bands import BAND_PIXELS
from PySide6 import QtGui, QtWidgets
from tests.presentation.visualization.utils.image_op_spy import (
    largest_operation,
    recorded_image_operations,
)


def _slab(x1, y1, x2, y2, z):
    return MeshData(
        vertices=[(x1, y1, z), (x2, y1, z), (x2, y2, z), (x1, y2, z)],
        faces=[(0, 1, 2), (0, 2, 3)],
    )


class TopViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_meshes_are_drawn_from_above_with_extent_and_elevations(self):
        result = render_top_view([_slab(0, 0, 40, 30, 0.0), _slab(10, 10, 20, 20, 8.0)])
        self.assertEqual(result["bbox_model"], [0.0, 0.0, 40.0, 30.0])
        self.assertEqual(result["z_range"], [0.0, 8.0])
        self.assertEqual(result["mesh_count"], 2)
        image = QtGui.QImage.fromData(
            base64.b64decode(result["image"]["png_base64"]), "PNG"
        )
        self.assertEqual(image.width(), TOP_VIEW_MAX_SIDE_PX)
        self.assertEqual(image.height(), round(TOP_VIEW_MAX_SIDE_PX * 30 / 40))
        low = image.pixelColor(int(image.width() * 0.1), int(image.height() * 0.1))
        high = image.pixelColor(int(image.width() * 0.375), int(image.height() * 0.5))
        self.assertNotEqual(low.name(), high.name())
        self.assertEqual(result["px_to_model"][0], 40.0 / TOP_VIEW_MAX_SIDE_PX)

    def test_an_empty_model_returns_no_image(self):
        result = render_top_view([MeshData([], [])])
        self.assertIsNone(result["image"])
        self.assertEqual(result["mesh_count"], 0)

    def test_no_image_operation_exceeds_a_band_and_it_runs_on_a_worker(self):
        results = []

        def run():
            with recorded_image_operations() as operations:
                results.append(
                    (render_top_view([_slab(0, 0, 400, 400, 1.0)]), operations)
                )

        worker = threading.Thread(target=run)
        worker.start()
        worker.join(30)
        result, operations = results[0]
        self.assertIsNotNone(result["image"])
        self.assertLessEqual(largest_operation(operations), BAND_PIXELS)


if __name__ == "__main__":
    unittest.main()
