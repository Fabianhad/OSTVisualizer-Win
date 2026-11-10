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
