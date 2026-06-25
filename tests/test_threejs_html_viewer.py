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
                {
                    "uid": "condition-a",
                    "name": "Condition A",
                    "visible": True,
                    "cdn_type_uid": "type-a",
                    "cdn_type_name": "Concrete",
                    "color": "#336699",
                    "ref_no": 2,
                },
                {
                    "uid": "condition-b",
                    "name": "Condition B",
                    "visible": True,
                    "cdn_type_uid": "",
                    "cdn_type_name": "",
                    "color": "",
                    "ref_no": 1,
                },
            ],
            "areas": [
                {"uid": "area-a", "name": "Area A", "visible": True, "sequence": 1},
            ],
            "page_image_layer": {"uid": "image", "name": "Image", "visible": False},
            "page_2d": {
                "uid": "page-1",
                "width": 72.0,
                "height": 144.0,
                "image_layer_uid": "image",
                "visible": False,
            },
            "takeoffs_2d": [
                {
                    "takeoff_uid": "takeoff-a",
                    "condition_uid": "condition-a",
                    "area_uid": "area-a",
                    "layer_uid": "layer-a",
                    "name": "Condition A",
                    "visible": True,
                    "kind": "area",
                    "color": "#336699",
                    "opacity": 0.5,
                    "rings": [[[0.0, 0.0], [72.0, 0.0], [72.0, 72.0]]],
                    "is_negative": False,
                }
            ],
        }
        html = _generate_html(scene_data, "Layer Test")
        self.assertIn('id="view-mode-switch"', html)
        self.assertIn('id="view-mode-plan"', html)
        self.assertIn('id="view-mode-3d"', html)
        self.assertIn('id="plan-view"', html)
        self.assertIn('id="plan-content"', html)
        self.assertIn('id="plan-pdf-canvas"', html)
        self.assertIn('id="plan-overlay"', html)
        self.assertIn('id="layer-panel"', html)
        self.assertIn('id="layer-list"', html)
        self.assertIn('id="layer-show-all"', html)
        self.assertIn("const layerVisibility = new Map()", html)
        self.assertIn("const conditionVisibility = new Map()", html)
        self.assertIn("const areaVisibility = new Map()", html)
        self.assertIn("function registerVisibilityObject(keys, object", html)
        self.assertIn("function setGroupVisible(registry, uid, visible)", html)
        self.assertIn("function setAllGroupsVisible(visible)", html)
        self.assertIn("function setRenderedObjectVisible(object, visible)", html)
        self.assertIn("function createVisibilityRow(entry, registry, rows", html)
        self.assertIn("renderVisibilitySection('Layers'", html)
        self.assertIn("function renderConditionSection()", html)
        self.assertIn("getConditionTypeUid(condition)", html)
        self.assertIn("getConditionTypeName(condition)", html)
        self.assertIn("const UNASSIGNED_CDN_TYPE_NAME = '(unassigned)'", html)
        self.assertIn("const IMAGE_LAYER_DISPLAY_NAME = 'Image'", html)
        self.assertIn("renderVisibilitySection('Areas'", html)
        self.assertIn("setGroupVisible(registry, entry.uid", html)
        self.assertIn("function compareConditionEntries(a, b)", html)
        self.assertIn(".sort(compareConditionEntries)", html)
        self.assertIn("mesh.userData.takeoffUid = geomData.takeoff_uid", html)
        self.assertIn("object.userData.conditionUid = conditionUid", html)
        self.assertIn("object.userData.areaUid = areaUid", html)
        self.assertIn("registerVisibilityObject(", html)
        self.assertIn("const page2D = sceneData.page_2d || null", html)
        self.assertIn("const takeoffs2D = Array.isArray(sceneData.takeoffs_2d)", html)
        self.assertIn("function fitPlanToViewport(force = false)", html)
        self.assertIn("function renderPlanTakeoffs()", html)
        self.assertIn("function setupPlanView(pdfCanvas = null)", html)
        self.assertIn("planView.addEventListener('wheel'", html)
        self.assertIn("planView.addEventListener('pointerdown'", html)
        self.assertIn("setViewMode('plan')", html)
        self.assertIn("controls.enabled = !usePlan", html)
        self.assertIn(
            "document.createElementNS('http://www.w3.org/2000/svg', 'path')", html
        )
        self.assertIn("layerUid: takeoff.layer_uid", html)
        self.assertIn("conditionUid: takeoff.condition_uid", html)
        self.assertIn("areaUid: takeoff.area_uid", html)
        self.assertIn("sceneData.page_image_layer", html)
        self.assertIn("pageEntry.visible = layer.visible !== false", html)
        self.assertNotIn("pdf-toggle", html)
        self.assertNotIn("layer-swatch", html)
        self.assertIn("condition-color-swatch", html)
        self.assertIn(
            "section.appendChild(createVisibilityRow(entry, registry, rows))", html
        )
        self.assertIn("swatchClass: 'condition-color-swatch'", html)

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
