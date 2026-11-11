"""Real ost_renderer checks for the instanced decoration model (tower crane).
They need a native Windows GL window, so they skip under the offscreen Qt
platform the normal test runs use."""

import math
import unittest
from PySide6 import QtCore, QtGui, QtWidgets
from tests.integration.native.glb_support import cube_glb
from tests.integration.native.test_renderer_section_cuts import _box

UNITS_PER_METRE = 10.0
RED_CUBE = ("red", 0.5, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 1.0), False)
# glTF +Z maps to scene +y, so this cube sits 10 units along +y before turning.
OFFSET_CUBE = ("offset", 0.5, (0.0, 0.0, 1.0), (1.0, 0.0, 0.0, 1.0), False)
# Layout matrices are 3 x 4, row-major, in the model's own glTF frame (metres, Y-up).
_IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]


def _translation(x, y, z):
    return [1.0, 0.0, 0.0, x, 0.0, 1.0, 0.0, y, 0.0, 0.0, 1.0, z]


def _scale(x, y, z):
    return [x, 0.0, 0.0, 0.0, 0.0, y, 0.0, 0.0, 0.0, 0.0, z, 0.0]


def _rotation_y(angle):
    c, s = math.cos(angle), math.sin(angle)
    return [c, 0.0, s, 0.0, 0.0, 1.0, 0.0, 0.0, -s, 0.0, c, 0.0]


def _rotation_z(angle):
    c, s = math.cos(angle), math.sin(angle)
    return [c, -s, 0.0, 0.0, s, c, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]


def _multiply(a, b):
    rows = [a[0:4], a[4:8], a[8:12], [0.0, 0.0, 0.0, 1.0]]
    cols = [b[0:4], b[4:8], b[8:12], [0.0, 0.0, 0.0, 1.0]]
    return [
        sum(rows[r][k] * cols[k][c] for k in range(4))
        for r in range(3)
        for c in range(4)
    ]


def reference_bounds(matrices, half, units, x=0.0, y=0.0, z=0.0, rotation=0.0):
    """Scene-frame bounds of cubes of half-size ``half`` placed by ``matrices``.
    From first principles: apply the matrix in the glTF frame, convert the point
    to the scene frame (-x, z, y) x units, then turn about +Z and move.
    """
    c, s = math.cos(rotation), math.sin(rotation)
    points = []
    for m in matrices:
        for gx in (-half, half):
            for gy in (-half, half):
                for gz in (-half, half):
                    px, py, pz = (
                        m[r * 4] * gx
                        + m[r * 4 + 1] * gy
                        + m[r * 4 + 2] * gz
                        + m[r * 4 + 3]
                        for r in range(3)
                    )
                    lx, ly, lz = -px * units, pz * units, py * units
                    points.append((c * lx - s * ly + x, s * lx + c * ly + y, lz + z))
    return (
        tuple(min(p[k] for p in points) for k in range(3)),
        tuple(max(p[k] for p in points) for k in range(3)),
    )


class NativeInstancedModelTests(unittest.TestCase):
    SIZE = 128

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        if QtGui.QGuiApplication.platformName() != "windows":
            raise unittest.SkipTest("needs the native Windows Qt platform for OpenGL")
        from ost_visualizer.presentation.components import ost_renderer

        cls.r = ost_renderer

    def setUp(self):
        r = self.r
        self.widget = QtWidgets.QWidget()
        self.widget.setAttribute(QtCore.Qt.WA_NativeWindow)
        self.widget.setAttribute(QtCore.Qt.WA_PaintOnScreen)
        self.widget.resize(self.SIZE, self.SIZE)
        self.widget.show()
        self.app.processEvents()
        self.renderer = r.Renderer(int(self.widget.winId()))
        self.renderer.resize(self.SIZE, self.SIZE)
        # A grey footing behind the model as seen from +x.
        vertices, faces = _box((-40, -5, -5), (-30, 5, 5))
        mesh = r.MeshData()
        mesh.set_vertices([float(v) for v in vertices])
        mesh.indices = faces
        mesh.color = r.Color(0.5, 0.5, 0.5, 1.0)
        self.renderer.scene.add_mesh(mesh)
        self.renderer.camera.restore_state(
            r.Vec3(100.0, 0.0, 0.0),
            r.Vec3(0.0, 0.0, 0.0),
            30.0,
            self.renderer.scene.get_bounds(),
        )
        self.renderer.resume()

    def tearDown(self):
        self.renderer.shutdown()
        self.widget.close()

    def _use_model(self, *parts):
        self.renderer.set_instanced_model(cube_glb(list(parts)), UNITS_PER_METRE)

    def _add(self, x=0.0, y=0.0, z=0.0, rotation=0.0, tint=None):
        r = self.r
        self.renderer.scene.add_model_instance(
            r.Vec3(x, y, z), rotation, tint or r.Color(0.0, 0.0, 0.0, 0.0)
        )

    def _frame(self):
        self.renderer.render()
        self.renderer.render()

    def _pixel(self, x, y):
        import ctypes

        gl = ctypes.WinDLL("opengl32")
        data = (ctypes.c_ubyte * 4)()
        gl.glReadBuffer(0x0404)  # GL_FRONT: the frame render() just presented
        gl.glReadPixels(x, y, 1, 1, 0x1908, 0x1401, data)
        return tuple(data)

    def test_instances_draw_hide_what_is_behind_and_never_pick(self):
        self._use_model(RED_CUBE)
        self.assertTrue(self.renderer.has_instanced_model())
        self._add()
        self.assertEqual(self.renderer.scene.model_instance_count(), 1)
        centre = self.SIZE // 2
        self._frame()
        red = self._pixel(centre, centre)
        self.assertGreater(red[0], 2 * max(red[1], red[2]) + 40, red)
        self.assertEqual(self.renderer.pick(centre, centre), -1)
        self.renderer.set_model_instances_visible(False)
        self.assertFalse(self.renderer.model_instances_visible())
        self._frame()
        grey = self._pixel(centre, centre)
        self.assertLess(abs(grey[0] - grey[2]), 8, grey)
        self.assertEqual(self.renderer.pick(centre, centre), 0)

    def test_instances_stay_out_of_scene_bounds_but_widen_render_bounds(self):
        self._use_model(RED_CUBE)
        self._add(z=20.0)
        self.assertAlmostEqual(self.renderer.scene.get_bounds().max.x, -30.0)
        bounds = self.renderer.render_bounds()
        self.assertAlmostEqual(bounds.max.x, 5.0, places=4)
        self.assertAlmostEqual(bounds.max.z, 25.0, places=4)
        self.renderer.set_model_instances_visible(False)
        self.assertAlmostEqual(self.renderer.render_bounds().max.x, -30.0)

    def test_a_section_cut_removes_the_part_beyond_it(self):
        self._use_model(RED_CUBE)
        self._add()
        centre = self.SIZE // 2
        self.renderer.set_section_cut(0, True, -10.0)
        self._frame()
        self.assertEqual(self.renderer.pick(centre, centre), 0)
        pixel = self._pixel(centre, centre)
        self.assertLess(abs(pixel[0] - pixel[2]), 8, pixel)

    def test_rotation_turns_the_model_about_its_base_and_tint_recolours_it(self):
        self._use_model(OFFSET_CUBE)
        centre = self.SIZE // 2
        # 10 scene units at 100 units with a 30 degree field of view is ~24 px.
        offsets = (centre - 24, centre + 24)

        def redness():
            self._frame()
            return [self._pixel(x, centre)[0] for x in offsets]

        self._add()
        unturned = redness()
        self.renderer.scene.clear()
        self.renderer.scene.add_mesh(self._footing())
        self._add(rotation=math.pi)
        turned = redness()
        self.assertEqual(
            [value > 150 for value in unturned],
            [value < 150 for value in unturned][::-1],
        )
        self.assertEqual(
            [value > 150 for value in turned], [value > 150 for value in unturned][::-1]
        )
        self.renderer.scene.clear()
        self.renderer.scene.add_mesh(self._footing())
        self._add(rotation=math.pi, tint=self.r.Color(0.0, 1.0, 0.0, 1.0))
        self._frame()
        lit = max((self._pixel(x, centre) for x in offsets), key=lambda p: p[1])
        self.assertGreater(lit[1], 2 * max(lit[0], lit[2]) + 40, lit)

    def _footing(self):
        r = self.r
        vertices, faces = _box((-40, -5, -5), (-30, 5, 5))
        mesh = r.MeshData()
        mesh.set_vertices([float(v) for v in vertices])
        mesh.indices = faces
        mesh.color = r.Color(0.5, 0.5, 0.5, 1.0)
        return mesh

    def test_transparent_parts_blend_and_edges_draw_without_errors(self):
        self._use_model(
            ("glass", 0.5, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.5), True),
        )
        self._add()
        centre = self.SIZE // 2
        self.renderer.set_edges_visible(True)
        self._frame()
        pixel = self._pixel(centre, centre)
        # The glass goes through the weighted pass; the native composite keeps
        # its averaged colour almost opaque at perspective depths.
        self.assertGreater(pixel[2], pixel[0] + 100, pixel)
        self.assertEqual(self.renderer.pick(centre, centre), -1)
        self.renderer.set_model_instances_visible(False)
        self._frame()
        grey = self._pixel(centre, centre)
        self.assertLess(abs(grey[0] - grey[2]), 8, grey)

    def test_baked_lines_are_drawn_as_the_edges_instead_of_computed_ones(self):
        centre = self.SIZE // 2
        self.renderer.set_edges_visible(True)

        def face_centre_red(line_indices):
            self.renderer.scene.clear()
            self.renderer.scene.add_mesh(self._footing())
            self.renderer.set_instanced_model(
                cube_glb([RED_CUBE], None, line_indices), UNITS_PER_METRE
            )
            self._add()
            self._frame()
            return self._pixel(centre, centre)[0]

        # The camera sees the cube's glTF -x face (vertices 4..7). A baked
        # diagonal 4-6 crosses the face centre, where computed edges never run.
        computed = face_centre_red(None)
        baked = face_centre_red([[4, 6]])
        self.assertGreater(computed, 150)
        self.assertLess(baked, computed - 40, (baked, computed))
        # A model that bakes lines elsewhere leaves this face without any edge.
        other_face = face_centre_red([[0, 2]])
        self.assertGreater(other_face, computed - 15, (other_face, computed))

    def test_parts_without_baked_lines_get_computed_edges(self):
        centre = self.SIZE // 2
        far = ("far", 0.1, (0.0, 3.0, 0.0), (0.0, 1.0, 0.0, 1.0), False)

        def border(line_indices, edges):
            self.renderer.scene.clear()
            self.renderer.scene.add_mesh(self._footing())
            self.renderer.set_instanced_model(
                cube_glb([RED_CUBE, far], None, line_indices), UNITS_PER_METRE
            )
            self._add()
            self.renderer.set_edges_visible(edges)
            self._frame()
            # The red cube's right silhouette edge is ~12 px from the centre.
            return sum(
                self._pixel(x, centre)[0] for x in range(centre + 6, centre + 18)
            )

        # The far part bakes lines; the red cube has none and still gets edges.
        self.assertNotEqual(border([None, [0, 2]], True), border([None, [0, 2]], False))
        self.assertEqual(border([None, [0, 2]], True), border(None, True))

    def test_components_marked_without_edges_draw_none_even_when_unbaked(self):
        centre = self.SIZE // 2
        far = ("far", 0.1, (0.0, 3.0, 0.0), (0.0, 1.0, 0.0, 1.0), False)

        def border(edges, without):
            self.renderer.scene.clear()
            self.renderer.scene.add_mesh(self._footing())
            self.renderer.set_instanced_model(
                cube_glb([RED_CUBE, far], ["red", "far"]), UNITS_PER_METRE, without
            )
            self._add()
            self.renderer.set_edges_visible(edges)
            self._frame()
            return sum(
                self._pixel(x, centre)[0] for x in range(centre + 6, centre + 18)
            )

        self.assertNotEqual(border(True, []), border(False, []))
        self.assertEqual(border(True, ["red"]), border(False, ["red"]))

    def test_shipped_kit_ropes_draw_no_edge_lines(self):
        from ost_visualizer.presentation.visualization.assets.tower_crane_asset import (
            read_tower_crane_kit,
            tower_crane_kit_metadata,
            tower_crane_parts_without_edges,
        )

        kit = read_tower_crane_kit()
        without = list(tower_crane_parts_without_edges(tower_crane_kit_metadata(kit)))
        self.assertEqual(without, ["rope"])
        centre = self.SIZE // 2
        # One thick rope standing across the view (scaled 40x in its width).
        rope = [40.0, 0.0, 0.0, 0.0, 0.0, 6.0, 0.0, -3.0, 0.0, 0.0, 40.0, 0.0]

        def column(edges):
            self.renderer.scene.clear()
            self.renderer.scene.add_mesh(self._footing())
            self.renderer.set_instanced_model(kit, UNITS_PER_METRE, without)
            layout = self.renderer.scene.add_model_layout(["rope"], rope)
            self.renderer.scene.add_model_instance(
                self.r.Vec3(0.0, 0.0, 0.0),
                0.0,
                self.r.Color(0.0, 0.0, 0.0, 0.0),
                layout,
            )
            self.renderer.set_edges_visible(edges)
            self._frame()
            return [self._pixel(x, centre) for x in range(centre - 20, centre + 20)]

        drawn = column(True)
        self.assertTrue(any(max(p[:3]) > 40 for p in drawn))
        self.assertEqual(drawn, column(False))

    def test_a_model_of_named_nodes_reports_its_components_and_draws_them_all(self):
        blue_offset = ("blue", 0.5, (0.0, 0.0, 1.0), (0.0, 0.0, 1.0, 1.0), False)
        self.assertEqual(self.renderer.instanced_model_components(), [])
        self.renderer.set_instanced_model(
            cube_glb([RED_CUBE, blue_offset], ["mast_a", "jib_section"]),
            UNITS_PER_METRE,
        )
        self.assertEqual(
            self.renderer.instanced_model_components(), ["mast_a", "jib_section"]
        )
        self._add()
        self._frame()
        centre = self.SIZE // 2
        red = self._pixel(centre, centre)
        self.assertGreater(red[0], 2 * max(red[1], red[2]) + 40, red)
        # The second component sits 10 units along +y, about 24 px to one side.
        sides = [self._pixel(centre + dx, centre) for dx in (-24, 24)]
        blue = max(sides, key=lambda pixel: pixel[2])
        self.assertGreater(blue[2], 2 * max(blue[0], blue[1]) + 40, sides)
        self._use_model(RED_CUBE)
        self.assertEqual(self.renderer.instanced_model_components(), [""])
        self.renderer.clear_instanced_model()
        self.assertEqual(self.renderer.instanced_model_components(), [])

    # --- layouts: each crane instance places named components with its own matrices
    BLUE_CUBE = ("blue", 0.5, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 1.0), False)

    def _use_kit(self):
        self.renderer.set_instanced_model(
            cube_glb([RED_CUBE, self.BLUE_CUBE], ["a", "b"]), UNITS_PER_METRE
        )

    def _layout(self, *items):
        names = [name for name, _matrix in items]
        values = [float(v) for _name, matrix in items for v in matrix]
        return self.renderer.scene.add_model_layout(names, values)

    def _place(self, layout, x=0.0, y=0.0, z=0.0, rotation=0.0, tint=None):
        r = self.r
        self.renderer.scene.add_model_instance(
            r.Vec3(x, y, z), rotation, tint or r.Color(0.0, 0.0, 0.0, 0.0), layout
        )

    def _instance_bounds(self):
        bounds = self.renderer.render_bounds()
        return (
            (bounds.min.x, bounds.min.y, bounds.min.z),
            (bounds.max.x, bounds.max.y, bounds.max.z),
        )

    def assertBounds(self, expected):
        got = self._instance_bounds()
        for got_corner, want_corner in zip(got, expected):
            for got_value, want_value in zip(got_corner, want_corner):
                self.assertAlmostEqual(got_value, want_value, places=3)

    def test_layout_matrices_place_components_exactly_like_the_reference(self):
        self._use_kit()
        quarter = _rotation_y(math.pi / 2)
        cases = {
            "identity": _IDENTITY,
            "translation": _translation(2.0, 3.0, 5.0),
            "rotation": quarter,
            "stretch": _scale(1.0, 6.0, 1.0),
            "rope": _multiply(
                _translation(1.0, 2.0, 0.5),
                _multiply(_rotation_z(0.6), _scale(0.2, 7.0, 0.2)),
            ),
        }
        for name, matrix in cases.items():
            for pose in ({}, {"x": 30.0, "y": -12.0, "z": 4.0, "rotation": 0.7}):
                with self.subTest(case=name, pose=pose):
                    self.renderer.scene.clear()
                    self._place(self._layout(("a", matrix)), **pose)
                    self.assertBounds(
                        reference_bounds([matrix], 0.5, UNITS_PER_METRE, **pose)
                    )

    def test_a_layout_draws_only_its_items_where_it_puts_them(self):
        self._use_kit()
        # "b" (blue) moves 1 m along glTF +Z: 10 units along scene +y, ~24 px aside.
        # "a" (red) is not in the layout, so the grey footing shows at the centre.
        self._place(self._layout(("b", _translation(0.0, 0.0, 1.0))))
        self._frame()
        centre = self.SIZE // 2
        middle = self._pixel(centre, centre)
        self.assertLess(abs(middle[0] - middle[2]), 8, middle)
        sides = [self._pixel(centre + dx, centre) for dx in (-24, 24)]
        blue = max(sides, key=lambda pixel: pixel[2])
        self.assertGreater(blue[2], 2 * max(blue[0], blue[1]) + 40, sides)
        self.assertEqual(self.renderer.pick(centre, centre), 0)

    def test_one_component_can_repeat_within_a_layout_and_across_instances(self):
        self._use_kit()
        pair = [_translation(0.0, 0.0, -1.0), _translation(0.0, 0.0, 1.0)]
        self.renderer.scene.clear()
        layout = self._layout(("a", pair[0]), ("a", pair[1]))
        self._place(layout)
        self.assertBounds(reference_bounds(pair, 0.5, UNITS_PER_METRE))
        # A second instance of the same layout, further up and turned.
        self._place(layout, z=40.0, rotation=1.1)
        low, high = reference_bounds(pair, 0.5, UNITS_PER_METRE)
        low_2, high_2 = reference_bounds(
            pair, 0.5, UNITS_PER_METRE, z=40.0, rotation=1.1
        )
        self.assertBounds(
            (
                tuple(min(a, b) for a, b in zip(low, low_2)),
                tuple(max(a, b) for a, b in zip(high, high_2)),
            )
        )
        self.renderer.scene.add_mesh(self._footing())
        self._frame()
        centre = self.SIZE // 2
        reds = [self._pixel(centre + dx, centre) for dx in (-24, 24)]
        for red in reds:
            self.assertGreater(red[0], 2 * max(red[1], red[2]) + 40, reds)
        middle = self._pixel(centre, centre)
        self.assertLess(abs(middle[0] - middle[2]), 8, middle)

    def test_a_stretched_component_draws_across_its_whole_length(self):
        self._use_kit()
        centre = self.SIZE // 2

        def red_at(dx):
            self._frame()
            pixel = self._pixel(centre + dx, centre)
            return pixel[0] > 2 * max(pixel[1], pixel[2]) + 40

        self._place(self._layout(("a", _IDENTITY)))
        self.assertFalse(red_at(40))
        self.renderer.scene.clear()
        self.renderer.scene.add_mesh(self._footing())
        # Six times longer along glTF Z (scene y): 30 units either side, ~72 px.
        self._place(self._layout(("a", _scale(1.0, 1.0, 6.0))))
        self.assertTrue(red_at(40))
        self.assertTrue(red_at(-40))

    def test_layout_instances_take_the_tint_and_the_visibility_switch(self):
        self._use_kit()
        self._place(
            self._layout(("a", _IDENTITY)), tint=self.r.Color(0.0, 1.0, 0.0, 1.0)
        )
        self._frame()
        centre = self.SIZE // 2
        green = self._pixel(centre, centre)
        self.assertGreater(green[1], 2 * max(green[0], green[2]) + 40, green)
        self.renderer.set_model_instances_visible(False)
        self._frame()
        grey = self._pixel(centre, centre)
        self.assertLess(abs(grey[0] - grey[2]), 8, grey)

    def test_a_rebuilt_scene_drops_the_previous_instances(self):
        self._use_kit()
        self._place(self._layout(("a", _IDENTITY)))
        self._frame()
        centre = self.SIZE // 2
        red = self._pixel(centre, centre)
        self.assertGreater(red[0], 2 * max(red[1], red[2]) + 40, red)
        self.renderer.scene.clear()
        self.renderer.scene.add_mesh(self._footing())
        self._frame()
        grey = self._pixel(centre, centre)
        self.assertLess(abs(grey[0] - grey[2]), 8, grey)
        # A layout naming a component the model lacks draws nothing and is harmless.
        self._place(self._layout(("missing", _IDENTITY)))
        self._frame()
        grey = self._pixel(centre, centre)
        self.assertLess(abs(grey[0] - grey[2]), 8, grey)

    def test_takeoff_meshes_keep_their_shape_after_instanced_draws(self):
        self._use_kit()
        self._place(self._layout(("b", _translation(0.0, 0.0, 1.0))))
        for _ in range(3):
            self._frame()
        centre = self.SIZE // 2
        # The grey footing (y and z from -5 to 5, about 9 px either side at its
        # depth) is still a small square at the centre, not collapsed or smeared.
        inside = self._pixel(centre, centre + 5)
        self.assertLess(abs(inside[0] - inside[2]), 8, inside)
        self.assertGreater(inside[0], 60, inside)
        self.assertEqual(self.renderer.pick(centre, centre + 5), 0)
        self.assertEqual(self.renderer.pick(centre, centre + 30), -1)

    # --- the shipped kit, laid out by Python
    def _kit_bounds(self, layout, kit, units, x=0.0, y=0.0, z=0.0, rotation=0.0):
        c, s = math.cos(rotation), math.sin(rotation)
        points = []
        for part, m in layout.items:
            box = kit["parts"][part]
            for corner in range(8):
                g = [
                    box["max"][k] if corner & (1 << k) else box["min"][k]
                    for k in range(3)
                ]
                px, py, pz = (
                    m[r * 4] * g[0]
                    + m[r * 4 + 1] * g[1]
                    + m[r * 4 + 2] * g[2]
                    + m[r * 4 + 3]
                    for r in range(3)
                )
                lx, ly, lz = -px * units, pz * units, py * units
                points.append((c * lx - s * ly + x, s * lx + c * ly + y, lz + z))
        return (
            tuple(min(p[k] for p in points) for k in range(3)),
            tuple(max(p[k] for p in points) for k in range(3)),
        )

    def test_the_shipped_kit_fills_exactly_the_bounds_the_python_layout_predicts(self):
        from ost_visualizer.domain.dtos.tower_crane_placement_dto import (
            INCHES_PER_METRE,
        )
        from ost_visualizer.domain.entities.tower_crane_spec import (
            resolve_tower_crane,
        )
        from ost_visualizer.presentation.visualization.assets.tower_crane_asset import (
            TOWER_CRANE_KIT_PARTS,
            read_tower_crane_kit,
        )
        from ost_visualizer.presentation.visualization.assets.tower_crane_layout import (
            shipped_tower_crane_kit,
            tower_crane_layout,
        )

        self.renderer.set_instanced_model(read_tower_crane_kit(), INCHES_PER_METRE)
        self.assertEqual(
            self.renderer.instanced_model_components(), list(TOWER_CRANE_KIT_PARTS)
        )
        kit = shipped_tower_crane_kit()
        cases = (
            ("[crane]", {}),
            ("[crane]", {"x": 300.0, "y": -120.0, "z": 48.0, "rotation": 0.9}),
            (
                "[crane mast=30 jib=24 counterjib=6 trolley=50% hook=40]",
                {"x": -50.0, "y": 75.0, "z": 12.0, "rotation": -2.2},
            ),
            ("[crane mast=1 jib=4 counterjib=2 hookheight=2]", {"rotation": 1.5}),
        )
        for notes, pose in cases:
            with self.subTest(notes=notes, pose=pose):
                layout = tower_crane_layout(resolve_tower_crane(notes).spec)
                self.renderer.scene.clear()
                index = self.renderer.scene.add_model_layout(
                    list(layout.parts), list(layout.flat_matrices)
                )
                self._place(index, **pose)
                expected = self._kit_bounds(layout, kit, INCHES_PER_METRE, **pose)
                got = self._instance_bounds()
                for got_corner, want_corner in zip(got, expected):
                    for got_value, want_value in zip(got_corner, want_corner):
                        # Part boxes in the metadata are rounded to 0.1 mm.
                        self.assertAlmostEqual(got_value, want_value, delta=0.05)

    def test_the_default_kit_crane_renders_with_edges_cuts_and_no_gl_error(self):
        import ctypes
        from ost_visualizer.domain.dtos.tower_crane_placement_dto import (
            INCHES_PER_METRE,
        )
        from ost_visualizer.domain.entities.tower_crane_spec import (
            DEFAULT_TOWER_CRANE_SPEC,
        )
        from ost_visualizer.presentation.visualization.assets.tower_crane_asset import (
            read_tower_crane_kit,
        )
        from ost_visualizer.presentation.visualization.assets.tower_crane_layout import (
            tower_crane_layout,
        )

        r = self.r
        self.renderer.set_instanced_model(read_tower_crane_kit(), INCHES_PER_METRE)
        layout = tower_crane_layout(DEFAULT_TOWER_CRANE_SPEC)
        index = self.renderer.scene.add_model_layout(
            list(layout.parts), list(layout.flat_matrices)
        )
        # The crane stands on the footing, far enough to see the mast at the centre.
        self._place(index, x=-35.0, z=5.0)
        self.renderer.camera.restore_state(
            r.Vec3(3000.0, 0.0, 800.0),
            r.Vec3(0.0, 0.0, 800.0),
            40.0,
            self.renderer.render_bounds(),
        )
        self.renderer.set_edges_visible(True)
        self.renderer.set_section_cut(0, True, 10000.0)
        self._frame()
        gl = ctypes.WinDLL("opengl32")
        self.assertEqual(gl.glGetError(), 0)
        centre = self.SIZE // 2
        column = [self._pixel(centre, y) for y in range(8, self.SIZE - 8, 4)]
        background = self._pixel(4, self.SIZE - 4)
        different = [
            p for p in column if sum(abs(a - b) for a, b in zip(p, background)) > 40
        ]
        # The mast crosses the middle column of the picture.
        self.assertGreater(len(different), 3, column)
        self.assertEqual(self.renderer.pick(centre, centre), -1)

    def test_a_bad_model_is_rejected_and_the_previous_one_kept(self):
        self._use_model(RED_CUBE)
        with self.assertRaises(ValueError):
            self.renderer.set_instanced_model(b"not a glb", UNITS_PER_METRE)
        self.assertTrue(self.renderer.has_instanced_model())
        self._add()
        self.renderer.scene.clear()
        self.assertEqual(self.renderer.scene.model_instance_count(), 0)
        self.renderer.clear_instanced_model()
        self.assertFalse(self.renderer.has_instanced_model())


if __name__ == "__main__":
    unittest.main()
