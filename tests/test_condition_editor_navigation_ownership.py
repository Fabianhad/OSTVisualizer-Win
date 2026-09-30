import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete, isValid
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    EditLeaseHandle,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
)
from ost_visualizer.application.dtos.update_condition_dto import (
    UpdateConditionResultDto,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.dialogs.edit_condition_dialog import (
    EditConditionDialog,
)
from ost_visualizer.presentation.handlers.condition_action_handler import (
    ConditionActionHandler,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from tests.workspace_state_test_support import make_workspace_state_model


class _ReadService:
    @staticmethod
    def display_to_inches(text, _metric):
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def inches_to_display(value, _metric):
        return "" if not value else str(value)

    @staticmethod
    def get_quantity_options_for_type(_condition_type):
        return []

    @staticmethod
    def get_valid_uoms_for_calc_type(_calc_type, _metric):
        return []

    @staticmethod
    def get_cdn_types(_database_id):
        return {}

    @staticmethod
    def get_merged_bid_layers(_database_id, _bid_uid):
        return []

    @staticmethod
    def get_layer_uids_in_use(_database_id, _bid_uid):
        return set()


class _Access:
    allowed = True

    @classmethod
    def is_allowed(cls, feature):
        return cls.allowed and feature == Feature.EDIT_CONDITION

    @staticmethod
    def has_license():
        return True


class _ProjectData:
    def __init__(self, conditions, folders, bid_ref):
        self.conditions = conditions
        self.folders = folders
        self.bid_ref = bid_ref
        self.bid = SimpleNamespace(measure_base=0, name="Project")

    def get_bid_conditions(self):
        return self.conditions

    def get_bid_condition_folders(self):
        return self.folders

    @staticmethod
    def get_all_takeoffs():
        return []

    def get_current_bid(self):
        return self.bid

    def get_bid(self, bid_ref):
        return self.bid if bid_ref == self.bid_ref else None

    @staticmethod
    def is_current_bid_locked():
        return False

    @staticmethod
    def get_cdn_types():
        return {}

    @staticmethod
    def get_bid_layer_snapshot():
        return []

    @staticmethod
    def get_layer_uids_in_use():
        return set()


class _WriteService:
    def __init__(self, project_data, sidebar, *, sql):
        self.project_data = project_data
        self.sidebar = sidebar
        self.sql = sql
        self.writes = []
        self.after_reconstruct = None

    def uses_sql_collaboration_mutations(self, _database_id):
        return self.sql

    def _reconstruct_family(self, condition_uid, changes):
        reconstructed = {
            uid: replace(condition)
            for uid, condition in self.project_data.conditions.items()
        }
        target = reconstructed[condition_uid]
        for field, value in changes.items():
            setattr(target, field, value)
        self.project_data.conditions = reconstructed
        self.sidebar.load_conditions(
            reconstructed, self.project_data.folders, "Project"
        )
        if self.after_reconstruct is not None:
            self.after_reconstruct()

    def update_condition(self, _database_id, _bid_uid, condition_uid, dto):
        changes = dto.get_changes()
        self.writes.append((condition_uid, changes))
        self._reconstruct_family(condition_uid, changes)
        return UpdateConditionResultDto(success=True)

    def queue_conditions_update(
        self,
        database_id,
        _bid_uid,
        condition_uids,
        changes,
        callback,
        *,
        edit_lease_handle,
    ):
        self.asserted_lease = edit_lease_handle
        condition_uid = condition_uids[0]
        self.writes.append((condition_uid, dict(changes)))
        self._reconstruct_family(condition_uid, changes)
        callback(
            QueuedMutationResult(
                database_id=database_id,
                runtime_generation=1,
                operation_id=(f"00000000-0000-0000-0000-{len(self.writes):012d}"),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        return len(self.writes)

    def queue_condition_create(
        self,
        database_id,
        _bid_uid,
        spec,
        callback,
    ):
        created_uid = "c4"
        reconstructed = {
            uid: replace(condition)
            for uid, condition in self.project_data.conditions.items()
        }
        reconstructed[created_uid] = Condition(
            uid=created_uid,
            name=spec.name,
            condition_type=spec.condition_type,
            folder_uid=spec.folder_uid,
        )
        self.project_data.conditions = reconstructed
        self.project_data.folders = {
            uid: replace(folder) for uid, folder in self.project_data.folders.items()
        }
        self.sidebar.load_conditions(
            reconstructed, self.project_data.folders, "Project"
        )
        callback(
            QueuedMutationResult(
                database_id=database_id,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000100",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                authoritative_result=AuthoritativeMutationResult(
                    created_resource_ids=(created_uid,),
                ),
                commit_attempted=True,
            )
        )
        return 1


class ConditionEditorNavigationOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        _Access.allowed = True
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            if isValid(widget):
                widget.close()
                delete(widget)
        self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def _make_harness(self, *, sql=False, foldered=False):
        bid_ref = BidRef("database.sql" if sql else "bid.mdb", "7")
        folders = {}
        folder_uids = (None, None, None)
        if foldered:
            folders = {
                "f1": BidConditionFolder(uid="f1", name="First"),
                "f2": BidConditionFolder(uid="f2", name="Second"),
            }
            folder_uids = ("f1", "f2", "f2")
        conditions = {
            f"c{index}": Condition(
                uid=f"c{index}",
                name=f"Condition {index}",
                ref_no=index,
                folder_uid=folder_uids[index - 1],
            )
            for index in range(1, 4)
        }
        sidebar = ConditionsSidebar(None)
        self.widgets.append(sidebar)
        sidebar.load_conditions(conditions, folders, "Project")
        sidebar.highlight_conditions({"c1"})
        data = _ProjectData(conditions, folders, bid_ref)
        writer = _WriteService(data, sidebar, sql=sql)
        active_bid = [bid_ref]
        highlights = []
        lease_requests = []
        lease_handles = []
        ended_leases = []
        event_bus = EventBus()

        def highlight(uids, reveal=True):
            highlights.append(set(uids))
            sidebar.highlight_conditions(set(uids), reveal=reveal)

        def request_lease(
            database_id,
            resources,
            callback,
            *,
            dependency_resources=(),
            operation_id="",
            owning_surface="desktop",
        ):
            resources = tuple(resources)
            lease_requests.append(resources)
            handle = EditLeaseHandle(
                database_id=database_id,
                draft_id=f"lease-{len(lease_requests)}",
                runtime_generation=1,
                operation_id=operation_id,
                owning_surface=owning_surface,
                resources=resources,
                dependency_resources=tuple(dependency_resources),
            )
            lease_handles.append(handle)
            callback(EditLeaseResult(True, handle=handle))

        coordinator = SimpleNamespace(
            ui_access_manager=_Access(),
            conditions_sidebar=sidebar,
            main_window=SimpleNamespace(icon_provider=None),
            event_bus=event_bus,
            placement=SimpleNamespace(is_active=False),
            _is_takeoff_2d_view_active=lambda: True,
            flush_deferred_for_file=lambda _database_id: True,
            request_collaboration_edit=request_lease,
            end_collaboration_edit=ended_leases.append,
            present_queued_mutation_error=lambda *_args: None,
            highlight_sidebar=highlight,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=writer,
            project_read_service=_ReadService(),
            project_data=data,
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: active_bid[0]
            ),
            workspace_state_model=make_workspace_state_model(),
        )
        return SimpleNamespace(
            bid_ref=bid_ref,
            active_bid=active_bid,
            data=data,
            writer=writer,
            sidebar=sidebar,
            handler=handler,
            highlights=highlights,
            lease_requests=lease_requests,
            lease_handles=lease_handles,
            ended_leases=ended_leases,
            event_bus=event_bus,
        )

    def _open_and_execute(self, harness, execute):
        warnings = []

        def capture_dialog(dialog, _event_bus):
            self.widgets.append(dialog)
            return execute(dialog)

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "exec_with_ost_blocking",
            capture_dialog,
        ), patch(
            "ost_visualizer.presentation.dialogs.edit_condition_dialog."
            "confirm_save_discard_cancel",
            return_value=True,
        ), patch(
            "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning",
            side_effect=lambda _parent, _title, message: warnings.append(message),
        ), patch(
            "ost_visualizer.presentation.handlers.condition_action_handler.show_warning",
            side_effect=lambda _parent, _title, message: warnings.append(message),
        ):
            harness.handler.on_edit_requested(["c1"])
        return warnings

    def test_mdb_save_next_advances_reconstructed_family_and_allows_second_save(self):
        harness = self._make_harness(foldered=True)

        def execute(dialog):
            dialog._name_edit.setText("First edited")
            dialog._on_next()
            self.assertEqual(dialog._current_uid, "c2")
            self.assertEqual(harness.sidebar.get_selected_condition_uids(), ["c2"])
            dialog._name_edit.setText("Second edited")
            dialog._on_apply()
            self.assertEqual(harness.sidebar.get_selected_condition_uids(), ["c2"])
            return QtWidgets.QDialog.DialogCode.Rejected

        warnings = self._open_and_execute(harness, execute)
        self.assertEqual(warnings, [])
        self.assertEqual([uid for uid, _changes in harness.writer.writes], ["c1", "c2"])
        self.assertEqual(harness.data.conditions["c1"].name, "First edited")
        self.assertEqual(harness.data.conditions["c2"].name, "Second edited")

    def test_mdb_save_previous_and_repeated_navigation_keep_sidebar_in_sync(self):
        harness = self._make_harness()

        def execute(dialog):
            dialog._navigate_to("c3")
            for expected_uid, method in (
                ("c2", dialog._on_previous),
                ("c1", dialog._on_previous),
                ("c2", dialog._on_next),
                ("c3", dialog._on_next),
            ):
                dialog._name_edit.setText(f"Edited {expected_uid}")
                method()
                self.assertEqual(dialog._current_uid, expected_uid)
                self.assertEqual(
                    harness.sidebar.get_selected_condition_uids(), [expected_uid]
                )
            self.assertFalse(dialog._next_btn.isEnabled())
            return QtWidgets.QDialog.DialogCode.Rejected

        warnings = self._open_and_execute(harness, execute)
        self.assertEqual(warnings, [])
        self.assertEqual(len(harness.writer.writes), 4)

    def test_sql_save_next_reacquires_lease_and_allows_second_save(self):
        harness = self._make_harness(sql=True)

        def execute(dialog):
            dialog._name_edit.setText("First edited")
            dialog._on_next()
            if dialog._current_uid == "c2":
                self.assertEqual(harness.sidebar.get_selected_condition_uids(), ["c2"])
                dialog._name_edit.setText("Second edited")
                dialog._on_apply()
                self.assertEqual(harness.sidebar.get_selected_condition_uids(), ["c2"])
            return QtWidgets.QDialog.DialogCode.Rejected

        warnings = self._open_and_execute(harness, execute)
        self.assertEqual(
            warnings,
            [],
            (harness.writer.writes, len(harness.lease_requests)),
        )
        self.assertEqual([uid for uid, _changes in harness.writer.writes], ["c1", "c2"])
        self.assertEqual(len(harness.lease_requests), 3)
        self.assertEqual(len(harness.ended_leases), 1)

    def test_sql_create_in_folder_highlights_after_family_reconstruction(self):
        harness = self._make_harness(sql=True, foldered=True)
        warnings = []

        def execute(dialog, _event_bus):
            self.widgets.append(dialog)
            dialog._name_edit.setText("Created in folder")
            dialog._ref_no_edit.setText("4")
            dialog._on_ok()
            self.assertEqual(
                dialog.result(), QtWidgets.QDialog.DialogCode.Accepted, warnings
            )
            return QtWidgets.QDialog.DialogCode.Accepted

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "exec_with_ost_blocking",
            execute,
        ), patch(
            "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning",
            side_effect=lambda _parent, _title, message: warnings.append(message),
        ):
            harness.handler.on_create_requested("f1")
        self.assertEqual(warnings, [])
        self.assertEqual(harness.sidebar.get_selected_condition_uids(), ["c4"])
        self.assertEqual(harness.data.conditions["c4"].folder_uid, "f1")
        self.assertEqual(harness.lease_requests, [])
        self.assertEqual(harness.ended_leases, [])

    def test_no_discard_cancel_and_navigation_boundaries(self):
        conditions = {
            "c1": Condition(uid="c1", name="First", ref_no=1),
            "c2": Condition(uid="c2", name="Second", ref_no=2),
        }
        saves = []
        dialog = EditConditionDialog(
            None,
            None,
            conditions["c1"],
            list(conditions),
            conditions,
            {},
            {},
            lambda _uid: False,
            lambda uid, dto: saves.append((uid, dto))
            or UpdateConditionResultDto(success=True),
            make_workspace_state_model(),
            read_service=_ReadService(),
        )
        self.widgets.append(dialog)
        navigated = []
        dialog.condition_navigated.connect(navigated.append)
        dialog._on_previous()
        self.assertEqual(navigated, [])
        dialog._on_next()
        self.assertEqual(navigated, ["c2"])
        dialog._on_next()
        self.assertEqual(navigated, ["c2"])
        dialog._name_edit.setText("Discard me")
        with patch(
            "ost_visualizer.presentation.dialogs.edit_condition_dialog."
            "confirm_save_discard_cancel",
            return_value=False,
        ):
            dialog._on_previous()
        self.assertEqual(dialog._current_uid, "c1")
        self.assertEqual(saves, [])
        dialog._name_edit.setText("Keep me")
        with patch(
            "ost_visualizer.presentation.dialogs.edit_condition_dialog."
            "confirm_save_discard_cancel",
            return_value=None,
        ):
            dialog._on_next()
        self.assertEqual(dialog._current_uid, "c1")
        self.assertEqual(dialog._name_edit.text(), "Keep me")
        dialog._dirty = False
        dialog.reject()

    def test_successful_save_rejects_unrelated_condition_change_during_refresh(self):
        harness = self._make_harness()

        def change_unrelated_condition():
            harness.data.conditions["c3"].name = "Changed externally"

        harness.writer.after_reconstruct = change_unrelated_condition

        def execute(dialog):
            dialog._name_edit.setText("First edited")
            dialog._on_next()
            self.assertEqual(dialog._current_uid, "c1")
            self.assertEqual(harness.sidebar.get_selected_condition_uids(), ["c1"])
            dialog._dirty = False
            dialog.reject()
            return QtWidgets.QDialog.DialogCode.Rejected

        warnings = self._open_and_execute(harness, execute)
        self.assertEqual(
            warnings,
            ["The active bid or authoritative Condition family changed."],
        )
        self.assertEqual(len(harness.writer.writes), 1)

    def test_successful_save_rejects_same_ref_bid_replacement(self):
        harness = self._make_harness()

        def replace_bid_owner():
            harness.data.bid = SimpleNamespace(measure_base=0, name="Replacement")

        harness.writer.after_reconstruct = replace_bid_owner

        def execute(dialog):
            dialog._name_edit.setText("First edited")
            dialog._on_next()
            self.assertEqual(dialog._current_uid, "c1")
            self.assertEqual(harness.sidebar.get_selected_condition_uids(), ["c1"])
            dialog._dirty = False
            dialog.reject()
            return QtWidgets.QDialog.DialogCode.Rejected

        warnings = self._open_and_execute(harness, execute)
        self.assertEqual(
            warnings,
            ["The active bid or authoritative Condition family changed."],
        )

    def test_external_family_replacement_during_no_change_navigation_closes_dialog(
        self,
    ):
        harness = self._make_harness()

        def execute(dialog):
            harness.data.conditions = {
                uid: replace(condition)
                for uid, condition in harness.data.conditions.items()
            }
            harness.sidebar.load_conditions(
                harness.data.conditions, harness.data.folders, "Project"
            )
            dialog._on_next()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
            self.assertEqual(harness.sidebar.get_selected_condition_uids(), ["c1"])
            return QtWidgets.QDialog.DialogCode.Rejected

        warnings = self._open_and_execute(harness, execute)
        self.assertEqual(warnings, [])
        self.assertEqual(harness.writer.writes, [])

    def test_bid_switch_and_access_revocation_still_reject_saves(self):
        harness = self._make_harness()

        def execute(dialog):
            harness.active_bid[0] = BidRef("other.mdb", "8")
            dialog._name_edit.setText("Must not save")
            dialog._on_apply()
            self.assertEqual(harness.writer.writes, [])
            harness.active_bid[0] = harness.bid_ref
            _Access.allowed = False
            dialog._on_apply()
            self.assertEqual(harness.writer.writes, [])
            dialog._dirty = False
            dialog.reject()
            return QtWidgets.QDialog.DialogCode.Rejected

        warnings = self._open_and_execute(harness, execute)
        self.assertEqual(
            warnings,
            [
                "The active bid or edit access changed.",
                "The active bid or edit access changed.",
            ],
        )
