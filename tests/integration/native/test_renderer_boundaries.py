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
