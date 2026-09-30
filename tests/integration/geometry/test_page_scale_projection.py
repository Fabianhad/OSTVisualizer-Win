import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.domain.services.page_scale_transform import (
    rescale_position_between_page_scales,
)
from PySide6 import QtWidgets


class PageScaleSurfaceSyncRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_authoritative_rescale_preserves_display_geometry_without_hybrid_jump(
        self,
    ) -> None:
        source_scale = (0.125, 12.0)
        target_scale = (0.25, 12.0)
        source_position = [960.0, 480.0, 1920.0, 960.0]
        target_position = rescale_position_between_page_scales(
            source_position, source_scale, target_scale
        )
        source_coordinates = OSTCoordinateSystem(
            {"scale_factor1": source_scale[0], "scale_factor2": source_scale[1]}
        )
        target_coordinates = OSTCoordinateSystem(
            {"scale_factor1": target_scale[0], "scale_factor2": target_scale[1]}
        )
        source_display = source_coordinates.transform_vertices_to_2d(source_position)
        target_display = target_coordinates.transform_vertices_to_2d(target_position)
        stale_hybrid_display = target_coordinates.transform_vertices_to_2d(
            source_position
        )
        self.assertEqual(target_position, [480.0, 240.0, 960.0, 480.0])
        self.assertEqual(target_display, source_display)
        self.assertNotEqual(stale_hybrid_display, source_display)
