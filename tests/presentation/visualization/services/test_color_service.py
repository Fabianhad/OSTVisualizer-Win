from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)
from ost_visualizer.domain.entities.condition import Condition
import unittest
import os
from pathlib import Path
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.utils.annotation_defaults import (
    apply_config_owned_annotation_defaults,
    build_placed_annotation_spec,
    set_annotation_styles_by_tool,
)
from PySide6 import QtCore, QtGui, QtWidgets


class ColorServiceTests(unittest.TestCase):
    def test_numeric_rgb_sequence_is_not_treated_as_color_opacity_pair(self):
        self.assertEqual(
            ColorService().convert_to_rgba((255, 128, 0)),
            (1.0, 128 / 255.0, 0.0, 1.0),
        )

    def test_numeric_rgba_sequence_converts_to_hex_with_opacity(self):
        self.assertEqual(
            ColorService().as_hex_with_opacity((255, 128, 0, 0.25)),
            ("#ff8000", 0.25),
        )

    def test_condition_color_preserves_black_fill(self):
        condition = Condition(uid="condition-1", color_fill=0)
        self.assertEqual(ColorService().get_condition_color(condition), [0, 0, 0])


class ColorServiceOpacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        set_annotation_styles_by_tool({}, Config())
        self.app.processEvents()

    def test_inactive_color_substitution_preserves_opacity(self):
        service = ColorService()
        takeoff = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", area_uid="area-b"
        )
        condition = Condition(uid="c1")
        color_map = {"c1": {"color": "#abcdef", "opacity": 0.37}}
        result_2d = service.get_2d_color_for_takeoff(
            takeoff,
            condition,
            color_map,
            {"p1": "area-a"},
            inactive_object_color="#123456",
        )
        result_3d = service.get_color_for_takeoff(
            takeoff,
            condition,
            color_map,
            Config.DISPLAY_MODE_SOLID,
            {"p1": "area-a"},
            inactive_object_color="#123456",
        )
        self.assertEqual((result_2d.hex, result_2d.opacity), ("#123456", 0.37))
        self.assertEqual((result_3d.hex, result_3d.opacity), ("#123456", 0.37))
