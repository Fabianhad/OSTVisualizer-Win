import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    EditLeaseHandle,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.services.project_write_service import (
    BatchWriteResult,
    WriteReloadResult,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.main_window import MainWindow
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from tests.presentation.dialogs.master_data_support import (
    FakeIconProvider as _master_data_support_FakeIconProvider,
    _app as _master_data_support__app,
)


class MasterDataCoordinatorDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def tearDown(self):
        self.app.processEvents()

    def _default_layer(
        self, uid: str, name: str, sequence: int, *, show: bool = True
    ) -> BidLayer:
        return BidLayer(
            uid=uid,
            bid_uid="",
            name=name,
            show=show,
            sequence=sequence,
            is_template=True,
            is_locked=True,
        )

    def test_open_areas_dialog_checks_current_usage_at_delete(self):
        used = {"area-1"}
        fail_query = False
        scans = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        bid_ref = BidRef("db.mdb", "bid-1")
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: bid_ref
        )
        coordinator.ui_access_manager = SimpleNamespace(is_allowed=lambda feature: True)

        def usage():
            scans.append(True)
            if fail_query:
                raise RuntimeError("usage query failed")
            return set(used)

        coordinator.project_data = SimpleNamespace(get_area_uids_with_takeoff=usage)
        coordinator._project_read_service = SimpleNamespace(
            get_bid_areas=lambda *args: [BidArea("area-1", "bid-1", "", "Area 1", 1)]
        )
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda path: False
        )
        coordinator._icon_provider = _master_data_support_FakeIconProvider()
        coordinator.main_window = None
        coordinator._workspace_state_model = make_workspace_state_model()
        interacted = []

        def interact(dialog, *args):
            nonlocal fail_query
            interacted.append(dialog)
            try:
                item = dialog.tree.topLevelItem(0)
                dialog.tree.setCurrentItem(item)
                used.clear()
                with (
                    patch.object(QtWidgets.QMessageBox, "warning") as warning,
                    patch.object(
                        QtWidgets.QMessageBox,
                        "question",
                        return_value=QtWidgets.QMessageBox.StandardButton.No,
                    ) as question,
                ):
                    dialog._on_delete()
                self.assertEqual(warning.call_count, 0)
                self.assertEqual(question.call_count, 1)
                self.assertEqual(len(scans), 1)
                used.add("area-1")
                with (
                    patch.object(QtWidgets.QMessageBox, "warning") as warning,
                    patch.object(QtWidgets.QMessageBox, "question") as question,
                ):
                    dialog._on_delete()
                self.assertEqual(warning.call_count, 1)
                self.assertEqual(question.call_count, 0)
                self.assertEqual(len(scans), 2)
                self.assertIs(dialog.tree.currentItem(), item)
                self.assertEqual(dialog._deleted_uids, [])
                fail_query = True
                with (
                    patch(
                        "ost_visualizer.presentation.dialogs.areas_dialog.show_warning"
                    ) as warning,
                    patch.object(QtWidgets.QMessageBox, "question") as question,
                    patch(
                        "ost_visualizer.presentation.dialogs.areas_dialog."
                        "confirm_multi_delete",
                        return_value=None,
                    ) as confirm,
                ):
                    dialog._on_delete()
                warning.assert_called_once_with(
                    dialog, "Delete Bid Area", "Failed to validate area usage."
                )
                self.assertEqual(question.call_count, 0)
                confirm.assert_not_called()
                self.assertEqual(len(scans), 3)
                self.assertEqual(dialog._deleted_uids, [])
                self.assertIs(dialog.tree.currentItem(), item)
                # Parent relationships still block deletion independently of usage.
                fail_query = False
                used.clear()
                item.addChild(dialog._make_item("child", "Child"))
                with patch.object(QtWidgets.QMessageBox, "warning") as warning:
                    dialog._on_delete()
                self.assertEqual(warning.call_count, 1)
                self.assertEqual(dialog._deleted_uids, [])
                item.takeChild(0)
            finally:
                dialog.cleanup()
                delete(dialog)

        coordinator._exec_with_collaboration_lease = interact
        coordinator.open_areas_dialog()
        # The assertions live inside the dialog callback, so prove it ran.
        self.assertEqual(len(interacted), 1)

    def _open_areas_dialog_with_capturing_dialog(self, *, saved, reload_ok):
        reload_calls = []
        warnings = []
        bid_ref = BidRef("db.mdb", "bid-1")

        class Access:
            def is_allowed(self, _feature):
                return True

        class UiState:
            selected_area_uid = None
            selected_file_path = bid_ref.file_path

            def get_selected_bid_ref(self):
                return bid_ref

        hierarchy_entry = HierarchyFileEntry(file_path=bid_ref.file_path)

        class ProjectData:
            def get_area_uids_with_takeoff(self):
                return set()

            def get_hierarchy(self):
                return HierarchyData(loaded_files=[hierarchy_entry])

        class ReadService:
            def get_bid_areas(self, file_path, bid_uid):
                return [BidArea("area-1", bid_uid, "", "Area 1", 1)]

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_file_path):
                return False

            def reload_and_notify(self, file_path):
                reload_calls.append(file_path)
                return reload_ok

        class CapturingAreasDialog:
            def __init__(
                self,
                icon_provider,
                workspace_state_model,
                parent=None,
                bid_areas=None,
                save_fn=None,
                used_uids=None,
                used_uids_fn=None,
                on_saved_fn=None,
                has_license=True,
                bid_ref=None,
                *,
                save_async_fn=None,
            ):
                pass

            def cleanup(self):
                pass

            def has_saved_changes(self):
                return saved

            def deleteLater(self):
                pass

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.ui_state_manager = UiState()
        coordinator.ui_access_manager = Access()
        coordinator.project_data = ProjectData()
        coordinator._project_read_service = ReadService()
        coordinator._project_write_service = WriteService()
        coordinator._icon_provider = _master_data_support_FakeIconProvider()

        def request_local_edit(
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
                        draft_id="areas-test-draft",
                        runtime_generation=0,
                        operation_id=operation_id,
                        owning_surface=owning_surface,
                        resources=resources,
                        dependency_resources=dependency_resources,
                    ),
                )
            )

        coordinator._sql_collaboration = SimpleNamespace(
            request_local_edit=request_local_edit,
            end_edit_lease=lambda _handle: None,
        )
        coordinator.main_window = None
        coordinator._workspace_state_model = make_workspace_state_model()
        coordinator.event_bus = EventBus()
        with (
            patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator."
                "BidAreasDialog",
                CapturingAreasDialog,
            ),
            patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator."
                "exec_with_ost_blocking",
                lambda _dialog, _event_bus: QtWidgets.QDialog.DialogCode.Rejected,
            ),
            patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator."
                "show_warning",
                lambda _parent, title, message: warnings.append((title, message)),
            ),
        ):
            UIEventCoordinator.open_areas_dialog(coordinator)
        return reload_calls, warnings

    def test_open_areas_dialog_refreshes_once_after_saved_changes(self):
        reload_calls, warnings = self._open_areas_dialog_with_capturing_dialog(
            saved=True, reload_ok=True
        )
        self.assertEqual(reload_calls, ["db.mdb"])
        self.assertEqual(warnings, [])

    def test_open_areas_dialog_does_not_refresh_without_saved_changes(self):
        # Negative control for the refresh test: same flow, nothing was saved.
        reload_calls, warnings = self._open_areas_dialog_with_capturing_dialog(
            saved=False, reload_ok=True
        )
        self.assertEqual(reload_calls, [])
        self.assertEqual(warnings, [])

    def test_open_areas_dialog_warns_when_refresh_after_save_fails(self):
        reload_calls, warnings = self._open_areas_dialog_with_capturing_dialog(
            saved=True, reload_ok=False
        )
        self.assertEqual(reload_calls, ["db.mdb"])
        self.assertEqual(
            warnings,
            [
                (
                    "Refresh Error",
                    "The bid area changes were saved, but the area list could not "
                    "be refreshed. Reopen the database to see the latest bid areas.",
                )
            ],
        )

    def test_sql_master_data_save_transfers_and_reacquires_modal_lease(self):
        database_id = "sql-database"
        lease_requests = []
        queued_handles = []
        queued_callbacks = []
        released_handles = []
        completions = []
        access_allowed = [True]

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_file_path):
                return True

            @staticmethod
            def queue_job_statuses_save(
                file_path,
                changes,
                callback,
                *,
                edit_lease_handle,
            ):
                self.assertEqual(file_path, database_id)
                self.assertTrue(changes["updated"])
                queued_handles.append(edit_lease_handle)
                queued_callbacks.append(callback)
                return 1

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = QtWidgets.QWidget()
        coordinator._workspace_state_model = make_workspace_state_model()
        coordinator._icon_provider = _master_data_support_FakeIconProvider()
        coordinator._editable_master_data_file_path = lambda: database_id
        coordinator._project_write_service = WriteService()
        coordinator._project_read_service = SimpleNamespace()
        hierarchy_entry = HierarchyFileEntry(file_path=database_id)
        coordinator.project_data = SimpleNamespace(
            get_job_status_snapshot=lambda _file_path: [
                JobStatus(uid="status-1", name="Bidding", locked=False, sequence=1)
            ],
            get_used_job_status_uids=lambda _file_path: set(),
            get_hierarchy=lambda: HierarchyData(loaded_files=[hierarchy_entry]),
        )
        coordinator.ui_state_manager = SimpleNamespace(
            selected_file_path=database_id,
            get_selected_bid_ref=lambda: None,
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: access_allowed[0]
        )
        coordinator.event_bus = EventBus()

        def request_local_edit(
            file_path,
            resources,
            callback,
            *,
            dependency_resources=(),
            operation_id="",
            owning_surface="desktop",
        ):
            handle = EditLeaseHandle(
                database_id=file_path,
                draft_id=f"draft-{len(lease_requests) + 1}",
                runtime_generation=1,
                operation_id=operation_id,
                owning_surface=owning_surface,
                resources=resources,
                dependency_resources=dependency_resources,
            )
            lease_requests.append(handle)
            callback(EditLeaseResult(True, handle=handle))

        coordinator._sql_collaboration = SimpleNamespace(
            request_local_edit=request_local_edit,
            end_edit_lease=released_handles.append,
        )

        def exercise_save(dialog, _event_bus):
            started = dialog._save_async_fn(
                {
                    "new": [],
                    "updated": [
                        JobStatus(
                            uid="status-1",
                            name="Awarded",
                            locked=False,
                            sequence=1,
                        )
                    ],
                    "deleted_uids": [],
                },
                lambda success, mapping: completions.append((success, mapping)),
            )
            self.assertTrue(started)
            # The lease now belongs to the queued mutation: a second save while
            # it is in flight is refused without touching the queue.
            self.assertFalse(
                dialog._save_async_fn(
                    {"new": [], "updated": [], "deleted_uids": []},
                    lambda success, mapping: completions.append(
                        ("in-flight", success, mapping)
                    ),
                )
            )
            self.assertEqual(len(queued_handles), 1)
            operation_id = str(uuid.uuid4())
            queued_callbacks[0](
                QueuedMutationResult(
                    database_id=database_id,
                    runtime_generation=1,
                    operation_id=operation_id,
                    outcome_status=(MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED),
                )
            )
            # A projection failure is not completion: no result is reported and
            # the lease is not yet reacquired.
            self.assertEqual(completions, [("in-flight", False, None)])
            self.assertEqual(len(lease_requests), 1)
            queued_callbacks[0](
                QueuedMutationResult(
                    database_id=database_id,
                    runtime_generation=1,
                    operation_id=operation_id,
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                    authoritative_result=AuthoritativeMutationResult(
                        affected_families=("job_statuses",)
                    ),
                )
            )
            access_allowed[0] = False
            self.assertFalse(
                dialog._save_async_fn(
                    {
                        "new": [],
                        "updated": [
                            JobStatus(
                                uid="status-1",
                                name="Closed",
                                locked=False,
                                sequence=1,
                            )
                        ],
                        "deleted_uids": [],
                    },
                    lambda success, mapping: completions.append((success, mapping)),
                )
            )

        try:
            with patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator."
                "exec_with_ost_blocking",
                side_effect=exercise_save,
            ):
                coordinator.open_job_statuses_dialog()
        finally:
            coordinator.main_window.close()
            coordinator.main_window.deleteLater()
        self.assertEqual(len(lease_requests), 2)
        self.assertEqual(queued_handles, [lease_requests[0]])
        self.assertEqual(released_handles, [lease_requests[1]])
        self.assertEqual(
            completions,
            [("in-flight", False, None), (True, {}), (False, None)],
        )
        self.assertEqual(
            {resource.resource_type for resource in lease_requests[0].resources},
            {"job_status", "job_statuses_collection"},
        )

    def test_default_layers_menu_opens_layers_dialog_with_default_source(self):
        default_layers = [self._default_layer("default-1", "Default 1", 1)]
        observed = {}

        class ReadService:
            def __init__(self):
                self.default_calls = []

            def get_default_layers(self, file_path):
                self.default_calls.append(file_path)
                return list(default_layers)

            def get_merged_bid_layers(self, _file_path, _bid_uid):
                raise AssertionError("Default Layers should not load bid layers")

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_file_path):
                return False

            def insert_default_layer_result(self, db_path, name, after_sequence):
                observed["insert"] = (db_path, name, after_sequence)
                return WriteReloadResult("default-new", True, True)

            def delete_default_layers(self, db_path, layer_uids):
                observed["delete"] = (db_path, list(layer_uids))
                return BatchWriteResult(
                    requested_uids=list(layer_uids),
                    succeeded_uids=list(layer_uids),
                    reload_success=True,
                )

            def update_default_layer_show(self, db_path, layer_uid, show):
                observed["show"] = (db_path, layer_uid, show)
                return True

            def update_all_default_layers_show(self, db_path, show):
                observed["show_all"] = (db_path, show)
                return True

            def update_default_layer_name(self, db_path, layer_uid, name):
                observed["name"] = (db_path, layer_uid, name)
                return True

            def swap_default_layer_sequence(self, db_path, layer_uid, neighbor_uid):
                observed["move"] = (db_path, layer_uid, neighbor_uid)
                return True

        hierarchy_entry = HierarchyFileEntry(file_path="defaults.mdb")

        class ProjectData:
            def __init__(self):
                self.current_file = None

            def set_current_file(self, file_path):
                self.current_file = file_path

            def get_hierarchy(self):
                return HierarchyData(loaded_files=[hierarchy_entry])

        class AccessManager:
            allowed = True

            def is_allowed(self, _feature):
                return self.allowed

        class MainWindow(QtWidgets.QWidget):
            def get_selected_database_context_file_path(self):
                return "defaults.mdb"

        read_service = ReadService()
        project_data = ProjectData()
        main_window = MainWindow()
        access_manager = AccessManager()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator.main_window = main_window
        coordinator._workspace_state_model = make_workspace_state_model()
        coordinator.ui_state_manager = SimpleNamespace(
            selected_file_path="defaults.mdb",
            get_selected_bid_ref=lambda: None,
        )
        coordinator.ui_access_manager = access_manager
        coordinator.project_data = project_data
        coordinator._icon_provider = _master_data_support_FakeIconProvider()
        coordinator._project_read_service = read_service
        coordinator._project_write_service = WriteService()
        coordinator._sql_collaboration = SimpleNamespace(
            request_local_edit=lambda database_id, resources, callback, **_kwargs: (
                callback(
                    EditLeaseResult(
                        True,
                        handle=EditLeaseHandle(
                            database_id=database_id,
                            draft_id="layers-test-draft",
                            runtime_generation=0,
                            operation_id="layers-test-edit",
                            owning_surface="test",
                            resources=resources,
                        ),
                    )
                )
            ),
            end_edit_lease=lambda _handle: None,
        )
        coordinator.event_bus = EventBus()

        def capture_dialog(dialog, _event_bus):
            observed["button_text"] = dialog.btn_select.text()
            observed["cancel_button"] = dialog.btn_cancel
            observed["layer_names"] = [layer.name for layer in dialog._layers]
            observed["async_callbacks"] = (
                dialog._insert_async_fn,
                dialog._delete_many_async_fn,
                dialog._update_name_async_fn,
                dialog._move_async_fn,
                dialog._update_show_async_fn,
                dialog._update_all_show_async_fn,
            )
            observed["new_uid"] = dialog._insert_fn("Added", 1)
            # While editing is allowed every callback reaches the write service.
            observed["deleted"] = dialog._delete_many_fn(["default-1"])
            observed["show_result"] = dialog._update_show_fn("default-1", False)
            observed["show_all_result"] = dialog._update_all_show_fn(False)
            observed["name_result"] = dialog._update_name_fn("default-1", "Renamed")
            observed["move_result"] = dialog._move_fn("default-1", "default-2")
            # Once access is revoked the same callbacks must not write anything.
            access_manager.allowed = False
            observed["denied_results"] = (
                dialog._delete_many_fn(["default-2"]),
                dialog._update_show_fn("default-2", True),
                dialog._update_all_show_fn(True),
                dialog._update_name_fn("default-2", "Denied"),
                dialog._move_fn("default-2", "default-3"),
            )

        try:
            with patch(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator."
                "exec_with_ost_blocking",
                side_effect=capture_dialog,
            ):
                UIEventCoordinator.open_default_layers_dialog(coordinator)
        finally:
            main_window.close()
            main_window.deleteLater()
        self.assertEqual(read_service.default_calls, ["defaults.mdb"])
        self.assertEqual(project_data.current_file, "defaults.mdb")
        self.assertEqual(observed["button_text"], "OK")
        self.assertIsNone(observed["cancel_button"])
        self.assertEqual(observed["layer_names"], ["Default 1"])
        self.assertEqual(observed["async_callbacks"], (None,) * 6)
        self.assertEqual(observed["insert"], ("defaults.mdb", "Added", 1))
        self.assertEqual(observed["new_uid"], "default-new")
        self.assertEqual(
            {
                key: observed[key]
                for key in ("delete", "show", "show_all", "name", "move")
            },
            {
                "delete": ("defaults.mdb", ["default-1"]),
                "show": ("defaults.mdb", "default-1", False),
                "show_all": ("defaults.mdb", False),
                "name": ("defaults.mdb", "default-1", "Renamed"),
                "move": ("defaults.mdb", "default-1", "default-2"),
            },
        )
        self.assertEqual(observed["show_result"], True)
        self.assertEqual(observed["show_all_result"], True)
        self.assertEqual(observed["name_result"], True)
        self.assertEqual(observed["move_result"], True)
        self.assertIsNotNone(observed["deleted"])
        # The recorded writes above are those of the allowed calls (their
        # arguments differ from the denied ones), and the denied calls reported
        # no success.
        self.assertEqual(observed["denied_results"][1:], (False,) * 4)
        self.assertIsNone(observed["denied_results"][0])

    def test_access_master_data_menus_do_not_install_sql_save_callbacks(self):
        dialogs = []
        main_window = QtWidgets.QWidget()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = main_window
        coordinator._workspace_state_model = make_workspace_state_model()
        coordinator._icon_provider = _master_data_support_FakeIconProvider()
        coordinator.event_bus = EventBus()
        coordinator._editable_master_data_file_path = lambda: "master-data.mdb"
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False
        )
        coordinator._project_read_service = SimpleNamespace(
            get_employees_and_pay_classes=lambda _file_path: (
                [
                    Employee(
                        uid="emp-1",
                        employee_no="1",
                        first_name="Ava",
                        last_name="Lee",
                    )
                ],
                [PayClass(uid="pay-1", name="Regular")],
            ),
            get_employee_uids_in_use=lambda _file_path: set(),
            get_job_statuses=lambda _file_path: [
                JobStatus(uid="status-1", name="Bidding", locked=False, sequence=1)
            ],
        )
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: None
        )
        coordinator._exec_with_collaboration_lease = (
            lambda dialog, *_args, **_kwargs: dialogs.append(dialog)
        )
        try:
            coordinator.open_employees_dialog()
            coordinator.open_job_statuses_dialog()
            coordinator.open_payroll_classes_dialog()
            self.assertEqual(len(dialogs), 3)
            employees, job_statuses, pay_classes = dialogs
            self.assertIsNone(employees._save_async_fn)
            self.assertIsNone(employees._pay_classes_save_async_fn)
            self.assertIsNone(job_statuses._save_async_fn)
            self.assertIsNone(pay_classes._save_async_fn)
        finally:
            for dialog in dialogs:
                dialog.close()
                dialog.cleanup()
                dialog.deleteLater()
            main_window.close()
            main_window.deleteLater()
