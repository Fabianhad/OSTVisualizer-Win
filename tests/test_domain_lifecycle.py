import unittest
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.workspace_state import (
    TakeoffWorkspaceState,
    WORKSPACE_VALID_ACTIVE_VIEWS,
    WorkspaceState,
)


class DomainLifecycleTests(unittest.TestCase):
    def test_validation_constants_are_immutable_shared_state(self):
        self.assertIsInstance(ConfigAggregate.VALID_COLOR_MODES, frozenset)
        self.assertIsInstance(ConfigAggregate.VALID_ROPING_SELECTION_METHODS, frozenset)
        self.assertIsInstance(ConfigAggregate.VALID_HOTLINK_TARGETS, frozenset)
        self.assertIsInstance(ConfigAggregate.VALID_MOUSE_SNAP_ANGLES, frozenset)

    def test_workspace_active_view_constants_are_immutable_shared_state(self):
        self.assertIsInstance(TakeoffWorkspaceState.VALID_ACTIVE_VIEWS, frozenset)
        self.assertEqual(
            TakeoffWorkspaceState.VALID_ACTIVE_VIEWS, WORKSPACE_VALID_ACTIVE_VIEWS
        )

    def test_workspace_annotation_styles_round_trip_and_clamp_values(self):
        state = WorkspaceState.from_dict(
            {
                "takeoff_workspace": {
                    "annotation_styles": {
                        "arrow": {
                            "color": "336699",
                            "line_width": 99,
                        },
                        "rect": {
                            "color": "00aa00",
                            "line_width": 2,
                        },
                    }
                }
            }
        )
        self.assertEqual(
            state.takeoff_workspace.annotation_styles["arrow"].color, "#336699"
        )
        self.assertEqual(
            state.takeoff_workspace.annotation_styles["arrow"].line_width, 16.0
        )
        self.assertEqual(
            state.takeoff_workspace.annotation_styles["rect"].color, "#00aa00"
        )
        self.assertEqual(
            state.takeoff_workspace.annotation_styles["rect"].line_width, 2.0
        )
        payload = state.to_dict()
        self.assertEqual(
            payload["takeoff_workspace"]["annotation_styles"]["arrow"]["color"],
            "#336699",
        )
        self.assertEqual(
            payload["takeoff_workspace"]["annotation_styles"]["arrow"]["line_width"],
            16.0,
        )

    def test_workspace_annotation_styles_default_to_empty_map(self):
        state = WorkspaceState.from_dict({})
        self.assertEqual(state.takeoff_workspace.annotation_styles, {})

    def test_workspace_summary_state_defaults_to_type_area_grouping(self):
        state = WorkspaceState.from_dict({})
        self.assertTrue(state.takeoff_workspace.summary_group_by_area)
        self.assertTrue(state.takeoff_workspace.summary_group_by_type)
        self.assertFalse(state.takeoff_workspace.summary_group_by_page)
        self.assertEqual(state.takeoff_workspace.summary_column_widths, {})

    def test_workspace_summary_state_round_trips_and_ignores_invalid_widths(self):
        state = WorkspaceState.from_dict(
            {
                "takeoff_workspace": {
                    "summary_group_by_area": False,
                    "summary_group_by_type": True,
                    "summary_group_by_page": True,
                    "summary_column_widths": {
                        "name": "220",
                        "area": 0,
                        "notes": -5,
                        "quantity1": "bad",
                    },
                }
            }
        )
        self.assertFalse(state.takeoff_workspace.summary_group_by_area)
        self.assertTrue(state.takeoff_workspace.summary_group_by_type)
        self.assertTrue(state.takeoff_workspace.summary_group_by_page)
        self.assertEqual(state.takeoff_workspace.summary_column_widths, {"name": 220})
        payload = state.to_dict()["takeoff_workspace"]
        self.assertEqual(payload["summary_column_widths"], {"name": 220})
        self.assertFalse(payload["summary_group_by_area"])
        self.assertTrue(payload["summary_group_by_type"])
        self.assertTrue(payload["summary_group_by_page"])

    def test_workspace_dropdown_popup_sizes_ignore_invalid_values(self):
        state = WorkspaceState.from_dict(
            {
                "takeoff_workspace": {
                    "dropdown_popup_sizes": {
                        "annotation_page": [0, 360],
                        "view_page": ["700", "500"],
                        "main_page": ["bad", 400],
                    }
                }
            }
        )
        self.assertEqual(
            state.takeoff_workspace.dropdown_popup_sizes,
            {"view_page": [700, 500]},
        )

    def test_workspace_detached_window_missing_fullscreen_defaults_false(self):
        state = WorkspaceState.from_dict(
            {
                "detached_windows": {
                    "annotation_view": {
                        "open": True,
                        "geometry_b64": "saved-geometry",
                        "is_maximized": False,
                    }
                }
            }
        )
        annotation_state = state.detached_windows.annotation_view
        self.assertTrue(annotation_state.open)
        self.assertEqual(annotation_state.geometry_b64, "saved-geometry")
        self.assertFalse(annotation_state.is_maximized)
        self.assertFalse(annotation_state.is_fullscreen)


if __name__ == "__main__":
    unittest.main()
