import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.project_data_service import ProjectDataService


class _AreaUsageModel:
    def __init__(self, takeoffs, conditions, page_takeoffs=None):
        self._takeoffs = list(takeoffs)
        self.bid_conditions = dict(conditions)
        page_takeoff_list = self._takeoffs if page_takeoffs is None else page_takeoffs
        self._pages = {"page-1": SimpleNamespace(takeoffs=list(page_takeoff_list))}

    def get_all_takeoffs(self):
        return list(self._takeoffs)

    def get_page(self, page_uid):
        return self._pages.get(page_uid)


def _condition(uid, condition_type=Condition.TYPE_AREA, layer_visible=True):
    return Condition(
        uid=uid,
        condition_type=condition_type,
        layer_visible=layer_visible,
    )


def _takeoff(
    uid,
    condition_uid="condition-area",
    area_uid="0",
    position=None,
    parent_uid="0",
):
    return Takeoff(
        uid=uid,
        condition_uid=condition_uid,
        page_uid="page-1",
        area_uid=area_uid,
        position=list(position or []),
        parent_uid=parent_uid,
    )


class AreaAssignmentStateTests(unittest.TestCase):
    def test_direct_condition_update_rejects_incompatible_selection_atomically(self):
        conditions = {
            "linear": _condition("linear", Condition.TYPE_LINEAR),
            "area": _condition("area", Condition.TYPE_AREA),
        }
        linear = _takeoff(
            "linear-takeoff",
            condition_uid="linear",
            position=[0.0, 0.0, 10.0, 0.0],
        )
        area = _takeoff(
            "area-takeoff",
            condition_uid="area",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
        )
        service = ProjectDataService(_AreaUsageModel([linear, area], conditions))
        page_uids = service.update_takeoffs_condition(
            ["linear-takeoff", "area-takeoff"], "linear"
        )
        self.assertEqual(page_uids, [])
        self.assertEqual(linear.condition_uid, "linear")
        self.assertEqual(area.condition_uid, "area")
        self.assertEqual(
            service.update_takeoffs_condition(["linear-takeoff", "missing"], "linear"),
            [],
        )
        self.assertEqual(linear.condition_uid, "linear")

    def test_direct_condition_update_allows_compatible_selection(self):
        conditions = {
            "linear-a": _condition("linear-a", Condition.TYPE_LINEAR),
            "linear-b": _condition("linear-b", Condition.TYPE_LINEAR),
        }
        takeoff = _takeoff("takeoff", condition_uid="linear-a")
        service = ProjectDataService(_AreaUsageModel([takeoff], conditions))
        page_uids = service.update_takeoffs_condition(["takeoff"], "linear-b")
        self.assertEqual(page_uids, ["page-1"])
        self.assertEqual(takeoff.condition_uid, "linear-b")

    def test_visible_renderable_unassigned_takeoff_bolds_unassigned_area(self):
        conditions = {
            "condition-count": _condition("condition-count", Condition.TYPE_COUNT)
        }
        takeoffs = [
            _takeoff(
                "takeoff-1",
                condition_uid="condition-count",
                area_uid="0",
                position=[10.0, 20.0],
            )
        ]
        service = ProjectDataService(_AreaUsageModel(takeoffs, conditions))
        self.assertEqual(service.get_area_uids_with_takeoff(), {"0"})

    def test_unrenderable_unassigned_takeoff_does_not_bold_unassigned_area(self):
        conditions = {
            "condition-area": _condition("condition-area", Condition.TYPE_AREA)
        }
        takeoffs = [
            _takeoff(
                "stale-takeoff",
                condition_uid="condition-area",
                area_uid="0",
                position=[10.0, 20.0, 30.0, 40.0],
            )
        ]
        service = ProjectDataService(_AreaUsageModel(takeoffs, conditions))
        self.assertEqual(service.get_area_uids_with_takeoff(), set())

    def test_hidden_condition_takeoff_does_not_bold_unassigned_area(self):
        conditions = {
            "condition-area": _condition(
                "condition-area",
                Condition.TYPE_AREA,
                layer_visible=False,
            )
        }
        takeoffs = [
            _takeoff(
                "hidden-takeoff",
                condition_uid="condition-area",
                area_uid="0",
                position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
            )
        ]
        service = ProjectDataService(_AreaUsageModel(takeoffs, conditions))
        self.assertEqual(service.get_area_uids_with_takeoff(), set())

    def test_takeoff_with_missing_condition_does_not_bold_unassigned_area(self):
        takeoffs = [
            _takeoff(
                "orphaned-condition-takeoff",
                condition_uid="missing-condition",
                area_uid="0",
                position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
            )
        ]
        service = ProjectDataService(_AreaUsageModel(takeoffs, {}))
        self.assertEqual(service.get_area_uids_with_takeoff(), set())

    def test_hole_row_does_not_independently_bold_unassigned_area(self):
        conditions = {
            "condition-area": _condition("condition-area", Condition.TYPE_AREA)
        }
        takeoffs = [
            _takeoff(
                "parent-area",
                condition_uid="condition-area",
                area_uid="area-1",
                position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0],
            ),
            _takeoff(
                "hole-row",
                condition_uid="condition-area",
                area_uid="0",
                position=[5.0, 5.0, 10.0, 5.0, 10.0, 10.0],
                parent_uid="parent-area",
            ),
        ]
        service = ProjectDataService(_AreaUsageModel(takeoffs, conditions))
        self.assertEqual(service.get_area_uids_with_takeoff(), {"area-1"})

    def test_stored_area_usage_keeps_delete_protection_separate_from_combo_bold(self):
        conditions = {
            "condition-area": _condition(
                "condition-area",
                Condition.TYPE_AREA,
                layer_visible=False,
            )
        }
        takeoffs = [
            _takeoff(
                "hidden-assigned-takeoff",
                condition_uid="condition-area",
                area_uid="area-1",
                position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0],
            )
        ]
        service = ProjectDataService(_AreaUsageModel(takeoffs, conditions))
        self.assertEqual(service.get_area_uids_with_takeoff(), set())
        self.assertEqual(
            service.get_assigned_area_uids_with_stored_takeoff(),
            {"area-1"},
        )

    def test_page_area_usage_uses_same_relevance_filter(self):
        conditions = {
            "condition-count": _condition("condition-count", Condition.TYPE_COUNT),
            "condition-area": _condition("condition-area", Condition.TYPE_AREA),
        }
        bid_takeoffs = [
            _takeoff(
                "valid-unassigned",
                condition_uid="condition-count",
                area_uid="0",
                position=[1.0, 2.0],
            ),
            _takeoff(
                "invalid-unassigned",
                condition_uid="condition-area",
                area_uid="0",
                position=[],
            ),
            _takeoff(
                "assigned-area",
                condition_uid="condition-area",
                area_uid="area-1",
                position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0],
            ),
        ]
        service = ProjectDataService(_AreaUsageModel(bid_takeoffs, conditions))
        self.assertEqual(
            service.get_area_uids_with_takeoff_for_page("page-1"),
            {"0", "area-1"},
        )


if __name__ == "__main__":
    unittest.main()
