import json
import unittest
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.presentation.visualization.renderers.threejs.threejs_renderer import (
    _generate_html,
)


class ThreejsHtmlViewerTests(unittest.TestCase):
    def test_html_generation_escapes_title_and_script_terminators(self):
        injected_text = "</script><script>window.injected=true</script>"
        scene_data = {
            "title": injected_text,
            "geometries": [],
            "camera": {"position": [0.0, 0.0, 1.0], "target": [0.0, 0.0, 0.0]},
            "bounds": {
                "min": [0.0, 0.0, 0.0],
                "max": [1.0, 1.0, 1.0],
            },
        }

        rendered_html = _generate_html(scene_data, f"Bid & {injected_text}")

        self.assertIn(
            "<title>Bid &amp; &lt;/script&gt;&lt;script&gt;"
            "window.injected=true&lt;/script&gt;</title>",
            rendered_html,
        )
        self.assertNotIn(injected_text, rendered_html)
        encoded_scene = (
            rendered_html.split('<script type="application/json" id="scene-data">', 1)[
                1
            ]
            .split("</script>", 1)[0]
            .strip()
        )
        self.assertEqual(json.loads(encoded_scene), scene_data)

    def test_viewer_renders_elevation_callouts_in_plan_svg_only(self):
        scene_data = {
            "title": "Elevation Callout Test",
            "geometries": [],
            "camera": {
                "position": [0.0, 150.0, -100.0],
                "target": [0.0, 0.0, 0.0],
            },
            "bounds": {
                "min": [-50.0, -5.0, -50.0],
                "max": [50.0, 75.0, 50.0],
            },
            "elevation_callouts": [
                {
                    "page_uid": "page-1",
                    "condition_uid": "condition-1",
                    "area_uid": "area-1",
                    "layer_uid": "layer-1",
                    "x": 30.0,
                    "y": 40.0,
                    "lines": ["F9", "410' - 3\"", "406' - 3\"", "6.43 CY"],
                    "color": "#123456",
                }
            ],
        }
        html = _generate_html(scene_data, "Elevation Callout Test")
        self.assertIn('"elevation_callouts":[', html)
        self.assertIn(
            '"lines":["F9","410\' - 3\\"","406\' - 3\\"","6.43 CY"]',
            html,
        )
        self.assertIn(
            "const elevationCallouts = Array.isArray(sceneData.elevation_callouts)",
            html,
        )
        self.assertIn("function renderPlanElevationCallouts(page)", html)
        self.assertIn('const group = createPlanSvgElement("g")', html)
        self.assertIn("function createPlanCalloutText(value, y)", html)
        self.assertIn("const ELEVATION_CALLOUT_LINE_SPACING = 12", html)
        self.assertIn("const lines = callout.lines", html)
        self.assertIn("group.style.color = callout.color", html)
        self.assertIn('"color":"#123456"', html)
        self.assertIn("...lines.map", html)
        self.assertRegex(html, r"createPlanCalloutText\(\s*line,")
        self.assertIn("index * ELEVATION_CALLOUT_LINE_SPACING", html)
        self.assertIn("planOverlay.appendChild(group)", html)
        self.assertIn("usesPage3dVisibility: false", html)
        self.assertIn("layerUid: callout.layer_uid", html)
        self.assertIn("conditionUid: callout.condition_uid", html)
        self.assertIn("areaUid: callout.area_uid", html)
        self.assertIn(".elevation-callout", html)
        self.assertIn("font-family: Arial, sans-serif", html)
        self.assertIn("stroke: none", html)
        self.assertIn("pointer-events: none", html)
        self.assertNotIn("color: #111827", html)
        self.assertIn("body:not(.plan-mode) #plan-view", html)
        self.assertNotIn("Plotly", html)
        self.assertNotIn("CSS2DRenderer", html)
        self.assertNotIn('createPlanSvgElement("circle")', html)
        self.assertNotIn('createPlanSvgElement("line")', html)
        for obsolete_field in (
            "condition_label",
            "top_label",
            "bottom_label",
            "quantity_label",
            "callout.takeoff_uid",
            "callout.visible",
        ):
            self.assertNotIn(obsolete_field, html)
        self.assertNotIn("Array.isArray(callout.lines)", html)
        self.assertNotIn(
            "normalizeOptionalUid(callout.page_uid) || page.uid",
            html,
        )

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
            "pages": [
                {
                    "uid": "page-1",
                    "label": "1 - A1",
                    "width": 72.0,
                    "height": 144.0,
                    "page_width": 400.0,
                    "page_height": 300.0,
                    "image_layer_uid": "image",
                    "visible": True,
                    "pdf_document_uid": "pdf-1",
                    "pdf_page_index": 0,
                }
            ],
            "active_page_uid": "page-1",
            "selected_page_uids": ["page-1"],
            "pdf_documents": [{"uid": "pdf-1", "data_base64": "JVBERi0xLjQ="}],
            "layers": [
                {"uid": "layer-a", "name": "Layer A", "visible": True, "sequence": 1}
            ],
            "page_image_layer": {"uid": "image", "name": "Image", "visible": True},
        }
        html = _generate_html(scene_data, "Depth Test")
        self.assertIn("const maxPageW = runtimePages.reduce", html)
        self.assertIn("const maxPageH = runtimePages.reduce", html)
        self.assertIn("function getPagePlaneBox(pageWidth, pageHeight, modelBox)", html)
        self.assertIn(
            "function getSceneClippingBounds(bounds, pageWidth, pageHeight)", html
        )
        self.assertIn(
            "const pageBox = getPagePlaneBox(pageWidth, pageHeight, box)", html
        )
        self.assertIn("box.clone().union(pageBox)", html)
        self.assertIn("const sceneClippingBounds = getSceneClippingBounds(", html)
        self.assertIn("sceneData.bounds,", html)
        self.assertIn("maxPageW,", html)
        self.assertIn("maxPageH,", html)
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
            "pages": [
                {
                    "uid": "page-1",
                    "label": "1 - A1",
                    "width": 72.0,
                    "height": 144.0,
                    "page_width": 1.0,
                    "page_height": 2.0,
                    "image_layer_uid": "image",
                    "visible": True,
                    "pdf_document_uid": "",
                    "pdf_page_index": 0,
                },
                {
                    "uid": "page-2",
                    "label": "2 - A2",
                    "width": 72.0,
                    "height": 144.0,
                    "page_width": 1.0,
                    "page_height": 2.0,
                    "image_layer_uid": "image",
                    "visible": True,
                    "pdf_document_uid": "",
                    "pdf_page_index": 0,
                },
            ],
            "active_page_uid": "page-1",
            "selected_page_uids": ["page-1", "page-2"],
            "takeoffs_2d": [
                {
                    "takeoff_uid": "takeoff-a",
                    "page_uid": "page-1",
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
        self.assertIn('id="page-combo"', html)
        self.assertIn('id="page-combo-button"', html)
        self.assertIn('id="page-combo-menu"', html)
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
        self.assertIn("const page3dVisibility = new Map()", html)
        self.assertIn("function normalizeScenePages()", html)
        self.assertIn("function buildPdfDocumentMap()", html)
        self.assertIn("const runtimePages = normalizeScenePages()", html)
        self.assertIn("let activePageUid = resolveActivePageUid(runtimePages)", html)
        self.assertIn("function registerVisibilityObject(keys, object", html)
        self.assertIn("object.userData.usesPage3dVisibility", html)
        self.assertIn("function setGroupVisible(registry, uid, visible)", html)
        self.assertIn("function setAllGroupsVisible(visible)", html)
        self.assertIn("function setRenderedObjectVisible(object, visible)", html)
        self.assertIn("function createVisibilityRow(entry, registry, rows", html)
        self.assertIn("function buildPageCombo()", html)
        self.assertIn("function setPage3dVisible(pageUid, visible)", html)
        self.assertIn('checkbox.addEventListener("change"', html)
        self.assertIn('name.addEventListener("click"', html)
        self.assertNotIn('renderVisibilitySection("Pages"', html)
        self.assertIn('renderVisibilitySection("Layers"', html)
        self.assertIn("function renderConditionSection()", html)
        self.assertIn("getConditionTypeUid(condition)", html)
        self.assertIn("getConditionTypeName(condition)", html)
        self.assertIn('const UNASSIGNED_CDN_TYPE_NAME = "(unassigned)"', html)
        self.assertIn('const IMAGE_LAYER_DISPLAY_NAME = "Image"', html)
        self.assertIn('renderVisibilitySection("Areas"', html)
        self.assertIn("setGroupVisible(registry, entry.uid", html)
        self.assertIn("function compareConditionEntries(a, b)", html)
        self.assertIn(".sort(compareConditionEntries)", html)
        self.assertIn("mesh.userData.takeoffUid = geomData.takeoff_uid", html)
        self.assertIn("object.userData.pageUid = pageUid", html)
        self.assertIn("object.userData.conditionUid = conditionUid", html)
        self.assertIn("object.userData.areaUid = areaUid", html)
        self.assertIn("registerVisibilityObject(", html)
        self.assertNotIn("const legacyPage = sceneData.page_2d || null", html)
        self.assertNotIn("sceneData.pdf_base64", html)
        self.assertIn("const takeoffs2D = Array.isArray(sceneData.takeoffs_2d)", html)
        self.assertIn("function fitPlanToViewport(force = false)", html)
        self.assertIn("function renderPlanTakeoffs()", html)
        self.assertIn("function setupPlanView(pdfCanvas = null, forceFit = true)", html)
        self.assertIn("function setActivePlanPage(pageUid)", html)
        self.assertIn("function updatePdfPlaneForActivePage()", html)
        self.assertIn('pageComboButton.addEventListener("click"', html)
        self.assertIn("planView.addEventListener(", html)
        self.assertIn('"wheel",', html)
        self.assertIn('planView.addEventListener("pointerdown"', html)
        self.assertIn('setViewMode("plan")', html)
        self.assertIn("controls.enabled = !usePlan", html)
        self.assertIn("document.createElementNS(", html)
        self.assertIn('"http://www.w3.org/2000/svg"', html)
        self.assertIn('"path"', html)
        self.assertIn("layerUid: takeoff.layer_uid", html)
        self.assertIn("pageUid: takeoffPageUid", html)
        self.assertIn("usesPage3dVisibility: false", html)
        self.assertIn("conditionUid: takeoff.condition_uid", html)
        self.assertIn("areaUid: takeoff.area_uid", html)
        self.assertIn("sceneData.page_image_layer", html)
        self.assertIn("pageEntry.visible = layer.visible !== false", html)
        self.assertIn("usesPage3dVisibility: true", html)
        self.assertIn("pdfPlane.userData.usesPage3dVisibility = false", html)
        self.assertIn("pdfPlane.userData.baseVisible = true", html)
        self.assertIn("planPdfCanvas.userData.usesPage3dVisibility = false", html)
        self.assertNotIn("pdf-toggle", html)
        self.assertNotIn("layer-swatch", html)
        self.assertIn("condition-color-swatch", html)
        self.assertIn(
            "section.appendChild(createVisibilityRow(entry, registry, rows))", html
        )
        self.assertIn('swatchClass: "condition-color-swatch"', html)

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
        self.assertIn("object.userData.usesPage3dVisibility !== true", html)
        self.assertIn("isGroupVisible(page3dVisibility, object.userData.pageUid)", html)
        self.assertIn("isGroupVisible(layerVisibility, object.userData.layerUid)", html)
        self.assertIn(
            "isGroupVisible(conditionVisibility, object.userData.conditionUid)",
            html,
        )
        self.assertIn("isGroupVisible(areaVisibility, object.userData.areaUid)", html)
        self.assertIn("if (!uid) return true", html)

    def test_wboit_transparent_mesh_render_respects_visibility_filters(self):
        html = _generate_html(
            {
                "title": "Transparent Visibility Test",
                "geometries": [
                    {
                        "vertices": [0, 0, 0, 1, 0, 0, 0, 1, 0],
                        "normals": [0, 1, 0, 0, 1, 0, 0, 1, 0],
                        "indices": [0, 1, 2],
                        "color": [0.3, 0.4, 0.5],
                        "opacity": 0.5,
                        "name": "Transparent Mesh",
                        "visible": True,
                        "takeoff_uid": "takeoff-1",
                        "page_uid": "page-1",
                        "condition_uid": "condition-1",
                        "area_uid": "area-1",
                        "layer_uid": "layer-1",
                    }
                ],
                "camera": {
                    "position": [0.0, 150.0, -100.0],
                    "target": [0.0, 0.0, 0.0],
                },
                "bounds": {
                    "min": [-50.0, -5.0, -50.0],
                    "max": [50.0, 75.0, 50.0],
                },
            },
            "Transparent Visibility Test",
        )
        self.assertIn("const wboitPass = hasTransparent", html)
        self.assertIn("function renderWboitPassWithVisibility()", html)
        self.assertIn("if (object.material && object.visible === false)", html)
        self.assertIn("object.material = null", html)
        self.assertIn("wboitPass.render(renderer)", html)
        self.assertIn("entry.object.material = entry.material", html)
        self.assertIn("renderWboitPassWithVisibility()", html)
        self.assertIn("usesPage3dVisibility: true", html)

    def test_scene_json_includes_split_display_modes(self):
        html = _generate_html(
            {
                "title": "Display Mode Test",
                "geometries": [],
                "camera": {
                    "position": [0.0, 150.0, -100.0],
                    "target": [0.0, 0.0, 0.0],
                },
                "bounds": {
                    "min": [-50.0, -5.0, -50.0],
                    "max": [50.0, 75.0, 50.0],
                },
                "display_modes": {
                    "synced": False,
                    "mode_3d": Config.DISPLAY_MODE_SOLID,
                    "mode_2d": Config.DISPLAY_MODE_TRANSPARENT,
                },
            },
            "Display Mode Test",
        )
        self.assertIn('"display_modes":', html)
        self.assertIn(f'"mode_3d":"{Config.DISPLAY_MODE_SOLID}"', html)
        self.assertIn(f'"mode_2d":"{Config.DISPLAY_MODE_TRANSPARENT}"', html)

    def test_wboit_detection_uses_3d_geometry_opacity_only(self):
        html = _generate_html(
            {
                "title": "2D Transparent Only Test",
                "geometries": [
                    {
                        "vertices": [0, 0, 0, 1, 0, 0, 0, 1, 0],
                        "normals": [0, 1, 0, 0, 1, 0, 0, 1, 0],
                        "indices": [0, 1, 2],
                        "color": [0.3, 0.4, 0.5],
                        "opacity": 1.0,
                        "name": "Solid Mesh",
                        "visible": True,
                        "takeoff_uid": "takeoff-1",
                        "page_uid": "page-1",
                        "condition_uid": "condition-1",
                        "area_uid": "area-1",
                        "layer_uid": "layer-1",
                    }
                ],
                "camera": {
                    "position": [0.0, 150.0, -100.0],
                    "target": [0.0, 0.0, 0.0],
                },
                "bounds": {
                    "min": [-50.0, -5.0, -50.0],
                    "max": [50.0, 75.0, 50.0],
                },
                "takeoffs_2d": [
                    {
                        "takeoff_uid": "takeoff-a",
                        "page_uid": "page-1",
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
            },
            "2D Transparent Only Test",
        )
        self.assertIn("sceneData.geometries.forEach((geomData) => {", html)
        self.assertIn("if (geomData.opacity < 1.0) hasTransparent = true", html)


if __name__ == "__main__":
    unittest.main()
