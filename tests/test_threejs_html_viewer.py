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
            "layers": [
                {"uid": "layer-a", "name": "Layer A", "visible": True, "sequence": 1}
            ],
            "page_image_layer": {"uid": "image", "name": "Image", "visible": True},
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

    def test_viewer_uses_layer_panel_visibility_wiring(self):
        scene_data = {
            "title": "Layer Test",
            "geometries": [],
            "camera": {
                "position": [0.0, 150.0, -100.0],
                "target": [0.0, 0.0, 0.0],
            },
            "bounds": {
                "min": [-50.0, -5.0, -50.0],
                "max": [50.0, 75.0, 50.0],
            },
            "layers": [
                {"uid": "layer-a", "name": "Layer A", "visible": True, "sequence": 1},
                {
                    "uid": "layer-b",
                    "name": "Layer B",
                    "visible": False,
                    "sequence": 2,
                },
            ],
            "conditions": [
                {"uid": "condition-a", "name": "Condition A", "visible": True},
            ],
            "areas": [
                {"uid": "area-a", "name": "Area A", "visible": True, "sequence": 1},
            ],
            "page_image_layer": {"uid": "image", "name": "Image", "visible": False},
        }
        html = _generate_html(scene_data, "Layer Test")
        self.assertIn('id="layer-panel"', html)
        self.assertIn('id="layer-list"', html)
        self.assertIn('id="layer-show-all"', html)
        self.assertIn("const layerVisibility = new Map()", html)
        self.assertIn("const conditionVisibility = new Map()", html)
        self.assertIn("const areaVisibility = new Map()", html)
        self.assertIn("function registerVisibilityObject(keys, object", html)
        self.assertIn("function setGroupVisible(registry, uid, visible)", html)
        self.assertIn("function setAllGroupsVisible(visible)", html)
        self.assertIn("renderVisibilitySection('Layers'", html)
        self.assertIn("renderVisibilitySection('Conditions'", html)
        self.assertIn("renderVisibilitySection('Areas'", html)
        self.assertIn("mesh.userData.takeoffUid = geomData.takeoff_uid", html)
        self.assertIn("object.userData.conditionUid = conditionUid", html)
        self.assertIn("object.userData.areaUid = areaUid", html)
        self.assertIn("registerVisibilityObject(", html)
        self.assertIn("sceneData.page_image_layer", html)
        self.assertIn("pageEntry.visible = layer.visible !== false", html)
        self.assertNotIn("pdf-toggle", html)
        self.assertNotIn("layer-swatch", html)

    def test_viewer_combines_layer_condition_and_area_visibility(self):
        html = _generate_html(
            {
                "title": "Visibility Test",
                "geometries": [],
                "camera": {
                    "position": [0.0, 150.0, -100.0],
                    "target": [0.0, 0.0, 0.0],
                },
                "bounds": {
                    "min": [-50.0, -5.0, -50.0],
                    "max": [50.0, 75.0, 50.0],
                },
            },
            "Visibility Test",
        )
        self.assertIn("function isObjectVisible(object)", html)
        self.assertIn("isGroupVisible(layerVisibility, object.userData.layerUid)", html)
        self.assertIn(
            "isGroupVisible(conditionVisibility, object.userData.conditionUid)",
            html,
        )
        self.assertIn("isGroupVisible(areaVisibility, object.userData.areaUid)", html)
        self.assertIn("if (!uid) return true", html)


if __name__ == "__main__":
    unittest.main()
