import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.presentation.handlers import import_handler as import_handler_module
from ost_visualizer.presentation.handlers.import_handler import ImportHandler
from PySide6 import QtWidgets
from shiboken6 import delete
from tests.helpers.import_workflow import (
    FakeAccess as _import_workflow_FakeAccess,
    FakeDeferredPersistence as _import_workflow_FakeDeferredPersistence,
    FakeImportService as _import_workflow_FakeImportService,
    FakeProgressDialog as _import_workflow_FakeProgressDialog,
    FakeProjectData as _import_workflow_FakeProjectData,
    FakeUiState as _import_workflow_FakeUiState,
)


class ImportHandlerRefreshTests(unittest.TestCase):
    def test_import_handler_runs_import_without_refresh_then_refreshes_on_ui_completion(
        self,
    ):
        service = _import_workflow_FakeImportService()
        messages = []
        window = object()
        handler = ImportHandler(
            window=window,
            project_data_service=_import_workflow_FakeProjectData(),
            import_service=service,
            ui_state_manager=_import_workflow_FakeUiState(),
            deferred_persistence_manager=_import_workflow_FakeDeferredPersistence(),
            ui_access_manager=_import_workflow_FakeAccess(),
        )
        original_dialog = import_handler_module.ProgressDialog
        original_get_open = import_handler_module.QtWidgets.QFileDialog.getOpenFileName
        original_show_info = import_handler_module.show_info

        def select_source_file(_parent, _caption, _directory, _filter):
            return "source.ost", ""

        try:
            _import_workflow_FakeProgressDialog.instances = []
            import_handler_module.ProgressDialog = _import_workflow_FakeProgressDialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                select_source_file
            )
            import_handler_module.show_info = (
                lambda parent, title, message: messages.append((parent, title, message))
            )
            handler.import_ost()
        finally:
            import_handler_module.ProgressDialog = original_dialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                original_get_open
            )
            import_handler_module.show_info = original_show_info
        self.assertEqual(
            service.import_calls,
            [("source.ost", "target.mdb", None, False)],
        )
        self.assertEqual(service.reloads, ["target.mdb"])
        self.assertEqual(len(_import_workflow_FakeProgressDialog.instances), 1)
        self.assertIs(_import_workflow_FakeProgressDialog.instances[0].parent, window)
        self.assertEqual(
            messages,
            [
                (
                    window,
                    "Import Complete",
                    "Successfully imported 'source.ost' into the database.",
                )
            ],
        )

    def test_import_handler_uses_explicit_context_destination(self):
        service = _import_workflow_FakeImportService()
        other_project = HierarchyProjectInfo("Other")
        hierarchy = HierarchyData(
            [
                HierarchyFileEntry(file_path="active.mdb"),
                HierarchyFileEntry(
                    file_path="other.mdb",
                    bid_projects={"other-project": other_project},
                ),
            ]
        )
        project_data = SimpleNamespace(get_hierarchy=lambda: hierarchy)
        ui_state = _import_workflow_FakeUiState()
        ui_state.selected_file_path = "active.mdb"
        handler = ImportHandler(
            window=object(),
            project_data_service=project_data,
            import_service=service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_import_workflow_FakeDeferredPersistence(),
            ui_access_manager=_import_workflow_FakeAccess(),
        )
        original_dialog = import_handler_module.ProgressDialog
        original_get_open = import_handler_module.QtWidgets.QFileDialog.getOpenFileName
        original_show_info = import_handler_module.show_info
        try:
            _import_workflow_FakeProgressDialog.instances = []
            import_handler_module.ProgressDialog = _import_workflow_FakeProgressDialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                lambda *_args: ("source.ost", "")
            )
            import_handler_module.show_info = lambda *_args: None
            handler.import_project_file("ost", "other.mdb", "other-project")
        finally:
            import_handler_module.ProgressDialog = original_dialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                original_get_open
            )
            import_handler_module.show_info = original_show_info
        self.assertEqual(
            service.import_calls,
            [("source.ost", "other.mdb", "other-project", False)],
        )

    def test_import_handler_keeps_project_target_that_opened_native_file_dialog(self):
        service = _import_workflow_FakeImportService()
        ui_state = _import_workflow_FakeUiState()
        ui_state.selected_project_uid = "original-project"
        handler = ImportHandler(
            window=None,
            project_data_service=_import_workflow_FakeProjectData(),
            import_service=service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_import_workflow_FakeDeferredPersistence(),
            ui_access_manager=_import_workflow_FakeAccess(),
        )

        def select_source_file(_parent, _caption, _directory, _filter):
            ui_state.selected_project_uid = "other-database-project"
            return "source.ost", ""

        with patch.object(
            import_handler_module.QtWidgets.QFileDialog,
            "getOpenFileName",
            side_effect=select_source_file,
        ), patch.object(
            import_handler_module, "ProgressDialog", _import_workflow_FakeProgressDialog
        ), patch.object(
            import_handler_module, "show_info"
        ):
            handler.import_ost()
        self.assertEqual(
            service.import_calls,
            [("source.ost", "target.mdb", "original-project", False)],
        )

    def test_import_handler_cancels_when_target_project_is_replaced_with_same_uid(
        self,
    ):
        service = _import_workflow_FakeImportService()
        ui_state = _import_workflow_FakeUiState()
        ui_state.selected_project_uid = "original-project"
        project_data = _import_workflow_FakeProjectData()
        warnings = []
        handler = ImportHandler(
            window=None,
            project_data_service=project_data,
            import_service=service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_import_workflow_FakeDeferredPersistence(),
            ui_access_manager=_import_workflow_FakeAccess(),
        )

        def select_source_file(_parent, _caption, _directory, _filter):
            project_data.file_entry.bid_projects["original-project"] = (
                HierarchyProjectInfo("Replacement with reused UID")
            )
            return "source.ost", ""

        with patch.object(
            import_handler_module.QtWidgets.QFileDialog,
            "getOpenFileName",
            side_effect=select_source_file,
        ), patch.object(
            import_handler_module,
            "show_warning",
            side_effect=lambda _parent, title, message: warnings.append(
                (title, message)
            ),
        ), patch.object(
            import_handler_module, "ProgressDialog", _import_workflow_FakeProgressDialog
        ), patch.object(
            import_handler_module, "show_info"
        ):
            handler.import_ost()
        self.assertEqual(service.import_calls, [])
        self.assertEqual(service.queued_imports, [])
        self.assertEqual(warnings[0][0], "Import Cancelled")

    def test_import_handler_stops_if_window_closes_inside_native_file_dialog(self):
        service = _import_workflow_FakeImportService()
        deferred = _import_workflow_FakeDeferredPersistence()
        handler = ImportHandler(
            window=object(),
            project_data_service=_import_workflow_FakeProjectData(),
            import_service=service,
            ui_state_manager=_import_workflow_FakeUiState(),
            deferred_persistence_manager=deferred,
            ui_access_manager=_import_workflow_FakeAccess(),
        )
        with (
            patch.object(
                import_handler_module.QtWidgets.QFileDialog,
                "getOpenFileName",
                return_value=("source.ost", ""),
            ),
            patch.object(import_handler_module, "isValid", return_value=False),
            patch.object(
                import_handler_module,
                "ProgressDialog",
                _import_workflow_FakeProgressDialog,
            ),
            patch.object(import_handler_module, "show_info"),
            patch.object(import_handler_module, "show_critical"),
        ):
            handler.import_ost()
        self.assertEqual(deferred.flush_calls, [])
        self.assertEqual(service.import_calls, [])
        self.assertEqual(service.queued_imports, [])

    def test_import_handler_stops_after_progress_parent_is_destroyed(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        service = _import_workflow_FakeImportService()
        window = QtWidgets.QDialog()
        critical_messages = []

        class DestroyingProgressDialog(QtWidgets.QDialog):
            def __init__(self, _filename, task_fn, parent=None):
                super().__init__(parent)
                self.result = task_fn()
                self.error = None
                self.cleanup_calls = 0

            def exec(self):
                delete(window)
                return QtWidgets.QDialog.DialogCode.Accepted

            def cleanup(self):
                self.cleanup_calls += 1

        handler = ImportHandler(
            window=window,
            project_data_service=_import_workflow_FakeProjectData(),
            import_service=service,
            ui_state_manager=_import_workflow_FakeUiState(),
            deferred_persistence_manager=_import_workflow_FakeDeferredPersistence(),
            ui_access_manager=_import_workflow_FakeAccess(),
        )
        with (
            patch.object(
                import_handler_module.QtWidgets.QFileDialog,
                "getOpenFileName",
                return_value=("source.ost", ""),
            ),
            patch.object(
                import_handler_module,
                "ProgressDialog",
                DestroyingProgressDialog,
            ),
            patch.object(
                import_handler_module,
                "show_info",
                side_effect=AssertionError("closed window must not receive success"),
            ),
            patch.object(
                import_handler_module,
                "show_warning",
                side_effect=AssertionError("closed window must not receive warning"),
            ),
            patch.object(
                import_handler_module,
                "show_critical",
                side_effect=lambda *_args: critical_messages.append(True),
            ),
        ):
            handler.import_ost()
        self.assertIsNotNone(app)
        self.assertEqual(service.reloads, [])
        self.assertEqual(critical_messages, [])

    def test_sql_import_handler_queues_without_modal_or_ui_thread_reload(self):
        service = _import_workflow_FakeImportService()
        service.sql_collaboration = True
        messages = []
        window = object()
        handler = ImportHandler(
            window=window,
            project_data_service=_import_workflow_FakeProjectData(),
            import_service=service,
            ui_state_manager=_import_workflow_FakeUiState(),
            deferred_persistence_manager=_import_workflow_FakeDeferredPersistence(),
            ui_access_manager=_import_workflow_FakeAccess(),
        )
        original_dialog = import_handler_module.ProgressDialog
        original_get_open = import_handler_module.QtWidgets.QFileDialog.getOpenFileName
        original_show_info = import_handler_module.show_info

        def reject_progress_dialog(_filename, _task_fn, parent=None):
            self.fail("SQL import must not open the synchronous progress path")

        def select_source_file(_parent, _caption, _directory, _filter):
            return "source.ost", ""

        try:
            import_handler_module.ProgressDialog = reject_progress_dialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                select_source_file
            )
            import_handler_module.show_info = (
                lambda parent, title, message: messages.append((parent, title, message))
            )
            handler.import_ost()
            self.assertEqual(service.reloads, [])
            self.assertEqual(len(service.queued_imports), 1)
            queued = service.queued_imports[0]
            self.assertEqual(queued[:4], ("source.ost", "ost", "target.mdb", None))
            operation_id = str(uuid.uuid4())
            queued[4](
                QueuedMutationResult(
                    database_id="target.mdb",
                    runtime_generation=1,
                    operation_id=operation_id,
                    outcome_status=(MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED),
                )
            )
            self.assertEqual(messages, [])
            queued[4](
                QueuedMutationResult(
                    database_id="target.mdb",
                    runtime_generation=1,
                    operation_id=operation_id,
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                )
            )
        finally:
            import_handler_module.ProgressDialog = original_dialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                original_get_open
            )
            import_handler_module.show_info = original_show_info
        self.assertEqual(messages[0][1], "Import Complete")
        self.assertEqual(service.reloads, [])

    def test_import_handler_denies_direct_call_when_import_access_is_read_only(self):
        service = _import_workflow_FakeImportService()
        handler = ImportHandler(
            window=None,
            project_data_service=_import_workflow_FakeProjectData(),
            import_service=service,
            ui_state_manager=_import_workflow_FakeUiState(),
            deferred_persistence_manager=_import_workflow_FakeDeferredPersistence(),
            ui_access_manager=_import_workflow_FakeAccess(False),
        )
        original_get_open = import_handler_module.QtWidgets.QFileDialog.getOpenFileName

        def reject_file_picker(_parent, _caption, _directory, _filter):
            self.fail("denied import must not open the file picker")

        try:
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                reject_file_picker
            )
            handler.import_ost()
        finally:
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                original_get_open
            )
        self.assertEqual(service.import_calls, [])

    def test_import_handler_stops_when_deferred_flush_fails(self):
        service = _import_workflow_FakeImportService()
        deferred = _import_workflow_FakeDeferredPersistence(result=False)
        handler = ImportHandler(
            window=None,
            project_data_service=_import_workflow_FakeProjectData(),
            import_service=service,
            ui_state_manager=_import_workflow_FakeUiState(),
            deferred_persistence_manager=deferred,
            ui_access_manager=_import_workflow_FakeAccess(),
        )
        original_get_open = import_handler_module.QtWidgets.QFileDialog.getOpenFileName

        def select_source_file(_parent, _caption, _directory, _filter):
            return "source.ost", ""

        try:
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                select_source_file
            )
            handler.import_ost()
        finally:
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                original_get_open
            )
        self.assertEqual(deferred.flush_calls, ["target.mdb"])
        self.assertEqual(service.import_calls, [])
        self.assertEqual(service.reloads, [])

    def test_import_handler_does_not_refresh_after_rejected_import(self):
        service = _import_workflow_FakeImportService()
        handler = ImportHandler(
            window=None,
            project_data_service=_import_workflow_FakeProjectData(),
            import_service=service,
            ui_state_manager=_import_workflow_FakeUiState(),
            deferred_persistence_manager=_import_workflow_FakeDeferredPersistence(),
            ui_access_manager=_import_workflow_FakeAccess(),
        )
        original_dialog = import_handler_module.ProgressDialog
        original_get_open = import_handler_module.QtWidgets.QFileDialog.getOpenFileName
        original_show_critical = import_handler_module.show_critical

        def select_source_file(_parent, _caption, _directory, _filter):
            return "source.ost", ""

        def ignore_message(_parent, _title, _message):
            pass

        try:
            _import_workflow_FakeProgressDialog.result_code = (
                QtWidgets.QDialog.DialogCode.Rejected
            )
            import_handler_module.ProgressDialog = _import_workflow_FakeProgressDialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                select_source_file
            )
            import_handler_module.show_critical = ignore_message
            handler.import_ost()
        finally:
            _import_workflow_FakeProgressDialog.result_code = (
                QtWidgets.QDialog.DialogCode.Accepted
            )
            import_handler_module.ProgressDialog = original_dialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                original_get_open
            )
            import_handler_module.show_critical = original_show_critical
        self.assertEqual(
            service.import_calls,
            [("source.ost", "target.mdb", None, False)],
        )
        self.assertEqual(service.reloads, [])

    def test_import_handler_warns_when_successful_import_cannot_refresh(self):
        service = _import_workflow_FakeImportService()
        service.reload_result = False
        messages = []
        handler = ImportHandler(
            window=None,
            project_data_service=_import_workflow_FakeProjectData(),
            import_service=service,
            ui_state_manager=_import_workflow_FakeUiState(),
            deferred_persistence_manager=_import_workflow_FakeDeferredPersistence(),
            ui_access_manager=_import_workflow_FakeAccess(),
        )
        original_dialog = import_handler_module.ProgressDialog
        original_get_open = import_handler_module.QtWidgets.QFileDialog.getOpenFileName
        original_show_info = import_handler_module.show_info
        original_show_warning = import_handler_module.show_warning

        def select_source_file(_parent, _caption, _directory, _filter):
            return "source.ost", ""

        def reject_success_message(_parent, _title, _message):
            self.fail("a failed refresh must not report an unqualified success")

        try:
            import_handler_module.ProgressDialog = _import_workflow_FakeProgressDialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                select_source_file
            )
            import_handler_module.show_info = reject_success_message
            import_handler_module.show_warning = (
                lambda _parent, title, message: messages.append((title, message))
            )
            handler.import_ost()
        finally:
            import_handler_module.ProgressDialog = original_dialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                original_get_open
            )
            import_handler_module.show_info = original_show_info
            import_handler_module.show_warning = original_show_warning
        self.assertEqual(service.reloads, ["target.mdb"])
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0][0], "Refresh Error")
        self.assertIn("Successfully imported 'source.ost'", messages[0][1])
