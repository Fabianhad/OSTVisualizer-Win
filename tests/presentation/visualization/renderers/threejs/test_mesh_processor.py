"""Mesh selection and metadata projection, independent of native tessellation."""

import unittest
from unittest.mock import Mock, patch
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.presentation.visualization.renderers.threejs.mesh_processor import (
    process_meshes_for_threejs,
)


class ProcessMeshesForThreejsTests(unittest.TestCase):
    def setUp(self):
        self.colors = Mock()
        self.colors.get_color_mapping.return_value = ({}, {"c": "#123456"})
        self.colors.get_color_for_takeoff.return_value = ("#123456", 0.4)
        self.takeoffs = Mock()
        self.module = (
            "ost_visualizer.presentation.visualization.renderers.threejs.mesh_processor"
        )

    def test_metadata_retains_page_area_layer_and_condition_identity(self):
        condition = Condition(
            "c",
            name="Wall",
            layer_uid="layer",
            cdn_type_uid="type",
            cdn_type_name="Masonry",
            ref_no=7,
        )
        takeoff = Takeoff("t", "c", page_uid="page", area_uid="area")
        self.takeoffs.group_area_takeoffs_with_holes.return_value = ([takeoff], {})
        self.takeoffs.group_takeoffs_by_type.return_value = {0: [takeoff]}
        mesh = MeshData([(0, 0, 0), (1, 2, 3), (4, 5, 6)], [(0, 1, 2)])
        with patch(self.module + ".MeshFactory") as factory:
            factory.return_value.create_mesh_for_takeoff.return_value = mesh
            with patch(
                self.module + ".apply_boolean_operations",
                side_effect=lambda items: items,
            ) as boolean:
                meshes, bounds = process_meshes_for_threejs(
                    {"c": condition},
                    [takeoff],
                    Mock(),
                    self.colors,
                    self.takeoffs,
                    areas=[BidArea("area", "bid", "0", "Level 1", 1)],
                    inactive_object_color="#aaaaaa",
                )
                boolean.assert_called_once()
            factory.return_value.create_mesh_for_takeoff.assert_called_once_with(
                takeoff, condition, None
            )
        self.assertIs(meshes[0][0], mesh)
        metadata = meshes[0][1]
        self.assertEqual(
            (metadata["condition_uid"], metadata["takeoff_uid"], metadata["page_uid"]),
            ("c", "t", "page"),
        )
        self.assertEqual(
            (metadata["area_uid"], metadata["area_name"], metadata["layer_uid"]),
            ("area", "Level 1", "layer"),
        )
        self.assertEqual(
            (
                metadata["opacity"],
                metadata["condition_ref_no"],
                metadata["cdn_type_uid"],
            ),
            (0.4, 7, "type"),
        )
        self.assertEqual(bounds, (0, 4, 0, 5, 0, 6))
        self.assertEqual(
            self.colors.get_color_for_takeoff.call_args.kwargs,
            {"inactive_object_color": "#aaaaaa"},
        )

    def test_missing_conditions_and_empty_meshes_do_not_publish_metadata(self):
        missing = Takeoff("missing", "foreign")
        empty = Takeoff("empty", "c")
        self.takeoffs.group_area_takeoffs_with_holes.return_value = (
            [missing, empty],
            {},
        )
        self.takeoffs.group_takeoffs_by_type.return_value = {0: [missing, empty]}
        with patch(self.module + ".MeshFactory") as factory:
            factory.return_value.create_mesh_for_takeoff.return_value = MeshData([], [])
            with patch(
                self.module + ".apply_boolean_operations",
                side_effect=lambda items: items,
            ):
                meshes, bounds = process_meshes_for_threejs(
                    {"c": Condition("c")},
                    [missing, empty],
                    Mock(),
                    self.colors,
                    self.takeoffs,
                    inactive_object_color="#aaaaaa",
                )
            self.assertEqual(factory.return_value.create_mesh_for_takeoff.call_count, 1)
        self.assertEqual(meshes, [])
        self.assertEqual(bounds, (-1000, 1000, -1000, 1000, -10, 10))
        self.colors.get_color_for_takeoff.assert_not_called()
