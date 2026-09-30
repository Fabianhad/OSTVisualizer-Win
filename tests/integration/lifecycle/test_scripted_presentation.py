import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
)
from tests.presentation.managers.test_deferred_persistence_manager import (
    DeferredPersistenceChaosHarness,
)
from tests.presentation.managers.test_detached_page_view_manager import (
    DetachedWindowChaosHarness,
)
from tests.integration.history.test_action_chaos import (
    PlanViewActionHandlerChaosHarness,
    action_handler_module,
)
from tests.presentation.components.plan_view.test_view import (
    PresentationChaosHarness,
    _chaos_app as _app,
)
from tests.presentation.coordinators.test_ui_event_coordinator import (
    UIEventCoordinatorChaosHarness,
)


def _pump_events(rounds: int = 3) -> None:
    app = _app()
    for _ in range(rounds):
        app.processEvents()


class PresentationScriptedWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_long_copy_paste_named_view_delete_and_write_failure_workflow(self):
        harness = PlanViewActionHandlerChaosHarness(11201, self)
        harness.run_sequence(
            ["select_all_current", "copy_selection", "switch_page", "paste_clipboard"]
        )
        _pump_events()
        pasted_takeoffs = [
            takeoff
            for uid, takeoff in harness.data.takeoffs.items()
            if uid not in {"t1", "t2", "t3"}
        ]
        self.assertTrue(pasted_takeoffs)
        self.assertEqual({takeoff.page_uid for takeoff in pasted_takeoffs}, {"p2"})
        harness._assert_invariants()
        harness._sync_plan_view_to_page("p1")
        harness.plan_view.set_selected_uids({"p1-named"})
        with mock.patch.object(action_handler_module, "confirm", return_value=False):
            harness.handler.on_elements_deleted(["p1-named"])
        _pump_events()
        remaining = {(a.uid, a.annotation_type) for a in harness.data.annotations}
        self.assertIn(("p1-named", ANNOTATION_TYPE_NAMED_VIEW), remaining)
        self.assertIn(("p1-hotlink", ANNOTATION_TYPE_HOTLINK), remaining)
        harness._assert_invariants()
        with mock.patch.object(action_handler_module, "confirm", return_value=True):
            harness.handler.on_elements_deleted(["p1-named"])
        _pump_events()
        harness._sync_plan_view_to_page("p1")
        harness._assert_invariants()
        remaining = {(a.uid, a.annotation_type) for a in harness.data.annotations}
        self.assertNotIn(("p1-named", ANNOTATION_TYPE_NAMED_VIEW), remaining)
        self.assertNotIn(("p1-hotlink", ANNOTATION_TYPE_HOTLINK), remaining)
        original_delete = harness.write.delete_takeoffs
        harness.write.delete_takeoffs = lambda *args, **kwargs: False
        try:
            harness.plan_view.set_selected_uids({"t1"})
            harness.handler.on_elements_deleted(["t1"])
        finally:
            harness.write.delete_takeoffs = original_delete
        _pump_events()
        self.assertIn("t1", harness.data.takeoffs)
        self.assertEqual(harness.plan_view.selected, {"t1"})
        harness._assert_invariants()

    def test_plan_view_render_failure_then_page_switch_clears_preview_and_stale_state(
        self,
    ):
        harness = PresentationChaosHarness(11202, self)
        try:
            harness.run_sequence(
                ["enter_annotation_placement", "mouse_move_during_placement"]
            )
            harness.state.active_page_uid = "p2"
            page = harness.state.active_page
            self.assertTrue(
                harness.view.load_page(
                    page,
                    harness.state.active_takeoffs(),
                    harness.state.conditions,
                    {},
                    bid_ref=harness.state.bid_ref,
                    annotations=harness.state.active_annotations(),
                    hidden_layer_uids=harness.state.hidden_layer_uids,
                )
            )
            request_id, request = harness.rendering_service.page_requests.pop()
            request["callback"](RenderResult(request_id, False, None, "missing"))
            _pump_events()
            harness.run_sequence(
                ["switch_page", "cancel_placement", "refresh_overlays"]
            )
            self.assertIsNone(harness.view.annotation_place_type)
            self.assertEqual(harness.view._place_preview_items, [])
        finally:
            harness.cleanup()

    def test_coordinator_deferred_and_detached_event_order_after_deletes(self):
        coordinator = UIEventCoordinatorChaosHarness(11203, self)
        coordinator.run_sequence(
            [
                "switch_to_2d_view",
                "takeoffs_changed_active_page",
                "switch_to_3d_view",
                "native_scene_updated",
                "clear_selected_pages",
                "takeoffs_changed_active_page",
            ]
        )
        _pump_events()
        self.assertFalse(coordinator.coordinator._mesh_scene_dirty)
        coordinator._assert_invariants()
        deferred = DeferredPersistenceChaosHarness(11204, self)
        try:
            deferred.run_sequence(
                [
                    "schedule_bid_selected_page",
                    "cancel_deleting_bid_selected_page",
                    "fail_next_write",
                    "schedule_layer_visibility",
                    "flush",
                    "toggle_expected_block",
                    "flush_for_file",
                ]
            )
            deferred._assert_invariants()
        finally:
            deferred.cleanup()
        detached = DetachedWindowChaosHarness(11205, self)
        detached.run_sequence(
            [
                "database_refresh_matching_file",
                "delete_active_page",
                "refresh_window",
                "annotations_changed_current_page",
                "close_window",
                "delete_active_page",
                "reopen_window",
                "refresh_window",
            ]
        )
        _pump_events()
        detached._assert_invariants()
