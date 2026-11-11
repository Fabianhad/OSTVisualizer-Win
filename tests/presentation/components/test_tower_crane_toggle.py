import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.mesh_geometry_dto import MeshSceneIdentity
from ost_visualizer.domain.dtos.tower_crane_placement_dto import (
    INCHES_PER_METRE,
    TowerCranePlacement,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer
from ost_visualizer.presentation.components.section_cut_controls import (
    SectionCutControls,
)
from ost_visualizer.presentation.components.tower_crane_toggle import TowerCraneToggle
from ost_visualizer.domain.entities.tower_crane_spec import resolve_tower_crane
from ost_visualizer.presentation.visualization.assets.tower_crane_layout import (
    tower_crane_layout,
)
from ost_visualizer.presentation.visualization.assets.tower_crane_models import (
    TowerCraneKit,
    tower_crane_catalog,
    tower_crane_kit,
)
from ost_visualizer.presentation.config import TOWER_CRANE_TOGGLE_LABEL
from PySide6 import QtWidgets
from tests.presentation.components.mesh_support import FakeMeshRenderer, FakeMeshScene

_MODULE = "ost_visualizer.presentation.components.mesh_view"
BID = BidRef("a.mdb", "bid-1")
TRIANGLE = [0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 10.0, 0.0]
NORMALS = [0.0, 0.0, 1.0] * 3
CATALOG = tower_crane_catalog()


def _spec(notes):
    return resolve_tower_crane(notes, CATALOG).spec


DEFAULT = _spec("[crane]")
LIEBHERR = _spec("[crane model=liebherr]")


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _crane(uid, inactive=False, rotation=0.25, spec=DEFAULT):
    return TowerCranePlacement(
        uid, "footing", "page-1", 10.0, 20.0, 48.0, rotation, inactive, spec
    )


def _prefixed(model, layout):
    return [f"{model}/{part}" for part in layout.parts]


class _Colors:
    @staticmethod
    def convert_to_rgba(color):
        return {"#808080": (0.5, 0.5, 0.5, 1.0)}.get(
            color["color"], (1.0, 0.0, 0.0, 1.0)
        )


class OpenGLViewerTowerCraneTests(unittest.TestCase):
    def setUp(self):
        _app()
        self.viewer = OpenGLViewer(None, _Colors())
        self.renderer = FakeMeshRenderer(FakeMeshScene([]))
        self.viewer._renderer = self.renderer
        self.generation = 0

    def tearDown(self):
        self.viewer._renderer = None
        self.viewer.cleanup()

    def _apply(self, cranes, colors=None):
        self.generation += 1
        self.viewer.prepare_scene_refresh(BID, ["page-1"])
        colors = colors or [{"color": "#ff0000", "opacity": 1.0}] * 2
        self.viewer._do_apply_mesh_data(
            [TRIANGLE, TRIANGLE],
            [NORMALS, NORMALS],
            [[0, 1, 2], [0, 1, 2]],
            colors,
            MeshSceneIdentity(BID, ("page-1",), self.generation),
            {"page-1": 0.0},
            ["footing", "footing"],
            ["t1", "t2"],
            tuple(cranes),
        )

    def test_cranes_load_the_kit_once_and_follow_each_scene(self):
        with patch(f"{_MODULE}.tower_crane_kit", wraps=tower_crane_kit) as find:
            self._apply([_crane("t1"), _crane("t2", rotation=-1.0)])
            self.assertEqual(
                self.renderer.instanced_models, [(b"glTF", INCHES_PER_METRE)]
            )
            self.assertEqual(
                self.renderer.loaded_model, tower_crane_kit("classic").read_bytes()
            )
            self.assertEqual(
                [prefix for prefix, _data in self.renderer.added_models], ["classic/"]
            )
            # Ropes never draw edges; the kit metadata says so.
            self.assertEqual(self.renderer.components_without_edges, ["rope"])
            self.assertEqual(
                self.renderer.scene.model_instances,
                [
                    (10.0, 20.0, 48.0, 0.25, (0.0, 0.0, 0.0, 0.0)),
                    (10.0, 20.0, 48.0, -1.0, (0.0, 0.0, 0.0, 0.0)),
                ],
            )
            self.assertEqual(self.viewer.tower_crane_count(), 2)
            self._apply([_crane("t2")])
            self.assertEqual(len(self.renderer.scene.model_instances), 1)
            self._apply([])
            self.assertEqual(self.viewer.tower_crane_count(), 0)
            self.assertEqual(self.renderer.scene.model_instances, [])
        find.assert_called_once_with("classic")
        self.assertEqual(len(self.renderer.instanced_models), 1)

    def test_each_crane_is_drawn_with_the_layout_of_its_own_arguments(self):
        tall = _spec("[crane mast=40 jib=30 hook=60]")
        self._apply([_crane("t1", spec=tall), _crane("t2")])
        scene = self.renderer.scene
        # One layout per distinct spec, in first-use order.
        self.assertEqual(scene.model_instance_layouts, [0, 1])
        for index, spec in enumerate((tall, DEFAULT)):
            layout = tower_crane_layout(spec)
            names, matrices = scene.model_layouts[index]
            self.assertEqual(names, _prefixed("classic", layout))
            self.assertEqual(matrices, list(layout.flat_matrices))
        self.assertEqual(scene.model_layouts[0][0].count("classic/mast_a"), 20)
        self.assertEqual(scene.model_layouts[1][0].count("classic/mast_a"), 13)
        self.assertIn("classic/rope", scene.model_layouts[0][0])

    def test_two_models_in_one_scene_load_side_by_side_under_their_names(self):
        with patch(f"{_MODULE}.tower_crane_kit", wraps=tower_crane_kit) as find:
            self._apply([_crane("t1"), _crane("t2", spec=LIEBHERR)])
            self._apply([_crane("t2", spec=LIEBHERR)])
        self.assertEqual(
            [prefix for prefix, _data in self.renderer.added_models],
            ["classic/", "liebherr/"],
        )
        self.assertEqual(
            self.renderer.added_models[1][1], tower_crane_kit("liebherr").read_bytes()
        )
        self.assertEqual(
            [call.args for call in find.call_args_list], [("classic",), ("liebherr",)]
        )
        names, matrices = self.renderer.scene.model_layouts[0]
        layout = tower_crane_layout(LIEBHERR)
        self.assertEqual(names, _prefixed("liebherr", layout))
        self.assertEqual(matrices, list(layout.flat_matrices))
        self.assertEqual(names.count("liebherr/mast_a"), 19)
        self.assertNotIn("liebherr/mast_b", names)
        self.assertEqual(self.viewer.tower_crane_count(), 1)

    def test_cranes_with_equal_arguments_share_one_layout(self):
        spec = _spec("[crane mast=30]")
        self._apply([_crane("t1", spec=spec), _crane("t2", spec=spec)])
        scene = self.renderer.scene
        self.assertEqual(len(scene.model_layouts), 1)
        self.assertEqual(scene.model_instance_layouts, [0, 0])
        # A rebuilt scene starts its layouts again.
        self._apply([_crane("t1", spec=spec)])
        self.assertEqual(len(scene.model_layouts), 1)
        self.assertEqual(scene.model_instance_layouts, [0])

    def test_a_placement_without_a_spec_draws_no_crane(self):
        self._apply([_crane("t1", spec=None)])
        self.assertEqual(self.renderer.scene.model_layouts, [])
        self.assertEqual(self.renderer.instanced_models, [])
        self.assertEqual(self.viewer.tower_crane_count(), 0)

    def test_a_kit_the_renderer_only_partly_loads_shows_no_cranes(self):
        self.renderer.instanced_components = ["classic/base", "classic/mast_a"]
        with self.assertLogs(_MODULE, "WARNING") as logs:
            self._apply([_crane("t1")])
        self.assertIn("did not load kit parts", logs.output[0])
        self.assertEqual(self.renderer.scene.model_instances, [])
        self.assertEqual(self.viewer.tower_crane_count(), 0)

    def test_an_inactive_footing_tints_its_crane_with_the_footing_colour(self):
        self._apply(
            [_crane("t1", inactive=True), _crane("t2")],
            colors=[
                {"color": "#808080", "opacity": 1.0},
                {"color": "#ff0000", "opacity": 1.0},
            ],
        )
        tints = [instance[4] for instance in self.renderer.scene.model_instances]
        self.assertEqual(tints, [(0.5, 0.5, 0.5, 1.0), (0.0, 0.0, 0.0, 0.0)])

    def test_scenes_without_cranes_never_read_the_model(self):
        with patch(f"{_MODULE}.tower_crane_kit") as find:
            self._apply([])
        find.assert_not_called()
        self.assertEqual(self.renderer.instanced_models, [])

    def test_a_missing_or_bad_model_logs_once_and_still_shows_the_scene(self):
        for error in (OSError("missing"), ValueError("bad glb")):
            with self.subTest(error=type(error).__name__):
                self.viewer._tower_crane_kits_loaded = {}
                with patch.object(
                    TowerCraneKit,
                    "read_bytes",
                    autospec=True,
                    side_effect=error if isinstance(error, OSError) else None,
                    return_value=tower_crane_kit("classic").read_bytes(),
                ), self.assertLogs(_MODULE, "WARNING") as logs:
                    if isinstance(error, ValueError):
                        self.renderer.instanced_model_error = error
                    self._apply([_crane("t1")])
                    self._apply([_crane("t1")])
                self.renderer.instanced_model_error = None
                self.assertEqual(len(logs.records), 1)
                self.assertEqual(self.renderer.scene.model_instances, [])
                self.assertEqual(self.viewer.tower_crane_count(), 0)
                self.assertEqual(self.renderer.scene.takeoff_uids, ["t1", "t2"])

    def test_a_crane_whose_layout_fails_is_left_out_and_the_scene_still_shows(self):
        # Like the export: a layout that cannot be built (a kit missing one of
        # its layout keys) costs that crane only, never the takeoffs.
        real = tower_crane_layout

        def layout(spec):
            if spec.model == "liebherr":
                raise KeyError("trolley_rope")
            return real(spec)

        with patch(
            f"{_MODULE}.tower_crane_layout", side_effect=layout
        ), self.assertLogs(_MODULE, "WARNING") as logs:
            self._apply([_crane("t1", spec=LIEBHERR), _crane("t2")])
        self.assertIn("could not be laid out", logs.output[0])
        self.assertEqual(self.viewer.tower_crane_count(), 1)
        self.assertEqual(self.renderer.scene.takeoff_uids, ["t1", "t2"])

    def test_a_model_without_a_kit_shows_no_crane_and_the_others_still_draw(self):
        unknown = replace(DEFAULT, model="potain")
        with self.assertLogs(_MODULE, "WARNING") as logs:
            self._apply([_crane("t1", spec=unknown), _crane("t2")])
        self.assertIn("potain", logs.output[0])
        self.assertEqual(self.viewer.tower_crane_count(), 1)
        self.assertEqual(len(self.renderer.scene.model_instances), 1)

    def test_visibility_reaches_current_and_later_renderers(self):
        self.assertTrue(self.viewer.tower_crane_visible())
        self.viewer.set_tower_crane_visible(False)
        self.assertEqual(self.renderer.model_instances_visible_calls, [False])
        self.viewer.set_tower_crane_visible(False)
        self.assertEqual(self.renderer.model_instances_visible_calls, [False])
        self.viewer._renderer = None
        self.viewer._tower_crane_kits_loaded = {"classic": True}
        with patch(f"{_MODULE}.ost_renderer.Renderer") as renderer_class:
            self.assertTrue(self.viewer._ensure_renderer())
        renderer_class.return_value.set_model_instances_visible.assert_called_once_with(
            False
        )
        # A new renderer has its own GL objects, so every kit is loaded again.
        self.assertEqual(self.viewer._tower_crane_kits_loaded, {})
        self.viewer._renderer = self.renderer

    def test_cross_thread_payload_and_scene_load_carry_the_cranes(self):
        self.viewer.prepare_scene_refresh(BID, ["page-1"])
        payload = {
            "vertices": [TRIANGLE],
            "normals": [NORMALS],
            "indices": [[0, 1, 2]],
            "colors": [{"color": "#ff0000", "opacity": 1.0}],
            "scene_identity": MeshSceneIdentity(BID, ("page-1",), 5),
            "page_floor_elevations": {"page-1": 0.0},
            "condition_uids": ["footing"],
            "takeoff_uids": ["t1"],
            "tower_cranes": (_crane("t1"),),
        }
        self.viewer._apply_queued_mesh_data(payload)
        self.assertEqual(self.viewer.tower_crane_count(), 1)
        self.viewer.prepare_scene_refresh(BID, ["page-1"])
        older = dict(payload, scene_identity=MeshSceneIdentity(BID, ("page-1",), 6))
        del older["tower_cranes"]
        self.viewer._apply_queued_mesh_data(older)
        self.assertEqual(self.viewer.tower_crane_count(), 0)
        self.viewer.begin_scene_load(BID)
        self.assertEqual(self.viewer.tower_crane_count(), 0)


class TowerCraneToggleTests(unittest.TestCase):
    def setUp(self):
        _app()
        self.viewer = OpenGLViewer(None, SimpleNamespace())
        self.renderer = FakeMeshRenderer(FakeMeshScene([]))
        self.viewer._renderer = self.renderer

    def tearDown(self):
        self.viewer._renderer = None
        self.viewer.cleanup()

    def test_toggle_starts_on_and_is_disabled_without_cranes(self):
        toggle = TowerCraneToggle(self.viewer)
        try:
            self.assertEqual(toggle.text(), TOWER_CRANE_TOGGLE_LABEL)
            self.assertTrue(toggle.isChecked())
            self.assertFalse(toggle.isEnabled())
            self.viewer._tower_crane_count = 2
            self.viewer.scene_content_changed.emit()
            self.assertTrue(toggle.isEnabled())
            toggle.setChecked(False)
            self.assertFalse(self.viewer.tower_crane_visible())
            self.assertEqual(self.renderer.model_instances_visible_calls, [False])
            self.viewer.set_tower_crane_visible(True)
            self.viewer.scene_content_changed.emit()
            self.assertTrue(toggle.isChecked())
        finally:
            toggle.deleteLater()

    def test_section_cut_row_holds_the_toggle(self):
        controls = SectionCutControls(self.viewer)
        try:
            self.assertIsInstance(controls.tower_crane_toggle, TowerCraneToggle)
            self.assertIs(controls.tower_crane_toggle.parent(), controls)
        finally:
            controls.deleteLater()


if __name__ == "__main__":
    unittest.main()
