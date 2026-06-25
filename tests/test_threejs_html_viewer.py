import unittest
from ost_visualizer.presentation.visualization.renderers.threejs.threejs_renderer import (
    _generate_html,
)


class ThreejsHtmlViewerTests(unittest.TestCase):
    def test_viewer_uses_bounds_aware_dynamic_camera_clipping(self):
        scene_data = {
            "title": "Depth Test",
            "geometries": [],
            "camera": {
                "position": [0.0, 150.0, -100.0],
                "target": [0.0, 0.0, 0.0],
            },
            "bounds": {
                "min": [-50.0, -5.0, -50.0],
                "max": [50.0, 75.0, 50.0],
            },
            "pdf_base64": "JVBERi0xLjQ=",
            "page_width": 400.0,
            "page_height": 300.0,
        }
        html = _generate_html(scene_data, "Depth Test")
        self.assertIn("const pageW = Number(sceneData.page_width || 0)", html)
        self.assertIn("function getPagePlaneBox(pageWidth, pageHeight, modelBox)", html)
        self.assertIn(
            "function getSceneClippingBounds(bounds, pageWidth, pageHeight)", html
        )
        self.assertIn(
            "const pageBox = getPagePlaneBox(pageWidth, pageHeight, box)", html
        )
        self.assertIn("box.clone().union(pageBox)", html)
        self.assertIn(
            "const sceneClippingBounds = getSceneClippingBounds(sceneData.bounds, pageW, pageH)",
            html,
        )
        self.assertIn("function getSceneDepthRange()", html)
        self.assertIn("function updateCameraClipping(force = false)", html)
        self.assertIn("nearBox: nearBox", html)
        self.assertIn("depthCorners: getBoxCorners(depthBox)", html)
        self.assertIn(
            "sceneClippingBounds.nearBox.containsPoint(camera.position)", html
        )
        self.assertIn("cornersBehindCamera > 0", html)
        self.assertIn(
            "depthRange.nearest - sceneClippingBounds.depthPadding",
            html,
        )
        self.assertIn("controls.maxDistance", html)
        self.assertIn("updateCameraClipping(true)", html)
        self.assertNotIn("0.1, 100000", html)


if __name__ == "__main__":
    unittest.main()
