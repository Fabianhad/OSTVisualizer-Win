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


def _triangle():
    return MeshData(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[(0, 1, 2)],
    )


def _metadata(**overrides):
    metadata = {
        "color": "#ff0000",
        "opacity": 1.0,
        "name": "Condition",
        "takeoff_uid": "takeoff-1",
        "condition_uid": "condition-1",
    }
    metadata.update(overrides)
    return metadata


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
        self.assertEqual(
            scene["conditions"],
            [
                {
                    "uid": "condition-1",
                    "name": "Condition",
                    "layer_uid": "layer-1",
                    "visible": True,
                    "cdn_type_uid": "type-1",
                    "cdn_type_name": "Concrete",
                    "color": "#336699",
                    "ref_no": 12,
                }
            ],
        )
        self.assertEqual(
            scene["areas"],
            [{"uid": "area-1", "name": "Area One", "visible": True, "sequence": 4}],
        )
        self.assertEqual(
            scene["layers"],
            [
                {"uid": "layer-1", "name": "Takeoff", "visible": False, "sequence": 7},
                {"uid": "image", "name": "Image", "visible": True, "sequence": 1},
            ],
        )
        self.assertEqual(scene["title"], "Layer Scene")
        # Source meshes are z-up (x, y, z); the viewer is y-up (x, z, -y).
        self.assertEqual(
            geometry["vertices"], [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, -1.0]
        )
        self.assertEqual(geometry["normals"], [0.0, 1.0, 0.0] * 3)
        self.assertEqual(geometry["indices"], [0, 1, 2])
        self.assertEqual(geometry["color"], [1.0, 0.0, 0.0])
        self.assertEqual(geometry["name"], "Condition")
        self.assertEqual(geometry["cdn_type_uid"], "type-1")
        self.assertEqual(geometry["cdn_type_name"], "Concrete")

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
        self.assertNotIn("layers", scene)
        self.assertNotIn("page_image_layer", scene)
        self.assertEqual(len(scene["conditions"]), 1)

    def test_threejs_adapter_derives_area_group_from_mesh_metadata_when_not_listed(
        self,
    ):
        adapter = ThreejsMeshAdapter(ColorService())
        scene = adapter.build_scene_data(
            [
                (_triangle(), _metadata(takeoff_uid="a", area_uid="area-9")),
                (_triangle(), _metadata(takeoff_uid="b", area_uid="area-9")),
                (
                    _triangle(),
                    _metadata(takeoff_uid="c", area_uid="area-8", area_name="Eight"),
                ),
            ],
            (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
            "Areas",
        )
        self.assertEqual(
            scene["areas"],
            [
                {"uid": "area-9", "name": "area-9", "visible": True, "sequence": 0},
                {"uid": "area-8", "name": "Eight", "visible": True, "sequence": 1},
            ],
        )
        listed = adapter.build_scene_data(
            [(_triangle(), _metadata(area_uid="derived"))],
            (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
            "Areas",
            areas=[BidArea("listed", "bid", "", "Listed", 7)],
        )
        # A derived group takes the next free position and areas are emitted in
        # sequence order, not insertion order.
        self.assertEqual(
            [(area["uid"], area["sequence"]) for area in listed["areas"]],
            [("derived", 1), ("listed", 7)],
        )

    def test_threejs_adapter_orders_and_filters_listed_layers_and_areas(self):
        adapter = ThreejsMeshAdapter(ColorService())
        scene = adapter.build_scene_data(
            [(_triangle(), _metadata())],
            (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
            "Ordering",
            layers=[
                BidLayer(uid="late", bid_uid="b", name="Late", show=True, sequence=9),
                BidLayer(uid="", bid_uid="b", name="No uid", show=True, sequence=1),
                BidLayer(uid="early", bid_uid="b", name="", show=True, sequence=2),
                BidLayer(uid="late", bid_uid="b", name="Dupe", show=False, sequence=10),
            ],
            areas=[
                BidArea(uid="b", bid_uid="x", parent_uid="", name="B", sequence=5),
                BidArea(
                    uid="0", bid_uid="x", parent_uid="", name="Unassigned", sequence=0
                ),
                BidArea(uid="a", bid_uid="x", parent_uid="", name="", sequence=2),
                BidArea(uid="b", bid_uid="x", parent_uid="", name="Dupe", sequence=6),
            ],
            page_image_layer={"uid": "early", "name": "Image", "visible": False},
        )
        # A page image layer whose uid is already a Layer is not added twice.
        self.assertEqual(
            scene["layers"],
            [
                {"uid": "early", "name": "early", "visible": True, "sequence": 2},
                {"uid": "late", "name": "Late", "visible": True, "sequence": 9},
            ],
        )
        self.assertEqual(
            scene["areas"],
            [
                {"uid": "a", "name": "a", "visible": True, "sequence": 2},
                {"uid": "b", "name": "B", "visible": True, "sequence": 5},
            ],
        )

    def test_threejs_adapter_deduplicates_conditions_and_skips_empty_meshes(self):
        adapter = ThreejsMeshAdapter(ColorService())
        scene = adapter.build_scene_data(
            [
                (
                    _triangle(),
                    _metadata(takeoff_uid="a", condition_uid="c1", name="One"),
                ),
                (
                    _triangle(),
                    _metadata(takeoff_uid="b", condition_uid="c1", name="Two"),
                ),
                (MeshData(vertices=[], faces=[]), _metadata(condition_uid="c-empty")),
                (_triangle(), _metadata(takeoff_uid="d", condition_uid="")),
            ],
            (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
            "Dedupe",
        )
        self.assertEqual(
            [geometry["takeoff_uid"] for geometry in scene["geometries"]],
            ["a", "b", "d"],
        )
        # Conditions come from mesh metadata even when their mesh is skipped,
        # but only once per uid and never for a blank uid.
        self.assertEqual(
            [(entry["uid"], entry["name"]) for entry in scene["conditions"]],
            [("c1", "One"), ("c-empty", "Condition")],
        )
        self.assertEqual(scene["conditions"][0]["cdn_type_name"], "Unknown")
        self.assertEqual(scene["conditions"][0]["ref_no"], 0)

    def test_threejs_adapter_frames_camera_and_bounds_in_y_up_space(self):
        adapter = ThreejsMeshAdapter(ColorService())
        scene = adapter.build_scene_data(
            [(_triangle(), _metadata())],
            (10.0, 30.0, -4.0, 6.0, 1.0, 5.0),
            "Camera",
        )
        # Center (20, 1, 3) in source space is (20, 3, -1) in viewer space and
        # the framing distance is the longest extent (20) times 1.5 / 1.
        self.assertEqual(
            scene["camera"],
            {"position": [20.0, 3.0 + 30.0, -1.0 - 20.0], "target": [20.0, 3.0, -1.0]},
        )
        self.assertEqual(
            scene["bounds"],
            {"min": [10.0, 1.0, -6.0], "max": [30.0, 5.0, 4.0]},
        )
        tiny = adapter.build_scene_data(
            [(_triangle(), _metadata())], (0.0, 0.5, 0.0, 0.5, 0.0, 0.5), "Tiny"
        )
        # Extents below one unit are framed as one unit.
        self.assertEqual(tiny["camera"]["position"], [0.25, 0.25 + 1.5, -0.25 - 1.0])

    def test_threejs_adapter_convert_mesh_splits_creased_vertices_and_defaults_metadata(
        self,
    ):
        adapter = ThreejsMeshAdapter(ColorService())
        mesh = MeshData(
            vertices=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ],
            faces=[(0, 1, 2), (0, 1, 3)],
        )
        geometry = adapter.convert_mesh(mesh, {})
        # The 90 degree crease splits the two shared corners into 6 vertices;
        # every position is mapped (x, y, z) -> (x, z, -y).
        self.assertEqual(
            geometry["vertices"],
            [0.0, 0.0, 0.0]
            + [0.0, 0.0, 0.0]
            + [1.0, 0.0, 0.0]
            + [1.0, 0.0, 0.0]
            + [0.0, 0.0, -1.0]
            + [0.0, 1.0, 0.0],
        )
        self.assertEqual(geometry["indices"], [0, 2, 4, 1, 3, 5])
        # Face normals (0, 0, 1) and (0, -1, 0) map to (0, 1, 0) and (0, 0, 1).
        self.assertEqual(
            geometry["normals"],
            [0.0, 1.0, 0.0, 0.0, 0.0, 1.0] * 3,
        )
        self.assertEqual(geometry["color"], [128 / 255.0] * 3)
        self.assertEqual(
            (geometry["opacity"], geometry["name"], geometry["visible"]),
            (1.0, "Mesh", True),
        )
        self.assertEqual(geometry["cdn_type_name"], "Unknown")
        self.assertIsNone(adapter.convert_mesh(MeshData(vertices=[], faces=[]), {}))

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
        self.assertEqual(geometry["color"], [51 / 255.0, 102 / 255.0, 153 / 255.0])
        self.assertEqual(geometry["page_uid"], "page-1")
        self.assertEqual(geometry["layer_uid"], "layer-1")
        self.assertEqual(geometry["condition_uid"], "condition-1")
        self.assertEqual(geometry["area_uid"], "area-1")
