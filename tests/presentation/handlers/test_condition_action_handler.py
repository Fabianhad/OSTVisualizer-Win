import os
import unittest
from dataclasses import fields, replace
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    EditLeaseHandle,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
)
from ost_visualizer.application.dtos.update_condition_dto import (
    UpdateConditionDto,
    UpdateConditionResultDto,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
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

    def test_condition_delete_hidden_fallback_keeps_takeoff_disabled(self):
        conditions = self._make_conditions(2)
        conditions["c1"].layer_visible = False
        sidebar, toolbar, placement = self._run_condition_delete_tool_projection(
            conditions, "c2"
        )
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])
        self.assertFalse(toolbar.place_enabled)
        self.assertFalse(placement.is_active)

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

    def test_sql_condition_delete_queues_and_selects_after_authoritative_completion(
        self,
    ):
        from ost_visualizer.presentation.handlers import condition_action_handler

        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(4)
        sidebar.load_conditions(conditions, {}, "Project")
        queued = {}
        errors = []

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
            placement=SimpleNamespace(force_exit=lambda: None),
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
        self.assertEqual(sidebar.get_selected_condition_uids(), [])
        operation_key = ("database", "7", "delete", "c3")
        self.assertIn(operation_key, handler._pending_sql_operations)
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
        self.assertEqual(set(callbacks), {"database-a", "database-b"})

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
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            workspace_state_model=make_workspace_state_model(),
        )
        handler.on_condition_renamed("c1", "Renamed")
        handler.on_move_condition_to_folder("c2", "folder-1")
        handler.on_condition_layer_change_requested(["c3"], "layer-1")
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
        self.assertEqual(highlighted, [])

    def test_sql_folder_create_completion_rejects_same_uid_bid_replacement(self):
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
        self.assertEqual(pending_edits, [])

    def test_sql_condition_delete_completion_rejects_same_uid_bid_replacement(self):
        queued = {}
        bid_ref = BidRef("database", "7")
        current_bid = [object()]
        placement_exits = []
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
            highlight_sidebar=lambda *_args, **_kwargs: None,
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
        self.assertEqual(placement_exits, [])

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
            present_queued_mutation_error=lambda *_args: None,
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
        callbacks[0](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000201",
                outcome_status=MutationOutcomeStatus.REJECTED,
                commit_attempted=False,
            )
        )
        self.assertEqual(completed, [])
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
            lambda _dialog, _event_bus: QtWidgets.QDialog.DialogCode.Rejected,
        ):
            handler.on_edit_requested(["c1"])
        self.assertEqual(refreshes, [])
        self.assertEqual(highlights, [])

    def test_condition_properties_rejected_save_preserves_active_takeoff_tool(self):
        condition = Condition(uid="c1", name="Condition 1", ref_no=1)
        save_calls = []
        highlights = []

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
            update_condition=lambda *_args: (
                save_calls.append(True)
                or UpdateConditionResultDto(success=False, error="Rejected")
            ),
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
            self.assertFalse(result.success)
            return QtWidgets.QDialog.DialogCode.Rejected

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler.EditConditionDialog",
            Dialog,
        ), patch(
            "ost_visualizer.presentation.handlers.condition_action_handler.exec_with_ost_blocking",
            execute,
        ):
            handler.on_edit_requested(["c1"])
        self.assertEqual(save_calls, [True])
        self.assertTrue(placement.is_active)
        self.assertEqual(highlights, [])

    def test_sql_condition_editor_save_transfers_and_reacquires_its_lease(self):
        conditions = {
            "c1": Condition(uid="c1", name="Condition 1", ref_no=1),
            "c2": Condition(uid="c2", name="Condition 2", ref_no=2),
        }
        lease_requests = []
        ended_leases = []
        queued = []
        completions = []

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
                        outcome_status=MutationOutcomeStatus.COMMITTED,
                        commit_attempted=True,
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
            present_queued_mutation_error=lambda *_args: None,
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
        self.assertEqual(lease_requests, [expected_resources, expected_resources])
        self.assertEqual(queued[0][:4], ("database", "7", ["c2"], {"name": "Renamed"}))
        self.assertEqual(queued[0][4].draft_id, "draft-1")
        self.assertEqual([result.success for result in completions], [True])
        self.assertEqual([handle.draft_id for handle in ended_leases], ["draft-2"])

    def test_delayed_condition_editor_lease_does_not_open_after_bid_switch(self):
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
        self.assertEqual(executions, [])
        self.assertEqual(ended_leases, [handle])

    def test_open_condition_editor_rejects_same_uid_condition_replacement(self):
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
            conditions[0] = {"c1": Condition(uid="c1", name="Replacement", ref_no=1)}
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
        self.assertFalse(save_results[0].success)
        self.assertEqual(writes, [])

    def test_create_condition_dialog_rejects_same_uid_bid_replacement(self):
        bid_ref = BidRef("database", "1")
        current_bid = [SimpleNamespace(measure_base=0)]
        writes = []
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

        project_data = SimpleNamespace(
            get_bid=lambda _bid_ref: current_bid[0],
            get_current_bid=lambda: current_bid[0],
        )
        coordinator = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            conditions_sidebar=Sidebar(),
            main_window=SimpleNamespace(icon_provider=None),
            event_bus=EventBus(),
            flush_deferred_for_file=lambda _file_path: True,
            highlight_sidebar=lambda *_args, **_kwargs: None,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: False,
                create_condition_result=lambda *args: (
                    writes.append(args)
                    or SimpleNamespace(
                        write_success=True,
                        value="new-condition",
                        refresh_failed=False,
                    )
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
        self.assertFalse(save_results[0].success)
        self.assertEqual(writes, [])

    def test_create_condition_in_folder_highlights_after_own_family_reconstruction(
        self,
    ):
        bid_ref = BidRef("database", "1")
        bid_owner = SimpleNamespace(measure_base=0)
        folders = [{"f1": BidConditionFolder(uid="f1", name="Folder")}]
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
            folders[0] = {uid: replace(folder) for uid, folder in folders[0].items()}
            return SimpleNamespace(
                write_success=True,
                value="new-condition",
                refresh_failed=False,
            )

        project_data = SimpleNamespace(
            get_bid=lambda _bid_ref: bid_owner,
            get_current_bid=lambda: bid_owner,
            get_bid_condition_folders=lambda: folders[0],
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
        self.assertTrue(save_results[0].success)
        self.assertEqual(highlighted, [{"new-condition"}])

    def test_condition_delete_confirmation_rejects_same_uid_replacement(self):
        original = Condition(uid="c1", name="Original", ref_no=1)
        conditions = [{"c1": original}]
        writes = []
        bid_ref = BidRef("database", "1")
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
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            workspace_state_model=make_workspace_state_model(),
        )

        def replace_during_confirmation(_parent, _names):
            conditions[0] = {"c1": Condition(uid="c1", name="Replacement", ref_no=1)}
            return ["c1"]

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "confirm_delete_conditions",
            replace_during_confirmation,
        ):
            handler.on_delete_requested(["c1"])
        self.assertEqual(writes, [])

    def test_condition_folder_delete_confirmation_rejects_same_uid_replacement(self):
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
            folders[0] = {"f1": BidConditionFolder(uid="f1", name="Replacement")}
            return [("Original", "f1")]

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "confirm_multi_delete",
            replace_during_confirmation,
        ):
            handler.on_folder_delete_requested(["f1"])
        self.assertEqual(writes, [])

    def test_condition_renumber_confirmation_rejects_same_uid_replacement(self):
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
            conditions[0] = {"c1": Condition(uid="c1", name="Replacement", ref_no=1)}
            return True

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler.confirm",
            replace_during_confirmation,
        ):
            handler.on_renumber_requested()
        self.assertEqual(writes, [])


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
        self.assertIn("could not be refreshed", warnings[0][2])
