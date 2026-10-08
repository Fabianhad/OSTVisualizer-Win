import base64
import os
import threading
import unittest
from unittest.mock import create_autospec

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.interfaces.i_mesh_generator import MeshData
from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.file_manager_service import FileManager
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.domain.services.takeoff_service_impl import TakeoffDomainService
from ost_visualizer.infrastructure.visualization_provider import VisualizationProvider
from ost_visualizer.presentation.services.ai_render_3d import (
    TOP_VIEW_MAX_SIDE_PX,
    AiTopViewSource,
    render_top_view,
)
from ost_visualizer.presentation.visualization.utils.image_bands import BAND_PIXELS
from PySide6 import QtGui, QtWidgets
from tests.presentation.visualization.utils.image_op_spy import (
    largest_operation,
    recorded_image_operations,
)

LOW = (70, 110, 200)
HIGH = (240, 120, 40)
NO_IMAGE = {"image": None, "mesh_count": 0, "bbox_model": None, "z_range": None}


def _slab(x1, y1, x2, y2, z):
    return MeshData(
        vertices=[(x1, y1, z), (x2, y1, z), (x2, y2, z), (x1, y2, z)],
        faces=[(0, 1, 2), (0, 2, 3)],
    )


def _decode(result):
    image = QtGui.QImage.fromData(
        base64.b64decode(result["image"]["png_base64"]), "PNG"
    )
    assert not image.isNull()
    return image


def _rgb(image, x, y):
    color = image.pixelColor(x, y)
    return color.red(), color.green(), color.blue()


def _size(result):
    return result["image"]["width_px"], result["image"]["height_px"]


class TopViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_meshes_are_drawn_from_above_with_extent_and_elevations(self):
        result = render_top_view([_slab(0, 0, 40, 30, 0.0), _slab(10, 10, 20, 20, 8.0)])
        self.assertEqual(result["bbox_model"], [0.0, 0.0, 40.0, 30.0])
        self.assertEqual(result["z_range"], [0.0, 8.0])
        self.assertEqual(result["mesh_count"], 2)
        image = _decode(result)
        self.assertEqual(image.width(), TOP_VIEW_MAX_SIDE_PX)
        self.assertEqual(image.height(), round(TOP_VIEW_MAX_SIDE_PX * 30 / 40))
        low = image.pixelColor(int(image.width() * 0.1), int(image.height() * 0.1))
        high = image.pixelColor(int(image.width() * 0.375), int(image.height() * 0.5))
        self.assertNotEqual(low.name(), high.name())
        self.assertEqual(result["px_to_model"][0], 40.0 / TOP_VIEW_MAX_SIDE_PX)

    def test_the_longest_side_is_1200_pixels_and_the_affine_maps_back_to_model(self):
        result = render_top_view([_slab(100, 50, 160, 80, 2.0)])
        self.assertEqual(result["bbox_model"], [100.0, 50.0, 160.0, 80.0])
        self.assertEqual(_size(result), (1200, 600))
        self.assertEqual(result["px_to_model"], [0.05, 0.0, 0.0, -0.05, 100.0, 80.0])
        image = _decode(result)
        self.assertEqual((image.width(), image.height()), (1200, 600))

    def test_heights_are_coloured_from_low_blue_to_high_orange_without_outlines(self):
        result = render_top_view(
            [
                _slab(100, 50, 160, 80, 2.0),
                _slab(110, 60, 120, 70, 10.0),
                _slab(140, 60, 150, 70, 6.0),
            ]
        )
        self.assertEqual(result["z_range"], [2.0, 10.0])
        image = _decode(result)
        self.assertEqual(_rgb(image, 0, 0), LOW)
        self.assertEqual(_rgb(image, 1199, 599), LOW)
        self.assertEqual(_rgb(image, 600, 300), LOW)
        self.assertEqual(_rgb(image, 300, 300), HIGH)
        self.assertEqual(_rgb(image, 900, 300), (155, 115, 120))
        self.assertEqual(_rgb(image, 300, 240), HIGH)

    def test_higher_triangles_are_painted_over_lower_ones_whatever_the_input_order(
        self,
    ):
        low = MeshData(
            vertices=[(40, 30, 0.0), (0, 30, 0.0), (0, 0, 0.0), (40, 0, 0.0)],
            faces=[(0, 1, 2), (0, 2, 3)],
        )
        image = _decode(render_top_view([_slab(10, 10, 20, 20, 8.0), low]))
        self.assertEqual(_rgb(image, 450, 450), HIGH)
        self.assertEqual(_rgb(image, 100, 100), LOW)

    def test_a_flat_model_uses_the_low_colour(self):
        result = render_top_view([_slab(0, 0, 10, 10, 5.0)])
        self.assertEqual(result["z_range"], [5.0, 5.0])
        self.assertEqual(_rgb(_decode(result), 600, 600), LOW)

    def test_empty_meshes_are_not_counted(self):
        result = render_top_view([MeshData([], []), _slab(0, 0, 10, 10, 1.0), None])
        self.assertEqual(result["mesh_count"], 1)

    def test_a_single_point_model_gives_a_one_pixel_image(self):
        point = MeshData(vertices=[(3.0, 4.0, 1.0)] * 3, faces=[(0, 1, 2)])
        result = render_top_view([point])
        self.assertEqual(result["bbox_model"], [3.0, 4.0, 3.0, 4.0])
        self.assertEqual(_size(result), (1, 1))
        self.assertAlmostEqual(result["px_to_model"][0], 1e-9 / 1200, delta=1e-20)
        self.assertEqual(_decode(result).width(), 1)

    def test_a_zero_width_model_keeps_one_pixel_of_width(self):
        sliver = MeshData(
            vertices=[(5.0, 0.0, 0.0), (5.0, 10.0, 0.0), (5.0, 5.0, 3.0)],
            faces=[(0, 1, 2)],
        )
        result = render_top_view([sliver])
        self.assertEqual(_size(result), (1, 1200))
        image = _decode(result)
        self.assertEqual((image.width(), image.height()), (1, 1200))
        self.assertEqual(
            result["px_to_model"], [10.0 / 1200, 0.0, 0.0, -10.0 / 1200, 5.0, 10.0]
        )

    def test_an_empty_model_returns_no_image(self):
        self.assertEqual(render_top_view([MeshData([], [])]), NO_IMAGE)

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
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(results), 1)
        result, operations = results[0]
        self.assertIsNotNone(result["image"])
        self.assertLessEqual(largest_operation(operations), BAND_PIXELS)


class AiTopViewSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.model = OstAggregate(create_autospec(FileManager, instance=True))
        self.model.bid_conditions = {
            "c1": Condition(uid="c1", condition_type=Condition.TYPE_AREA, thickness=1.0)
        }
        self.model.page_area_selections = {"p1": "area-1"}
        self.data = ProjectDataService(self.model)
        self.source = AiTopViewSource(
            self.data,
            VisualizationProvider(TakeoffDomainService()).get_mesh_generator(),
            lambda: "#808080",
        )

    @staticmethod
    def _takeoff(uid, page_uid):
        return Takeoff(
            uid=uid,
            condition_uid="c1",
            page_uid=page_uid,
            position=[1.0, 1.0, 3.0, 1.0, 3.0, 2.0, 1.0, 2.0],
        )

    def test_snapshot_copies_takeoffs_conditions_and_page_transforms(self):
        scaled = Page(
            uid="p1",
            name="P1",
            width_pts=720.0,
            height_pts=360.0,
            scale_factor1=0.25,
            scale_factor2=12.0,
            rotation=90,
            flip_x=True,
            flip_y=True,
        )
        bare = Page(
            uid="p2",
            name="P2",
            scale_factor1=0.0,
            scale_factor2=0.0,
            rotation=None,
        )
        self.model.set_pages({"p1": scaled, "p2": bare})
        self.data.add_takeoffs([self._takeoff("t1", "p1"), self._takeoff("t2", "p2")])
        scaled.takeoffs.append(self._takeoff("t3", "deleted-page"))
        takeoffs, conditions, page_areas, page_infos, inactive = self.source.snapshot()
        self.assertEqual(sorted(t.uid for t in takeoffs), ["t1", "t2", "t3"])
        self.assertEqual(conditions, self.model.bid_conditions)
        self.assertIsNot(conditions, self.model.bid_conditions)
        self.assertEqual(page_areas, {"p1": "area-1"})
        self.assertIsNot(page_areas, self.model.page_area_selections)
        self.assertEqual(inactive, "#808080")
        self.assertEqual(
            page_infos,
            {
                "p1": {
                    "scale_factor1": 0.25,
                    "scale_factor2": 12.0,
                    "rotation": 90,
                    "flip_x": True,
                    "flip_y": True,
                    "width": 720.0,
                    "height": 360.0,
                    "view_scale": 1.0,
                },
                "p2": {
                    "scale_factor1": 1.0,
                    "scale_factor2": 1.0,
                    "rotation": 0,
                    "flip_x": False,
                    "flip_y": False,
                    "width": 0.0,
                    "height": 0.0,
                    "view_scale": 1.0,
                },
            },
        )

    def test_render_meshes_the_snapshot_with_the_real_generator(self):
        self.model.set_pages(
            {"p1": Page(uid="p1", name="P1", width_pts=720.0, height_pts=360.0)}
        )
        self.data.add_takeoffs([self._takeoff("t1", "p1")])
        result = self.source.render(self.source.snapshot())
        self.assertEqual(result["mesh_count"], 1)
        self.assertEqual(result["bbox_model"], [-3.0, 1.0, -1.0, 2.0])
        self.assertEqual(result["z_range"], [0.0, 1.0])
        self.assertEqual(_size(result), (1200, 600))

    def test_render_without_takeoffs_returns_no_image(self):
        self.assertEqual(self.source.render(self.source.snapshot()), NO_IMAGE)


if __name__ == "__main__":
    unittest.main()
