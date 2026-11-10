"""Real ost_renderer checks for section cuts. They need a native Windows GL window,
so they skip under the offscreen Qt platform the normal test runs use."""

import unittest
from PySide6 import QtCore, QtGui, QtWidgets


def _box(low, high):
    (x0, y0, z0), (x1, y1, z1) = low, high
    vertices = [
        x0,
        y0,
        z0,
        x1,
        y0,
        z0,
        x1,
        y1,
        z0,
        x0,
        y1,
        z0,
        x0,
        y0,
        z1,
        x1,
        y0,
        z1,
        x1,
        y1,
        z1,
        x0,
        y1,
        z1,
    ]
    faces = [
        0,
        1,
        2,
        0,
        2,
        3,
        4,
        6,
        5,
        4,
        7,
        6,
        0,
        4,
        5,
        0,
        5,
        1,
        1,
        5,
        6,
        1,
        6,
        2,
        2,
        6,
        7,
        2,
        7,
        3,
        3,
        7,
        4,
        3,
        4,
        0,
    ]
    return vertices, faces


class NativeSectionCutTests(unittest.TestCase):
    SIZE = 64

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        if QtGui.QGuiApplication.platformName() != "windows":
            raise unittest.SkipTest("needs the native Windows Qt platform for OpenGL")
        from ost_visualizer.presentation.components import ost_renderer

        cls.ost_renderer = ost_renderer

    def setUp(self):
        r = self.ost_renderer
        self.widget = QtWidgets.QWidget()
        self.widget.setAttribute(QtCore.Qt.WA_NativeWindow)
        self.widget.setAttribute(QtCore.Qt.WA_PaintOnScreen)
        self.widget.resize(self.SIZE, self.SIZE)
        self.widget.show()
        self.app.processEvents()
        self.renderer = r.Renderer(int(self.widget.winId()))
        self.renderer.resize(self.SIZE, self.SIZE)
        # Box 0 at x 0..10, box 1 at x 20..30, both seen end-on from +x.
        for low, high in (((0, -5, -5), (10, 5, 5)), ((20, -5, -5), (30, 5, 5))):
            vertices, faces = _box(low, high)
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

    def _center_pick(self):
        self.renderer.render()
        return self.renderer.pick(self.SIZE // 2, self.SIZE // 2)

    def test_picking_ignores_the_removed_side_of_a_cut(self):
        self.assertEqual(self._center_pick(), 1)
        self.renderer.set_section_cut(0, True, 15.0)
        self.assertTrue(self.renderer.section_cut_enabled(0))
        self.assertEqual(self.renderer.section_cut_position(0), 15.0)
        self.assertEqual(self._center_pick(), 0)
        self.renderer.set_section_cut(0, False, 0.0)
        self.assertFalse(self.renderer.section_cut_enabled(0))
        self.assertEqual(self._center_pick(), 1)

    def test_a_cut_through_a_solid_keeps_it_pickable_with_edges_on(self):
        self.renderer.set_edges_visible(True)
        self.renderer.set_section_cut(0, True, 5.0)
        self.assertEqual(self._center_pick(), 0)
        self.renderer.set_section_cut(1, True, 100.0)
        self.assertEqual(self._center_pick(), 0)
        self.renderer.set_section_cut(0, True, -1.0)
        self.assertEqual(self._center_pick(), -1)

    def _read_pixel(self, x, y):
        import ctypes

        gl = ctypes.WinDLL("opengl32")
        data = (ctypes.c_ubyte * 4)()
        gl.glReadBuffer(0x0404)  # GL_FRONT: the frame render() just presented
        gl.glReadPixels(x, y, 1, 1, 0x1908, 0x1401, data)  # GL_RGBA, GL_UNSIGNED_BYTE
        return tuple(data)

    def test_cap_has_a_hole_where_the_solid_has_a_cavity_and_open_meshes_are_skipped(
        self,
    ):
        r = self.ost_renderer
        self.renderer.scene.clear()
        size = 128
        self.widget.resize(size, size)
        self.app.processEvents()
        self.renderer.resize(size, size)
        outer_vertices, outer_faces = _box((0, -5, -5), (10, 5, 5))
        inner_vertices, inner_faces = _box((2, -2, -2), (8, 2, 2))
        solid = r.MeshData()
        solid.set_vertices([float(v) for v in outer_vertices + inner_vertices])
        solid.indices = outer_faces + [index + 8 for index in inner_faces]
        solid.color = r.Color(0.5, 0.5, 0.5, 1.0)
        self.renderer.scene.add_mesh(solid)
        # An open mesh (one quad) beside it must not break cap building.
        sheet = r.MeshData()
        sheet.set_vertices(
            [0.0, 20.0, 0.0, 10.0, 20.0, 0.0, 10.0, 30.0, 0.0, 0.0, 30.0, 0.0]
        )
        sheet.indices = [0, 1, 2, 0, 2, 3]
        sheet.color = r.Color(0.5, 0.5, 0.5, 1.0)
        self.renderer.scene.add_mesh(sheet)
        self.renderer.camera.restore_state(
            r.Vec3(100.0, 0.0, 0.0),
            r.Vec3(0.0, 0.0, 0.0),
            30.0,
            self.renderer.scene.get_bounds(),
        )
        self.renderer.set_section_cut(0, True, 5.0)
        self.renderer.render()
        self.renderer.render()
        centre = size // 2
        hole = self._read_pixel(centre, centre)
        ring = self._read_pixel(centre + 8, centre)
        self.assertEqual(self.renderer.pick(centre + 8, centre), 0)
        # Faces without normals are lit as +Z (about 129 for grey 0.5); the cap faces
        # +x and is 0.86 darker (about 89). The hole shows the cavity wall behind it.
        self.assertTrue(60 < ring[0] < 100, ring)
        self.assertGreater(hole[0], 115, hole)

    def test_invalid_cut_axis_is_rejected(self):
        with self.assertRaises(ValueError):
            self.renderer.set_section_cut(2, True, 0.0)
        self.renderer.set_section_cut(1, True, float("nan"))
        self.assertFalse(self.renderer.section_cut_enabled(1))


if __name__ == "__main__":
    unittest.main()
