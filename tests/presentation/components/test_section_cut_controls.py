import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.components.mesh_view import (
    SECTION_CUT_EAST_WEST,
    SECTION_CUT_NORTH_SOUTH,
    OpenGLViewer,
    ost_renderer,
)
from ost_visualizer.presentation.components.section_cut_controls import (
    SECTION_CUT_SLIDER_STEPS,
    SectionCutControls,
    format_section_cut_value,
)
from ost_visualizer.presentation.config import (
    SECTION_CUT_EAST_WEST_LABEL,
    SECTION_CUT_NORTH_SOUTH_LABEL,
)
from PySide6 import QtWidgets
from tests.presentation.components.mesh_support import FakeMeshRenderer, FakeMeshScene


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _viewer_with_scene():
    viewer = OpenGLViewer(None, SimpleNamespace())
    scene = FakeMeshScene(["takeoff"])
    # Native Z-up bounds: x -120..0 (east-west), y 78..2418 (north-south).
    scene.bounds.min = ost_renderer.Vec3(-120.0, 78.0, 0.0)
    scene.bounds.max = ost_renderer.Vec3(0.0, 2418.0, 332.0)
    renderer = FakeMeshRenderer(scene)
    viewer._renderer = renderer
    return viewer, renderer


class OpenGLViewerSectionCutTests(unittest.TestCase):
    def setUp(self):
        _app()
        self.viewer, self.renderer = _viewer_with_scene()

    def tearDown(self):
        self.viewer._renderer = None
        self.viewer.cleanup()

    def test_cuts_start_off_and_map_to_native_axes(self):
        self.assertEqual(self.viewer.section_cut_fraction(SECTION_CUT_NORTH_SOUTH), 1.0)
        self.assertIsNone(self.viewer.section_cut_offset_feet(SECTION_CUT_NORTH_SOUTH))
        self.viewer.set_section_cut(SECTION_CUT_NORTH_SOUTH, 0.25)
        # North-south moves along native y (axis 1); east-west stays off.
        self.assertEqual(
            self.renderer.section_cut_calls[-2:],
            [(1, True, 78.0 + 0.25 * 2340.0), (0, False, 0.0)],
        )
        self.assertAlmostEqual(
            self.viewer.section_cut_offset_feet(SECTION_CUT_NORTH_SOUTH), 48.75
        )
        self.viewer.set_section_cut(SECTION_CUT_EAST_WEST, 0.5)
        self.assertIn((0, True, -60.0), self.renderer.section_cut_calls[-2:])
        self.assertAlmostEqual(
            self.viewer.section_cut_offset_feet(SECTION_CUT_EAST_WEST), 5.0
        )

    def test_the_right_end_turns_a_cut_off_and_values_are_clamped(self):
        self.viewer.set_section_cut(SECTION_CUT_EAST_WEST, -3)
        self.assertEqual(self.viewer.section_cut_fraction(SECTION_CUT_EAST_WEST), 0.0)
        self.assertIn((0, True, -120.0), self.renderer.section_cut_calls[-2:])
        self.viewer.set_section_cut(SECTION_CUT_EAST_WEST, 7)
        self.assertEqual(self.viewer.section_cut_fraction(SECTION_CUT_EAST_WEST), 1.0)
        self.assertIn((0, False, 0.0), self.renderer.section_cut_calls[-2:])
        self.assertIsNone(self.viewer.section_cut_offset_feet(SECTION_CUT_EAST_WEST))
        with self.assertRaises(ValueError):
            self.viewer.set_section_cut("vertical", 0.5)

    def test_a_new_scene_reapplies_the_cut_to_its_own_extent(self):
        self.viewer.set_section_cut(SECTION_CUT_NORTH_SOUTH, 0.5)
        self.renderer.scene.bounds.min = ost_renderer.Vec3(0.0, 0.0, 0.0)
        self.renderer.scene.bounds.max = ost_renderer.Vec3(10.0, 100.0, 5.0)
        self.renderer.section_cut_calls.clear()
        self.viewer.scene_content_changed.emit()
        self.assertIn((1, True, 50.0), self.renderer.section_cut_calls)

    def test_an_empty_scene_keeps_the_cut_off_in_the_renderer(self):
        self.viewer.set_section_cut(SECTION_CUT_NORTH_SOUTH, 0.5)
        self.renderer.scene.bounds = ost_renderer.Box3()
        self.renderer.section_cut_calls.clear()
        self.viewer.scene_content_changed.emit()
        self.assertIn((1, False, 0.0), self.renderer.section_cut_calls)
        self.assertIsNone(self.viewer.section_cut_offset_feet(SECTION_CUT_NORTH_SOUTH))

    def test_bounds_are_not_read_while_both_cuts_are_off(self):
        calls = self.renderer.scene.get_bounds_calls
        self.viewer.scene_content_changed.emit()
        self.assertEqual(self.renderer.scene.get_bounds_calls, calls)
        self.assertEqual(
            self.renderer.section_cut_calls[-2:], [(1, False, 0.0), (0, False, 0.0)]
        )


class SectionCutControlsTests(unittest.TestCase):
    def setUp(self):
        _app()
        self.viewer, self.renderer = _viewer_with_scene()
        self.controls = SectionCutControls(self.viewer)

    def tearDown(self):
        self.controls.deleteLater()
        self.viewer._renderer = None
        self.viewer.cleanup()

    def test_sliders_start_at_the_off_end_with_labels(self):
        labels = [
            label.text()
            for label in self.controls.findChildren(QtWidgets.QLabel)
            if label.buddy() is not None
        ]
        self.assertEqual(
            labels, [SECTION_CUT_NORTH_SOUTH_LABEL, SECTION_CUT_EAST_WEST_LABEL]
        )
        for cut in (SECTION_CUT_NORTH_SOUTH, SECTION_CUT_EAST_WEST):
            slider = self.controls.slider(cut)
            self.assertEqual(
                (slider.minimum(), slider.maximum()), (0, SECTION_CUT_SLIDER_STEPS)
            )
            self.assertEqual(slider.value(), SECTION_CUT_SLIDER_STEPS)
            self.assertEqual(self.controls.value_text(cut), "off")

    def test_moving_a_slider_cuts_the_view_and_shows_feet(self):
        self.controls.slider(SECTION_CUT_NORTH_SOUTH).setValue(250)
        self.assertEqual(
            self.viewer.section_cut_fraction(SECTION_CUT_NORTH_SOUTH), 0.25
        )
        self.assertEqual(self.controls.value_text(SECTION_CUT_NORTH_SOUTH), "48.8'")
        self.controls.slider(SECTION_CUT_NORTH_SOUTH).setValue(SECTION_CUT_SLIDER_STEPS)
        self.assertEqual(self.controls.value_text(SECTION_CUT_NORTH_SOUTH), "off")

    def test_a_scene_change_refreshes_the_feet_label(self):
        self.controls.slider(SECTION_CUT_EAST_WEST).setValue(500)
        self.assertEqual(self.controls.value_text(SECTION_CUT_EAST_WEST), "5.0'")
        self.renderer.scene.bounds.max = ost_renderer.Vec3(1200.0, 2418.0, 332.0)
        self.viewer.scene_content_changed.emit()
        self.assertEqual(self.controls.value_text(SECTION_CUT_EAST_WEST), "55.0'")

    def test_value_format(self):
        self.assertEqual(format_section_cut_value(None), "off")
        self.assertEqual(format_section_cut_value(1234.56), "1,234.6'")


if __name__ == "__main__":
    unittest.main()
