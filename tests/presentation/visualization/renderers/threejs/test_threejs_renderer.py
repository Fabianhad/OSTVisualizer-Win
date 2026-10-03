import json
import re
import shutil
import subprocess
import unittest
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.presentation.visualization.renderers.threejs.threejs_renderer import (
    _generate_html,
)
import copy
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import create_autospec, patch
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.presentation.visualization.renderers.threejs.adapters.threejs_mesh_adapter import (
    ThreejsMeshAdapter,
)
from ost_visualizer.presentation.visualization.renderers.threejs.threejs_renderer import (
    _build_multi_page_data,
    visualize_with_threejs,
)
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)
from tests.presentation.visualization.renderers.threejs.export_support import (
    _TakeoffService as _export_support__TakeoffService,
    _takeoff_2d_entry as _export_support__takeoff_2d_entry,
)


def _embedded_scene(rendered_html):
    encoded_scene = (
        rendered_html.split('<script type="application/json" id="scene-data">', 1)[1]
        .split("</script>", 1)[0]
        .strip()
    )
    return json.loads(encoded_scene)


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

    def test_html_generation_does_not_expand_template_placeholders_in_user_text(self):
        placeholder_title = "Bid {{SCENE_DATA}} {{TITLE}}"
        scene_data = {
            "title": "Scene {{TITLE}} {{SCENE_DATA}}",
            "geometries": [],
            "camera": {"position": [0.0, 0.0, 1.0], "target": [0.0, 0.0, 0.0]},
            "bounds": {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
        }
        rendered_html = _generate_html(scene_data, placeholder_title)
        self.assertIn(f"<title>{placeholder_title}</title>", rendered_html)
        encoded_scene = (
            rendered_html.split('<script type="application/json" id="scene-data">', 1)[
                1
            ]
            .split("</script>", 1)[0]
            .strip()
        )
        self.assertEqual(json.loads(encoded_scene), scene_data)
        # The scene appears once, in its data block, and nowhere in the title.
        self.assertEqual(rendered_html.count('"geometries":[]'), 1)

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
        self.assertEqual(
            _embedded_scene(html)["elevation_callouts"],
            scene_data["elevation_callouts"],
        )
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
        self.assertEqual(
            _embedded_scene(html)["display_modes"],
            {
                "synced": False,
                "mode_3d": Config.DISPLAY_MODE_SOLID,
                "mode_2d": Config.DISPLAY_MODE_TRANSPARENT,
            },
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
        # Transparency is decided only here; 2D takeoff opacity never enables
        # the weighted-blended OIT pass.
        self.assertEqual(html.count("hasTransparent = true"), 1)
        self.assertEqual(html.count("let hasTransparent = false"), 1)


class ThreejsExportLayerTests(unittest.TestCase):
    def test_html_scene_adds_callouts_without_changing_3d_geometry_data(self):
        condition = Condition(
            uid="condition-1",
            name="Footing @T 10' 0\"",
            condition_type=Condition.TYPE_AREA,
            thickness=24.0,
            z_value=120.0,
            is_top=True,
        )
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-1",
        )
        takeoff_entry = _export_support__takeoff_2d_entry(
            condition,
            [[[10.0, 20.0], [50.0, 20.0], [50.0, 60.0]]],
        )
        callout_entry = {
            "page_uid": "page-1",
            "condition_uid": "condition-1",
            "area_uid": "",
            "layer_uid": "layer-1",
            "x": 30.0,
            "y": 40.0,
            "lines": ["Footing", "10' - 0\"", "8' - 0\"", "5.14 CY"],
            "color": "#ff0000",
        }
        geometry_payload = [{"existing_3d_geometry": True}]
        base_scene = {
            "title": "Elevation Scene",
            "geometries": geometry_payload,
            "camera": {"position": [0.0, 0.0, 1.0], "target": [0.0, 0.0, 0.0]},
            "bounds": {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
        }
        captured_scene = {}

        def capture_scene(scene_data, _title):
            captured_scene.update(copy.deepcopy(scene_data))
            return "<html></html>"

        renderer_module = (
            "ost_visualizer.presentation.visualization.renderers.threejs."
            "threejs_renderer"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = str(Path(tmpdir) / "scene.html")
            with ExitStack() as stack:
                stack.enter_context(
                    patch(
                        f"{renderer_module}.process_meshes_for_threejs",
                        return_value=(
                            [
                                (
                                    MeshData(
                                        vertices=[(0.0, 0.0, 0.0)],
                                        faces=[(0, 0, 0)],
                                    ),
                                    {"page_uid": "page-1"},
                                )
                            ],
                            (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
                        ),
                    )
                )
                stack.enter_context(
                    patch.object(
                        ThreejsMeshAdapter,
                        "build_scene_data",
                        return_value=copy.deepcopy(base_scene),
                    )
                )
                build_multi_page_data = stack.enter_context(
                    patch(
                        f"{renderer_module}._build_multi_page_data",
                        return_value=(
                            [{"uid": "page-1"}],
                            [],
                            [takeoff_entry],
                            [callout_entry],
                        ),
                    )
                )
                stack.enter_context(
                    patch(
                        f"{renderer_module}._generate_html",
                        side_effect=capture_scene,
                    )
                )
                browser_open = stack.enter_context(
                    patch(f"{renderer_module}.webbrowser.open")
                )
                result = visualize_with_threejs(
                    {"condition-1": condition},
                    [takeoff],
                    object(),
                    ColorService(),
                    _export_support__TakeoffService(),
                    output_path=output_path,
                    auto_open=True,
                    pages=[],
                    inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                    include_elevation_callouts=True,
                )
            written_html = Path(output_path).read_text(encoding="utf-8")
        self.assertEqual(result, output_path)
        browser_open.assert_called_once_with(Path(output_path).resolve().as_uri())
        self.assertEqual(captured_scene["geometries"], geometry_payload)
        self.assertEqual(captured_scene["takeoffs_2d"], [takeoff_entry])
        self.assertEqual(captured_scene["elevation_callouts"], [callout_entry])
        self.assertEqual(captured_scene["pages"], [{"uid": "page-1"}])
        self.assertEqual(captured_scene["selected_page_uids"], ["page-1"])
        self.assertEqual(captured_scene["active_page_uid"], "page-1")
        self.assertEqual(
            captured_scene["display_modes"],
            {
                "synced": True,
                "mode_3d": Config.DISPLAY_MODE_SOLID,
                "mode_2d": Config.DISPLAY_MODE_SOLID,
            },
        )
        self.assertNotIn("pdf_documents", captured_scene)
        build_kwargs = build_multi_page_data.call_args.kwargs
        self.assertTrue(build_kwargs["include_elevation_callouts"])
        self.assertEqual(build_kwargs["page_floor_elevations"], {"page-1": 0.0})
        self.assertEqual(
            build_kwargs["elevation_callout_color"],
            Config.DEFAULT_ELEVATION_CALLOUT_COLOR,
        )
        self.assertEqual(written_html, "<html></html>")

    def test_html_scene_omits_callout_data_and_resolution_when_disabled(self):
        condition = Condition(
            uid="condition-1",
            name="Footing @T 10' 0\"",
            condition_type=Condition.TYPE_AREA,
            thickness=24.0,
            z_value=120.0,
            is_top=True,
        )
        takeoff = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-1",
        )
        takeoff_entry = _export_support__takeoff_2d_entry(
            condition,
            [[[10.0, 20.0], [50.0, 20.0], [50.0, 60.0]]],
        )
        captured_scene = {}

        def capture_scene(scene_data, _title):
            captured_scene.update(copy.deepcopy(scene_data))
            return "<html></html>"

        renderer_module = (
            "ost_visualizer.presentation.visualization.renderers.threejs."
            "threejs_renderer"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                stack.enter_context(
                    patch(
                        f"{renderer_module}.process_meshes_for_threejs",
                        return_value=(
                            [
                                (
                                    MeshData(
                                        vertices=[(0.0, 0.0, 0.0)],
                                        faces=[(0, 0, 0)],
                                    ),
                                    {"page_uid": "page-1"},
                                )
                            ],
                            (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
                        ),
                    )
                )
                stack.enter_context(
                    patch.object(
                        ThreejsMeshAdapter,
                        "build_scene_data",
                        return_value={
                            "title": "Elevation Scene",
                            "geometries": [],
                            "camera": {
                                "position": [0.0, 0.0, 1.0],
                                "target": [0.0, 0.0, 0.0],
                            },
                            "bounds": {
                                "min": [0.0, 0.0, 0.0],
                                "max": [1.0, 1.0, 1.0],
                            },
                        },
                    )
                )
                build_multi_page_data = stack.enter_context(
                    patch(
                        f"{renderer_module}._build_multi_page_data",
                        return_value=([{"uid": "page-1"}], [], [takeoff_entry], []),
                    )
                )
                stack.enter_context(
                    patch(
                        f"{renderer_module}._generate_html", side_effect=capture_scene
                    )
                )
                visualize_with_threejs(
                    {"condition-1": condition},
                    [takeoff],
                    object(),
                    ColorService(),
                    _export_support__TakeoffService(),
                    output_path=str(Path(tmpdir) / "scene.html"),
                    auto_open=False,
                    pages=[],
                    inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                    include_elevation_callouts=False,
                )
        self.assertFalse(
            build_multi_page_data.call_args.kwargs["include_elevation_callouts"]
        )
        self.assertEqual(
            build_multi_page_data.call_args.kwargs["page_floor_elevations"],
            {"page-1": 0.0},
        )
        self.assertNotIn("elevation_callouts", captured_scene)


_RENDERER_MODULE = (
    "ost_visualizer.presentation.visualization.renderers.threejs.threejs_renderer"
)


class VisualizeWithThreejsPipelineTests(unittest.TestCase):
    """Orchestration of visualize_with_threejs with its stages replaced.
    Mesh processing, the scene adapter, page assembly and HTML rendering are
    patched (the native tessellation/Manifold stages are not exercised here);
    the tests pin what the orchestrator forwards, includes and omits.
    """

    def setUp(self):
        self.condition = Condition(
            uid="condition-1", condition_type=Condition.TYPE_AREA, color_fill=0x336699
        )
        self.takeoff = Takeoff(
            uid="takeoff-1", condition_uid="condition-1", page_uid="page-1"
        )
        self.mesh = MeshData(
            vertices=[(0.0, 0.0, 2.0), (1.0, 0.0, -3.0), (0.0, 1.0, 5.0)],
            faces=[(0, 1, 2)],
        )

    def run_pipeline(
        self,
        *,
        conditions=None,
        takeoffs=None,
        processed=None,
        multi_page=None,
        use_temp_file=False,
        auto_open=False,
        **kwargs,
    ):
        if conditions is None:
            conditions = {"condition-1": self.condition}
        takeoffs = [self.takeoff] if takeoffs is None else takeoffs
        if processed is None:
            processed = (
                [(self.mesh, {"page_uid": "page-1"})],
                (0.0, 1.0, 0.0, 1.0, -3.0, 5.0),
            )
        captured = {}

        def capture_scene(scene_data, title):
            captured["scene"] = copy.deepcopy(scene_data)
            captured["title"] = title
            return "<html>generated</html>"

        with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as stack:
            process_meshes = stack.enter_context(
                patch(
                    f"{_RENDERER_MODULE}.process_meshes_for_threejs",
                    autospec=True,
                    return_value=processed,
                )
            )
            build_scene = stack.enter_context(
                patch.object(
                    ThreejsMeshAdapter,
                    "build_scene_data",
                    autospec=True,
                    side_effect=lambda *_args, **_kwargs: {
                        "title": "built",
                        "geometries": [],
                        "camera": {"position": [0, 0, 1], "target": [0, 0, 0]},
                        "bounds": {"min": [0, 0, 0], "max": [1, 1, 1]},
                    },
                )
            )
            build_pages = stack.enter_context(
                patch(
                    f"{_RENDERER_MODULE}._build_multi_page_data",
                    autospec=True,
                    return_value=multi_page or ([], [], [], []),
                )
            )
            generate = stack.enter_context(
                patch(
                    f"{_RENDERER_MODULE}._generate_html",
                    autospec=True,
                    side_effect=capture_scene,
                )
            )
            browser = stack.enter_context(patch(f"{_RENDERER_MODULE}.webbrowser.open"))
            target = None if use_temp_file else str(Path(tmpdir) / "scene.html")
            result = visualize_with_threejs(
                conditions,
                takeoffs,
                object(),
                ColorService(),
                _export_support__TakeoffService(),
                output_path=target,
                auto_open=auto_open,
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                include_elevation_callouts=False,
                **kwargs,
            )
            written = None
            if result and Path(result).exists():
                written = Path(result).read_text(encoding="utf-8")
            if use_temp_file and result:
                Path(result).unlink()
        return SimpleNamespace(
            result=result,
            target=target,
            written=written,
            scene=captured.get("scene"),
            title=captured.get("title"),
            process_meshes=process_meshes,
            build_scene=build_scene,
            build_pages=build_pages,
            generate=generate,
            browser=browser,
        )

    def test_nothing_to_visualize_returns_none_without_running_any_stage(self):
        for name, kwargs in (
            ("no conditions", {"conditions": {}}),
            ("no takeoffs", {"takeoffs": []}),
        ):
            with self.subTest(name):
                run = self.run_pipeline(**kwargs)
                self.assertIsNone(run.result)
                run.process_meshes.assert_not_called()
                run.generate.assert_not_called()
                self.assertIsNone(run.written)

    def test_empty_mesh_result_returns_none_without_writing_html(self):
        run = self.run_pipeline(processed=([], (0, 0, 0, 0, 0, 0)))
        self.assertIsNone(run.result)
        run.process_meshes.assert_called_once()
        run.build_scene.assert_not_called()
        run.generate.assert_not_called()
        self.assertFalse(Path(run.target).exists())

    def test_display_modes_flags_and_mesh_options_are_forwarded(self):
        run = self.run_pipeline(
            display_mode_3d=Config.DISPLAY_MODE_TRANSPARENT,
            display_mode_2d=Config.DISPLAY_MODE_ORIGINAL,
            display_modes_synced=False,
            grayscale_enabled=False,
            page_area_selections={"page-1": "area-1"},
            title="Exported",
        )
        self.assertEqual(
            run.scene["display_modes"],
            {
                "synced": False,
                "mode_3d": Config.DISPLAY_MODE_TRANSPARENT,
                "mode_2d": Config.DISPLAY_MODE_ORIGINAL,
            },
        )
        mesh_kwargs = run.process_meshes.call_args.kwargs
        self.assertEqual(mesh_kwargs["display_mode"], Config.DISPLAY_MODE_TRANSPARENT)
        self.assertFalse(mesh_kwargs["grayscale_enabled"])
        self.assertEqual(mesh_kwargs["page_area_selections"], {"page-1": "area-1"})
        page_args = run.build_pages.call_args
        self.assertEqual(page_args.args[5], Config.DISPLAY_MODE_ORIGINAL)
        self.assertFalse(page_args.args[6])
        self.assertEqual(page_args.args[7], {"page-1": "area-1"})
        self.assertEqual(run.title, "Exported")

    def test_page_floor_elevations_are_the_lowest_mesh_vertex_of_each_page(self):
        other = MeshData(
            vertices=[(0.0, 0.0, 7.0), (1.0, 0.0, 9.0), (0.0, 1.0, 8.0)],
            faces=[(0, 1, 2)],
        )
        run = self.run_pipeline(
            processed=(
                [
                    (self.mesh, {"page_uid": "page-1"}),
                    (other, {"page_uid": "page-2"}),
                    (other, {"page_uid": ""}),
                ],
                (0.0, 1.0, 0.0, 1.0, -3.0, 9.0),
            )
        )
        self.assertEqual(
            run.build_pages.call_args.kwargs["page_floor_elevations"],
            {"page-1": -3.0, "page-2": 7.0},
        )

    def test_exported_pages_set_selection_and_resolve_the_active_page(self):
        pages = [{"uid": "page-1"}, {"uid": "page-2"}]
        documents = [{"uid": "pdf-1", "data_base64": "AAAA"}]
        multi_page = (pages, documents, [], [])
        kept = self.run_pipeline(multi_page=multi_page, active_page_uid="page-2")
        fallback = self.run_pipeline(multi_page=multi_page, active_page_uid="page-9")
        for run in (kept, fallback):
            self.assertEqual(run.scene["pages"], pages)
            self.assertEqual(run.scene["selected_page_uids"], ["page-1", "page-2"])
            self.assertEqual(run.scene["pdf_documents"], documents)
            self.assertEqual(run.scene["takeoffs_2d"], [])
            # Callouts and their key are only present when some were produced.
            self.assertNotIn("elevation_callouts", run.scene)
        self.assertEqual(kept.scene["active_page_uid"], "page-2")
        self.assertEqual(fallback.scene["active_page_uid"], "page-1")
        # No extracted PDF pages: the key is omitted rather than empty.
        without_documents = self.run_pipeline(multi_page=(pages, [], [], []))
        self.assertNotIn("pdf_documents", without_documents.scene)
        self.assertEqual(without_documents.scene["pages"], pages)

    def test_scene_without_exported_pages_has_no_page_keys(self):
        run = self.run_pipeline()
        for key in (
            "pages",
            "selected_page_uids",
            "active_page_uid",
            "takeoffs_2d",
            "pdf_documents",
            "elevation_callouts",
        ):
            self.assertNotIn(key, run.scene)

    def test_html_is_written_to_a_temp_file_and_opened_only_when_requested(self):
        quiet = self.run_pipeline(use_temp_file=True)
        self.assertTrue(quiet.result.endswith(".html"))
        self.assertEqual(quiet.written, "<html>generated</html>")
        quiet.browser.assert_not_called()
        opened = self.run_pipeline(auto_open=True)
        opened.browser.assert_called_once_with(Path(opened.result).resolve().as_uri())


def _extract_js_function(source, name):
    start = source.index(f"function {name}(")
    depth = 0
    for index in range(source.index("{", start), len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unterminated function {name}")


def _run_node(script):
    completed = subprocess.run(
        [shutil.which("node"), "-"],
        input=script,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return completed.stdout


_MINIMAL_SCENE = {
    "title": "Viewer",
    "geometries": [],
    "camera": {"position": [0.0, 0.0, 1.0], "target": [0.0, 0.0, 0.0]},
    "bounds": {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
}


@unittest.skipUnless(shutil.which("node"), "Node.js is required to execute viewer JS")
class ThreejsViewerScriptTests(unittest.TestCase):
    """Executes viewer.html script text under Node (no DOM, no network)."""

    def test_every_inline_script_parses(self):
        viewer_html = _generate_html(_MINIMAL_SCENE, "Viewer")
        scripts = re.findall(
            r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", viewer_html, re.S
        )
        parsed = []
        with tempfile.TemporaryDirectory() as tmpdir:
            for index, (attrs, body) in enumerate(scripts):
                if "src=" in attrs:
                    continue
                if "application/json" in attrs or "importmap" in attrs:
                    parsed.append(("json", json.loads(body)))
                    continue
                suffix = ".mjs" if 'type="module"' in attrs else ".js"
                script_path = Path(tmpdir) / f"script-{index}{suffix}"
                script_path.write_text(body, encoding="utf-8")
                completed = subprocess.run(
                    [shutil.which("node"), "--check", str(script_path)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                parsed.append((suffix, None))
        kinds = [kind for kind, _ in parsed]
        # scene data + importmap (JSON), theme bootstrap (.js), viewer (.mjs).
        self.assertEqual(kinds.count("json"), 2)
        self.assertEqual(kinds.count(".js"), 1)
        self.assertEqual(kinds.count(".mjs"), 1)
        self.assertEqual(parsed[0][1], _MINIMAL_SCENE)

    def test_object_visibility_combines_base_page_layer_condition_and_area(self):
        viewer_html = _generate_html(_MINIMAL_SCENE, "Viewer")
        functions = "\n".join(
            _extract_js_function(viewer_html, name)
            for name in ("isGroupVisible", "isObjectVisible")
        )
        everything = {"page": "p", "layer": "l", "condition": "c", "area": "a"}

        def case(hidden=(), user_data=None, expected=True):
            data = {
                "pageUid": "p",
                "layerUid": "l",
                "conditionUid": "c",
                "areaUid": "a",
                "usesPage3dVisibility": True,
            }
            data.update(user_data or {})
            return {"hidden": list(hidden), "userData": data, "expected": expected}

        cases = [
            case(),
            case(hidden=["layer"], expected=False),
            case(hidden=["condition"], expected=False),
            case(hidden=["area"], expected=False),
            case(hidden=["page"], expected=False),
            # 2D overlays opt out of the per-page 3D visibility switch.
            case(hidden=["page"], user_data={"usesPage3dVisibility": False}),
            case(user_data={"baseVisible": False}, expected=False),
            case(user_data={"baseVisible": True}),
            # Blank uids are always visible even when the registry hides "".
            case(hidden=["layer"], user_data={"layerUid": ""}),
            case(hidden=["area"], user_data={"areaUid": ""}),
            # Unknown uids (not in a registry) are visible.
            case(user_data={"conditionUid": "unregistered"}),
        ]
        script = f"""
        const layerVisibility = new Map();
        const conditionVisibility = new Map();
        const areaVisibility = new Map();
        const page3dVisibility = new Map();
        {functions}
        const registries = {{
          page: page3dVisibility, layer: layerVisibility,
          condition: conditionVisibility, area: areaVisibility,
        }};
        const uids = {json.dumps(everything)};
        const cases = {json.dumps(cases)};
        const results = cases.map((entry) => {{
          for (const key of Object.keys(registries)) {{
            registries[key].clear();
            registries[key].set(uids[key], {{ visible: !entry.hidden.includes(key) }});
          }}
          return isObjectVisible({{ userData: entry.userData }});
        }});
        console.log(JSON.stringify(results));
        """
        results = json.loads(_run_node(script))
        self.assertEqual(results, [entry["expected"] for entry in cases])

    def test_transparent_pass_hides_materials_of_invisible_objects_and_restores_them(
        self,
    ):
        viewer_html = _generate_html(_MINIMAL_SCENE, "Viewer")
        function = _extract_js_function(viewer_html, "renderWboitPassWithVisibility")
        script = f"""
        const objects = [
          {{ name: "visible", material: "m-visible", visible: true }},
          {{ name: "hidden", material: "m-hidden", visible: false }},
          {{ name: "hidden-without-material", visible: false }},
        ];
        const scene = {{ traverse: (callback) => objects.forEach(callback) }};
        const renderer = {{}};
        const snapshot = () => objects.map((object) => object.material ?? null);
        const outcome = {{}};
        let wboitPass = {{ render: (target) => {{
          outcome.renderTarget = target === renderer;
          outcome.during = snapshot();
        }} }};
        {function}
        renderWboitPassWithVisibility();
        outcome.after = snapshot();
        wboitPass = {{ render: () => {{ outcome.duringFailing = snapshot(); throw new Error("boom"); }} }};
        try {{ renderWboitPassWithVisibility(); }} catch (error) {{ outcome.error = error.message; }}
        outcome.afterFailure = snapshot();
        console.log(JSON.stringify(outcome));
        """
        outcome = json.loads(_run_node(script))
        self.assertTrue(outcome["renderTarget"])
        self.assertEqual(outcome["during"], ["m-visible", None, None])
        self.assertEqual(outcome["after"], ["m-visible", "m-hidden", None])
        self.assertEqual(outcome["duringFailing"], ["m-visible", None, None])
        self.assertEqual(outcome["error"], "boom")
        self.assertEqual(outcome["afterFailure"], ["m-visible", "m-hidden", None])
