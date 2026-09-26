import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from PySide6.QtWidgets import QApplication
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    MutationOutcomeStatus,
    PlanItemsPastePayload,
    QueuedMutationResult,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    annotation_resource_id,
)
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.services.selection_clipboard_service import (
    SelectionClipboardService,
)
from tests import test_plan_property_history_identity as history_fixture
from tests import test_takeoff_lifecycle_placement as placement_fixture
from tests import test_text_annotation_lifecycle as text_fixture
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)


class CrossSystemWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def mixed_handler(self, queued=False):
        handler, data, write, undo = (
            history_fixture.PlanPropertyHistoryIdentityTests().make_handler()
        )
        # These workflows exercise placement ownership/history, independent of
        # the host font catalog (other fixtures install a minimal catalog).
        handler._default_takeoff_label_extras = lambda: {}
        write.sql_collaboration_mutations = queued
        data.pages["p1"].scale_factor1 = 0.125
        data.pages["p1"].scale_factor2 = 12
        data.takeoffs["parent"].position = [0, 0, 96, 0, 96, 96, 0, 96]
        annotation = BidAnnotation(
            uid="text",
            annotation_type="text",
            page_uid="p1",
            position=[24, 24, 48, 24],
            properties={"Text": "Room A"},
        )
        data.annotations.append(annotation)
        handler._plan_view.annotations["text"] = annotation
        handler._plan_view.annotation_key_map[("text", "text")] = "text"
        return handler, data, write, undo

    def test_child_and_annotation_copy_paste_stays_one_atomic_workflow(self):
        for queued in (False, True):
            for valid_child in (False, True):
                with self.subTest(queued=queued, valid_child=valid_child):
                    handler, data, write, undo = self.mixed_handler(queued)
                    handler._plan_view.intelligent_paste_enabled = False
                    preview = (
                        placement_fixture.TakeoffLifecyclePlacementTests().harness(
                            Condition.TYPE_AREA, (0, 0), (1, 1), backout=True
                        )
                    )
                    preview._current_conditions = data.conditions
                    preview._current_takeoffs = {"parent": data.takeoffs["parent"]}
                    handler._plan_view.resolve_pasted_child_parents = (
                        preview.resolve_pasted_child_parents
                    )
                    if not valid_child:
                        data.takeoffs["child"].position = [200, 200, 210, 200, 210, 210]
                    handler._clipboard_svc = SelectionClipboardService()
                    handler.on_copy_requested(["child", "text"])
                    self.assertEqual(len(handler._clipboard_svc.items), 1)
                    self.assertEqual(len(handler._clipboard_svc.annotations), 1)
                    self.assertFalse(undo.can_undo())
                    handler.on_paste_requested()
                    self.assertEqual(handler._plan_view.paste_backout_calls, [])
                    requests = write.queued_pastes if queued else write.local_pastes
                    self.assertEqual(len(requests), 1 if valid_child else 0)
                    if valid_child:
                        payload = requests[-1][1]
                        self.assertEqual(len(payload.takeoff_specs), 1)
                        self.assertEqual(len(payload.annotation_specs), 1)
                        self.assertEqual(payload.takeoff_specs[0].parent_uid, "parent")
                        self.assertEqual(
                            payload.annotation_specs[0].properties["Text"], "Room A"
                        )
                    else:
                        self.assertFalse(undo.can_undo())
                    self.assertEqual(write.reloads, [])

    def test_mixed_delete_then_scale_then_undo_restores_current_paper_geometry(self):
        for queued in (False, True):
            with self.subTest(queued=queued):
                handler, data, write, undo = self.mixed_handler(queued)
                handler.on_elements_deleted(["parent", "text"])
                if queued:
                    self.assertFalse(undo.can_undo())
                    data.takeoffs.clear()
                    data.annotations.clear()
                    write.queued_deletes[-1][-1](
                        history_fixture.PlanPropertyHistoryIdentityTests.committed()
                    )
                self.assertTrue(undo.can_undo())
                self.assertEqual(data.takeoffs, {})
                self.assertEqual(data.annotations, [])
                data.pages["p1"].scale_factor1 = 0.25
                undo.undo()
                requests = write.queued_pastes if queued else write.local_pastes
                payload = requests[-1][1]
                self.assertEqual(
                    payload.takeoff_specs[0].position, [0, 0, 48, 0, 48, 48, 0, 48]
                )
                self.assertEqual(payload.annotation_specs[0].position, [12, 12, 24, 12])
                self.assertEqual(
                    payload.annotation_specs[0].properties["Text"], "Room A"
                )
                self.assertEqual(write.reloads, [])

    def test_queued_mixed_paste_scale_before_completion_then_undo_redo(self):
        handler, data, write, undo = self.mixed_handler(True)
        source_annotation = annotation_resource_id("text", "source-ann")
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("source",),
            takeoff_specs=(
                InsertTakeoffSpec("c1", "p1", "0", [24, 24, 48, 24, 48, 48]),
            ),
            annotation_source_uids=(source_annotation,),
            annotation_specs=(
                InsertAnnotationSpec(
                    "p1",
                    "text",
                    [24, 24, 48, 24],
                    "#000000",
                    1,
                    properties={"Text": "Copied"},
                ),
            ),
        )
        bid_ref = handler._ui_state.get_selected_bid_ref()
        handler._queue_sql_plan_items_paste_payload(bid_ref, "p1", payload, ())
        self.assertFalse(undo.can_undo())
        data.pages["p1"].scale_factor1 = 0.25
        data.takeoffs["new"] = Takeoff(
            uid="new",
            condition_uid="c1",
            page_uid="p1",
            position=[12, 12, 24, 12, 24, 24],
        )
        data.annotations.append(
            BidAnnotation(
                uid="new-ann",
                annotation_type="text",
                page_uid="p1",
                position=[12, 12, 24, 12],
                properties={"Text": "Copied"},
            )
        )
        write.queued_pastes[-1][-1](
            history_fixture.PlanPropertyHistoryIdentityTests.committed(
                AuthoritativeMutationResult(
                    created_uid_maps=(
                        ("takeoffs", (("source", "new"),)),
                        ("annotations", ((source_annotation, "new-ann"),)),
                    )
                )
            )
        )
        self.assertTrue(undo.can_undo())
        undo.undo()
        data.takeoffs.pop("new")
        data.annotations = [item for item in data.annotations if item.uid != "new-ann"]
        write.queued_deletes[-1][-1](
            history_fixture.PlanPropertyHistoryIdentityTests.committed()
        )
        undo.redo()
        replay = write.queued_pastes[-1][1]
        self.assertEqual(replay.takeoff_specs[0].position, [12, 12, 24, 12, 24, 24])
        self.assertEqual(replay.annotation_specs[0].position, [12, 12, 24, 12])

    def test_queued_placement_after_annotation_selection_keeps_newer_intent(self):
        for newer_intent in ("selection", "tool", "cleanup"):
            with self.subTest(newer_intent=newer_intent):
                handler, data, write, undo = self.mixed_handler(True)
                handler.on_takeoff_created("c1", [24, 24, 48, 24, 48, 48], "p1")
                operation_id, callback = write.queued_takeoff_callbacks[-1]
                self.assertFalse(undo.can_undo())
                if newer_intent == "selection":
                    handler._plan_view.set_selected_uids({"text"})
                elif newer_intent == "tool":
                    handler._plan_view.tool_revision += 1
                else:
                    handler._plan_view._is_cleaning_up = True
                expected_selection = handler._plan_view.get_selected_uids()
                data.takeoffs["placed"] = Takeoff(
                    uid="placed",
                    condition_uid="c1",
                    page_uid="p1",
                    position=[24, 24, 48, 24, 48, 48],
                )
                callback(
                    QueuedMutationResult(
                        database_id="bid.mdb",
                        runtime_generation=3,
                        operation_id=operation_id,
                        outcome_status=MutationOutcomeStatus.COMMITTED,
                        created_resource_ids=("placed",),
                    )
                )
                self.assertEqual(handler._plan_view.selected, expected_selection)
                self.assertTrue(undo.can_undo())
                self.assertEqual(handler._pending_plan_takeoff_uids_by_bid, {})
                if newer_intent != "cleanup":
                    self.assertEqual(handler._plan_view.pending_mutation_uids, set())

    def test_failed_queued_placement_after_bid_switch_cannot_refresh_new_bid(self):
        handler, data, write, undo = self.mixed_handler(True)
        handler.on_takeoff_created("c1", [24, 24, 48, 24, 48, 48], "p1")
        operation_id, callback = write.queued_takeoff_callbacks[-1]
        handler.hide_pending_takeoff_placement_previews()
        handler._ui_state.get_selected_bid_ref = lambda: BidRef("bid.mdb", "8")
        undo.set_active_bid(BidRef("bid.mdb", "8"))
        data.takeoffs = {
            "parent": Takeoff(
                uid="parent", condition_uid="c1", page_uid="p1", position=[100, 100]
            )
        }
        handler._plan_view.set_selected_uids({"parent"})
        handler._event_bus.events.clear()
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            )
        )
        self.assertFalse(
            any(
                event == AppEvents.TAKEOFFS_CHANGED
                for event, _payload in handler._event_bus.events
            )
        )
        self.assertEqual(data.takeoffs["parent"].position, [100, 100])
        self.assertEqual(handler._plan_view.selected, {"parent"})
        self.assertFalse(undo.can_undo())

    def test_queued_takeoff_placement_scale_then_undo_redo_preserves_paper_size(self):
        handler, data, write, undo = self.mixed_handler(True)
        handler.on_takeoff_created("c1", [24, 24, 48, 24, 48, 48], "p1")
        operation_id, callback = write.queued_takeoff_callbacks[-1]
        data.takeoffs["placed"] = Takeoff(
            uid="placed",
            condition_uid="c1",
            page_uid="p1",
            position=[12, 12, 24, 12, 24, 24],
        )
        data.pages["p1"].scale_factor1 = 0.25
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("placed",),
            )
        )
        undo.undo()
        data.takeoffs.pop("placed")
        write.queued_deletes[-1][-1](
            history_fixture.PlanPropertyHistoryIdentityTests.committed()
        )
        undo.redo()
        self.assertEqual(write.calls[-1][2][0].position, [12, 12, 24, 12, 24, 24])

    def test_queued_annotation_placement_scale_then_undo_redo(self):
        handler, data, write, undo = self.mixed_handler(True)
        handler.on_annotation_created("dimension", [24, 24, 48, 24], "p1")
        payload = write.queued_pastes[-1][1]
        self.assertFalse(undo.can_undo())
        data.pages["p1"].scale_factor1 = 0.25
        data.annotations.append(
            BidAnnotation(
                uid="placed",
                annotation_type="dimension",
                page_uid="p1",
                position=[12, 12, 24, 12],
            )
        )
        write.queued_pastes[-1][-1](
            history_fixture.PlanPropertyHistoryIdentityTests.committed(
                AuthoritativeMutationResult(
                    created_uid_maps=(
                        (
                            "annotations",
                            ((payload.annotation_source_uids[0], "placed"),),
                        ),
                    )
                )
            )
        )
        self.assertTrue(undo.can_undo())
        undo.undo()
        data.annotations = [item for item in data.annotations if item.uid != "placed"]
        write.queued_deletes[-1][-1](
            history_fixture.PlanPropertyHistoryIdentityTests.committed()
        )
        undo.redo()
        self.assertEqual(
            write.queued_pastes[-1][1].annotation_specs[0].position, [12, 12, 24, 12]
        )

    def test_cancel_executing_placement_then_select_annotation_then_delete_failure(
        self,
    ):
        handler, data, write, undo = self.mixed_handler(True)
        write.cancel_queued_mutation_result = False
        handler.on_takeoff_created("c1", [24, 24, 48, 24, 48, 48], "p1")
        operation_id, callback = write.queued_takeoff_callbacks[-1]
        pending_uid = handler._pending_takeoff_placements[operation_id].pending_uids[0]
        handler.on_elements_deleted([pending_uid])
        data.takeoffs["placed"] = Takeoff(
            uid="placed",
            condition_uid="c1",
            page_uid="p1",
            position=[24, 24, 48, 24, 48, 48],
        )
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("placed",),
            )
        )
        self.assertEqual(write.queued_deletes[-1][2], ["placed"])
        self.assertFalse(undo.can_undo())
        handler._plan_view.set_selected_uids({"text"})
        write.queued_deletes[-1][-1](
            replace(
                history_fixture.PlanPropertyHistoryIdentityTests.committed(),
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            )
        )
        self.assertEqual(handler._plan_view.selected, {"text"})
        self.assertIn("placed", data.takeoffs)
        self.assertEqual(handler._plan_view.pending_mutation_uids, set())

    def test_queued_mixed_move_then_scale_then_history_keeps_families_aligned(self):
        handler, data, write, undo = self.mixed_handler(True)
        takeoff_old = list(data.takeoffs["parent"].position)
        takeoff_new = [value + 24 for value in takeoff_old]
        annotation_old = list(data.annotations[0].position)
        annotation_new = [value + 24 for value in annotation_old]
        handler.on_positions_flushed(
            [("parent", takeoff_old, takeoff_new)],
            [("text", "text", annotation_old, annotation_new)],
        )
        self.assertFalse(undo.can_undo())
        data.pages["p1"].scale_factor1 = 0.25
        data.takeoffs["parent"].position = [value / 2 for value in takeoff_new]
        data.annotations[0].position = [value / 2 for value in annotation_new]
        write.queued_geometry[-1][-1](
            history_fixture.PlanPropertyHistoryIdentityTests.committed()
        )
        self.assertTrue(undo.can_undo())
        undo.undo()
        changes = write.queued_geometry[-1][2]
        self.assertEqual(
            changes["takeoff_positions"],
            [("parent", [value / 2 for value in takeoff_old])],
        )
        self.assertEqual(
            changes["annotation_positions"],
            [("text", "text", [value / 2 for value in annotation_old])],
        )

    def test_old_bid_geometry_completion_keeps_new_bid_pending_plan_and_mesh(self):
        handler, data, write, undo = self.mixed_handler(True)
        active_bid = [BidRef("bid.mdb", "7")]
        handler._ui_state.get_selected_bid_ref = lambda: active_bid[0]
        mesh = Mock()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = handler._ui_state
        coordinator._pending_3d_takeoff_uids_by_bid = {}
        coordinator._native_3d_views = lambda: [mesh]
        original_publish = handler._event_bus.publish

        def publish(event, **payload):
            original_publish(event, **payload)
            if event == AppEvents.PENDING_PLAN_MUTATIONS_CHANGED:
                coordinator._on_pending_plan_mutations_changed(**payload)

        handler._event_bus.publish = publish
        old = list(data.takeoffs["parent"].position)
        handler.on_positions_flushed([("parent", old, [v + 2 for v in old])], [])
        completion_a = write.queued_geometry[-1][-1]
        self.assertEqual(handler._plan_view.pending_mutation_uids, {"parent"})
        active_bid[0] = BidRef("bid.mdb", "8")
        undo.set_active_bid(active_bid[0])
        data.takeoffs["parent"] = replace(
            data.takeoffs["parent"], position=[v + 100 for v in old]
        )
        old_b = list(data.takeoffs["parent"].position)
        handler.on_positions_flushed([("parent", old_b, [v + 2 for v in old_b])], [])
        self.assertEqual(handler._plan_view.pending_mutation_uids, {"parent"})
        mesh.reset_mock()
        completion_a(history_fixture.PlanPropertyHistoryIdentityTests.committed())
        self.assertEqual(handler._plan_view.pending_mutation_uids, {"parent"})
        mesh.set_pending_mutation_uids.assert_not_called()
        self.assertFalse(undo.can_undo())

    def test_interleaved_placement_unknown_result_and_reverse_completion_order(self):
        handler, data, write, undo = self.mixed_handler(True)
        position = [24, 24, 48, 24, 48, 48]
        handler.on_takeoff_created("c1", position, "p1")
        operation_id, takeoff_complete = write.queued_takeoff_callbacks[-1]
        position[:] = [999, 999]
        result = QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=3,
            operation_id=operation_id,
            outcome_status=MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
        )
        takeoff_complete(result)
        self.assertFalse(undo.can_undo())
        self.assertEqual(write.calls[-1][2][0].position, [24, 24, 48, 24, 48, 48])
        handler.on_annotation_created("dimension", [24, 60, 48, 60], "p1")
        payload = write.queued_pastes[-1][1]
        data.annotations.append(
            BidAnnotation(
                "dimension", "dimension", page_uid="p1", position=[24, 60, 48, 60]
            )
        )
        write.queued_pastes[-1][-1](
            history_fixture.PlanPropertyHistoryIdentityTests.committed(
                AuthoritativeMutationResult(
                    created_uid_maps=(
                        (
                            "annotations",
                            ((payload.annotation_source_uids[0], "dimension"),),
                        ),
                    )
                )
            )
        )
        self.assertFalse(undo.can_undo())
        handler._plan_view.set_selected_uids({"text"})
        data.takeoffs["placed"] = Takeoff(
            "placed", "c1", page_uid="p1", position=[24, 24, 48, 24, 48, 48]
        )
        takeoff_complete(
            replace(
                result,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("placed",),
            )
        )
        self.assertEqual(handler._plan_view.selected, {"text"})
        self.assertTrue(undo.can_undo())
        undo.undo()
        self.assertEqual(write.queued_deletes[-1][2], [])
        self.assertEqual(write.queued_deletes[-1][3], [("dimension", "dimension")])
        data.annotations = [
            item for item in data.annotations if item.uid != "dimension"
        ]
        write.queued_deletes[-1][-1](
            history_fixture.PlanPropertyHistoryIdentityTests.committed()
        )
        undo.undo()
        self.assertEqual(write.queued_deletes[-1][2], ["placed"])

    def test_external_page_replacement_then_failure_retry_does_not_repopulate_old_history(
        self,
    ):
        handler, data, write, undo = self.mixed_handler(True)
        handler.on_takeoff_created("c1", [24, 24, 48, 24, 48, 48], "p1")
        operation_id, callback = write.queued_takeoff_callbacks[-1]
        undo.clear()
        handler.hide_pending_takeoff_placement_previews()
        data.pages["p1"] = SimpleNamespace(**vars(data.pages["p1"]))
        handler._plan_view.set_selected_uids({"text"})
        data.takeoffs["placed"] = Takeoff(
            "placed", "c1", page_uid="p1", position=[24, 24, 48, 24, 48, 48]
        )
        callback(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("placed",),
            )
        )
        self.assertFalse(undo.can_undo())
        self.assertEqual(handler._plan_view.selected, {"text"})
        handler.on_takeoff_created("c1", [60, 24, 72, 24, 72, 48], "p1")
        failed_id, failed = write.queued_takeoff_callbacks[-1]
        failed(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=failed_id,
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            )
        )
        self.assertFalse(undo.can_undo())
        self.assertEqual(handler._pending_plan_takeoff_uids_by_bid, {})
        handler.on_takeoff_created("c1", [60, 24, 72, 24, 72, 48], "p1")
        retry_id, retry = write.queued_takeoff_callbacks[-1]
        data.takeoffs["retry"] = Takeoff(
            "retry", "c1", page_uid="p1", position=[60, 24, 72, 24, 72, 48]
        )
        retry(
            QueuedMutationResult(
                database_id="bid.mdb",
                runtime_generation=3,
                operation_id=retry_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                created_resource_ids=("retry",),
            )
        )
        self.assertTrue(undo.can_undo())
        self.assertEqual(handler._plan_view.selected, {"retry"})


class DetachedScaleWorkflowTests(unittest.TestCase):
    def test_real_plan_bid_navigation_clears_same_uid_pending_and_selection(self):
        case = text_fixture.DetachedTextHistoryTests()
        case.setUp()
        try:
            for plan in (case.fixture.main_plan, case.window.plan_view):
                with self.subTest(detached=plan is case.window.plan_view):
                    key = next(
                        iter(plan.find_annotation_keys_by_uid_type({("text", "text")}))
                    )
                    plan.set_selection_enabled(True)
                    plan.set_selected_uids({key})
                    plan.set_pending_mutation_uids({key})
                    replacement = replace(
                        case.fixture.data.annotations[0],
                        properties={"Text": "Another Bid"},
                    )
                    plan.load_page(
                        case.fixture.data.page,
                        [],
                        {},
                        {},
                        bid_ref=BidRef(case.fixture.bid_ref.file_path, "8"),
                        annotations=[replacement],
                    )
                    self.assertEqual(plan.get_pending_mutation_uids(), set())
                    self.assertEqual(set(plan.get_selected_uids()), set())
                    self.assertIs(
                        next(iter(plan._current_annotations.values())), replacement
                    )
        finally:
            case.doCleanups()

    def test_main_scale_during_detached_queued_edit_preserves_history_geometry(self):
        for operation in ("move", "insert", "delete"):
            with self.subTest(operation=operation):
                case = text_fixture.DetachedTextHistoryTests()
                case.setUp()
                try:
                    window, history, write = case.window, case.history, case.write
                    data, bid = case.fixture.data, case.fixture.bid_ref
                    data.page.scale_factor1, data.page.scale_factor2 = 1, 1
                    original = list(data.annotations[0].position)
                    if operation == "move":
                        moved = [value + 2 for value in original]
                        window._queue_sql_annotation_geometry(
                            bid.file_path, [("text", "text", original, moved)]
                        )
                    elif operation == "insert":
                        window._queue_sql_annotation_insert(
                            bid,
                            [
                                InsertAnnotationSpec(
                                    data.page.uid,
                                    "text",
                                    original,
                                    "#000000",
                                    1,
                                    properties={"Text": "Draft"},
                                )
                            ],
                        )
                    else:
                        window._queue_sql_annotation_delete(
                            bid,
                            [replace(data.annotations[0])],
                            set(),
                            {("text", "text")},
                        )
                    self.assertFalse(history.can_undo())
                    # Main applies the new Page calibration before the detached callback.
                    data.page.scale_factor2 = 2
                    if operation == "move":
                        data.annotations[0].position = [value * 2 for value in moved]
                        write.queued_geometry[-1][-1](
                            text_fixture.TextAnnotationHistoryTests.committed()
                        )
                    elif operation == "insert":
                        payload = write.queued_pastes[-1][1]
                        data.annotations.append(
                            BidAnnotation(
                                "placed",
                                "text",
                                page_uid=data.page.uid,
                                position=[value * 2 for value in original],
                                properties={"Text": "Draft"},
                            )
                        )
                        write.queued_pastes[-1][-1](
                            replace(
                                text_fixture.TextAnnotationHistoryTests.committed(),
                                authoritative_result=AuthoritativeMutationResult(
                                    created_uid_maps=(
                                        (
                                            "annotations",
                                            (
                                                (
                                                    payload.annotation_source_uids[0],
                                                    "placed",
                                                ),
                                            ),
                                        ),
                                    )
                                ),
                            )
                        )
                    else:
                        data.annotations.clear()
                        write.queued_deletes[-1][-1](
                            text_fixture.TextAnnotationHistoryTests.committed()
                        )
                    self.assertTrue(history.can_undo())
                    history.undo()
                    if operation == "insert":
                        data.annotations = [
                            item for item in data.annotations if item.uid != "placed"
                        ]
                        write.queued_deletes[-1][-1](
                            text_fixture.TextAnnotationHistoryTests.committed()
                        )
                        history.redo()
                    if operation == "move":
                        replay = write.queued_geometry[-1][2]["annotation_positions"][
                            0
                        ][2]
                    else:
                        replay = write.queued_pastes[-1][1].annotation_specs[0].position
                    self.assertEqual(replay, [value * 2 for value in original])
                finally:
                    case.doCleanups()


if __name__ == "__main__":
    unittest.main()
