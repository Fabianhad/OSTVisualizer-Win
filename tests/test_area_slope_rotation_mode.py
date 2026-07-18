import math
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.components.plan_view.components.input_handler import (
    InputHandlerMixin,
)


class SlopeRotationHarness(InputHandlerMixin):
    def __init__(self):
        self._selection_enabled = True
        self._editing_enabled = True
        self._selected_uids = {"a1"}
        self._current_conditions = {
            "area": Condition(
                uid="area",
                condition_type=Condition.TYPE_AREA,
                layer_visible=True,
                rise=3,
                run=12,
            ),
            "linear": Condition(
                uid="linear",
                condition_type=Condition.TYPE_LINEAR,
                layer_visible=True,
                rise=3,
                run=12,
            ),
        }
        self._current_takeoffs = {
            "a1": Takeoff(
                uid="a1",
                condition_uid="area",
                position=[0, 0, 10, 0, 10, 10, 0, 10],
                rotation=0.0,
            ),
            "a2": Takeoff(
                uid="a2",
                condition_uid="area",
                position=[0, 0, 10, 0, 10, 10, 0, 10],
                rotation=0.0,
                parent_uid="a1",
            ),
            "l1": Takeoff(
                uid="l1",
                condition_uid="linear",
                position=[0, 0, 10, 0],
                rotation=0.0,
            ),
        }
        self._rotation_drag_uid = ""
        self._rotation_drag_orig_rotations = {}
        self._rotation_before_edit = {}
        self._dirty_rotations = {}
        self.flushed_rotations = []

    def _flush_dirty_rotations(self) -> None:
        self.flushed_rotations.extend(
            (uid, self._rotation_before_edit.get(uid, 0.0), rotation)
            for uid, rotation in self._dirty_rotations.items()
        )
        self._rotation_before_edit.clear()
        self._dirty_rotations.clear()


class AreaSlopeRotationModeTests(unittest.TestCase):
    def test_slope_rotate_selection_requires_single_area_takeoff_with_slope(self):
        harness = SlopeRotationHarness()
        self.assertEqual(harness._selected_area_slope_uid(), "a1")
        harness._selected_uids = {"a1", "l1"}
        self.assertEqual(harness._selected_area_slope_uid(), "")
        harness._selected_uids = {"l1"}
        self.assertEqual(harness._selected_area_slope_uid(), "")
        harness._selected_uids = {"a2"}
        self.assertEqual(harness._selected_area_slope_uid(), "")
        harness._selected_uids = {"a1"}
        harness._current_conditions["area"].run = 0
        self.assertEqual(harness._selected_area_slope_uid(), "")

    def test_apply_slope_rotation_changes_rotation_without_moving_area(self):
        harness = SlopeRotationHarness()
        original_position = list(harness._current_takeoffs["a1"].position)
        harness._rotation_drag_uid = "a1"
        harness._rotation_drag_orig_rotations = {"a1": 0.25}
        harness._apply_slope_rotation("a1", 90.0)
        self.assertEqual(harness._current_takeoffs["a1"].position, original_position)
        self.assertAlmostEqual(
            harness._current_takeoffs["a1"].rotation,
            0.25 - math.pi / 2.0,
        )
        self.assertEqual(
            harness.flushed_rotations,
            [("a1", 0.25, 0.25 - math.pi / 2.0)],
        )


if __name__ == "__main__":
    unittest.main()
