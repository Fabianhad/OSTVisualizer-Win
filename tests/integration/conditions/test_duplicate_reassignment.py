import unittest
from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import Mock, patch
from ost_visualizer.application.dtos.active_bid_locked_error import (
    ActiveBidLockedError,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    ConcurrencyToken,
    DatabaseMutationResult,
    DurableOperationResult,
    MutationOutcomeStatus,
    MutationRejectionReason,
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
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.components import conditions_sidebar as sidebar_module
from ost_visualizer.presentation.handlers.condition_action_handler import (
    ConditionActionHandler,
)
from ost_visualizer.presentation.handlers.plan_view_action_handler import (
    PlanViewActionHandler,
)
from ost_visualizer.application.services.annotation_write_service import (
    AnnotationWriteService,
)
from ost_visualizer.application.services.project_read_service import (
    ProjectReadService,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.page_settings_bar import PageSettingsBar
from ost_visualizer.presentation.coordinators.sidebar_coordinator import (
    SidebarCoordinator,
)
from ost_visualizer.presentation.managers.deferred_persistence_manager import (
    DeferredPersistenceManager,
)
from tests.helpers.workspace_state import make_workspace_state_model
from ost_visualizer.presentation.coordinators.placement_coordinator import (
    PlacementCoordinator,
)
from ost_visualizer.presentation.managers.ui_access_manager import (
    Feature,
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
        self.write = Mock(spec=ProjectWriteService)
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
            Mock(spec=AnnotationWriteService),
            Mock(spec=PageSettingsBar),
            self.undo,
            EventBus(),
            Mock(spec=DeferredPersistenceManager),
            self.access,
        )
        self.coordinator._plan_view_handler = self.plan_handler
        self.coordinator._deferred_persistence = Mock(spec=DeferredPersistenceManager)
        self.coordinator._deferred_persistence.flush_for_file.return_value = True
        self.coordinator._placement = Mock(spec=PlacementCoordinator)
        self.coordinator._sidebar = Mock(spec=SidebarCoordinator)
        self.handler = ConditionActionHandler(
            self.coordinator,
            self.write,
            Mock(spec=ProjectReadService),
            self.data,
            self.state,
            make_workspace_state_model(),
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
        self.write.duplicate_conditions_result.assert_not_called()
        self.write.queue_conditions_duplicate.assert_not_called()

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
        # The committed reassignment on the original Page is still recorded
        # (and only undo/redo ever queue plan properties), unchanged by the
        # navigation; the assertion is made through a real undo.
        self.write.queue_plan_properties.assert_not_called()
        self.assertTrue(self.undo.can_undo())
        self.undo.undo()
        args, options = self.write.queue_plan_properties.call_args
        self.assertEqual(
            args[2:4], ("takeoff_condition", [("1", "target"), ("2", "target")])
        )
        self.assertEqual(options["page_uids"], ("p1",))

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

    def test_sql_pending_selection_handling_leaves_detached_surface_alone(self):
        detached = self.make_plan()
        self.load_page(detached, self.other_page)
        detached.set_selected_uids({"4"})
        self.plan.set_selected_uids({"1"})
        self.submit_sql()
        # Positive control: the Main Plan's own selection was handled...
        self.assertEqual(self.plan.get_selected_uids(), [])
        self.assertEqual(detached.get_selected_uids(), ["4"])
        self.callback(self.result())
        self.assertEqual(self.plan.get_selected_uids(), ["1"])
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
        # Native deletion alone (no cleanup() state reset, no cleanup flag): only
        # the validity guards stand between the completion and the dead widget.
        delete(self.plan)
        self.callback(self.result())
        self.coordinator.placement.enter.assert_not_called()
        self.assertEqual(self.undo.can_undo(), False)

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

    # --- Guard isolation: each scenario changes exactly one captured owner so
    # --- that the guard under test is the only one that can stop the action.
    def deny_only(self, feature):
        self.access.is_allowed.side_effect = lambda requested: requested != feature

    def assert_menu_action_invalidated(self, change_during_menu):
        self.open_menu(
            during_menu=lambda action: (change_during_menu(), action.trigger())
        )
        self.write.duplicate_conditions_result.assert_not_called()
        self.write.queue_conditions_duplicate.assert_not_called()

    def assert_mdb_placement_blocked(self, change_during_write, *, history):
        def duplicate(*_args, **_options):
            change_during_write()
            return WriteReloadResult(["new"], write_success=True, reload_success=True)

        self.write.duplicate_conditions_result.side_effect = duplicate
        self.open_menu(during_menu=lambda action: action.trigger())
        self.write.duplicate_conditions_result.assert_called_once()
        self.coordinator.placement.enter.assert_not_called()
        # The write itself committed; only a Bid switch may drop its history.
        self.assertEqual(self.undo.can_undo(), history)

    def test_mdb_unchanged_context_after_write_places_and_records_history(self):
        # Positive control for the isolated MDB guard scenarios below.
        self.write.duplicate_conditions_result.side_effect = (
            lambda *_args, **_options: WriteReloadResult(
                ["new"], write_success=True, reload_success=True
            )
        )
        self.open_menu(during_menu=lambda action: action.trigger())
        self.coordinator.placement.enter.assert_called_once_with("new", ["new"])
        self.assertTrue(self.undo.can_undo())

    def test_mdb_active_page_change_alone_blocks_placement(self):
        self.assert_mdb_placement_blocked(
            lambda: setattr(self.state, "active_page_uid", "p2"), history=True
        )

    def test_mdb_page_replacement_alone_blocks_placement(self):
        self.assert_mdb_placement_blocked(
            lambda: self.model.set_pages(
                {"p1": replace(self.page), "p2": self.other_page}
            ),
            history=True,
        )

    def test_mdb_selected_bid_change_blocks_placement_and_history(self):
        other = BidRef("C:/other.mdb", "9")
        self.assert_mdb_placement_blocked(
            lambda: setattr(self.state, "get_selected_bid_ref", lambda: other),
            history=False,
        )

    def test_mdb_main_plan_replacement_blocks_placement(self):
        self.assert_mdb_placement_blocked(
            lambda: setattr(self.coordinator, "plan_view", self.make_plan()),
            history=True,
        )

    def test_mdb_main_plan_destruction_blocks_placement(self):
        # Delete the native widget without the Plan's own cleanup(), which
        # would also clear its projected Page and hide the destruction itself.
        self.assert_mdb_placement_blocked(lambda: delete(self.plan), history=True)

    def test_mdb_cleanup_in_progress_blocks_placement(self):
        self.assert_mdb_placement_blocked(
            lambda: setattr(self.coordinator, "_is_cleaning_up", True), history=True
        )

    def test_mdb_edit_access_loss_alone_blocks_placement(self):
        self.assert_mdb_placement_blocked(
            lambda: self.deny_only(Feature.EDIT_PLAN_ITEMS), history=True
        )

    def test_mdb_duplicate_access_loss_alone_blocks_placement(self):
        self.assert_mdb_placement_blocked(
            lambda: self.deny_only(Feature.DUPLICATE_CONDITION), history=True
        )

    def test_mdb_active_2d_loss_blocks_placement(self):
        self.assert_mdb_placement_blocked(
            lambda: setattr(
                self.coordinator._toolbar.is_takeoff_2d_view_active,
                "return_value",
                False,
            ),
            history=True,
        )

    def test_reassignment_without_captured_context_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "captured Plan context"):
            self.handler.on_duplicate_requested(
                ["target"],
                reassign_takeoffs=ConditionTakeoffReassignment(
                    "target", "p1", ("1", "2")
                ),
            )
        self.write.duplicate_conditions_result.assert_not_called()
        self.write.queue_conditions_duplicate.assert_not_called()

    def test_sql_revalidation_after_deferred_flush_rejects_replacement(self):
        self.write.uses_sql_collaboration_mutations.return_value = True

        def flush(_path):
            self.conditions["target"] = replace(self.conditions["target"])
            return True

        self.coordinator.flush_deferred_for_file.side_effect = flush
        self.open_menu(during_menu=lambda action: action.trigger())
        self.write.queue_conditions_duplicate.assert_not_called()
        self.assertEqual(self.plan.get_pending_mutation_uids(), set())
        self.assertFalse(self.undo.can_undo())

    def test_sql_selection_change_after_submission_skips_placement_only(self):
        self.submit_sql()
        self.plan.set_selected_uids({"3"})
        self.callback(self.result())
        self.assertEqual(self.plan.get_selected_uids(), ["3"])
        self.coordinator.placement.enter.assert_not_called()
        # The committed reassignment is still undoable and no longer pending.
        self.assertTrue(self.undo.can_undo())
        self.assertEqual(self.plan.get_pending_mutation_uids(), set())

    def test_sql_selection_revision_change_with_equal_selection_blocks_placement(
        self,
    ):
        self.submit_sql()
        self.plan.set_selected_uids({"3"})
        self.plan.set_selected_uids(set())
        self.callback(self.result())
        self.assertEqual(self.plan.get_selected_uids(), [])
        self.coordinator.placement.enter.assert_not_called()
        self.assertTrue(self.undo.can_undo())

    def test_sql_cleanup_flag_after_submission_blocks_placement(self):
        self.submit_sql()
        self.coordinator._is_cleaning_up = True
        self.callback(self.result())
        self.coordinator.placement.enter.assert_not_called()

    def test_sql_edit_access_loss_alone_blocks_placement(self):
        self.submit_sql()
        self.deny_only(Feature.EDIT_PLAN_ITEMS)
        self.callback(self.result())
        self.coordinator.placement.enter.assert_not_called()

    def test_sql_duplicate_access_loss_alone_blocks_placement(self):
        self.submit_sql()
        self.deny_only(Feature.DUPLICATE_CONDITION)
        self.callback(self.result())
        self.coordinator.placement.enter.assert_not_called()

    def test_sql_page_model_replacement_without_plan_reload_blocks_placement(self):
        self.submit_sql()
        self.model.set_pages({"p1": replace(self.page), "p2": self.other_page})
        self.callback(self.result())
        self.coordinator.placement.enter.assert_not_called()

    def test_sql_plan_projected_for_other_bid_blocks_placement(self):
        self.submit_sql()
        self.assertTrue(
            self.plan.load_page(
                self.page,
                self.page.takeoffs,
                self.conditions,
                {uid: "#000000" for uid in self.conditions},
                bid_ref=BidRef(self.bid_ref.file_path, "9"),
            )
        )
        self.callback(self.result())
        self.coordinator.placement.enter.assert_not_called()

    def test_sql_success_records_reassignment_history_with_new_condition(self):
        self.submit_sql()
        self.callback(self.result())
        self.undo.undo()
        args, options = self.write.queue_plan_properties.call_args
        self.assertEqual(
            args[2:4], ("takeoff_condition", [("1", "target"), ("2", "target")])
        )
        self.assertEqual(options["page_uids"], ("p1",))
        expected_dependencies = (
            ResourceRef("condition", "target", 7),
            ResourceRef("condition", "new", 7),
        )
        self.assertEqual(options["dependency_resources"], expected_dependencies)
        args[4](self.result())
        self.assertTrue(self.undo.can_redo())
        self.undo.redo()
        args, options = self.write.queue_plan_properties.call_args
        self.assertEqual(args[2:4], ("takeoff_condition", [("1", "new"), ("2", "new")]))
        self.assertEqual(options["dependency_resources"], expected_dependencies)

    # --- Action availability guards, one captured owner at a time.
    def test_missing_plan_handler_disables_action(self):
        self.coordinator._plan_view_handler = None
        self.assertFalse(self.open_menu())

    def test_main_plan_replacement_invalidates_action(self):
        self.assert_menu_action_invalidated(
            lambda: setattr(self.coordinator, "plan_view", self.make_plan())
        )

    def test_selected_bid_change_invalidates_action(self):
        other = BidRef("C:/other.mdb", "9")
        self.assert_menu_action_invalidated(
            lambda: setattr(self.state, "get_selected_bid_ref", lambda: other)
        )

    def test_active_page_change_alone_invalidates_action(self):
        self.assert_menu_action_invalidated(
            lambda: setattr(self.state, "active_page_uid", "p2")
        )

    def test_selection_change_invalidates_action(self):
        self.assert_menu_action_invalidated(lambda: self.plan.set_selected_uids({"3"}))

    def test_selection_revision_change_with_equal_selection_invalidates_action(self):
        self.assert_menu_action_invalidated(
            lambda: (
                self.plan.set_selected_uids({"3"}),
                self.plan.set_selected_uids(set()),
            )
        )

    def test_plan_surface_edit_access_alone_disables_action(self):
        self.access.get_plan_surface_access.return_value = PlanSurfaceAccessState(
            can_select_plan_items=True, can_edit_plan_items=False
        )
        self.assertFalse(self.open_menu())

    def test_duplicate_feature_denied_alone_disables_action(self):
        self.deny_only(Feature.DUPLICATE_CONDITION)
        self.assertFalse(self.open_menu())

    def test_duplicate_disabled_in_sidebar_disables_reassign_action_too(self):
        self.assertTrue(self.open_menu())
        self.sidebar.set_duplicate_enabled(False)
        self.assertFalse(self.open_menu())

    def test_edit_plan_items_feature_denied_alone_disables_action(self):
        self.deny_only(Feature.EDIT_PLAN_ITEMS)
        self.assertFalse(self.open_menu())

    def test_takeoff_displayed_on_other_page_disables_action(self):
        self.assertTrue(self.open_menu())
        stale = [replace(item, page_uid="p2") for item in self.page.takeoffs]
        self.assertTrue(
            self.plan.load_page(
                self.page,
                stale,
                self.conditions,
                {uid: "#000000" for uid in self.conditions},
                bid_ref=self.bid_ref,
            )
        )
        self.assertFalse(self.open_menu())

    # --- Second-pass additions: guards that were only reachable together with others.
    def test_missing_cleaning_or_destroyed_main_plan_disables_action(self):
        self.assertTrue(self.open_menu())
        plan = self.coordinator.plan_view
        self.coordinator.plan_view = None
        self.assertFalse(self.open_menu())
        self.coordinator.plan_view = plan
        self.coordinator._is_cleaning_up = True
        self.assertFalse(self.open_menu())
        self.coordinator._is_cleaning_up = False
        self.assertTrue(self.open_menu())
        delete(self.plan)
        self.assertFalse(self.open_menu())
        self.write.duplicate_conditions_result.assert_not_called()

    def test_bid_missing_from_hierarchy_or_plan_without_bid_ref_disables_action(self):
        self.assertTrue(self.open_menu())
        self.assertTrue(
            self.plan.load_page(
                self.page,
                self.page.takeoffs,
                self.conditions,
                {uid: "#000000" for uid in self.conditions},
            )
        )
        self.assertIsNone(self.plan._context_menu_owner()[0])
        self.assertFalse(self.open_menu())
        self.assertTrue(
            self.plan.load_page(
                self.page,
                self.page.takeoffs,
                self.conditions,
                {uid: "#000000" for uid in self.conditions},
                bid_ref=self.bid_ref,
            )
        )
        self.assertTrue(self.open_menu())
        self.model.set_hierarchy(
            HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(file_path=self.bid_ref.file_path, orphan_bids=[])
                ]
            )
        )
        self.assertIsNone(self.data.get_bid(self.bid_ref))
        self.assertFalse(self.open_menu())
        self.write.duplicate_conditions_result.assert_not_called()

    def test_cleanup_flags_or_destruction_during_menu_invalidate_action(self):
        self.assert_menu_action_invalidated(
            lambda: setattr(self.coordinator, "_is_cleaning_up", True)
        )

    def test_plan_cleanup_flag_alone_during_menu_invalidates_action(self):
        self.assert_menu_action_invalidated(
            lambda: setattr(self.plan, "_is_cleaning_up", True)
        )

    def test_plan_surface_without_select_access_disables_action(self):
        self.access.get_plan_surface_access.return_value = PlanSurfaceAccessState(
            can_select_plan_items=False, can_edit_plan_items=True
        )
        self.assertFalse(self.open_menu())

    def test_sql_pending_duplicate_blocks_resubmission_and_completion_reports_no_error(
        self,
    ):
        self.write.uses_sql_collaboration_mutations.return_value = True
        callbacks = []
        self.write.queue_conditions_duplicate.side_effect = (
            lambda _path, _bid, _uids, callback: callbacks.append(callback)
        )
        self.handler.on_duplicate_requested(["target"])
        self.handler.on_duplicate_requested(["target"])
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(self.handler._pending_sql_operations), 1)
        callbacks[0](self.result())
        self.assertEqual(self.handler._pending_sql_operations, set())
        self.coordinator.present_queued_mutation_error.assert_not_called()
        self.handler.on_duplicate_requested(["target"])
        self.assertEqual(len(callbacks), 2)

    def test_sql_submission_failure_releases_the_pending_operation_key(self):
        self.write.uses_sql_collaboration_mutations.return_value = True
        self.write.queue_conditions_duplicate.side_effect = RuntimeError(
            "not submitted"
        )
        self.open_menu(during_menu=lambda action: action.trigger())
        self.assertEqual(self.handler._pending_sql_operations, set())
        self.warning.assert_called_once()

    def test_sql_locked_bid_rejection_reports_once_and_releases_pending_state(self):
        self.submit_sql()
        locked = replace(
            self.result(MutationOutcomeStatus.REJECTED),
            rejection_reason=MutationRejectionReason.BID_LOCKED,
        )
        self.callback(locked)
        self.coordinator.present_queued_mutation_error.assert_called_once()
        self.assertEqual(self.plan.get_pending_mutation_uids(), set())
        self.assertEqual(self.handler._pending_sql_operations, set())
        self.coordinator.placement.enter.assert_not_called()

    def test_sql_selected_bid_change_before_completion_blocks_placement_and_history(
        self,
    ):
        self.submit_sql()
        other = BidRef("C:/other.mdb", "9")
        self.state.get_selected_bid_ref = lambda: other
        self.callback(self.result())
        self.coordinator.placement.enter.assert_not_called()
        self.assertFalse(self.undo.can_undo())

    def test_sql_plan_cleanup_flag_alone_after_submission_blocks_placement(self):
        self.submit_sql()
        self.plan._is_cleaning_up = True
        self.callback(self.result())
        self.coordinator.placement.enter.assert_not_called()

    def test_direct_duplicate_request_without_selected_bid_does_nothing(self):
        self.state.get_selected_bid_ref = lambda: None
        self.handler.on_duplicate_requested(["target"])
        self.write.duplicate_conditions_result.assert_not_called()
        self.write.queue_conditions_duplicate.assert_not_called()
        self.state.get_selected_bid_ref = lambda: self.bid_ref
        self.handler.on_duplicate_requested(["target"])
        self.write.duplicate_conditions_result.assert_called_once()

    def test_finished_duplicate_highlights_the_new_condition_without_reveal(self):
        highlight = Mock()
        self.coordinator.highlight_sidebar = highlight
        self.open_menu(during_menu=lambda action: action.trigger())
        highlight.assert_called_once_with({"new"}, reveal=False)
        highlight.reset_mock()
        self.submit_sql()
        highlight.assert_not_called()
        self.callback(self.result())
        highlight.assert_called_once_with({"new"}, reveal=False)

    def test_duplicate_without_conditions_sidebar_places_and_failure_warns_without_parent(
        self,
    ):
        highlight = Mock()
        self.coordinator.highlight_sidebar = highlight
        self.coordinator.conditions_sidebar = None
        self.handler.on_duplicate_requested(["target"])
        self.write.duplicate_conditions_result.assert_called_once()
        self.coordinator.placement.enter.assert_called_once_with("new", ["new"])
        highlight.assert_not_called()
        self.write.duplicate_conditions_result.return_value = WriteReloadResult([])
        self.handler.on_duplicate_requested(
            ["target"],
            reassign_takeoffs=ConditionTakeoffReassignment("target", "p1", ("1", "2")),
            context_is_current=lambda: True,
        )
        self.warning.assert_called_once()
        self.assertIsNone(self.warning.call_args.args[0])

    def test_multiple_duplicated_conditions_place_the_last_one_and_highlight_all(self):
        highlight = Mock()
        self.coordinator.highlight_sidebar = highlight
        self.write.duplicate_conditions_result.return_value = WriteReloadResult(
            ["first", "second"], write_success=True, reload_success=True
        )
        self.handler.on_duplicate_requested(["target", "other"])
        self.coordinator.placement.enter.assert_called_once_with(
            "second", ["first", "second"]
        )
        highlight.assert_called_once_with({"first", "second"}, reveal=False)

    def test_sql_commit_without_created_conditions_finishes_nothing(self):
        self.write.uses_sql_collaboration_mutations.return_value = True
        callbacks = []
        self.write.queue_conditions_duplicate.side_effect = (
            lambda _path, _bid, _uids, callback: callbacks.append(callback)
        )
        self.handler.on_duplicate_requested(["target"])
        callbacks[0](
            replace(
                self.result(),
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=()
                ),
            )
        )
        self.coordinator.placement.enter.assert_not_called()
        self.assertEqual(self.handler._pending_sql_operations, set())

    def test_failed_duplicate_is_logged_and_warns_with_the_sidebar_window(self):
        self.write.duplicate_conditions_result.return_value = WriteReloadResult([])
        reassign = ConditionTakeoffReassignment("target", "p1", ("1", "2"))
        with self.assertLogs(
            "ost_visualizer.presentation.handlers.condition_action_handler", "WARNING"
        ) as logs:
            self.handler.on_duplicate_requested(
                ["target"], reassign_takeoffs=reassign, context_is_current=lambda: True
            )
        self.assertIn("Failed to duplicate conditions", logs.output[0])
        self.assertIs(self.warning.call_args.args[0], self.sidebar.window())

    def test_sql_cleanup_flag_after_submission_installs_no_history(self):
        self.submit_sql()
        self.coordinator._is_cleaning_up = True
        self.callback(self.result())
        self.assertFalse(self.undo.can_undo())
        self.assertEqual(self.plan.get_pending_mutation_uids(), set())


class ConditionDuplicateReassignmentCleanupTests(unittest.TestCase):
    """Second-pass additions that need the same fixture as ConditionDuplicateReassignmentTests.
    Real sidebar, Plan, handlers and UndoRedoService; the write service is a spec'd Mock,
    so the SQL leg is the queue stub whose callback the test completes by hand.
    """

    make_plan = ConditionDuplicateReassignmentTests.make_plan
    load_page = ConditionDuplicateReassignmentTests.load_page
    takeoff = staticmethod(ConditionDuplicateReassignmentTests.takeoff)
    setUp = ConditionDuplicateReassignmentTests.setUp
    open_menu = ConditionDuplicateReassignmentTests.open_menu
    submit_sql = ConditionDuplicateReassignmentTests.submit_sql
    result = ConditionDuplicateReassignmentTests.result

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_completion_never_touches_a_plan_that_is_cleaning_up(self):
        with patch.object(
            self.plan,
            "set_pending_mutation_uids",
            wraps=self.plan.set_pending_mutation_uids,
        ) as pending:
            self.submit_sql()
            self.assertEqual(self.plan.get_pending_mutation_uids(), {"1", "2"})
            self.assertEqual(pending.call_count, 1)
            self.callback(self.result())
            # Positive control: a normal completion releases the marks on the Plan.
            self.assertEqual(self.plan.get_pending_mutation_uids(), set())
            self.assertEqual(pending.call_count, 2)
            self.submit_sql()
            self.assertEqual(pending.call_count, 3)
            self.plan._is_cleaning_up = True
            # A new operation id: a repeated id would be ignored as an applied duplicate.
            self.callback(
                replace(
                    self.result(), operation_id="00000000-0000-0000-0000-000000000002"
                )
            )
            self.assertEqual(pending.call_count, 3)
            self.assertEqual(self.plan.get_pending_mutation_uids(), {"1", "2"})
            self.assertEqual(self.handler._pending_sql_operations, set())


class ConditionDuplicateReassignmentGenericFailureTests(unittest.TestCase):
    """Decision S3: a generic exception (RuntimeError, ValueError, KeyError) at each
    submit boundary of duplicate-and-reassign leaves nothing behind on the real Plan,
    the real PlanViewActionHandler, the real UndoRedoService and the real condition
    handler: no pending marks, no forward-mutation token, the selection restored, no
    pending key, no edit lease, no history, no placement and no second write. The write
    service is a spec'd Mock; the queue stub raises after receiving its callback."""

    make_plan = ConditionDuplicateReassignmentTests.make_plan
    load_page = ConditionDuplicateReassignmentTests.load_page
    takeoff = staticmethod(ConditionDuplicateReassignmentTests.takeoff)
    setUp = ConditionDuplicateReassignmentTests.setUp
    result = ConditionDuplicateReassignmentTests.result
    FAILURES = (
        RuntimeError("queue closed"),
        ValueError("bad value"),
        KeyError("missing"),
    )

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def start(self, failure=None, prepare_patch=None):
        self.undone = []
        self.undo.push_local(lambda: self.undone.append("undo") or True, lambda: True)
        self.plan.set_selected_uids({"1", "3"})
        self.write.uses_sql_collaboration_mutations.return_value = True
        self.callbacks = []

        def submit(_path, _bid, _uids, callback, **_options):
            self.callbacks.append(callback)
            if failure is not None:
                raise failure
            return 1

        self.write.queue_conditions_duplicate.side_effect = submit
        assignment = ConditionTakeoffReassignment("target", "p1", ("1", "2"))
        outcome = []
        with ExitStack() as stack:
            if prepare_patch is not None:
                stack.enter_context(prepare_patch)
            try:
                self.handler.on_duplicate_requested(
                    ["target"],
                    reassign_takeoffs=assignment,
                    context_is_current=lambda: True,
                )
            except Exception as error:
                outcome.append(error)
        return outcome

    def assert_nothing_left_behind(self):
        self.assertEqual(self.plan.get_pending_mutation_uids(), set())
        self.assertEqual(self.plan_handler._pending_plan_takeoff_uids_by_bid, {})
        self.assertEqual(self.plan_handler._pending_plan_annotations_by_bid, {})
        self.assertEqual(self.undo._forward_mutations, {})
        self.assertTrue(self.undo.can_undo())
        self.assertEqual(sorted(self.plan.get_selected_uids()), ["1", "3"])
        self.assertEqual(self.handler._pending_sql_operations, set())
        self.assertIsNone(self.plan_handler._geometry_edit_lease_handle)
        self.assertEqual(
            [call for call in self.write.mock_calls if "lease" in call[0]], []
        )
        self.write.queue_plan_properties.assert_not_called()
        self.coordinator.placement.enter.assert_not_called()

    def assert_the_callback_is_inert(self):
        self.assertEqual(len(self.callbacks), 1)
        self.callbacks[0](self.result())
        self.assertEqual(self.plan.get_pending_mutation_uids(), set())
        self.coordinator.placement.enter.assert_not_called()
        self.coordinator.present_queued_mutation_error.assert_not_called()
        self.assertEqual(self.write.queue_conditions_duplicate.call_count, 1)
        self.assertTrue(self.undo.can_undo())
        self.undo.undo()
        self.write.queue_plan_properties.assert_not_called()
        self.assertEqual(self.undone, ["undo"])

    def test_a_generic_error_from_the_duplicate_queue_call_leaves_nothing_behind(self):
        for failure in self.FAILURES:
            with self.subTest(type(failure).__name__):
                self.setUp()
                outcome = self.start(failure)
                swallowed = isinstance(failure, (RuntimeError, ValueError))
                self.assertEqual(outcome, [] if swallowed else [failure])
                if outcome:
                    self.assertIs(outcome[0], failure)
                self.assertEqual(self.warning.call_count, 1 if swallowed else 0)
                self.assert_nothing_left_behind()
                self.assert_the_callback_is_inert()

    def test_a_locked_bid_still_refuses_silently_and_leaves_nothing_behind(self):
        outcome = self.start(ActiveBidLockedError())
        self.assertEqual(outcome, [])
        self.warning.assert_not_called()
        self.assert_nothing_left_behind()
        self.assert_the_callback_is_inert()

    def test_a_control_submission_holds_every_piece_of_state_until_it_completes(self):
        self.assertEqual(self.start(), [])
        self.assertEqual(self.plan.get_pending_mutation_uids(), {"1", "2"})
        self.assertEqual(
            self.plan_handler._pending_plan_takeoff_uids_by_bid,
            {self.bid_ref: {"1", "2"}},
        )
        self.assertEqual(len(self.undo._forward_mutations), 1)
        self.assertFalse(self.undo.can_undo())
        self.assertEqual(self.plan.get_selected_uids(), ["3"])
        self.assertEqual(
            self.handler._pending_sql_operations,
            {(self.bid_ref.file_path, "7", "duplicate_reassign", "p1", "target")},
        )

    def prepare_failures(self):
        return (
            (
                "page identities",
                lambda failure: patch.object(
                    self.plan_handler, "_capture_page_identities", side_effect=failure
                ),
            ),
            (
                "pending marks",
                lambda failure: patch.object(
                    self.plan, "set_pending_mutation_uids", side_effect=failure
                ),
            ),
        )

    def test_a_generic_error_while_preparing_the_completion_leaves_nothing_behind(self):
        for label, make_patch in self.prepare_failures():
            for failure in self.FAILURES:
                with self.subTest(label, error=type(failure).__name__):
                    self.setUp()
                    outcome = self.start(prepare_patch=make_patch(failure))
                    self.assertEqual(len(outcome), 1)
                    self.assertIs(outcome[0], failure)
                    self.write.queue_conditions_duplicate.assert_not_called()
                    self.warning.assert_not_called()
                    self.assertEqual(self.callbacks, [])
                    self.assert_nothing_left_behind()
