import unittest
from dataclasses import replace
from unittest.mock import Mock, patch
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    ConcurrencyToken,
    DatabaseMutationResult,
    DurableOperationResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
)
from ost_visualizer.application.dtos.condition_takeoff_reassignment import (
    ConditionTakeoffReassignment,
)
from ost_visualizer.application.dtos.write_reload_result import WriteReloadResult
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.components import conditions_sidebar as sidebar_module
from ost_visualizer.presentation.handlers.condition_action_handler import (
    ConditionActionHandler,
)
from ost_visualizer.presentation.handlers.plan_view_action_handler import (
    PlanViewActionHandler,
)
from ost_visualizer.presentation.managers.ui_access_manager import (
    PlanSurfaceAccessState,
)
from ost_visualizer.presentation.services.undo_redo_service import UndoRedoService
from PySide6 import QtWidgets
from shiboken6 import delete
import tests.integration.selection.test_condition_objects as selection_tests


class ConditionDuplicateReassignmentTests(unittest.TestCase):
    make_plan = selection_tests.ConditionObjectSelectionTests.make_plan
    load_page = selection_tests.ConditionObjectSelectionTests.load_page
    takeoff = staticmethod(selection_tests.ConditionObjectSelectionTests.takeoff)

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        selection_tests.ConditionObjectSelectionTests.setUp(self)
        self.model.find_bid_info(self.bid_ref).uid = "7"
        self.bid_ref = BidRef(self.bid_ref.file_path, "7")
        self.model.current_bid_ref = self.bid_ref
        self.model.current_bid.uid = "7"
        self.load_page(self.plan, self.page)
        self.access.is_allowed.return_value = True
        self.access.get_plan_surface_access.return_value = PlanSurfaceAccessState(
            can_select_plan_items=True, can_edit_plan_items=True
        )
        self.sidebar.set_duplicate_enabled(True)
        self.write = Mock()
        self.write.uses_sql_collaboration_mutations.return_value = False
        self.write.duplicate_conditions_result.return_value = WriteReloadResult(
            ["new"], write_success=True, reload_success=True
        )
        self.undo = UndoRedoService()
        self.undo.set_active_bid(self.bid_ref)
        self.plan_handler = PlanViewActionHandler(
            self.plan,
            self.state,
            self.data,
            self.write,
            Mock(),
            Mock(),
            self.undo,
            Mock(),
            Mock(),
            self.access,
        )
        self.coordinator._plan_view_handler = self.plan_handler
        self.coordinator._deferred_persistence = Mock()
        self.coordinator._deferred_persistence.flush_for_file.return_value = True
        self.coordinator._placement = Mock()
        self.coordinator._sidebar = Mock()
        self.handler = ConditionActionHandler(
            self.coordinator, self.write, Mock(), self.data, self.state, Mock()
        )
        self.coordinator._condition_handler = self.handler
        self.coordinator.flush_deferred_for_file = Mock(return_value=True)
        self.coordinator.present_queued_mutation_error = Mock()
        self.sidebar.set_duplicate_reassign_command_factory(
            self.coordinator.prepare_condition_duplicate_reassignment
        )
        warning_patch = patch(
            "ost_visualizer.presentation.handlers.condition_action_handler.show_warning"
        )
        self.warning = warning_patch.start()
        self.addCleanup(warning_patch.stop)
        self.callback = None

    def open_menu(self, uid="target", during_menu=None):
        states = []

        def execute(menu, _position):
            names = [action.text() for action in menu.actions()]
            self.assertEqual(
                names[names.index("Duplicate") + 1], "Duplicate and Reassign Takeoff"
            )
            action = menu.actions()[names.index("Duplicate and Reassign Takeoff")]
            states.append(action.isEnabled())
            if during_menu:
                during_menu(action)

        item = self.sidebar._condition_items[uid]
        with patch.object(sidebar_module, "exec_transient_menu", side_effect=execute):
            self.sidebar._on_context_menu(
                self.sidebar.tree.visualItemRect(item).center()
            )
        self.assertEqual(len(states), 1)
        if during_menu:
            self.assertTrue(states[0])
        return states[0]

    def submit_sql(self):
        self.write.uses_sql_collaboration_mutations.return_value = True

        def submit(_path, _bid, _uids, callback, **_options):
            self.callback = callback
            return 1

        self.write.queue_conditions_duplicate.side_effect = submit
        self.assertTrue(self.open_menu(during_menu=lambda action: action.trigger()))
        self.assertIsNotNone(self.callback)

    def result(self, status=MutationOutcomeStatus.COMMITTED):
        return QueuedMutationResult(
            database_id=self.bid_ref.file_path,
            runtime_generation=1,
            operation_id="00000000-0000-0000-0000-000000000001",
            outcome_status=status,
            authoritative_result=(
                AuthoritativeMutationResult(created_resource_ids=("new",))
                if status == MutationOutcomeStatus.COMMITTED
                else None
            ),
        )

    def test_menu_position_and_loaded_page_enablement(self):
        self.assertTrue(self.open_menu())
        self.assertTrue(self.open_menu("other"))
        self.assertFalse(self.open_menu("unused"))
        self.assertFalse(self.open_menu("elsewhere"))
        self.write.assert_not_called()

    def test_invocation_uses_single_right_clicked_condition_and_all_matching_takeoffs(
        self,
    ):
        self.sidebar.highlight_conditions({"target", "other"})
        self.open_menu(during_menu=lambda action: action.trigger())
        args, options = self.write.duplicate_conditions_result.call_args
        self.assertEqual(args, (self.bid_ref.file_path, "7", ["target"]))
        self.assertEqual(
            options["reassign_takeoffs"],
            ConditionTakeoffReassignment("target", "p1", ("1", "2")),
        )
        self.write.duplicate_conditions_result.assert_called_once()
        self.write.save_takeoffs_condition.assert_not_called()
        self.coordinator.placement.enter.assert_called_once_with("new", ["new"])
        self.assertTrue(self.undo.can_undo())

    def test_same_uid_page_replacement_invalidates_action(self):
        self.open_menu(
            during_menu=lambda action: (
                self.model.set_pages({"p1": replace(self.page), "p2": self.other_page}),
                action.trigger(),
            )
        )
        self.write.duplicate_conditions_result.assert_not_called()

    def test_same_uid_condition_replacement_invalidates_action(self):
        self.open_menu(
            during_menu=lambda action: (
                self.conditions.update(target=replace(self.conditions["target"])),
                action.trigger(),
            )
        )
        self.write.duplicate_conditions_result.assert_not_called()

    def test_condition_deletion_invalidates_action(self):
        self.open_menu(
            during_menu=lambda action: (self.conditions.pop("target"), action.trigger())
        )
        self.write.duplicate_conditions_result.assert_not_called()

    def test_navigation_invalidates_action(self):
        self.open_menu(
            during_menu=lambda action: (
                self.load_page(self.plan, self.other_page),
                action.trigger(),
            )
        )
        self.write.duplicate_conditions_result.assert_not_called()

    def test_active_2d_loss_invalidates_action(self):
        def invoke(action):
            self.coordinator._toolbar.is_takeoff_2d_view_active.return_value = False
            action.trigger()

        self.open_menu(during_menu=invoke)
        self.write.duplicate_conditions_result.assert_not_called()
        self.assertFalse(self.open_menu())

    def test_new_tool_intent_invalidates_action(self):
        self.open_menu(
            during_menu=lambda action: (
                self.plan.set_cursor_mode("pan"),
                action.trigger(),
            )
        )
        self.write.duplicate_conditions_result.assert_not_called()

    def test_access_loss_invalidates_action(self):
        def invoke(action):
            self.access.is_allowed.return_value = False
            action.trigger()

        self.open_menu(during_menu=invoke)
        self.write.duplicate_conditions_result.assert_not_called()
        self.assertFalse(self.open_menu())

    def test_bid_replacement_invalidates_action(self):
        def invoke(action):
            self.model.current_bid = replace(self.model.current_bid)
            action.trigger()

        self.open_menu(during_menu=invoke)
        self.write.duplicate_conditions_result.assert_not_called()

    def test_sidebar_rebuild_invalidates_action(self):
        self.open_menu(
            during_menu=lambda action: (
                self.sidebar.load_conditions(self.conditions, {}, "Rebuilt"),
                action.trigger(),
            )
        )
        self.write.duplicate_conditions_result.assert_not_called()

    def test_revalidation_after_deferred_flush_rejects_replacement(self):
        def flush(_path):
            self.conditions["target"] = replace(self.conditions["target"])
            return True

        self.coordinator.flush_deferred_for_file.side_effect = flush
        self.open_menu(during_menu=lambda action: action.trigger())
        self.write.duplicate_conditions_result.assert_not_called()

    def test_pending_takeoffs_disable_action(self):
        self.plan.set_pending_mutation_uids({"1"})
        self.assertFalse(self.open_menu())

    def test_stale_plan_assignment_disables_action(self):
        self.page.takeoffs = [replace(self.page.takeoffs[-1], condition_uid="target")]
        self.assertFalse(self.open_menu())

    def test_no_matches_at_invocation_preserves_selection(self):
        self.plan.set_selected_uids({"3"})
        self.open_menu(
            during_menu=lambda action: (self.page.takeoffs.clear(), action.trigger())
        )
        self.assertEqual(self.plan.get_selected_uids(), ["3"])
        self.write.duplicate_conditions_result.assert_not_called()

    def test_mdb_failure_reports_without_history_or_placement(self):
        self.write.duplicate_conditions_result.return_value = WriteReloadResult([])
        self.open_menu(during_menu=lambda action: action.trigger())
        self.assertFalse(self.undo.can_undo())
        self.coordinator.placement.enter.assert_not_called()
        self.warning.assert_called_once()

    def test_sql_failure_releases_pending_items_and_history_barrier(self):
        self.undo.push_local(lambda: True, lambda: True)
        self.submit_sql()
        self.assertFalse(self.undo.can_undo())
        self.assertEqual(self.plan.get_pending_mutation_uids(), {"1", "2"})
        self.callback(self.result(MutationOutcomeStatus.FAILED_BEFORE_COMMIT))
        self.assertTrue(self.undo.can_undo())
        self.assertEqual(self.plan.get_pending_mutation_uids(), set())
        self.coordinator.placement.enter.assert_not_called()
        self.coordinator.present_queued_mutation_error.assert_called_once()

    def test_sql_failure_restores_selected_matching_takeoffs_with_other_selection(self):
        self.plan.set_selected_uids({"1", "3"})
        self.submit_sql()
        self.assertEqual(self.plan.get_selected_uids(), ["3"])
        self.callback(self.result(MutationOutcomeStatus.FAILED_BEFORE_COMMIT))
        self.assertEqual(self.plan.get_selected_uids(), ["1", "3"])
        self.coordinator.placement.enter.assert_not_called()

    def test_sql_success_with_matching_selection_finishes_normal_duplicate(self):
        self.plan.set_selected_uids({"1", "3"})
        self.submit_sql()
        self.callback(self.result())
        self.assertEqual(self.plan.get_selected_uids(), ["1", "3"])
        self.coordinator.placement.enter.assert_called_once_with("new", ["new"])

    def test_sql_submission_failure_releases_pending_items_and_history_barrier(self):
        self.undo.push_local(lambda: True, lambda: True)
        self.plan.set_selected_uids({"1", "3"})
        self.write.uses_sql_collaboration_mutations.return_value = True
        self.write.queue_conditions_duplicate.side_effect = RuntimeError(
            "not submitted"
        )
        self.open_menu(during_menu=lambda action: action.trigger())
        self.assertEqual(self.plan.get_pending_mutation_uids(), set())
        self.assertTrue(self.undo.can_undo())
        self.assertEqual(self.plan.get_selected_uids(), ["1", "3"])
        self.warning.assert_called_once()

    def test_sql_success_preserves_typed_selection_and_records_only_reassignment_history(
        self,
    ):
        annotation = BidAnnotation(
            uid="1",
            page_uid="p1",
            annotation_type=ANNOTATION_TYPE_TEXT,
            position=[0.0, 0.0, 20.0, 20.0],
        )
        self.load_page(self.plan, self.page, [annotation])
        keys = self.plan.find_annotation_keys_by_uid_type({("1", ANNOTATION_TYPE_TEXT)})
        self.plan.set_selected_uids({"3", *keys})
        self.submit_sql()
        self.callback(self.result())
        self.assertEqual(set(self.plan.get_selected_uids()), {"3", *keys})
        self.assertTrue(self.undo.can_undo())
        self.undo.undo()
        args = self.write.queue_plan_properties.call_args.args
        self.assertEqual(
            args[2:4], ("takeoff_condition", [("1", "target"), ("2", "target")])
        )
        self.write.queue_conditions_duplicate.assert_called_once()

    def test_sql_navigation_before_completion_cannot_project_to_other_page(self):
        self.submit_sql()
        self.state.active_page_uid = "p2"
        self.load_page(self.plan, self.other_page)
        self.plan.set_selected_uids({"4"})
        self.callback(self.result())
        self.assertEqual(self.plan.get_selected_uids(), ["4"])
        self.coordinator.placement.enter.assert_not_called()
        self.write.queue_conditions_duplicate.assert_called_once()
        self.write.queue_plan_properties.assert_not_called()

    def test_sql_page_replacement_before_completion_cannot_project_history_or_selection(
        self,
    ):
        self.submit_sql()
        replacement = replace(self.page)
        self.model.set_pages({"p1": replacement, "p2": self.other_page})
        self.load_page(self.plan, replacement)
        self.plan.set_selected_uids({"3"})
        self.callback(self.result())
        self.assertEqual(self.plan.get_selected_uids(), ["3"])
        self.assertFalse(self.undo.can_undo())
        self.coordinator.placement.enter.assert_not_called()

    def test_sql_unknown_commit_waits_for_reconciliation_without_second_write(self):
        self.submit_sql()
        self.callback(self.result(MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN))
        self.callback(self.result(MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED))
        self.assertEqual(self.plan.get_pending_mutation_uids(), {"1", "2"})
        self.callback(self.result())
        self.assertEqual(self.plan.get_pending_mutation_uids(), set())
        self.assertTrue(self.undo.can_undo())
        self.write.queue_conditions_duplicate.assert_called_once()

    def test_detached_surface_selection_is_untouched(self):
        detached = self.make_plan()
        self.load_page(detached, self.other_page)
        detached.set_selected_uids({"4"})
        self.open_menu(during_menu=lambda action: action.trigger())
        self.assertEqual(detached.get_selected_uids(), ["4"])

    def test_partial_stale_plan_projection_does_not_reassign_a_subset(self):
        # One matching Takeoff is hydrated before its new geometry reaches this Plan.
        self.page.takeoffs.append(self.takeoff("6", "target", "p1"))
        self.assertFalse(self.open_menu())

    def test_duplicate_sql_completion_does_not_repeat_placement_or_history(self):
        self.submit_sql()
        self.callback(self.result())
        self.callback(self.result())
        self.coordinator.placement.enter.assert_called_once()
        self.undo.undo()
        self.write.queue_plan_properties.assert_called_once()

    def test_destroyed_main_plan_rejects_sql_completion_without_qobject_access(self):
        self.submit_sql()
        self.plan.cleanup()
        delete(self.plan)
        self.coordinator._is_cleaning_up = True
        self.callback(self.result())
        self.coordinator.placement.enter.assert_not_called()

    def test_bid_replacement_before_sql_completion_cannot_install_history(self):
        self.submit_sql()
        self.model.current_bid = replace(self.model.current_bid)
        self.callback(self.result())
        self.assertFalse(self.undo.can_undo())
        self.coordinator.placement.enter.assert_not_called()

    def test_existing_duplicate_applies_its_terminal_completion_once(self):
        self.write.uses_sql_collaboration_mutations.return_value = True
        callbacks = []
        self.write.queue_conditions_duplicate.side_effect = (
            lambda _path, _bid, _uids, callback: callbacks.append(callback)
        )
        self.handler.on_duplicate_requested(["target"])
        callbacks[0](self.result())
        callbacks[0](self.result())
        self.coordinator.placement.enter.assert_called_once_with("new", ["new"])

    def test_existing_reassignment_submission_error_releases_pending_takeoffs(self):
        self.write.uses_sql_collaboration_mutations.return_value = True
        self.write.queue_plan_properties.side_effect = RuntimeError("submission failed")
        self.undo.push_local(lambda: True, lambda: True)
        with self.assertRaisesRegex(RuntimeError, "submission failed"):
            self.plan_handler.on_reassign_condition(["1", "2"], "other")
        self.assertEqual(self.plan.get_pending_mutation_uids(), set())
        self.assertTrue(self.undo.can_undo())

    def test_repeated_property_failure_does_not_release_newer_pending_selection(self):
        self.write.uses_sql_collaboration_mutations.return_value = True
        callbacks = []
        self.write.queue_plan_properties.side_effect = (
            lambda _path, _bid, _kind, _updates, callback, **_options: callbacks.append(
                callback
            )
        )
        self.undo.push_local(lambda: True, lambda: True)
        self.plan_handler.on_reassign_condition(["1", "2"], "other")
        failure = self.result(MutationOutcomeStatus.FAILED_BEFORE_COMMIT)
        callbacks[0](failure)
        self.plan_handler.on_reassign_condition(["1", "2"], "other")
        self.assertEqual(self.plan.get_pending_mutation_uids(), {"1", "2"})
        callbacks[0](failure)
        self.assertEqual(self.plan.get_pending_mutation_uids(), {"1", "2"})
        self.assertFalse(self.undo.can_undo())
        callbacks[1](
            replace(failure, operation_id="00000000-0000-0000-0000-000000000002")
        )
        self.assertEqual(self.plan.get_pending_mutation_uids(), set())
        self.assertTrue(self.undo.can_undo())

    def test_sql_new_tool_intent_survives_completion(self):
        self.submit_sql()
        self.plan.set_cursor_mode("pan")
        self.callback(self.result())
        self.assertEqual(self.plan.cursor_mode, "pan")
        self.coordinator.placement.enter.assert_not_called()

    def test_sql_access_loss_survives_completion_without_placement(self):
        self.submit_sql()
        self.access.is_allowed.return_value = False
        self.callback(self.result())
        self.coordinator.placement.enter.assert_not_called()
        self.assertEqual(self.plan.get_pending_mutation_uids(), set())

    def test_sql_active_2d_loss_survives_completion_without_placement(self):
        self.submit_sql()
        self.coordinator._toolbar.is_takeoff_2d_view_active.return_value = False
        self.callback(self.result())
        self.coordinator.placement.enter.assert_not_called()

    def test_hidden_condition_layer_keeps_authoritative_reassignment_scope(self):
        self.conditions["target"].layer_visible = False
        self.load_page(self.plan, self.page)
        self.assertTrue(self.open_menu(during_menu=lambda action: action.trigger()))
        self.assertEqual(
            self.write.duplicate_conditions_result.call_args.kwargs[
                "reassign_takeoffs"
            ].takeoff_uids,
            ("1", "2"),
        )

    def test_sql_deferred_navigation_cannot_reactivate_placement_on_old_plan(self):
        self.submit_sql()
        self.state.active_page_uid = "p2"
        self.callback(self.result())
        self.coordinator.placement.enter.assert_not_called()

    def test_sql_main_surface_replacement_cannot_receive_old_completion(self):
        self.submit_sql()
        new_plan = self.make_plan()
        self.load_page(new_plan, self.page)
        self.coordinator.plan_view = new_plan
        self.callback(self.result())
        self.coordinator.placement.enter.assert_not_called()
        self.assertFalse(self.undo.can_undo())

    def test_mdb_navigation_during_reload_cannot_reactivate_placement(self):
        def duplicate(*_args, **_options):
            self.state.active_page_uid = "p2"
            self.load_page(self.plan, self.other_page)
            return WriteReloadResult(["new"], write_success=True, reload_success=True)

        self.write.duplicate_conditions_result.side_effect = duplicate
        self.open_menu(during_menu=lambda action: action.trigger())
        self.coordinator.placement.enter.assert_not_called()

    def test_mdb_own_reload_preserves_normal_duplicate_placement(self):
        def duplicate(*_args, **_options):
            replacement = replace(self.page)
            self.model.set_pages({"p1": replacement, "p2": self.other_page})
            self.load_page(self.plan, replacement)
            return WriteReloadResult(["new"], write_success=True, reload_success=True)

        self.write.duplicate_conditions_result.side_effect = duplicate
        self.open_menu(during_menu=lambda action: action.trigger())
        self.coordinator.placement.enter.assert_called_once_with("new", ["new"])
