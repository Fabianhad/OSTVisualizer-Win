import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
)
from ost_visualizer.presentation.modes.cursor import CURSOR_MODE_SELECT
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
        self.assertEqual({takeoff.page_uid for takeoff in pasted_takeoffs}, {"p2"})
        # Both selected page-1 takeoffs are pasted, translated by one common
        # offset from the paste anchor (t1 -> (100, 200), t2 keeps its delta).
        self.assertEqual(
            sorted(takeoff.position for takeoff in pasted_takeoffs),
            [[100.0, 200.0, 140.0, 200.0], [115.0, 215.0]],
        )
        self.assertEqual({takeoff.condition_uid for takeoff in pasted_takeoffs}, {"42"})
        # Page-1 text and hotlink are pasted onto page 2 the same way; the Named
        # View is not part of a copy.
        pasted_annotations = sorted(
            (a.annotation_type, a.page_uid, tuple(a.position))
            for a in harness.data.annotations
            if a.uid.startswith("ann-")
        )
        self.assertEqual(
            pasted_annotations,
            [
                (ANNOTATION_TYPE_HOTLINK, "p2", (110.0, 210.0)),
                ("text", "p2", (95.0, 195.0, 45.0, 15.0)),
            ],
        )
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
        failed_delete_calls = []

        def failing_delete(db_path, uids, *args, **kwargs):
            failed_delete_calls.append((db_path, list(uids)))
            # A refresh triggered by the attempted write drops the selection;
            # the handler must put it back when the write reports failure.
            harness.plan_view.clear_selection()
            return False

        harness.write.delete_takeoffs = failing_delete
        undo_depth = len(harness.undo._undo_stack)
        try:
            harness.plan_view.set_selected_uids({"t1"})
            harness.handler.on_elements_deleted(["t1"])
        finally:
            harness.write.delete_takeoffs = original_delete
        _pump_events()
        # The handler really attempted the write; its failure leaves no undo
        # entry behind and restores the selection.
        self.assertEqual(failed_delete_calls, [("bid.mdb", ["t1"])])
        self.assertEqual(len(harness.undo._undo_stack), undo_depth)
        self.assertIn("t1", harness.data.takeoffs)
        self.assertEqual(harness.plan_view.selected, {"t1"})
        harness._assert_invariants()
        # Positive control: the same delete with a succeeding writer records
        # exactly one undo entry.
        harness.handler.on_elements_deleted(["t1"])
        _pump_events()
        self.assertEqual(harness.write.delete_calls[-1][:2], ("bid.mdb", ["t1"]))
        self.assertEqual(len(harness.undo._undo_stack), undo_depth + 1)

    def test_plan_view_render_failure_then_page_switch_clears_preview_and_stale_state(
        self,
    ):
        # Seed 9004 enters hotlink placement and the pointer lands on the page,
        # so a live placement preview exists before the failing load below.
        harness = PresentationChaosHarness(9004, self)
        try:
            harness.run_sequence(
                ["enter_annotation_placement", "mouse_move_during_placement"]
            )
            self.assertEqual(
                harness.view.annotation_place_type, ANNOTATION_TYPE_HOTLINK
            )
            self.assertEqual(len(harness.view._place_preview_items), 1)
            first_page_uid = harness.state.active_page_uid
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
            self.assertNotEqual(first_page_uid, "p2")
            request_id, request = harness.rendering_service.page_requests.pop()
            with self.assertLogs(level="WARNING") as render_logs:
                request["callback"](RenderResult(request_id, False, None, "missing"))
            self.assertTrue(
                any(
                    "Page render failed: missing" in line for line in render_logs.output
                )
            )
            _pump_events()
            # The failed render leaves the loaded page current and the stale
            # preview gone, not a half-applied placement.
            self.assertEqual(harness.view.current_page_uid, "p2")
            self.assertEqual(harness.view._place_preview_items, [])
            harness.run_sequence(["switch_page", "refresh_overlays"])
            self.assertEqual(
                harness.view.current_page_uid, harness.state.active_page_uid
            )
            self.assertEqual(harness.view._place_preview_items, [])
            harness.run_sequence(["cancel_placement"])
            self.assertIsNone(harness.view.annotation_place_type)
            self.assertEqual(harness.view._cursor_mode, CURSOR_MODE_SELECT)
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
        self.assertEqual(coordinator.coordinator._dirty_mesh_page_uids, set())
        # Switching to 3D refreshed the mesh for the changed page; once the
        # selected pages were deleted, the next takeoff change refreshed it for
        # the now empty selection and dropped the cached native scene.
        self.assertEqual(
            coordinator.coordinator.visualization_service.mesh_pages,
            [["page-1"], []],
        )
        self.assertIsNone(coordinator.coordinator._last_mesh_scene)
        self.assertEqual(
            coordinator.coordinator._viewer.plan_pages, ["page-1", "page-1"]
        )
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
            # Deterministic outcome check (the random harness above picks the
            # bid to cancel by seed): a cancelled Bid selection is never written,
            # and a failed selected-page write is abandoned, not retried.
            manager, service = deferred.manager, deferred.service
            service.expected_blocked = False
            service.calls.clear()
            manager.cancel_for_file("chaos.mdb")
            self.assertEqual(manager.pending_count, 0)
            manager.schedule_bid_selected_page("chaos.mdb", "b1", "p2")
            manager.schedule_bid_selected_page("chaos.mdb", "b2", "p1")
            manager.cancel_bid_selected_pages("chaos.mdb", ["b2"])
            self.assertEqual(manager.pending_count, 1)
            service.fail_next = True
            self.assertTrue(manager.flush())
            self.assertEqual(manager.pending_count, 0)
            self.assertTrue(manager.flush())
            self.assertEqual(
                service.calls,
                [("bid_selected_page", "chaos.mdb", "b1", "p2")],
            )
        finally:
            deferred.cleanup()
        detached = DetachedWindowChaosHarness(11205, self)
        first_window = detached.window
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
        # The window was retargeted p1 -> p2 on the first delete; while it was
        # closed it received nothing, and reopening after the second delete
        # (p2 gone) retargets the view to the only remaining page.
        self.assertEqual(first_window.page_updates, ["p1", "p2", "p2", "p2"])
        self.assertEqual(detached.window.page_updates, ["p3", "p3"])
        self.assertEqual(detached.view.target_page_uid, "p3")
        self.assertEqual(detached.repository.update_calls, [("p2", None), ("p3", None)])
