from tests.helpers.workspace_state import make_workspace_state_model
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.handlers.condition_action_handler import (
    ConditionActionHandler,
)
from ost_visualizer.presentation.dialogs.edit_condition_dialog import (
    EditConditionDialog,
)
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.utils.ost_blocking import exec_with_ost_blocking
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.application.dtos.update_condition_dto import (
    UpdateConditionResultDto,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    EditLeaseHandle,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
)
from shiboken6 import delete, isValid
from PySide6 import QtCore, QtWidgets
from unittest.mock import patch
from types import SimpleNamespace
from dataclasses import replace
import unittest
import os
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.collaboration_dtos import (
    EditLeaseHandle,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from PySide6 import QtWidgets


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


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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
        reconstructed[condition_uid] = replace(reconstructed[condition_uid], **changes)
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

    def _make_mdb_creation_harness(self, *, foldered):
        from ost_visualizer.application.services.project_write_service import (
            ProjectWriteService,
        )
        from ost_visualizer.application.use_cases.project.load_bid_use_case import (
            LoadBidUseCase,
        )
        from ost_visualizer.application.use_cases.project.reload_database_use_case import (
            ReloadDatabaseUseCase,
        )
        from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
        from ost_visualizer.domain.entities.file_results import (
            BidLoadResult,
            FileLoadResult,
        )
        from ost_visualizer.domain.entities.hierarchy_data import (
            HierarchyBidInfo,
            HierarchyData,
            HierarchyFileEntry,
        )
        from ost_visualizer.domain.services.project_data_service import (
            ProjectDataService,
        )
        from ost_visualizer.application.events.app_events import AppEvents
        import logging

        harness = self._make_harness(foldered=foldered)
        persisted = dict(harness.data.conditions)
        folders = dict(harness.data.folders)
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    harness.bid_ref.file_path,
                    orphan_bids=[HierarchyBidInfo("7", name="Project")],
                )
            ]
        )
        manager = SimpleNamespace(
            current_file_path=harness.bid_ref.file_path,
            apply_bid_load=lambda _path: None,
            prepare_bid_load=lambda *_args: BidLoadResult(
                bid_conditions={uid: replace(cond) for uid, cond in persisted.items()},
                bid_condition_folders={
                    uid: replace(folder) for uid, folder in folders.items()
                },
            ),
            reload_database=lambda *_args, **_kwargs: FileLoadResult(True, hierarchy),
            project_repository=SimpleNamespace(get_cdn_types=lambda _path: {}),
        )
        model = OstAggregate(manager)
        model.set_hierarchy(hierarchy)
        data = ProjectDataService(model)
        loader = LoadBidUseCase(
            model,
            data,
            manager,
            SimpleNamespace(load_bid=lambda *_args: None),
            SimpleNamespace(uses_sql_workspace=lambda _path: False),
        )
        self.assertTrue(loader.execute(harness.bid_ref))
        reloader = ReloadDatabaseUseCase(model, manager, loader)
        service = object.__new__(ProjectWriteService)
        service._project_data = data
        service._event_bus = harness.event_bus
        service.logger = logging.getLogger(__name__)
        service._reload_database = Mock(wraps=reloader.execute_after_write)
        service.uses_sql_collaboration_mutations = lambda _path: False
        service._bid_write_guard = SimpleNamespace(
            blocks_active_locked_bid_write=lambda *_args: False,
        )
        service._execute_database_mutation = (
            lambda _db, _resources, operation: SimpleNamespace(
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=operation(Mock()),
            )
        )
        writes = []

        def insert(_database, _bid, spec):
            writes.append(spec)
            persisted["4"] = Condition(
                uid="4",
                name=spec.name,
                condition_type=spec.condition_type,
                folder_uid=spec.folder_uid,
                ref_no=4,
            )
            return "4"

        service._insert_condition = SimpleNamespace(execute=insert)
        harness.handler._write_service = service
        harness.handler._project_data = data
        harness.data = data
        harness.writer = service
        harness.writes = writes
        harness.event_bus.subscribe(
            AppEvents.CONDITIONS_CHANGED,
            lambda **_event: harness.sidebar.load_conditions(
                data.get_bid_conditions(), data.get_bid_condition_folders(), "Project"
            ),
        )
        return harness

    def test_mdb_navigation_uses_targeted_writer_projection_without_bid_reload(self):
        from ost_visualizer.application.events.app_events import AppEvents

        harness = self._make_mdb_creation_harness(foldered=True)
        data = harness.data
        original_bid = data.get_bid(harness.bid_ref)
        persisted = dict(data.get_bid_conditions())
        folders = dict(data.get_bid_condition_folders())
        writes = []
        events = []

        def update(database, bid_uid, uid, dto):
            self.assertEqual((database, bid_uid), (harness.bid_ref.file_path, "7"))
            persisted[uid] = replace(persisted[uid], **dto.get_changes())
            writes.append(uid)
            return UpdateConditionResultDto(success=True)

        harness.writer._update_condition = SimpleNamespace(execute=update)
        reader = Mock(
            side_effect=lambda *_args: (
                {uid: replace(condition) for uid, condition in persisted.items()},
                {uid: replace(folder) for uid, folder in folders.items()},
            )
        )
        harness.writer._condition_family_reader = reader
        harness.event_bus.subscribe(
            AppEvents.CONDITIONS_CHANGED, lambda **event: events.append(event)
        )
        broad_refreshes = []
        harness.event_bus.subscribe(
            AppEvents.DATABASE_REFRESHED,
            lambda **event: broad_refreshes.append(event),
        )

        def execute(dialog):
            for button, target_uid in (
                (dialog._next_btn, "c2"),
                (dialog._next_btn, "c3"),
                (dialog._prev_btn, "c2"),
                (dialog._prev_btn, "c1"),
            ):
                previous = dict(data.get_bid_conditions())
                source_uid = dialog._current_uid
                name = f"Saved {source_uid} before {target_uid}"
                dialog._name_edit.setText(name)
                button.click()
                self.assertEqual(dialog._current_uid, target_uid)
                self.assertEqual(
                    harness.sidebar.get_selected_condition_uids(), [target_uid]
                )
                self.assertEqual(data.get_bid_conditions()[source_uid].name, name)
                self.assertIs(data.get_bid(harness.bid_ref), original_bid)
                for uid, owner in previous.items():
                    self.assertIsNot(data.get_bid_conditions()[uid], owner)
                    self.assertIs(
                        dialog._conditions_map[uid], data.get_bid_conditions()[uid]
                    )
            dialog.reject()
            return QtWidgets.QDialog.DialogCode.Rejected

        self.assertEqual(self._open_and_execute(harness, execute), [])
        self.assertEqual(writes, ["c1", "c2", "c3", "c2"])
        self.assertEqual(reader.call_count, 4)
        self.assertEqual(
            [event["condition_uids"] for event in events], [[uid] for uid in writes]
        )
        self.assertTrue(all(event["local_completion"] for event in events))
        self.assertEqual(broad_refreshes, [])
        harness.writer._reload_database.assert_not_called()

    def test_mdb_creation_accepts_own_full_bid_reconstruction(self):
        for foldered in (False, True):
            with self.subTest(foldered=foldered):
                harness = self._make_mdb_creation_harness(foldered=foldered)
                original_bid = harness.data.get_bid(harness.bid_ref)
                warnings = []

                def execute(dialog, _events):
                    self.widgets.append(dialog)
                    dialog._name_edit.setText("Created once")
                    dialog._ref_no_edit.setText("4")
                    dialog._ok_btn.click()
                    self.assertIsNot(
                        harness.data.get_bid(harness.bid_ref), original_bid
                    )
                    self.assertEqual(len(harness.writes), 1)
                    self.assertEqual(
                        dialog.result(), QtWidgets.QDialog.DialogCode.Accepted, warnings
                    )
                    return dialog.result()

                with patch(
                    "ost_visualizer.presentation.handlers.condition_action_handler.exec_with_ost_blocking",
                    execute,
                ), patch(
                    "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning",
                    side_effect=lambda _parent, _title, message: warnings.append(
                        message
                    ),
                ):
                    harness.handler.on_create_requested("f1" if foldered else "")
                self.assertEqual(warnings, [])
                self.assertEqual(harness.sidebar.get_selected_condition_uids(), ["4"])
                harness.writer._reload_database.assert_called_once_with(
                    harness.bid_ref.file_path
                )

    def test_mdb_creation_refresh_failure_closes_committed_draft_and_warns_once(self):
        harness = self._make_mdb_creation_harness(foldered=True)
        harness.writer._reload_database = Mock(return_value=False)
        warnings = []

        def execute(dialog, _events):
            self.widgets.append(dialog)
            dialog._name_edit.setText("Committed but not refreshed")
            dialog._ref_no_edit.setText("4")
            dialog._ok_btn.click()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertFalse(dialog._dirty)
            return dialog.result()

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "exec_with_ost_blocking",
            execute,
        ), patch(
            "ost_visualizer.presentation.handlers.condition_action_handler.show_warning",
            side_effect=lambda _parent, _title, message: warnings.append(message),
        ):
            harness.handler.on_create_requested("f1")
        self.assertEqual(len(harness.writes), 1)
        self.assertEqual(harness.highlights, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("created, but the conditions list could not be", warnings[0])
        harness.writer._reload_database.assert_called_once_with(
            harness.bid_ref.file_path
        )

    def test_committed_mdb_creation_does_not_adopt_replacements_from_event_consumers(
        self,
    ):
        from ost_visualizer.application.events.app_events import AppEvents

        for target in ("bid", "condition", "folder", "selection"):
            with self.subTest(target=target):
                harness = self._make_mdb_creation_harness(foldered=True)
                warnings = []

                def replace_owner(**_event):
                    model = harness.data.model
                    if target == "bid":
                        model.current_bid = replace(model.current_bid)
                    elif target == "condition":
                        model.bid_conditions["4"] = replace(model.bid_conditions["4"])
                    elif target == "folder":
                        model.bid_condition_folders["f1"] = replace(
                            model.bid_condition_folders["f1"]
                        )
                    else:
                        harness.active_bid[0] = BidRef("other.mdb", "7")

                harness.event_bus.subscribe(AppEvents.CONDITIONS_CHANGED, replace_owner)

                def execute(dialog, _events):
                    self.widgets.append(dialog)
                    dialog._name_edit.setText("Committed once")
                    dialog._ref_no_edit.setText("4")
                    dialog._ok_btn.click()
                    self.assertEqual(
                        dialog.result(), QtWidgets.QDialog.DialogCode.Accepted, warnings
                    )
                    self.assertFalse(dialog._dirty)
                    self.assertEqual(len(harness.writes), 1)
                    return dialog.result()

                with patch(
                    "ost_visualizer.presentation.handlers.condition_action_handler.exec_with_ost_blocking",
                    execute,
                ), patch(
                    "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning",
                    side_effect=lambda _parent, _title, message: warnings.append(
                        message
                    ),
                ):
                    harness.handler.on_create_requested("f1")
                self.assertEqual(warnings, [])
                self.assertEqual(harness.highlights, [])

    def test_committed_sql_creation_closes_without_projecting_into_replacement_bid(
        self,
    ):
        harness = self._make_harness(sql=True, foldered=True)
        queue_create = harness.writer.queue_condition_create
        committed_calls = []

        def replace_before_completion(database, bid, spec, completed):
            def committed(result):
                committed_calls.append(result)
                harness.data.bid = SimpleNamespace(measure_base=0, name="Replacement")
                completed(result)

            return queue_create(database, bid, spec, committed)

        harness.writer.queue_condition_create = replace_before_completion
        warnings = []

        def execute(dialog, _events):
            self.widgets.append(dialog)
            dialog._name_edit.setText("Committed once")
            dialog._ref_no_edit.setText("4")
            dialog._ok_btn.click()
            self.assertEqual(
                dialog.result(), QtWidgets.QDialog.DialogCode.Accepted, warnings
            )
            self.assertFalse(dialog._dirty)
            return dialog.result()

        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler.exec_with_ost_blocking",
            execute,
        ), patch(
            "ost_visualizer.presentation.dialogs.edit_condition_dialog.show_warning",
            side_effect=lambda _parent, _title, message: warnings.append(message),
        ):
            harness.handler.on_create_requested("f1")
        self.assertEqual(warnings, [])
        self.assertEqual(len(committed_calls), 1)
        self.assertEqual(harness.highlights, [])
        self.assertEqual(harness.handler._pending_sql_operations, set())

    def test_created_condition_replacement_on_dialog_accept_is_not_highlighted(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                harness = (
                    self._make_harness(sql=True, foldered=True)
                    if sql
                    else self._make_mdb_creation_harness(foldered=True)
                )
                uid = "c4" if sql else "4"

                def execute(dialog, _events):
                    self.widgets.append(dialog)

                    def replace_created_condition():
                        conditions = harness.data.get_bid_conditions()
                        conditions[uid] = replace(conditions[uid])

                    dialog.accepted.connect(replace_created_condition)
                    dialog._name_edit.setText("Committed once")
                    dialog._ref_no_edit.setText("4")
                    dialog._ok_btn.click()
                    self.assertEqual(
                        dialog.result(), QtWidgets.QDialog.DialogCode.Accepted
                    )
                    return dialog.result()

                with patch(
                    "ost_visualizer.presentation.handlers.condition_action_handler."
                    "exec_with_ost_blocking",
                    execute,
                ):
                    harness.handler.on_create_requested("f1")
                self.assertEqual(harness.highlights, [])

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

    def test_save_navigation_recovers_cleared_selection_before_subsequent_save(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                harness = self._make_harness(sql=sql, foldered=True)
                cleared_selections = []

                def clear_projection_selection():
                    harness.sidebar.highlight_conditions(set())
                    cleared_selections.append(
                        harness.sidebar.get_selected_condition_uids()
                    )

                harness.writer.after_reconstruct = clear_projection_selection
                observed = []

                def execute(dialog):
                    dialog._name_edit.setText("First saved")
                    dialog._next_btn.click()
                    observed.append(
                        (
                            dialog._current_uid,
                            harness.sidebar.get_selected_condition_uids(),
                        )
                    )
                    # Exercise the subsequent save even if navigation lost selection,
                    # so the historical failure also proves the spurious access error.
                    dialog._name_edit.setText("Second saved")
                    dialog._apply_btn.click()
                    observed.append(
                        (
                            dialog._current_uid,
                            harness.sidebar.get_selected_condition_uids(),
                        )
                    )
                    dialog._dirty = False
                    dialog.reject()
                    return QtWidgets.QDialog.DialogCode.Rejected

                warnings = self._open_and_execute(harness, execute)
                self.assertEqual(warnings, [], (observed, harness.writer.writes))
                self.assertEqual(cleared_selections, [[], []])
                self.assertEqual(observed, [("c2", ["c2"]), ("c2", ["c2"])])
                self.assertEqual(
                    [uid for uid, _changes in harness.writer.writes], ["c1", "c2"]
                )
                self.assertEqual(harness.data.conditions["c2"].name, "Second saved")
                self.assertEqual(harness.handler._pending_sql_operations, set())

    def test_real_modal_save_yes_navigation_rebinds_every_condition(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                harness = self._make_harness(sql=sql, foldered=True)
                if sql:
                    queue_update = harness.writer.queue_conditions_update

                    def enqueue(*args, **kwargs):
                        QtCore.QTimer.singleShot(
                            0, lambda: queue_update(*args, **kwargs)
                        )
                        return len(harness.writer.writes) + 1

                    harness.writer.queue_conditions_update = enqueue
                errors = []
                prompts = []
                warnings = []

                def answer_message_box():
                    box = self.app.activeModalWidget()
                    if not isinstance(box, QtWidgets.QMessageBox):
                        return
                    if box.text() == "Do you want to save your changes?":
                        prompts.append(box.text())
                        box.button(QtWidgets.QMessageBox.StandardButton.Yes).click()
                    else:
                        warnings.append(box.text())
                        box.accept()

                def interact():
                    dialog = self.app.activeModalWidget()
                    try:
                        self.assertIsInstance(dialog, EditConditionDialog)
                        self.widgets.append(dialog)
                        for target_uid, button in (
                            ("c2", dialog._next_btn),
                            ("c3", dialog._next_btn),
                            ("c2", dialog._prev_btn),
                            ("c1", dialog._prev_btn),
                        ):
                            old_owners = dict(harness.data.conditions)
                            source_uid = dialog._current_uid
                            edited_name = f"Edited before {target_uid}"
                            dialog._name_edit.setText(edited_name)
                            button.click()
                            deadline = QtCore.QDeadlineTimer(2000)
                            while dialog._save_pending and not deadline.hasExpired():
                                self.app.processEvents()
                            self.assertFalse(dialog._save_pending)
                            self.assertEqual(dialog._current_uid, target_uid)
                            self.assertEqual(
                                harness.sidebar.get_selected_condition_uids(),
                                [target_uid],
                            )
                            self.assertEqual(
                                harness.data.conditions[source_uid].name, edited_name
                            )
                            for uid, owner in old_owners.items():
                                self.assertIsNot(harness.data.conditions[uid], owner)
                                self.assertIs(
                                    dialog._conditions_map[uid],
                                    harness.data.conditions[uid],
                                )
                        self.assertFalse(dialog._prev_btn.isEnabled())
                    except Exception as error:
                        errors.append(error)
                    finally:
                        if isinstance(dialog, EditConditionDialog) and isValid(dialog):
                            dialog._dirty = False
                            dialog.reject()

                responder = QtCore.QTimer(harness.sidebar)
                responder.timeout.connect(answer_message_box)
                responder.start(1)
                QtCore.QTimer.singleShot(0, interact)
                try:
                    harness.handler.on_edit_requested(["c1"])
                finally:
                    responder.stop()
                if errors:
                    raise errors[0]
                self.assertEqual(len(prompts), 4)
                self.assertEqual(warnings, [])
                self.assertEqual(len(harness.writer.writes), 4)
                self.assertEqual(harness.handler._pending_sql_operations, set())
                if sql:
                    self.assertEqual(len(harness.lease_requests), 5)
                    self.assertEqual(harness.ended_leases, harness.lease_handles[-1:])

    def test_external_replacement_after_own_save_is_not_adopted(self):
        for sql in (False, True):
            for replaced_uid in ("c1", "c2", "c3"):
                with self.subTest(sql=sql, replaced_uid=replaced_uid):
                    harness = self._make_harness(sql=sql, foldered=True)

                    def execute(dialog):
                        dialog._name_edit.setText("Saved draft")
                        dialog._next_btn.click()
                        self.assertEqual(dialog._current_uid, "c2")
                        replacement = replace(harness.data.conditions[replaced_uid])
                        harness.data.conditions[replaced_uid] = replacement
                        dialog._name_edit.setText("Must not save")
                        dialog._apply_btn.click()
                        self.assertEqual(len(harness.writer.writes), 1)
                        self.assertIs(
                            harness.data.conditions[replaced_uid], replacement
                        )
                        self.assertEqual(
                            harness.data.conditions["c2"].name, "Condition 2"
                        )
                        dialog._dirty = False
                        dialog.reject()
                        return QtWidgets.QDialog.DialogCode.Rejected

                    self.assertEqual(
                        self._open_and_execute(harness, execute),
                        ["The active bid or edit access changed."],
                    )

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
            self.assertEqual(dialog._current_uid, "c2")
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

    def test_sql_navigation_ignores_old_lease_loss_but_rejects_current_lease_loss(self):
        from ost_visualizer.application.dtos.collaboration_dtos import EditLeaseLoss
        from ost_visualizer.application.events.app_events import AppEvents

        harness = self._make_harness(sql=True, foldered=True)
        rejected = []

        def lose_lease(handle):
            harness.event_bus.publish(
                AppEvents.EDIT_LEASE_LOST,
                loss=EditLeaseLoss(
                    database_id=handle.database_id,
                    draft_id=handle.draft_id,
                    runtime_generation=handle.runtime_generation,
                    operation_id=handle.operation_id,
                    owning_surface=handle.owning_surface,
                    resources=handle.resources,
                    reason="test-lease-loss",
                ),
            )

        def execute(dialog):
            dialog.show()
            dialog.rejected.connect(lambda: rejected.append(True))
            original_lease = harness.lease_handles[-1]
            dialog._name_edit.setText("Saved before lease transition")
            dialog._next_btn.click()
            current_lease = harness.lease_handles[-1]
            self.assertIsNot(current_lease, original_lease)
            self.assertEqual(dialog._current_uid, "c2")
            self.assertEqual(harness.sidebar.get_selected_condition_uids(), ["c2"])
            lose_lease(original_lease)
            self.assertEqual(rejected, [])
            self.assertTrue(dialog.isVisible())
            self.assertEqual(harness.sidebar.get_selected_condition_uids(), ["c2"])
            lose_lease(current_lease)
            self.assertEqual(rejected, [True])
            self.assertFalse(dialog.isVisible())
            self.assertEqual(len(harness.writer.writes), 1)
            self.assertEqual(harness.handler._pending_sql_operations, set())
            return QtWidgets.QDialog.DialogCode.Rejected

        self.assertEqual(self._open_and_execute(harness, execute), [])
        self.assertEqual(len(harness.lease_requests), 2)
        self.assertEqual(harness.ended_leases, [])

    def test_sql_navigation_rejects_replacement_while_reacquiring_edit_lease(self):
        harness = self._make_harness(sql=True)
        coordinator = harness.handler._coordinator
        request_lease = coordinator.request_collaboration_edit
        pending_grants = []

        def delay_reacquisition(database_id, resources, callback, **options):
            if harness.writer.writes:
                pending_grants.append(
                    lambda: request_lease(database_id, resources, callback, **options)
                )
            else:
                request_lease(database_id, resources, callback, **options)

        coordinator.request_collaboration_edit = delay_reacquisition

        def execute(dialog):
            dialog._name_edit.setText("Committed edit")
            dialog._next_btn.click()
            self.assertEqual(len(harness.writer.writes), 1)
            self.assertEqual(len(pending_grants), 1)
            self.assertEqual(dialog._current_uid, "c1")
            reconstructed = harness.data.conditions["c2"]
            harness.data.conditions["c2"] = replace(reconstructed)
            self.assertIsNot(harness.data.conditions["c2"], reconstructed)
            pending_grants.pop()()
            self.assertEqual(dialog._current_uid, "c1")
            self.assertEqual(harness.sidebar.get_selected_condition_uids(), ["c1"])
            dialog._dirty = False
            dialog.reject()
            return QtWidgets.QDialog.DialogCode.Rejected

        warnings = self._open_and_execute(harness, execute)
        self.assertEqual(
            warnings, ["The active bid or authoritative Condition family changed."]
        )
        self.assertEqual(len(harness.writer.writes), 1)

    def test_delayed_sql_next_previous_saves_project_once_and_keep_editing(self):
        harness = self._make_harness(sql=True, foldered=True)
        queue_update = harness.writer.queue_conditions_update
        pending = []

        def enqueue(*args, **kwargs):
            pending.append(lambda: queue_update(*args, **kwargs))
            return len(harness.writer.writes) + 1

        harness.writer.queue_conditions_update = enqueue

        def execute(dialog):
            for expected_uid, button in (
                ("c2", dialog._next_btn),
                ("c3", dialog._next_btn),
                ("c2", dialog._prev_btn),
                ("c1", dialog._prev_btn),
            ):
                previous_uid = dialog._current_uid
                prior_writes = len(harness.writer.writes)
                dialog._name_edit.setText(f"Revision {prior_writes}")
                button.click()
                self.assertTrue(dialog._save_pending)
                self.assertEqual(dialog._current_uid, previous_uid)
                self.assertEqual(len(harness.writer.writes), prior_writes)
                self.assertEqual(len(pending), 1)
                pending.pop()()
                self.assertFalse(dialog._save_pending)
                self.assertEqual(dialog._current_uid, expected_uid)
                self.assertIs(
                    dialog._current_condition(), harness.data.conditions[expected_uid]
                )
                self.assertEqual(
                    harness.sidebar.get_selected_condition_uids(), [expected_uid]
                )
                self.assertEqual(len(harness.writer.writes), prior_writes + 1)
            self.assertFalse(dialog._prev_btn.isEnabled())
            dialog.reject()
            return QtWidgets.QDialog.DialogCode.Rejected

        self.assertEqual(self._open_and_execute(harness, execute), [])
        self.assertEqual(len(harness.lease_requests), 5)
        for resources in harness.lease_requests:
            self.assertEqual(
                resources,
                tuple(ResourceRef("condition", uid, 7) for uid in ("c1", "c2", "c3")),
            )
        self.assertEqual(harness.handler._pending_sql_operations, set())

    def test_destroyed_editor_during_pending_sql_save_does_not_reacquire_or_project(
        self,
    ):
        harness = self._make_harness(sql=True)
        queue_update = harness.writer.queue_conditions_update
        pending = []

        def enqueue(*args, **kwargs):
            pending.append(lambda: queue_update(*args, **kwargs))
            return 1

        harness.writer.queue_conditions_update = enqueue

        def execute(dialog):
            dialog._name_edit.setText("Committed after editor destruction")
            dialog._next_btn.click()
            self.assertTrue(dialog._save_pending)
            self.assertEqual(len(pending), 1)
            delete(dialog)
            prior_highlights = list(harness.highlights)
            pending.pop()()
            self.assertEqual(harness.highlights, prior_highlights)
            self.assertEqual(len(harness.lease_requests), 1)
            return QtWidgets.QDialog.DialogCode.Rejected

        self.assertEqual(self._open_and_execute(harness, execute), [])
        self.assertEqual(len(harness.writer.writes), 1)
        self.assertEqual(
            harness.data.conditions["c1"].name,
            "Committed after editor destruction",
        )
        self.assertEqual(harness.handler._pending_sql_operations, set())

    def test_destroyed_editor_releases_late_post_save_lease_without_selection(self):
        harness = self._make_harness(sql=True)
        coordinator = harness.handler._coordinator
        request_lease = coordinator.request_collaboration_edit
        pending_grants = []

        def delay_reacquisition(database_id, resources, callback, **options):
            if harness.writer.writes:
                pending_grants.append(
                    lambda: request_lease(database_id, resources, callback, **options)
                )
            else:
                request_lease(database_id, resources, callback, **options)

        coordinator.request_collaboration_edit = delay_reacquisition

        def execute(dialog):
            dialog._name_edit.setText("Saved before lease completion")
            dialog._next_btn.click()
            self.assertTrue(dialog._save_pending)
            self.assertEqual(len(pending_grants), 1)
            delete(dialog)
            prior_highlights = list(harness.highlights)
            pending_grants.pop()()
            self.assertEqual(harness.highlights, prior_highlights)
            self.assertEqual(harness.ended_leases, harness.lease_handles[-1:])
            return QtWidgets.QDialog.DialogCode.Rejected

        self.assertEqual(self._open_and_execute(harness, execute), [])
        self.assertEqual(len(harness.writer.writes), 1)
        self.assertEqual(harness.handler._pending_sql_operations, set())

    def test_discard_cancel_and_unchanged_navigation_keep_real_sidebar_selection(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                harness = self._make_harness(sql=sql, foldered=True)

                def execute(dialog):
                    dialog._next_btn.click()
                    self.assertEqual(dialog._current_uid, "c2")
                    self.assertEqual(
                        harness.sidebar.get_selected_condition_uids(), ["c2"]
                    )
                    dialog._name_edit.setText("Unsaved draft")
                    with patch(
                        "ost_visualizer.presentation.dialogs.edit_condition_dialog."
                        "confirm_save_discard_cancel",
                        return_value=None,
                    ):
                        dialog._next_btn.click()
                    self.assertEqual(dialog._current_uid, "c2")
                    self.assertEqual(
                        harness.sidebar.get_selected_condition_uids(), ["c2"]
                    )
                    with patch(
                        "ost_visualizer.presentation.dialogs.edit_condition_dialog."
                        "confirm_save_discard_cancel",
                        return_value=False,
                    ):
                        dialog._prev_btn.click()
                    self.assertEqual(dialog._current_uid, "c1")
                    self.assertEqual(
                        harness.sidebar.get_selected_condition_uids(), ["c1"]
                    )
                    dialog.reject()
                    return QtWidgets.QDialog.DialogCode.Rejected

                self.assertEqual(self._open_and_execute(harness, execute), [])
                self.assertEqual(harness.writer.writes, [])

    def test_delayed_initial_lease_does_not_open_destroyed_condition_dialog(self):
        harness = self._make_harness(sql=True)
        coordinator = harness.handler._coordinator
        request_lease = coordinator.request_collaboration_edit
        pending_grants = []

        def delay_initial(database_id, resources, callback, **options):
            pending_grants.append(
                lambda: request_lease(database_id, resources, callback, **options)
            )

        coordinator.request_collaboration_edit = delay_initial
        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler."
            "exec_with_ost_blocking",
            wraps=exec_with_ost_blocking,
        ) as execute:
            harness.handler.on_edit_requested(["c1"])
            self.assertEqual(len(pending_grants), 1)
            delete(harness.sidebar)
            pending_grants.pop()()
        execute.assert_not_called()
        self.assertEqual(harness.ended_leases, harness.lease_handles)

    def test_external_delete_or_renumber_rejects_subsequent_dialog_save(self):
        for sql in (False, True):
            for change in ("delete", "renumber"):
                with self.subTest(sql=sql, change=change):
                    harness = self._make_harness(sql=sql)

                    def execute(dialog):
                        if change == "delete":
                            harness.data.conditions.pop("c2")
                        else:
                            harness.data.conditions["c2"] = replace(
                                harness.data.conditions["c2"], ref_no=20
                            )
                        dialog._name_edit.setText("Stale draft")
                        dialog._next_btn.click()
                        self.assertEqual(dialog._current_uid, "c1")
                        self.assertEqual(harness.writer.writes, [])
                        dialog._dirty = False
                        dialog.reject()
                        return QtWidgets.QDialog.DialogCode.Rejected

                    self.assertEqual(
                        self._open_and_execute(harness, execute),
                        ["The active bid or edit access changed."],
                    )

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


class ConditionRepeatedSaveOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_condition_handler_rebinds_same_dialog_after_each_mdb_or_sql_save(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                original = Condition(uid="1", name="Original", ref_no=1)
                conditions = {"1": original}
                saves = []
                handles = []
                sidebar = QtWidgets.QWidget()
                sidebar.collect_ordered_condition_uids = lambda: ["1"]
                bid_ref = BidRef("sql-id" if sql else "test.mdb", "7")
                bid_owner = SimpleNamespace(measure_base=0)
                data = SimpleNamespace(
                    is_current_bid_locked=lambda: False,
                    get_bid_conditions=lambda: conditions,
                    get_all_takeoffs=lambda: [],
                    get_current_bid=lambda: bid_owner,
                    get_bid=lambda _bid_ref: bid_owner,
                    get_cdn_types=lambda: {},
                    get_bid_layer_snapshot=lambda: [],
                    get_layer_uids_in_use=lambda: set(),
                )
                read = FakeReadService()
                read.get_cdn_types = lambda _db: {}
                read.get_merged_bid_layers = lambda _db, _bid: []

                def update(_database, _bid, uid, dto):
                    conditions[uid] = replace(conditions[uid], **dto.get_changes())
                    saves.append(conditions[uid])
                    return UpdateConditionResultDto(success=True)

                def queue(
                    database, _bid, uids, changes, completed, *, edit_lease_handle
                ):
                    conditions[uids[0]] = replace(conditions[uids[0]], **changes)
                    saves.append(conditions[uids[0]])
                    handles.append(edit_lease_handle)
                    completed(
                        QueuedMutationResult(
                            database_id=database,
                            runtime_generation=1,
                            operation_id="00000000-0000-0000-0000-000000000001",
                            outcome_status=MutationOutcomeStatus.COMMITTED,
                        )
                    )
                    return len(saves)

                def grant(database, resources, completed, **options):
                    completed(
                        EditLeaseResult(
                            True,
                            handle=EditLeaseHandle(
                                database,
                                f"draft-{len(saves)}",
                                1,
                                options["operation_id"],
                                options["owning_surface"],
                                resources,
                            ),
                        )
                    )

                coordinator = SimpleNamespace(
                    ui_access_manager=Mock(),
                    conditions_sidebar=sidebar,
                    main_window=SimpleNamespace(icon_provider=None),
                    event_bus=EventBus(),
                    highlight_sidebar=Mock(),
                    placement=SimpleNamespace(is_active=False),
                    flush_deferred_for_file=lambda _database: True,
                    request_collaboration_edit=grant,
                    end_collaboration_edit=Mock(),
                )
                coordinator.ui_access_manager.is_allowed.return_value = True
                service = SimpleNamespace(
                    uses_sql_collaboration_mutations=lambda _db: sql,
                    update_condition=update,
                    queue_conditions_update=queue,
                )
                handler = ConditionActionHandler(
                    coordinator,
                    service,
                    read,
                    data,
                    SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
                    make_workspace_state_model(),
                )

                def interact(dialog, _events):
                    dialog.show()
                    try:
                        self.assertIs(dialog._current_condition(), original)
                        for name in ("Second", "Third"):
                            previous = dialog._current_condition()
                            dialog._name_edit.setText(name)
                            dialog._on_apply()
                            self.assertIsNot(conditions["1"], previous)
                            self.assertIs(dialog._current_condition(), conditions["1"])
                            self.assertEqual(dialog._current_condition().name, name)
                            self.assertFalse(dialog._dirty)
                            self.assertTrue(dialog.isVisible())
                        return QtWidgets.QDialog.DialogCode.Rejected
                    finally:
                        dialog.reject()

                try:
                    with patch(
                        "ost_visualizer.presentation.handlers.condition_action_handler.exec_with_ost_blocking",
                        side_effect=interact,
                    ):
                        handler.on_edit_requested(["1"])
                    self.assertEqual(len(saves), 2)
                    if sql:
                        self.assertIsNot(handles[0], handles[1])
                finally:
                    sidebar.close()
                    sidebar.deleteLater()
