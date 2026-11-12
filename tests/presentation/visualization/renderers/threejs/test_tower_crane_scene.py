import base64
import json
import math
import shutil
import unittest
from dataclasses import replace
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
    native_instance_corners,
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
from ost_visualizer.domain.entities.tower_crane_spec import resolve_tower_crane
from ost_visualizer.presentation.visualization.assets.tower_crane_layout import (
    tower_crane_layout,
)
from ost_visualizer.presentation.visualization.assets.tower_crane_models import (
    TowerCraneKit,
    tower_crane_catalog,
    tower_crane_kit,
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
CATALOG = tower_crane_catalog()


def _spec(notes):
    return resolve_tower_crane(notes, CATALOG).spec


DEFAULT = _spec("[crane]")
LIEBHERR = _spec("[crane model=liebherr]")


def _kit_entry(model):
    kit = tower_crane_kit(model)
    return {
        "model": model,
        "model_base64": base64.b64encode(kit.read_bytes()).decode("ascii"),
        "credit": kit.credit,
        "parts_without_edges": ["rope"],
    }


def _crane(uid, x, y, z, rotation, inactive=False, spec=DEFAULT):
    return TowerCranePlacement(
        uid, "footing", "page", x, y, z, rotation, inactive, spec
    )


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
        self.assertEqual(data["kits"], [_kit_entry("classic")])
        self.assertEqual(data["units_per_metre"], INCHES_PER_METRE)
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
                "layout": 0,
                "hover": "",
            },
        )
        self.assertEqual(
            data["placements"][1]["tint"], [128 / 255.0, 128 / 255.0, 128 / 255.0]
        )
        # Both cranes are the default one: a single layout, shared.
        default = tower_crane_layout(DEFAULT)
        self.assertEqual(
            data["layouts"],
            [
                {
                    "kit": 0,
                    "parts": list(default.parts),
                    "matrices": list(default.flat_matrices),
                }
            ],
        )
        self.assertEqual([p["layout"] for p in data["placements"]], [0, 0])
        # Clip bounds cover every placed crane's box, mapped to Y-up.
        bounds = default.bounds
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

    def test_each_distinct_spec_gets_one_layout_and_placements_point_at_it(self):
        tall = _spec("[crane mast=40 jib=30 hook=60]")
        short = _spec("[crane mast=5 jib=6]")
        cranes = [
            _crane("t1", 0.0, 0.0, 0.0, 0.0, spec=tall),
            _crane("t2", 500.0, 0.0, 0.0, 1.0, spec=short),
            _crane("t3", 900.0, 0.0, 0.0, 2.0, spec=tall),
            _crane("t4", 1300.0, 0.0, 0.0, 0.0),
        ]
        data = build_tower_crane_scene_data([(_MESH, _metadata(c)) for c in cranes])
        self.assertEqual([p["layout"] for p in data["placements"]], [0, 1, 0, 2])
        for index, spec in enumerate((tall, short, DEFAULT)):
            layout = tower_crane_layout(spec)
            self.assertEqual(data["layouts"][index]["parts"], list(layout.parts))
            self.assertEqual(
                data["layouts"][index]["matrices"], list(layout.flat_matrices)
            )
        self.assertEqual(data["layouts"][0]["parts"].count("mast_a"), 20)
        # The tallest crane sets the top of the clip bounds (Y-up, inches).
        top = tower_crane_layout(tall).bounds[1][1] * INCHES_PER_METRE
        self.assertAlmostEqual(data["render_bounds"]["max"][1], top, places=6)
        # The kit is embedded once however many cranes there are.
        self.assertEqual(len(data["kits"]), 1)
        self.assertLess(len(json.dumps(data)), 2 * len(data["kits"][0]["model_base64"]))

    def test_each_model_in_use_is_embedded_once_with_its_credit(self):
        cranes = [
            _crane("t1", 0.0, 0.0, 0.0, 0.0, spec=LIEBHERR),
            _crane("t2", 500.0, 0.0, 0.0, 1.0),
            _crane(
                "t3", 900.0, 0.0, 0.0, 2.0, spec=_spec("[crane model=liebherr mast=20]")
            ),
        ]
        data = build_tower_crane_scene_data([(_MESH, _metadata(c)) for c in cranes])
        # Kits in first-use order; every layout says which kit it uses.
        self.assertEqual(data["kits"], [_kit_entry("liebherr"), _kit_entry("classic")])
        self.assertEqual([layout["kit"] for layout in data["layouts"]], [0, 1, 0])
        self.assertEqual([p["layout"] for p in data["placements"]], [0, 1, 2])
        self.assertEqual(data["kits"][0]["credit"]["title"], "Liebherr tower crane")
        self.assertEqual(data["kits"][0]["credit"]["author"], "Cem Alagozlu")
        self.assertEqual(data["kits"][1]["credit"]["author"], "Chamod")
        self.assertNotIn("mast_b", data["layouts"][0]["parts"])
        # The export carries the same matrices the native viewer gets.
        for layout, spec in zip(data["layouts"], (LIEBHERR, DEFAULT, cranes[2].spec)):
            self.assertEqual(
                layout["matrices"], list(tower_crane_layout(spec).flat_matrices)
            )

    def test_a_kit_that_is_not_used_is_not_embedded(self):
        liebherr_only = build_tower_crane_scene_data(
            [(_MESH, _metadata(_crane("t1", 0.0, 0.0, 0.0, 0.0, spec=LIEBHERR)))]
        )
        classic_only = build_tower_crane_scene_data(
            [(_MESH, _metadata(_crane("t1", 0.0, 0.0, 0.0, 0.0)))]
        )
        self.assertEqual([kit["model"] for kit in liebherr_only["kits"]], ["liebherr"])
        classic_text = json.dumps(classic_only)
        self.assertNotIn(_kit_entry("liebherr")["model_base64"][:4000], classic_text)
        # The crane data is about the size of the kits it embeds, nothing more.
        for data, model in ((classic_only, "classic"), (liebherr_only, "liebherr")):
            embedded = len(_kit_entry(model)["model_base64"])
            self.assertLess(len(json.dumps(data)), embedded + 40_000)

    def test_a_missing_or_unreadable_kit_logs_and_exports_without_those_cranes(self):
        crane = _crane("t1", 0.0, 0.0, 0.0, 0.0)
        with patch.object(
            TowerCraneKit, "read_bytes", side_effect=OSError("gone")
        ), self.assertLogs(_SCENE_MODULE, "WARNING"):
            self.assertIsNone(build_tower_crane_scene_data([(_MESH, _metadata(crane))]))
        unknown = _crane(
            "t2", 0.0, 0.0, 0.0, 0.0, spec=replace(DEFAULT, model="potain")
        )
        with self.assertLogs(_SCENE_MODULE, "WARNING") as logs:
            data = build_tower_crane_scene_data(
                [(_MESH, _metadata(unknown)), (_MESH, _metadata(crane))]
            )
        self.assertIn("potain", logs.output[0])
        self.assertEqual([kit["model"] for kit in data["kits"]], ["classic"])
        self.assertEqual(len(data["placements"]), 1)

    def test_a_crane_that_cannot_be_laid_out_is_skipped_and_its_kit_dropped(self):
        real = tower_crane_layout

        def layout(spec):
            if spec.model == "liebherr":
                raise KeyError("jib")
            return real(spec)

        cranes = [
            _crane("t1", 0.0, 0.0, 0.0, 0.0, spec=LIEBHERR),
            _crane("t2", 0.0, 0.0, 0.0, 0.0),
        ]
        with patch(
            f"{_SCENE_MODULE}.tower_crane_layout", side_effect=layout
        ), self.assertLogs(_SCENE_MODULE, "WARNING"):
            data = build_tower_crane_scene_data([(_MESH, _metadata(c)) for c in cranes])
        self.assertEqual([kit["model"] for kit in data["kits"]], ["classic"])
        self.assertEqual(data["layouts"][0]["kit"], 0)
        self.assertEqual(len(data["placements"]), 1)
        with patch(
            f"{_SCENE_MODULE}.tower_crane_layout", side_effect=KeyError("jib")
        ), self.assertLogs(_SCENE_MODULE, "WARNING"):
            self.assertIsNone(
                build_tower_crane_scene_data([(_MESH, _metadata(cranes[1]))])
            )

    def test_a_placement_without_a_spec_is_left_out(self):
        crane = _crane("t1", 0.0, 0.0, 0.0, 0.0, spec=None)
        self.assertIsNone(build_tower_crane_scene_data([(_MESH, _metadata(crane))]))

    def test_the_export_lists_the_parts_that_draw_no_edges(self):
        data = build_tower_crane_scene_data(
            [
                (_MESH, _metadata(_crane("t1", 0.0, 0.0, 0.0, 0.0))),
                (_MESH, _metadata(_crane("t2", 0.0, 0.0, 0.0, 0.0, spec=LIEBHERR))),
            ]
        )
        self.assertEqual(
            [kit["parts_without_edges"] for kit in data["kits"]], [["rope"], ["rope"]]
        )

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
            "c", condition_type=Condition.TYPE_COUNT, height=24.0, notes="[crane]"
        )
        takeoff = Takeoff(
            "t", "c", page_uid="page", position=[100.0, 50.0], rotation=0.5
        )
        metadata = self._process(condition, takeoff)
        self.assertEqual(
            metadata["tower_crane"],
            TowerCranePlacement(
                "t", "c", "page", -100.0, 50.0, 24.0, -0.5, True, DEFAULT
            ),
        )
        liebherr = Condition(
            "c",
            condition_type=Condition.TYPE_COUNT,
            height=24.0,
            notes="[crane model=liebherr]",
        )
        self.colors.is_inactive_area_takeoff.reset_mock()
        self.assertEqual(self._process(liebherr, takeoff)["tower_crane"].spec, LIEBHERR)
        self.colors.is_inactive_area_takeoff.reset_mock()
        self._process(condition, takeoff)
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
        # The Options "Tower crane" setting is the toggle's default; on if absent.
        self.assertCodeIn(
            "let towerCraneEnabled = viewOptions.tower_crane !== false;", self.html
        )
        self.assertCodeIn("towerCraneToggle.checked = towerCraneEnabled;", self.html)

    def test_loader_is_imported_on_demand_and_cranes_follow_the_footing(self):
        self.assertCodeIn('import("three/addons/loaders/GLTFLoader.js")', self.html)
        self.assertNotIn("import { GLTFLoader }", self.html)
        self.assertCodeIn(
            "(object.userData.towerCrane !== true || towerCraneEnabled) &&", self.html
        )
        self.assertNotIn("towerCraneLocalMatrix", self.html)
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

    def test_the_viewer_places_a_layout_exactly_where_python_puts_it(self):
        function = "const EDGE_THRESHOLD_DEGREES = 15;\n" + "\n".join(
            _extract_js_function(self.html, name)
            for name in (
                "towerCraneFeatureEdges",
                "towerCraneComputedLines",
                "towerCraneLayoutParts",
            )
        )
        for model, notes_list in (
            (
                "classic",
                (
                    "[crane]",
                    "[crane mast=30 jib=24 counterjib=6 trolley=50% hook=40]",
                    "[crane mast=2 jib=5 counterjib=2 hookheight=3]",
                ),
            ),
            (
                "liebherr",
                (
                    "[crane model=liebherr]",
                    "[crane model=liebherr mast=20 jib=45m counterjib=6 trolley=60% hookheight=20ft]",
                    "[crane model=liebherr mast=4 jib=11 counterjib=1]",
                ),
            ),
        ):
            with self.subTest(model=model):
                self._check_layout_parity(function, model, notes_list)

    def _check_layout_parity(self, function, model, notes_list):
        kit = tower_crane_kit(model).metadata
        # A stand-in kit: every part is the eight corners of its real bounding box
        # (two triangles and one edge segment are enough to carry them through).
        fake_kit = {}
        for name in kit["parts"]:
            low, high = kit["parts"][name]["min"], kit["parts"][name]["max"]
            corners = [
                [high[k] if corner & (1 << k) else low[k] for k in range(3)]
                for corner in range(8)
            ]
            fake_kit[name] = {
                "meshes": [
                    {
                        "positions": [v for corner in corners for v in corner],
                        "normals": [0.0, 1.0, 0.0] * 8,
                        "indices": [0, 1, 2, 5, 6, 7],
                        "color": [1.0, 0.5, 0.0] if name != "rope" else [0.2, 0.2, 0.2],
                        "alpha": 1.0,
                    }
                ],
                "lines": (
                    []
                    if name == "rope"
                    else [
                        {
                            "positions": [v for corner in corners for v in corner],
                            "indices": [0, 7],
                            "color": [1.0, 0.5, 0.0],
                            "alpha": 1.0,
                        }
                    ]
                ),
            }
        for notes in notes_list:
            with self.subTest(notes=notes):
                layout = tower_crane_layout(_spec(notes))
                payload = {
                    "kit": fake_kit,
                    "layout": {
                        "parts": list(layout.parts),
                        "matrices": list(layout.flat_matrices),
                    },
                    "units": INCHES_PER_METRE,
                }
                script = f"""
                {function}
                const input = {json.dumps(payload)};
                const kit = new Map(Object.entries(input.kit));
                // As the viewer does: the kit's parts_without_edges (the rope).
                const groups = towerCraneLayoutParts(
                  kit, input.layout, input.units, new Set(["rope"])
                );
                const bounds = (values) => {{
                  const lo = [Infinity, Infinity, Infinity];
                  const hi = [-Infinity, -Infinity, -Infinity];
                  for (let i = 0; i < values.length; i += 3) {{
                    for (let k = 0; k < 3; k++) {{
                      lo[k] = Math.min(lo[k], values[i + k]);
                      hi[k] = Math.max(hi[k], values[i + k]);
                    }}
                  }}
                  return [lo, hi];
                }};
                console.log(JSON.stringify(groups.map((g) => ({{
                  color: g.color,
                  alpha: g.alpha,
                  vertices: g.positions.length / 3,
                  indices: g.indices.length,
                  maxIndex: Math.max(...g.indices),
                  edges: g.edges.length / 3,
                  bounds: bounds(g.positions),
                  normalLengths: [
                    Math.min(...Array.from({{length: g.normals.length / 3}}, (_, i) =>
                      Math.hypot(g.normals[i*3], g.normals[i*3+1], g.normals[i*3+2]))),
                    Math.max(...Array.from({{length: g.normals.length / 3}}, (_, i) =>
                      Math.hypot(g.normals[i*3], g.normals[i*3+1], g.normals[i*3+2]))),
                  ],
                }}))));
                """
                groups = json.loads(_run_node(script))
                steel, rope = groups
                self.assertEqual(rope["color"], [0.2, 0.2, 0.2])
                items = len(layout.items)
                ropes = layout.parts.count("rope")
                self.assertEqual(steel["vertices"], 8 * (items - ropes))
                self.assertEqual(rope["vertices"], 8 * ropes)
                self.assertEqual(steel["indices"], 6 * (items - ropes))
                self.assertEqual(steel["maxIndex"], steel["vertices"] - 1)
                self.assertEqual(steel["edges"], 2 * (items - ropes))
                self.assertEqual(rope["edges"], 0)
                for group in groups:
                    for length in group["normalLengths"]:
                        self.assertAlmostEqual(length, 1.0, places=6)
                # The merged crane fills the Python layout's bounds, in the
                # viewer's local frame: (x, y, z) -> (-x, y, -z) x inches.
                low, high = layout.bounds
                expected_low = [-high[0], low[1], -high[2]]
                expected_high = [-low[0], high[1], -low[2]]
                got_low = [min(g["bounds"][0][k] for g in groups) for k in range(3)]
                got_high = [max(g["bounds"][1][k] for g in groups) for k in range(3)]
                for got, want in zip(got_low + got_high, expected_low + expected_high):
                    self.assertAlmostEqual(got, want * INCHES_PER_METRE, places=6)

    def test_layout_placement_ignores_unknown_parts_and_short_matrix_lists(self):
        function = "const EDGE_THRESHOLD_DEGREES = 15;\n" + "\n".join(
            _extract_js_function(self.html, name)
            for name in (
                "towerCraneFeatureEdges",
                "towerCraneComputedLines",
                "towerCraneLayoutParts",
            )
        )
        script = f"""
        {function}
        const part = {{meshes: [{{positions: [1, 2, 3], normals: [0, 1, 0],
          indices: [0], color: [1, 0, 0], alpha: 1}}], lines: []}};
        const kit = new Map([["a", part]]);
        const identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0];
        const move = [1, 0, 0, 10, 0, 1, 0, 20, 0, 0, 1, 30];
        console.log(JSON.stringify([
          towerCraneLayoutParts(kit, {{parts: ["a", "missing", "a"],
            matrices: [...identity, ...identity, ...move]}}, 2).map((g) => g.positions),
          towerCraneLayoutParts(kit, {{parts: ["a", "a"], matrices: identity}}, 1)
            .map((g) => g.positions),
          towerCraneLayoutParts(kit, undefined, 1),
          towerCraneLayoutParts(kit, {{}}, 1),
        ]));
        """
        placed, short, missing, empty = json.loads(_run_node(script))
        self.assertEqual(placed, [[-2, 4, -6, -22, 44, -66]])
        self.assertEqual(short, [[-1, 2, -3]])
        self.assertEqual((missing, empty), ([], []))

    def test_parts_marked_without_edges_contribute_no_edge_lines(self):
        function = "const EDGE_THRESHOLD_DEGREES = 15;\n" + "\n".join(
            _extract_js_function(self.html, name)
            for name in (
                "towerCraneFeatureEdges",
                "towerCraneComputedLines",
                "towerCraneLayoutParts",
            )
        )
        script = f"""
        {function}
        const mesh = {{positions: [0, 0, 0, 1, 0, 0, 0, 1, 0], normals: [0, 0, 1, 0, 0, 1, 0, 0, 1],
          indices: [0, 1, 2], color: [1, 0, 0], alpha: 1}};
        const lines = [{{positions: mesh.positions, indices: [0, 1], color: [1, 0, 0], alpha: 1}}];
        const kit = new Map([["rope", {{meshes: [mesh], lines}}], ["mast", {{meshes: [mesh], lines}}]]);
        const identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0];
        const edges = (names, without) => towerCraneLayoutParts(
          kit, {{parts: names, matrices: names.flatMap(() => identity)}}, 1, without
        ).reduce((n, g) => n + g.edges.length / 3, 0);
        console.log(JSON.stringify([
          edges(["rope"], new Set(["rope"])), edges(["mast"], new Set(["rope"])),
          edges(["rope"], undefined),
        ]));
        """
        rope, mast, unflagged = json.loads(_run_node(script))
        self.assertEqual((rope, mast, unflagged), (0, 2, 2))
        load = _compact_code(_extract_js_function(self.html, "loadTowerCranes"))
        self.assertIn(
            _compact_code(
                "towerCraneLayoutParts(kit, layout, unitsPerMetre, withoutEdges)"
            ),
            load,
        )
        self.assertIn(_compact_code("new Set(kit.parts_without_edges || [])"), load)
        # Each layout is drawn from its own kit, with that kit's edge rule.
        self.assertIn(_compact_code("const kit = kitParts[layout.kit];"), load)
        self.assertIn(
            _compact_code("const withoutEdges = kitWithoutEdges[layout.kit];"), load
        )
        self.assertIn(_compact_code("buffers.map("), load)
        self.assertIn(_compact_code("Promise.all("), load)

    def test_every_embedded_kit_gets_its_own_credit_line(self):
        function = _extract_js_function(self.html, "renderTowerCraneCredit")
        script = f"""
        const node = (tag) => ({{tag, children: [], textContent: "",
          append(...items) {{ this.children.push(...items); }}}});
        const document = {{createElement: node}};
        const towerCraneCredit = node("p");
        {function}
        const text = () => towerCraneCredit.children.map((c) =>
          typeof c === "string" ? c : c.tag === "br" ? "\\n" : c.textContent).join("");
        const credit = (title, author) => ({{title, author, site: "Sketchfab",
          license: "CC BY 4.0", modified: "cut", source_url: "s", author_url: "a",
          license_url: "l"}});
        renderTowerCraneCredit([credit("One", "A"), credit("Two", "B")]);
        const two = text();
        towerCraneCredit.children = [];
        renderTowerCraneCredit([credit("One", "A")]);
        const one = text();
        towerCraneCredit.children = [];
        renderTowerCraneCredit(undefined);
        // ASCII only: the console's code page would mangle the curly quotes.
        console.log(JSON.stringify([two, one, text()]).replace(/[^\\x00-\\x7f]/g,
          (c) => "\\\\u" + c.charCodeAt(0).toString(16).padStart(4, "0")));
        """
        two, one, none = json.loads(_run_node(script))
        line = "Crane model: \u201c{}\u201d by {} on Sketchfab, CC BY 4.0; cut."
        self.assertEqual(two, line.format("One", "A") + "\n" + line.format("Two", "B"))
        self.assertEqual(one, line.format("One", "A"))
        self.assertEqual(none, "")

    def test_unbaked_parts_get_computed_edges_like_the_native_viewer(self):
        functions = "\n".join(
            _extract_js_function(self.html, name)
            for name in (
                "towerCraneFeatureEdges",
                "towerCraneComputedLines",
                "towerCraneLayoutParts",
            )
        )
        script = f"""
        const EDGE_THRESHOLD_DEGREES = 15;
        {functions}
        // A unit cube with its own vertices per face (as glTF stores it): the
        // twelve cube edges are creases, the face diagonals are not edges.
        const faces = [
          [[0,0,0],[0,1,0],[1,1,0],[1,0,0]], [[0,0,1],[1,0,1],[1,1,1],[0,1,1]],
          [[0,0,0],[1,0,0],[1,0,1],[0,0,1]], [[0,1,0],[0,1,1],[1,1,1],[1,1,0]],
          [[0,0,0],[0,0,1],[0,1,1],[0,1,0]], [[1,0,0],[1,1,0],[1,1,1],[1,0,1]],
        ];
        const positions = [], indices = [];
        faces.forEach((quad) => {{
          const base = positions.length / 3;
          quad.forEach((p) => positions.push(...p));
          indices.push(base, base + 1, base + 2, base, base + 2, base + 3);
        }});
        const mesh = {{positions, normals: positions.map(() => 0), indices, color: [1, 0, 0], alpha: 1}};
        const baked = {{positions, indices: [0, 2], color: [1, 0, 0], alpha: 1}};
        const kit = new Map([
          ["plain", {{meshes: [mesh], lines: []}}],
          ["rope", {{meshes: [mesh], lines: []}}],
          ["drawn", {{meshes: [mesh], lines: [baked]}}],
        ]);
        const identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0];
        const edges = (name) => towerCraneLayoutParts(
          kit, {{parts: [name], matrices: identity}}, 1, new Set(["rope"])
        ).reduce((n, g) => n + g.edges.length / 6, 0);
        console.log(JSON.stringify([edges("plain"), edges("rope"), edges("drawn")]));
        """
        plain, rope, drawn = json.loads(_run_node(script))
        # Computed: the 12 cube edges. Marked without edges: none. Baked: only those.
        self.assertEqual((plain, rope, drawn), (12, 0, 1))

    def test_placing_reports_the_count_and_shares_edge_materials(self):
        function = _extract_js_function(self.html, "placeTowerCranes")
        script = f"""
        let lineMaterials = 0;
        class Vector3 {{
          constructor(x, y, z) {{ this.x = x; this.y = y; this.z = z; }}
          copy(v) {{ this.x = v.x; this.y = v.y; this.z = v.z; return this; }}
        }}
        class Group {{
          constructor() {{ this.position = new Vector3(0, 0, 0); this.rotation = {{y: 0}}; }}
          add() {{}}
        }}
        class Mesh {{
          constructor(geometry, material) {{
            this.geometry = geometry; this.material = material;
            this.userData = {{}}; this.layers = {{set() {{}}}};
          }}
        }}
        class LineSegments extends Mesh {{}}
        class LineBasicMaterial {{ constructor() {{ lineMaterials += 1; }} }}
        class Color {{ constructor() {{}} }}
        const THREE = {{Vector3, Group, Mesh, LineSegments, LineBasicMaterial, Color}};
        const readVector3 = (v, fallback) =>
          Array.isArray(v) && v.length >= 3 ? new Vector3(v[0], v[1], v[2]) : fallback;
        const readColor = (c) => c;
        const createNativeMaterial = (kind) => ({{kind}});
        const towerCranePlacementKeys = () => ({{}});
        const addTowerCraneObject = () => {{}};
        const scene = new Group();
        const edgesRoot = new Group();
        const transparentMeshes = [];
        const NATIVE_TRANSPARENT_ALPHA = 0.99, EDGE_COLOR_SCALE = 0.45;
        const OPAQUE_LAYER = 0, TRANSPARENT_LAYER = 1, EDGE_LAYER = 2;
        const sectionPlanes = [];
        const hoverMeshes = [];
        {function}
        const part = (color) => ({{geometry: {{}}, edgesGeometry: {{}}, color, alpha: 1}});
        const layouts = [[part([1, 0, 0]), part([0, 1, 0]), part([1, 0, 0])]];
        const at = (layout) => ({{position: [0, 0, 0], rotation_y: 0, layout}});
        const placed = placeTowerCranes(layouts, [at(0), at(0)]);
        const skipped = placeTowerCranes(layouts, [at(5), {{position: [], rotation_y: 0, layout: 0}}]);
        console.log(JSON.stringify([placed, skipped, lineMaterials]));
        """
        placed, skipped, line_materials = json.loads(_run_node(script))
        self.assertEqual((placed, skipped), (2, 0))
        # Two cranes of three parts in two colours share two edge materials.
        self.assertEqual(line_materials, 2)

    def _load_with(self, kits, layouts, placements):
        """Run the viewer's own loadTowerCranes with a stand-in GLTFLoader that
        refuses a kit whose bytes read "bad"; returns what it placed and showed."""
        functions = "\n".join(
            _extract_js_function(self.html, name)
            for name in ("base64ToArrayBuffer", "loadTowerCranes")
        )
        loader_import = 'import("three/addons/loaders/GLTFLoader.js")'
        self.assertIn(loader_import, functions)
        functions = functions.replace(
            loader_import, "Promise.resolve({ GLTFLoader: FakeLoader })"
        )
        data = {
            "units_per_metre": 39.37,
            "kits": kits,
            "layouts": layouts,
            "placements": placements,
        }
        script = f"""
        class FakeLoader {{
          parse(buffer, path, resolve, reject) {{
            const text = new TextDecoder().decode(buffer);
            if (text === "bad") reject(new Error("bad glb"));
            else resolve({{ name: text }});
          }}
        }}
        const towerCraneData = {json.dumps(data)};
        const log = {{ credits: null, controls: [], placed: null }};
        const renderTowerCraneCredit = (credits) => {{
          log.credits = credits.map((c) => c.title);
        }};
        const showTowerCraneControls = (visible) => log.controls.push(visible);
        const towerCraneKitParts = (gltf) => gltf.name;
        const towerCraneLayoutParts = (kit, layout) => [kit + ":" + layout.parts[0]];
        const towerCraneGeometries = (part) => part;
        const placeTowerCranes = (layouts) => {{
          log.placed = layouts;
          return layouts.filter((parts) => parts.length).length;
        }};
        console.warn = () => {{}};
        {functions}
        loadTowerCranes();
        setTimeout(() => console.log(JSON.stringify(log)), 100);
        """
        return json.loads(_run_node(script))

    def test_a_kit_that_fails_to_load_drops_only_its_own_cranes(self):
        # The native viewer leaves out only the cranes of a model whose kit
        # fails; the export must do the same, for a kit that will not parse and
        # for one whose embedded bytes will not decode.
        good = {"model": "a", "model_base64": "Z29vZA==", "credit": {"title": "A"}}
        layouts = [{"kit": 0, "parts": ["x"]}, {"kit": 1, "parts": ["y"]}]
        placements = [{"layout": 0}, {"layout": 1}]
        for name, broken in (
            ("parse", {"model": "b", "model_base64": "YmFk", "credit": {"title": "B"}}),
            ("decode", {"model": "b", "model_base64": "@@@", "credit": {"title": "B"}}),
        ):
            with self.subTest(failure=name):
                log = self._load_with([good, broken], layouts, placements)
                self.assertEqual(log["placed"], [["good:x"], []])
                self.assertEqual(log["controls"], [True])
                # Only the models on screen are credited.
                self.assertEqual(log["credits"], ["A"])
        # When every kit fails there is nothing to show.
        log = self._load_with(
            [dict(good, model_base64="YmFk")], [layouts[0]], [placements[0]]
        )
        self.assertEqual(log["controls"], [False])
        self.assertEqual(log["credits"], [])

    def test_crane_controls_show_only_when_a_crane_was_placed(self):
        load = _extract_js_function(self.html, "loadTowerCranes")
        self.assertNotIn("showTowerCraneControls(true)", load)
        self.assertIn(
            _compact_code(
                "showTowerCraneControls(placeTowerCranes(layouts, placements) > 0)"
            ),
            _compact_code(load),
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
