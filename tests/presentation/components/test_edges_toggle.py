import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.mesh_geometry_dto import MeshSceneIdentity
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.components.edges_toggle import EdgesToggle
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer
from ost_visualizer.presentation.components.section_cut_controls import (
    SectionCutControls,
)
from ost_visualizer.presentation.components.tower_crane_toggle import TowerCraneToggle
from ost_visualizer.presentation.config import (
    EDGES_TOGGLE_LABEL,
    EDGES_TOGGLE_TOOLTIP,
    OPTIONS_LABEL_EDGES,
    OPTIONS_TOOLTIP_EDGES,
)
from PySide6 import QtWidgets
from tests.presentation.components.mesh_support import FakeMeshRenderer, FakeMeshScene

BID = BidRef("a.mdb", "bid-1")
TRIANGLE = [0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 10.0, 0.0]
NORMALS = [0.0, 0.0, 1.0] * 3


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _Colors:
    @staticmethod
    def convert_to_rgba(_color):
        return (1.0, 0.0, 0.0, 1.0)


class _ViewerCase(unittest.TestCase):
    def setUp(self):
        _app()
        self.viewer = OpenGLViewer(None, _Colors())
        self.renderer = FakeMeshRenderer(FakeMeshScene([]))
        self.viewer._renderer = self.renderer
        self.requests = {"edges": [], "crane": []}
        self.viewer.edges_visibility_requested.connect(self.requests["edges"].append)
        self.viewer.tower_crane_visibility_requested.connect(
            self.requests["crane"].append
        )

    def tearDown(self):
        self.viewer._renderer = None
        self.viewer.cleanup()

    def widget(self, widget):
        self.addCleanup(widget.deleteLater)
        return widget


class EdgesToggleTests(_ViewerCase):
    def test_the_toggle_matches_the_options_label_and_tooltip(self):
        toggle = self.widget(EdgesToggle(self.viewer))
        self.assertEqual(toggle.text(), EDGES_TOGGLE_LABEL)
        self.assertEqual(EDGES_TOGGLE_LABEL, OPTIONS_LABEL_EDGES)
        self.assertEqual(toggle.toolTip(), EDGES_TOGGLE_TOOLTIP)
        self.assertEqual(EDGES_TOGGLE_TOOLTIP, OPTIONS_TOOLTIP_EDGES)
        self.assertFalse(toggle.isChecked())
        self.assertTrue(toggle.isEnabled())

    def test_clicking_redraws_this_view_and_requests_the_shared_setting(self):
        toggle = self.widget(EdgesToggle(self.viewer))
        toggle.click()
        self.assertTrue(self.viewer.edges_visible())
        self.assertEqual(self.renderer.edges_visible_calls, [True])
        self.assertEqual(self.requests["edges"], [True])
        toggle.click()
        self.assertFalse(self.viewer.edges_visible())
        self.assertEqual(self.requests["edges"], [True, False])

    def test_an_options_change_moves_the_toggle_without_requesting_it_again(self):
        toggle = self.widget(EdgesToggle(self.viewer))
        # The Options dialog reaches the viewer through set_edges_visible.
        self.viewer.set_edges_visible(True)
        self.assertTrue(toggle.isChecked())
        self.viewer.set_edges_visible(False)
        self.assertFalse(toggle.isChecked())
        self.assertEqual(self.requests["edges"], [])

    def test_a_toggle_made_after_the_setting_starts_from_it(self):
        self.viewer.set_edges_visible(True)
        toggle = self.widget(EdgesToggle(self.viewer))
        self.assertTrue(toggle.isChecked())


class EdgesWithoutRebuildTests(_ViewerCase):
    def _apply_scene(self):
        self.viewer.prepare_scene_refresh(BID, ["page-1"])
        self.viewer._do_apply_mesh_data(
            [TRIANGLE],
            [NORMALS],
            [[0, 1, 2]],
            [{"color": "#ff0000", "opacity": 1.0}],
            MeshSceneIdentity(BID, ("page-1",), 1),
            {"page-1": 0.0},
            ["condition"],
            ["t1"],
        )

    def test_toggling_edges_only_redraws_the_existing_scene(self):
        self._apply_scene()
        scene = self.renderer.scene
        clears = scene.scene_clear_calls
        content_changes = []
        self.viewer.scene_content_changed.connect(lambda: content_changes.append(1))
        toggle = self.widget(EdgesToggle(self.viewer))
        with patch.object(self.viewer, "update") as update, patch.object(
            self.viewer, "_do_apply_mesh_data"
        ) as rebuild:
            toggle.click()
            toggle.click()
        self.assertEqual(self.renderer.edges_visible_calls, [True, False])
        self.assertEqual(update.call_count, 2)
        rebuild.assert_not_called()
        self.assertEqual(scene.scene_clear_calls, clears)
        self.assertEqual(content_changes, [])


class TowerCraneToggleSyncTests(_ViewerCase):
    def test_clicking_requests_the_shared_setting(self):
        self.viewer._tower_crane_count = 1
        toggle = self.widget(TowerCraneToggle(self.viewer))
        toggle.click()
        self.assertFalse(self.viewer.tower_crane_visible())
        self.assertEqual(self.requests["crane"], [False])

    def test_an_options_change_moves_the_toggle_without_a_new_scene(self):
        toggle = self.widget(TowerCraneToggle(self.viewer))
        self.viewer.set_tower_crane_visible(False)
        self.assertFalse(toggle.isChecked())
        self.viewer.set_tower_crane_visible(True)
        self.assertTrue(toggle.isChecked())
        self.assertEqual(self.requests["crane"], [])


class SectionCutRowTests(_ViewerCase):
    def test_edges_sits_right_before_the_tower_crane_toggle(self):
        controls = self.widget(SectionCutControls(self.viewer))
        layout = controls.layout()
        widgets = [
            layout.itemAt(index).widget()
            for index in range(layout.count())
            if layout.itemAt(index).widget() is not None
        ]
        self.assertIsInstance(controls.edges_toggle, EdgesToggle)
        self.assertIs(controls.edges_toggle.parent(), controls)
        position = widgets.index(controls.edges_toggle)
        self.assertIs(widgets[position + 1], controls.tower_crane_toggle)
        self.assertEqual(widgets[-1], controls.tower_crane_toggle)


class MeshWindowForwardingTests(unittest.TestCase):
    def test_the_detached_window_forwards_both_requests(self):
        from ost_visualizer.presentation.windows.mesh_view_window import (
            MeshViewWindow,
        )
        from tests.presentation.windows.detached_controls_support import (
            FakeWindowIconProvider,
        )

        _app()
        window = MeshViewWindow(FakeWindowIconProvider(), _Colors())
        self.addCleanup(window.deleteLater)
        seen = []
        window.edges_visibility_requested.connect(lambda v: seen.append(("e", v)))
        window.tower_crane_visibility_requested.connect(lambda v: seen.append(("c", v)))
        window.section_cut_controls.edges_toggle.click()
        window.viewer.request_tower_crane_visible(False)
        self.assertEqual(seen, [("e", True), ("c", False)])


if __name__ == "__main__":
    unittest.main()
