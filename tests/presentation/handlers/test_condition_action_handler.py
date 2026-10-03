import os
import unittest
from dataclasses import fields, replace
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.dtos.active_bid_locked_error import (
    ActiveBidLockedError,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    EditLeaseHandle,
    EditLeaseResult,
    MutationOutcomeStatus,
    MutationRejectionReason,
    QueuedMutationResult,
    ResourceRef,
)
from ost_visualizer.application.dtos.update_condition_dto import (
    UpdateConditionDto,
    UpdateConditionResultDto,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.handlers.condition_action_handler import (
    ConditionActionHandler,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
from tests.application.services import (
    test_sql_collaboration_coordinator as _coordinator_tests,
)
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    DatabaseMutationResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
)
from ost_visualizer.application.services.project_write_service import (
    BatchWriteResult,
    DeleteValidationResult,
    ProjectWriteService,
    WriteReloadResult,
)
from ost_visualizer.presentation.managers.ui_access_manager import (
    _DATABASE_EDIT_FEATURES,
    MAIN_PLAN_SURFACE_ID,
    Feature,
    UIAccessManager,
)
from tests.helpers.workspace_state import make_workspace_state_model
from tests.presentation.dialogs.master_data_support import (
    FakeIconProvider as _master_data_support_FakeIconProvider,
    MasterLayersDialog as _master_data_support_MasterLayersDialog,
)
from tests.presentation.handlers.project_command_support import (
    _ConditionDuplicateRefreshFailedWriteService as _permissions__ConditionDuplicateRefreshFailedWriteService,
    _ConditionStructureWriteService as _permissions__ConditionStructureWriteService,
)
from tests.presentation.managers.permission_support import (
    _FakeAccess as _permissions__FakeAccess,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class FakeReadService:
    def display_to_inches(self, text, _metric):
        try:
            return float(text)
        except ValueError:
            return None

    def inches_to_display(self, value, _metric):
        return "" if not value else str(value)

    def get_quantity_options_for_type(self, _condition_type):
        return []

    def get_valid_uoms_for_calc_type(self, _calc_type, _metric):
        return []


class ConditionActionHandlerConditionBehaviorTests(unittest.TestCase):
    def _make_conditions(self, count: int, prefix: str = "c"):
        return {
            f"{prefix}{index}": Condition(
                uid=f"{prefix}{index}",
                name=f"Condition {index}",
                ref_no=index,
            )
            for index in range(1, count + 1)
        }

    def _foldered_conditions(self):
        conditions = {
            "c1": Condition(uid="c1", name="Condition 1", ref_no=1, folder_uid="f1"),
            "c2": Condition(uid="c2", name="Condition 2", ref_no=2, folder_uid="f2"),
        }
        folders = {
            "f1": BidConditionFolder(uid="f1", name="Folder 1"),
            "f2": BidConditionFolder(uid="f2", name="Folder 2"),
        }
        return conditions, folders

    def _make_condition_delete_handler(self, sidebar, conditions, highlighted):
        class Access:
            def is_allowed(self, feature):
                return feature == Feature.DELETE_CONDITION

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return False

            def delete_conditions(self, _file_path, _bid_uid, condition_uids):
                for uid in condition_uids:
                    conditions.pop(uid, None)
                sidebar.load_conditions(conditions, {}, "Project")
                return True

        coordinator = SimpleNamespace(
            ui_access_manager=Access(),
            conditions_sidebar=sidebar,
            placement=SimpleNamespace(force_exit=lambda: None),
            flush_deferred_for_file=lambda _file_path: True,
            highlight_sidebar=lambda uids, reveal=True: sidebar.highlight_conditions(
                set(uids), reveal=reveal
            ),
            ensure_select_mode=lambda: None,
            refresh_conditions_ui=lambda: sidebar.load_conditions(
                conditions, {}, "Project"
            ),
        )
        ui_state = SimpleNamespace(
            highlighted_condition_uids=set(highlighted),
            get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1"),
        )
        return ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid_conditions=lambda: conditions,
            ),
            ui_state_manager=ui_state,
            workspace_state_model=make_workspace_state_model(),
        )

    def test_condition_delete_handler_selects_previous_after_write_refresh(self):
        from ost_visualizer.presentation.handlers import condition_action_handler

        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(4)
        sidebar.load_conditions(conditions, {}, "Project")
        handler = self._make_condition_delete_handler(sidebar, conditions, {"c3"})
        original_confirm = condition_action_handler.confirm_delete_conditions
        condition_action_handler.confirm_delete_conditions = lambda _parent, names: [
            uid for uid, _name in names
        ]
        try:
            handler.on_delete_requested(["c3"])
        finally:
            condition_action_handler.confirm_delete_conditions = original_confirm
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c2"])

    def _run_condition_delete_tool_projection(
        self,
        conditions,
        deleted_uid,
        *,
        revoke_place_access_after_write=False,
    ):
        from ost_visualizer.presentation.handlers import condition_action_handler

        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        sidebar.load_conditions(conditions, {}, "Project")
        sidebar.highlight_conditions({deleted_uid})

        class Access:
            def __init__(self):
                self.allowed = {
                    Feature.DELETE_CONDITION,
                    Feature.PLACE_PLAN_ITEMS,
                }

            def is_allowed(self, feature):
                return feature in self.allowed

        access = Access()

        class Toolbar:
            def __init__(self):
                self.place_enabled = False
                self.refreshes = 0

            def refresh(self):
                self.refreshes += 1
                selected = sidebar.get_selected_condition_uids()
                self.place_enabled = bool(
                    access.is_allowed(Feature.PLACE_PLAN_ITEMS)
                    and selected
                    and sidebar.is_condition_placeable(selected[0])
                )

        class Placement:
            def __init__(self):
                self.is_active = True
                self.force_exit_calls = 0
                self.enter_calls = []

            def force_exit(self):
                self.force_exit_calls += 1
                self.is_active = False

            def enter(self, condition_uid, condition_uids):
                self.enter_calls.append((condition_uid, list(condition_uids)))
                self.is_active = True
                return True

        toolbar = Toolbar()
        placement = Placement()

        def set_highlighted_conditions(uids):
            ui_state.highlighted_condition_uids = set(uids)

        ui_state = SimpleNamespace(
            highlighted_condition_uids={deleted_uid},
            get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1"),
            set_highlighted_conditions=set_highlighted_conditions,
        )
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_access_manager = access
        coordinator.conditions_sidebar = sidebar
        coordinator.ui_state_manager = ui_state
        coordinator._selection_projected_condition_uids = set()
        coordinator._nav = SimpleNamespace(is_refreshing=False)
        coordinator._toolbar = toolbar
        coordinator._mesh_window = None
        coordinator._is_cleaning_up = False
        coordinator._placement = placement
        coordinator.flush_deferred_for_file = lambda _file_path: True
        coordinator.ensure_select_mode = lambda: None

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return False

            @staticmethod
            def delete_conditions(_file_path, _bid_uid, condition_uids):
                for uid in condition_uids:
                    conditions.pop(uid, None)
                if revoke_place_access_after_write:
                    access.allowed.discard(Feature.PLACE_PLAN_ITEMS)
                sidebar.load_conditions(conditions, {}, "Project")
                # Authoritative projection occurs before the handler installs its
                # captured fallback selection.
                toolbar.refresh()
                return True

        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid_conditions=lambda: conditions,
            ),
            ui_state_manager=ui_state,
            workspace_state_model=make_workspace_state_model(),
        )
        with patch.object(
            condition_action_handler,
            "confirm_delete_conditions",
            lambda _parent, names: [uid for uid, _name in names],
        ):
            handler.on_delete_requested([deleted_uid])
        return sidebar, toolbar, placement

    def test_condition_delete_fallback_reenables_takeoff_without_restarting_it(self):
        conditions = self._make_conditions(3)
        sidebar, toolbar, placement = self._run_condition_delete_tool_projection(
            conditions, "c3"
        )
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c2"])
        self.assertTrue(toolbar.place_enabled)
        self.assertFalse(placement.is_active)
        self.assertEqual(placement.force_exit_calls, 1)
        self.assertEqual(placement.enter_calls, [])

    def test_condition_delete_last_condition_disables_takeoff(self):
        sidebar, toolbar, placement = self._run_condition_delete_tool_projection(
            self._make_conditions(1), "c1"
        )
        self.assertEqual(sidebar.get_selected_condition_uids(), [])
        self.assertFalse(toolbar.place_enabled)
        self.assertFalse(placement.is_active)
        self.assertEqual(placement.force_exit_calls, 1)
        self.assertEqual(placement.enter_calls, [])

    def test_condition_delete_hidden_fallback_keeps_takeoff_disabled(self):
        conditions = self._make_conditions(2)
        conditions["c1"].layer_visible = False
        sidebar, toolbar, placement = self._run_condition_delete_tool_projection(
            conditions, "c2"
        )
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])
        self.assertFalse(toolbar.place_enabled)
        self.assertFalse(placement.is_active)
        self.assertEqual(placement.force_exit_calls, 1)
        self.assertEqual(placement.enter_calls, [])

    def test_condition_delete_different_type_fallback_enables_new_takeoff(self):
        conditions = self._make_conditions(2)
        conditions["c1"].condition_type = Condition.TYPE_LINEAR
        conditions["c2"].condition_type = Condition.TYPE_AREA
        sidebar, toolbar, placement = self._run_condition_delete_tool_projection(
            conditions, "c2"
        )
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])
        self.assertTrue(toolbar.place_enabled)
        self.assertFalse(placement.is_active)
        self.assertEqual(placement.force_exit_calls, 1)
        self.assertEqual(placement.enter_calls, [])

    def test_condition_delete_fallback_respects_lost_place_access(self):
        sidebar, toolbar, placement = self._run_condition_delete_tool_projection(
            self._make_conditions(2),
            "c2",
            revoke_place_access_after_write=True,
        )
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])
        self.assertFalse(toolbar.place_enabled)
        self.assertFalse(placement.is_active)
        self.assertEqual(placement.force_exit_calls, 1)
        self.assertEqual(placement.enter_calls, [])

    def test_condition_delete_revalidates_access_after_confirmation(self):
        from ost_visualizer.presentation.handlers import condition_action_handler

        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(1)
        sidebar.load_conditions(conditions, {}, "Project")
        delete_calls = []

        class Access:
            allowed = True

            def is_allowed(self, feature):
                return self.allowed and feature == Feature.DELETE_CONDITION

        access = Access()
        coordinator = SimpleNamespace(
            ui_access_manager=access,
            conditions_sidebar=sidebar,
            placement=SimpleNamespace(force_exit=lambda: None),
            flush_deferred_for_file=lambda _file_path: True,
            highlight_sidebar=lambda _uids, reveal=True: None,
            ensure_select_mode=lambda: None,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: False,
                delete_conditions=lambda *args: delete_calls.append(args) or True,
            ),
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid_conditions=lambda: conditions,
            ),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1")
            ),
            workspace_state_model=make_workspace_state_model(),
        )

        def confirm_and_revoke(_parent, names):
            access.allowed = False
            return [uid for uid, _name in names]

        original_confirm = condition_action_handler.confirm_delete_conditions
        condition_action_handler.confirm_delete_conditions = confirm_and_revoke
        try:
            handler.on_delete_requested(["c1"])
        finally:
            condition_action_handler.confirm_delete_conditions = original_confirm
        self.assertFalse(access.allowed)
        self.assertEqual(delete_calls, [])

    def test_condition_delete_handler_selects_previous_after_multi_write_refresh(self):
        from ost_visualizer.presentation.handlers import condition_action_handler

        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(5)
        sidebar.load_conditions(conditions, {}, "Project")
        handler = self._make_condition_delete_handler(sidebar, conditions, {"c3", "c4"})
        original_confirm = condition_action_handler.confirm_delete_conditions
        condition_action_handler.confirm_delete_conditions = lambda _parent, names: [
            uid for uid, _name in names
        ]
        try:
            handler.on_delete_requested(["c3", "c4"])
        finally:
            condition_action_handler.confirm_delete_conditions = original_confirm
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c2"])

    def test_condition_delete_cancelled_confirmation_keeps_conditions_and_selection(
        self,
    ):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(3)
        sidebar.load_conditions(conditions, {}, "Project")
        sidebar.highlight_conditions({"c3"})
        handler = self._make_condition_delete_handler(sidebar, conditions, {"c3"})
        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "confirm_delete_conditions",
            return_value=[],
        ) as confirm_delete:
            handler.on_delete_requested(["c3"])
        confirm_delete.assert_called_once()
        self.assertEqual(sorted(conditions), ["c1", "c2", "c3"])
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c3"])

    def test_condition_delete_failed_write_keeps_tool_and_selection(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(3)
        sidebar.load_conditions(conditions, {}, "Project")
        sidebar.highlight_conditions({"c3"})
        handler = self._make_condition_delete_handler(sidebar, conditions, {"c3"})
        exits = []
        delete_calls = []
        handler._coordinator.placement = SimpleNamespace(
            force_exit=lambda: exits.append(True)
        )
        handler._write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False,
            delete_conditions=lambda *args: delete_calls.append(args) or False,
        )
        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "confirm_delete_conditions",
            lambda _parent, names: [uid for uid, _name in names],
        ), self.assertLogs(
            "ost_visualizer.presentation.handlers.condition_action_handler",
            level="WARNING",
        ):
            handler.on_delete_requested(["c3"])
        self.assertEqual(delete_calls, [("db.mdb", "bid-1", ["c3"])])
        self.assertEqual(exits, [])
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c3"])

    def test_sql_condition_delete_queues_and_selects_after_authoritative_completion(
        self,
    ):
        from ost_visualizer.presentation.handlers import condition_action_handler

        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(4)
        sidebar.load_conditions(conditions, {}, "Project")
        queued = {"calls": 0}
        errors = []
        placement_exits = []

        class Access:
            @staticmethod
            def is_allowed(feature):
                return feature == Feature.DELETE_CONDITION

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def delete_conditions(*_args):
                raise AssertionError(
                    "SQL condition deletion must not run synchronously"
                )

            @staticmethod
            def queue_conditions_delete(database_id, bid_uid, condition_uids, callback):
                queued["calls"] += 1
                queued.update(
                    database_id=database_id,
                    bid_uid=bid_uid,
                    condition_uids=list(condition_uids),
                    callback=callback,
                )
                return 1

        coordinator = SimpleNamespace(
            ui_access_manager=Access(),
            conditions_sidebar=sidebar,
            placement=SimpleNamespace(force_exit=lambda: placement_exits.append(True)),
            flush_deferred_for_file=lambda _file_path: True,
            highlight_sidebar=lambda uids, reveal=True: sidebar.highlight_conditions(
                set(uids), reveal=reveal
            ),
            ensure_select_mode=lambda: None,
            present_queued_mutation_error=lambda *_args, **_kwargs: errors.append(
                _args
            ),
        )
        bid = object()
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid=lambda _ref: bid,
                get_bid_conditions=lambda: conditions,
            ),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("database", "7")
            ),
            workspace_state_model=make_workspace_state_model(),
        )
        original_confirm = condition_action_handler.confirm_delete_conditions
        condition_action_handler.confirm_delete_conditions = lambda _parent, names: [
            uid for uid, _name in names
        ]
        try:
            handler.on_delete_requested(["c3"])
        finally:
            condition_action_handler.confirm_delete_conditions = original_confirm
        self.assertEqual(queued["condition_uids"], ["c3"])
        self.assertEqual(queued["database_id"], "database")
        self.assertEqual(queued["bid_uid"], "7")
        self.assertEqual(sidebar.get_selected_condition_uids(), [])
        operation_key = ("database", "7", "delete", "c3")
        self.assertIn(operation_key, handler._pending_sql_operations)
        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "confirm_delete_conditions",
            lambda _parent, names: [uid for uid, _name in names],
        ):
            handler.on_delete_requested(["c3"])
        self.assertEqual(queued["calls"], 1)
        self.assertEqual(placement_exits, [])
        queued["callback"](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000001",
                outcome_status=MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                commit_attempted=True,
            )
        )
        self.assertIn(operation_key, handler._pending_sql_operations)
        self.assertEqual(errors, [])
        queued["callback"](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000001",
                outcome_status=MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                commit_attempted=True,
            )
        )
        self.assertIn(operation_key, handler._pending_sql_operations)
        self.assertEqual(errors, [])
        conditions.pop("c3")
        sidebar.load_conditions(conditions, {}, "Project")
        queued["callback"](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000001",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertNotIn(operation_key, handler._pending_sql_operations)
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c2"])
        self.assertEqual(placement_exits, [True])
        self.assertEqual(errors, [])

    def test_sql_condition_operations_with_same_uid_are_scoped_to_bid(self):
        callbacks = {}
        coordinator = SimpleNamespace(
            present_queued_mutation_error=lambda *_args: None,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=SimpleNamespace(),
            project_read_service=None,
            project_data=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: None),
            workspace_state_model=make_workspace_state_model(),
        )
        first = BidRef("database-a", "7")
        second = BidRef("database-b", "7")
        third = BidRef("database-a", "8")
        self.assertTrue(
            handler._submit_sql_condition_operation(
                first,
                ("rename_condition", "c1"),
                "Rename Condition",
                lambda callback: callbacks.__setitem__(first.file_path, callback),
            )
        )
        self.assertTrue(
            handler._submit_sql_condition_operation(
                second,
                ("rename_condition", "c1"),
                "Rename Condition",
                lambda callback: callbacks.__setitem__(second.file_path, callback),
            )
        )
        self.assertTrue(
            handler._submit_sql_condition_operation(
                third,
                ("rename_condition", "c1"),
                "Rename Condition",
                lambda callback: callbacks.__setitem__("third", callback),
            )
        )
        self.assertEqual(set(callbacks), {"database-a", "database-b", "third"})
        repeated = []
        self.assertFalse(
            handler._submit_sql_condition_operation(
                first,
                ("rename_condition", "c1"),
                "Rename Condition",
                repeated.append,
            )
        )
        self.assertEqual(repeated, [])
        self.assertEqual(
            handler._pending_sql_operations,
            {
                ("database-a", "7", "rename_condition", "c1"),
                ("database-b", "7", "rename_condition", "c1"),
                ("database-a", "8", "rename_condition", "c1"),
            },
        )

    def test_sql_condition_operation_lifecycle_presents_failures_and_releases_key(
        self,
    ):
        errors = []
        committed = []
        failed = []
        callbacks = []
        handler = ConditionActionHandler(
            coordinator=SimpleNamespace(
                present_queued_mutation_error=lambda *args: errors.append(args),
                conditions_sidebar=SimpleNamespace(window=lambda: "window"),
            ),
            project_write_service=SimpleNamespace(),
            project_read_service=None,
            project_data=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: None),
            workspace_state_model=make_workspace_state_model(),
        )
        bid_ref = BidRef("database", "7")
        key = ("database", "7", "rename_condition", "c1")

        def submit_operation():
            return handler._submit_sql_condition_operation(
                bid_ref,
                ("rename_condition", "c1"),
                "Rename Condition",
                callbacks.append,
                committed.append,
                failed.append,
            )

        self.assertTrue(submit_operation())
        self.assertEqual(handler._pending_sql_operations, {key})
        rejected = QueuedMutationResult(
            database_id="database",
            runtime_generation=1,
            operation_id="00000000-0000-0000-0000-000000000301",
            outcome_status=MutationOutcomeStatus.REJECTED,
            commit_attempted=False,
        )
        callbacks[0](rejected)
        callbacks[0](rejected)
        self.assertEqual(errors, [("database", "Rename Condition", rejected)])
        self.assertEqual(failed, [rejected])
        self.assertEqual(committed, [])
        self.assertEqual(handler._pending_sql_operations, set())
        self.assertTrue(submit_operation())
        self.assertEqual(handler._pending_sql_operations, {key})

        def failing_submit(_callback):
            raise ValueError("Could not queue.")

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "show_warning"
        ) as warning:
            self.assertFalse(
                handler._submit_sql_condition_operation(
                    bid_ref, ("other",), "Other Operation", failing_submit
                )
            )
        warning.assert_called_once_with("window", "Other Operation", "Could not queue.")
        self.assertEqual(handler._pending_sql_operations, {key})

    def test_sql_condition_operation_releases_key_when_submit_raises_unexpectedly(
        self,
    ):
        handler = ConditionActionHandler(
            coordinator=SimpleNamespace(
                present_queued_mutation_error=lambda *_args: None,
                conditions_sidebar=SimpleNamespace(window=lambda: "window"),
            ),
            project_write_service=SimpleNamespace(),
            project_read_service=None,
            project_data=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: None),
            workspace_state_model=make_workspace_state_model(),
        )
        bid_ref = BidRef("database", "7")
        callbacks = []

        def broken_submit(_callback):
            raise LookupError("unexpected queue failure")

        with self.assertRaises(LookupError):
            handler._submit_sql_condition_operation(
                bid_ref, ("rename_condition", "c1"), "Rename Condition", broken_submit
            )
        self.assertEqual(handler._pending_sql_operations, set())
        self.assertTrue(
            handler._submit_sql_condition_operation(
                bid_ref,
                ("rename_condition", "c1"),
                "Rename Condition",
                callbacks.append,
            )
        )
        self.assertEqual(
            handler._pending_sql_operations,
            {("database", "7", "rename_condition", "c1")},
        )

    def test_sql_condition_delete_completion_does_not_project_into_new_bid(self):
        from ost_visualizer.presentation.handlers import condition_action_handler

        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(4)
        sidebar.load_conditions(conditions, {}, "Project")
        queued = {}
        active_bid = [BidRef("database", "7")]
        placement_exits = []

        class Access:
            @staticmethod
            def is_allowed(feature):
                return feature == Feature.DELETE_CONDITION

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def queue_conditions_delete(database_id, bid_uid, condition_uids, callback):
                queued.update(
                    database_id=database_id,
                    bid_uid=bid_uid,
                    condition_uids=list(condition_uids),
                    callback=callback,
                )
                return 1

        coordinator = SimpleNamespace(
            ui_access_manager=Access(),
            conditions_sidebar=sidebar,
            placement=SimpleNamespace(
                force_exit=lambda: placement_exits.append(True),
            ),
            flush_deferred_for_file=lambda _file_path: True,
            highlight_sidebar=lambda uids, reveal=True: sidebar.highlight_conditions(
                set(uids), reveal=reveal
            ),
            ensure_select_mode=lambda: None,
            present_queued_mutation_error=lambda *_args, **_kwargs: None,
        )
        bid = object()
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid=lambda ref: bid if ref == active_bid[0] else None,
                get_bid_conditions=lambda: conditions,
            ),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: active_bid[0]
            ),
            workspace_state_model=make_workspace_state_model(),
        )
        original_confirm = condition_action_handler.confirm_delete_conditions
        condition_action_handler.confirm_delete_conditions = lambda _parent, names: [
            uid for uid, _name in names
        ]
        try:
            handler.on_delete_requested(["c3"])
        finally:
            condition_action_handler.confirm_delete_conditions = original_confirm
        active_bid[0] = BidRef("database", "8")
        sidebar.load_conditions(
            {"new-bid-condition": Condition(uid="new-bid-condition")},
            {},
            "Other Project",
        )
        sidebar.highlight_conditions({"new-bid-condition"})
        queued["callback"](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000105",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertEqual(sidebar.get_selected_condition_uids(), ["new-bid-condition"])
        self.assertEqual(placement_exits, [])

    def test_sql_condition_duplicate_completion_does_not_place_in_new_bid(self):
        queued = {}
        active_bid = [BidRef("database", "7")]
        placement_calls = []

        class Access:
            @staticmethod
            def is_allowed(feature):
                return feature == Feature.DUPLICATE_CONDITION

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def queue_conditions_duplicate(
                database_id,
                bid_uid,
                condition_uids,
                callback,
                **_options,
            ):
                queued.update(
                    database_id=database_id,
                    bid_uid=bid_uid,
                    condition_uids=list(condition_uids),
                    callback=callback,
                )
                return 1

        coordinator = SimpleNamespace(
            ui_access_manager=Access(),
            conditions_sidebar=None,
            placement=SimpleNamespace(
                enter=lambda *args: placement_calls.append(args),
            ),
            flush_deferred_for_file=lambda _file_path: True,
            _is_takeoff_2d_view_active=lambda: True,
            present_queued_mutation_error=lambda *_args, **_kwargs: None,
        )
        bid = object()
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid=lambda ref: bid if ref == active_bid[0] else None
            ),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: active_bid[0]
            ),
            workspace_state_model=make_workspace_state_model(),
        )
        handler.on_duplicate_requested(["c1"])
        active_bid[0] = BidRef("database", "8")
        queued["callback"](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000106",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("c1-copy",),
                ),
                commit_attempted=True,
            )
        )
        self.assertEqual(placement_calls, [])

    def test_sql_condition_duplicate_completion_places_and_highlights_when_bid_unchanged(
        self,
    ):
        queued = {}
        bid_ref = BidRef("database", "7")
        bid = object()
        placement_calls = []
        highlighted = []

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def queue_conditions_duplicate(
                database_id,
                bid_uid,
                condition_uids,
                callback,
                **options,
            ):
                queued.update(
                    args=(database_id, bid_uid, list(condition_uids)),
                    options=options,
                    callback=callback,
                )
                return 1

        coordinator = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            conditions_sidebar=SimpleNamespace(window=lambda: None),
            placement=SimpleNamespace(
                enter=lambda *args: placement_calls.append(args),
            ),
            highlight_sidebar=lambda uids, reveal=True: highlighted.append(
                (set(uids), reveal)
            ),
            flush_deferred_for_file=lambda _file_path: True,
            _is_takeoff_2d_view_active=lambda: True,
            present_queued_mutation_error=lambda *_args, **_kwargs: None,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(get_bid=lambda _ref: bid),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            workspace_state_model=make_workspace_state_model(),
        )
        handler.on_duplicate_requested(["c1"])
        self.assertEqual(queued["args"], ("database", "7", ["c1"]))
        self.assertEqual(queued["options"], {})
        self.assertEqual(placement_calls, [])
        queued["callback"](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000111",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("c1-copy",),
                ),
                commit_attempted=True,
            )
        )
        self.assertEqual(placement_calls, [("c1-copy", ["c1-copy"])])
        self.assertEqual(highlighted, [({"c1-copy"}, False)])
        self.assertEqual(handler._pending_sql_operations, set())

    def test_sql_condition_duplicate_completion_rejects_same_uid_bid_replacement(self):
        queued = {}
        bid_ref = BidRef("database", "7")
        original_bid = object()
        current_bid = [original_bid]
        placement_calls = []

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def queue_conditions_duplicate(
                database_id,
                bid_uid,
                condition_uids,
                callback,
                **_options,
            ):
                queued["callback"] = callback
                return 1

        coordinator = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            conditions_sidebar=None,
            placement=SimpleNamespace(
                enter=lambda *args: placement_calls.append(args),
            ),
            flush_deferred_for_file=lambda _file_path: True,
            _is_takeoff_2d_view_active=lambda: True,
            present_queued_mutation_error=lambda *_args, **_kwargs: None,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(get_bid=lambda _ref: current_bid[0]),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            workspace_state_model=make_workspace_state_model(),
        )
        handler.on_duplicate_requested(["c1"])
        current_bid[0] = object()
        self.assertIsNot(current_bid[0], original_bid)
        queued["callback"](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000107",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("c1-copy",),
                ),
                commit_attempted=True,
            )
        )
        self.assertEqual(placement_calls, [])

    def test_sql_condition_duplicate_completion_does_not_restore_placement_after_access_revocation(
        self,
    ):
        queued = {}
        bid_ref = BidRef("database", "7")
        bid = object()
        placement_calls = []
        access_allowed = [True]

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def queue_conditions_duplicate(
                database_id,
                bid_uid,
                condition_uids,
                callback,
                **_options,
            ):
                queued["callback"] = callback
                return 1

        coordinator = SimpleNamespace(
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda _feature: access_allowed[0]
            ),
            conditions_sidebar=None,
            placement=SimpleNamespace(
                enter=lambda *args: placement_calls.append(args),
            ),
            flush_deferred_for_file=lambda _file_path: True,
            _is_takeoff_2d_view_active=lambda: True,
            present_queued_mutation_error=lambda *_args, **_kwargs: None,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(get_bid=lambda _ref: bid),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            workspace_state_model=make_workspace_state_model(),
        )
        handler.on_duplicate_requested(["c1"])
        access_allowed[0] = False
        queued["callback"](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000108",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("c1-copy",),
                ),
                commit_attempted=True,
            )
        )
        self.assertEqual(placement_calls, [])

    def test_sql_condition_update_followups_reject_same_uid_bid_replacement(self):
        for replaced in (False, True):
            with self.subTest(replaced=replaced):
                queued = []
                callbacks = []
                bid_ref = BidRef("database", "7")
                current_bid = [object()]
                highlighted = []

                class WriteService:
                    @staticmethod
                    def uses_sql_collaboration_mutations(_database_id):
                        return True

                    @staticmethod
                    def queue_conditions_update(*args):
                        queued.append(args[:-1])
                        callbacks.append(args[-1])
                        return len(callbacks)

                sidebar = SimpleNamespace(
                    set_pending_condition_selection=lambda _uid: None,
                )
                coordinator = SimpleNamespace(
                    ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
                    conditions_sidebar=sidebar,
                    flush_deferred_for_file=lambda _file_path: True,
                    highlight_sidebar=lambda uids: highlighted.append(set(uids)),
                    present_queued_mutation_error=lambda *_args, **_kwargs: None,
                )
                handler = ConditionActionHandler(
                    coordinator=coordinator,
                    project_write_service=WriteService(),
                    project_read_service=None,
                    project_data=SimpleNamespace(get_bid=lambda _ref: current_bid[0]),
                    ui_state_manager=SimpleNamespace(
                        get_selected_bid_ref=lambda: bid_ref
                    ),
                    workspace_state_model=make_workspace_state_model(),
                )
                handler.on_condition_renamed("c1", "Renamed")
                handler.on_move_condition_to_folder("c2", "folder-1")
                handler.on_condition_layer_change_requested(["c3"], "layer-1")
                self.assertEqual(
                    queued,
                    [
                        ("database", "7", ["c1"], {"name": "Renamed"}),
                        ("database", "7", ["c2"], {"folder_uid": "folder-1"}),
                        ("database", "7", ["c3"], {"layer_uid": "layer-1"}),
                    ],
                )
                if replaced:
                    current_bid[0] = object()
                for index, callback in enumerate(callbacks, start=1):
                    callback(
                        QueuedMutationResult(
                            database_id="database",
                            runtime_generation=1,
                            operation_id=f"00000000-0000-0000-0000-{index:012d}",
                            outcome_status=MutationOutcomeStatus.COMMITTED,
                            commit_attempted=True,
                        )
                    )
                self.assertEqual(
                    highlighted, [] if replaced else [{"c1"}, {"c2"}, {"c3"}]
                )

    def test_sql_folder_create_completion_rejects_same_uid_bid_replacement(self):
        for replaced in (False, True):
            with self.subTest(replaced=replaced):
                self._assert_sql_folder_create_completion(replaced=replaced)

    def _assert_sql_folder_create_completion(self, *, replaced):
        queued = {}
        bid_ref = BidRef("database", "7")
        original_bid = object()
        current_bid = [original_bid]
        pending_edits = []
        sidebar = SimpleNamespace(
            set_pending_folder_edit=lambda uid: pending_edits.append(uid),
            window=lambda: None,
        )

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def queue_condition_folder_create(
                database_id,
                bid_uid,
                name,
                parent_uid,
                callback,
            ):
                queued["args"] = (database_id, bid_uid, name, parent_uid)
                queued["callback"] = callback
                return 1

        coordinator = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            conditions_sidebar=sidebar,
            flush_deferred_for_file=lambda _file_path: True,
            present_queued_mutation_error=lambda *_args, **_kwargs: None,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(get_bid=lambda _ref: current_bid[0]),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            workspace_state_model=make_workspace_state_model(),
        )
        handler.on_create_folder_requested("")
        self.assertEqual(queued["args"], ("database", "7", "New Folder", None))
        if replaced:
            current_bid[0] = object()
        queued["callback"](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000109",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("folder-new",),
                ),
                commit_attempted=True,
            )
        )
        self.assertEqual(pending_edits, [] if replaced else ["folder-new"])

    def test_sql_condition_delete_completion_rejects_same_uid_bid_replacement(self):
        for replaced in (False, True):
            with self.subTest(replaced=replaced):
                self._assert_sql_delete_completion(replaced=replaced)

    def _assert_sql_delete_completion(self, *, replaced):
        queued = {}
        bid_ref = BidRef("database", "7")
        current_bid = [object()]
        placement_exits = []
        highlighted = []
        conditions = {"c1": Condition(uid="c1", name="Condition")}
        sidebar = SimpleNamespace(
            get_condition_name=lambda _uid: "Condition",
            condition_selection_after_delete=lambda _uids: "c2",
            window=lambda: None,
        )

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def queue_conditions_delete(
                _database_id, _bid_uid, _condition_uids, callback
            ):
                queued["callback"] = callback
                return 1

        coordinator = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            conditions_sidebar=sidebar,
            placement=SimpleNamespace(
                force_exit=lambda: placement_exits.append(True),
            ),
            ensure_select_mode=lambda: None,
            highlight_sidebar=lambda uids, reveal=True: highlighted.append(
                (set(uids), reveal)
            ),
            flush_deferred_for_file=lambda _file_path: True,
            present_queued_mutation_error=lambda *_args, **_kwargs: None,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid=lambda _ref: current_bid[0],
                get_bid_conditions=lambda: conditions,
            ),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            workspace_state_model=make_workspace_state_model(),
        )
        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "confirm_delete_conditions",
            return_value=["c1"],
        ):
            handler.on_delete_requested(["c1"])
        if replaced:
            current_bid[0] = object()
        queued["callback"](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000110",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertEqual(placement_exits, [] if replaced else [True])
        self.assertEqual(highlighted, [] if replaced else [({"c2"}, False)])

    def test_sql_condition_cut_clipboard_clears_only_after_committed_move(self):
        callbacks = []
        completed = []
        highlighted = []
        bid_ref = BidRef("database", "7")
        current_bid = [object()]

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def queue_conditions_update(
                _database_id,
                _bid_uid,
                _condition_uids,
                _changes,
                callback,
            ):
                callbacks.append(callback)
                return len(callbacks)

        errors = []
        sidebar = SimpleNamespace(
            complete_cut_paste=lambda uids, revision: completed.append(
                (list(uids), revision)
            ),
            window=lambda: None,
        )
        coordinator = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            conditions_sidebar=sidebar,
            flush_deferred_for_file=lambda _file_path: True,
            highlight_sidebar=lambda uids: highlighted.append(set(uids)),
            present_queued_mutation_error=lambda *args: errors.append(args),
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(get_bid=lambda _ref: current_bid[0]),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            workspace_state_model=make_workspace_state_model(),
        )
        target = {
            "kind": "folder",
            "folder_uid": "f1",
            "cut": True,
            "clipboard_revision": 3,
        }
        handler.on_paste_requested(["c1"], target)
        rejected = QueuedMutationResult(
            database_id="database",
            runtime_generation=1,
            operation_id="00000000-0000-0000-0000-000000000201",
            outcome_status=MutationOutcomeStatus.REJECTED,
            commit_attempted=False,
        )
        callbacks[0](rejected)
        self.assertEqual(completed, [])
        self.assertEqual(highlighted, [])
        self.assertEqual(errors, [("database", "Move Conditions", rejected)])
        self.assertEqual(handler._pending_sql_operations, set())
        handler.on_paste_requested(["c1"], target)
        current_bid[0] = object()
        callbacks[1](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000202",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertEqual(completed, [])
        self.assertEqual(highlighted, [])
        handler.on_paste_requested(["c1"], target)
        callbacks[2](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000203",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertEqual(completed, [(["c1"], 3)])
        self.assertEqual(highlighted, [{"c1"}])
        self.assertEqual(len(errors), 1)

    def test_condition_tree_inline_rename_projects_authoritative_result(self):
        app = _app()
        for kind in ("condition", "folder"):
            for outcome in (
                "escape",
                "flush_rejected",
                "sql_rejected",
                "mdb_rejected",
                "sql_committed",
                "mdb_committed",
            ):
                with self.subTest(kind=kind, outcome=outcome):
                    conditions, folders = self._foldered_conditions()
                    sidebar = ConditionsSidebar(None)
                    sidebar.load_conditions(conditions, folders, "Project")
                    sidebar.set_edit_enabled(True)
                    sidebar.set_create_folder_enabled(True)
                    callbacks = []
                    writes = []
                    errors = []

                    def queue(*args):
                        writes.append(args[:-1])
                        callbacks.append(args[-1])
                        return True

                    def reject(*args):
                        writes.append(args)
                        if outcome == "mdb_committed":
                            project_saved_name()
                        return SimpleNamespace(
                            success=outcome == "mdb_committed", error="Rejected"
                        )

                    def save_folder(*args):
                        return reject(*args).success

                    def project_saved_name():
                        target = (
                            conditions["c1"] if kind == "condition" else folders["f1"]
                        )
                        target.name = "Requested name"
                        refresh()

                    def refresh():
                        sidebar.load_conditions(conditions, folders, "Project")

                    coordinator = SimpleNamespace(
                        ui_access_manager=SimpleNamespace(
                            is_allowed=lambda _feature: True
                        ),
                        conditions_sidebar=sidebar,
                        flush_deferred_for_file=lambda _path: outcome
                        != "flush_rejected",
                        refresh_conditions_ui=refresh,
                        highlight_sidebar=sidebar.highlight_conditions,
                        present_queued_mutation_error=lambda *args: errors.append(args),
                    )
                    handler = ConditionActionHandler(
                        coordinator=coordinator,
                        project_write_service=SimpleNamespace(
                            uses_sql_collaboration_mutations=lambda _path: outcome.startswith(
                                "sql_"
                            ),
                            queue_conditions_update=queue,
                            queue_condition_folder_rename=queue,
                            update_condition=reject,
                            rename_condition_folder=save_folder,
                        ),
                        project_read_service=None,
                        project_data=SimpleNamespace(get_bid=lambda _ref: conditions),
                        ui_state_manager=SimpleNamespace(
                            get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1")
                        ),
                        workspace_state_model=make_workspace_state_model(),
                    )
                    sidebar.condition_renamed.connect(handler.on_condition_renamed)
                    sidebar.folder_renamed.connect(handler.on_folder_renamed)
                    try:
                        sidebar.show()
                        sidebar.tree.expandAll()
                        app.processEvents()
                        if kind == "condition":
                            item = sidebar._condition_items["c1"]
                            column = 1
                            sidebar.tree.setCurrentItem(item)
                            sidebar.tree.editItem(item, column)
                        else:
                            item = sidebar._folder_items["f1"]
                            column = 0
                            sidebar.start_folder_edit("f1")
                        original = item.text(column)
                        editor = sidebar.tree.viewport().focusWidget()
                        self.assertIsInstance(editor, QtWidgets.QLineEdit)
                        editor.selectAll()
                        QTest.keyClicks(editor, "Requested name")
                        QTest.keyClick(
                            editor,
                            (
                                QtCore.Qt.Key.Key_Escape
                                if outcome == "escape"
                                else QtCore.Qt.Key.Key_Return
                            ),
                        )
                        app.processEvents()
                        if callbacks:
                            self.assertEqual(item.text(column), original)
                            if outcome == "sql_committed":
                                project_saved_name()
                            callbacks.pop()(
                                QueuedMutationResult(
                                    database_id="db.mdb",
                                    runtime_generation=1,
                                    operation_id="00000000-0000-0000-0000-000000000001",
                                    outcome_status=(
                                        MutationOutcomeStatus.COMMITTED
                                        if outcome == "sql_committed"
                                        else MutationOutcomeStatus.REJECTED
                                    ),
                                )
                            )
                        restored = (
                            sidebar._condition_items["c1"]
                            if kind == "condition"
                            else sidebar._folder_items["f1"]
                        )
                        committed = outcome.endswith("committed")
                        self.assertEqual(
                            restored.text(column),
                            "Requested name" if committed else original,
                        )
                        self.assertEqual(
                            len(writes),
                            0 if outcome in ("escape", "flush_rejected") else 1,
                        )
                        if writes and outcome.startswith("sql_"):
                            self.assertEqual(
                                writes[0],
                                (
                                    (
                                        "db.mdb",
                                        "bid-1",
                                        ["c1"],
                                        {"name": "Requested name"},
                                    )
                                    if kind == "condition"
                                    else ("db.mdb", "bid-1", "f1", "Requested name")
                                ),
                            )
                        elif writes and kind == "condition":
                            self.assertEqual(writes[0][:3], ("db.mdb", "bid-1", "c1"))
                            self.assertEqual(
                                writes[0][3].get_changes(), {"name": "Requested name"}
                            )
                        elif writes:
                            self.assertEqual(
                                writes[0], ("db.mdb", "f1", "Requested name")
                            )
                        self.assertEqual(len(errors), int(outcome == "sql_rejected"))
                        self.assertEqual(
                            conditions["c1"].name,
                            (
                                "Requested name"
                                if committed and kind == "condition"
                                else "Condition 1"
                            ),
                        )
                        self.assertEqual(
                            folders["f1"].name,
                            (
                                "Requested name"
                                if committed and kind == "folder"
                                else "Folder 1"
                            ),
                        )
                    finally:
                        sidebar.close()
                        sidebar.deleteLater()

    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls._quit_on_last_window_closed = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls._quit_on_last_window_closed)

    def tearDown(self):
        self.app.processEvents()

    def test_condition_properties_cancel_does_not_refresh_or_highlight_sidebar(self):
        condition = Condition(uid="c1", name="Condition 1", ref_no=1)
        refreshes = []
        highlights = []
        executed = []

        class Access:
            def is_allowed(self, feature):
                return feature == Feature.EDIT_CONDITION

            def has_license(self):
                return True

        class Sidebar(QtCore.QObject):
            def window(self):
                return None

            def collect_ordered_condition_uids(self):
                return ["c1"]

        class ProjectData:
            bid = SimpleNamespace(measure_base=0)

            def is_current_bid_locked(self):
                return False

            def get_bid_conditions(self):
                return {"c1": condition}

            def get_all_takeoffs(self):
                return []

            def get_current_bid(self):
                return self.bid

            def get_bid(self, _bid_ref):
                return self.bid

        class ReadService:
            def get_cdn_types(self, _file_path):
                return {}

            def get_merged_bid_layers(self, _file_path, _bid_uid):
                return []

        class Dialog:
            condition_navigated = SimpleNamespace(connect=lambda _callback: None)

            def __init__(
                self,
                icon_provider,
                parent,
                condition,
                condition_uids,
                conditions_map,
                cdn_types,
                layers,
                has_takeoffs_fn,
                save_fn,
                workspace_state_model,
                save_async_fn=None,
                has_license=True,
                condition_type_save_fn=None,
                condition_type_save_async_fn=None,
                condition_type_reload_fn=None,
                condition_type_blocked_delete_uids_fn=None,
                condition_type_delete_fn=None,
                layer_reload_fn=None,
                layer_used_uids_fn=None,
                layer_insert_fn=None,
                layer_delete_many_fn=None,
                layer_update_show_fn=None,
                layer_update_all_show_fn=None,
                layer_update_name_fn=None,
                layer_move_fn=None,
                read_service=None,
                read_only=False,
                metric=False,
            ):
                pass

            def deleteLater(self):
                pass

        def request_collaboration_edit(
            database_id,
            resources,
            callback,
            *,
            dependency_resources=(),
            operation_id="",
            owning_surface="desktop",
        ):
            callback(
                EditLeaseResult(
                    True,
                    handle=EditLeaseHandle(
                        database_id=database_id,
                        draft_id="test-draft",
                        runtime_generation=0,
                        operation_id=operation_id,
                        owning_surface=owning_surface,
                        resources=resources,
                        dependency_resources=dependency_resources,
                    ),
                )
            )

        coordinator = SimpleNamespace(
            ui_access_manager=Access(),
            conditions_sidebar=Sidebar(),
            main_window=SimpleNamespace(icon_provider=None),
            event_bus=EventBus(),
            refresh_conditions_ui=lambda: refreshes.append(True),
            highlight_sidebar=lambda uids, reveal=True: highlights.append(set(uids)),
            placement=SimpleNamespace(is_active=False),
            _is_takeoff_2d_view_active=lambda: True,
            flush_deferred_for_file=lambda _file_path: True,
            request_collaboration_edit=request_collaboration_edit,
            end_collaboration_edit=lambda _handle: None,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: False
            ),
            project_read_service=ReadService(),
            project_data=ProjectData(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1")
            ),
            workspace_state_model=make_workspace_state_model(),
        )
        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler.EditConditionDialog",
            Dialog,
        ), patch(
            "ost_visualizer.presentation.handlers.condition_action_handler.exec_with_ost_blocking",
            lambda dialog, _event_bus: (
                executed.append(dialog) or QtWidgets.QDialog.DialogCode.Rejected
            ),
        ):
            handler.on_edit_requested(["c1"])
        self.assertEqual(len(executed), 1)
        self.assertIsInstance(executed[0], Dialog)
        self.assertEqual(refreshes, [])
        self.assertEqual(highlights, [])

    def test_condition_properties_rejected_save_preserves_active_takeoff_tool(self):
        outcome = self._run_condition_properties_save(
            UpdateConditionResultDto(success=False, error="Rejected")
        )
        self.assertFalse(outcome["result"].success)
        self.assertEqual(outcome["result"].error, "Rejected")
        self.assertEqual(len(outcome["save_calls"]), 1)
        self.assertEqual(outcome["save_calls"][0][:3], ("db.mdb", "bid-1", "c1"))
        self.assertTrue(outcome["placement"].is_active)
        self.assertEqual(outcome["highlights"], [])
        self.assertEqual(outcome["refreshes"], [])

    def test_condition_properties_accepted_save_highlights_and_refreshes_dialog(self):
        outcome = self._run_condition_properties_save(
            UpdateConditionResultDto(success=True)
        )
        self.assertTrue(outcome["result"].success)
        self.assertEqual(len(outcome["save_calls"]), 1)
        self.assertEqual(outcome["highlights"], [{"c1"}])
        self.assertEqual(outcome["refreshes"], [{"c1": outcome["condition"]}])
        self.assertTrue(outcome["placement"].is_active)

    def _run_condition_properties_save(self, update_result):
        condition = Condition(uid="c1", name="Condition 1", ref_no=1)
        save_calls = []
        highlights = []
        refreshes = []
        results = []

        class Access:
            @staticmethod
            def is_allowed(feature):
                return feature == Feature.EDIT_CONDITION

            @staticmethod
            def has_license():
                return True

        class Sidebar(QtCore.QObject):
            @staticmethod
            def window():
                return None

            @staticmethod
            def collect_ordered_condition_uids():
                return ["c1"]

        class ProjectData:
            bid = SimpleNamespace(measure_base=0)

            @staticmethod
            def is_current_bid_locked():
                return False

            @staticmethod
            def get_bid_conditions():
                return {"c1": condition}

            @staticmethod
            def get_all_takeoffs():
                return []

            @staticmethod
            def get_current_bid():
                return ProjectData.bid

            @staticmethod
            def get_bid(_bid_ref):
                return ProjectData.bid

        class ReadService:
            @staticmethod
            def get_cdn_types(_file_path):
                return {}

            @staticmethod
            def get_merged_bid_layers(_file_path, _bid_uid):
                return []

        class Dialog:
            condition_navigated = SimpleNamespace(connect=lambda _callback: None)

            def __init__(self, *args, save_fn, **kwargs):
                _ = args, kwargs
                self.save_fn = save_fn

            @staticmethod
            def refresh_condition_data(conditions):
                refreshes.append(dict(conditions))

            @staticmethod
            def deleteLater():
                pass

        placement = SimpleNamespace(is_active=True)
        sidebar = Sidebar()
        coordinator = SimpleNamespace(
            ui_access_manager=Access(),
            conditions_sidebar=sidebar,
            main_window=SimpleNamespace(icon_provider=None),
            event_bus=EventBus(),
            highlight_sidebar=lambda uids, reveal=True: highlights.append(set(uids)),
            placement=placement,
            _is_takeoff_2d_view_active=lambda: True,
            flush_deferred_for_file=lambda _file_path: True,
            request_collaboration_edit=lambda _database_id, _resources, callback, **_kw: (
                callback(
                    EditLeaseResult(
                        True,
                        handle=EditLeaseHandle(
                            database_id="db.mdb",
                            draft_id="condition-edit-test",
                            runtime_generation=0,
                            operation_id="edit-condition-dialog",
                            owning_surface="condition-sidebar",
                            resources=(ResourceRef("condition", "c1", 1),),
                        ),
                    )
                )
            ),
            end_collaboration_edit=lambda _handle: None,
        )
        write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False,
            update_condition=lambda *args: save_calls.append(args) or update_result,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=write_service,
            project_read_service=ReadService(),
            project_data=ProjectData(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1")
            ),
            workspace_state_model=make_workspace_state_model(),
        )

        def execute(dialog, _event_bus):
            result = dialog.save_fn(
                "c1", UpdateConditionDto({"name": "Condition 1 edited"})
            )
            results.append(result)
            return QtWidgets.QDialog.DialogCode.Rejected

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler.EditConditionDialog",
            Dialog,
        ), patch(
            "ost_visualizer.presentation.handlers.condition_action_handler.exec_with_ost_blocking",
            execute,
        ):
            handler.on_edit_requested(["c1"])
        self.assertEqual(len(results), 1)
        return {
            "result": results[0],
            "save_calls": save_calls,
            "highlights": highlights,
            "refreshes": refreshes,
            "placement": placement,
            "condition": condition,
        }

    def test_sql_condition_editor_save_transfers_and_reacquires_its_lease(self):
        run = self._run_sql_condition_editor_save(MutationOutcomeStatus.COMMITTED)
        self.assertEqual(run["lease_requests"], [run["expected_resources"]] * 2)
        self.assertEqual(
            run["queued"][0][:4], ("database", "7", ["c2"], {"name": "Renamed"})
        )
        self.assertEqual(run["queued"][0][4].draft_id, "draft-1")
        self.assertEqual([result.success for result in run["completions"]], [True])
        self.assertEqual(
            [handle.draft_id for handle in run["ended_leases"]], ["draft-2"]
        )
        self.assertEqual(run["errors"], [])

    def test_sql_condition_editor_rejected_save_reports_error_and_reacquires_lease(
        self,
    ):
        run = self._run_sql_condition_editor_save(MutationOutcomeStatus.REJECTED)
        self.assertEqual(run["lease_requests"], [run["expected_resources"]] * 2)
        self.assertEqual(
            run["queued"][0][:4], ("database", "7", ["c2"], {"name": "Renamed"})
        )
        self.assertEqual(len(run["completions"]), 1)
        completion = run["completions"][0]
        self.assertFalse(completion.success)
        self.assertEqual(completion.error, "Failed to save condition.")
        self.assertTrue(completion.error_presented)
        self.assertEqual(len(run["errors"]), 1)
        self.assertEqual(run["errors"][0][:2], ("database", "Save Condition"))
        self.assertEqual(
            [handle.draft_id for handle in run["ended_leases"]], ["draft-2"]
        )

    def _run_sql_condition_editor_save(self, outcome):
        conditions = {
            "c1": Condition(uid="c1", name="Condition 1", ref_no=1),
            "c2": Condition(uid="c2", name="Condition 2", ref_no=2),
        }
        lease_requests = []
        ended_leases = []
        queued = []
        completions = []
        errors = []

        class Access:
            @staticmethod
            def is_allowed(_feature):
                return True

            @staticmethod
            def has_license():
                return True

        class Sidebar:
            @staticmethod
            def window():
                return None

            @staticmethod
            def collect_ordered_condition_uids():
                return ["c1", "c2"]

        class ProjectData:
            bid = SimpleNamespace(measure_base=0)

            @staticmethod
            def is_current_bid_locked():
                return False

            @staticmethod
            def get_bid_conditions():
                return conditions

            @staticmethod
            def get_all_takeoffs():
                return []

            @staticmethod
            def get_current_bid():
                return ProjectData.bid

            @staticmethod
            def get_bid(_bid_ref):
                return ProjectData.bid

            @staticmethod
            def get_cdn_types():
                return {}

            @staticmethod
            def get_bid_layer_snapshot():
                return []

            @staticmethod
            def get_layer_uids_in_use():
                return set()

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def queue_conditions_update(
                database_id,
                bid_uid,
                condition_uids,
                changes,
                callback,
                *,
                edit_lease_handle,
            ):
                queued.append(
                    (
                        database_id,
                        bid_uid,
                        list(condition_uids),
                        dict(changes),
                        edit_lease_handle,
                    )
                )
                callback(
                    QueuedMutationResult(
                        database_id=database_id,
                        runtime_generation=1,
                        operation_id="00000000-0000-0000-0000-000000000001",
                        outcome_status=outcome,
                        commit_attempted=outcome == MutationOutcomeStatus.COMMITTED,
                    )
                )
                return 1

        def request_collaboration_edit(
            database_id,
            resources,
            callback,
            *,
            dependency_resources=(),
            operation_id="",
            owning_surface="desktop",
        ):
            lease_requests.append(tuple(resources))
            callback(
                EditLeaseResult(
                    True,
                    handle=EditLeaseHandle(
                        database_id=database_id,
                        draft_id=f"draft-{len(lease_requests)}",
                        runtime_generation=1,
                        operation_id=operation_id,
                        owning_surface=owning_surface,
                        resources=tuple(resources),
                        dependency_resources=dependency_resources,
                    ),
                )
            )

        coordinator = SimpleNamespace(
            ui_access_manager=Access(),
            conditions_sidebar=Sidebar(),
            main_window=SimpleNamespace(icon_provider=None),
            event_bus=EventBus(),
            highlight_sidebar=lambda *_args, **_kwargs: None,
            placement=SimpleNamespace(is_active=False),
            _is_takeoff_2d_view_active=lambda: True,
            flush_deferred_for_file=lambda _file_path: True,
            request_collaboration_edit=request_collaboration_edit,
            end_collaboration_edit=ended_leases.append,
            present_queued_mutation_error=lambda *args: errors.append(args),
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=FakeReadService(),
            project_data=ProjectData(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("database", "7")
            ),
            workspace_state_model=make_workspace_state_model(),
        )

        def execute_dialog(dialog, _event_bus):
            self.assertIsNotNone(dialog._layer_insert_async_fn)
            self.assertIsNotNone(dialog._layer_delete_many_async_fn)
            self.assertIsNotNone(dialog._layer_update_name_async_fn)
            self.assertIsNotNone(dialog._layer_move_async_fn)
            dto = UpdateConditionDto()
            dto.set("name", "Renamed")
            self.assertTrue(dialog._save_async_fn("c2", dto, completions.append))
            return QtWidgets.QDialog.DialogCode.Rejected

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler.exec_with_ost_blocking",
            execute_dialog,
        ):
            handler.on_edit_requested(["c1"])
        expected_resources = (
            ResourceRef("condition", "c1", 7),
            ResourceRef("condition", "c2", 7),
        )
        return {
            "expected_resources": expected_resources,
            "lease_requests": lease_requests,
            "queued": queued,
            "completions": completions,
            "ended_leases": ended_leases,
            "errors": errors,
        }

    def test_delayed_condition_editor_lease_does_not_open_after_bid_switch(self):
        executions, ended_leases, handle = self._run_delayed_condition_editor_lease(
            switch_bid=True
        )
        self.assertEqual(executions, [])
        self.assertEqual(ended_leases, [handle])

    def test_delayed_condition_editor_lease_opens_when_bid_unchanged(self):
        executions, ended_leases, handle = self._run_delayed_condition_editor_lease(
            switch_bid=False
        )
        self.assertEqual(executions, [True])
        self.assertEqual(ended_leases, [handle])

    def _run_delayed_condition_editor_lease(self, *, switch_bid):
        condition = Condition(uid="c1", name="Condition 1", ref_no=1)
        bid_ref = BidRef("database", "1")
        selected_bid_ref = [bid_ref]
        original_bid = object()
        current_bid = [original_bid]
        lease_callbacks = []
        ended_leases = []
        executions = []

        class Access:
            @staticmethod
            def is_allowed(_feature):
                return True

            @staticmethod
            def has_license():
                return True

        class Sidebar:
            @staticmethod
            def window():
                return None

            @staticmethod
            def collect_ordered_condition_uids():
                return ["c1"]

        class ProjectData:
            @staticmethod
            def is_current_bid_locked():
                return False

            @staticmethod
            def get_bid_conditions():
                return {"c1": condition}

            @staticmethod
            def get_all_takeoffs():
                return []

            @staticmethod
            def get_current_bid():
                return SimpleNamespace(measure_base=0)

            @staticmethod
            def get_cdn_types():
                return {}

            @staticmethod
            def get_bid_layer_snapshot():
                return []

            @staticmethod
            def get_layer_uids_in_use():
                return set()

            @staticmethod
            def get_bid(_bid_ref):
                return current_bid[0]

        class Dialog(QtWidgets.QDialog):
            condition_navigated = QtCore.Signal(str)

            def __init__(self, *args, **kwargs):
                super().__init__()

            @staticmethod
            def refresh_condition_data(_conditions):
                pass

        def request_collaboration_edit(
            _database_id,
            _resources,
            callback,
            **_kwargs,
        ):
            lease_callbacks.append(callback)

        coordinator = SimpleNamespace(
            ui_access_manager=Access(),
            conditions_sidebar=Sidebar(),
            main_window=SimpleNamespace(icon_provider=None),
            event_bus=EventBus(),
            placement=SimpleNamespace(is_active=False),
            _is_takeoff_2d_view_active=lambda: True,
            flush_deferred_for_file=lambda _file_path: True,
            request_collaboration_edit=request_collaboration_edit,
            end_collaboration_edit=ended_leases.append,
            highlight_sidebar=lambda *_args, **_kwargs: None,
            present_queued_mutation_error=lambda *_args, **_kwargs: None,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: True
            ),
            project_read_service=None,
            project_data=ProjectData(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: selected_bid_ref[0]
            ),
            workspace_state_model=make_workspace_state_model(),
        )
        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "EditConditionDialog",
            Dialog,
        ), patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "exec_with_ost_blocking",
            lambda *_args: executions.append(True),
        ):
            handler.on_edit_requested(["c1"])
            self.assertEqual(len(lease_callbacks), 1)
            if switch_bid:
                selected_bid_ref[0] = BidRef("database", "2")
            handle = EditLeaseHandle(
                database_id="database",
                draft_id="late-condition-edit",
                runtime_generation=1,
                operation_id="edit-condition-dialog",
                owning_surface="condition-sidebar",
                resources=(ResourceRef("condition", "c1", 1),),
            )
            lease_callbacks[0](EditLeaseResult(True, handle=handle))
        return executions, ended_leases, handle

    def test_open_condition_editor_rejects_same_uid_condition_replacement(self):
        save_results, writes = self._run_open_condition_editor_save(
            replace_condition=True
        )
        self.assertFalse(save_results[0].success)
        self.assertEqual(
            save_results[0].error,
            "The active bid or edit access changed.",
        )
        self.assertEqual(writes, [])

    def test_open_condition_editor_saves_when_condition_family_is_unchanged(self):
        save_results, writes = self._run_open_condition_editor_save(
            replace_condition=False
        )
        self.assertTrue(save_results[0].success)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][:3], ("database", "1", "c1"))
        self.assertEqual(writes[0][3].get_changes(), {"name": "Edited"})

    def _run_open_condition_editor_save(self, *, replace_condition):
        original = Condition(uid="c1", name="Original", ref_no=1)
        conditions = [{"c1": original}]
        writes = []
        save_results = []
        bid_ref = BidRef("database", "1")

        class Sidebar(QtCore.QObject):
            @staticmethod
            def window():
                return None

            @staticmethod
            def collect_ordered_condition_uids():
                return ["c1"]

        class Dialog:
            condition_navigated = SimpleNamespace(connect=lambda _callback: None)

            def __init__(self, *args, save_fn, **kwargs):
                self.save_fn = save_fn

            @staticmethod
            def refresh_condition_data(_conditions):
                pass

            @staticmethod
            def deleteLater():
                pass

        bid_owner = SimpleNamespace(measure_base=0)
        project_data = SimpleNamespace(
            is_current_bid_locked=lambda: False,
            get_bid_conditions=lambda: conditions[0],
            get_all_takeoffs=lambda: [],
            get_current_bid=lambda: bid_owner,
            get_bid=lambda _bid_ref: bid_owner,
        )
        coordinator = SimpleNamespace(
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda _feature: True,
                has_license=lambda: True,
            ),
            conditions_sidebar=Sidebar(),
            main_window=SimpleNamespace(icon_provider=None),
            event_bus=EventBus(),
            placement=SimpleNamespace(is_active=False),
            _is_takeoff_2d_view_active=lambda: True,
            flush_deferred_for_file=lambda _file_path: True,
            request_collaboration_edit=lambda _database_id, _resources, callback, **_kw: (
                callback(
                    EditLeaseResult(
                        True,
                        handle=EditLeaseHandle(
                            database_id="database",
                            draft_id="condition-editor",
                            runtime_generation=1,
                            operation_id="edit-condition-dialog",
                            owning_surface="condition-sidebar",
                            resources=(ResourceRef("condition", "c1", 1),),
                        ),
                    )
                )
            ),
            highlight_sidebar=lambda *_args, **_kwargs: None,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: False,
                update_condition=lambda *args: (
                    writes.append(args) or UpdateConditionResultDto(success=True)
                ),
            ),
            project_read_service=SimpleNamespace(
                get_cdn_types=lambda _file_path: {},
                get_merged_bid_layers=lambda _file_path, _bid_uid: [],
            ),
            project_data=project_data,
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            workspace_state_model=make_workspace_state_model(),
        )

        def execute(dialog, _event_bus):
            if replace_condition:
                conditions[0] = {
                    "c1": Condition(uid="c1", name="Replacement", ref_no=1)
                }
            save_results.append(
                dialog.save_fn("c1", UpdateConditionDto({"name": "Edited"}))
            )
            return QtWidgets.QDialog.DialogCode.Rejected

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "EditConditionDialog",
            Dialog,
        ), patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "exec_with_ost_blocking",
            execute,
        ), patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "delete_later_if_valid",
            lambda _dialog: None,
        ):
            handler.on_edit_requested(["c1"])
        return save_results, writes

    def test_create_condition_dialog_rejects_same_uid_bid_replacement(self):
        save_results, writes, highlighted = self._run_create_condition_dialog_save(
            replace_bid=True
        )
        self.assertFalse(save_results[0].success)
        self.assertEqual(
            save_results[0].error, "The active bid or edit access changed."
        )
        self.assertEqual(writes, [])
        self.assertEqual(highlighted, [])

    def test_create_condition_dialog_saves_and_highlights_when_bid_unchanged(self):
        save_results, writes, highlighted = self._run_create_condition_dialog_save(
            replace_bid=False
        )
        self.assertTrue(save_results[0].success)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][:2], ("database", "1"))
        self.assertEqual(writes[0][2].name, "New Condition")
        self.assertIsNone(writes[0][2].folder_uid)
        self.assertEqual(highlighted, [{"new-condition"}])

    def _run_create_condition_dialog_save(self, *, replace_bid):
        bid_ref = BidRef("database", "1")
        current_bid = [SimpleNamespace(measure_base=0)]
        writes = []
        save_results = []
        highlighted = []
        conditions = {}

        class Sidebar(QtCore.QObject):
            @staticmethod
            def window():
                return None

        class Dialog:
            def __init__(self, *args, save_fn, **kwargs):
                self.save_fn = save_fn
                self._dirty = False

            @staticmethod
            def set_apply_allowed(_allowed):
                pass

            @staticmethod
            def deleteLater():
                pass

        def create_condition(*args):
            writes.append(args)
            conditions["new-condition"] = Condition(uid="new-condition", name="New")
            return SimpleNamespace(
                write_success=True,
                value="new-condition",
                refresh_failed=False,
                projection=None,
            )

        project_data = SimpleNamespace(
            get_bid=lambda _bid_ref: current_bid[0],
            get_current_bid=lambda: current_bid[0],
            get_bid_conditions=lambda: conditions,
        )
        coordinator = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            conditions_sidebar=Sidebar(),
            main_window=SimpleNamespace(icon_provider=None),
            event_bus=EventBus(),
            flush_deferred_for_file=lambda _file_path: True,
            highlight_sidebar=lambda uids: highlighted.append(set(uids)),
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: False,
                create_condition_result=create_condition,
            ),
            project_read_service=SimpleNamespace(
                get_cdn_types=lambda _file_path: {},
                get_merged_bid_layers=lambda _file_path, _bid_uid: [],
            ),
            project_data=project_data,
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            workspace_state_model=make_workspace_state_model(),
        )

        def execute(dialog, _event_bus):
            if replace_bid:
                current_bid[0] = SimpleNamespace(measure_base=0)
            save_results.append(
                dialog.save_fn("__new__", UpdateConditionDto({"name": "New Condition"}))
            )
            return QtWidgets.QDialog.DialogCode.Rejected

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "EditConditionDialog",
            Dialog,
        ), patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "exec_with_ost_blocking",
            execute,
        ), patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "delete_later_if_valid",
            lambda _dialog: None,
        ):
            handler.on_create_requested("")
        return save_results, writes, highlighted

    def test_create_condition_in_folder_highlights_after_own_family_reconstruction(
        self,
    ):
        save_results, highlighted = self._run_create_condition_in_folder(
            changed_folder=False
        )
        self.assertTrue(save_results[0].success)
        self.assertEqual(highlighted, [{"new-condition"}])

    def test_create_condition_in_folder_does_not_highlight_after_folder_changed(self):
        save_results, highlighted = self._run_create_condition_in_folder(
            changed_folder=True
        )
        self.assertTrue(save_results[0].success)
        self.assertEqual(highlighted, [])

    def _run_create_condition_in_folder(self, *, changed_folder):
        bid_ref = BidRef("database", "1")
        bid_owner = SimpleNamespace(measure_base=0)
        folders = [{"f1": BidConditionFolder(uid="f1", name="Folder")}]
        conditions = {}
        highlighted = []
        save_results = []

        class Sidebar(QtCore.QObject):
            @staticmethod
            def window():
                return None

        class Dialog:
            def __init__(self, *args, save_fn, **kwargs):
                self.save_fn = save_fn
                self._dirty = False

            @staticmethod
            def set_apply_allowed(_allowed):
                pass

            @staticmethod
            def deleteLater():
                pass

        def create_condition(*_args):
            folders[0] = {
                uid: (
                    replace(folder, name="Changed")
                    if changed_folder
                    else replace(folder)
                )
                for uid, folder in folders[0].items()
            }
            conditions["new-condition"] = Condition(uid="new-condition", name="New")
            return SimpleNamespace(
                write_success=True,
                value="new-condition",
                refresh_failed=False,
                projection=None,
            )

        project_data = SimpleNamespace(
            get_bid=lambda _bid_ref: bid_owner,
            get_current_bid=lambda: bid_owner,
            get_bid_condition_folders=lambda: folders[0],
            get_bid_conditions=lambda: conditions,
        )
        coordinator = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            conditions_sidebar=Sidebar(),
            main_window=SimpleNamespace(icon_provider=None),
            event_bus=EventBus(),
            flush_deferred_for_file=lambda _file_path: True,
            highlight_sidebar=lambda uids: highlighted.append(set(uids)),
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: False,
                create_condition_result=create_condition,
            ),
            project_read_service=SimpleNamespace(
                get_cdn_types=lambda _file_path: {},
                get_merged_bid_layers=lambda _file_path, _bid_uid: [],
            ),
            project_data=project_data,
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            workspace_state_model=make_workspace_state_model(),
        )

        def execute(dialog, _event_bus):
            save_results.append(
                dialog.save_fn("__new__", UpdateConditionDto({"name": "New"}))
            )
            return QtWidgets.QDialog.DialogCode.Accepted

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "EditConditionDialog",
            Dialog,
        ), patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "exec_with_ost_blocking",
            execute,
        ), patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "delete_later_if_valid",
            lambda _dialog: None,
        ):
            handler.on_create_requested("f1")
        return save_results, highlighted

    def test_condition_delete_confirmation_rejects_same_uid_replacement(self):
        self.assertEqual(self._run_condition_delete_confirmation(replace=True), [])

    def test_condition_delete_confirmation_rejects_bid_switch(self):
        self.assertEqual(
            self._run_condition_delete_confirmation(replace=False, switch_bid=True),
            [],
        )

    def test_condition_delete_confirmation_deletes_unreplaced_condition(self):
        self.assertEqual(
            self._run_condition_delete_confirmation(replace=False),
            [("database", "1", ["c1"])],
        )

    def _run_condition_delete_confirmation(self, *, replace, switch_bid=False):
        original = Condition(uid="c1", name="Original", ref_no=1)
        conditions = [{"c1": original}]
        writes = []
        bid_ref = BidRef("database", "1")
        selected_bid_ref = [bid_ref]
        sidebar = SimpleNamespace(
            get_condition_name=lambda uid: conditions[0][uid].name,
            window=lambda: None,
            condition_selection_after_delete=lambda _uids: None,
        )
        coordinator = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            conditions_sidebar=sidebar,
            flush_deferred_for_file=lambda _file_path: True,
            placement=SimpleNamespace(force_exit=lambda: None),
            ensure_select_mode=lambda: None,
            highlight_sidebar=lambda *_args, **_kwargs: None,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: False,
                delete_conditions=lambda *args: writes.append(args) or True,
            ),
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid_conditions=lambda: conditions[0],
            ),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: selected_bid_ref[0]
            ),
            workspace_state_model=make_workspace_state_model(),
        )

        def replace_during_confirmation(_parent, _names):
            if replace:
                conditions[0] = {
                    "c1": Condition(uid="c1", name="Replacement", ref_no=1)
                }
            if switch_bid:
                selected_bid_ref[0] = BidRef("database", "2")
            return ["c1"]

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "confirm_delete_conditions",
            replace_during_confirmation,
        ):
            handler.on_delete_requested(["c1"])
        return writes

    def test_condition_folder_delete_confirmation_rejects_same_uid_replacement(self):
        self.assertEqual(
            self._run_condition_folder_delete_confirmation(replace=True), []
        )

    def test_condition_folder_delete_confirmation_deletes_unreplaced_folder(self):
        self.assertEqual(
            self._run_condition_folder_delete_confirmation(replace=False),
            [("database", "1", ["f1"])],
        )

    def _run_condition_folder_delete_confirmation(self, *, replace):
        folders = [{"f1": BidConditionFolder(uid="f1", name="Original")}]
        writes = []
        bid_ref = BidRef("database", "1")
        coordinator = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            conditions_sidebar=SimpleNamespace(window=lambda: None),
            flush_deferred_for_file=lambda _file_path: True,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: False,
                validate_condition_folder_delete=lambda *_args: SimpleNamespace(
                    blocked_uids=()
                ),
                delete_condition_folders_result=lambda *args: (
                    writes.append(args)
                    or SimpleNamespace(write_success=True, refresh_failed=False)
                ),
            ),
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid_condition_folders=lambda: folders[0],
            ),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            workspace_state_model=make_workspace_state_model(),
        )

        def replace_during_confirmation(*_args, **_kwargs):
            if replace:
                folders[0] = {"f1": BidConditionFolder(uid="f1", name="Replacement")}
            return [("Original", "f1")]

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "confirm_multi_delete",
            replace_during_confirmation,
        ):
            handler.on_folder_delete_requested(["f1"])
        return writes

    def test_condition_renumber_confirmation_rejects_same_uid_replacement(self):
        self.assertEqual(self._run_condition_renumber_confirmation(replace=True), [])

    def test_condition_renumber_confirmation_renumbers_unreplaced_conditions(self):
        self.assertEqual(
            self._run_condition_renumber_confirmation(replace=False),
            [("database", "1", ["c1"])],
        )

    def _run_condition_renumber_confirmation(self, *, replace):
        conditions = [{"c1": Condition(uid="c1", name="Original", ref_no=1)}]
        writes = []
        bid_ref = BidRef("database", "1")
        sidebar = SimpleNamespace(
            collect_ordered_condition_uids=lambda: ["c1"],
            window=lambda: None,
        )
        coordinator = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            conditions_sidebar=sidebar,
            flush_deferred_for_file=lambda _file_path: True,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: False,
                renumber_conditions=lambda *args: writes.append(args) or True,
            ),
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid_conditions=lambda: conditions[0],
            ),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            workspace_state_model=make_workspace_state_model(),
        )

        def replace_during_confirmation(*_args, **_kwargs):
            if replace:
                conditions[0] = {
                    "c1": Condition(uid="c1", name="Replacement", ref_no=1)
                }
            return True

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler.confirm",
            replace_during_confirmation,
        ):
            handler.on_renumber_requested()
        return writes


class BidLockPermissionTests(unittest.TestCase):
    def _condition_structure_handler(self, allowed):
        access = _permissions__FakeAccess(allowed)
        write_service = _permissions__ConditionStructureWriteService()
        folder = SimpleNamespace(name="Folder 1")
        coordinator = SimpleNamespace(
            ui_access_manager=access,
            conditions_sidebar=SimpleNamespace(window=lambda: None),
            flush_deferred_for_file=lambda _file_path: True,
        )
        ui_state = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1")
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=write_service,
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid_condition_folders=lambda: {"folder-1": folder}
            ),
            ui_state_manager=ui_state,
            workspace_state_model=make_workspace_state_model(),
        )
        return handler, access, write_service

    def test_condition_folder_delete_and_move_use_structure_permission(self):
        handler, access, write_service = self._condition_structure_handler(
            {Feature.DELETE_CONDITION, Feature.EDIT_CONDITION}
        )
        handler.on_folder_delete_requested(["folder-1"])
        handler.on_move_condition_to_folder("cond-1", "folder-2")
        self.assertEqual(write_service.deleted_folders, [])
        self.assertEqual(write_service.condition_updates, [])
        self.assertEqual(
            access.checked,
            [
                Feature.EDIT_CONDITION_STRUCTURE,
                Feature.EDIT_CONDITION_STRUCTURE,
            ],
        )
        handler, access, write_service = self._condition_structure_handler(
            {Feature.EDIT_CONDITION_STRUCTURE}
        )
        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "confirm_multi_delete",
            return_value=[("Folder 1", "folder-1")],
        ):
            handler.on_folder_delete_requested(["folder-1"])
        handler.on_move_condition_to_folder("cond-1", "folder-2")
        self.assertEqual(write_service.deleted_folders, [("db.mdb", ["folder-1"])])
        self.assertEqual(len(write_service.condition_updates), 1)
        _file_path, _bid_uid, condition_uid, dto = write_service.condition_updates[0]
        self.assertEqual(condition_uid, "cond-1")
        self.assertEqual(dto.get_changes()["folder_uid"], "folder-2")
        self.assertEqual(
            access.checked,
            [
                Feature.EDIT_CONDITION_STRUCTURE,
                Feature.EDIT_CONDITION_STRUCTURE,
                Feature.EDIT_CONDITION_STRUCTURE,
            ],
        )

    def test_batch_condition_field_update_reloads_once_after_loop(self):
        access = _permissions__FakeAccess({Feature.EDIT_CONDITION})
        write_service = _permissions__ConditionStructureWriteService()
        coordinator = SimpleNamespace(
            ui_access_manager=access,
            conditions_sidebar=None,
            refresh_conditions_ui=lambda: None,
            highlight_sidebar=lambda _uids: None,
            flush_deferred_for_file=lambda _file_path: True,
        )
        ui_state = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1")
        )
        project_data = SimpleNamespace(get_bid_conditions=lambda: {})
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=write_service,
            project_read_service=None,
            project_data=project_data,
            ui_state_manager=ui_state,
            workspace_state_model=make_workspace_state_model(),
        )
        handler.on_condition_layer_change_requested(["cond-1", "cond-2"], "layer-1")
        self.assertEqual(len(write_service.condition_updates), 2)
        self.assertEqual(
            [
                call.get("publish_database_refreshed_after_write")
                for call in write_service.condition_update_options
            ],
            [False, False],
        )
        self.assertEqual(
            write_service.reloads,
            [
                (
                    "db.mdb",
                    "bid-1",
                    ["cond-1", "cond-2"],
                    ["layer_uid"],
                    [ChangeOperation.UPDATE],
                )
            ],
        )

    def test_batch_condition_field_update_skips_failed_rows_and_warns_on_reload_failure(
        self,
    ):
        for label, failing, reload_ok, expected_reload, expected_warnings in (
            ("one row fails", {"cond-1"}, True, ["cond-2"], 0),
            ("every row fails", {"cond-1", "cond-2"}, True, None, 0),
            ("reload fails", set(), False, ["cond-1", "cond-2"], 1),
        ):
            with self.subTest(label):
                highlighted = []
                warnings = []

                class WriteService(_permissions__ConditionStructureWriteService):
                    def update_condition(
                        self, db_path, bid_uid, condition_uid, *args, **kw
                    ):
                        super().update_condition(
                            db_path, bid_uid, condition_uid, *args, **kw
                        )
                        return SimpleNamespace(
                            success=condition_uid not in failing, error="Rejected"
                        )

                    def reload_conditions_and_notify(self, *args):
                        super().reload_conditions_and_notify(*args)
                        return reload_ok

                write_service = WriteService()
                coordinator = SimpleNamespace(
                    ui_access_manager=_permissions__FakeAccess(
                        {Feature.EDIT_CONDITION}
                    ),
                    conditions_sidebar=SimpleNamespace(window=lambda: None),
                    highlight_sidebar=lambda uids: highlighted.append(set(uids)),
                    flush_deferred_for_file=lambda _file_path: True,
                )
                handler = ConditionActionHandler(
                    coordinator=coordinator,
                    project_write_service=write_service,
                    project_read_service=None,
                    project_data=SimpleNamespace(),
                    ui_state_manager=SimpleNamespace(
                        get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1")
                    ),
                    workspace_state_model=make_workspace_state_model(),
                )
                with patch(
                    "ost_visualizer.presentation.handlers.condition_action_handler."
                    "show_warning",
                    lambda *args: warnings.append(args),
                ), patch(
                    "ost_visualizer.presentation.handlers.condition_action_handler."
                    "logger"
                ) as handler_logger:
                    handler.on_condition_type_change_requested(
                        ["cond-1", "cond-2"], "type-1"
                    )
                self.assertEqual(handler_logger.warning.call_count, len(failing))
                self.assertEqual(len(write_service.condition_updates), 2)
                self.assertEqual(
                    [call[3].get_changes() for call in write_service.condition_updates],
                    [{"cdn_type_uid": "type-1"}] * 2,
                )
                self.assertEqual(
                    [reload[:4] for reload in write_service.reloads],
                    (
                        []
                        if expected_reload is None
                        else [("db.mdb", "bid-1", expected_reload, ["cdn_type_uid"])]
                    ),
                )
                self.assertEqual(len(warnings), expected_warnings)
                if expected_warnings:
                    self.assertEqual(warnings[0][1], "Refresh Error")
                    self.assertIn("The condition was updated", warnings[0][2])
                    self.assertEqual(highlighted, [])
                else:
                    self.assertEqual(
                        highlighted,
                        [] if expected_reload is None else [set(expected_reload)],
                    )

    def test_condition_duplicate_refresh_failure_warns_without_placement(self):
        warnings = []
        access = _permissions__FakeAccess({Feature.DUPLICATE_CONDITION})
        write_service = _permissions__ConditionDuplicateRefreshFailedWriteService()
        placement = SimpleNamespace(entered=[])
        placement.enter = lambda *args: placement.entered.append(args)
        coordinator = SimpleNamespace(
            ui_access_manager=access,
            conditions_sidebar=None,
            placement=placement,
            _is_takeoff_2d_view_active=lambda: True,
            refresh_conditions_ui=lambda: None,
            highlight_sidebar=lambda _uids: None,
            flush_deferred_for_file=lambda _file_path: True,
        )
        ui_state = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1")
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=write_service,
            project_read_service=None,
            project_data=SimpleNamespace(),
            ui_state_manager=ui_state,
            workspace_state_model=make_workspace_state_model(),
        )
        from ost_visualizer.presentation.handlers import condition_action_handler

        old_warning = condition_action_handler.show_warning
        condition_action_handler.show_warning = lambda *args: warnings.append(args)
        try:
            handler.on_duplicate_requested(["condition-1"])
        finally:
            condition_action_handler.show_warning = old_warning
        self.assertEqual(write_service.calls, [("db.mdb", "bid-1", ["condition-1"])])
        self.assertEqual(placement.entered, [])
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0][:2], (None, "Refresh Error"))
        self.assertIn("The condition was duplicated", warnings[0][2])
        self.assertIn("could not be refreshed", warnings[0][2])

    def test_condition_folder_delete_handler_uses_shared_validation(self):
        access = _permissions__FakeAccess({Feature.EDIT_CONDITION_STRUCTURE})
        validate_calls = []
        delete_calls = []

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return False

            def validate_condition_folder_delete(self, file_path, bid_uid, folder_uids):
                validate_calls.append((file_path, bid_uid, list(folder_uids)))
                return DeleteValidationResult(
                    requested_uids=list(folder_uids),
                    blocked_uids=["folder-1"],
                    failure_reason="condition_folder_in_use",
                )

            def delete_condition_folders_result(self, db_path, bid_uid, folder_uids):
                delete_calls.append((db_path, bid_uid, folder_uids))
                raise AssertionError("blocked folder delete should not run")

        coordinator = SimpleNamespace(
            ui_access_manager=access,
            conditions_sidebar=SimpleNamespace(window=lambda: None),
            flush_deferred_for_file=lambda _file_path: True,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid_condition_folders=lambda: {
                    "folder-1": SimpleNamespace(name="Folder 1")
                }
            ),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1")
            ),
            workspace_state_model=make_workspace_state_model(),
        )
        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "confirm_multi_delete",
            return_value=None,
        ) as confirm_delete:
            handler.on_folder_delete_requested(["folder-1"])
        self.assertEqual(validate_calls, [("db.mdb", "bid-1", ["folder-1"])])
        self.assertEqual(delete_calls, [])
        self.assertEqual(confirm_delete.call_args.args[1], "Delete Folder")
        self.assertEqual(confirm_delete.call_args.args[2], [("Folder 1", "folder-1")])
        self.assertEqual(confirm_delete.call_args.args[3], {"folder-1"})

    def test_condition_dialog_layer_insert_warns_when_refresh_fails(self):
        warnings = []
        bid_ref = BidRef("db.mdb", "bid-1")
        coordinator = SimpleNamespace(
            conditions_sidebar=None,
            flush_deferred_for_file=lambda _file_path: True,
        )
        write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False,
            insert_layer_result=lambda _file_path, _bid_uid, _name, _sequence: (
                WriteReloadResult("layer-new", write_success=True, reload_success=False)
            ),
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=write_service,
            project_read_service=None,
            project_data=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(),
            workspace_state_model=make_workspace_state_model(),
        )
        from ost_visualizer.presentation.handlers import condition_action_handler

        old_warning = condition_action_handler.show_warning
        condition_action_handler.show_warning = lambda *args: warnings.append(args)
        try:
            callbacks = handler._layer_dialog_callbacks(bid_ref, write_service)
            uid = callbacks["layer_insert_fn"]("Layer", 3)
        finally:
            condition_action_handler.show_warning = old_warning
        self.assertEqual(uid, "layer-new")
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0][:2], (None, "Refresh Error"))
        self.assertIn(
            "created, but the layer list could not be refreshed", warnings[0][2]
        )

    def test_condition_dialog_condition_type_save_warns_when_refresh_fails(self):
        warnings = []
        bid_ref = BidRef("db.mdb", "bid-1")
        coordinator = SimpleNamespace(
            conditions_sidebar=None,
            flush_deferred_for_file=lambda _file_path: True,
        )
        write_service = SimpleNamespace(
            save_condition_types_result=lambda _file_path, _changes: (
                WriteReloadResult(
                    {"new_condition_type": "type-new"},
                    write_success=True,
                    reload_success=False,
                )
            )
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=write_service,
            project_read_service=None,
            project_data=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(),
            workspace_state_model=make_workspace_state_model(),
        )
        from ost_visualizer.presentation.handlers import condition_action_handler

        old_warning = condition_action_handler.show_warning
        condition_action_handler.show_warning = lambda *args: warnings.append(args)
        try:
            result = handler._save_condition_types_from_dialog(
                bid_ref,
                write_service,
                {"new": [{"uid": "new_condition_type", "name": "Concrete"}]},
            )
        finally:
            condition_action_handler.show_warning = old_warning
        self.assertEqual(result, {"new_condition_type": "type-new"})
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0][:2], (None, "Refresh Error"))
        self.assertIn("condition type changes were saved", warnings[0][2])
        self.assertIn("could not be refreshed", warnings[0][2])


class ConditionFolderLockedBidHandlerParityTests(unittest.TestCase):
    """Decisions F2 and G3: on a status-locked active Bid the write service refuses every
    Condition command (Access: a failed result, SQL: ActiveBidLockedError at
    submission). The handler reacts the same way on both backends: it logs, shows no
    queued-mutation error, and leaves the sidebar and the pending-operation registry
    untouched (a folder or Condition rename also refreshes the sidebar so the edited
    text is reverted). The one presentation difference that remains is Renumber, whose
    Access failure also opens a warning dialog; the SQL block only logs."""

    OPERATIONS = ("create folder", "rename folder", "delete folders", "move", "cut")
    CONDITION_OPERATIONS = (
        "delete conditions",
        "duplicate conditions",
        "paste-duplicate conditions",
        "rename condition",
        "change condition layer",
        "change condition type",
        "renumber conditions",
    )

    def _handler(self, *, sql):
        record = SimpleNamespace(
            writes=[],
            warnings=[],
            errors=[],
            refreshes=[],
            pending_edits=[],
            completed_cuts=[],
            highlights=[],
        )
        bid_ref = BidRef("database", "7")
        owner = object()
        folder = BidConditionFolder(uid="f1", name="Folder")
        conditions = {"c1": object(), "c2": object()}

        def blocked(name):
            def queue(*args, **_kwargs):
                record.writes.append((name, args[:-1]))
                raise ActiveBidLockedError()

            return queue

        def failed(name, result):
            def write(*args, **_kwargs):
                record.writes.append((name, args))
                return result

            return write

        class WriteService:
            uses = staticmethod(lambda _database_id: sql)
            uses_sql_collaboration_mutations = uses
            validate_condition_folder_delete = staticmethod(
                lambda _database_id, _bid_uid, folder_uids: SimpleNamespace(
                    blocked_uids=[]
                )
            )
            if sql:
                queue_condition_folder_create = staticmethod(blocked("create"))
                queue_condition_folder_rename = staticmethod(blocked("rename"))
                queue_condition_folders_delete = staticmethod(blocked("delete"))
                queue_conditions_update = staticmethod(blocked("update"))
                queue_conditions_delete = staticmethod(blocked("delete conditions"))
                queue_conditions_duplicate = staticmethod(blocked("duplicate"))
                queue_conditions_renumber = staticmethod(blocked("renumber"))
            else:
                create_condition_folder_result = staticmethod(
                    failed("create", WriteReloadResult(None, False, False))
                )
                rename_condition_folder = staticmethod(failed("rename", False))
                delete_condition_folders_result = staticmethod(
                    failed("delete", WriteReloadResult(None, False, False))
                )
                update_condition = staticmethod(
                    failed(
                        "update",
                        UpdateConditionResultDto(
                            success=False, error="The active bid is locked"
                        ),
                    )
                )
                delete_conditions = staticmethod(failed("delete conditions", False))
                duplicate_conditions_result = staticmethod(
                    failed("duplicate", WriteReloadResult([], False, False))
                )
                renumber_conditions = staticmethod(failed("renumber", False))

        sidebar = SimpleNamespace(
            set_pending_folder_edit=record.pending_edits.append,
            set_pending_condition_selection=record.pending_edits.append,
            complete_cut_paste=lambda *args: record.completed_cuts.append(args),
            get_condition_name=lambda uid: f"Name {uid}",
            condition_selection_after_delete=lambda _uids: "c2",
            collect_ordered_condition_uids=lambda: ["c2", "c1"],
            window=lambda: "window",
        )
        coordinator = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            conditions_sidebar=sidebar,
            flush_deferred_for_file=lambda _file_path: True,
            present_queued_mutation_error=lambda *args, **_kwargs: record.errors.append(
                args
            ),
            refresh_conditions_ui=lambda: record.refreshes.append(True),
            highlight_sidebar=lambda *args, **_kwargs: record.highlights.append(args),
            placement=SimpleNamespace(force_exit=lambda: None),
            ensure_select_mode=lambda: None,
            _is_takeoff_2d_view_active=lambda: False,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid=lambda _ref: owner,
                get_bid_condition_folders=lambda: {"f1": folder},
                get_bid_conditions=lambda: conditions,
            ),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            workspace_state_model=make_workspace_state_model(),
        )
        return handler, record

    def _run(self, handler, operation):
        patched = "ost_visualizer.presentation.handlers.condition_action_handler"
        with patch(f"{patched}.show_warning") as warning, patch(
            f"{patched}.confirm_multi_delete", return_value=[("Folder", "f1")]
        ), patch(f"{patched}.confirm_delete_conditions", return_value=["c1"]), patch(
            f"{patched}.confirm", return_value=True
        ), patch(
            f"{patched}.QSignalBlocker"
        ):
            if operation == "delete conditions":
                handler.on_delete_requested(["c1"])
            elif operation == "duplicate conditions":
                handler.on_duplicate_requested(["c1"])
            elif operation == "paste-duplicate conditions":
                handler.on_paste_requested(
                    ["c1"], {"kind": "folder", "folder_uid": "f1", "cut": False}
                )
            elif operation == "rename condition":
                handler.on_condition_renamed("c1", "N")
            elif operation == "change condition layer":
                handler.on_condition_layer_change_requested(["c1"], "40")
            elif operation == "change condition type":
                handler.on_condition_type_change_requested(["c1"], "3")
            elif operation == "renumber conditions":
                handler.on_renumber_requested()
            elif operation == "create folder":
                handler.on_create_folder_requested("")
            elif operation == "rename folder":
                handler.on_folder_renamed("f1", "N")
            elif operation == "delete folders":
                handler.on_folder_delete_requested(["f1"])
            elif operation == "move":
                handler.on_move_condition_to_folder("c1", "f1")
            else:
                handler.on_paste_requested(
                    ["c1"],
                    {
                        "kind": "folder",
                        "folder_uid": "f1",
                        "cut": True,
                        "clipboard_revision": 3,
                    },
                )
        return warning

    def test_locked_bid_block_is_silent_and_identical_on_both_backends(self):
        for operation in self.OPERATIONS:
            for sql in (False, True):
                with self.subTest(operation=operation, sql=sql):
                    handler, record = self._handler(sql=sql)
                    with self.assertLogs(
                        "ost_visualizer.presentation.handlers.condition_action_handler",
                        level="WARNING",
                    ) as logs:
                        warning = self._run(handler, operation)
                    # The write service was reached exactly once (the gate is there).
                    self.assertEqual(len(record.writes), 1)
                    self.assertEqual(len(logs.records), 1)
                    warning.assert_not_called()
                    self.assertEqual(record.errors, [])
                    self.assertEqual(record.pending_edits, [])
                    self.assertEqual(record.completed_cuts, [])
                    self.assertEqual(record.highlights, [])
                    self.assertEqual(handler._pending_sql_operations, set())
                    self.assertEqual(
                        record.refreshes,
                        [True] if operation == "rename folder" else [],
                    )

    def test_condition_command_block_is_identical_on_both_backends(self):
        logged = "ost_visualizer.presentation.handlers.condition_action_handler.logger"
        for operation in self.CONDITION_OPERATIONS:
            for sql in (False, True):
                with self.subTest(operation=operation, sql=sql):
                    handler, record = self._handler(sql=sql)
                    with patch(f"{logged}.warning") as log:
                        warning = self._run(handler, operation)
                    # The write service was reached exactly once (the gate is there).
                    self.assertEqual(len(record.writes), 1)
                    # Access Renumber is the one reaction that differs: it opens a
                    # warning dialog (UI-unreachable on a locked Bid, the Renumber
                    # command is lock-blocked there); everything else only logs.
                    access_renumber = operation == "renumber conditions" and not sql
                    self.assertEqual(log.call_count, 0 if access_renumber else 1)
                    self.assertEqual(warning.call_count, 1 if access_renumber else 0)
                    self.assertEqual(record.errors, [])
                    self.assertEqual(record.completed_cuts, [])
                    self.assertEqual(handler._pending_sql_operations, set())
                    rename = operation == "rename condition"
                    self.assertEqual(record.refreshes, [True] if rename else [])
                    self.assertEqual(record.highlights, [({"c1"},)] if rename else [])

    def test_blocked_sql_operation_can_be_retried_after_the_bid_is_unlocked(self):
        for operation in ("create folder", *self.CONDITION_OPERATIONS):
            with self.subTest(operation=operation):
                handler, record = self._handler(sql=True)
                for _attempt in range(2):
                    with self.assertLogs(
                        "ost_visualizer.presentation.handlers.condition_action_handler",
                        level="WARNING",
                    ):
                        self._run(handler, operation)
                # The pending key was released by the first block, so the second
                # attempt reached the service again instead of being dropped as a
                # duplicate.
                self.assertEqual(len(record.writes), 2)

    def test_lock_block_is_distinct_from_other_queue_rejections(self):
        handler, _record = self._handler(sql=True)
        bid_ref = BidRef("database", "7")
        blocked = []

        def locked(_callback):
            raise ActiveBidLockedError()

        def rejected(_callback):
            raise RuntimeError("The SQL mutation queue is full.")

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "show_warning"
        ) as warning, self.assertLogs(
            "ost_visualizer.presentation.handlers.condition_action_handler",
            level="WARNING",
        ):
            self.assertFalse(
                handler._submit_sql_condition_operation(
                    bid_ref,
                    ("a",),
                    "Locked",
                    locked,
                    on_blocked=lambda: blocked.append(True),
                )
            )
            warning.assert_not_called()
            self.assertEqual(blocked, [True])
            self.assertFalse(
                handler._submit_sql_condition_operation(
                    bid_ref,
                    ("b",),
                    "Rejected",
                    rejected,
                    on_blocked=lambda: blocked.append(True),
                )
            )
        warning.assert_called_once_with(
            "window", "Rejected", "The SQL mutation queue is full."
        )
        self.assertEqual(blocked, [True])
        self.assertEqual(handler._pending_sql_operations, set())


class ConditionActionHandlerSameKeyResubmitTests(unittest.TestCase):
    """The key-based pending marker survives a late terminal delivery of an earlier
    operation with the identical key (the D7p stale-delivery shape)."""

    def test_late_terminal_of_operation_a_does_not_clear_the_marker_of_operation_b(
        self,
    ):
        errors = []
        events = []
        callbacks_a, callbacks_b = [], []
        handler = ConditionActionHandler(
            coordinator=SimpleNamespace(
                present_queued_mutation_error=lambda *args: errors.append(args),
            ),
            project_write_service=SimpleNamespace(),
            project_read_service=None,
            project_data=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: None),
            workspace_state_model=make_workspace_state_model(),
        )
        bid_ref = BidRef("database", "7")
        key = ("database", "7", "rename_condition", "c1")

        def submit(callbacks, label):
            return handler._submit_sql_condition_operation(
                bid_ref,
                ("rename_condition", "c1"),
                "Rename Condition",
                callbacks.append,
                lambda _result: events.append((label, "committed")),
                lambda _result: events.append((label, "failed")),
            )

        def result(status, operation_id):
            return QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id=operation_id,
                outcome_status=status,
                commit_attempted=False,
            )

        self.assertTrue(submit(callbacks_a, "A"))
        # While A is pending (also across interim results) the same key is refused.
        callbacks_a[0](
            result(
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                "00000000-0000-0000-0000-00000000000a",
            )
        )
        self.assertFalse(submit([], "refused"))
        rejected_a = result(
            MutationOutcomeStatus.REJECTED, "00000000-0000-0000-0000-00000000000a"
        )
        callbacks_a[0](rejected_a)
        self.assertEqual(events, [("A", "failed")])
        self.assertTrue(submit(callbacks_b, "B"))
        # A's terminal result is delivered again after B started with the same key.
        callbacks_a[0](rejected_a)
        self.assertEqual(handler._pending_sql_operations, {key})
        self.assertEqual(events, [("A", "failed")])
        self.assertEqual(len(errors), 1)
        self.assertFalse(submit([], "refused"))
        callbacks_b[0](
            result(
                MutationOutcomeStatus.COMMITTED, "00000000-0000-0000-0000-00000000000b"
            )
        )
        self.assertEqual(events, [("A", "failed"), ("B", "committed")])
        self.assertEqual(handler._pending_sql_operations, set())


class ConditionActionHandlerCommittedCallbackFailureTests(
    _coordinator_tests._SecondPassBase
):
    """Decision G4: an exception raised by on_committed is not swallowed by the handler
    and is not lost: it propagates to the SQL coordinator (real object here, fake
    store/dispatcher), which logs it with its traceback at ERROR and keeps the
    committed operation for recovery; the recovery re-delivery of COMMITTED must not
    run on_committed a second time."""

    def _handler(self, errors):
        return ConditionActionHandler(
            coordinator=SimpleNamespace(
                present_queued_mutation_error=lambda *args: errors.append(args),
            ),
            project_write_service=SimpleNamespace(),
            project_read_service=None,
            project_data=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: None),
            workspace_state_model=make_workspace_state_model(),
        )

    def _submit(self, handler, database_id, on_committed):
        callbacks = []
        self.assertTrue(
            handler._submit_sql_condition_operation(
                BidRef(database_id, "7"),
                ("rename_condition", "c1"),
                "Rename Condition",
                callbacks.append,
                on_committed,
            )
        )
        return callbacks[0], (database_id, "7", "rename_condition", "c1")

    def test_failing_on_committed_propagates_and_the_redelivery_does_not_rerun_it(
        self,
    ):
        errors, calls = [], []

        def on_committed(result):
            calls.append(result.operation_id)
            raise RuntimeError("on_committed failed")

        handler = self._handler(errors)
        complete, key = self._submit(handler, "database", on_committed)
        committed = QueuedMutationResult(
            database_id="database",
            runtime_generation=1,
            operation_id="00000000-0000-0000-0000-0000000000c1",
            outcome_status=MutationOutcomeStatus.COMMITTED,
            commit_attempted=True,
        )
        with self.assertRaisesRegex(RuntimeError, "on_committed failed"):
            complete(committed)
        self.assertEqual(calls, [committed.operation_id])
        self.assertNotIn(key, handler._pending_sql_operations)
        self.assertEqual(errors, [])
        complete(committed)
        self.assertEqual(calls, [committed.operation_id])
        self.assertEqual(errors, [])

    def test_the_real_coordinator_logs_a_failing_on_committed_with_its_traceback(self):
        coordinator, runtime = self.ready_coordinator()
        request = _coordinator_tests._placement_request(
            runtime.database_id, "condition-handler-on-committed"
        )
        coordinator._pending_mutations.begin(
            request, runtime_generation=runtime.generation
        )
        errors, calls = [], []

        def on_committed(result):
            calls.append(result.operation_id)
            raise RuntimeError("on_committed failed")

        handler = self._handler(errors)  # the callback holds only a weak reference
        complete, _key = self._submit(handler, runtime.database_id, on_committed)
        committed = QueuedMutationResult(
            database_id=runtime.database_id,
            runtime_generation=runtime.generation,
            operation_id=request.operation_id,
            outcome_status=MutationOutcomeStatus.COMMITTED,
            commit_attempted=True,
        )
        with self.assertLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ) as logged:
            coordinator._complete_mutation_request((complete, committed))
        (record,) = logged.records
        self.assertEqual(
            record.getMessage(), "SQL queued-mutation completion callback failed"
        )
        self.assertEqual(record.levelname, "ERROR")
        self.assertIsInstance(record.exc_info[1], RuntimeError)
        self.assertEqual(str(record.exc_info[1]), "on_committed failed")
        self.assertEqual(calls, [request.operation_id])
        stored_request, stored_callback = coordinator._uncertain_callbacks[
            request.operation_id
        ]
        self.assertEqual(stored_request, request)
        with self.assertNoLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ):
            coordinator._complete_mutation_request((stored_callback, committed))
        self.assertEqual(calls, [request.operation_id])
        self.assertEqual(errors, [])


class LayerLockedBidHandlerParityTests(unittest.TestCase):
    """Decisions H2 and H3: on a status-locked active Bid the write service refuses the
    Layer dialog commands (Access: a failed result, SQL: ActiveBidLockedError at
    submission). The handler turns the SQL refusal into a SILENT 'not started' (log
    only, no dialog, pending key released) so the real Layers dialog restores its
    optimistic edit exactly like its failed-result path and stays usable for a retry.
    The accepted presentation difference (lock-arrives-while-open race only): the
    Access failure also opens the dialog's own failure warning, the SQL refusal does not.
    """

    HANDLER_LOGGER = "ost_visualizer.presentation.handlers.condition_action_handler"
    DIALOG = "ost_visualizer.presentation.dialogs.layers_dialog"
    OPERATIONS = ("insert", "delete", "rename", "move")

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        self.app.processEvents()

    def _handler(self, *, sql):
        record = SimpleNamespace(writes=[], errors=[])

        def blocked(name):
            def queue(*args, **_kwargs):
                record.writes.append(name)
                raise ActiveBidLockedError()

            return queue

        def failed(name, result):
            def write(*_args, **_kwargs):
                record.writes.append(name)
                return result

            return write

        class WriteService:
            uses = staticmethod(lambda _database_id: sql)
            uses_sql_collaboration_mutations = uses
            if sql:
                queue_layer_insert = staticmethod(blocked("insert"))
                queue_layers_delete = staticmethod(blocked("delete"))
                queue_layer_rename = staticmethod(blocked("rename"))
                queue_layer_reorder = staticmethod(blocked("move"))
            else:
                insert_layer_result = staticmethod(
                    failed("insert", WriteReloadResult(None, False, False))
                )
                delete_layers = staticmethod(
                    failed(
                        "delete",
                        BatchWriteResult(requested_uids=["40"], failed_uids=["40"]),
                    )
                )
                update_layer_name = staticmethod(failed("rename", False))
                swap_layer_sequence = staticmethod(failed("move", False))

        bid_ref = BidRef("database", "7")
        layers = [
            BidLayer(uid="40", bid_uid="7", name="Roads", sequence=1, show=True),
            BidLayer(uid="41", bid_uid="7", name="Walls", sequence=2, show=True),
        ]
        handler = ConditionActionHandler(
            coordinator=SimpleNamespace(
                present_queued_mutation_error=lambda *args, **_kwargs: (
                    record.errors.append(args)
                ),
                conditions_sidebar=SimpleNamespace(window=lambda: "window"),
            ),
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid_layer_snapshot=lambda: layers,
                get_layer_uids_in_use=lambda: set(),
            ),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            workspace_state_model=make_workspace_state_model(),
        )
        callbacks = handler._layer_dialog_callbacks(bid_ref, handler._write_service)
        return handler, record, callbacks, layers

    def test_sql_queue_callbacks_report_a_locked_bid_as_not_started_and_silent(self):
        calls = {
            "insert": lambda cb, done: cb["layer_insert_async_fn"]("Streets", 1, done),
            "delete": lambda cb, done: cb["layer_delete_many_async_fn"](["40"], done),
            "rename": lambda cb, done: cb["layer_update_name_async_fn"](
                "40", "Streets", done
            ),
            "move": lambda cb, done: cb["layer_move_async_fn"]("40", "41", done),
        }
        for operation in self.OPERATIONS:
            with self.subTest(operation=operation):
                handler, record, callbacks, _layers = self._handler(sql=True)
                completed = []
                with patch(
                    f"{self.HANDLER_LOGGER}.show_warning"
                ) as warning, self.assertLogs(
                    self.HANDLER_LOGGER, level="WARNING"
                ) as logs:
                    started = calls[operation](
                        callbacks, lambda *args: completed.append(args)
                    )
                self.assertIs(started, False)
                self.assertEqual(record.writes, [operation])
                self.assertEqual(completed, [])
                self.assertEqual(len(logs.records), 1)
                warning.assert_not_called()
                self.assertEqual(record.errors, [])
                self.assertEqual(handler._pending_sql_operations, set())

    def _dialog(self, callbacks, layers, *, sql):
        keys = (
            {
                "insert_async_fn": "layer_insert_async_fn",
                "delete_many_async_fn": "layer_delete_many_async_fn",
                "update_name_async_fn": "layer_update_name_async_fn",
                "move_async_fn": "layer_move_async_fn",
            }
            if sql
            else {
                "insert_fn": "layer_insert_fn",
                "delete_many_fn": "layer_delete_many_fn",
                "update_name_fn": "layer_update_name_fn",
                "move_fn": "layer_move_fn",
            }
        )
        return _master_data_support_MasterLayersDialog(
            _master_data_support_FakeIconProvider(),
            layers=list(layers),
            reload_fn=lambda: list(layers),
            **{argument: callbacks[key] for argument, key in keys.items()},
        )

    def _drive(self, dialog, operation):
        tree = dialog.tree
        if operation == "rename":
            tree.topLevelItem(0).setText(2, "Streets")
        elif operation == "insert":
            tree.setCurrentItem(tree.topLevelItem(0))
            dialog._on_new()
            item = tree.currentItem()
            tree.blockSignals(True)
            item.setText(2, "Streets")
            tree.blockSignals(False)
            dialog._on_item_changed(item, 2)
        elif operation == "delete":
            tree.setCurrentItem(tree.topLevelItem(0))
            tree.topLevelItem(0).setSelected(True)
            with patch(
                f"{self.DIALOG}.confirm_multi_delete", return_value=[("Roads", "40")]
            ):
                dialog._on_delete()
        else:
            tree.setCurrentItem(tree.topLevelItem(0))
            tree.topLevelItem(0).setSelected(True)
            dialog._move_selected_down()

    @staticmethod
    def _names(dialog):
        return [
            dialog.tree.topLevelItem(row).text(2)
            for row in range(dialog.tree.topLevelItemCount())
        ]

    def test_layers_dialog_restores_state_and_stays_usable_after_a_locked_bid_refusal(
        self,
    ):
        for operation in self.OPERATIONS:
            for sql in (False, True):
                with self.subTest(operation=operation, sql=sql):
                    handler, record, callbacks, layers = self._handler(sql=sql)
                    dialog = self._dialog(callbacks, layers, sql=sql)
                    try:
                        for attempt in (1, 2):
                            with patch(
                                f"{self.DIALOG}.show_warning"
                            ) as dialog_warning, patch(
                                f"{self.HANDLER_LOGGER}.show_warning"
                            ) as handler_warning, patch(
                                f"{self.HANDLER_LOGGER}.logger.warning"
                            ) as log:
                                self._drive(dialog, operation)
                            # Optimistic edit reverted; nothing left pending.
                            self.assertEqual(self._names(dialog), ["Roads", "Walls"])
                            self.assertIsNone(dialog._pending_new_item)
                            self.assertFalse(dialog._operation_pending)
                            self.assertTrue(dialog._is_interactive)
                            self.assertTrue(dialog.btn_new.isEnabled())
                            # The retry reached the service again (key released).
                            self.assertEqual(record.writes, [operation] * attempt)
                            self.assertEqual(record.errors, [])
                            self.assertEqual(handler._pending_sql_operations, set())
                            handler_warning.assert_not_called()
                            # Accepted difference: only the Access failure opens the
                            # dialog's own failure warning; the SQL block is silent.
                            self.assertEqual(
                                (dialog_warning.call_count, log.call_count),
                                (0, 1) if sql else (1, 0),
                            )
                    finally:
                        dialog.close()
                        dialog.cleanup()
                        dialog.deleteLater()


class ConditionHandlerBidLockedRejectionTests(unittest.TestCase):
    """Decision B4 at the Condition handler: a queued SQL Condition write that the SQL
    writer refused with REJECTED / bid_locked behaves like the queue-time refusal of
    ConditionFolderLockedBidHandlerParityTests: no dialog (the real
    UIEventCoordinator.present_queued_mutation_error stays silent for the reason), the
    pending-operation key is released once, and a folder or Condition rename reverts
    the sidebar's edited text exactly as the queue-time refusal does (refresh, then
    highlight for a Condition). A rejection WITHOUT the reason keeps its dialog and
    does not run the blocked-revert. Real handler and the real coordinator method; the
    write service and sidebar are fakes."""

    LOGGER = "ost_visualizer.presentation.handlers.condition_action_handler"
    COORDINATOR = "ost_visualizer.presentation.coordinators.ui_event_coordinator"

    def _handler(self):
        record = SimpleNamespace(
            callbacks=[], refreshes=[], highlights=[], prepared=[], writes=[]
        )
        bid_ref = BidRef("database", "7")
        owner = object()
        folder = BidConditionFolder(uid="f1", name="Folder")
        conditions = {"c1": object(), "c2": object()}

        def queued(name):
            def queue(*args, **_kwargs):
                record.writes.append(name)
                record.callbacks.append(args[-1])
                return 1

            return queue

        class WriteService:
            uses_sql_collaboration_mutations = staticmethod(lambda _database_id: True)
            validate_condition_folder_delete = staticmethod(
                lambda _database_id, _bid_uid, folder_uids: SimpleNamespace(
                    blocked_uids=[]
                )
            )
            queue_condition_folder_create = staticmethod(queued("create folder"))
            queue_condition_folder_rename = staticmethod(queued("rename folder"))
            queue_conditions_update = staticmethod(queued("update"))
            queue_conditions_duplicate = staticmethod(queued("duplicate"))

        sidebar = SimpleNamespace(
            set_pending_folder_edit=lambda _uid: None,
            set_pending_condition_selection=lambda _uid: None,
            get_condition_name=lambda uid: f"Name {uid}",
            window=lambda: "window",
        )
        presenter = UIEventCoordinator.__new__(UIEventCoordinator)
        presenter._is_cleaning_up = False
        presenter.main_window = "main-window"
        presenter._prepare_for_modal_mutation_error = record.prepared.append
        coordinator = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            conditions_sidebar=sidebar,
            flush_deferred_for_file=lambda _file_path: True,
            present_queued_mutation_error=presenter.present_queued_mutation_error,
            refresh_conditions_ui=lambda: record.refreshes.append(True),
            highlight_sidebar=lambda *args, **_kwargs: record.highlights.append(args),
            placement=SimpleNamespace(force_exit=lambda: None),
            ensure_select_mode=lambda: None,
            _is_takeoff_2d_view_active=lambda: False,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(
                get_bid=lambda _ref: owner,
                get_bid_condition_folders=lambda: {"f1": folder},
                get_bid_conditions=lambda: conditions,
            ),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            workspace_state_model=make_workspace_state_model(),
        )
        return handler, record

    @staticmethod
    def _rejection(bid_locked=True):
        return QueuedMutationResult(
            database_id="database",
            runtime_generation=2,
            operation_id="00000000-0000-4000-8000-0000000000aa",
            outcome_status=MutationOutcomeStatus.REJECTED,
            message="The active bid is locked" if bid_locked else "busy",
            rejection_reason=(
                MutationRejectionReason.BID_LOCKED if bid_locked else None
            ),
        )

    def _run(self, handler, operation):
        ConditionFolderLockedBidHandlerParityTests._run(self, handler, operation)

    def _deliver_twice(self, record, result=None):
        result = result or self._rejection()
        with patch(f"{self.COORDINATOR}.show_warning") as warning, patch(
            f"{self.COORDINATOR}.show_critical"
        ) as critical, patch(f"{self.LOGGER}.show_warning") as handler_warning:
            record.callbacks[0](result)
            record.callbacks[0](result)
        return warning, critical, handler_warning

    def test_a_rejected_folder_rename_reverts_the_sidebar_once_without_a_dialog(self):
        handler, record = self._handler()
        self._run(handler, "rename folder")
        self.assertEqual(record.writes, ["rename folder"])
        self.assertEqual(len(handler._pending_sql_operations), 1)
        warning, critical, handler_warning = self._deliver_twice(record)
        for dialog in (warning, critical, handler_warning):
            dialog.assert_not_called()
        self.assertEqual(record.refreshes, [True])
        self.assertEqual(record.highlights, [])
        self.assertEqual(record.prepared, [])
        self.assertEqual(handler._pending_sql_operations, set())
        # the surface stays usable: the key was released
        self._run(handler, "rename folder")
        self.assertEqual(record.writes, ["rename folder"] * 2)

    def test_a_rejected_condition_rename_reverts_text_and_highlight_once(self):
        handler, record = self._handler()
        self._run(handler, "rename condition")
        self.assertEqual(record.writes, ["update"])
        warning, critical, handler_warning = self._deliver_twice(record)
        for dialog in (warning, critical, handler_warning):
            dialog.assert_not_called()
        self.assertEqual(record.refreshes, [True])
        self.assertEqual(record.highlights, [({"c1"},)])
        self.assertEqual(handler._pending_sql_operations, set())

    def test_other_rejected_condition_commands_are_silent_and_free_their_key(self):
        for operation, written in (
            ("create folder", "create folder"),
            ("change condition layer", "update"),
            ("duplicate conditions", "duplicate"),
        ):
            with self.subTest(operation=operation):
                handler, record = self._handler()
                self._run(handler, operation)
                self.assertEqual(record.writes, [written])
                warning, critical, handler_warning = self._deliver_twice(record)
                for dialog in (warning, critical, handler_warning):
                    dialog.assert_not_called()
                self.assertEqual(record.prepared, [])
                self.assertEqual(handler._pending_sql_operations, set())

    def test_a_rejection_without_the_reason_keeps_its_dialog_and_skips_the_revert(self):
        handler, record = self._handler()
        self._run(handler, "rename folder")
        warning, critical, _handler_warning = self._deliver_twice(
            record, self._rejection(bid_locked=False)
        )
        warning.assert_called_once_with(
            "main-window", "Rename Condition Folder", "busy"
        )
        critical.assert_not_called()
        self.assertEqual(record.prepared, ["database"])
        self.assertEqual(record.refreshes, [])
        self.assertEqual(handler._pending_sql_operations, set())


import contextlib
import gc
import weakref
from unittest import mock
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationRejectionReason as _SecondPassRejectionReason,
)
from ost_visualizer.application.dtos.condition_takeoff_reassignment import (
    ConditionTakeoffReassignment,
)
from ost_visualizer.application.dtos.create_condition_result import (
    CreateConditionResult as _SecondPassCreateConditionResult,
)
from ost_visualizer.application.services.project_write_service import (
    DeleteValidationResult as _SecondPassDeleteValidationResult,
)
from ost_visualizer.presentation.utils.messagebox import (
    DB_LOCKED_HINT as _SECOND_PASS_DB_LOCKED_HINT,
)

_COND_MODULE = "ost_visualizer.presentation.handlers.condition_action_handler"


class _SecondPassConditionSidebar(QtCore.QObject):
    """A recording sidebar (a real QObject, because the handler blocks its signals)."""

    def __init__(self, harness):
        super().__init__()
        self.harness = harness

    def window(self):
        return "window"

    def get_condition_name(self, uid):
        return f"Name {uid}"

    def condition_selection_after_delete(self, uids):
        self.harness.events.append(("selection_after_delete", list(uids)))
        return self.harness.replacement

    def collect_ordered_condition_uids(self):
        return list(self.harness.ordered)

    def set_pending_folder_edit(self, uid):
        self.harness.events.append(("pending_folder_edit", uid))

    def set_pending_condition_selection(self, uid):
        self.harness.events.append(("pending_condition_selection", uid))

    def complete_cut_paste(self, uids, revision):
        self.harness.events.append(("complete_cut_paste", list(uids), revision))


class _SecondPassConditions:
    """A real ConditionActionHandler over strict recording fakes (no live SQL Server, no
    real queue, no real dialogs): every write-service call is recorded with its exact
    arguments, queued callbacks are kept for delivery, Access results are scripted per
    method and every coordinator side effect lands in one ordered event list."""

    DB = "database"
    BID = "7"

    def __init__(self, *, sql, allowed=None, license_ok=True, sidebar=True):
        self.sql = sql
        self.allowed = None if allowed is None else set(allowed)
        self.license_ok = license_ok
        self.events = []
        self.calls = []
        self.callbacks = []
        self.script = {}
        self.selected = BidRef(self.DB, self.BID)
        self.owner = SimpleNamespace(measure_base=0)
        self.conditions = {
            "c1": Condition(uid="c1", name="Condition 1", ref_no=1),
            "c2": Condition(uid="c2", name="Condition 2", ref_no=2),
        }
        self.folders = {"f1": BidConditionFolder(uid="f1", name="Folder 1")}
        self.ordered = ["c1", "c2"]
        self.replacement = "c2"
        self.flush_ok = True
        self.locked = False
        self.layers = [
            BidLayer(uid="40", bid_uid="7", name="Default", sequence=1, show=True),
            BidLayer(uid="41", bid_uid="7", name="Roads", sequence=2, show=False),
        ]
        self.takeoffs = []
        self.cdn_types = {"t1": SimpleNamespace(uid="t1")}
        self.plan_active = True
        self.placement_active = False
        self.requested = []
        self.ended = []
        harness = self

        class Access:
            def is_allowed(self, feature):
                harness.events.append(("allowed?", feature))
                return harness.allowed is None or feature in harness.allowed

            def has_license(self):
                return harness.license_ok

        class Placement:
            @property
            def is_active(self):
                return harness.placement_active

            def force_exit(self):
                harness.events.append(("placement_exit",))

            def enter(self, uid, uids):
                harness.events.append(("placement_enter", uid, list(uids)))

        class Coordinator:
            ui_access_manager = Access()
            placement = Placement()
            main_window = SimpleNamespace(icon_provider="icons")
            event_bus = EventBus()
            _is_cleaning_up = False

            def flush_deferred_for_file(self, file_path):
                harness.events.append(("flush", file_path))
                return harness.flush_ok

            def highlight_sidebar(self, uids, reveal=True):
                harness.events.append(("highlight", set(uids), reveal))

            def ensure_select_mode(self):
                harness.events.append(("ensure_select_mode",))

            def refresh_conditions_ui(self):
                harness.events.append(("refresh_conditions_ui",))

            def present_queued_mutation_error(self, file_path, title, result):
                harness.events.append(("present_error", file_path, title, result))

            def _is_takeoff_2d_view_active(self):
                return harness.plan_active

            def update_layer_visibility_deferred(self, uid, show):
                harness.events.append(("layer_visibility", uid, show))
                return "visibility-result"

            def update_all_layers_visibility_deferred(self, show):
                harness.events.append(("all_layers_visibility", show))
                return "all-visibility-result"

            def request_collaboration_edit(
                self,
                database_id,
                resources,
                callback,
                *,
                dependency_resources=(),
                operation_id="",
                owning_surface="desktop",
            ):
                handle = EditLeaseHandle(
                    database_id=database_id,
                    draft_id=f"draft-{len(harness.requested) + 1}",
                    runtime_generation=1,
                    operation_id=operation_id,
                    owning_surface=owning_surface,
                    resources=tuple(resources),
                    dependency_resources=tuple(dependency_resources),
                )
                harness.requested.append(handle)
                callback(EditLeaseResult(True, handle=handle))

            def end_collaboration_edit(self, handle):
                harness.ended.append(handle)

        coordinator = Coordinator()
        coordinator.conditions_sidebar = (
            _SecondPassConditionSidebar(self) if sidebar else None
        )
        self.coordinator = coordinator

        class Data:
            def get_bid(self, ref):
                harness.events.append(("get_bid", ref))
                return harness.owner

            def get_current_bid(self):
                return harness.owner

            def is_current_bid_locked(self):
                return harness.locked

            def get_bid_conditions(self):
                return harness.conditions

            def get_bid_condition_folders(self):
                return harness.folders

            def get_cdn_types(self):
                harness.events.append(("data_cdn_types",))
                return harness.cdn_types

            def get_bid_layer_snapshot(self):
                harness.events.append(("data_layers",))
                return harness.layers

            def get_layer_uids_in_use(self):
                harness.events.append(("data_layer_uids",))
                return {"40"}

            def get_all_takeoffs(self):
                return harness.takeoffs

        class Read:
            def get_cdn_types(self, file_path):
                harness.events.append(("read_cdn_types", file_path))
                return harness.cdn_types

            def get_merged_bid_layers(self, file_path, bid_uid):
                harness.events.append(("read_layers", file_path, bid_uid))
                return harness.layers

            def get_layer_uids_in_use(self, file_path, bid_uid):
                harness.events.append(("read_layer_uids", file_path, bid_uid))
                return {"41"}

        class Write:
            def uses_sql_collaboration_mutations(self, _file_path):
                return harness.sql

            def _queue(self, name, args, kwargs):
                harness.calls.append((name, args[:-1], kwargs))
                harness.callbacks.append(args[-1])
                scripted = harness.script.get(name)
                if isinstance(scripted, BaseException):
                    raise scripted
                return len(harness.callbacks)

            def _scripted(self, name, args, kwargs, default):
                harness.calls.append((name, args, kwargs))
                outcome = harness.script.get(name, default)
                if isinstance(outcome, list):
                    return outcome.pop(0) if len(outcome) > 1 else outcome[0]
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome

        for name in (
            "queue_condition_create",
            "queue_conditions_duplicate",
            "queue_conditions_update",
            "queue_conditions_delete",
            "queue_conditions_renumber",
            "queue_condition_folder_create",
            "queue_condition_folder_rename",
            "queue_condition_folders_delete",
            "queue_condition_types_save",
            "queue_layer_insert",
            "queue_layers_delete",
            "queue_layer_rename",
            "queue_layer_reorder",
        ):
            setattr(
                Write,
                name,
                (lambda name: lambda self, *a, **k: self._queue(name, a, k))(name),
            )
        for name, default in (
            ("create_condition_result", None),
            ("update_condition", SimpleNamespace(success=True, error="")),
            ("duplicate_conditions_result", None),
            ("delete_conditions", True),
            ("renumber_conditions", True),
            ("create_condition_folder_result", None),
            ("rename_condition_folder", True),
            ("delete_condition_folders_result", None),
            ("validate_condition_folder_delete", None),
            ("reload_conditions_and_notify", True),
            ("save_condition_types_result", None),
            ("validate_condition_types_delete", None),
            ("delete_condition_types_result", None),
            ("insert_layer_result", None),
            ("delete_layers", True),
            ("update_layer_name", True),
            ("swap_layer_sequence", True),
        ):
            setattr(
                Write,
                name,
                (
                    lambda name, default: lambda self, *a, **k: self._scripted(
                        name, a, k, default
                    )
                )(name, default),
            )
        self.write = Write()
        self.data = Data()
        self.read = Read()
        self.ui = SimpleNamespace(
            get_selected_bid_ref=lambda: harness.selected,
            active_page_uid="page-1",
            highlighted_condition_uids=set(),
        )
        self.handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=self.write,
            project_read_service=self.read,
            project_data=self.data,
            ui_state_manager=self.ui,
            workspace_state_model=make_workspace_state_model(),
        )

    def call(self, name):
        return [(args, kwargs) for n, args, kwargs in self.calls if n == name]

    def names(self):
        return [name for name, _args, _kwargs in self.calls]

    def event_names(self):
        return [event[0] for event in self.events]

    def clear(self):
        self.events.clear()
        self.calls.clear()
        self.callbacks.clear()

    @staticmethod
    def result(status=MutationOutcomeStatus.COMMITTED, **fields):
        return QueuedMutationResult(
            database_id=_SecondPassConditions.DB,
            runtime_generation=1,
            operation_id="00000000-0000-4000-8000-0000000000f1",
            outcome_status=status,
            **fields,
        )

    def patched(self):
        stack = contextlib.ExitStack()
        self.warning = stack.enter_context(patch(f"{_COND_MODULE}.show_warning"))
        self.confirm = stack.enter_context(
            patch(f"{_COND_MODULE}.confirm", return_value=True)
        )
        self.confirm_delete = stack.enter_context(
            patch(
                f"{_COND_MODULE}.confirm_delete_conditions",
                side_effect=lambda _parent, names: [uid for uid, _name in names],
            )
        )
        self.confirm_multi = stack.enter_context(
            patch(
                f"{_COND_MODULE}.confirm_multi_delete",
                side_effect=lambda _parent, _title, items, _blocked: [
                    item for item in items
                ],
            )
        )
        return stack


class ConditionActionHandlerSecondPassSubmitTests(unittest.TestCase):
    """_submit_sql_condition_operation: the pending key and every terminal path."""

    def test_a_committed_terminal_runs_only_the_committed_callback_and_frees_the_key(
        self,
    ):
        harness = _SecondPassConditions(sql=True)
        committed, failed, blocked = [], [], []
        callbacks = []
        self.assertTrue(
            harness.handler._submit_sql_condition_operation(
                harness.selected,
                ("op", 5),
                "Title",
                callbacks.append,
                committed.append,
                failed.append,
                lambda: blocked.append(True),
            )
        )
        self.assertEqual(
            harness.handler._pending_sql_operations, {("database", "7", "op", "5")}
        )
        done = harness.result()
        callbacks[0](done)
        self.assertEqual((committed, failed, blocked), ([done], [], []))
        self.assertEqual(harness.handler._pending_sql_operations, set())
        self.assertNotIn("present_error", harness.event_names())

    def test_a_committed_terminal_without_callbacks_just_frees_the_key(self):
        harness = _SecondPassConditions(sql=True)
        callbacks = []
        harness.handler._submit_sql_condition_operation(
            harness.selected, ("op",), "Title", callbacks.append
        )
        callbacks[0](harness.result())
        self.assertEqual(harness.handler._pending_sql_operations, set())

    def test_a_failed_terminal_presents_then_fails_and_only_a_lock_adds_the_revert(
        self,
    ):
        for reason, expects_blocked in (
            (None, False),
            (_SecondPassRejectionReason.BID_LOCKED, True),
        ):
            with self.subTest(reason=reason):
                harness = _SecondPassConditions(sql=True)
                order = []
                callbacks = []
                harness.handler._submit_sql_condition_operation(
                    harness.selected,
                    ("op",),
                    "Title",
                    callbacks.append,
                    lambda _result: order.append("committed"),
                    lambda result: order.append(("failed", result.message)),
                    lambda: order.append("blocked"),
                )
                rejected = harness.result(
                    MutationOutcomeStatus.REJECTED,
                    message="refused",
                    rejection_reason=reason,
                )
                callbacks[0](rejected)
                self.assertEqual(
                    [event for event in harness.events if event[0] == "present_error"],
                    [("present_error", "database", "Title", rejected)],
                )
                self.assertEqual(
                    order,
                    [("failed", "refused")] + (["blocked"] if expects_blocked else []),
                )
                self.assertEqual(harness.handler._pending_sql_operations, set())

    def test_a_locked_rejection_without_a_blocked_callback_still_fails_cleanly(self):
        harness = _SecondPassConditions(sql=True)
        failed = []
        callbacks = []
        harness.handler._submit_sql_condition_operation(
            harness.selected, ("op",), "Title", callbacks.append, None, failed.append
        )
        callbacks[0](
            harness.result(
                MutationOutcomeStatus.REJECTED,
                rejection_reason=_SecondPassRejectionReason.BID_LOCKED,
            )
        )
        self.assertEqual(len(failed), 1)

    def test_interim_statuses_are_ignored_until_a_terminal_result_arrives(self):
        harness = _SecondPassConditions(sql=True)
        committed, failed = [], []
        callbacks = []
        harness.handler._submit_sql_condition_operation(
            harness.selected,
            ("op",),
            "Title",
            callbacks.append,
            committed.append,
            failed.append,
        )
        for status in (
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        ):
            callbacks[0](harness.result(status))
        self.assertEqual((committed, failed), ([], []))
        self.assertEqual(len(harness.handler._pending_sql_operations), 1)
        callbacks[0](harness.result())
        callbacks[0](harness.result(MutationOutcomeStatus.CONFLICT))
        self.assertEqual((len(committed), failed), (1, []))

    def test_a_collected_handler_ignores_a_late_terminal_result(self):
        callbacks, committed = [], []

        def build():
            harness = _SecondPassConditions(sql=True)
            harness.handler._submit_sql_condition_operation(
                harness.selected,
                ("op",),
                "Title",
                callbacks.append,
                committed.append,
            )
            return weakref.ref(harness.handler)

        handler_ref = build()
        gc.collect()
        self.assertIsNone(handler_ref())
        callbacks[0](_SecondPassConditions.result())
        self.assertEqual(committed, [])

    def test_a_locked_submission_runs_the_blocked_callback_but_not_the_failure_one(
        self,
    ):
        harness = _SecondPassConditions(sql=True)
        failed, blocked = [], []

        def refuse(_callback):
            raise ActiveBidLockedError()

        with harness.patched(), self.assertLogs(_COND_MODULE, "WARNING") as logged:
            started = harness.handler._submit_sql_condition_operation(
                harness.selected,
                ("op",),
                "Title",
                refuse,
                None,
                failed.append,
                lambda: blocked.append(True),
            )
        self.assertIs(started, False)
        self.assertEqual((failed, blocked), ([], [True]))
        self.assertEqual(
            logged.output,
            [f"WARNING:{_COND_MODULE}:Title blocked: the active bid is locked"],
        )
        harness.warning.assert_not_called()
        self.assertEqual(harness.handler._pending_sql_operations, set())

    def test_a_locked_submission_without_a_blocked_callback_is_still_silent(self):
        harness = _SecondPassConditions(sql=True)

        def refuse(_callback):
            raise ActiveBidLockedError()

        with harness.patched(), self.assertLogs(_COND_MODULE, "WARNING"):
            self.assertIs(
                harness.handler._submit_sql_condition_operation(
                    harness.selected, ("op",), "Title", refuse
                ),
                False,
            )
        harness.warning.assert_not_called()

    def test_other_refused_submissions_warn_once_with_the_sidebar_window(self):
        for error in (RuntimeError("queue closed"), ValueError("bad value")):
            with self.subTest(error=type(error).__name__):
                harness = _SecondPassConditions(sql=True)
                failed, blocked = [], []

                def refuse(_callback, error=error):
                    raise error

                with harness.patched():
                    started = harness.handler._submit_sql_condition_operation(
                        harness.selected,
                        ("op",),
                        "Title",
                        refuse,
                        None,
                        failed.append,
                        lambda: blocked.append(True),
                    )
                self.assertIs(started, False)
                self.assertEqual((failed, blocked), ([], []))
                harness.warning.assert_called_once_with("window", "Title", str(error))
                self.assertEqual(harness.handler._pending_sql_operations, set())

    def test_a_bid_with_no_pending_key_collision_is_scoped_by_database_and_bid(self):
        harness = _SecondPassConditions(sql=True)
        callbacks = []
        for ref in (
            BidRef("database", "7"),
            BidRef("database", "8"),
            BidRef("other", "7"),
        ):
            self.assertTrue(
                harness.handler._submit_sql_condition_operation(
                    ref, ("op",), "T", callbacks.append
                )
            )
        self.assertEqual(len(harness.handler._pending_sql_operations), 3)
        self.assertIs(
            harness.handler._submit_sql_condition_operation(
                BidRef("database", "7"), ("op",), "T", self.fail
            ),
            False,
        )


class ConditionActionHandlerSecondPassLayerAndTypeCallbackTests(unittest.TestCase):
    """The callbacks the handler hands to the condition dialog for Layers and Condition
    Types: which service answers on Access and on SQL, the exact queue arguments, the
    pending key and the value handed back on commit."""

    def _callbacks(self, harness):
        return harness.handler._layer_dialog_callbacks(harness.selected, harness.write)

    def test_access_callbacks_route_to_the_read_and_write_services(self):
        harness = _SecondPassConditions(sql=False)
        callbacks = self._callbacks(harness)
        self.assertEqual(
            set(callbacks),
            {
                "layer_reload_fn",
                "layer_used_uids_fn",
                "layer_insert_fn",
                "layer_delete_many_fn",
                "layer_update_show_fn",
                "layer_update_all_show_fn",
                "layer_update_name_fn",
                "layer_move_fn",
            },
        )
        self.assertIs(callbacks["layer_reload_fn"](), harness.layers)
        self.assertEqual(callbacks["layer_used_uids_fn"](), {"41"})
        self.assertEqual(
            harness.events,
            [("read_layers", "database", "7"), ("read_layer_uids", "database", "7")],
        )
        self.assertIs(callbacks["layer_delete_many_fn"](["40", "41"]), True)
        self.assertIs(callbacks["layer_update_name_fn"]("40", "Streets"), True)
        self.assertIs(callbacks["layer_move_fn"]("40", "41"), True)
        self.assertEqual(
            harness.calls,
            [
                ("delete_layers", ("database", ["40", "41"]), {}),
                ("update_layer_name", ("database", "40", "Streets"), {}),
                ("swap_layer_sequence", ("database", "40", "41"), {}),
            ],
        )
        harness.events.clear()
        self.assertEqual(
            callbacks["layer_update_show_fn"]("40", False), "visibility-result"
        )
        self.assertEqual(
            callbacks["layer_update_all_show_fn"](True), "all-visibility-result"
        )
        self.assertEqual(
            harness.events,
            [("layer_visibility", "40", False), ("all_layers_visibility", True)],
        )

    def test_sql_callbacks_answer_from_the_hydrated_snapshots(self):
        harness = _SecondPassConditions(sql=True)
        callbacks = self._callbacks(harness)
        self.assertEqual(
            set(callbacks)
            - {"layer_reload_fn", "layer_used_uids_fn"}
            - {
                "layer_insert_fn",
                "layer_delete_many_fn",
                "layer_update_show_fn",
                "layer_update_all_show_fn",
                "layer_update_name_fn",
                "layer_move_fn",
            },
            {
                "layer_insert_async_fn",
                "layer_delete_many_async_fn",
                "layer_update_name_async_fn",
                "layer_move_async_fn",
            },
        )
        self.assertEqual(callbacks["layer_reload_fn"](), harness.layers)
        self.assertEqual(callbacks["layer_used_uids_fn"](), {"40"})
        self.assertEqual(harness.event_names(), ["data_layers", "data_layer_uids"])

    def test_the_insert_callback_returns_the_new_uid_only_for_a_real_write(self):
        harness = _SecondPassConditions(sql=False)
        callbacks = self._callbacks(harness)
        cases = (
            (WriteReloadResult(None, False, False), None, 0),
            (WriteReloadResult("", True, True), None, 0),
            (WriteReloadResult(None, True, True), None, 0),
            (WriteReloadResult(41, True, True), "41", 0),
            (WriteReloadResult("42", True, False), "42", 1),
        )
        for result, expected, warnings in cases:
            with self.subTest(result=result):
                harness.script["insert_layer_result"] = result
                with harness.patched():
                    self.assertEqual(
                        callbacks["layer_insert_fn"]("Streets", 3), expected
                    )
                self.assertEqual(harness.warning.call_count, warnings)
                if warnings:
                    harness.warning.assert_called_once_with(
                        "window",
                        "Refresh Error",
                        "The layer was created, but the layer list could not be "
                        "refreshed. Reopen the database to see the new layer.",
                    )
        self.assertEqual(
            harness.call("insert_layer_result")[0],
            (("database", "7", "Streets", 3), {}),
        )

    def test_the_layer_refresh_warning_has_no_parent_without_a_sidebar(self):
        harness = _SecondPassConditions(sql=False, sidebar=False)
        harness.script["insert_layer_result"] = WriteReloadResult("42", True, False)
        with harness.patched():
            self._callbacks(harness)["layer_insert_fn"]("Streets", 1)
        self.assertEqual(harness.warning.call_args.args[0], None)

    def test_sql_layer_operations_queue_with_their_title_key_and_arguments(self):
        harness = _SecondPassConditions(sql=True)
        callbacks = self._callbacks(harness)
        done = []
        cases = (
            (
                "layer_insert_async_fn",
                ("Streets", 3),
                "queue_layer_insert",
                ("database", "7", "Streets", 3),
                ("database", "7", "insert_layer", "Streets"),
                "New Layer",
            ),
            (
                "layer_delete_many_async_fn",
                (["40", "41"],),
                "queue_layers_delete",
                ("database", "7", ["40", "41"]),
                ("database", "7", "delete_layers", "40", "41"),
                "Delete Layer",
            ),
            (
                "layer_update_name_async_fn",
                (40, "Streets"),
                "queue_layer_rename",
                ("database", "7", 40, "Streets"),
                ("database", "7", "rename_layer", "40"),
                "Rename Layer",
            ),
            (
                "layer_move_async_fn",
                (40, "41"),
                "queue_layer_reorder",
                ("database", "7", 40, "41"),
                ("database", "7", "move_layer", "40"),
                "Move Layer",
            ),
        )
        for key, args, queue_name, queue_args, pending_key, title in cases:
            with self.subTest(key=key):
                harness.clear()
                harness.handler._pending_sql_operations.clear()
                done.clear()
                with harness.patched():
                    started = callbacks[key](*args, lambda *a: done.append(a))
                self.assertIs(started, True)
                self.assertEqual(harness.call(queue_name), [(queue_args, {})])
                self.assertEqual(harness.handler._pending_sql_operations, {pending_key})
                self.assertIs(callbacks[key](*args, lambda *a: done.append(a)), False)
                self.assertEqual(len(harness.call(queue_name)), 1)
                harness.callbacks[0](harness.result(MutationOutcomeStatus.CONFLICT))
                self.assertEqual(done, [(False, None)])
                self.assertEqual(
                    [e for e in harness.events if e[0] == "present_error"][0][2], title
                )
                self.assertEqual(harness.handler._pending_sql_operations, set())

    def test_a_committed_sql_insert_returns_the_single_created_layer_uid(self):
        for created, expected in (
            (("55",), "55"),
            ((), None),
            (("55", "56"), None),
            (None, None),
        ):
            with self.subTest(created=created):
                harness = _SecondPassConditions(sql=True)
                done = []
                self._callbacks(harness)["layer_insert_async_fn"](
                    "Streets", 1, lambda *a: done.append(a)
                )
                harness.callbacks[0](
                    harness.result(
                        authoritative_result=(
                            None
                            if created is None
                            else AuthoritativeMutationResult(
                                created_resource_ids=created
                            )
                        )
                    )
                )
                self.assertEqual(done, [(True, expected)])

    def test_committed_sql_delete_rename_and_move_hand_back_no_value(self):
        for key, args in (
            ("layer_delete_many_async_fn", (["40"],)),
            ("layer_update_name_async_fn", ("40", "N")),
            ("layer_move_async_fn", ("40", "41")),
        ):
            with self.subTest(key=key):
                harness = _SecondPassConditions(sql=True)
                done = []
                self._callbacks(harness)[key](*args, lambda *a: done.append(a))
                harness.callbacks[0](
                    harness.result(
                        authoritative_result=AuthoritativeMutationResult(
                            created_resource_ids=("99",)
                        )
                    )
                )
                self.assertEqual(done, [(True, None)])

    def test_the_condition_type_save_stops_on_flush_or_write_failure(self):
        harness = _SecondPassConditions(sql=False)
        harness.flush_ok = False
        with harness.patched():
            self.assertIsNone(
                harness.handler._save_condition_types_from_dialog(
                    harness.selected, harness.write, {"new": []}
                )
            )
        self.assertEqual(harness.calls, [])
        harness.flush_ok = True
        harness.script["save_condition_types_result"] = WriteReloadResult(
            {"x": "y"}, False, False
        )
        with harness.patched():
            self.assertIsNone(
                harness.handler._save_condition_types_from_dialog(
                    harness.selected, harness.write, {"new": []}
                )
            )
        harness.warning.assert_not_called()
        self.assertEqual(
            harness.call("save_condition_types_result"),
            [(("database", {"new": []}), {})],
        )

    def test_the_condition_type_save_returns_the_value_and_warns_on_refresh_failure(
        self,
    ):
        harness = _SecondPassConditions(sql=False)
        harness.script["save_condition_types_result"] = WriteReloadResult(
            {"new": "t2"}, True, True
        )
        with harness.patched():
            self.assertEqual(
                harness.handler._save_condition_types_from_dialog(
                    harness.selected, harness.write, {}
                ),
                {"new": "t2"},
            )
        harness.warning.assert_not_called()
        harness.script["save_condition_types_result"] = WriteReloadResult(
            {"new": "t2"}, True, False
        )
        with harness.patched():
            harness.handler._save_condition_types_from_dialog(
                harness.selected, harness.write, {}
            )
        harness.warning.assert_called_once_with(
            "window",
            "Refresh Error",
            "The condition type changes were saved, but the condition type list "
            "could not be refreshed. Reopen the database to see the latest "
            "condition types.",
        )

    def test_the_condition_type_warning_has_no_parent_without_a_sidebar(self):
        harness = _SecondPassConditions(sql=False, sidebar=False)
        with harness.patched():
            harness.handler._warn_condition_type_refresh_failed()
        self.assertIsNone(harness.warning.call_args.args[0])

    def test_condition_type_delete_helpers_validate_and_delete_through_the_service(
        self,
    ):
        harness = _SecondPassConditions(sql=False)
        harness.script["validate_condition_types_delete"] = (
            _SecondPassDeleteValidationResult(
                requested_uids=["1", "2"], blocked_uids=[2, "3"]
            )
        )
        self.assertEqual(
            harness.handler._blocked_condition_type_delete_uids_from_dialog(
                harness.selected, harness.write, ["1", "2"]
            ),
            {"2", "3"},
        )
        harness.flush_ok = False
        with harness.patched():
            self.assertIsNone(
                harness.handler._delete_condition_types_from_dialog(
                    harness.selected, harness.write, ["1"]
                )
            )
        self.assertEqual(harness.call("delete_condition_types_result"), [])
        harness.flush_ok = True
        outcome = WriteReloadResult(["1"], True, False)
        harness.script["delete_condition_types_result"] = outcome
        with harness.patched():
            self.assertIs(
                harness.handler._delete_condition_types_from_dialog(
                    harness.selected, harness.write, ["1"]
                ),
                outcome,
            )
        self.assertEqual(
            harness.call("delete_condition_types_result"),
            [(("database", ["1"]), {})],
        )
        self.assertEqual(harness.warning.call_count, 1)
        harness.script["delete_condition_types_result"] = WriteReloadResult(
            ["1"], True, True
        )
        with harness.patched():
            harness.handler._delete_condition_types_from_dialog(
                harness.selected, harness.write, ["1"]
            )
        harness.warning.assert_not_called()

    def test_the_async_condition_type_save_maps_created_types_and_reports_failure(
        self,
    ):
        harness = _SecondPassConditions(sql=True)
        done = []
        changes = {"new": [{"uid": "x"}]}
        with harness.patched():
            self.assertIs(
                harness.handler._save_condition_types_async_from_dialog(
                    harness.selected, harness.write, changes, lambda *a: done.append(a)
                ),
                True,
            )
        self.assertEqual(
            harness.call("queue_condition_types_save"), [(("database", changes), {})]
        )
        self.assertEqual(
            harness.handler._pending_sql_operations,
            {("database", "7", "condition_types")},
        )
        harness.callbacks[0](
            harness.result(
                authoritative_result=AuthoritativeMutationResult(
                    created_uid_maps=(
                        ("condition_types", (("x", "t9"),)),
                        ("other", (("y", "z"),)),
                    )
                )
            )
        )
        self.assertEqual(done, [(True, {"x": "t9"})])
        done.clear()
        harness.clear()
        with harness.patched():
            harness.handler._save_condition_types_async_from_dialog(
                harness.selected, harness.write, changes, lambda *a: done.append(a)
            )
        harness.callbacks[0](harness.result())
        self.assertEqual(done, [(True, {})])
        done.clear()
        harness.clear()
        with harness.patched():
            harness.handler._save_condition_types_async_from_dialog(
                harness.selected, harness.write, changes, lambda *a: done.append(a)
            )
        harness.callbacks[0](harness.result(MutationOutcomeStatus.REJECTED))
        self.assertEqual(done, [(False, None)])
        self.assertEqual(
            [e[2] for e in harness.events if e[0] == "present_error"],
            ["Condition Types"],
        )


class _SecondPassSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class _SecondPassConditionDialog:
    """Records every argument the handler builds the condition dialog with."""

    instance = None
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._dirty = False
        self.apply_allowed = None
        self.refreshed = []
        self.rejected = 0
        self.deleted = False
        self.condition_navigated = _SecondPassSignal()
        self.destroyed = _SecondPassSignal()
        type(self).instance = self
        type(self).instances.append(self)

    def set_apply_allowed(self, allowed):
        self.apply_allowed = allowed

    def refresh_condition_data(self, conditions):
        self.refreshed.append(dict(conditions))

    def reject(self):
        self.rejected += 1

    def deleteLater(self):
        self.deleted = True


def _second_pass_open_dialog(harness, call, *, on_exec=None):
    """Runs `call` with the dialog class, its modal exec and the deferred delete
    replaced: no real dialog is built and nothing blocks."""
    _SecondPassConditionDialog.instance = None
    executed = []

    def execute(dialog, _event_bus):
        executed.append(dialog)
        if on_exec is not None:
            on_exec(dialog)
        return QtWidgets.QDialog.DialogCode.Rejected

    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch(f"{_COND_MODULE}.EditConditionDialog", _SecondPassConditionDialog)
        )
        stack.enter_context(patch(f"{_COND_MODULE}.exec_with_ost_blocking", execute))
        stack.enter_context(
            patch(
                f"{_COND_MODULE}.delete_later_if_valid",
                side_effect=lambda dialog: dialog.deleteLater(),
            )
        )
        stack.enter_context(harness.patched())
        call()
    return _SecondPassConditionDialog.instance, executed


class ConditionActionHandlerSecondPassCreateTests(unittest.TestCase):
    """The New Condition dialog on both backends: guards, how the dialog is wired, and
    the create-save paths (Access synchronous, SQL queued)."""

    def _open(self, harness, folder_uid="", on_exec=None):
        return _second_pass_open_dialog(
            harness,
            lambda: harness.handler.on_create_requested(folder_uid),
            on_exec=on_exec,
        )

    def test_nothing_opens_without_access_a_bid_an_owner_a_sidebar_or_the_folder(self):
        cases = (
            ("access denied", lambda h: setattr(h, "allowed", set()), ""),
            ("no bid", lambda h: setattr(h, "selected", None), ""),
            ("bid not loaded", lambda h: setattr(h, "owner", None), ""),
            (
                "no sidebar",
                lambda h: setattr(h.coordinator, "conditions_sidebar", None),
                "",
            ),
            ("unknown folder", lambda h: None, "missing"),
        )
        for label, arrange, folder_uid in cases:
            with self.subTest(label):
                harness = _SecondPassConditions(sql=False)
                arrange(harness)
                dialog, executed = self._open(harness, folder_uid)
                self.assertIsNone(dialog)
                self.assertEqual(executed, [])
                self.assertEqual(harness.calls, [])

    def test_the_access_dialog_is_built_from_the_read_service(self):
        harness = _SecondPassConditions(sql=False)
        harness.owner = SimpleNamespace(measure_base=1)
        dialog, executed = self._open(harness)
        self.assertEqual(executed, [dialog])
        kwargs = dialog.kwargs
        self.assertEqual(kwargs["icon_provider"], "icons")
        self.assertEqual(kwargs["parent"], "window")
        synthetic = kwargs["condition"]
        self.assertEqual(
            (
                synthetic.uid,
                synthetic.name,
                synthetic.condition_type,
                synthetic.layer_uid,
                synthetic.thickness,
                synthetic.spacing,
                synthetic.color_fill,
                synthetic.uom1,
            ),
            ("__new__", "", Condition.TYPE_LINEAR, "40", 4.0, 4.0, 13353215, 2),
        )
        self.assertEqual(kwargs["condition_uids"], ["__new__"])
        self.assertEqual(kwargs["conditions_map"], {"__new__": synthetic})
        self.assertIs(kwargs["cdn_types"], harness.cdn_types)
        self.assertEqual(
            {
                uid: (layer.name, layer.visible)
                for uid, layer in kwargs["layers"].items()
            },
            {"40": ("Default", True), "41": ("Roads", False)},
        )
        self.assertIs(kwargs["has_takeoffs_fn"]("anything"), False)
        self.assertIsNone(kwargs["save_async_fn"])
        self.assertIsNone(kwargs["condition_type_save_async_fn"])
        self.assertIs(kwargs["read_only"], False)
        self.assertIs(kwargs["metric"], True)
        self.assertIs(kwargs["read_service"], harness.read)
        self.assertIs(dialog._dirty, True)
        self.assertIs(dialog.apply_allowed, False)
        self.assertTrue(dialog.deleted)
        self.assertIn(("read_layers", "database", "7"), harness.events)
        harness.events.clear()
        types = kwargs["condition_type_reload_fn"]()
        self.assertEqual(types, list(harness.cdn_types.values()))
        self.assertEqual(harness.events, [("read_cdn_types", "database")])
        self.assertIn("layer_insert_fn", kwargs)
        self.assertNotIn("layer_insert_async_fn", kwargs)

    def test_the_access_dialog_validates_condition_type_deletes_with_the_service(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["validate_condition_types_delete"] = (
            _SecondPassDeleteValidationResult(requested_uids=["1"], blocked_uids=["1"])
        )
        dialog, _executed = self._open(harness)
        self.assertEqual(
            dialog.kwargs["condition_type_blocked_delete_uids_fn"](["1"]), {"1"}
        )
        self.assertEqual(
            harness.call("validate_condition_types_delete"), [(("database", ["1"]), {})]
        )
        harness.script["delete_condition_types_result"] = WriteReloadResult(
            ["1"], True, True
        )
        dialog.kwargs["condition_type_delete_fn"](["1"])
        self.assertEqual(
            harness.call("delete_condition_types_result"), [(("database", ["1"]), {})]
        )

    def test_the_sql_dialog_is_built_from_the_hydrated_state_with_async_saves(self):
        harness = _SecondPassConditions(sql=True)
        harness.layers = [
            BidLayer(uid="41", bid_uid="7", name="Roads", sequence=1, show=True)
        ]
        dialog, _executed = self._open(harness)
        kwargs = dialog.kwargs
        self.assertIs(kwargs["cdn_types"], harness.cdn_types)
        self.assertIsNone(kwargs["condition"].layer_uid)
        self.assertEqual(list(kwargs["layers"]), ["41"])
        self.assertEqual(
            [
                event
                for event in harness.events
                if event[0].startswith(("read", "data"))
            ],
            [("data_cdn_types",), ("data_layers",)],
        )
        self.assertIsNotNone(kwargs["save_async_fn"])
        self.assertIsNotNone(kwargs["condition_type_save_async_fn"])
        self.assertEqual(kwargs["condition_type_blocked_delete_uids_fn"](["1"]), set())
        self.assertEqual(harness.call("validate_condition_types_delete"), [])
        harness.events.clear()
        self.assertEqual(
            kwargs["condition_type_reload_fn"](), list(harness.cdn_types.values())
        )
        self.assertEqual(harness.events, [("data_cdn_types",)])
        done = []
        harness.clear()
        kwargs["condition_type_save_async_fn"]({"new": []}, lambda *a: done.append(a))
        self.assertEqual(
            harness.call("queue_condition_types_save"),
            [(("database", {"new": []}), {})],
        )

    def test_the_create_save_is_refused_when_access_or_the_bid_changed_or_the_flush_fails(
        self,
    ):
        results = []

        def attempt(harness, dialog):
            results.append(
                dialog.kwargs["save_fn"]("__new__", UpdateConditionDto({"name": "N"}))
            )

        harness = _SecondPassConditions(sql=False)

        def lose_access(dialog):
            harness.allowed = set()
            attempt(harness, dialog)

        self._open(harness, on_exec=lose_access)
        self.assertEqual(
            (results[0].success, results[0].error),
            (False, "The active bid or edit access changed."),
        )
        self.assertEqual(harness.call("create_condition_result"), [])
        results.clear()
        harness = _SecondPassConditions(sql=False)
        harness.flush_ok = False
        self._open(harness, on_exec=lambda dialog: attempt(harness, dialog))
        self.assertEqual(
            (results[0].success, results[0].error),
            (False, "Failed to save pending visual state."),
        )
        self.assertEqual(harness.call("create_condition_result"), [])

    def test_the_access_create_save_builds_the_spec_from_type_defaults_and_the_dialog(
        self,
    ):
        results = []

        def save(harness, changes):
            harness.script["create_condition_result"] = (
                _SecondPassCreateConditionResult("n1", True, True)
            )
            harness.conditions["n1"] = Condition(uid="n1", name="New")

            def on_exec(dialog):
                results.append(
                    dialog.kwargs["save_fn"]("__new__", UpdateConditionDto(changes))
                )

            self._open(harness, folder_uid="f1", on_exec=on_exec)
            return harness.call("create_condition_result")[0][0]

        harness = _SecondPassConditions(sql=False)
        args = save(harness, {})
        self.assertEqual(args[:2], ("database", "7"))
        spec = args[2]
        self.assertEqual(
            (
                spec.name,
                spec.condition_type,
                spec.thickness,
                spec.spacing,
                spec.layer_uid,
                spec.uom1,
                spec.calc_type1,
                spec.folder_uid,
                spec.display_grid_while_drawing,
            ),
            ("Untitled", Condition.TYPE_LINEAR, 4.0, 4.0, "40", 2, 1, "f1", False),
        )
        self.assertTrue(results[0].success)
        harness = _SecondPassConditions(sql=False)
        spec = save(
            harness,
            {
                "condition_type": Condition.TYPE_AREA,
                "name": "Slab",
                "thickness": 9.5,
                "bogus": 1,
            },
        )[2]
        self.assertEqual(
            (
                spec.name,
                spec.condition_type,
                spec.thickness,
                spec.spacing,
                spec.calc_type1,
                spec.uom1,
                spec.display_grid_while_drawing,
            ),
            ("Slab", Condition.TYPE_AREA, 9.5, 6.0, 11, 5, True),
        )
        self.assertFalse(hasattr(spec, "bogus"))

    def test_the_access_create_save_reports_a_failed_write(self):
        results = []
        harness = _SecondPassConditions(sql=False)
        for outcome in (
            _SecondPassCreateConditionResult(None, False, False),
            _SecondPassCreateConditionResult("", True, True),
        ):
            harness.script["create_condition_result"] = outcome
            self._open(
                harness,
                on_exec=lambda dialog: results.append(
                    dialog.kwargs["save_fn"]("__new__", UpdateConditionDto({}))
                ),
            )
        self.assertEqual(
            [(r.success, r.error) for r in results],
            [(False, "Failed to create condition.")] * 2,
        )

    def test_a_created_condition_is_highlighted_or_its_refresh_failure_is_reported(
        self,
    ):
        for refresh_ok in (True, False):
            with self.subTest(refresh_ok=refresh_ok):
                harness = _SecondPassConditions(sql=False)
                harness.script["create_condition_result"] = (
                    _SecondPassCreateConditionResult("n1", True, refresh_ok)
                )
                harness.conditions["n1"] = Condition(uid="n1", name="New")
                self._open(
                    harness,
                    on_exec=lambda dialog: dialog.kwargs["save_fn"](
                        "__new__", UpdateConditionDto({})
                    ),
                )
                highlights = [e for e in harness.events if e[0] == "highlight"]
                if refresh_ok:
                    self.assertEqual(highlights, [("highlight", {"n1"}, True)])
                else:
                    self.assertEqual(highlights, [])
                    harness.warning.assert_called_once_with(
                        "window",
                        "Refresh Error",
                        "The condition was created, but the conditions list could not "
                        "be refreshed. Reopen the database to see the new condition.",
                    )

    def _sql_create(self, harness, changes=None, on_done=None, folder_uid=""):
        results = []
        saved = []

        def on_exec(dialog):
            saved.append(
                dialog.kwargs["save_async_fn"](
                    "__new__",
                    UpdateConditionDto(changes or {"name": "N"}),
                    results.append,
                )
            )
            if on_done is not None:
                on_done(dialog)

        self._open(harness, folder_uid=folder_uid, on_exec=on_exec)
        return results, saved

    def test_the_sql_create_save_is_refused_before_queueing(self):
        for label, arrange, error in (
            (
                "access lost",
                lambda h: setattr(h, "allowed", set()),
                "The active bid or edit access changed.",
            ),
            (
                "flush failure",
                lambda h: setattr(h, "flush_ok", False),
                "Failed to save pending visual state.",
            ),
        ):
            with self.subTest(label):
                harness = _SecondPassConditions(sql=True)
                results, saved = [], []

                def on_exec(dialog, results=results, saved=saved, harness=harness):
                    arrange(harness)
                    saved.append(
                        dialog.kwargs["save_async_fn"](
                            "__new__", UpdateConditionDto({}), results.append
                        )
                    )

                self._open(harness, on_exec=on_exec)
                self.assertEqual(saved, [False])
                self.assertEqual(
                    [(r.success, r.error, r.error_presented) for r in results],
                    [(False, error, False)],
                )
                self.assertEqual(harness.call("queue_condition_create"), [])

    def test_the_sql_create_save_queues_the_spec_and_completes_on_the_commit(self):
        harness = _SecondPassConditions(sql=True)
        outcome = {}

        def on_done(dialog):
            args, _kwargs = harness.call("queue_condition_create")[0]
            outcome["spec"] = args[2]
            self.assertEqual(args[:2], ("database", "7"))
            self.assertEqual(
                harness.handler._pending_sql_operations,
                {("database", "7", "create_condition")},
            )
            harness.conditions["n9"] = Condition(uid="n9", name="Created")
            harness.callbacks[0](
                harness.result(
                    authoritative_result=AuthoritativeMutationResult(
                        created_resource_ids=("n9",)
                    )
                )
            )

        results, saved = self._sql_create(
            harness,
            {"name": "Slab", "condition_type": Condition.TYPE_AREA},
            on_done,
            "f1",
        )
        self.assertEqual(saved, [True])
        spec = outcome["spec"]
        self.assertEqual(
            (spec.name, spec.condition_type, spec.folder_uid, spec.layer_uid),
            ("Slab", Condition.TYPE_AREA, "f1", "40"),
        )
        self.assertEqual([(r.success, r.error) for r in results], [(True, None)])
        self.assertEqual(harness.handler._pending_sql_operations, set())
        self.assertEqual(
            [e for e in harness.events if e[0] == "highlight"],
            [("highlight", {"n9"}, True)],
        )

    def test_the_sql_create_save_needs_exactly_one_created_condition(self):
        for created in ((), ("a", "b")):
            with self.subTest(created=created):
                harness = _SecondPassConditions(sql=True)

                def on_done(dialog, created=created, harness=harness):
                    harness.callbacks[0](
                        harness.result(
                            authoritative_result=AuthoritativeMutationResult(
                                created_resource_ids=created
                            )
                        )
                    )

                results, saved = self._sql_create(harness, on_done=on_done)
                self.assertEqual(
                    [(r.success, r.error) for r in results],
                    [(False, "The committed condition result was incomplete.")],
                )
                self.assertEqual([e for e in harness.events if e[0] == "highlight"], [])

    def test_a_rejected_sql_create_save_reports_its_message_once(self):
        for message, expected in (
            ("no space", "no space"),
            ("", "Failed to create condition."),
        ):
            with self.subTest(message=message):
                harness = _SecondPassConditions(sql=True)

                def on_done(dialog, message=message, harness=harness):
                    harness.callbacks[0](
                        harness.result(MutationOutcomeStatus.REJECTED, message=message)
                    )

                results, _saved = self._sql_create(harness, on_done=on_done)
                self.assertEqual(
                    [(r.success, r.error, r.error_presented) for r in results],
                    [(False, expected, True)],
                )
                self.assertEqual(
                    [e[2] for e in harness.events if e[0] == "present_error"],
                    ["Create Condition"],
                )


class ConditionActionHandlerSecondPassDuplicatePasteTests(unittest.TestCase):
    """Duplicate and paste of Conditions on both backends side by side."""

    def _duplicate(self, harness, uids=("c1",), **options):
        with harness.patched(), patch(f"{_COND_MODULE}.logger") as logger:
            harness.handler.on_duplicate_requested(list(uids), **options)
        return logger

    def test_duplicate_is_ignored_without_uids_access_or_a_bid(self):
        for label, arrange, uids in (
            ("no uids", lambda h: None, ()),
            ("access denied", lambda h: setattr(h, "allowed", set()), ("c1",)),
            ("no bid", lambda h: setattr(h, "selected", None), ("c1",)),
        ):
            with self.subTest(label):
                harness = _SecondPassConditions(sql=False)
                arrange(harness)
                self._duplicate(harness, uids)
                self.assertEqual(harness.calls, [])

    def test_a_plan_reassignment_needs_its_captured_context(self):
        harness = _SecondPassConditions(sql=False)
        reassign = ConditionTakeoffReassignment(
            condition_uid="c1", takeoff_uids=("t1",), page_uid="page-1"
        )
        with self.assertRaisesRegex(ValueError, "requires its captured Plan context"):
            self._duplicate(harness, reassign_takeoffs=reassign)
        self._duplicate(
            harness, reassign_takeoffs=reassign, context_is_current=lambda: False
        )
        self.assertEqual(harness.calls, [])

    def test_access_duplicate_places_and_highlights_the_copies(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["duplicate_conditions_result"] = WriteReloadResult(
            ["n1", "n2"], True, True
        )
        self._duplicate(harness, ("c1", "c2"))
        self.assertEqual(
            harness.call("duplicate_conditions_result"),
            [(("database", "7", ["c1", "c2"]), {})],
        )
        self.assertEqual(
            [
                event
                for event in harness.events
                if event[0] in ("placement_enter", "highlight")
            ],
            [
                ("placement_enter", "n2", ["n1", "n2"]),
                ("highlight", {"n1", "n2"}, False),
            ],
        )
        harness.warning.assert_not_called()

    def test_access_duplicate_skips_placement_outside_the_takeoff_view_and_the_sidebar(
        self,
    ):
        harness = _SecondPassConditions(sql=False, sidebar=False)
        harness.plan_active = False
        harness.script["duplicate_conditions_result"] = WriteReloadResult(
            ["n1"], True, True
        )
        self._duplicate(harness)
        self.assertEqual(
            [e for e in harness.events if e[0] in ("placement_enter", "highlight")], []
        )

    def test_access_duplicate_failure_logs_and_a_refresh_failure_warns(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["duplicate_conditions_result"] = WriteReloadResult(
            [], False, False
        )
        logger = self._duplicate(harness)
        logger.warning.assert_called_once()
        self.assertEqual(
            [e for e in harness.events if e[0] in ("placement_enter", "highlight")], []
        )
        harness = _SecondPassConditions(sql=False)
        harness.script["duplicate_conditions_result"] = WriteReloadResult(
            ["n1"], True, False
        )
        self._duplicate(harness)
        harness.warning.assert_called_once_with(
            "window",
            "Refresh Error",
            "The condition was duplicated, but the conditions list could not be "
            "refreshed. Reopen the database to see the latest conditions.",
        )
        self.assertEqual(
            [e for e in harness.events if e[0] in ("placement_enter", "highlight")], []
        )

    def test_access_duplicate_with_pending_changes_that_cannot_be_saved_writes_nothing(
        self,
    ):
        harness = _SecondPassConditions(sql=False)
        harness.flush_ok = False
        logger = self._duplicate(harness)
        self.assertEqual(harness.calls, [])
        logger.warning.assert_called_once()

    def test_sql_duplicate_queues_with_its_key_and_title_and_ignores_empty_commits(
        self,
    ):
        harness = _SecondPassConditions(sql=True)
        self._duplicate(harness, ("c1", "c2"))
        self.assertEqual(
            harness.call("queue_conditions_duplicate"),
            [(("database", "7", ["c1", "c2"]), {})],
        )
        self.assertEqual(
            harness.handler._pending_sql_operations,
            {("database", "7", "duplicate", "c1", "c2")},
        )
        harness.callbacks[0](harness.result())
        self.assertEqual(
            [e for e in harness.events if e[0] in ("placement_enter", "highlight")], []
        )
        self.assertEqual(harness.handler._pending_sql_operations, set())
        harness.clear()
        self._duplicate(harness)
        harness.callbacks[0](harness.result(MutationOutcomeStatus.REJECTED))
        self.assertEqual(
            [e[2] for e in harness.events if e[0] == "present_error"],
            ["Duplicate Conditions"],
        )

    def test_sql_duplicate_stops_before_queueing_when_flush_or_the_bid_is_missing(self):
        harness = _SecondPassConditions(sql=True)
        harness.flush_ok = False
        self._duplicate(harness)
        self.assertEqual(harness.calls, [])
        harness = _SecondPassConditions(sql=True)
        harness.owner = None
        self._duplicate(harness)
        self.assertEqual(harness.calls, [])

    def _paste(self, harness, uids, target):
        with harness.patched(), patch(f"{_COND_MODULE}.logger") as logger:
            harness.handler.on_paste_requested(uids, target)
        return logger

    def test_paste_ignores_empty_input_bad_targets_and_missing_permissions(self):
        folder = {"kind": "folder", "folder_uid": "f1"}
        cut = {
            "kind": "folder",
            "folder_uid": "f1",
            "cut": True,
            "clipboard_revision": 2,
        }
        for label, arrange, uids, target in (
            ("no uids", lambda h: None, [], folder),
            ("not a dict", lambda h: None, ["c1"], "folder"),
            ("unknown kind", lambda h: None, ["c1"], {"kind": "page"}),
            (
                "copy without the duplicate right",
                lambda h: setattr(h, "allowed", {Feature.EDIT_CONDITION_STRUCTURE}),
                ["c1"],
                folder,
            ),
            (
                "cut without the structure right",
                lambda h: setattr(h, "allowed", {Feature.DUPLICATE_CONDITION}),
                ["c1"],
                cut,
            ),
            ("no bid", lambda h: setattr(h, "selected", None), ["c1"], folder),
        ):
            for sql in (False, True):
                with self.subTest(label, sql=sql):
                    harness = _SecondPassConditions(sql=sql)
                    arrange(harness)
                    self._paste(harness, uids, target)
                    self.assertEqual(harness.calls, [])

    def test_paste_checks_the_right_that_matches_cut_or_copy(self):
        for target, feature in (
            ({"kind": "root"}, Feature.DUPLICATE_CONDITION),
            (
                {"kind": "root", "cut": True, "clipboard_revision": 1},
                Feature.EDIT_CONDITION_STRUCTURE,
            ),
        ):
            with self.subTest(feature=feature):
                harness = _SecondPassConditions(sql=True, allowed={feature})
                self._paste(harness, ["c1"], target)
                self.assertEqual(
                    [e[1] for e in harness.events if e[0] == "allowed?"][:1], [feature]
                )
                self.assertEqual(len(harness.calls), 1)

    def test_sql_cut_paste_moves_to_the_target_and_completes_the_clipboard(self):
        cases = (
            ({"kind": "folder", "folder_uid": "f1"}, {"folder_uid": "f1"}),
            ({"kind": "root", "folder_uid": ""}, {"folder_uid": None}),
            (
                {"kind": "cdn_type", "folder_uid": "f1", "cdn_type_uid": "t1"},
                {"folder_uid": "f1", "cdn_type_uid": "t1"},
            ),
            (
                {"kind": "cdn_type", "cdn_type_uid": ""},
                {"folder_uid": None, "cdn_type_uid": None},
            ),
        )
        for target, expected in cases:
            with self.subTest(target=target):
                harness = _SecondPassConditions(sql=True)
                target = {**target, "cut": True, "clipboard_revision": 4}
                self._paste(harness, ["c1", "c2"], target)
                self.assertEqual(
                    harness.call("queue_conditions_update"),
                    [(("database", "7", ["c1", "c2"], expected), {})],
                )
                self.assertEqual(
                    harness.handler._pending_sql_operations,
                    {("database", "7", "move", "c1", "c2")},
                )
                harness.callbacks[0](harness.result())
                self.assertEqual(
                    [
                        e
                        for e in harness.events
                        if e[0] in ("complete_cut_paste", "highlight")
                    ],
                    [
                        ("complete_cut_paste", ["c1", "c2"], 4),
                        ("highlight", {"c1", "c2"}, True),
                    ],
                )

    def test_sql_cut_paste_without_a_sidebar_has_nothing_to_complete(self):
        harness = _SecondPassConditions(sql=True, sidebar=False)
        self._paste(
            harness, ["c1"], {"kind": "root", "cut": True, "clipboard_revision": 1}
        )
        harness.callbacks[0](harness.result())
        self.assertEqual(
            [e for e in harness.events if e[0] in ("complete_cut_paste", "highlight")],
            [],
        )

    def test_sql_copy_paste_duplicates_into_the_target_and_places_the_copies(self):
        for target, expected in (
            ({"kind": "folder", "folder_uid": "f1"}, {"folder_uid": "f1"}),
            ({"kind": "root"}, {"folder_uid": None}),
            (
                {"kind": "cdn_type", "folder_uid": "", "cdn_type_uid": "t1"},
                {"folder_uid": None, "cdn_type_uid": "t1"},
            ),
        ):
            with self.subTest(target=target):
                harness = _SecondPassConditions(sql=True)
                self._paste(harness, ["c1"], target)
                self.assertEqual(
                    harness.call("queue_conditions_duplicate"),
                    [(("database", "7", ["c1"]), {"target_changes": expected})],
                )
                self.assertEqual(
                    harness.handler._pending_sql_operations,
                    {("database", "7", "paste", "c1")},
                )
                with patch(f"{_COND_MODULE}.logger"):
                    harness.callbacks[0](
                        harness.result(
                            authoritative_result=AuthoritativeMutationResult(
                                created_resource_ids=("n1", "n2")
                            )
                        )
                    )
                self.assertEqual(
                    [
                        e
                        for e in harness.events
                        if e[0] in ("placement_enter", "highlight")
                    ],
                    [
                        ("placement_enter", "n2", ["n1", "n2"]),
                        ("highlight", {"n1", "n2"}, False),
                    ],
                )

    def test_a_sql_copy_paste_that_created_nothing_or_lost_access_places_nothing(self):
        for label, created, revoke in (
            ("nothing created", (), False),
            ("access revoked", ("n1",), True),
        ):
            with self.subTest(label):
                harness = _SecondPassConditions(sql=True)
                self._paste(harness, ["c1"], {"kind": "root"})
                if revoke:
                    harness.allowed = set()
                harness.callbacks[0](
                    harness.result(
                        authoritative_result=AuthoritativeMutationResult(
                            created_resource_ids=created
                        )
                    )
                )
                self.assertEqual(
                    [
                        e
                        for e in harness.events
                        if e[0] in ("placement_enter", "highlight")
                    ],
                    [],
                )

    def test_a_sql_paste_rejection_is_presented_under_its_title(self):
        for target, title in (
            ({"kind": "root", "cut": True, "clipboard_revision": 1}, "Move Conditions"),
            ({"kind": "root"}, "Paste Conditions"),
        ):
            with self.subTest(title=title):
                harness = _SecondPassConditions(sql=True)
                self._paste(harness, ["c1"], target)
                harness.callbacks[0](harness.result(MutationOutcomeStatus.REJECTED))
                self.assertEqual(
                    [e[2] for e in harness.events if e[0] == "present_error"], [title]
                )

    def test_access_cut_paste_moves_each_condition_and_reloads_the_moved_ones(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["update_condition"] = [
            SimpleNamespace(success=True, error=""),
            SimpleNamespace(success=False, error="locked"),
            SimpleNamespace(success=True, error=""),
        ]
        target = {
            "kind": "cdn_type",
            "folder_uid": "f1",
            "cdn_type_uid": "t1",
            "cut": True,
            "clipboard_revision": 6,
        }
        logger = self._paste(harness, ["c1", "c2", "c3"], target)
        updates = harness.call("update_condition")
        self.assertEqual(
            [(args[:3], kwargs, args[3].get_changes()) for args, kwargs in updates],
            [
                (
                    ("database", "7", uid),
                    {"publish_database_refreshed_after_write": False},
                    {"folder_uid": "f1", "cdn_type_uid": "t1"},
                )
                for uid in ("c1", "c2", "c3")
            ],
        )
        self.assertEqual(
            harness.call("reload_conditions_and_notify"),
            [
                (
                    (
                        "database",
                        "7",
                        ["c1", "c3"],
                        ["folder_uid", "cdn_type_uid"],
                        [ChangeOperation.UPDATE],
                    ),
                    {},
                )
            ],
        )
        logger.warning.assert_called_once()
        self.assertEqual(
            [e for e in harness.events if e[0] in ("complete_cut_paste", "highlight")],
            [
                ("complete_cut_paste", ["c1", "c3"], 6),
                ("highlight", {"c1", "c3"}, True),
            ],
        )

    def test_access_cut_paste_to_a_folder_only_reloads_the_folder_field(self):
        harness = _SecondPassConditions(sql=False)
        target = {
            "kind": "folder",
            "folder_uid": "",
            "cut": True,
            "clipboard_revision": 1,
        }
        self._paste(harness, ["c1"], target)
        ((args, _kwargs),) = harness.call("update_condition")
        self.assertEqual(args[3].get_changes(), {"folder_uid": None})
        self.assertEqual(
            harness.call("reload_conditions_and_notify")[0][0][3], ["folder_uid"]
        )

    def test_access_cut_paste_stops_on_flush_failure_total_failure_or_reload_failure(
        self,
    ):
        target = {
            "kind": "folder",
            "folder_uid": "f1",
            "cut": True,
            "clipboard_revision": 2,
        }
        harness = _SecondPassConditions(sql=False)
        harness.flush_ok = False
        self._paste(harness, ["c1"], target)
        self.assertEqual(harness.calls, [])
        harness = _SecondPassConditions(sql=False)
        harness.script["update_condition"] = SimpleNamespace(success=False, error="x")
        self._paste(harness, ["c1", "c2"], target)
        self.assertEqual(harness.call("reload_conditions_and_notify"), [])
        self.assertEqual(
            [e for e in harness.events if e[0] in ("complete_cut_paste", "highlight")],
            [],
        )
        harness = _SecondPassConditions(sql=False)
        harness.script["reload_conditions_and_notify"] = False
        self._paste(harness, ["c1"], target)
        harness.warning.assert_called_once_with(
            "window",
            "Refresh Error",
            "The condition was moved, but the conditions list could not be refreshed. "
            "Reopen the database to see the latest conditions.",
        )
        self.assertEqual(
            [e for e in harness.events if e[0] in ("complete_cut_paste", "highlight")],
            [],
        )

    def test_access_cut_paste_without_a_sidebar_still_reloads(self):
        harness = _SecondPassConditions(sql=False, sidebar=False)
        target = {
            "kind": "folder",
            "folder_uid": "f1",
            "cut": True,
            "clipboard_revision": 2,
        }
        self._paste(harness, ["c1"], target)
        self.assertEqual(len(harness.call("reload_conditions_and_notify")), 1)
        self.assertEqual(
            [e for e in harness.events if e[0] in ("complete_cut_paste", "highlight")],
            [],
        )

    def test_access_copy_paste_duplicates_then_applies_the_target_to_the_copies(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["duplicate_conditions_result"] = WriteReloadResult(
            ["n1", "n2"], True, True
        )
        harness.script["update_condition"] = [
            SimpleNamespace(success=False, error="locked"),
            SimpleNamespace(success=True, error=""),
        ]
        logger = self._paste(
            harness,
            ["c1"],
            {"kind": "cdn_type", "folder_uid": "f1", "cdn_type_uid": "t1"},
        )
        self.assertEqual(
            harness.call("duplicate_conditions_result"),
            [(("database", "7", ["c1"]), {})],
        )
        updates = harness.call("update_condition")
        self.assertEqual(
            [(args[2], args[3].get_changes(), kwargs) for args, kwargs in updates],
            [
                (
                    "n1",
                    {"folder_uid": "f1", "cdn_type_uid": "t1"},
                    {"publish_database_refreshed_after_write": False},
                ),
                (
                    "n2",
                    {"folder_uid": "f1", "cdn_type_uid": "t1"},
                    {"publish_database_refreshed_after_write": False},
                ),
            ],
        )
        self.assertEqual(
            harness.call("reload_conditions_and_notify"),
            [
                (
                    (
                        "database",
                        "7",
                        ["n1", "n2"],
                        ["folder_uid", "cdn_type_uid"],
                        [ChangeOperation.UPDATE],
                    ),
                    {},
                )
            ],
        )
        logger.warning.assert_called_once()
        self.assertEqual(
            [e for e in harness.events if e[0] in ("placement_enter", "highlight")],
            [
                ("placement_enter", "n2", ["n1", "n2"]),
                ("highlight", {"n1", "n2"}, False),
            ],
        )

    def test_access_copy_paste_to_the_root_clears_only_the_folder(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["duplicate_conditions_result"] = WriteReloadResult(
            ["n1"], True, True
        )
        self._paste(harness, ["c1"], {"kind": "root"})
        ((args, _kwargs),) = harness.call("update_condition")
        self.assertEqual(args[3].get_changes(), {"folder_uid": None})

    def test_access_copy_paste_without_an_applied_target_does_not_reload(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["duplicate_conditions_result"] = WriteReloadResult(
            ["n1"], True, True
        )
        harness.script["update_condition"] = SimpleNamespace(success=False, error="x")
        logger = self._paste(harness, ["c1"], {"kind": "folder", "folder_uid": "f1"})
        self.assertEqual(harness.call("reload_conditions_and_notify"), [])
        logger.warning.assert_called_once()
        self.assertIn(("placement_enter", "n1", ["n1"]), harness.events)

    def test_access_copy_paste_failure_or_refresh_failure_applies_no_target(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["duplicate_conditions_result"] = WriteReloadResult(
            [], False, False
        )
        logger = self._paste(harness, ["c1"], {"kind": "root"})
        self.assertEqual(harness.call("update_condition"), [])
        logger.warning.assert_called_once()
        harness = _SecondPassConditions(sql=False)
        harness.script["duplicate_conditions_result"] = WriteReloadResult(
            ["n1"], True, False
        )
        self._paste(harness, ["c1"], {"kind": "root"})
        self.assertEqual(harness.call("update_condition"), [])
        self.assertEqual(harness.warning.call_count, 1)
        self.assertEqual(
            harness.warning.call_args.args[:2], ("window", "Refresh Error")
        )


class ConditionActionHandlerSecondPassStructureCommandTests(unittest.TestCase):
    """Delete, renumber, folder and field-update commands on both backends."""

    def _run(self, harness, call):
        with harness.patched(), patch(f"{_COND_MODULE}.logger") as logger:
            call(harness.handler)
        return logger

    def test_delete_is_ignored_without_uids_access_bid_sidebar_or_known_conditions(
        self,
    ):
        for label, arrange, uids in (
            ("no uids", lambda h: None, []),
            ("access denied", lambda h: setattr(h, "allowed", set()), ["c1"]),
            ("no bid", lambda h: setattr(h, "selected", None), ["c1"]),
            (
                "no sidebar",
                lambda h: setattr(h.coordinator, "conditions_sidebar", None),
                ["c1"],
            ),
            ("unknown condition", lambda h: None, ["missing"]),
        ):
            for sql in (False, True):
                with self.subTest(label, sql=sql):
                    harness = _SecondPassConditions(sql=sql)
                    arrange(harness)
                    self._run(harness, lambda h: h.on_delete_requested(uids))
                    self.assertEqual(harness.calls, [])
                    harness.confirm_delete.assert_not_called()

    def test_delete_asks_with_the_condition_names_and_stops_when_declined_or_unflushed(
        self,
    ):
        harness = _SecondPassConditions(sql=False)
        harness.replacement = None
        self._run(harness, lambda h: h.on_delete_requested(["c1", "c2"]))
        self.assertEqual(
            harness.confirm_delete.call_args.args,
            ("window", [("c1", "Name c1"), ("c2", "Name c2")]),
        )
        harness = _SecondPassConditions(sql=False)
        with harness.patched() as _stack:
            harness.confirm_delete.side_effect = lambda _parent, _names: []
            harness.handler.on_delete_requested(["c1"])
        self.assertEqual(harness.calls, [])
        harness = _SecondPassConditions(sql=False)
        harness.flush_ok = False
        self._run(harness, lambda h: h.on_delete_requested(["c1"]))
        self.assertEqual(harness.calls, [])

    def test_access_delete_exits_placement_and_selects_the_replacement(self):
        for replacement, expected in (("c2", {"c2"}), (None, set())):
            with self.subTest(replacement=replacement):
                harness = _SecondPassConditions(sql=False)
                harness.replacement = replacement
                self._run(harness, lambda h: h.on_delete_requested(["c1"]))
                self.assertEqual(
                    harness.call("delete_conditions"), [(("database", "7", ["c1"]), {})]
                )
                self.assertEqual(
                    [
                        e
                        for e in harness.events
                        if e[0] in ("placement_exit", "ensure_select_mode", "highlight")
                    ],
                    [
                        ("placement_exit",),
                        ("ensure_select_mode",),
                        ("highlight", expected, False),
                    ],
                )

    def test_access_delete_failure_keeps_the_placement_and_logs(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["delete_conditions"] = False
        logger = self._run(harness, lambda h: h.on_delete_requested(["c1"]))
        logger.warning.assert_called_once()
        self.assertEqual(
            [e for e in harness.events if e[0] in ("placement_exit", "highlight")], []
        )

    def test_sql_delete_queues_with_the_confirmed_uids_and_finishes_when_committed(
        self,
    ):
        harness = _SecondPassConditions(sql=True)
        harness.replacement = "c2"
        with harness.patched():
            harness.confirm_delete.side_effect = lambda _parent, names: [names[0][0]]
            harness.handler.on_delete_requested(["c1", "c2"])
        self.assertEqual(
            harness.call("queue_conditions_delete"), [(("database", "7", ["c1"]), {})]
        )
        self.assertEqual(
            harness.handler._pending_sql_operations, {("database", "7", "delete", "c1")}
        )
        self.assertIn(("selection_after_delete", ["c1"]), harness.events)
        harness.callbacks[0](harness.result())
        self.assertEqual(
            [
                e
                for e in harness.events
                if e[0] in ("placement_exit", "ensure_select_mode", "highlight")
            ],
            [
                ("placement_exit",),
                ("ensure_select_mode",),
                ("highlight", {"c2"}, False),
            ],
        )

    def test_renumber_availability_needs_a_bid_the_right_and_conditions(self):
        for label, arrange, expected in (
            ("ready", lambda h: None, True),
            ("no bid", lambda h: setattr(h, "selected", None), False),
            ("access denied", lambda h: setattr(h, "allowed", set()), False),
            ("no conditions", lambda h: setattr(h, "conditions", {}), False),
        ):
            with self.subTest(label):
                harness = _SecondPassConditions(sql=False)
                arrange(harness)
                self.assertIs(harness.handler.can_renumber_conditions(), expected)

    def test_renumber_asks_then_writes_through_the_backend(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                harness = _SecondPassConditions(sql=sql)
                harness.ordered = ["c2", "c1"]
                self._run(harness, lambda h: h.on_renumber_requested())
                harness.confirm.assert_called_once_with(
                    "window",
                    "Renumber Conditions",
                    "Renumber all the conditions using the current sort order?\n"
                    "This cannot be undone",
                )
                if sql:
                    self.assertEqual(
                        harness.call("queue_conditions_renumber"),
                        [(("database", "7", ["c2", "c1"]), {})],
                    )
                    self.assertEqual(
                        harness.handler._pending_sql_operations,
                        {("database", "7", "renumber", "c2", "c1")},
                    )
                    harness.callbacks[0](harness.result(MutationOutcomeStatus.REJECTED))
                    self.assertEqual(
                        [e[2] for e in harness.events if e[0] == "present_error"],
                        ["Renumber Conditions"],
                    )
                else:
                    self.assertEqual(
                        harness.call("renumber_conditions"),
                        [(("database", "7", ["c2", "c1"]), {})],
                    )
                    harness.warning.assert_not_called()

    def test_renumber_stops_before_writing_when_it_cannot_or_is_declined(self):
        for label, arrange in (
            ("no bid", lambda h: setattr(h, "selected", None)),
            (
                "no sidebar",
                lambda h: setattr(h.coordinator, "conditions_sidebar", None),
            ),
            ("empty order", lambda h: setattr(h, "ordered", [])),
            (
                "unknown condition in the order",
                lambda h: setattr(h, "ordered", ["c1", "x"]),
            ),
            ("flush failure", lambda h: setattr(h, "flush_ok", False)),
        ):
            for sql in (False, True):
                with self.subTest(label, sql=sql):
                    harness = _SecondPassConditions(sql=sql)
                    arrange(harness)
                    self._run(harness, lambda h: h.on_renumber_requested())
                    self.assertEqual(harness.calls, [])
        harness = _SecondPassConditions(sql=False)
        with harness.patched():
            harness.confirm.return_value = False
            harness.handler.on_renumber_requested()
        self.assertEqual(harness.calls, [])

    def test_renumber_loses_its_right_while_the_confirmation_is_open(self):
        harness = _SecondPassConditions(sql=False)
        with harness.patched():
            harness.confirm.side_effect = (
                lambda *args: setattr(harness, "allowed", set()) or True
            )
            harness.handler.on_renumber_requested()
        self.assertEqual(harness.calls, [])

    def test_an_access_renumber_failure_warns_with_the_database_hint(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["renumber_conditions"] = False
        self._run(harness, lambda h: h.on_renumber_requested())
        harness.warning.assert_called_once_with(
            "window",
            "Renumber Conditions",
            f"Failed to renumber conditions. {_SECOND_PASS_DB_LOCKED_HINT}",
        )

    def test_create_folder_is_ignored_without_the_right_a_bid_a_sidebar_or_a_flush(
        self,
    ):
        for label, arrange in (
            ("access denied", lambda h: setattr(h, "allowed", set())),
            ("no bid", lambda h: setattr(h, "selected", None)),
            (
                "no sidebar",
                lambda h: setattr(h.coordinator, "conditions_sidebar", None),
            ),
            ("flush failure", lambda h: setattr(h, "flush_ok", False)),
        ):
            for sql in (False, True):
                with self.subTest(label, sql=sql):
                    harness = _SecondPassConditions(sql=sql)
                    arrange(harness)
                    self._run(harness, lambda h: h.on_create_folder_requested("f1"))
                    self.assertEqual(harness.calls, [])

    def test_access_create_folder_starts_the_inline_edit_of_the_new_folder(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["create_condition_folder_result"] = WriteReloadResult(
            "f9", True, True
        )
        self._run(harness, lambda h: h.on_create_folder_requested("f1"))
        self.assertEqual(
            harness.call("create_condition_folder_result"),
            [(("database", "7", "New Folder", "f1"), {})],
        )
        self.assertEqual(harness.events[-1], ("pending_folder_edit", "f9"))
        harness = _SecondPassConditions(sql=False)
        harness.script["create_condition_folder_result"] = WriteReloadResult(
            "f9", True, True
        )
        self._run(harness, lambda h: h.on_create_folder_requested(""))
        self.assertEqual(harness.call("create_condition_folder_result")[0][0][3], None)

    def test_access_create_folder_failure_logs_and_a_refresh_failure_warns(self):
        for outcome in (
            WriteReloadResult(None, False, False),
            WriteReloadResult("", True, True),
        ):
            harness = _SecondPassConditions(sql=False)
            harness.script["create_condition_folder_result"] = outcome
            logger = self._run(harness, lambda h: h.on_create_folder_requested(""))
            logger.warning.assert_called_once()
            self.assertNotIn("pending_folder_edit", harness.event_names())
        harness = _SecondPassConditions(sql=False)
        harness.script["create_condition_folder_result"] = WriteReloadResult(
            "f9", True, False
        )
        self._run(harness, lambda h: h.on_create_folder_requested(""))
        harness.warning.assert_called_once_with(
            "window",
            "Refresh Error",
            "The condition was created, but the conditions list could not be "
            "refreshed. Reopen the database to see the latest conditions.",
        )
        self.assertNotIn("pending_folder_edit", harness.event_names())

    def test_sql_create_folder_queues_and_starts_the_edit_only_for_a_created_folder(
        self,
    ):
        harness = _SecondPassConditions(sql=True)
        self._run(harness, lambda h: h.on_create_folder_requested("f1"))
        self.assertEqual(
            harness.call("queue_condition_folder_create"),
            [(("database", "7", "New Folder", "f1"), {})],
        )
        self.assertEqual(
            harness.handler._pending_sql_operations,
            {("database", "7", "create_folder", "f1")},
        )
        harness.callbacks[0](
            harness.result(
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("f9", "f10")
                )
            )
        )
        self.assertEqual(harness.events[-1], ("pending_folder_edit", "f9"))
        harness = _SecondPassConditions(sql=True)
        self._run(harness, lambda h: h.on_create_folder_requested(""))
        self.assertEqual(
            harness.handler._pending_sql_operations,
            {("database", "7", "create_folder", "root")},
        )
        harness.callbacks[0](harness.result())
        self.assertNotIn("pending_folder_edit", harness.event_names())
        harness.clear()
        self._run(harness, lambda h: h.on_create_folder_requested(""))
        harness.allowed = set()
        harness.callbacks[0](
            harness.result(
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("f9",)
                )
            )
        )
        self.assertNotIn("pending_folder_edit", harness.event_names())

    def test_folder_rename_writes_through_the_backend_and_reverts_on_failure(self):
        harness = _SecondPassConditions(sql=True)
        self._run(harness, lambda h: h.on_folder_renamed("f1", "Plans"))
        self.assertEqual(
            harness.call("queue_condition_folder_rename"),
            [(("database", "7", "f1", "Plans"), {})],
        )
        self.assertEqual(
            harness.handler._pending_sql_operations,
            {("database", "7", "rename_folder", "f1")},
        )
        harness.callbacks[0](harness.result(MutationOutcomeStatus.REJECTED))
        self.assertEqual(
            [e[2] for e in harness.events if e[0] == "present_error"],
            ["Rename Condition Folder"],
        )
        harness = _SecondPassConditions(sql=False)
        self._run(harness, lambda h: h.on_folder_renamed("f1", "Plans"))
        self.assertEqual(
            harness.call("rename_condition_folder"), [(("database", "f1", "Plans"), {})]
        )
        self.assertNotIn("refresh_conditions_ui", harness.event_names())
        harness.script["rename_condition_folder"] = False
        logger = self._run(harness, lambda h: h.on_folder_renamed("f1", "Plans"))
        logger.warning.assert_called_once()
        self.assertEqual(harness.event_names().count("refresh_conditions_ui"), 1)

    def test_folder_rename_is_ignored_without_the_right_a_bid_or_a_flush(self):
        for arrange in (
            lambda h: setattr(h, "allowed", set()),
            lambda h: setattr(h, "selected", None),
            lambda h: setattr(h, "flush_ok", False),
        ):
            for sql in (False, True):
                harness = _SecondPassConditions(sql=sql)
                arrange(harness)
                self._run(harness, lambda h: h.on_folder_renamed("f1", "Plans"))
                self.assertEqual(harness.calls, [])

    def test_condition_rename_records_the_pending_selection_and_writes_the_name(self):
        harness = _SecondPassConditions(sql=True)
        self._run(harness, lambda h: h.on_condition_renamed("c1", "Plan A"))
        self.assertEqual(
            [
                e
                for e in harness.events
                if e[0] in ("pending_condition_selection", "flush")
            ],
            [("pending_condition_selection", "c1"), ("flush", "database")],
        )
        self.assertEqual(
            harness.call("queue_conditions_update"),
            [(("database", "7", ["c1"], {"name": "Plan A"}), {})],
        )
        self.assertEqual(
            harness.handler._pending_sql_operations,
            {("database", "7", "rename_condition", "c1")},
        )
        harness.callbacks[0](harness.result())
        self.assertEqual(
            [e for e in harness.events if e[0] == "highlight"],
            [("highlight", {"c1"}, True)],
        )
        harness = _SecondPassConditions(sql=False)
        harness.script["update_condition"] = SimpleNamespace(
            success=False, error="refused"
        )
        self._run(harness, lambda h: h.on_condition_renamed("c1", "Plan A"))
        ((args, kwargs),) = harness.call("update_condition")
        self.assertEqual(
            (args[:3], args[3].get_changes(), kwargs),
            (("database", "7", "c1"), {"name": "Plan A"}, {}),
        )
        self.assertEqual(
            [
                e[0]
                for e in harness.events
                if e[0] in ("refresh_conditions_ui", "highlight")
            ],
            ["refresh_conditions_ui", "highlight"],
        )

    def test_condition_rename_without_a_sidebar_still_writes_and_does_not_highlight(
        self,
    ):
        harness = _SecondPassConditions(sql=False, sidebar=False)
        harness.script["update_condition"] = SimpleNamespace(
            success=False, error="refused"
        )
        self._run(harness, lambda h: h.on_condition_renamed("c1", "Plan A"))
        self.assertEqual(len(harness.call("update_condition")), 1)
        self.assertNotIn("highlight", harness.event_names())

    def test_condition_rename_is_ignored_without_the_right_a_bid_or_a_flush(self):
        for arrange in (
            lambda h: setattr(h, "allowed", set()),
            lambda h: setattr(h, "selected", None),
            lambda h: setattr(h, "flush_ok", False),
            lambda h: setattr(h, "owner", None),
        ):
            harness = _SecondPassConditions(sql=True)
            arrange(harness)
            self._run(harness, lambda h: h.on_condition_renamed("c1", "N"))
            self.assertEqual(harness.calls, [])

    def test_folder_delete_validates_confirms_and_deletes_the_confirmed_folders(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                harness = _SecondPassConditions(sql=sql)
                harness.folders["f2"] = BidConditionFolder(uid="f2", name="Folder 2")
                harness.script["validate_condition_folder_delete"] = (
                    _SecondPassDeleteValidationResult(
                        requested_uids=["f1", "f2"], blocked_uids=["f2"]
                    )
                )
                harness.script["delete_condition_folders_result"] = WriteReloadResult(
                    ["f1"], True, True
                )
                with harness.patched():
                    harness.confirm_multi.side_effect = lambda *args: [
                        ("Folder 1", "f1")
                    ]
                    harness.handler.on_folder_delete_requested(["f1", "f2"])
                self.assertEqual(
                    harness.confirm_multi.call_args.args,
                    (
                        "window",
                        "Delete Folder",
                        [("Folder 1", "f1"), ("Folder 2", "f2")],
                        {"f2"},
                    ),
                )
                self.assertEqual(
                    harness.call("validate_condition_folder_delete"),
                    [(("database", "7", ["f1", "f2"]), {})],
                )
                if sql:
                    self.assertEqual(
                        harness.call("queue_condition_folders_delete"),
                        [(("database", "7", ["f1"]), {})],
                    )
                    self.assertEqual(
                        harness.handler._pending_sql_operations,
                        {("database", "7", "delete_folders", "f1")},
                    )
                    harness.callbacks[0](harness.result(MutationOutcomeStatus.REJECTED))
                    self.assertEqual(
                        [e[2] for e in harness.events if e[0] == "present_error"],
                        ["Delete Condition Folders"],
                    )
                else:
                    self.assertEqual(
                        harness.call("delete_condition_folders_result"),
                        [(("database", "7", ["f1"]), {})],
                    )

    def test_folder_delete_stops_when_unflushed_unknown_declined_or_unauthorised(self):
        for label, arrange in (
            ("empty", None),
            ("access", lambda h: setattr(h, "allowed", set())),
            ("no bid", lambda h: setattr(h, "selected", None)),
            ("flush", lambda h: setattr(h, "flush_ok", False)),
            ("unknown folder", lambda h: None),
        ):
            harness = _SecondPassConditions(sql=False)
            harness.script["validate_condition_folder_delete"] = (
                _SecondPassDeleteValidationResult(requested_uids=[], blocked_uids=[])
            )
            uids = [] if arrange is None else ["f1"]
            if label == "unknown folder":
                uids = ["missing"]
            elif arrange is not None:
                arrange(harness)
            self._run(harness, lambda h: h.on_folder_delete_requested(uids))
            self.assertEqual(harness.call("delete_condition_folders_result"), [], label)
        harness = _SecondPassConditions(sql=False)
        harness.script["validate_condition_folder_delete"] = (
            _SecondPassDeleteValidationResult(requested_uids=["f1"], blocked_uids=[])
        )
        with harness.patched():
            harness.confirm_multi.side_effect = lambda *args: None
            harness.handler.on_folder_delete_requested(["f1"])
        self.assertEqual(harness.call("delete_condition_folders_result"), [])

    def test_a_failed_access_folder_delete_is_logged(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["validate_condition_folder_delete"] = (
            _SecondPassDeleteValidationResult(requested_uids=["f1"], blocked_uids=[])
        )
        harness.script["delete_condition_folders_result"] = WriteReloadResult(
            None, False, False
        )
        logger = self._run(harness, lambda h: h.on_folder_delete_requested(["f1"]))
        logger.warning.assert_called_once()

    def test_move_to_folder_writes_the_folder_and_highlights_the_moved_condition(self):
        for folder, expected in (("f1", "f1"), ("", None)):
            with self.subTest(folder=folder):
                harness = _SecondPassConditions(sql=True)
                self._run(
                    harness, lambda h: h.on_move_condition_to_folder("c1", folder)
                )
                self.assertEqual(
                    harness.call("queue_conditions_update"),
                    [(("database", "7", ["c1"], {"folder_uid": expected}), {})],
                )
                self.assertEqual(
                    harness.handler._pending_sql_operations,
                    {("database", "7", "move_condition", "c1")},
                )
                harness.callbacks[0](harness.result())
                self.assertEqual(
                    [e for e in harness.events if e[0] == "highlight"],
                    [("highlight", {"c1"}, True)],
                )
                harness = _SecondPassConditions(sql=False)
                harness.script["update_condition"] = SimpleNamespace(
                    success=False, error="x"
                )
                logger = self._run(
                    harness, lambda h: h.on_move_condition_to_folder("c1", folder)
                )
                ((args, _kwargs),) = harness.call("update_condition")
                self.assertEqual(args[3].get_changes(), {"folder_uid": expected})
                logger.warning.assert_called_once()

    def test_move_to_folder_is_ignored_without_the_right_a_bid_or_a_flush(self):
        for arrange in (
            lambda h: setattr(h, "allowed", set()),
            lambda h: setattr(h, "selected", None),
            lambda h: setattr(h, "flush_ok", False),
            lambda h: setattr(h, "owner", None),
        ):
            harness = _SecondPassConditions(sql=True)
            arrange(harness)
            self._run(harness, lambda h: h.on_move_condition_to_folder("c1", "f1"))
            self.assertEqual(harness.calls, [])

    def test_bulk_field_updates_map_empty_values_to_none_and_use_their_own_key(self):
        for method, field, value, expected in (
            ("on_condition_layer_change_requested", "layer_uid", "40", "40"),
            ("on_condition_layer_change_requested", "layer_uid", "", None),
            ("on_condition_type_change_requested", "cdn_type_uid", "t1", "t1"),
            ("on_condition_type_change_requested", "cdn_type_uid", "", None),
        ):
            with self.subTest(field=field, value=value):
                harness = _SecondPassConditions(sql=True)
                self._run(harness, lambda h: getattr(h, method)(["c1", "c2"], value))
                self.assertEqual(
                    harness.call("queue_conditions_update"),
                    [(("database", "7", ["c1", "c2"], {field: expected}), {})],
                )
                self.assertEqual(
                    harness.handler._pending_sql_operations,
                    {("database", "7", "bulk_update", field, "c1", "c2")},
                )
                harness.callbacks[0](harness.result())
                self.assertEqual(
                    [e for e in harness.events if e[0] == "highlight"],
                    [("highlight", {"c1", "c2"}, True)],
                )

    def test_bulk_field_updates_without_a_sidebar_do_not_highlight(self):
        harness = _SecondPassConditions(sql=True, sidebar=False)
        self._run(
            harness, lambda h: h.on_condition_layer_change_requested(["c1"], "40")
        )
        harness.callbacks[0](harness.result())
        self.assertNotIn("highlight", harness.event_names())

    def test_bulk_field_updates_are_ignored_without_input_the_right_a_bid_or_a_flush(
        self,
    ):
        for label, arrange, uids in (
            ("no uids", lambda h: None, []),
            ("access denied", lambda h: setattr(h, "allowed", set()), ["c1"]),
            ("no bid", lambda h: setattr(h, "selected", None), ["c1"]),
            ("flush", lambda h: setattr(h, "flush_ok", False), ["c1"]),
            ("bid not loaded", lambda h: setattr(h, "owner", None), ["c1"]),
        ):
            harness = _SecondPassConditions(sql=True)
            arrange(harness)
            self._run(
                harness, lambda h: h.on_condition_layer_change_requested(uids, "40")
            )
            self.assertEqual(harness.calls, [], label)

    def test_a_sql_bulk_update_rejection_is_presented_under_its_title(self):
        harness = _SecondPassConditions(sql=True)
        self._run(harness, lambda h: h.on_condition_type_change_requested(["c1"], "t1"))
        harness.callbacks[0](harness.result(MutationOutcomeStatus.REJECTED))
        self.assertEqual(
            [e[2] for e in harness.events if e[0] == "present_error"],
            ["Update Conditions"],
        )


class ConditionActionHandlerSecondPassOwnershipHelperTests(unittest.TestCase):
    """The small guards every command relies on, tested directly with exact values."""

    def test_the_selected_bid_and_write_service_pair(self):
        harness = _SecondPassConditions(sql=False)
        self.assertEqual(
            harness.handler._get_bid_ref_and_write_service(),
            (BidRef("database", "7"), harness.write),
        )
        harness.selected = None
        self.assertEqual(harness.handler._get_bid_ref_and_write_service(), (None, None))

    def test_flushing_asks_the_coordinator_for_the_bid_database(self):
        harness = _SecondPassConditions(sql=False)
        self.assertIs(harness.handler._flush_deferred_for_bid(harness.selected), True)
        harness.flush_ok = False
        self.assertIs(harness.handler._flush_deferred_for_bid(harness.selected), False)
        self.assertEqual(
            [e for e in harness.events if e[0] == "flush"],
            [("flush", "database")] * 2,
        )

    def test_the_unit_system_follows_the_current_bid(self):
        harness = _SecondPassConditions(sql=False)
        for owner, expected in (
            (SimpleNamespace(measure_base=1), True),
            (SimpleNamespace(measure_base=0), False),
            (SimpleNamespace(measure_base=2), False),
            (None, False),
        ):
            harness.owner = owner
            self.assertIs(harness.handler._is_metric(), expected)

    def test_the_backend_is_asked_about_the_bid_database(self):
        for sql in (True, False):
            harness = _SecondPassConditions(sql=sql)
            self.assertIs(harness.handler._uses_sql_queue(harness.selected), sql)

    def test_capturing_resource_owners_needs_every_resource_to_exist(self):
        harness = _SecondPassConditions(sql=False)
        capture = harness.handler._capture_resource_owners
        resources = {"1": "one", "2": "two"}
        self.assertEqual(capture(resources, [1, "2"]), {"1": "one", "2": "two"})
        self.assertEqual(capture(resources, ["1", "9"]), {})
        self.assertEqual(capture(resources, ["1", ""]), {"1": "one"})
        self.assertEqual(capture(resources, []), {})
        self.assertEqual(capture({"1": None}, ["1"]), {})

    def test_owners_are_current_only_for_the_same_bid_and_identical_objects(self):
        harness = _SecondPassConditions(sql=False)
        one, two = object(), object()
        current = harness.handler._resource_owners_are_current
        ref = harness.selected
        self.assertIs(current(ref, {"1": one, "2": two}, {"1": one, "2": two}), True)
        self.assertIs(current(ref, {"1": one}, {"1": one, "2": two}), True)
        self.assertIs(
            current(ref, {"1": one, "2": two}, {"1": one, "2": object()}), False
        )
        self.assertIs(current(ref, {"1": one}, {}), False)
        self.assertIs(current(ref, {}, {"1": one}), False)
        self.assertIs(current(BidRef("database", "8"), {"1": one}, {"1": one}), False)
        harness.selected = None
        self.assertIs(current(ref, {"1": one}, {"1": one}), False)

    def test_a_bid_owner_is_current_only_while_it_is_selected_and_unreplaced(self):
        harness = _SecondPassConditions(sql=False)
        ref = harness.selected
        owner = harness.owner
        self.assertIs(harness.handler._bid_owner_is_current(ref, owner), True)
        self.assertIs(harness.handler._bid_owner_is_current(ref, None), False)
        self.assertIs(harness.handler._bid_owner_is_current(ref, object()), False)
        self.assertIs(
            harness.handler._bid_owner_is_current(BidRef("database", "8"), owner), False
        )
        harness.owner = None
        self.assertIs(harness.handler._bid_owner_is_current(ref, owner), False)
        self.assertIs(harness.handler._is_current_bid(ref), True)
        self.assertEqual(harness.handler._capture_bid_owner(ref), None)

    def test_interaction_needs_the_current_bid_and_the_matching_right(self):
        harness = _SecondPassConditions(sql=False, allowed={Feature.EDIT_CONDITION})
        ref, owner = harness.selected, harness.owner
        handler = harness.handler
        self.assertIs(
            handler._bid_interaction_still_allowed(ref, owner, Feature.EDIT_CONDITION),
            True,
        )
        self.assertIs(
            handler._bid_interaction_still_allowed(
                ref, owner, Feature.DELETE_CONDITION
            ),
            False,
        )
        self.assertIs(
            handler._bid_interaction_still_allowed(
                ref, object(), Feature.EDIT_CONDITION
            ),
            False,
        )
        self.assertIs(handler._action_still_allowed(ref, Feature.EDIT_CONDITION), True)
        self.assertIs(
            handler._action_still_allowed(ref, Feature.DELETE_CONDITION), False
        )
        self.assertIs(
            handler._action_still_allowed(
                BidRef("database", "8"), Feature.EDIT_CONDITION
            ),
            False,
        )


class ConditionActionHandlerSecondPassEditDialogTests(unittest.TestCase):
    """The Condition Properties dialog: when it opens (and read-only), how it is wired on
    each backend, its lease request and the navigation guard."""

    def _edit(self, harness, uids=("c1",), on_exec=None):
        return _second_pass_open_dialog(
            harness,
            lambda: harness.handler.on_edit_requested(list(uids)),
            on_exec=on_exec,
        )

    def test_nothing_opens_without_input_a_bid_an_owner_a_sidebar_or_known_conditions(
        self,
    ):
        for label, arrange, uids in (
            ("no uids", lambda h: None, ()),
            ("no bid", lambda h: setattr(h, "selected", None), ("c1",)),
            ("bid not loaded", lambda h: setattr(h, "owner", None), ("c1",)),
            (
                "no sidebar",
                lambda h: setattr(h.coordinator, "conditions_sidebar", None),
                ("c1",),
            ),
            ("unknown condition", lambda h: None, ("missing",)),
            (
                "unknown condition in order",
                lambda h: setattr(h, "ordered", ["c1", "x"]),
                ("c1",),
            ),
        ):
            with self.subTest(label):
                harness = _SecondPassConditions(sql=False)
                arrange(harness)
                dialog, executed = self._edit(harness, uids)
                self.assertIsNone(dialog)
                self.assertEqual(
                    (executed, harness.requested, harness.calls), ([], [], [])
                )

    def test_the_edit_right_and_the_lock_decide_whether_the_dialog_opens_read_only(
        self,
    ):
        for label, allowed, locked, license_ok, opens, read_only in (
            ("can edit", {Feature.EDIT_CONDITION}, False, False, True, False),
            (
                "can edit on a locked bid",
                {Feature.EDIT_CONDITION},
                True,
                False,
                True,
                True,
            ),
            ("view only on a locked licensed bid", set(), True, True, True, True),
            ("view only on a locked unlicensed bid", set(), True, False, False, None),
            ("no right on an unlocked bid", set(), False, True, False, None),
        ):
            with self.subTest(label):
                harness = _SecondPassConditions(
                    sql=False, allowed=allowed, license_ok=license_ok
                )
                harness.locked = locked
                dialog, executed = self._edit(harness)
                if not opens:
                    self.assertIsNone(dialog)
                    continue
                self.assertEqual(executed, [dialog])
                self.assertIs(dialog.kwargs["read_only"], read_only)

    def test_the_access_dialog_is_wired_to_the_read_service_and_requests_its_lease(
        self,
    ):
        harness = _SecondPassConditions(sql=False)
        harness.owner = SimpleNamespace(measure_base=1)
        harness.takeoffs = [
            SimpleNamespace(condition_uid="c1"),
            SimpleNamespace(condition_uid="c1"),
        ]
        harness.script["validate_condition_types_delete"] = (
            _SecondPassDeleteValidationResult(requested_uids=["9"], blocked_uids=["9"])
        )
        dialog, executed = self._edit(harness, ("c2", "c1"))
        kwargs = dialog.kwargs
        self.assertEqual(executed, [dialog])
        self.assertEqual(kwargs["icon_provider"], "icons")
        self.assertEqual(kwargs["parent"], "window")
        self.assertIs(kwargs["condition"], harness.conditions["c2"])
        self.assertEqual(kwargs["condition_uids"], ["c1", "c2"])
        self.assertIs(kwargs["conditions_map"], harness.conditions)
        self.assertIs(kwargs["cdn_types"], harness.cdn_types)
        self.assertEqual(
            {
                uid: (layer.name, layer.visible)
                for uid, layer in kwargs["layers"].items()
            },
            {"40": ("Default", True), "41": ("Roads", False)},
        )
        self.assertIs(kwargs["has_takeoffs_fn"]("c1"), True)
        self.assertIs(kwargs["has_takeoffs_fn"]("c2"), False)
        self.assertIsNone(kwargs["save_async_fn"])
        self.assertIsNone(kwargs["condition_type_save_async_fn"])
        self.assertIs(kwargs["metric"], True)
        self.assertIs(kwargs["read_service"], harness.read)
        self.assertEqual(kwargs["condition_type_blocked_delete_uids_fn"](["9"]), {"9"})
        self.assertEqual(
            kwargs["condition_type_reload_fn"](), list(harness.cdn_types.values())
        )
        self.assertIn(("read_cdn_types", "database"), harness.events)
        self.assertIn(("read_layers", "database", "7"), harness.events)
        self.assertTrue(dialog.deleted)
        (lease,) = harness.requested
        self.assertEqual(lease.operation_id, "edit-condition-dialog")
        self.assertEqual(lease.owning_surface, "condition-sidebar")
        self.assertEqual(
            lease.resources,
            (ResourceRef("condition", "c1", 7), ResourceRef("condition", "c2", 7)),
        )

    def test_a_non_numeric_bid_uid_leases_the_conditions_without_a_bid_number(self):
        harness = _SecondPassConditions(sql=False)
        harness.selected = BidRef("database", "bid-x")
        self._edit(harness)
        self.assertEqual(
            harness.requested[0].resources,
            (ResourceRef("condition", "c1"), ResourceRef("condition", "c2")),
        )
        self.assertEqual(
            [r.bid_uid for r in harness.requested[0].resources], [None, None]
        )

    def test_the_sql_dialog_is_wired_to_the_hydrated_state_with_async_saves(self):
        harness = _SecondPassConditions(sql=True)
        dialog, executed = self._edit(harness)
        kwargs = dialog.kwargs
        self.assertEqual(executed, [dialog])
        self.assertIs(kwargs["cdn_types"], harness.cdn_types)
        self.assertEqual(sorted(kwargs["layers"]), ["40", "41"])
        self.assertIsNotNone(kwargs["save_async_fn"])
        self.assertIsNotNone(kwargs["condition_type_save_async_fn"])
        self.assertEqual(kwargs["condition_type_blocked_delete_uids_fn"](["9"]), set())
        self.assertEqual(harness.call("validate_condition_types_delete"), [])
        self.assertNotIn(("read_cdn_types", "database"), harness.events)
        self.assertEqual(len(harness.requested), 1)
        self.assertEqual(
            harness.requested[0].resources,
            (ResourceRef("condition", "c1", 7), ResourceRef("condition", "c2", 7)),
        )
        self.assertEqual(harness.ended, harness.requested)
        self.assertEqual(len(dialog.destroyed.callbacks), 1)

    def test_the_dialog_is_not_executed_when_the_lease_is_denied_or_the_bid_changed(
        self,
    ):
        harness = _SecondPassConditions(sql=False)

        def deny(database_id, resources, callback, **options):
            callback(EditLeaseResult(False, "Another user is editing."))

        harness.coordinator.request_collaboration_edit = deny
        dialog, executed = self._edit(harness)
        self.assertEqual(executed, [])
        self.assertTrue(dialog.deleted)
        harness = _SecondPassConditions(sql=False)

        def grant_after_switch(database_id, resources, callback, **options):
            harness.owner = SimpleNamespace(measure_base=0)
            callback(
                EditLeaseResult(
                    True,
                    handle=EditLeaseHandle(
                        database_id=database_id,
                        draft_id="late",
                        runtime_generation=1,
                        operation_id="edit-condition-dialog",
                        owning_surface="condition-sidebar",
                        resources=tuple(resources),
                    ),
                )
            )

        harness.coordinator.request_collaboration_edit = grant_after_switch
        dialog, executed = self._edit(harness)
        self.assertEqual(executed, [])
        self.assertTrue(dialog.deleted)

    def test_a_denied_sql_lease_closes_the_session_without_executing_the_dialog(self):
        harness = _SecondPassConditions(sql=True)

        def deny(database_id, resources, callback, **options):
            callback(EditLeaseResult(False, "Another user is editing."))

        harness.coordinator.request_collaboration_edit = deny
        dialog, executed = self._edit(harness)
        self.assertEqual(executed, [])
        self.assertEqual(harness.ended, [])
        self.assertTrue(dialog.deleted)

    def test_navigating_inside_the_dialog_highlights_and_re_enters_placement(self):
        harness = _SecondPassConditions(sql=False)
        harness.placement_active = True
        harness.plan_active = True

        def navigate(dialog):
            harness.clear()
            dialog.condition_navigated.emit("c2")

        self._edit(harness, on_exec=navigate)
        self.assertEqual(
            [e for e in harness.events if e[0] in ("highlight", "placement_enter")],
            [("highlight", {"c2"}, True), ("placement_enter", "c2", ["c2"])],
        )
        for placement_active, plan_active in ((False, True), (True, False)):
            harness = _SecondPassConditions(sql=False)
            harness.placement_active = placement_active
            harness.plan_active = plan_active
            self._edit(harness, on_exec=lambda d: d.condition_navigated.emit("c2"))
            self.assertNotIn("placement_enter", harness.event_names())
            self.assertIn("highlight", harness.event_names())

    def test_navigating_after_the_bid_was_replaced_rejects_the_dialog(self):
        harness = _SecondPassConditions(sql=False)

        def navigate(dialog):
            harness.owner = SimpleNamespace(measure_base=0)
            harness.events.clear()
            dialog.condition_navigated.emit("c2")
            self.assertEqual(dialog.rejected, 1)

        dialog, _executed = self._edit(harness, on_exec=navigate)
        self.assertNotIn("highlight", harness.event_names())

    def test_an_access_properties_save_is_refused_after_a_foreign_change(self):
        for label, arrange, error in (
            (
                "access lost",
                lambda h: setattr(h, "allowed", set()),
                "The active bid or edit access changed.",
            ),
            (
                "flush failure",
                lambda h: setattr(h, "flush_ok", False),
                "Failed to save pending visual state.",
            ),
        ):
            with self.subTest(label):
                harness = _SecondPassConditions(sql=False)
                results = []

                def save(dialog, harness=harness, arrange=arrange, results=results):
                    arrange(harness)
                    results.append(
                        dialog.kwargs["save_fn"](
                            "c1", UpdateConditionDto({"name": "N"})
                        )
                    )

                self._edit(harness, on_exec=save)
                self.assertEqual(
                    [(r.success, r.error) for r in results], [(False, error)]
                )
                self.assertEqual(harness.call("update_condition"), [])

    def test_an_access_properties_save_with_a_changed_family_is_reported(self):
        harness = _SecondPassConditions(sql=False)
        results = []

        def save(dialog):
            harness.script["update_condition"] = SimpleNamespace(success=True, error="")
            original_update = harness.write.update_condition

            def update_then_change(*args, **kwargs):
                outcome = original_update(*args, **kwargs)
                harness.conditions["c2"] = replace(
                    harness.conditions["c2"], name="Changed elsewhere"
                )
                return outcome

            harness.write.update_condition = update_then_change
            results.append(
                dialog.kwargs["save_fn"]("c1", UpdateConditionDto({"name": "N"}))
            )

        self._edit(harness, on_exec=save)
        self.assertEqual(
            [(r.success, r.error) for r in results],
            [(False, "The active bid or authoritative Condition family changed.")],
        )
        self.assertEqual([e for e in harness.events if e[0] == "highlight"], [])

    def test_a_sql_properties_save_reports_a_changed_family_without_an_error_dialog(
        self,
    ):
        harness = _SecondPassConditions(sql=True)
        completions = []

        def save(dialog):
            started = dialog.kwargs["save_async_fn"](
                "c1", UpdateConditionDto({"name": "N"}), completions.append
            )
            self.assertTrue(started)
            harness.conditions["c2"] = replace(
                harness.conditions["c2"], name="Elsewhere"
            )
            harness.callbacks[0](harness.result())

        self._edit(harness, on_exec=save)
        (completion,) = completions
        self.assertEqual(
            (completion.success, completion.error, completion.error_presented),
            (False, "The active bid or authoritative Condition family changed.", False),
        )
        self.assertEqual(len(harness.requested), 2)

    def test_a_sql_properties_save_that_is_refused_before_queueing_reports_why(self):
        for label, arrange, error in (
            (
                "access",
                lambda h: setattr(h, "allowed", set()),
                "The active bid or edit access changed.",
            ),
            (
                "flush",
                lambda h: setattr(h, "flush_ok", False),
                "Failed to save pending visual state.",
            ),
        ):
            with self.subTest(label):
                harness = _SecondPassConditions(sql=True)
                completions, started = [], []

                def save(dialog, harness=harness, arrange=arrange):
                    arrange(harness)
                    started.append(
                        dialog.kwargs["save_async_fn"](
                            "c1", UpdateConditionDto({"name": "N"}), completions.append
                        )
                    )

                self._edit(harness, on_exec=save)
                self.assertEqual(started, [False])
                self.assertEqual(
                    [(c.success, c.error) for c in completions], [(False, error)]
                )
                self.assertEqual(harness.call("queue_conditions_update"), [])

    def test_a_sql_properties_save_queues_with_the_lease_key_and_title(self):
        harness = _SecondPassConditions(sql=True)
        completions = []

        def save(dialog):
            dialog.kwargs["save_async_fn"](
                "c1",
                UpdateConditionDto({"name": "N", "notes": "x"}),
                completions.append,
            )
            args, kwargs = harness.call("queue_conditions_update")[0]
            self.assertEqual(
                args, ("database", "7", ["c1"], {"name": "N", "notes": "x"})
            )
            self.assertIs(kwargs["edit_lease_handle"], harness.requested[0])
            self.assertEqual(
                harness.handler._pending_sql_operations,
                {("database", "7", "edit_condition", "c1")},
            )
            harness.callbacks[0](
                harness.result(MutationOutcomeStatus.CONFLICT, message="stale")
            )

        self._edit(harness, on_exec=save)
        self.assertEqual(
            [(c.success, c.error, c.error_presented) for c in completions],
            [(False, "stale", True)],
        )
        self.assertEqual(
            [e[2] for e in harness.events if e[0] == "present_error"],
            ["Save Condition"],
        )


from ost_visualizer.application.dtos.create_condition_result import (
    CreatedConditionProjection,
)


class ConditionActionHandlerSecondPassCreateDefaultsTests(unittest.TestCase):
    """The defaults of a new Condition and the ownership checks around its creation."""

    def _open(self, harness, folder_uid="", on_exec=None):
        return _second_pass_open_dialog(
            harness,
            lambda: harness.handler.on_create_requested(folder_uid),
            on_exec=on_exec,
        )

    def test_the_new_condition_dialog_starts_from_the_documented_defaults(self):
        from ost_visualizer.domain.entities.pattern import TRANSPARENT

        harness = _SecondPassConditions(sql=False)
        dialog, _executed = self._open(harness)
        synthetic = dialog.kwargs["condition"]
        self.assertEqual(
            {
                field: getattr(synthetic, field)
                for field in (
                    "uid",
                    "name",
                    "condition_type",
                    "thickness",
                    "pattern",
                    "display_size",
                    "width",
                    "height",
                    "depth",
                    "rise",
                    "run",
                    "spacing",
                    "color_fill",
                    "shape",
                    "layer_uid",
                    "uom1",
                    "uom2",
                    "uom3",
                    "calc_type1",
                    "calc_type2",
                    "calc_type3",
                    "round_up",
                    "drop_run",
                    "drop_value",
                    "round_quantity",
                    "grid",
                    "grid_size1",
                    "grid_size2",
                    "gap",
                    "trim",
                    "is_curved_segment",
                    "display_dimension",
                    "display_name",
                    "display_grid_while_drawing",
                )
            },
            {
                "uid": "__new__",
                "name": "",
                "condition_type": Condition.TYPE_LINEAR,
                "thickness": 4.0,
                "pattern": TRANSPARENT,
                "display_size": 100.0,
                "width": 12.0,
                "height": 0.0,
                "depth": 0.0,
                "rise": 0.0,
                "run": 0.0,
                "spacing": 4.0,
                "color_fill": 13353215,
                "shape": -1,
                "layer_uid": "40",
                "uom1": 2,
                "uom2": -1,
                "uom3": -1,
                "calc_type1": 1,
                "calc_type2": 0,
                "calc_type3": 0,
                "round_up": 0.0,
                "drop_run": False,
                "drop_value": 0.0,
                "round_quantity": False,
                "grid": False,
                "grid_size1": 0.0,
                "grid_size2": 0.0,
                "gap": 0.0,
                "trim": False,
                "is_curved_segment": False,
                "display_dimension": False,
                "display_name": False,
                "display_grid_while_drawing": False,
            },
        )
        harness = _SecondPassConditions(sql=False)
        harness.layers = harness.layers[1:]
        dialog, _executed = self._open(harness)
        self.assertIsNone(dialog.kwargs["condition"].layer_uid)

    def test_the_default_layer_is_the_first_layer_named_default(self):
        harness = _SecondPassConditions(sql=False)
        harness.layers = [
            BidLayer(uid="50", bid_uid="7", name="Roads", sequence=1, show=True),
            BidLayer(uid="51", bid_uid="7", name="Default", sequence=2, show=True),
            BidLayer(uid="52", bid_uid="7", name="Default", sequence=3, show=True),
        ]
        dialog, _executed = self._open(harness)
        self.assertEqual(dialog.kwargs["condition"].layer_uid, "51")

    def test_an_unknown_condition_type_falls_back_to_the_plain_spec_defaults(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["create_condition_result"] = _SecondPassCreateConditionResult(
            "n1", True, True
        )
        harness.conditions["n1"] = Condition(uid="n1", name="New")
        self._open(
            harness,
            on_exec=lambda dialog: dialog.kwargs["save_fn"](
                "__new__", UpdateConditionDto({"condition_type": 99})
            ),
        )
        spec = harness.call("create_condition_result")[0][0][2]
        self.assertEqual(
            (
                spec.condition_type,
                spec.name,
                spec.thickness,
                spec.spacing,
                spec.shape,
                spec.uom1,
                spec.calc_type1,
                spec.display_grid_while_drawing,
                spec.backout,
                spec.display_dimension,
                spec.color_fill,
                spec.layer_uid,
            ),
            (99, "Untitled", 4.0, 4.0, -1, 0, 0, False, False, False, 13353215, "40"),
        )
        self.assertEqual(spec.pattern, 8)
        self.assertIsNone(spec.folder_uid)

    def _projection_run(self, *, folder_uid, mutate):
        harness = _SecondPassConditions(sql=False)
        replacement = SimpleNamespace(measure_base=0)
        new_condition = Condition(uid="n1", name="New")
        facts = {
            "previous": harness.owner,
            "bid": replacement,
            "condition": new_condition,
            "folder": "current" if folder_uid else None,
        }
        mutate(facts)

        def create(*args, **kwargs):
            harness.calls.append(("create_condition_result", args, kwargs))
            harness.owner = replacement
            harness.conditions = {**harness.conditions, "n1": new_condition}
            if folder_uid:
                harness.folders = {"f1": replace(harness.folders["f1"])}
            folder = facts["folder"]
            return _SecondPassCreateConditionResult(
                "n1",
                True,
                True,
                projection=CreatedConditionProjection(
                    previous_bid=facts["previous"],
                    bid=facts["bid"],
                    condition=facts["condition"],
                    folder=harness.folders["f1"] if folder == "current" else folder,
                ),
            )

        harness.write.create_condition_result = create
        self._open(
            harness,
            folder_uid=folder_uid,
            on_exec=lambda dialog: dialog.kwargs["save_fn"](
                "__new__", UpdateConditionDto({})
            ),
        )
        return [e for e in harness.events if e[0] == "highlight"]

    def test_a_created_condition_is_only_highlighted_for_a_matching_projection(self):
        cases = (
            ("consistent", "", lambda f: None, True),
            ("consistent in a folder", "f1", lambda f: None, True),
            (
                "a different previous bid",
                "",
                lambda f: f.update(previous=object()),
                False,
            ),
            (
                "a projected bid that is not current",
                "",
                lambda f: f.update(bid=object()),
                False,
            ),
            (
                "another condition object",
                "",
                lambda f: f.update(condition=Condition(uid="n1", name="Other")),
                False,
            ),
            (
                "another folder object",
                "f1",
                lambda f: f.update(folder=BidConditionFolder(uid="f1", name="Other")),
                False,
            ),
        )
        for label, folder_uid, mutate, highlighted in cases:
            with self.subTest(label):
                events = self._projection_run(folder_uid=folder_uid, mutate=mutate)
                self.assertEqual(
                    events, [("highlight", {"n1"}, True)] if highlighted else []
                )

    def test_a_sql_commit_after_the_bid_was_replaced_completes_without_highlighting(
        self,
    ):
        harness = _SecondPassConditions(sql=True)
        results = []

        def on_exec(dialog):
            dialog.kwargs["save_async_fn"](
                "__new__", UpdateConditionDto({}), results.append
            )
            harness.owner = SimpleNamespace(measure_base=0)
            harness.conditions["n1"] = Condition(uid="n1", name="New")
            harness.callbacks[0](
                harness.result(
                    authoritative_result=AuthoritativeMutationResult(
                        created_resource_ids=("n1",)
                    )
                )
            )

        _second_pass_open_dialog(
            harness, lambda: harness.handler.on_create_requested(""), on_exec=on_exec
        )
        self.assertEqual([(r.success, r.error) for r in results], [(True, None)])
        self.assertEqual([e for e in harness.events if e[0] == "highlight"], [])

    def test_a_sql_commit_in_a_folder_whose_value_changed_does_not_highlight(self):
        for changed, expected in ((False, [("highlight", {"n1"}, True)]), (True, [])):
            with self.subTest(changed=changed):
                harness = _SecondPassConditions(sql=True)

                def on_exec(dialog, harness=harness, changed=changed):
                    dialog.kwargs["save_async_fn"](
                        "__new__", UpdateConditionDto({}), lambda result: None
                    )
                    harness.conditions["n1"] = Condition(uid="n1", name="New")
                    harness.folders = {
                        "f1": replace(
                            harness.folders["f1"],
                            name="Changed" if changed else "Folder 1",
                        )
                    }
                    harness.callbacks[0](
                        harness.result(
                            authoritative_result=AuthoritativeMutationResult(
                                created_resource_ids=("n1",)
                            )
                        )
                    )

                _second_pass_open_dialog(
                    harness,
                    lambda: harness.handler.on_create_requested("f1"),
                    on_exec=on_exec,
                )
                self.assertEqual(
                    [e for e in harness.events if e[0] == "highlight"], expected
                )


from shiboken6 import delete as _second_pass_delete_qobject


class ConditionActionHandlerSecondPassSurvivorTests(unittest.TestCase):
    """Cases the first sweep of the added tests left unobserved: stale owners that are
    None, empty-string targets, missing results, stale Plan contexts and the checks
    after the New Condition dialog closed."""

    def _paste(self, harness, uids, target):
        with harness.patched(), patch(f"{_COND_MODULE}.logger") as logger:
            harness.handler.on_paste_requested(uids, target)
        return logger

    def test_a_missing_owner_is_never_current_even_when_the_bid_is_not_loaded(self):
        harness = _SecondPassConditions(sql=False)
        harness.owner = None
        self.assertIs(
            harness.handler._bid_owner_is_current(harness.selected, None), False
        )
        self.assertIs(harness.handler._is_current_bid(harness.selected), True)

    def test_a_layer_insert_with_a_value_but_no_successful_write_returns_nothing(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["insert_layer_result"] = WriteReloadResult("41", False, True)
        with harness.patched():
            callbacks = harness.handler._layer_dialog_callbacks(
                harness.selected, harness.write
            )
            self.assertIsNone(callbacks["layer_insert_fn"]("Streets", 1))
        harness.warning.assert_not_called()

    def test_a_deleted_sidebar_or_a_replaced_bid_suppresses_the_follow_up_after_create(
        self,
    ):
        for label, arrange, expect_warning in (
            ("control", lambda h, d: None, True),
            (
                "sidebar deleted",
                lambda h, d: _second_pass_delete_qobject(
                    h.coordinator.conditions_sidebar
                ),
                False,
            ),
            (
                "bid replaced",
                lambda h, d: setattr(h, "owner", SimpleNamespace(measure_base=0)),
                False,
            ),
        ):
            with self.subTest(label):
                harness = _SecondPassConditions(sql=False)
                harness.script["create_condition_result"] = (
                    _SecondPassCreateConditionResult("n1", True, False)
                )
                harness.conditions["n1"] = Condition(uid="n1", name="New")

                def on_exec(dialog, harness=harness, arrange=arrange):
                    dialog.kwargs["save_fn"]("__new__", UpdateConditionDto({}))
                    arrange(harness, dialog)

                _second_pass_open_dialog(
                    harness,
                    lambda: harness.handler.on_create_requested(""),
                    on_exec=on_exec,
                )
                self.assertEqual(harness.warning.call_count, int(expect_warning))
                self.assertEqual([e for e in harness.events if e[0] == "highlight"], [])

    def test_a_created_condition_missing_or_replaced_in_project_data_is_not_highlighted(
        self,
    ):
        for label, at_save, afterwards in (
            ("control", True, None),
            ("absent at save", False, None),
            ("replaced afterwards", True, "replace"),
            ("removed afterwards", True, "remove"),
        ):
            with self.subTest(label):
                harness = _SecondPassConditions(sql=False)
                harness.script["create_condition_result"] = (
                    _SecondPassCreateConditionResult("n1", True, True)
                )

                def on_exec(
                    dialog, harness=harness, at_save=at_save, afterwards=afterwards
                ):
                    if at_save:
                        harness.conditions["n1"] = Condition(uid="n1", name="New")
                    dialog.kwargs["save_fn"]("__new__", UpdateConditionDto({}))
                    if afterwards == "replace":
                        harness.conditions["n1"] = Condition(uid="n1", name="Other")
                    elif afterwards == "remove":
                        harness.conditions.pop("n1")

                _second_pass_open_dialog(
                    harness,
                    lambda: harness.handler.on_create_requested(""),
                    on_exec=on_exec,
                )
                highlights = [e for e in harness.events if e[0] == "highlight"]
                self.assertEqual(
                    highlights,
                    [("highlight", {"n1"}, True)] if label == "control" else [],
                )

    def test_a_stale_plan_context_stops_a_duplicate_on_both_backends(self):
        for sql in (True, False):
            with self.subTest(sql=sql):
                harness = _SecondPassConditions(sql=sql)
                harness.script["duplicate_conditions_result"] = WriteReloadResult(
                    ["n1"], True, True
                )
                with harness.patched(), patch(f"{_COND_MODULE}.logger"):
                    harness.handler.on_duplicate_requested(
                        ["c1"], context_is_current=lambda: False
                    )
                self.assertEqual(harness.calls, [])
                with harness.patched(), patch(f"{_COND_MODULE}.logger"):
                    harness.handler.on_duplicate_requested(
                        ["c1"], context_is_current=lambda: True
                    )
                self.assertEqual(len(harness.calls), 1)

    def test_sql_paste_stops_when_pending_changes_cannot_be_saved_or_the_bid_is_gone(
        self,
    ):
        targets = (
            {"kind": "root"},
            {"kind": "root", "cut": True, "clipboard_revision": 1},
        )
        for target in targets:
            for label, arrange in (
                ("flush", lambda h: setattr(h, "flush_ok", False)),
                ("owner", lambda h: setattr(h, "owner", None)),
            ):
                with self.subTest(label, cut=bool(target.get("cut"))):
                    harness = _SecondPassConditions(sql=True)
                    arrange(harness)
                    self._paste(harness, ["c1"], target)
                    self.assertEqual(harness.calls, [])

    def test_access_paste_without_a_value_or_with_empty_targets_writes_exactly_none(
        self,
    ):
        harness = _SecondPassConditions(sql=False)
        harness.script["duplicate_conditions_result"] = WriteReloadResult(
            None, False, False
        )
        logger = self._paste(harness, ["c1"], {"kind": "root"})
        self.assertEqual(harness.call("update_condition"), [])
        logger.warning.assert_called_once()
        harness = _SecondPassConditions(sql=False, sidebar=False)
        harness.script["duplicate_conditions_result"] = WriteReloadResult(
            None, False, False
        )
        with harness.patched(), patch(f"{_COND_MODULE}.logger") as logger:
            harness.handler.on_duplicate_requested(["c1"])
        logger.warning.assert_called_once()
        harness = _SecondPassConditions(sql=False)
        harness.script["duplicate_conditions_result"] = WriteReloadResult(
            ["n1"], True, True
        )
        self._paste(
            harness,
            ["c1"],
            {"kind": "cdn_type", "folder_uid": "", "cdn_type_uid": ""},
        )
        ((args, _kwargs),) = harness.call("update_condition")
        self.assertEqual(
            args[3].get_changes(), {"folder_uid": None, "cdn_type_uid": None}
        )
        harness = _SecondPassConditions(sql=False)
        self._paste(
            harness,
            ["c1"],
            {
                "kind": "cdn_type",
                "folder_uid": "",
                "cdn_type_uid": "",
                "cut": True,
                "clipboard_revision": 1,
            },
        )
        ((args, _kwargs),) = harness.call("update_condition")
        self.assertEqual(
            args[3].get_changes(), {"folder_uid": None, "cdn_type_uid": None}
        )

    def test_the_condition_dialog_survives_a_sql_save_when_its_owner_check_still_holds(
        self,
    ):
        harness = _SecondPassConditions(sql=True)
        completions = []

        def save(dialog):
            dialog.kwargs["save_async_fn"](
                "c1", UpdateConditionDto({"name": "N"}), completions.append
            )
            harness.callbacks[0](harness.result())

        _second_pass_open_dialog(
            harness, lambda: harness.handler.on_edit_requested(["c1"]), on_exec=save
        )
        self.assertEqual(
            [(c.success, c.error, c.error_presented) for c in completions],
            [(True, "", False)],
        )
        self.assertEqual(
            [e for e in harness.events if e[0] == "highlight"],
            [("highlight", {"c1"}, True)],
        )


from ost_visualizer.application.dtos.collaboration_dtos import EditLeaseLoss
from ost_visualizer.application.events.app_events import AppEvents


class ConditionActionHandlerSecondPassRound3Tests(unittest.TestCase):
    """Survivors of the second sweep: per-type creation defaults, ownership
    reconciliation with an unchanged Bid, guards that precede confirmations, the SQL
    edit dialog's lease/ownership completion and exact failure texts."""

    def _create(self, harness, folder_uid="", on_exec=None):
        return _second_pass_open_dialog(
            harness,
            lambda: harness.handler.on_create_requested(folder_uid),
            on_exec=on_exec,
        )

    def _edit(self, harness, uids=("c1",), on_exec=None):
        return _second_pass_open_dialog(
            harness,
            lambda: harness.handler.on_edit_requested(list(uids)),
            on_exec=on_exec,
        )

    def test_every_condition_type_creates_its_own_default_spec(self):
        expected = {
            0: (4.0, 4.0, -1, 2, 1, False, False),
            1: (4.0, 6.0, -1, 5, 11, False, True),
            2: (4.0, 4.0, 0, 0, 23, True, False),
            3: (0.0, 4.0, 0, 0, 23, True, False),
        }
        for condition_type, values in expected.items():
            with self.subTest(condition_type=condition_type):
                harness = _SecondPassConditions(sql=False)
                harness.script["create_condition_result"] = (
                    _SecondPassCreateConditionResult("n1", True, True)
                )
                harness.conditions["n1"] = Condition(uid="n1", name="New")
                self._create(
                    harness,
                    on_exec=lambda dialog, t=condition_type: dialog.kwargs["save_fn"](
                        "__new__", UpdateConditionDto({"condition_type": t})
                    ),
                )
                spec = harness.call("create_condition_result")[0][0][2]
                self.assertEqual(
                    (
                        spec.thickness,
                        spec.spacing,
                        spec.shape,
                        spec.uom1,
                        spec.calc_type1,
                        spec.backout,
                        spec.display_grid_while_drawing,
                    ),
                    values,
                )

    def test_the_create_command_works_without_a_folder_argument(self):
        harness = _SecondPassConditions(sql=False)
        _second_pass_open_dialog(harness, lambda: harness.handler.on_create_requested())
        self.assertIsNotNone(_SecondPassConditionDialog.instance)

    def test_a_create_result_with_a_value_but_no_successful_write_is_a_failure(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["create_condition_result"] = _SecondPassCreateConditionResult(
            "n1", False, True
        )
        results = []
        self._create(
            harness,
            on_exec=lambda dialog: results.append(
                dialog.kwargs["save_fn"]("__new__", UpdateConditionDto({}))
            ),
        )
        self.assertEqual(
            [(r.success, r.error) for r in results],
            [(False, "Failed to create condition.")],
        )

    def test_the_create_save_is_refused_when_the_bid_or_the_folder_object_was_replaced(
        self,
    ):
        def replace_bid(harness):
            harness.owner = SimpleNamespace(measure_base=0)

        def replace_folder(harness):
            harness.folders = {"f1": replace(harness.folders["f1"])}

        for sql in (False, True):
            for label, arrange, folder_uid in (
                ("bid", replace_bid, ""),
                ("folder", replace_folder, "f1"),
            ):
                with self.subTest(sql=sql, replaced=label):
                    harness = _SecondPassConditions(sql=sql)
                    results = []

                    def on_exec(
                        dialog,
                        harness=harness,
                        arrange=arrange,
                        results=results,
                        sql=sql,
                    ):
                        arrange(harness)
                        dto = UpdateConditionDto({})
                        if sql:
                            dialog.kwargs["save_async_fn"](
                                "__new__", dto, results.append
                            )
                        else:
                            results.append(dialog.kwargs["save_fn"]("__new__", dto))

                    self._create(harness, folder_uid=folder_uid, on_exec=on_exec)
                    self.assertEqual(
                        [(r.success, r.error) for r in results],
                        [(False, "The active bid or edit access changed.")],
                    )
                    self.assertEqual(harness.calls, [])

    def _projection_case(self, *, folder_uid, mutate, after_save=None):
        harness = _SecondPassConditions(sql=False)
        new_condition = Condition(uid="n1", name="New")
        facts = {
            "condition": new_condition,
            "folder": "current" if folder_uid else None,
        }
        mutate(facts)

        def create(*args, **kwargs):
            harness.calls.append(("create_condition_result", args, kwargs))
            harness.conditions = {**harness.conditions, "n1": new_condition}
            if folder_uid:
                harness.folders = {"f1": replace(harness.folders["f1"])}
            folder = facts["folder"]
            return _SecondPassCreateConditionResult(
                "n1",
                True,
                True,
                projection=CreatedConditionProjection(
                    previous_bid=harness.owner,
                    bid=harness.owner,
                    condition=facts["condition"],
                    folder=harness.folders["f1"] if folder == "current" else folder,
                ),
            )

        harness.write.create_condition_result = create

        def on_exec(dialog):
            dialog.kwargs["save_fn"]("__new__", UpdateConditionDto({}))
            if after_save is not None:
                after_save(harness)

        self._create(harness, folder_uid=folder_uid, on_exec=on_exec)
        return [e for e in harness.events if e[0] == "highlight"]

    def test_a_projection_on_an_unchanged_bid_still_checks_condition_and_folder_identity(
        self,
    ):
        highlighted = [("highlight", {"n1"}, True)]
        cases = (
            ("consistent", "", lambda f: None, None, highlighted),
            (
                "a folder given for a root create",
                "",
                lambda f: f.update(folder=BidConditionFolder(uid="f9", name="x")),
                None,
                highlighted,
            ),
            ("consistent in a folder", "f1", lambda f: None, None, highlighted),
            (
                "another condition object",
                "",
                lambda f: f.update(condition=Condition(uid="n1", name="Other")),
                None,
                [],
            ),
            (
                "another folder object",
                "f1",
                lambda f: f.update(folder=BidConditionFolder(uid="f1", name="Other")),
                None,
                [],
            ),
            (
                "the folder changed value afterwards",
                "f1",
                lambda f: None,
                lambda h: h.folders.update(
                    {"f1": replace(h.folders["f1"], name="Renamed")}
                ),
                [],
            ),
            (
                "the folder vanished afterwards",
                "f1",
                lambda f: None,
                lambda h: h.folders.clear(),
                [],
            ),
        )
        for label, folder_uid, mutate, after_save, expected in cases:
            with self.subTest(label):
                self.assertEqual(
                    self._projection_case(
                        folder_uid=folder_uid, mutate=mutate, after_save=after_save
                    ),
                    expected,
                )

    def test_a_bid_replaced_during_the_save_and_restored_is_not_trusted(self):
        harness = _SecondPassConditions(sql=False)
        original = harness.owner
        harness.conditions["n1"] = Condition(uid="n1", name="New")

        def create(*args, **kwargs):
            harness.calls.append(("create_condition_result", args, kwargs))
            harness.owner = SimpleNamespace(measure_base=0)
            return _SecondPassCreateConditionResult("n1", True, True)

        harness.write.create_condition_result = create

        def on_exec(dialog):
            dialog.kwargs["save_fn"]("__new__", UpdateConditionDto({}))
            harness.owner = original

        self._create(harness, on_exec=on_exec)
        self.assertEqual([e for e in harness.events if e[0] == "highlight"], [])

    def test_commands_stop_before_asking_when_their_guards_fail(self):
        harness = _SecondPassConditions(sql=False, allowed=set())
        with harness.patched():
            harness.handler.on_renumber_requested()
        harness.confirm.assert_not_called()
        harness = _SecondPassConditions(sql=False)
        harness.conditions = {}
        with harness.patched():
            harness.handler.on_renumber_requested()
        harness.confirm.assert_not_called()
        harness = _SecondPassConditions(sql=False)
        harness.ordered = ["c1", "unknown"]
        with harness.patched():
            harness.handler.on_renumber_requested()
        harness.confirm.assert_not_called()
        harness = _SecondPassConditions(sql=False)
        harness.ordered = []
        with harness.patched():
            harness.handler.on_renumber_requested()
        harness.confirm.assert_not_called()
        for uids in ([], ["missing"]):
            harness = _SecondPassConditions(sql=False)
            with harness.patched():
                harness.handler.on_folder_delete_requested(uids)
            self.assertEqual(harness.event_names().count("flush"), 0 if not uids else 1)
            self.assertEqual(harness.calls, [])
            harness.confirm_multi.assert_not_called()

    def test_sql_delete_and_create_folder_need_a_loaded_bid(self):
        harness = _SecondPassConditions(sql=True)
        harness.owner = None
        with harness.patched():
            harness.handler.on_delete_requested(["c1"])
            harness.handler.on_create_folder_requested("")
        self.assertEqual(harness.calls, [])

    def test_a_folder_create_with_a_value_but_no_write_is_a_failure(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["create_condition_folder_result"] = WriteReloadResult(
            "f9", False, True
        )
        with harness.patched(), patch(f"{_COND_MODULE}.logger") as logger:
            harness.handler.on_create_folder_requested("")
        logger.warning.assert_called_once()
        self.assertNotIn("pending_folder_edit", harness.event_names())

    def test_the_failure_titles_of_the_remaining_sql_commands(self):
        cases = (
            ("Delete Conditions", lambda h: h.on_delete_requested(["c1"])),
            ("Create Condition Folder", lambda h: h.on_create_folder_requested("")),
            ("Rename Condition", lambda h: h.on_condition_renamed("c1", "N")),
            ("Move Condition", lambda h: h.on_move_condition_to_folder("c1", "f1")),
        )
        for title, run in cases:
            with self.subTest(title):
                harness = _SecondPassConditions(sql=True)
                with harness.patched():
                    run(harness.handler)
                harness.callbacks[0](harness.result(MutationOutcomeStatus.REJECTED))
                self.assertEqual(
                    [e[2] for e in harness.events if e[0] == "present_error"], [title]
                )

    def test_an_access_paste_with_a_failed_refresh_warns_with_the_duplicated_text(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["duplicate_conditions_result"] = WriteReloadResult(
            ["n1"], True, False
        )
        with harness.patched(), patch(f"{_COND_MODULE}.logger"):
            harness.handler.on_paste_requested(["c1"], {"kind": "root"})
        harness.warning.assert_called_once_with(
            "window",
            "Refresh Error",
            "The condition was duplicated, but the conditions list could not be "
            "refreshed. Reopen the database to see the latest conditions.",
        )

    def test_the_sql_edit_dialog_reloads_types_from_project_data_and_leases_as_the_sidebar(
        self,
    ):
        harness = _SecondPassConditions(sql=True)
        dialog, _executed = self._edit(harness)
        harness.events.clear()
        self.assertEqual(
            dialog.kwargs["condition_type_reload_fn"](),
            list(harness.cdn_types.values()),
        )
        self.assertEqual(harness.events, [("data_cdn_types",)])
        (lease,) = harness.requested
        self.assertEqual(lease.operation_id, "edit-condition-dialog")
        self.assertEqual(lease.owning_surface, "condition-sidebar")

    def test_a_lost_lease_rejects_the_sql_edit_dialog(self):
        harness = _SecondPassConditions(sql=True)

        def lose(dialog):
            lease = harness.requested[0]
            harness.coordinator.event_bus.publish(
                AppEvents.EDIT_LEASE_LOST,
                loss=EditLeaseLoss(
                    database_id=lease.database_id,
                    draft_id=lease.draft_id,
                    runtime_generation=lease.runtime_generation,
                    operation_id=lease.operation_id,
                    owning_surface=lease.owning_surface,
                    resources=lease.resources,
                    reason="expired",
                ),
            )

        dialog, _executed = self._edit(harness, on_exec=lose)
        self.assertEqual(dialog.rejected, 1)

    def test_an_invalid_dialog_is_not_executed(self):
        harness = _SecondPassConditions(sql=False)

        def only_other_objects_are_valid(obj):
            return not isinstance(obj, _SecondPassConditionDialog)

        with patch(f"{_COND_MODULE}.isValid", side_effect=only_other_objects_are_valid):
            dialog, executed = self._edit(harness)
        self.assertEqual(executed, [])

    def test_the_sql_properties_save_is_refused_when_a_condition_object_was_replaced(
        self,
    ):
        harness = _SecondPassConditions(sql=True)
        completions, started = [], []

        def save(dialog):
            harness.conditions["c2"] = replace(harness.conditions["c2"])
            started.append(
                dialog.kwargs["save_async_fn"](
                    "c1", UpdateConditionDto({"name": "N"}), completions.append
                )
            )

        self._edit(harness, on_exec=save)
        self.assertEqual(started, [False])
        self.assertEqual(
            [(c.success, c.error) for c in completions],
            [(False, "The active bid or edit access changed.")],
        )

    def test_a_second_sql_save_while_one_is_pending_completes_without_an_error_text(
        self,
    ):
        harness = _SecondPassConditions(sql=True)
        completions, started = [], []

        def save(dialog):
            dto = UpdateConditionDto({"name": "N"})
            started.append(
                dialog.kwargs["save_async_fn"]("c1", dto, completions.append)
            )
            started.append(
                dialog.kwargs["save_async_fn"]("c1", dto, completions.append)
            )

        self._edit(harness, on_exec=save)
        self.assertEqual(started, [True, False])
        self.assertEqual(
            [(c.success, c.error, c.error_presented) for c in completions],
            [(False, "", True)],
        )

    def test_a_sql_save_success_needs_both_the_reconciled_family_and_the_current_owners(
        self,
    ):
        results = {}
        for label, arrange in (
            ("control", lambda h: None),
            (
                "another condition mutated in place",
                lambda h: setattr(h.conditions["c2"], "name", "Elsewhere"),
            ),
        ):
            harness = _SecondPassConditions(sql=True)
            completions = []

            def save(dialog, harness=harness, arrange=arrange, completions=completions):
                dialog.kwargs["save_async_fn"](
                    "c1", UpdateConditionDto({"name": "N"}), completions.append
                )
                arrange(harness)
                harness.callbacks[0](harness.result())

            dialog, _executed = self._edit(harness, ("c1",), on_exec=save)
            results[label] = (
                [(c.success, c.error_presented) for c in completions],
                list(dialog.refreshed),
            )
        self.assertEqual(results["control"][0], [(True, False)])
        self.assertEqual(len(results["control"][1]), 1)
        self.assertEqual(
            results["another condition mutated in place"], ([(False, False)], [])
        )

    def test_a_sql_save_whose_bid_is_replaced_during_the_lease_handover_fails(self):
        harness = _SecondPassConditions(sql=True)
        completions = []
        original_request = harness.coordinator.request_collaboration_edit

        def save(dialog):
            dialog.kwargs["save_async_fn"](
                "c1", UpdateConditionDto({"name": "N"}), completions.append
            )

            def replace_then_grant(*args, **kwargs):
                harness.owner = SimpleNamespace(measure_base=0)
                return original_request(*args, **kwargs)

            harness.coordinator.request_collaboration_edit = replace_then_grant
            harness.callbacks[0](harness.result())

        self._edit(harness, on_exec=save)
        self.assertEqual(
            [(c.success, c.error, c.error_presented) for c in completions],
            [
                (
                    False,
                    "The active bid or authoritative Condition family changed.",
                    False,
                )
            ],
        )

    def test_the_access_properties_save_checks_the_saved_and_the_other_conditions(self):
        def run(change):
            harness = _SecondPassConditions(sql=False)
            results = []
            real = harness.write.update_condition

            def update(*args, **kwargs):
                outcome = real(*args, **kwargs)
                change(harness)
                return outcome

            harness.write.update_condition = update
            self._edit(
                harness,
                on_exec=lambda dialog: results.append(
                    dialog.kwargs["save_fn"]("c1", UpdateConditionDto({"name": "N"}))
                ),
            )
            return results[0].success

        self.assertIs(run(lambda h: None), True)
        self.assertIs(
            run(
                lambda h: h.conditions.update(
                    {"c1": replace(h.conditions["c1"], name="N")}
                )
            ),
            True,
        )
        self.assertIs(run(lambda h: h.conditions.pop("c1")), False)
        self.assertIs(run(lambda h: h.conditions.pop("c2")), False)
        self.assertIs(
            run(
                lambda h: h.conditions.update(
                    {"c2": replace(h.conditions["c2"], name="X")}
                )
            ),
            False,
        )
        self.assertIs(
            run(lambda h: setattr(h, "owner", SimpleNamespace(measure_base=0))), False
        )


def _second_pass_unexpected_modal(name):
    def refuse(*_args, **_kwargs):
        raise AssertionError(
            f"unexpected modal call {name}: patch it in the test that expects it"
        )

    return refuse


_second_pass_modal_guards = []


def setUpModule():
    """A regression that reaches a real modal dialog fails fast instead of hanging the
    whole run (a stuck QMessageBox freezes the test process); tests that expect a
    dialog patch it themselves, which takes precedence over this module default."""
    for name in (
        "show_warning",
        "confirm",
        "confirm_delete_conditions",
        "confirm_multi_delete",
        "exec_with_ost_blocking",
    ):
        guard = patch(
            "ost_visualizer.presentation.handlers.condition_action_handler." + name,
            side_effect=_second_pass_unexpected_modal(name),
        )
        guard.start()
        _second_pass_modal_guards.append(guard)


def tearDownModule():
    while _second_pass_modal_guards:
        _second_pass_modal_guards.pop().stop()


import shiboken6 as _sp4_shiboken


class _Sp4Plan(QtCore.QObject):
    """A recording stand-in for the Plan view: only what the reassignment guards read.
    The context-menu owner is a (token, page object) pair like the real one."""

    def __init__(self):
        super().__init__()
        self.selection_revision = 3
        self.tool_revision = 5
        self.current_page_uid = "page-1"
        self.page_object = SimpleNamespace(uid="page-1")
        self.owner_token = object()
        self.owner_current = True

    def _context_menu_owner(self):
        return (self.owner_token, self.page_object)

    def _context_menu_owner_is_current(self, owner):
        return self.owner_current and owner[0] is self.owner_token


class _Sp4PlanViewHandler:
    def __init__(self):
        self.prepared = []
        self.completed = []
        self.aborted = 0
        self.recorded = []
        self.on_complete = None

    def prepare_sql_property_completion(self, *args, **kwargs):
        self.prepared.append((args, kwargs))
        return self._complete, self._abort

    def _complete(self, result):
        self.completed.append(result)
        if self.on_complete is not None:
            self.on_complete()

    def _abort(self):
        self.aborted += 1

    def record_local_condition_reassignment(self, bid_ref, old_updates, new_updates):
        self.recorded.append((bid_ref, old_updates, new_updates))


def _sp4_reassignment_harness(sql, sidebar=True):
    harness = _SecondPassConditions(sql=sql, sidebar=sidebar)
    plan = _Sp4Plan()
    plan_handler = _Sp4PlanViewHandler()
    harness.plan = plan
    harness.plan_handler = plan_handler
    harness.coordinator.plan_view = plan
    harness.coordinator._plan_view_handler = plan_handler
    harness.data.get_page = lambda uid: (
        harness.plan.page_object if uid == "page-1" else None
    )
    harness.ui.active_page_uid = "page-1"
    return harness


_SP4_REASSIGN = ConditionTakeoffReassignment(
    condition_uid="c1", takeoff_uids=("t1", "t2"), page_uid="page-1"
)


def _sp4_duplicate_with_reassignment(harness, context=lambda: True, uids=("c1",)):
    with harness.patched(), patch(f"{_COND_MODULE}.logger") as logger:
        harness.handler.on_duplicate_requested(
            list(uids), reassign_takeoffs=_SP4_REASSIGN, context_is_current=context
        )
    return logger


def _sp4_world_changes(sql):
    """One entry per fact the post-commit/post-write guards of a Plan reassignment
    re-check; each change breaks exactly that fact and nothing else. The SQL path also
    re-checks the context-menu owner and the tool revision it captured when queueing;
    the Access path re-checks the page the Plan view shows."""
    common = (
        ("shutting down", lambda h: setattr(h.coordinator, "_is_cleaning_up", True)),
        ("plan view destroyed", lambda h: _sp4_shiboken.delete(h.plan)),
        (
            "another plan view",
            lambda h: setattr(h.coordinator, "plan_view", _Sp4Plan()),
        ),
        ("another active page", lambda h: setattr(h.ui, "active_page_uid", "page-2")),
        (
            "page object replaced",
            lambda h: setattr(
                h.data, "get_page", lambda uid: SimpleNamespace(uid="page-1")
            ),
        ),
        ("no longer the takeoff view", lambda h: setattr(h, "plan_active", False)),
        (
            "plan editing revoked",
            lambda h: setattr(h, "allowed", {Feature.DUPLICATE_CONDITION}),
        ),
        (
            "duplicating revoked",
            lambda h: setattr(h, "allowed", {Feature.EDIT_PLAN_ITEMS}),
        ),
    )
    if sql:
        return common + (
            (
                "context menu owner stale",
                lambda h: setattr(h.plan, "owner_current", False),
            ),
            ("tool changed", lambda h: setattr(h.plan, "tool_revision", 6)),
        )
    return common + (
        (
            "plan shows another page",
            lambda h: setattr(h.plan, "current_page_uid", "page-2"),
        ),
    )


class ConditionActionHandlerSecondPassSqlReassignmentTests(unittest.TestCase):
    """Duplicate-and-reassign on the SQL path: what is prepared for the Plan view, what
    is queued, and every fact re-checked before the copies are placed. The Plan view and
    its handler are recording fakes (the real ones are covered by the plan-view modules
    and tests/integration/conditions)."""

    def _queued(self, harness):
        _sp4_duplicate_with_reassignment(harness)
        return harness.plan_handler.prepared[0]

    def test_the_plan_completion_is_prepared_and_the_duplicate_is_queued_with_its_options(
        self,
    ):
        harness = _sp4_reassignment_harness(sql=True)
        args, kwargs = self._queued(harness)
        self.assertEqual(args, (BidRef("database", "7"), "takeoff_condition", []))
        self.assertEqual(
            sorted(kwargs),
            [
                "committed_updates",
                "old_updates",
                "owner_is_current",
                "page_uids",
                "plan_uids",
                "preserve_selection",
                "takeoff_uids",
            ],
        )
        self.assertEqual(kwargs["old_updates"], [("t1", "c1"), ("t2", "c1")])
        self.assertEqual(kwargs["plan_uids"], {"t1", "t2"})
        self.assertEqual(kwargs["takeoff_uids"], {"t1", "t2"})
        self.assertEqual(kwargs["page_uids"], ("page-1",))
        self.assertIs(kwargs["preserve_selection"], True)
        self.assertEqual(
            harness.call("queue_conditions_duplicate"),
            [(("database", "7", ["c1"]), {"reassign_takeoffs": _SP4_REASSIGN})],
        )
        self.assertEqual(
            harness.handler._pending_sql_operations,
            {("database", "7", "duplicate_reassign", "page-1", "c1")},
        )

    def test_the_committed_updates_move_the_takeoffs_to_the_first_copy(self):
        harness = _sp4_reassignment_harness(sql=True)
        _args, kwargs = self._queued(harness)
        result = harness.result(
            authoritative_result=AuthoritativeMutationResult(
                created_resource_ids=("n1", "n2")
            )
        )
        updates, resources = kwargs["committed_updates"](result)
        self.assertEqual(updates, [("t1", "n1"), ("t2", "n1")])
        self.assertEqual(
            resources,
            (
                ResourceRef("condition", "c1", 7),
                ResourceRef("condition", "n1", 7),
            ),
        )

    def test_the_plan_completion_owner_is_current_only_while_everything_still_matches(
        self,
    ):
        harness = _sp4_reassignment_harness(sql=True)
        _args, kwargs = self._queued(harness)
        self.assertIs(kwargs["owner_is_current"](), True)
        changes = (
            (
                "shutting down",
                lambda h: setattr(h.coordinator, "_is_cleaning_up", True),
            ),
            ("plan view destroyed", lambda h: _sp4_shiboken.delete(h.plan)),
            (
                "another plan view",
                lambda h: setattr(h.coordinator, "plan_view", _Sp4Plan()),
            ),
            (
                "bid replaced",
                lambda h: setattr(h, "owner", SimpleNamespace(measure_base=0)),
            ),
            (
                "another bid selected",
                lambda h: setattr(h, "selected", BidRef("database", "8")),
            ),
        )
        for label, change in changes:
            with self.subTest(label):
                harness = _sp4_reassignment_harness(sql=True)
                _args, kwargs = self._queued(harness)
                change(harness)
                self.assertIs(kwargs["owner_is_current"](), False)

    def _deliver(self, harness, created=("n1", "n2")):
        result = harness.result(
            authoritative_result=(
                AuthoritativeMutationResult(created_resource_ids=created)
                if created is not None
                else None
            )
        )
        harness.events.clear()
        harness.callbacks[0](result)
        return result, [
            e for e in harness.events if e[0] in ("placement_enter", "highlight")
        ]

    def test_a_commit_places_and_highlights_the_copies_after_completing_the_plan_side(
        self,
    ):
        harness = _sp4_reassignment_harness(sql=True)
        self._queued(harness)
        result, finished = self._deliver(harness)
        self.assertEqual(harness.plan_handler.completed, [result])
        self.assertEqual(
            finished,
            [
                ("placement_enter", "n2", ["n1", "n2"]),
                ("highlight", {"n1", "n2"}, False),
            ],
        )

    def test_nothing_is_placed_when_a_checked_fact_changed_but_the_plan_side_still_completes(
        self,
    ):
        for label, change in _sp4_world_changes(sql=True):
            with self.subTest(label):
                harness = _sp4_reassignment_harness(sql=True)
                self._queued(harness)
                change(harness)
                result, finished = self._deliver(harness)
                self.assertEqual(harness.plan_handler.completed, [result])
                self.assertEqual(finished, [])

    def test_nothing_is_placed_when_the_selection_moved_or_no_copy_was_created(self):
        harness = _sp4_reassignment_harness(sql=True)
        self._queued(harness)
        harness.plan.selection_revision = 4
        result, finished = self._deliver(harness)
        self.assertEqual(harness.plan_handler.completed, [result])
        self.assertEqual(finished, [])
        for created in ((), None):
            with self.subTest(created=created):
                harness = _sp4_reassignment_harness(sql=True)
                self._queued(harness)
                result, finished = self._deliver(harness, created)
                self.assertEqual(harness.plan_handler.completed, [result])
                self.assertEqual(finished, [])

    def test_a_plan_view_destroyed_while_the_plan_side_completes_gets_no_placement(
        self,
    ):
        harness = _sp4_reassignment_harness(sql=True)
        self._queued(harness)
        harness.plan_handler.on_complete = lambda: _sp4_shiboken.delete(harness.plan)
        result, finished = self._deliver(harness)
        self.assertEqual(harness.plan_handler.completed, [result])
        self.assertEqual(finished, [])

    def test_a_rejected_reassignment_completes_the_plan_side_with_the_failure(self):
        harness = _sp4_reassignment_harness(sql=True)
        self._queued(harness)
        harness.events.clear()
        result = harness.result(MutationOutcomeStatus.REJECTED)
        harness.callbacks[0](result)
        self.assertEqual(harness.plan_handler.completed, [result])
        self.assertEqual(
            [e[2] for e in harness.events if e[0] == "present_error"],
            ["Duplicate Conditions"],
        )
        self.assertEqual(harness.plan_handler.aborted, 0)

    def test_a_submission_that_does_not_start_aborts_the_prepared_plan_completion(self):
        harness = _sp4_reassignment_harness(sql=True)
        self._queued(harness)
        self.assertEqual(harness.plan_handler.aborted, 0)
        _sp4_duplicate_with_reassignment(harness)
        self.assertEqual(len(harness.plan_handler.prepared), 2)
        self.assertEqual(harness.plan_handler.aborted, 1)
        self.assertEqual(len(harness.call("queue_conditions_duplicate")), 1)
        for label, failure in (
            ("rejected by the queue", RuntimeError("busy")),
            ("locked", ActiveBidLockedError()),
        ):
            with self.subTest(label):
                harness = _sp4_reassignment_harness(sql=True)
                harness.script["queue_conditions_duplicate"] = failure
                _sp4_duplicate_with_reassignment(harness)
                self.assertEqual(harness.plan_handler.aborted, 1)
                self.assertEqual(harness.handler._pending_sql_operations, set())


class ConditionActionHandlerSecondPassAccessReassignmentTests(unittest.TestCase):
    """Duplicate-and-reassign on the Access path: the synchronous write, the local
    reassignment record and the guards between the write and the placement."""

    def _run(self, harness, value=("n1", "n2"), refresh_ok=True, mutate=None):
        outcome = WriteReloadResult(list(value), bool(value), refresh_ok)
        real = harness.write.duplicate_conditions_result

        def duplicate(*args, **kwargs):
            real(*args, **kwargs)
            if mutate is not None:
                mutate(harness)
            return outcome

        harness.write.duplicate_conditions_result = duplicate
        logger = _sp4_duplicate_with_reassignment(harness)
        return logger, [
            e for e in harness.events if e[0] in ("placement_enter", "highlight")
        ]

    def test_the_copies_are_recorded_for_the_plan_then_placed(self):
        harness = _sp4_reassignment_harness(sql=False)
        _logger, finished = self._run(harness)
        self.assertEqual(
            harness.call("duplicate_conditions_result"),
            [(("database", "7", ["c1"]), {"reassign_takeoffs": _SP4_REASSIGN})],
        )
        self.assertEqual(
            harness.plan_handler.recorded,
            [
                (
                    BidRef("database", "7"),
                    [("t1", "c1"), ("t2", "c1")],
                    [("t1", "n1"), ("t2", "n1")],
                )
            ],
        )
        self.assertEqual(
            finished,
            [
                ("placement_enter", "n2", ["n1", "n2"]),
                ("highlight", {"n1", "n2"}, False),
            ],
        )
        harness.warning.assert_not_called()

    def test_nothing_is_placed_when_a_checked_fact_changed_after_the_write(self):
        for label, change in _sp4_world_changes(sql=False):
            with self.subTest(label):
                harness = _sp4_reassignment_harness(sql=False)
                _logger, finished = self._run(harness, mutate=change)
                self.assertEqual(finished, [])
                self.assertEqual(len(harness.plan_handler.recorded), 1)

    def test_nothing_is_recorded_or_placed_when_another_bid_was_selected_meanwhile(
        self,
    ):
        harness = _sp4_reassignment_harness(sql=False)
        _logger, finished = self._run(
            harness, mutate=lambda h: setattr(h, "selected", BidRef("database", "8"))
        )
        self.assertEqual(harness.plan_handler.recorded, [])
        self.assertEqual(finished, [])

    def test_a_failed_reassignment_warns_with_the_sidebar_window_as_parent_when_it_is_alive(
        self,
    ):
        harness = _sp4_reassignment_harness(sql=False)
        logger, finished = self._run(harness, value=())
        harness.warning.assert_called_once_with(
            "window",
            "Duplicate and Reassign Takeoff",
            "The operation could not complete. Refresh the database before retrying.",
        )
        logger.warning.assert_called_once()
        self.assertEqual(finished, [])
        self.assertEqual(harness.plan_handler.recorded, [])

    def test_a_failed_reassignment_has_no_parent_without_a_sidebar_or_with_a_destroyed_one(
        self,
    ):
        for label, has_sidebar in (("no sidebar", False), ("destroyed sidebar", True)):
            with self.subTest(label):
                harness = _sp4_reassignment_harness(sql=False, sidebar=has_sidebar)
                self._run(
                    harness,
                    value=(),
                    mutate=lambda h: (
                        _sp4_shiboken.delete(h.coordinator.conditions_sidebar)
                        if h.coordinator.conditions_sidebar is not None
                        else None
                    ),
                )
                harness.warning.assert_called_once_with(
                    None,
                    "Duplicate and Reassign Takeoff",
                    "The operation could not complete. Refresh the database before retrying.",
                )

    def test_a_failed_plain_duplicate_does_not_warn(self):
        harness = _SecondPassConditions(sql=False)
        harness.script["duplicate_conditions_result"] = WriteReloadResult(
            [], False, False
        )
        with harness.patched(), patch(f"{_COND_MODULE}.logger"):
            harness.handler.on_duplicate_requested(["c1"])
        harness.warning.assert_not_called()


from ost_visualizer.application.dtos.create_condition_result import (
    CreatedConditionProjection as _Sp4CreatedConditionProjection,
)


class ConditionActionHandlerSecondPassGuardTests(unittest.TestCase):
    """Guards that precede every command: no write service, an empty selection, and the
    bulk-update follow-up without a sidebar."""

    def _commands(self):
        return (
            ("create", lambda h: h.on_create_requested("")),
            ("duplicate", lambda h: h.on_duplicate_requested(["c1"])),
            ("paste", lambda h: h.on_paste_requested(["c1"], {"kind": "root"})),
            ("delete", lambda h: h.on_delete_requested(["c1"])),
            ("renumber", lambda h: h.on_renumber_requested()),
            ("create folder", lambda h: h.on_create_folder_requested("")),
            ("rename folder", lambda h: h.on_folder_renamed("f1", "N")),
            ("rename condition", lambda h: h.on_condition_renamed("c1", "N")),
            ("delete folder", lambda h: h.on_folder_delete_requested(["f1"])),
            ("move condition", lambda h: h.on_move_condition_to_folder("c1", "f1")),
            (
                "layer change",
                lambda h: h.on_condition_layer_change_requested(["c1"], "40"),
            ),
            (
                "type change",
                lambda h: h.on_condition_type_change_requested(["c1"], "t1"),
            ),
            ("edit", lambda h: h.on_edit_requested(["c1"])),
        )

    def test_every_command_does_nothing_without_a_write_service(self):
        for sql in (False, True):
            for label, run in self._commands():
                with self.subTest(label, sql=sql):
                    harness = _SecondPassConditions(sql=sql)
                    handler = ConditionActionHandler(
                        coordinator=harness.coordinator,
                        project_write_service=None,
                        project_read_service=harness.read,
                        project_data=harness.data,
                        ui_state_manager=harness.ui,
                        workspace_state_model=make_workspace_state_model(),
                    )
                    with harness.patched():
                        run(handler)
                    self.assertEqual(harness.calls, [])
                    self.assertEqual(harness.callbacks, [])
                    self.assertEqual(
                        [e for e in harness.events if e[0] != "allowed?"], []
                    )

    def test_an_empty_selection_does_not_even_consult_the_access_manager(self):
        for label, run in (
            ("delete", lambda h: h.on_delete_requested([])),
            ("edit", lambda h: h.on_edit_requested([])),
            ("duplicate", lambda h: h.on_duplicate_requested([])),
            ("paste", lambda h: h.on_paste_requested([], {"kind": "root"})),
            ("layer change", lambda h: h.on_condition_layer_change_requested([], "40")),
            ("folder delete", lambda h: h.on_folder_delete_requested([])),
        ):
            for sql in (False, True):
                with self.subTest(label, sql=sql):
                    harness = _SecondPassConditions(sql=sql)
                    with harness.patched():
                        run(harness.handler)
                    self.assertEqual(harness.events, [])
                    self.assertEqual(harness.calls, [])

    def test_a_bulk_update_commit_highlights_only_while_the_sidebar_exists(self):
        for has_sidebar, expected in (
            (True, [("highlight", {"c1", "c2"}, True)]),
            (False, []),
        ):
            with self.subTest(sidebar=has_sidebar):
                harness = _SecondPassConditions(sql=True, sidebar=has_sidebar)
                with harness.patched():
                    harness.handler.on_condition_type_change_requested(
                        ["c1", "c2"], "t1"
                    )
                harness.events.clear()
                harness.callbacks[0](harness.result())
                self.assertEqual(
                    [e for e in harness.events if e[0] == "highlight"], expected
                )


class ConditionActionHandlerSecondPassCreateOwnershipTests(unittest.TestCase):
    """The ownership bookkeeping of the New Condition dialog across saves: only a save
    whose result is still authoritative may highlight the created Condition."""

    def _create(self, harness, folder_uid="f1", on_exec=None):
        return _second_pass_open_dialog(
            harness,
            lambda: harness.handler.on_create_requested(folder_uid),
            on_exec=on_exec,
        )

    def _script_creates(self, harness, outcomes):
        pending = list(outcomes)

        def create(*args, **kwargs):
            harness.calls.append(("create_condition_result", args, kwargs))
            return pending.pop(0)(harness)

        harness.write.create_condition_result = create

    @staticmethod
    def _saved(refresh_ok=True, change=None, projection=None):
        def outcome(harness):
            harness.conditions["n1"] = harness.conditions.get(
                "n1", Condition(uid="n1", name="New")
            )
            if change is not None:
                change(harness)
            return _SecondPassCreateConditionResult(
                "n1", True, refresh_ok, projection=projection
            )

        return outcome

    def _run(self, harness, saves, folder_uid="f1"):
        def on_exec(dialog):
            for _ in range(saves):
                dialog.kwargs["save_fn"]("__new__", UpdateConditionDto({}))

        self._create(harness, folder_uid=folder_uid, on_exec=on_exec)
        return [e for e in harness.events if e[0] == "highlight"]

    def test_a_single_clean_save_highlights_the_created_condition(self):
        harness = _SecondPassConditions(sql=False)
        self._script_creates(harness, [self._saved()])
        self.assertEqual(self._run(harness, 1), [("highlight", {"n1"}, True)])

    def test_a_folder_changed_during_the_save_is_not_trusted_in_place_or_replaced(self):
        def rename_in_place(harness):
            harness.folders["f1"].name = "Renamed elsewhere"

        def replace_renamed(harness):
            harness.folders = {
                "f1": replace(harness.folders["f1"], name="Renamed elsewhere")
            }

        for label, change in (
            ("in place", rename_in_place),
            ("replaced", replace_renamed),
        ):
            with self.subTest(label):
                harness = _SecondPassConditions(sql=False)
                self._script_creates(harness, [self._saved(change=change)])
                self.assertEqual(self._run(harness, 1), [])
                harness.warning.assert_not_called()

    def test_a_later_save_that_is_no_longer_authoritative_cancels_the_earlier_highlight(
        self,
    ):
        harness = _SecondPassConditions(sql=False)
        self._script_creates(
            harness,
            [
                self._saved(),
                self._saved(
                    change=lambda h: setattr(
                        h.folders["f1"], "name", "Renamed elsewhere"
                    )
                ),
            ],
        )
        self.assertEqual(self._run(harness, 2), [])

    def test_a_later_save_whose_list_refresh_failed_warns_and_does_not_highlight(self):
        harness = _SecondPassConditions(sql=False)
        self._script_creates(harness, [self._saved(), self._saved(refresh_ok=False)])
        self.assertEqual(self._run(harness, 2), [])
        harness.warning.assert_called_once_with(
            "window",
            "Refresh Error",
            "The condition was created, but the conditions list could not be "
            "refreshed. Reopen the database to see the new condition.",
        )

    def test_a_rejected_projection_does_not_advance_the_owner_and_the_warning_still_shows(
        self,
    ):
        harness = _SecondPassConditions(sql=False)
        other_bid = SimpleNamespace(measure_base=0)
        new_condition = Condition(uid="n1", name="New")

        def create(*args, **kwargs):
            harness.conditions["n1"] = new_condition
            return _SecondPassCreateConditionResult(
                "n1",
                True,
                False,
                projection=_Sp4CreatedConditionProjection(
                    previous_bid=harness.owner,
                    bid=other_bid,
                    condition=new_condition,
                    folder=None,
                ),
            )

        harness.write.create_condition_result = create
        self.assertEqual(self._run(harness, 1, folder_uid=""), [])
        harness.warning.assert_called_once_with(
            "window",
            "Refresh Error",
            "The condition was created, but the conditions list could not be "
            "refreshed. Reopen the database to see the new condition.",
        )

    def test_a_committed_empty_identity_is_never_highlighted(self):
        harness = _SecondPassConditions(sql=True)
        harness.conditions[""] = Condition(uid="", name="Empty uid")
        completions = []

        def on_exec(dialog):
            dialog.kwargs["save_async_fn"](
                "__new__", UpdateConditionDto({}), completions.append
            )
            harness.callbacks[0](
                harness.result(
                    authoritative_result=AuthoritativeMutationResult(
                        created_resource_ids=("",)
                    )
                )
            )

        self._create(harness, folder_uid="", on_exec=on_exec)
        self.assertEqual([c.success for c in completions], [True])
        self.assertEqual([e for e in harness.events if e[0] == "highlight"], [])


class ConditionActionHandlerSecondPassEditOwnershipTests(unittest.TestCase):
    """The SQL properties dialog reconciles the authoritative Condition family after a
    commit; anything it cannot reconcile is a plain False (not None), without an error
    dialog."""

    def _edit(self, harness, on_exec):
        return _second_pass_open_dialog(
            harness, lambda: harness.handler.on_edit_requested(["c1"]), on_exec=on_exec
        )

    def test_a_saved_condition_that_is_missing_from_the_authoritative_family_fails(
        self,
    ):
        harness = _SecondPassConditions(sql=True)
        completions = []

        def save(dialog):
            dialog.kwargs["save_async_fn"](
                "ghost", UpdateConditionDto({"name": "N"}), completions.append
            )
            harness.callbacks[0](harness.result())

        dialog, _executed = self._edit(harness, save)
        self.assertEqual(len(completions), 1)
        self.assertIs(completions[0].success, False)
        self.assertEqual(
            (completions[0].error, completions[0].error_presented),
            ("The active bid or authoritative Condition family changed.", False),
        )
        self.assertEqual(dialog.refreshed, [])

    def test_a_bid_replaced_before_the_commit_arrives_fails_with_a_real_false(self):
        harness = _SecondPassConditions(sql=True)
        completions = []

        def save(dialog):
            dialog.kwargs["save_async_fn"](
                "c1", UpdateConditionDto({"name": "N"}), completions.append
            )
            harness.owner = SimpleNamespace(measure_base=0)
            harness.callbacks[0](harness.result())

        dialog, _executed = self._edit(harness, save)
        self.assertEqual(len(completions), 1)
        self.assertIs(completions[0].success, False)
        self.assertEqual(
            (completions[0].error, completions[0].error_presented),
            ("The active bid or authoritative Condition family changed.", False),
        )
        self.assertEqual(dialog.refreshed, [])


class _Dec10RaisingPlanViewHandler(_Sp4PlanViewHandler):
    def __init__(self, prepare_failure=None):
        super().__init__()
        self.prepare_failure = prepare_failure

    def prepare_sql_property_completion(self, *args, **kwargs):
        if self.prepare_failure is not None:
            raise self.prepare_failure
        return super().prepare_sql_property_completion(*args, **kwargs)


def _dec10_harness(prepare_failure=None):
    harness = _sp4_reassignment_harness(sql=True)
    harness.plan_handler = _Dec10RaisingPlanViewHandler(prepare_failure)
    harness.coordinator._plan_view_handler = harness.plan_handler
    return harness


_DEC10_SWALLOWED = (RuntimeError("busy"), ValueError("bad value"))
_DEC10_RERAISED = (KeyError("missing"), OSError("pipe"), AttributeError("none"))


class ConditionActionHandlerReassignmentSubmitFailureTests(unittest.TestCase):
    """Decision S3: whatever the submit helper of a Plan reassignment raises, the Plan
    completion prepared for it (pending marks, forward-mutation token, deferred
    selection, history) is aborted exactly once, the pending key is freed, the callback
    the queue was handed can no longer place or complete anything, and a generic error
    is re-raised unchanged. The Plan handler is a recording fake here; the real one runs
    in tests/integration/conditions/test_duplicate_reassignment.py."""

    def _fail_queue(self, failure):
        harness = _dec10_harness()
        harness.script["queue_conditions_duplicate"] = failure
        return harness

    def test_a_generic_error_from_the_duplicate_queue_call_aborts_the_prepared_completion(
        self,
    ):
        for failure in _DEC10_RERAISED:
            with self.subTest(type(failure).__name__):
                harness = self._fail_queue(failure)
                with self.assertRaises(type(failure)) as raised:
                    _sp4_duplicate_with_reassignment(harness)
                self.assertIs(raised.exception, failure)
                self.assertEqual(len(harness.plan_handler.prepared), 1)
                self.assertEqual(len(harness.call("queue_conditions_duplicate")), 1)
                self.assertEqual(harness.plan_handler.aborted, 1)
                self.assertEqual(harness.plan_handler.completed, [])
                self.assertEqual(harness.handler._pending_sql_operations, set())
                self.assertEqual(harness.plan_handler.recorded, [])

    def test_a_swallowed_queue_error_aborts_once_warns_once_and_does_not_raise(self):
        for failure in _DEC10_SWALLOWED:
            with self.subTest(type(failure).__name__):
                harness = self._fail_queue(failure)
                _sp4_duplicate_with_reassignment(harness)
                harness.warning.assert_called_once_with(
                    harness.coordinator.conditions_sidebar.window(),
                    "Duplicate Conditions",
                    str(failure),
                )
                self.assertEqual(harness.plan_handler.aborted, 1)
                self.assertEqual(harness.plan_handler.completed, [])
                self.assertEqual(harness.handler._pending_sql_operations, set())

    def test_the_callback_of_a_failed_submission_cannot_place_or_complete_anything(
        self,
    ):
        for failure in _DEC10_SWALLOWED + _DEC10_RERAISED:
            with self.subTest(type(failure).__name__):
                harness = self._fail_queue(failure)
                try:
                    _sp4_duplicate_with_reassignment(harness)
                except type(failure):
                    pass
                self.assertEqual(len(harness.callbacks), 1)
                harness.events.clear()
                harness.callbacks[0](
                    harness.result(
                        authoritative_result=AuthoritativeMutationResult(
                            created_resource_ids=("n1", "n2")
                        )
                    )
                )
                self.assertEqual(harness.plan_handler.completed, [])
                self.assertEqual(
                    [
                        e
                        for e in harness.events
                        if e[0] in ("placement_enter", "highlight", "present_error")
                    ],
                    [],
                )
                self.assertEqual(len(harness.call("queue_conditions_duplicate")), 1)

    def test_a_failure_while_preparing_queues_nothing_and_leaves_no_key(self):
        for failure in _DEC10_SWALLOWED + _DEC10_RERAISED:
            with self.subTest(type(failure).__name__):
                harness = _dec10_harness(prepare_failure=failure)
                with self.assertRaises(type(failure)) as raised:
                    _sp4_duplicate_with_reassignment(harness)
                self.assertIs(raised.exception, failure)
                self.assertEqual(harness.call("queue_conditions_duplicate"), [])
                self.assertEqual(harness.callbacks, [])
                self.assertEqual(harness.plan_handler.prepared, [])
                self.assertEqual(harness.plan_handler.aborted, 0)
                self.assertEqual(harness.handler._pending_sql_operations, set())
                harness.warning.assert_not_called()

    def test_a_locked_bid_still_refuses_silently_and_aborts_once(self):
        harness = self._fail_queue(ActiveBidLockedError())
        _sp4_duplicate_with_reassignment(harness)
        self.assertEqual(harness.plan_handler.aborted, 1)
        self.assertEqual(harness.handler._pending_sql_operations, set())
        harness.warning.assert_not_called()
        harness.callbacks[0](
            harness.result(
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=("n1",)
                )
            )
        )
        self.assertEqual(harness.plan_handler.completed, [])
        self.assertEqual(harness.event_names().count("placement_enter"), 0)

    def test_a_failing_abort_never_replaces_the_queue_error(self):
        failure = KeyError("missing")
        harness = self._fail_queue(failure)

        def broken_abort():
            harness.plan_handler.aborted += 1
            raise RuntimeError("abort failed")

        harness.plan_handler._abort = broken_abort
        with patch(f"{_COND_MODULE}.logger") as logger:
            with self.assertRaises(KeyError) as raised:
                harness.handler.on_duplicate_requested(
                    ["c1"],
                    reassign_takeoffs=_SP4_REASSIGN,
                    context_is_current=lambda: True,
                )
        self.assertIs(raised.exception, failure)
        self.assertEqual(harness.plan_handler.aborted, 1)
        logger.exception.assert_called_once()
        self.assertEqual(harness.handler._pending_sql_operations, set())
