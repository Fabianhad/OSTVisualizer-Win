import unittest
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.presentation.visualization.renderers.threejs.adapters.threejs_mesh_adapter import (
    ThreejsMeshAdapter,
)
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)


class ThreejsExportLayerTests(unittest.TestCase):
    def test_threejs_adapter_exports_layer_condition_and_area_metadata(self):
        adapter = ThreejsMeshAdapter(ColorService())
        mesh = MeshData(
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[(0, 1, 2)],
        )
        scene = adapter.build_scene_data(
            [
                (
                    mesh,
                    {
                        "color": "#ff0000",
                        "opacity": 1.0,
                        "name": "Condition",
                        "takeoff_uid": "takeoff-1",
                        "page_uid": "page-1",
                        "condition_uid": "condition-1",
                        "area_uid": "area-1",
                        "area_name": "Area One",
                        "layer_uid": "layer-1",
                        "visible": True,
                        "cdn_type_uid": "type-1",
                        "cdn_type_name": "Concrete",
                        "condition_color": "#336699",
                        "condition_ref_no": 12,
                    },
                )
            ],
            (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
            "Layer Scene",
            layers=[
                BidLayer(
                    uid="layer-1",
                    bid_uid="bid",
                    name="Takeoff",
                    show=False,
                    sequence=7,
                )
            ],
            areas=[
                BidArea(
                    uid="area-1",
                    bid_uid="bid",
                    parent_uid="",
                    name="Area One",
                    sequence=4,
                )
            ],
            page_image_layer={"uid": "image", "name": "Image", "visible": True},
        )
        geometry = scene["geometries"][0]
        self.assertEqual(geometry["takeoff_uid"], "takeoff-1")
        self.assertEqual(geometry["page_uid"], "page-1")
        self.assertEqual(geometry["condition_uid"], "condition-1")
        self.assertEqual(geometry["area_uid"], "area-1")
        self.assertEqual(geometry["layer_uid"], "layer-1")
        self.assertTrue(geometry["visible"])
        self.assertEqual(scene["conditions"][0]["layer_uid"], "layer-1")
        self.assertTrue(scene["conditions"][0]["visible"])
        self.assertEqual(scene["conditions"][0]["cdn_type_uid"], "type-1")
        self.assertEqual(scene["conditions"][0]["cdn_type_name"], "Concrete")
        self.assertEqual(scene["conditions"][0]["color"], "#336699")
        self.assertEqual(scene["conditions"][0]["ref_no"], 12)
        self.assertEqual(scene["areas"][0]["uid"], "area-1")
        self.assertEqual(scene["areas"][0]["name"], "Area One")
        self.assertEqual(scene["layers"][0]["uid"], "layer-1")
        self.assertFalse(scene["layers"][0]["visible"])
        self.assertEqual(scene["page_image_layer"]["uid"], "image")

    def test_threejs_adapter_keeps_unassigned_area_meshes_out_of_area_groups(self):
        adapter = ThreejsMeshAdapter(ColorService())
        mesh = MeshData(
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[(0, 1, 2)],
        )
        scene = adapter.build_scene_data(
            [
                (
                    mesh,
                    {
                        "color": "#ff0000",
                        "opacity": 1.0,
                        "name": "Condition",
                        "takeoff_uid": "takeoff-1",
                        "condition_uid": "condition-1",
                        "area_uid": "",
                        "layer_uid": "layer-1",
                    },
                )
            ],
            (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
            "Layer Scene",
        )
        self.assertEqual(scene["geometries"][0]["area_uid"], "")
        self.assertNotIn("areas", scene)

    def test_threejs_adapter_preserves_visibility_metadata_for_transparent_meshes(self):
        adapter = ThreejsMeshAdapter(ColorService())
        mesh = MeshData(
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[(0, 1, 2)],
        )
        scene = adapter.build_scene_data(
            [
                (
                    mesh,
                    {
                        "color": "#336699",
                        "opacity": 0.5,
                        "name": "Transparent Condition",
                        "takeoff_uid": "takeoff-1",
                        "page_uid": "page-1",
                        "condition_uid": "condition-1",
                        "area_uid": "area-1",
                        "layer_uid": "layer-1",
                        "visible": False,
                    },
                )
            ],
            (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
            "Transparent Scene",
        )
        geometry = scene["geometries"][0]
        self.assertEqual(geometry["opacity"], 0.5)
        self.assertFalse(geometry["visible"])
        self.assertEqual(geometry["page_uid"], "page-1")
        self.assertEqual(geometry["layer_uid"], "layer-1")
        self.assertEqual(geometry["condition_uid"], "condition-1")
        self.assertEqual(geometry["area_uid"], "area-1")
