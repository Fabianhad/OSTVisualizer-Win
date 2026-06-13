import unittest
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.workspace_state import (
    TakeoffWorkspaceState,
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

    def test_workspace_annotation_style_round_trips_and_clamps_values(self):
        state = WorkspaceState.from_dict(
            {
                "takeoff_workspace": {
                    "annotation_style": {
                        "color": "336699",
                        "line_width": 99,
                    }
                }
            }
        )
        self.assertEqual(state.takeoff_workspace.annotation_style.color, "#336699")
        self.assertEqual(state.takeoff_workspace.annotation_style.line_width, 16.0)
        payload = state.to_dict()
        self.assertEqual(
            payload["takeoff_workspace"]["annotation_style"],
            {"color": "#336699", "line_width": 16.0},
        )

    def test_workspace_annotation_style_defaults_to_red_four_pixels(self):
        state = WorkspaceState.from_dict({})
        self.assertEqual(state.takeoff_workspace.annotation_style.color, "#ff0000")
        self.assertEqual(state.takeoff_workspace.annotation_style.line_width, 4.0)


if __name__ == "__main__":
    unittest.main()
