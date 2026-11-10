import base64
import json
import math
import shutil
import unittest
from unittest.mock import create_autospec, patch
from ost_visualizer.application.dtos.color_dtos import (
    ColorMappingResult,
    ColorWithOpacity,
)
from ost_visualizer.application.interfaces.i_color_service import IColorService
from ost_visualizer.application.interfaces.i_coordinate_transformer import (
    ICoordinateTransformer,
)
from ost_visualizer.application.interfaces.i_takeoff_domain_service import (
    ITakeoffDomainService,
)
from ost_visualizer.domain.dtos.tower_crane_placement_dto import (
    INCHES_PER_METRE,
    TowerCranePlacement,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.visualization.assets.tower_crane_asset import (
    TOWER_CRANE_CREDIT,
    glb_local_bounds,
    native_instance_corners,
    read_tower_crane_model,
)
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.presentation.visualization.renderers.threejs.mesh_processor import (
    process_meshes_for_threejs,
)
from ost_visualizer.presentation.visualization.renderers.threejs.threejs_renderer import (
    _generate_html,
)
from ost_visualizer.presentation.visualization.renderers.threejs.tower_crane_scene import (
    build_tower_crane_scene_data,
)
from tests.presentation.visualization.renderers.threejs.test_threejs_renderer import (
    _MINIMAL_SCENE,
    _compact_code,
    _embedded_scene,
    _extract_js_function,
    _run_node,
)

_SCENE_MODULE = (
    "ost_visualizer.presentation.visualization.renderers.threejs.tower_crane_scene"
)
_MESH = MeshData([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])


def _crane(uid, x, y, z, rotation, inactive=False):
    return TowerCranePlacement(uid, "footing", "page", x, y, z, rotation, inactive)


def _metadata(crane, color="#ff0000"):
    return {
        "tower_crane": crane,
        "layer_uid": "layer",
        "area_uid": "area",
        "color": color,
        "takeoff_uid": crane.takeoff_uid,
    }


class TowerCraneSceneDataTests(unittest.TestCase):
    def test_bids_without_crane_footings_get_no_crane_data(self):
        self.assertIsNone(build_tower_crane_scene_data([]))
        self.assertIsNone(
            build_tower_crane_scene_data(
                [(_MESH, {"takeoff_uid": "t", "color": "#fff"})]
            )
        )

    def test_placements_use_the_export_frame_and_footing_keys(self):
        first = _crane("t1", -1200.0, 600.0, 48.0, -math.radians(30.0))
        second = _crane("t2", -300.0, 900.0, 12.0, 0.0, inactive=True)
        data = build_tower_crane_scene_data(
            [(_MESH, _metadata(first)), (_MESH, _metadata(second, "#808080"))]
        )
        self.assertEqual(
            base64.b64decode(data["model_base64"]), read_tower_crane_model()
        )
        self.assertEqual(data["units_per_metre"], INCHES_PER_METRE)
        self.assertEqual(data["credit"], TOWER_CRANE_CREDIT)
        self.assertEqual(
            data["placements"][0],
            {
                "position": [-1200.0, 48.0, -600.0],
                "rotation_y": -math.radians(30.0),
                "tint": [],
                "takeoff_uid": "t1",
                "condition_uid": "footing",
                "layer_uid": "layer",
                "area_uid": "area",
                "page_uid": "page",
            },
        )
        self.assertEqual(
            data["placements"][1]["tint"], [128 / 255.0, 128 / 255.0, 128 / 255.0]
        )
        # Clip bounds cover every placed crane's box, mapped to Y-up.
        bounds = glb_local_bounds(read_tower_crane_model())
        for crane in (first, second):
            for x, y, z in native_instance_corners(
                bounds, INCHES_PER_METRE, crane.x, crane.y, crane.z, crane.rotation
            ):
                for value, low, high in zip(
                    (x, z, -y),
                    data["render_bounds"]["min"],
                    data["render_bounds"]["max"],
                ):
                    self.assertLessEqual(low, value + 1e-6)
                    self.assertGreaterEqual(high, value - 1e-6)

    def test_a_missing_model_logs_and_exports_without_cranes(self):
        crane = _crane("t1", 0.0, 0.0, 0.0, 0.0)
        with patch(
            f"{_SCENE_MODULE}.read_tower_crane_model", side_effect=OSError("gone")
        ), self.assertLogs(_SCENE_MODULE, "WARNING"):
            self.assertIsNone(build_tower_crane_scene_data([(_MESH, _metadata(crane))]))

    def test_html_embeds_the_crane_data_safely(self):
        scene = dict(_MINIMAL_SCENE)
        scene["tower_cranes"] = build_tower_crane_scene_data(
            [(_MESH, _metadata(_crane("t1", 0.0, 0.0, 0.0, 0.0)))]
        )
        html = _generate_html(scene, "Viewer")
        self.assertEqual(_embedded_scene(html)["tower_cranes"], scene["tower_cranes"])
        self.assertNotIn(
            "tower_cranes", _embedded_scene(_generate_html(_MINIMAL_SCENE, "V"))
        )


class TowerCraneMeshMetadataTests(unittest.TestCase):
    def setUp(self):
        self.colors = create_autospec(IColorService, instance=True)
        self.colors.get_color_mapping.return_value = ColorMappingResult(
            {}, {"c": "#123456"}
        )
        self.colors.get_color_for_takeoff.return_value = ColorWithOpacity(
            "#123456", 1.0
        )
        self.colors.is_inactive_area_takeoff.return_value = True
        self.takeoffs = create_autospec(ITakeoffDomainService, instance=True)
        self.coord_system = create_autospec(ICoordinateTransformer, instance=True)
        self.coord_system.transform_to_3d.side_effect = lambda x, y: (-x, y)
        self.coord_system.ost_to_real_units.side_effect = float
        self.module = (
            "ost_visualizer.presentation.visualization.renderers.threejs.mesh_processor"
        )

    def _process(self, condition, takeoff):
        self.takeoffs.group_area_takeoffs_with_holes.return_value = ([takeoff], {})
        self.takeoffs.group_takeoffs_by_type.return_value = {2: [takeoff]}
        with patch(self.module + ".MeshFactory") as factory, patch(
            self.module + ".apply_boolean_operations", side_effect=lambda items: items
        ):
            factory.return_value.create_mesh_for_takeoff.return_value = _MESH
            meshes, _ = process_meshes_for_threejs(
                {"c": condition},
                [takeoff],
                self.coord_system,
                self.colors,
                self.takeoffs,
                page_area_selections={"page": "other"},
                inactive_object_color="#aaaaaa",
            )
        return meshes[0][1]

    def test_tagged_count_footings_carry_their_crane_into_the_export(self):
        condition = Condition(
            "c", condition_type=Condition.TYPE_COUNT, height=24.0, notes="(crane)"
        )
        takeoff = Takeoff(
            "t", "c", page_uid="page", position=[100.0, 50.0], rotation=0.5
        )
        metadata = self._process(condition, takeoff)
        self.assertEqual(
            metadata["tower_crane"],
            TowerCranePlacement("t", "c", "page", -100.0, 50.0, 24.0, -0.5, True),
        )
        self.colors.is_inactive_area_takeoff.assert_called_once_with(
            takeoff, {"page": "other"}
        )

    def test_untagged_footings_never_ask_for_area_state(self):
        condition = Condition("c", condition_type=Condition.TYPE_COUNT, notes="pad")
        takeoff = Takeoff("t", "c", page_uid="page", position=[100.0, 50.0])
        self.assertNotIn("tower_crane", self._process(condition, takeoff))
        self.colors.is_inactive_area_takeoff.assert_not_called()


class TowerCraneTemplateTests(unittest.TestCase):
    def setUp(self):
        self.html = _generate_html(_MINIMAL_SCENE, "Viewer")

    def assertCodeIn(self, needle, html):
        self.assertIn(_compact_code(needle).rstrip(","), _compact_code(html))

    def test_toggle_and_credit_are_hidden_until_cranes_load(self):
        self.assertCodeIn(
            '<label for="tower-crane-toggle" id="tower-crane-label" hidden>Tower crane</label>',
            self.html,
        )
        self.assertCodeIn(
            '<input id="tower-crane-toggle" type="checkbox" checked hidden />',
            self.html,
        )
        self.assertCodeIn(
            '<p class="note" id="tower-crane-credit" hidden></p>', self.html
        )
        self.assertCodeIn("let towerCraneEnabled = true;", self.html)

    def test_loader_is_imported_on_demand_and_cranes_follow_the_footing(self):
        self.assertCodeIn('import("three/addons/loaders/GLTFLoader.js")', self.html)
        self.assertNotIn("import { GLTFLoader }", self.html)
        self.assertCodeIn(
            "(object.userData.towerCrane !== true || towerCraneEnabled) &&", self.html
        )
        self.assertCodeIn("new THREE.Matrix4().makeRotationY(Math.PI)", self.html)
        self.assertCodeIn("target.rotation.y = rotation;", self.html)
        self.assertCodeIn("registerVisibilityObject(keys, object, true);", self.html)
        self.assertCodeIn(
            "unionSceneBounds(sceneData.bounds, sceneData.tower_cranes && "
            "sceneData.tower_cranes.render_bounds)",
            self.html,
        )
        # Cameras and cut extents keep the takeoff bounds; no caps for cranes.
        self.assertCodeIn(
            'extent: getSectionCutExtent(sceneData.bounds, "northSouth"),', self.html
        )
        crane_code = self.html.split("function placeTowerCranes", 1)[1].split(
            "function loadTowerCranes", 1
        )[0]
        self.assertNotIn("meshRecords", crane_code)


@unittest.skipUnless(shutil.which("node"), "Node.js is required to execute viewer JS")
class TowerCraneScriptTests(unittest.TestCase):
    def setUp(self):
        self.html = _generate_html(_MINIMAL_SCENE, "Viewer")

    def test_crane_objects_need_their_footing_visible_and_the_toggle_on(self):
        functions = "\n".join(
            _extract_js_function(self.html, name)
            for name in ("isGroupVisible", "isObjectVisible")
        )
        script = f"""
        let towerCraneEnabled = true;
        const layerVisibility = new Map();
        const conditionVisibility = new Map();
        const areaVisibility = new Map([["a", {{visible: true}}]]);
        const page3dVisibility = new Map();
        {functions}
        const crane = {{userData: {{towerCrane: true, areaUid: "a"}}}};
        const footing = {{userData: {{areaUid: "a"}}}};
        const out = [isObjectVisible(crane), isObjectVisible(footing)];
        towerCraneEnabled = false;
        out.push(isObjectVisible(crane), isObjectVisible(footing));
        towerCraneEnabled = true;
        areaVisibility.get("a").visible = false;
        out.push(isObjectVisible(crane), isObjectVisible(footing));
        console.log(JSON.stringify(out));
        """
        self.assertEqual(
            json.loads(_run_node(script)), [True, True, False, True, False, False]
        )

    def test_clip_bounds_union_ignores_missing_or_bad_crane_bounds(self):
        function = _extract_js_function(self.html, "unionSceneBounds")
        script = f"""
        {function}
        const base = {{min: [0, 0, -10], max: [10, 5, 0]}};
        console.log(JSON.stringify([
          unionSceneBounds(base, {{min: [-4, 1, -2], max: [3, 50, 1]}}),
          unionSceneBounds(base, undefined),
          unionSceneBounds(base, {{min: [], max: []}}),
          unionSceneBounds(undefined, {{min: [1, 2, 3], max: [4, 5, 6]}}),
        ]));
        """
        self.assertEqual(
            json.loads(_run_node(script)),
            [
                {"min": [-4, 0, -10], "max": [10, 50, 1]},
                {"min": [0, 0, -10], "max": [10, 5, 0]},
                {"min": [0, 0, -10], "max": [10, 5, 0]},
                {"min": [1, 2, 3], "max": [4, 5, 6]},
            ],
        )


if __name__ == "__main__":
    unittest.main()
