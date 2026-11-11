import unittest
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer, ost_renderer


class NativeRendererBoundaryTests(unittest.TestCase):
    def test_native_camera_restore_clears_motion_and_sets_saved_pose_atomically(self):
        camera = ost_renderer.Camera()
        camera.rotate(100.0, -50.0)
        self.assertTrue(camera.has_velocity())
        bounds = ost_renderer.Box3()
        bounds.min = ost_renderer.Vec3(-10.0, -20.0, -1.0)
        bounds.max = ost_renderer.Vec3(10.0, 20.0, 5.0)
        camera.restore_state(
            ost_renderer.Vec3(4.0, 5.0, 6.0),
            ost_renderer.Vec3(1.0, 2.0, 3.0),
            38.0,
            bounds,
        )
        self.assertFalse(camera.has_velocity())
        self.assertEqual(
            (camera.position.x, camera.position.y, camera.position.z),
            (4.0, 5.0, 6.0),
        )
        self.assertEqual(
            (camera.target.x, camera.target.y, camera.target.z),
            (1.0, 2.0, 3.0),
        )
        self.assertEqual(camera.fov, 38.0)

    def test_default_camera_frames_the_model_like_the_html_export(self):
        from ost_visualizer.presentation.visualization.renderers.threejs.adapters.threejs_mesh_adapter import (
            ThreejsMeshAdapter,
        )

        # Native Z-up bounds of bid 2828: x, y, z min/max.
        x0, x1, y0, y1, z0, z1 = -3306.0, -528.0, 77.0, 2418.0, 0.0, 332.0
        bounds = ost_renderer.Box3()
        bounds.min = ost_renderer.Vec3(x0, y0, z0)
        bounds.max = ost_renderer.Vec3(x1, y1, z1)
        camera = ost_renderer.Camera()
        camera.show_object(bounds)
        export = ThreejsMeshAdapter(None).build_scene_data(
            [], (x0, x1, y0, y1, z0, z1), "Camera"
        )["camera"]

        def to_native(v):  # the export is Y-up: (x, y, z) -> native (x, -z, y)
            return (v[0], -v[2], v[1])

        for native, exported in (
            (camera.position, export["position"]),
            (camera.target, export["target"]),
        ):
            for actual, expected in zip(
                (native.x, native.y, native.z), to_native(exported)
            ):
                self.assertAlmostEqual(actual, expected, places=2)
        # Seen from the +y side looking toward -y, as in the export.
        self.assertGreater(camera.position.y, camera.target.y)
        self.assertGreater(camera.position.z, camera.target.z)

    def test_native_camera_reset_looks_from_the_same_side(self):
        camera = ost_renderer.Camera()
        camera.reset()
        self.assertEqual(
            (camera.position.x, camera.position.y, camera.position.z),
            (0.0, 1000.0, 1500.0),
        )

    def test_shipped_tower_crane_kit_parses_into_the_scene_frame(self):
        from ost_visualizer.domain.dtos.tower_crane_placement_dto import (
            INCHES_PER_METRE,
        )
        from ost_visualizer.presentation.visualization.assets.tower_crane_models import (
            tower_crane_kit,
        )

        classic = tower_crane_kit("classic")
        summary = ost_renderer.parse_instanced_model_summary(
            classic.read_bytes(), INCHES_PER_METRE
        )
        components = {entry["name"]: entry for entry in summary["components"]}
        self.assertEqual(list(components), list(classic.metadata["parts"]))
        self.assertIs(summary["baked_lines"], True)
        materials = {part["name"] for part in summary["parts"]}
        self.assertEqual(
            materials,
            {"material", "frame", "CONCRETE", "IRON", "BUCKET", "ROPE", "GLASS"},
        )
        alphas = {part["name"]: part["color"][3] for part in summary["parts"]}
        self.assertLess(alphas["GLASS"], 0.99)
        self.assertEqual(alphas["material"], 1.0)
        # Z-up inches: a jib bay runs one pitch toward scene -x (plan +x), a mast
        # bay rises one pitch along +z, the base anchors dip below the footing top.
        self.assertAlmostEqual(
            components["jib_a"]["min"][0], -1.9973 * INCHES_PER_METRE, delta=2
        )
        self.assertLess(components["jib_a"]["max"][0], 2.0)
        self.assertAlmostEqual(
            components["mast_a"]["max"][2], 1.52 * INCHES_PER_METRE, delta=4
        )
        self.assertAlmostEqual(
            components["base"]["min"][2], -0.372 * INCHES_PER_METRE, delta=1
        )
        # The unit rope is one metre tall and carries no edge lines.
        self.assertAlmostEqual(
            components["rope"]["max"][2], INCHES_PER_METRE, delta=0.1
        )
        self.assertEqual([part["lines"] for part in components["rope"]["parts"]], [0])

    def test_liebherr_kit_parses_with_one_mast_bay_and_its_base_on_the_footing(self):
        from ost_visualizer.domain.dtos.tower_crane_placement_dto import (
            INCHES_PER_METRE,
        )
        from ost_visualizer.presentation.visualization.assets.tower_crane_models import (
            tower_crane_kit,
        )

        liebherr = tower_crane_kit("liebherr")
        summary = ost_renderer.parse_instanced_model_summary(
            liebherr.read_bytes(), INCHES_PER_METRE
        )
        components = {entry["name"]: entry for entry in summary["components"]}
        self.assertEqual(list(components), list(liebherr.metadata["parts"]))
        self.assertNotIn("mast_b", components)
        self.assertIs(summary["baked_lines"], True)
        # Only the cab windows are see-through, with the classic kit's glass.
        glass = {p["color"][3] for p in summary["parts"] if p["name"] == "GLASS"}
        self.assertEqual(len(glass), 1)
        self.assertAlmostEqual(glass.pop(), 0.5, places=3)
        self.assertTrue(
            all(p["color"][3] == 1.0 for p in summary["parts"] if p["name"] != "GLASS")
        )
        # Z-up inches: the base block's bottom is the footing top; a mast bay
        # rises one pitch; a jib bay runs one pitch toward scene -x.
        self.assertAlmostEqual(components["base"]["min"][2], 0.0, delta=0.1)
        self.assertAlmostEqual(
            components["mast_a"]["max"][2], 1.65537 * INCHES_PER_METRE, delta=0.5
        )
        self.assertLess(components["jib_a"]["min"][0], -1.28 * INCHES_PER_METRE)
        self.assertEqual([part["lines"] for part in components["rope"]["parts"]], [0])

    def test_model_nodes_parse_into_named_components_with_their_own_parts(self):
        from tests.integration.native.glb_support import cube_glb

        red = (1.0, 0.0, 0.0, 1.0)
        blue = (0.0, 0.0, 1.0, 1.0)
        glass = (0.5, 0.5, 0.5, 0.5)
        parts = [
            ("steel", 0.5, (0.0, 0.0, 0.0), red, False),
            ("steel_b", 0.5, (0.0, 2.0, 0.0), red, False),
            ("paint", 1.0, (10.0, 0.0, 0.0), blue, False),
            ("glass", 0.25, (0.0, 0.0, 5.0), glass, True),
            ("paint_b", 0.5, (12.0, 0.0, 0.0), blue, False),
        ]
        names = ["mast_a", "mast_a", "jib_section", None, "jib_section"]
        summary = ost_renderer.parse_instanced_model_summary(
            cube_glb(parts, names), 10.0
        )
        components = {entry["name"]: entry for entry in summary["components"]}
        # Components keep node order; an unnamed node is the "" component.
        self.assertEqual(list(components), ["mast_a", "jib_section", ""])
        self.assertEqual(
            {
                name: [part["name"] for part in entry["parts"]]
                for name, entry in components.items()
            },
            {
                "mast_a": ["steel", "steel_b"],
                "jib_section": ["paint", "paint_b"],
                "": ["glass"],
            },
        )
        # Each component has its own bounds, in the scene frame (-x, z, y) * units.
        self.assertEqual(components["mast_a"]["min"], (-5.0, -5.0, -5.0))
        self.assertEqual(components["mast_a"]["max"], (5.0, 5.0, 25.0))
        self.assertEqual(components["jib_section"]["min"], (-125.0, -10.0, -10.0))
        self.assertEqual(components["jib_section"]["max"], (-90.0, 10.0, 10.0))
        self.assertEqual(components[""]["min"], (-2.5, 47.5, -2.5))
        self.assertEqual(components[""]["max"], (2.5, 52.5, 2.5))
        # The flattened part list and overall bounds cover every component.
        self.assertEqual(
            [part["name"] for part in summary["parts"]],
            ["steel", "steel_b", "paint", "paint_b", "glass"],
        )
        self.assertEqual(summary["min"], (-125.0, -10.0, -10.0))
        self.assertEqual(summary["max"], (5.0, 52.5, 25.0))
        self.assertEqual(sum(part["triangles"] for part in summary["parts"]), 60)

    def test_a_single_unnamed_node_is_one_component_as_before(self):
        from tests.integration.native.glb_support import cube_glb

        parts = [
            ("a", 0.5, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 1.0), False),
            ("b", 0.5, (3.0, 0.0, 0.0), (0.0, 1.0, 0.0, 1.0), False),
        ]
        summary = ost_renderer.parse_instanced_model_summary(cube_glb(parts), 1.0)
        (component,) = summary["components"]
        self.assertEqual(component["name"], "")
        self.assertEqual([part["name"] for part in component["parts"]], ["a", "b"])
        self.assertEqual(component["parts"], summary["parts"])

    def test_baked_line_primitives_become_the_parts_edges(self):
        from tests.integration.native.glb_support import cube_glb

        red = (1.0, 0.0, 0.0, 1.0)
        parts = [
            ("a", 0.5, (0.0, 0.0, 0.0), red, False),
            ("b", 0.5, (3.0, 0.0, 0.0), red, False),
            ("rope", 0.5, (6.0, 0.0, 0.0), red, False),
        ]
        names = ["mast", "mast", "rope"]
        # Part "a" bakes two segments, "b" one; the rope carries none.
        lines = [[0, 2, 4, 6], [1, 3], None]
        summary = ost_renderer.parse_instanced_model_summary(
            cube_glb(parts, names, lines), 1.0
        )
        self.assertIs(summary["baked_lines"], True)
        self.assertEqual(
            {part["name"]: part["lines"] for part in summary["parts"]},
            {"a": 2, "b": 1, "rope": 0},
        )
        self.assertEqual(sum(part["triangles"] for part in summary["parts"]), 36)
        # Without any LINES primitive the renderer computes edges itself.
        plain = ost_renderer.parse_instanced_model_summary(cube_glb(parts, names), 1.0)
        self.assertIs(plain["baked_lines"], False)
        self.assertEqual([part["lines"] for part in plain["parts"]], [0, 0, 0])
        for bad in ([0, 2, 4], [0, 99]):
            with self.subTest(lines=bad):
                with self.assertRaises(ValueError):
                    ost_renderer.parse_instanced_model_summary(
                        cube_glb(parts[:1], None, [bad]), 1.0
                    )

    def test_model_layouts_are_validated_numbered_and_cleared_with_the_scene(self):
        scene = ost_renderer.Scene()
        clear = ost_renderer.Color(0.0, 0.0, 0.0, 0.0)
        origin = ost_renderer.Vec3(0.0, 0.0, 0.0)
        identity = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        self.assertEqual(scene.model_layout_count(), 0)
        self.assertEqual(scene.add_model_layout(["mast_a"], identity), 0)
        self.assertEqual(scene.add_model_layout(["mast_a", "rope"], identity * 2), 1)
        self.assertEqual(scene.add_model_layout([], []), 2)
        self.assertEqual(scene.model_layout_count(), 3)
        for names, values in (
            (["mast_a"], identity[:11]),
            (["mast_a"], identity * 2),
            ([], identity),
            (["mast_a", "rope"], identity),
        ):
            with self.subTest(names=names, values=len(values)):
                with self.assertRaisesRegex(ValueError, "12 matrix values"):
                    scene.add_model_layout(names, values)
        for bad in (float("nan"), float("inf")):
            with self.assertRaisesRegex(ValueError, "finite"):
                scene.add_model_layout(["mast_a"], identity[:3] + [bad] + identity[4:])
        self.assertEqual(scene.model_layout_count(), 3)
        # An instance uses the whole model (-1, the default) or an existing layout.
        scene.add_model_instance(origin, 0.0, clear)
        scene.add_model_instance(origin, 0.0, clear, -1)
        scene.add_model_instance(origin, 0.0, clear, layout=2)
        for missing in (3, -2):
            with self.assertRaisesRegex(ValueError, "layout does not exist"):
                scene.add_model_instance(origin, 0.0, clear, missing)
        self.assertEqual(scene.model_instance_count(), 3)
        self.assertTrue(scene.get_bounds().is_empty())
        scene.clear()
        self.assertEqual(scene.model_layout_count(), 0)
        self.assertEqual(scene.model_instance_count(), 0)
        with self.assertRaisesRegex(ValueError, "layout does not exist"):
            scene.add_model_instance(origin, 0.0, clear, 0)

    def test_instanced_model_and_instances_reject_bad_input(self):
        for data in (b"", b"not a glb", b"glTF" + bytes(16)):
            with self.subTest(data=data[:8]):
                with self.assertRaises(ValueError):
                    ost_renderer.parse_instanced_model_summary(data, 39.37)
        from ost_visualizer.presentation.visualization.assets.tower_crane_models import (
            tower_crane_kit,
        )

        for units in (0.0, -1.0, float("nan")):
            with self.subTest(units=units):
                with self.assertRaises(ValueError):
                    ost_renderer.parse_instanced_model_summary(
                        tower_crane_kit("classic").read_bytes(), units
                    )
        scene = ost_renderer.Scene()
        clear = ost_renderer.Color(0.0, 0.0, 0.0, 0.0)
        scene.add_model_instance(ost_renderer.Vec3(1.0, 2.0, 3.0), 0.5, clear)
        self.assertEqual(scene.model_instance_count(), 1)
        self.assertTrue(scene.get_bounds().is_empty())
        with self.assertRaisesRegex(ValueError, "finite"):
            scene.add_model_instance(
                ost_renderer.Vec3(1.0, 2.0, 3.0), float("inf"), clear
            )
        scene.clear()
        self.assertEqual(scene.model_instance_count(), 0)

    def test_layout_matrices_must_keep_a_positive_volume(self):
        scene = ost_renderer.Scene()
        identity = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        self.assertEqual(scene.add_model_layout(["part"], identity), 0)
        for label, matrix in (
            ("zero", [0.0] * 12),
            ("flattened", [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ("mirrored", [1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]),
        ):
            with self.subTest(label):
                with self.assertRaisesRegex(ValueError, "determinant"):
                    scene.add_model_layout(["part", "part"], identity + matrix)
        # A rejected layout adds nothing.
        self.assertEqual(scene.add_model_layout(["part"], identity), 1)

    def test_native_mesh_vectors_reject_incomplete_coordinates(self):
        mesh = ost_renderer.MeshData()
        with self.assertRaisesRegex(ValueError, "vertex array length"):
            mesh.set_vertices([0.0, 1.0])
        with self.assertRaisesRegex(ValueError, "normal array length"):
            mesh.set_normals([0.0, 0.0, 1.0, 1.0])

    def test_native_scene_rejects_invalid_indices_before_gl_upload(self):
        mesh = ost_renderer.MeshData()
        mesh.set_vertices(
            [
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
            ]
        )
        scene = ost_renderer.Scene()
        mesh.indices = [0, 1]
        with self.assertRaisesRegex(ValueError, "index array length"):
            scene.add_mesh(mesh)
        mesh.indices = [0, 1, 3]
        with self.assertRaisesRegex(ValueError, "outside the vertex array"):
            scene.add_mesh(mesh)
