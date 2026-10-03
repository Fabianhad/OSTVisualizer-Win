"""Mesh selection and metadata projection, independent of native tessellation."""

import unittest
from unittest.mock import create_autospec, patch
from ost_visualizer.application.dtos.color_dtos import (
    ColorMappingResult,
    ColorWithOpacity,
)
from ost_visualizer.application.interfaces.i_color_service import IColorService
from ost_visualizer.application.interfaces.i_coordinate_transformer import (
    ICoordinateTransformer,
)
from ost_visualizer.application.interfaces.i_takeoff_domain_service import (
    ITakeoffDomainService,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.presentation.visualization.renderers.threejs.mesh_processor import (
    process_meshes_for_threejs,
)


class ProcessMeshesForThreejsTests(unittest.TestCase):
    """Native tessellation (MeshFactory) and Manifold booleans are faked here.
    The collaborators are autospecced against the application interfaces, so a
    call the real services would reject fails these tests too.
    """

    def setUp(self):
        self.colors = create_autospec(IColorService, instance=True)
        self.colors.get_color_mapping.return_value = ColorMappingResult(
            {}, {"c": "#123456"}
        )
        self.colors.get_color_for_takeoff.return_value = ColorWithOpacity(
            "#123456", 0.4
        )
        self.takeoffs = create_autospec(ITakeoffDomainService, instance=True)
        self.coord_system = create_autospec(ICoordinateTransformer, instance=True)
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
            color_fill=0x336699,
        )
        takeoff = Takeoff("t", "c", page_uid="page", area_uid="area")
        self.takeoffs.group_area_takeoffs_with_holes.return_value = ([takeoff], {})
        self.takeoffs.group_takeoffs_by_type.return_value = {0: [takeoff]}
        mesh = MeshData([(0, 0, 0), (1, 2, 3), (4, 5, 6)], [(0, 1, 2)])
        boolean_result = (
            MeshData([(-1, -2, -3), (7, 8, 9)], [(0, 1, 1)]),
            {"marker": "from boolean"},
        )
        with patch(self.module + ".MeshFactory") as factory:
            factory.return_value.create_mesh_for_takeoff.return_value = mesh
            with patch(
                self.module + ".apply_boolean_operations",
                return_value=[boolean_result],
            ) as boolean:
                meshes, bounds = process_meshes_for_threejs(
                    {"c": condition},
                    [takeoff],
                    self.coord_system,
                    self.colors,
                    self.takeoffs,
                    areas=[BidArea("area", "bid", "0", "Level 1", 1)],
                    inactive_object_color="#aaaaaa",
                )
            factory.assert_called_once_with(self.coord_system)
            factory.return_value.create_mesh_for_takeoff.assert_called_once_with(
                takeoff, condition, None
            )
        expected_metadata = {
            "IsNegativeQuantity": False,
            "color": "#123456",
            "opacity": 0.4,
            "condition_uid": "c",
            "takeoff_uid": "t",
            "page_uid": "page",
            "area_uid": "area",
            "area_name": "Level 1",
            "condition_type": 0,
            "layer_uid": "layer",
            "visible": True,
            "name": "Wall",
            "cdn_type_uid": "type",
            "cdn_type_name": "Masonry",
            "condition_color": "#996633",
            "condition_ref_no": 7,
        }
        (boolean_input,) = boolean.call_args.args[0]
        self.assertIs(boolean_input[0], mesh)
        self.assertEqual(boolean_input[1], expected_metadata)
        # The processed result of the boolean pass is what is returned and
        # bounded; the raw mesh is not.
        self.assertEqual(meshes, [boolean_result])
        self.assertEqual(bounds, (-1, 7, -2, 8, -3, 9))
        self.assertEqual(
            self.colors.get_color_for_takeoff.call_args.kwargs,
            {"inactive_object_color": "#aaaaaa"},
        )

    def test_unnamed_unassigned_takeoff_uses_fallback_labels(self):
        condition = Condition("c", cdn_type_name="", color_fill=0)
        takeoff = Takeoff("t", "c", is_negative=True)
        mesh = MeshData([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
        self.takeoffs.group_area_takeoffs_with_holes.return_value = ([takeoff], {})
        self.takeoffs.group_takeoffs_by_type.return_value = {1: [takeoff]}
        with patch(self.module + ".MeshFactory") as factory:
            factory.return_value.create_mesh_for_takeoff.return_value = mesh
            with patch(
                self.module + ".apply_boolean_operations",
                side_effect=lambda items: items,
            ):
                meshes, _ = process_meshes_for_threejs(
                    {"c": condition},
                    [takeoff],
                    self.coord_system,
                    self.colors,
                    self.takeoffs,
                    areas=[BidArea("other", "bid", "0", "Elsewhere", 1)],
                    inactive_object_color="#aaaaaa",
                )
        metadata = meshes[0][1]
        self.assertEqual(metadata["name"], "Element t")
        self.assertEqual(metadata["cdn_type_name"], "Unknown")
        self.assertEqual(metadata["cdn_type_uid"], "")
        self.assertEqual(metadata["layer_uid"], "")
        self.assertEqual(metadata["page_uid"], "")
        self.assertEqual((metadata["area_uid"], metadata["area_name"]), ("", ""))
        self.assertEqual(metadata["condition_color"], "#000000")
        self.assertTrue(metadata["IsNegativeQuantity"])

    def test_missing_conditions_and_empty_meshes_do_not_publish_metadata(self):
        missing = Takeoff("missing", "foreign")
        empty = Takeoff("empty", "c")
        none_mesh = Takeoff("none", "c")
        kept = Takeoff("kept", "c")
        kept_mesh = MeshData([(0, 0, 0), (2, 0, 0), (0, 3, 1)], [(0, 1, 2)])
        all_takeoffs = [missing, empty, none_mesh, kept]
        self.takeoffs.group_area_takeoffs_with_holes.return_value = (all_takeoffs, {})
        self.takeoffs.group_takeoffs_by_type.return_value = {0: all_takeoffs}
        meshes_by_uid = {
            "empty": MeshData([], []),
            "none": None,
            "kept": kept_mesh,
        }
        with patch(self.module + ".MeshFactory") as factory:
            factory.return_value.create_mesh_for_takeoff.side_effect = (
                lambda takeoff, condition, holes: meshes_by_uid[takeoff.uid]
            )
            with patch(
                self.module + ".apply_boolean_operations",
                side_effect=lambda items: items,
            ):
                meshes, bounds = process_meshes_for_threejs(
                    {"c": Condition("c")},
                    all_takeoffs,
                    self.coord_system,
                    self.colors,
                    self.takeoffs,
                    inactive_object_color="#aaaaaa",
                )
            # "missing" never reaches the factory; the other three do.
            created = factory.return_value.create_mesh_for_takeoff
            self.assertEqual(
                [call.args[0].uid for call in created.call_args_list],
                ["empty", "none", "kept"],
            )
        self.assertEqual([metadata["takeoff_uid"] for _, metadata in meshes], ["kept"])
        self.assertIs(meshes[0][0], kept_mesh)
        self.assertEqual(bounds, (0, 2, 0, 3, 0, 1))
        self.colors.get_color_for_takeoff.assert_called_once()

    def test_no_meshes_yield_default_bounds(self):
        takeoff = Takeoff("t", "c")
        self.takeoffs.group_area_takeoffs_with_holes.return_value = ([takeoff], {})
        self.takeoffs.group_takeoffs_by_type.return_value = {0: [takeoff]}
        with patch(self.module + ".MeshFactory") as factory:
            factory.return_value.create_mesh_for_takeoff.return_value = MeshData([], [])
            with patch(
                self.module + ".apply_boolean_operations",
                side_effect=lambda items: items,
            ):
                meshes, bounds = process_meshes_for_threejs(
                    {"c": Condition("c")},
                    [takeoff],
                    self.coord_system,
                    self.colors,
                    self.takeoffs,
                    inactive_object_color="#aaaaaa",
                )
        self.assertEqual(meshes, [])
        self.assertEqual(bounds, (-1000, 1000, -1000, 1000, -10, 10))
        self.colors.get_color_for_takeoff.assert_not_called()

    def test_meshes_are_emitted_area_then_linear_then_count_then_attachment(self):
        conditions = {
            "area": Condition("area", condition_type=Condition.TYPE_AREA),
            "linear": Condition("linear", condition_type=Condition.TYPE_LINEAR),
            "count": Condition("count", condition_type=Condition.TYPE_COUNT),
            "attachment": Condition(
                "attachment", condition_type=Condition.TYPE_ATTACHMENT
            ),
        }
        takeoffs = {uid: Takeoff(f"t-{uid}", uid) for uid in conditions}
        self.takeoffs.group_area_takeoffs_with_holes.return_value = (
            list(takeoffs.values()),
            {},
        )
        # Grouping order is deliberately scrambled relative to the emit order.
        self.takeoffs.group_takeoffs_by_type.return_value = {
            3: [takeoffs["attachment"]],
            2: [takeoffs["count"]],
            0: [takeoffs["linear"]],
            1: [takeoffs["area"]],
        }
        mesh = MeshData([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
        with patch(self.module + ".MeshFactory") as factory:
            factory.return_value.create_mesh_for_takeoff.return_value = mesh
            with patch(
                self.module + ".apply_boolean_operations",
                side_effect=lambda items: items,
            ):
                meshes, _ = process_meshes_for_threejs(
                    conditions,
                    list(takeoffs.values()),
                    self.coord_system,
                    self.colors,
                    self.takeoffs,
                    inactive_object_color="#aaaaaa",
                )
        self.assertEqual(
            [metadata["takeoff_uid"] for _, metadata in meshes],
            ["t-area", "t-linear", "t-count", "t-attachment"],
        )
        self.assertEqual(
            [metadata["condition_type"] for _, metadata in meshes], [1, 0, 2, 3]
        )

    def test_area_holes_and_display_options_reach_their_collaborators(self):
        condition = Condition("c", condition_type=Condition.TYPE_AREA)
        outer = Takeoff("outer", "c", page_uid="p1", area_uid="a1")
        hole = Takeoff(
            "hole", "c", parent_uid="outer", position=[1.0, 1.0, 2.0, 1.0, 2.0, 2.0]
        )
        flat = Takeoff("flat", "c", parent_uid="outer", position=[1.0, 1.0])
        self.takeoffs.group_area_takeoffs_with_holes.return_value = (
            [outer],
            {"outer": [hole, flat]},
        )
        self.takeoffs.group_takeoffs_by_type.return_value = {1: [outer]}
        mesh = MeshData([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
        selections = {"p1": "a1"}
        with patch(self.module + ".MeshFactory") as factory:
            factory.return_value.create_mesh_for_takeoff.return_value = mesh
            with patch(
                self.module + ".apply_boolean_operations",
                side_effect=lambda items: items,
            ):
                process_meshes_for_threejs(
                    {"c": condition},
                    [outer, hole, flat],
                    self.coord_system,
                    self.colors,
                    self.takeoffs,
                    display_mode=Config.DISPLAY_MODE_TRANSPARENT,
                    grayscale_enabled=False,
                    page_area_selections=selections,
                    inactive_object_color="#aaaaaa",
                )
            factory.return_value.create_mesh_for_takeoff.assert_called_once_with(
                outer, condition, [[(1.0, 1.0), (2.0, 1.0), (2.0, 2.0)]]
            )
        self.colors.get_color_mapping.assert_called_once_with(
            {"c": condition},
            [outer, hole, flat],
            Config.DISPLAY_MODE_TRANSPARENT,
            False,
        )
        self.takeoffs.group_takeoffs_by_type.assert_called_once_with(
            {"c": condition}, [outer]
        )
        self.colors.get_color_for_takeoff.assert_called_once_with(
            outer,
            condition,
            {"c": "#123456"},
            Config.DISPLAY_MODE_TRANSPARENT,
            selections,
            inactive_object_color="#aaaaaa",
        )
