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
