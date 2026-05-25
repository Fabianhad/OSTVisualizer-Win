import unittest

from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.workspace_state import \
    TakeoffWorkspaceState


class DomainLifecycleTests(unittest.TestCase):
    def test_validation_constants_are_immutable_shared_state(self):
        self.assertIsInstance(ConfigAggregate.VALID_COLOR_MODES, frozenset)
        self.assertIsInstance(ConfigAggregate.VALID_ROPING_SELECTION_METHODS, frozenset)
        self.assertIsInstance(ConfigAggregate.VALID_HOTLINK_TARGETS, frozenset)
        self.assertIsInstance(ConfigAggregate.VALID_MOUSE_SNAP_ANGLES, frozenset)

    def test_workspace_active_view_constants_are_immutable_shared_state(self):
        self.assertIsInstance(TakeoffWorkspaceState.VALID_ACTIVE_VIEWS, frozenset)


if __name__ == "__main__":
    unittest.main()
