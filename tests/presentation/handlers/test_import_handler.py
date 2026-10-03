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
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete, isValid
from tests.helpers.import_workflow import (
    FakeAccess as _import_workflow_FakeAccess,
    FakeDeferredPersistence as _import_workflow_FakeDeferredPersistence,
    FakeImportService as _import_workflow_FakeImportService,
    FakeProgressDialog as _import_workflow_FakeProgressDialog,
    FakeProjectData as _import_workflow_FakeProjectData,
    FakeUiState as _import_workflow_FakeUiState,
)


class _OspCapableImportService(_import_workflow_FakeImportService):
    def __init__(self):
        super().__init__()
        self.osp_calls = []

    def import_osp(self, filename, target_db, target_project_uid, refresh=True):
        self.osp_calls.append((filename, target_db, target_project_uid, refresh))
        return self.next_result


class ImportHandlerRefreshTests(unittest.TestCase):
    def test_import_handler_runs_import_without_refresh_then_refreshes_on_ui_completion(
        self,
    ):
        service = _import_workflow_FakeImportService()
        deferred = _import_workflow_FakeDeferredPersistence()
        messages = []
        window = object()
        handler = ImportHandler(
            window=window,
            project_data_service=_import_workflow_FakeProjectData(),
            import_service=service,
            ui_state_manager=_import_workflow_FakeUiState(),
            deferred_persistence_manager=deferred,
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
        self.assertEqual(deferred.flush_calls, ["target.mdb"])
        self.assertEqual(len(_import_workflow_FakeProgressDialog.instances), 1)
        dialog = _import_workflow_FakeProgressDialog.instances[0]
        self.assertIs(dialog.parent, window)
        self.assertEqual(dialog.filename, "source.ost")
        self.assertEqual((dialog.cleanup_calls, dialog.delete_later_calls), (1, 1))
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
        deferred = _import_workflow_FakeDeferredPersistence()
        handler = ImportHandler(
            window=object(),
            project_data_service=project_data,
            import_service=service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=deferred,
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
        self.assertEqual(service.reloads, ["other.mdb"])
        self.assertEqual(deferred.flush_calls, ["other.mdb"])

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

        with (
            patch.object(
                import_handler_module.QtWidgets.QFileDialog,
                "getOpenFileName",
                side_effect=select_source_file,
            ),
            patch.object(
                import_handler_module,
                "ProgressDialog",
                _import_workflow_FakeProgressDialog,
            ),
            patch.object(import_handler_module, "show_info"),
            patch.object(
                import_handler_module,
                "show_warning",
                side_effect=AssertionError("the captured target is still current"),
            ),
        ):
            handler.import_ost()
        self.assertEqual(ui_state.selected_project_uid, "other-database-project")
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
        deferred = _import_workflow_FakeDeferredPersistence()
        handler = ImportHandler(
            window=None,
            project_data_service=project_data,
            import_service=service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=deferred,
            ui_access_manager=_import_workflow_FakeAccess(),
        )

        def select_source_file(_parent, _caption, _directory, _filter):
            project_data.file_entry.bid_projects["original-project"] = (
                HierarchyProjectInfo("Replacement with reused UID")
            )
            return "source.ost", ""

        with (
            patch.object(
                import_handler_module.QtWidgets.QFileDialog,
                "getOpenFileName",
                side_effect=select_source_file,
            ),
            patch.object(
                import_handler_module,
                "show_warning",
                side_effect=lambda _parent, title, message: warnings.append(
                    (title, message)
                ),
            ),
            patch.object(
                import_handler_module,
                "ProgressDialog",
                _import_workflow_FakeProgressDialog,
            ),
            patch.object(import_handler_module, "show_info"),
        ):
            handler.import_ost()
        self.assertEqual(service.import_calls, [])
        self.assertEqual(service.queued_imports, [])
        self.assertEqual(deferred.flush_calls, [])
        self.assertEqual(
            warnings,
            [
                (
                    "Import Cancelled",
                    "The selected database or project changed while the file dialog "
                    "was open. Select the destination again before importing.",
                )
            ],
        )

    def test_import_handler_stops_if_window_closes_inside_native_file_dialog(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        window = QtWidgets.QDialog()
        service = _import_workflow_FakeImportService()
        deferred = _import_workflow_FakeDeferredPersistence()
        handler = ImportHandler(
            window=window,
            project_data_service=_import_workflow_FakeProjectData(),
            import_service=service,
            ui_state_manager=_import_workflow_FakeUiState(),
            deferred_persistence_manager=deferred,
            ui_access_manager=_import_workflow_FakeAccess(),
        )

        def close_window_while_dialog_is_open(*_args):
            delete(window)
            return "source.ost", ""

        for sql_collaboration in (False, True):
            with self.subTest(sql_collaboration=sql_collaboration):
                service.sql_collaboration = sql_collaboration
                if sql_collaboration:
                    window = QtWidgets.QDialog()
                    handler.window = window
                with (
                    patch.object(
                        import_handler_module.QtWidgets.QFileDialog,
                        "getOpenFileName",
                        side_effect=close_window_while_dialog_is_open,
                    ),
                    patch.object(
                        import_handler_module,
                        "ProgressDialog",
                        _import_workflow_FakeProgressDialog,
                    ),
                    patch.object(import_handler_module, "show_info") as info,
                    patch.object(import_handler_module, "show_warning") as warning,
                    patch.object(import_handler_module, "show_critical") as critical,
                ):
                    handler.import_ost()
                info.assert_not_called()
                warning.assert_not_called()
                critical.assert_not_called()
        self.assertIsNotNone(app)
        self.assertFalse(isValid(window))
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
        self.assertFalse(isValid(window))
        self.assertEqual(
            service.import_calls, [("source.ost", "target.mdb", None, False)]
        )
        self.assertEqual(service.reloads, [])
        self.assertEqual(critical_messages, [])

    def test_sql_import_handler_queues_without_modal_or_ui_thread_reload(self):
        service = _import_workflow_FakeImportService()
        service.sql_collaboration = True
        messages = []
        window = object()
        deferred = _import_workflow_FakeDeferredPersistence()
        handler = ImportHandler(
            window=window,
            project_data_service=_import_workflow_FakeProjectData(),
            import_service=service,
            ui_state_manager=_import_workflow_FakeUiState(),
            deferred_persistence_manager=deferred,
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
        self.assertEqual(deferred.flush_calls, ["target.mdb"])
        self.assertEqual(service.import_calls, [])
        self.assertEqual(service.reloads, [])

    def test_import_handler_denies_direct_call_when_import_access_is_read_only(self):
        service = _OspCapableImportService()
        deferred = _import_workflow_FakeDeferredPersistence()
        handler = ImportHandler(
            window=None,
            project_data_service=_import_workflow_FakeProjectData(),
            import_service=service,
            ui_state_manager=_import_workflow_FakeUiState(),
            deferred_persistence_manager=deferred,
            ui_access_manager=_import_workflow_FakeAccess(False),
        )

        def reject_file_picker(_parent, _caption, _directory, _filter):
            self.fail("denied import must not open the file picker")

        with (
            patch.object(
                import_handler_module.QtWidgets.QFileDialog,
                "getOpenFileName",
                side_effect=reject_file_picker,
            ),
            patch.object(import_handler_module, "show_warning") as warning,
            patch.object(import_handler_module, "show_critical") as critical,
        ):
            handler.import_ost()
            handler.import_osp()
            handler.import_project_file("ost", "target.mdb", "original-project")
        warning.assert_not_called()
        critical.assert_not_called()
        self.assertEqual(deferred.flush_calls, [])
        self.assertEqual(service.import_calls, [])
        self.assertEqual(service.osp_calls, [])
        self.assertEqual(service.queued_imports, [])

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
        for sql_collaboration in (False, True):
            with self.subTest(sql_collaboration=sql_collaboration):
                service.sql_collaboration = sql_collaboration
                with (
                    patch.object(
                        import_handler_module.QtWidgets.QFileDialog,
                        "getOpenFileName",
                        return_value=("source.ost", ""),
                    ),
                    patch.object(
                        import_handler_module,
                        "ProgressDialog",
                        side_effect=AssertionError("no import after failed flush"),
                    ),
                    patch.object(import_handler_module, "show_critical") as critical,
                    patch.object(import_handler_module, "show_warning") as warning,
                ):
                    handler.import_ost()
                critical.assert_not_called()
                warning.assert_not_called()
        self.assertEqual(deferred.flush_calls, ["target.mdb", "target.mdb"])
        self.assertEqual(service.import_calls, [])
        self.assertEqual(service.queued_imports, [])
        self.assertEqual(service.reloads, [])

    def test_import_handler_does_not_refresh_after_rejected_import(self):
        service = _import_workflow_FakeImportService()
        service.next_result = False
        handler = ImportHandler(
            window=None,
            project_data_service=_import_workflow_FakeProjectData(),
            import_service=service,
            ui_state_manager=_import_workflow_FakeUiState(),
            deferred_persistence_manager=_import_workflow_FakeDeferredPersistence(),
            ui_access_manager=_import_workflow_FakeAccess(),
        )
        try:
            _import_workflow_FakeProgressDialog.result_code = (
                QtWidgets.QDialog.DialogCode.Rejected
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
                    _import_workflow_FakeProgressDialog,
                ),
                patch.object(import_handler_module, "show_info") as info,
                patch.object(import_handler_module, "show_critical") as critical,
            ):
                handler.import_ost()
        finally:
            _import_workflow_FakeProgressDialog.result_code = (
                QtWidgets.QDialog.DialogCode.Accepted
            )
        self.assertEqual(
            service.import_calls,
            [("source.ost", "target.mdb", None, False)],
        )
        self.assertEqual(service.reloads, [])
        info.assert_not_called()
        critical.assert_called_once_with(
            None,
            "Import Error",
            "Failed to import OST file. "
            "The file may be corrupted or in an unsupported format.",
        )

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
        self.assertEqual(
            messages,
            [
                (
                    "Refresh Error",
                    "Successfully imported 'source.ost', but the database view "
                    "could not be refreshed. Reopen the database to see the "
                    "imported project.",
                )
            ],
        )

    def _make_handler(self, service=None, deferred=None, ui_state=None, **overrides):
        options = dict(
            window=None,
            project_data_service=_import_workflow_FakeProjectData(),
            import_service=service or _import_workflow_FakeImportService(),
            ui_state_manager=ui_state or _import_workflow_FakeUiState(),
            deferred_persistence_manager=(
                deferred or _import_workflow_FakeDeferredPersistence()
            ),
            ui_access_manager=_import_workflow_FakeAccess(),
        )
        options.update(overrides)
        return ImportHandler(**options)

    def test_import_dialog_caption_filter_and_service_follow_the_format(self):
        service = _OspCapableImportService()
        handler = self._make_handler(service)
        with (
            patch.object(
                import_handler_module.QtWidgets.QFileDialog,
                "getOpenFileName",
                return_value=("package.osp", ""),
            ) as picker,
            patch.object(
                import_handler_module,
                "ProgressDialog",
                _import_workflow_FakeProgressDialog,
            ),
            patch.object(import_handler_module, "show_info"),
        ):
            handler.import_osp()
            handler.import_project_file("osp", "target.mdb", "original-project")
            handler.import_ost()
        self.assertEqual(
            [call.args[1:] for call in picker.call_args_list],
            [
                ("Import OSP File", "", "OSP Files (*.osp)"),
                ("Import OSP File", "", "OSP Files (*.osp)"),
                ("Import OST File", "", "OST Files (*.ost)"),
            ],
        )
        self.assertEqual(
            service.osp_calls,
            [
                ("package.osp", "target.mdb", None, False),
                ("package.osp", "target.mdb", "original-project", False),
            ],
        )
        self.assertEqual(
            service.import_calls, [("package.osp", "target.mdb", None, False)]
        )

    def test_import_project_file_ignores_unknown_format_and_cancelled_dialog(self):
        service = _OspCapableImportService()
        deferred = _import_workflow_FakeDeferredPersistence()
        handler = self._make_handler(service, deferred)
        with (
            patch.object(
                import_handler_module.QtWidgets.QFileDialog,
                "getOpenFileName",
                return_value=("", ""),
            ) as picker,
            patch.object(
                import_handler_module,
                "ProgressDialog",
                side_effect=AssertionError("no import without a chosen file"),
            ),
            patch.object(import_handler_module, "show_warning") as warning,
            patch.object(import_handler_module, "show_critical") as critical,
        ):
            handler.import_project_file("csv", "target.mdb", None)
            picker.assert_not_called()
            handler.import_ost()
            picker.assert_called_once()
        warning.assert_not_called()
        critical.assert_not_called()
        self.assertEqual(deferred.flush_calls, [])
        self.assertEqual((service.import_calls, service.osp_calls), ([], []))

    def test_import_warns_without_loaded_database_or_missing_destination(self):
        project_data = SimpleNamespace(
            get_current_file_path=lambda: None,
            get_hierarchy=lambda: HierarchyData([]),
        )
        service = _import_workflow_FakeImportService()
        handler = self._make_handler(service, project_data_service=project_data)
        with (
            patch.object(
                import_handler_module.QtWidgets.QFileDialog,
                "getOpenFileName",
                side_effect=AssertionError("no picker without a destination"),
            ),
            patch.object(import_handler_module, "show_warning") as warning,
        ):
            handler.import_ost()
            handler.import_project_file("ost", "target.mdb", None)
        self.assertEqual(
            [call.args[1:] for call in warning.call_args_list],
            [
                (
                    "No Database",
                    "No database is loaded. Please open a database file before "
                    "importing.",
                ),
                (
                    "Import Cancelled",
                    "The selected import destination is no longer available. "
                    "Select the database or project again.",
                ),
            ],
        )
        missing_project = self._make_handler(service)
        with (
            patch.object(
                import_handler_module.QtWidgets.QFileDialog,
                "getOpenFileName",
                side_effect=AssertionError("no picker without a destination"),
            ),
            patch.object(import_handler_module, "show_warning") as warning,
        ):
            missing_project.import_project_file("ost", "target.mdb", "gone-project")
        warning.assert_called_once()
        self.assertEqual(warning.call_args.args[1], "Import Cancelled")
        self.assertEqual(service.import_calls, [])

    def test_import_resolves_target_database_and_project_by_precedence(self):
        hierarchy = HierarchyData(
            [
                HierarchyFileEntry(file_path="first.mdb"),
                HierarchyFileEntry(
                    file_path="bid.mdb",
                    bid_projects={
                        "bid-project": HierarchyProjectInfo("Bid"),
                        "other-bid-project": HierarchyProjectInfo("Other"),
                    },
                ),
                HierarchyFileEntry(file_path="selected.mdb"),
                HierarchyFileEntry(
                    file_path="project.mdb",
                    bid_projects={"project-uid": HierarchyProjectInfo("Project")},
                ),
                HierarchyFileEntry(file_path="current.mdb"),
            ]
        )
        bid_ref = SimpleNamespace(file_path="bid.mdb", bid_uid="bid-1")
        cases = (
            (
                "selected bid database wins and the selected project wins over it",
                dict(
                    bid_ref=bid_ref,
                    file="selected.mdb",
                    project="other-bid-project",
                ),
                "current.mdb",
                ("bid.mdb", "other-bid-project"),
            ),
            (
                "bid project when no project is selected",
                dict(bid_ref=bid_ref, file=None, project=None),
                "current.mdb",
                ("bid.mdb", "bid-project"),
            ),
            (
                "selected file",
                dict(bid_ref=None, file="selected.mdb", project=None),
                "current.mdb",
                ("selected.mdb", None),
            ),
            (
                "file that owns the selected project",
                dict(bid_ref=None, file=None, project="project-uid"),
                "current.mdb",
                ("project.mdb", "project-uid"),
            ),
            (
                "current file",
                dict(bid_ref=None, file=None, project=None),
                "current.mdb",
                ("current.mdb", None),
            ),
            (
                "first loaded file",
                dict(bid_ref=None, file=None, project=None),
                None,
                ("first.mdb", None),
            ),
        )
        for label, selection, current_file, (expected_db, expected_project) in cases:
            with self.subTest(label):
                service = _import_workflow_FakeImportService()
                ui_state = _import_workflow_FakeUiState()
                ui_state.selected_file_path = selection["file"]
                ui_state.selected_project_uid = selection["project"]
                ui_state.get_selected_bid_ref = lambda ref=selection["bid_ref"]: ref
                project_data = SimpleNamespace(
                    get_hierarchy=lambda: hierarchy,
                    get_current_file_path=lambda current_file=current_file: (
                        current_file
                    ),
                    find_project_uid_for_bid=lambda _ref: "bid-project",
                )
                handler = self._make_handler(
                    service, ui_state=ui_state, project_data_service=project_data
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
                        _import_workflow_FakeProgressDialog,
                    ),
                    patch.object(import_handler_module, "show_info"),
                    patch.object(import_handler_module, "show_warning") as warning,
                ):
                    handler.import_ost()
                warning.assert_not_called()
                self.assertEqual(
                    service.import_calls,
                    [("source.ost", expected_db, expected_project, False)],
                )

    def test_import_reports_unexpected_worker_exception_without_refresh(self):
        service = _import_workflow_FakeImportService()

        def failing_import(*_args, **_kwargs):
            raise OSError("source is unreadable")

        service.import_ost = failing_import
        handler = self._make_handler(service)
        with (
            patch.object(
                import_handler_module.QtWidgets.QFileDialog,
                "getOpenFileName",
                return_value=("source.ost", ""),
            ),
            patch.object(
                import_handler_module,
                "ProgressDialog",
                _import_workflow_FakeProgressDialog,
            ),
            patch.object(import_handler_module, "show_info") as info,
            patch.object(import_handler_module, "show_critical") as critical,
            self.assertLogs(import_handler_module.logger, level="ERROR"),
        ):
            handler.import_ost()
        info.assert_not_called()
        self.assertEqual(service.reloads, [])
        critical.assert_called_once_with(
            None,
            "Import Error",
            "An unexpected error occurred while importing the OST file. "
            "Please verify the file is valid and try again.",
        )

    def test_sql_import_reports_each_terminal_outcome(self):
        def result(status, message=""):
            return QueuedMutationResult(
                database_id="target.mdb",
                runtime_generation=1,
                operation_id=str(uuid.uuid4()),
                outcome_status=status,
                message=message,
            )

        failure_default = (
            "Failed to import OST file. The file may be corrupted or in an "
            "unsupported format."
        )
        cases = (
            (
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                "",
                ("warning", "Import Status Unknown"),
                "The commit status for 'source.ost' is being recovered. Do not "
                "import the file again until recovery completes.",
            ),
            (
                MutationOutcomeStatus.REJECTED,
                "Project is locked.",
                ("critical", "Import Error"),
                "Project is locked.",
            ),
            (
                MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                "",
                ("critical", "Import Error"),
                failure_default,
            ),
            (
                MutationOutcomeStatus.CONFLICT,
                "",
                ("critical", "Import Error"),
                failure_default,
            ),
            (MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED, "", None, None),
        )
        for status, message, expected_kind, expected_message in cases:
            with self.subTest(status=status):
                service = _import_workflow_FakeImportService()
                service.sql_collaboration = True
                handler = self._make_handler(service)
                with (
                    patch.object(
                        import_handler_module.QtWidgets.QFileDialog,
                        "getOpenFileName",
                        return_value=("source.ost", ""),
                    ),
                    patch.object(import_handler_module, "show_info") as info,
                    patch.object(import_handler_module, "show_warning") as warning,
                    patch.object(import_handler_module, "show_critical") as critical,
                ):
                    handler.import_ost()
                    service.queued_imports[0][4](result(status, message))
                info.assert_not_called()
                if expected_kind is None:
                    warning.assert_not_called()
                    critical.assert_not_called()
                elif expected_kind[0] == "warning":
                    warning.assert_called_once_with(
                        None, expected_kind[1], expected_message
                    )
                    critical.assert_not_called()
                else:
                    critical.assert_called_once_with(
                        None, expected_kind[1], expected_message
                    )
                    warning.assert_not_called()

    def test_sql_import_completion_is_ignored_after_window_is_destroyed(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        window = QtWidgets.QDialog()
        service = _import_workflow_FakeImportService()
        service.sql_collaboration = True
        handler = self._make_handler(service, window=window)
        with patch.object(
            import_handler_module.QtWidgets.QFileDialog,
            "getOpenFileName",
            return_value=("source.ost", ""),
        ):
            handler.import_ost()
        delete(window)
        self.assertIsNotNone(app)
        with (
            patch.object(import_handler_module, "show_info") as info,
            patch.object(import_handler_module, "show_warning") as warning,
            patch.object(import_handler_module, "show_critical") as critical,
        ):
            for status in (
                MutationOutcomeStatus.COMMITTED,
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.REJECTED,
            ):
                service.queued_imports[0][4](
                    QueuedMutationResult(
                        database_id="target.mdb",
                        runtime_generation=1,
                        operation_id=str(uuid.uuid4()),
                        outcome_status=status,
                    )
                )
        info.assert_not_called()
        warning.assert_not_called()
        critical.assert_not_called()

    def test_sql_import_reports_queue_failure_without_progress_dialog(self):
        service = _import_workflow_FakeImportService()
        service.sql_collaboration = True

        def failing_queue(*_args):
            raise RuntimeError("queue closed")

        service.queue_project_import = failing_queue
        handler = self._make_handler(service)
        with (
            patch.object(
                import_handler_module.QtWidgets.QFileDialog,
                "getOpenFileName",
                return_value=("source.ost", ""),
            ),
            patch.object(
                import_handler_module,
                "ProgressDialog",
                side_effect=AssertionError("SQL import must not use the modal path"),
            ),
            patch.object(import_handler_module, "show_critical") as critical,
            self.assertLogs(import_handler_module.logger, level="ERROR"),
        ):
            handler.import_ost()
        critical.assert_called_once_with(
            None, "Import Error", "The OST import could not be queued."
        )
        self.assertEqual(service.import_calls, [])


class ImportHandlerOutcomeFromResultTests(unittest.TestCase):
    """Decision S1: an Access import is a success or a failure by the worker result only.
    ProgressDialog.reject() is allowed once the result has arrived and its thread has
    stopped, so Esc in the window before the queued QThread.finished slot runs ends
    exec() with Rejected AFTER the import committed; the dialog code must not turn that
    committed import into a failed import or skip the refresh and success message."""

    ACCEPTED = QtWidgets.QDialog.DialogCode.Accepted
    REJECTED = QtWidgets.QDialog.DialogCode.Rejected
    FAILED_TEXT = (
        "Failed to import OST file. "
        "The file may be corrupted or in an unsupported format."
    )

    def _handler(self, service, window=None):
        return ImportHandler(
            window=window,
            project_data_service=_import_workflow_FakeProjectData(),
            import_service=service,
            ui_state_manager=_import_workflow_FakeUiState(),
            deferred_persistence_manager=_import_workflow_FakeDeferredPersistence(),
            ui_access_manager=_import_workflow_FakeAccess(),
        )

    def _import(self, handler, dialog_class):
        with (
            patch.object(
                import_handler_module.QtWidgets.QFileDialog,
                "getOpenFileName",
                return_value=("source.ost", ""),
            ),
            patch.object(import_handler_module, "ProgressDialog", dialog_class),
            patch.object(import_handler_module, "show_info") as info,
            patch.object(import_handler_module, "show_warning") as warning,
            patch.object(import_handler_module, "show_critical") as critical,
        ):
            handler.import_ost()
        return info, warning, critical

    def _fixed_code_dialog(self, code, error=None):
        class FixedCodeDialog(_import_workflow_FakeProgressDialog):
            result_code = code

            def __init__(self, filename, task_fn, parent=None):
                super().__init__(filename, task_fn, parent=parent)
                self.error = error

        return FixedCodeDialog

    def test_a_committed_import_survives_a_dialog_rejected_after_the_result(self):
        for code in (self.ACCEPTED, self.REJECTED):
            with self.subTest(code=code):
                service = _import_workflow_FakeImportService()
                info, warning, critical = self._import(
                    self._handler(service), self._fixed_code_dialog(code)
                )
                self.assertEqual(service.reloads, ["target.mdb"])
                info.assert_called_once_with(
                    None,
                    "Import Complete",
                    "Successfully imported 'source.ost' into the database.",
                )
                warning.assert_not_called()
                critical.assert_not_called()

    def test_a_rejected_dialog_after_a_committed_import_still_reports_a_failed_refresh(
        self,
    ):
        service = _import_workflow_FakeImportService()
        service.reload_result = False
        info, warning, critical = self._import(
            self._handler(service), self._fixed_code_dialog(self.REJECTED)
        )
        self.assertEqual(service.reloads, ["target.mdb"])
        info.assert_not_called()
        warning.assert_called_once()
        self.assertEqual(warning.call_args.args[1], "Refresh Error")
        critical.assert_not_called()

    def test_an_import_that_did_not_commit_fails_for_every_dialog_code(self):
        for code in (self.ACCEPTED, self.REJECTED):
            for result in (False, None):
                with self.subTest(code=code, result=result):
                    service = _import_workflow_FakeImportService()
                    service.next_result = result
                    info, warning, critical = self._import(
                        self._handler(service), self._fixed_code_dialog(code)
                    )
                    self.assertEqual(service.reloads, [])
                    info.assert_not_called()
                    warning.assert_not_called()
                    critical.assert_called_once_with(
                        None, "Import Error", self.FAILED_TEXT
                    )

    def test_a_crashed_worker_without_a_result_fails_for_every_dialog_code(self):
        for code in (self.ACCEPTED, self.REJECTED):
            for error in (None, RuntimeError("worker died")):
                with self.subTest(code=code, error=error):
                    service = _import_workflow_FakeImportService()
                    service.next_result = None
                    with patch.object(import_handler_module, "logger") as logger:
                        info, warning, critical = self._import(
                            self._handler(service),
                            self._fixed_code_dialog(code, error),
                        )
                    self.assertEqual(logger.error.call_count, int(error is not None))
                    self.assertEqual(service.reloads, [])
                    info.assert_not_called()
                    warning.assert_not_called()
                    critical.assert_called_once_with(
                        None, "Import Error", self.FAILED_TEXT
                    )

    def _escaping_dialog_class(self, escape_after_result):
        from ost_visualizer.presentation.components.progress_dialog import (
            ProgressDialog as RealProgressDialog,
        )

        class EscapeBetweenResultAndFinishedSlot(RealProgressDialog):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.escaped = False
                guard = QtCore.QTimer(self)
                guard.setSingleShot(True)
                guard.timeout.connect(lambda: QtWidgets.QDialog.reject(self))
                guard.start(8000)

            def _finish_if_ready(self):
                if escape_after_result and self._worker_finished:
                    if not self.escaped:
                        self.escaped = True
                        self._thread.wait(5000)
                        self.reject()
                    return
                super()._finish_if_ready()

        return EscapeBetweenResultAndFinishedSlot

    def _import_through_a_real_dialog(
        self, *, escape_after_result, service=None, fail_with=None
    ):
        QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        window = QtWidgets.QWidget()
        service = service or _import_workflow_FakeImportService()
        if fail_with is not None:

            def failing_import(*_args, **_kwargs):
                raise fail_with

            service.import_ost = failing_import
        try:
            with patch.object(import_handler_module, "logger") as logger:
                info, warning, critical = self._import(
                    self._handler(service, window),
                    self._escaping_dialog_class(escape_after_result),
                )
        finally:
            window.deleteLater()
        return service, info, warning, critical, window, logger

    def test_esc_between_the_worker_result_and_the_finished_slot_keeps_a_committed_import(
        self,
    ):
        service, info, warning, critical, window, _logger = (
            self._import_through_a_real_dialog(escape_after_result=True)
        )
        self.assertEqual(
            service.import_calls, [("source.ost", "target.mdb", None, False)]
        )
        self.assertEqual(service.reloads, ["target.mdb"])
        info.assert_called_once_with(
            window,
            "Import Complete",
            "Successfully imported 'source.ost' into the database.",
        )
        warning.assert_not_called()
        critical.assert_not_called()

    def test_a_real_dialog_without_an_escape_reports_the_same_committed_import(self):
        service, info, warning, critical, window, _logger = (
            self._import_through_a_real_dialog(escape_after_result=False)
        )
        self.assertEqual(service.reloads, ["target.mdb"])
        info.assert_called_once_with(
            window,
            "Import Complete",
            "Successfully imported 'source.ost' into the database.",
        )
        warning.assert_not_called()
        critical.assert_not_called()

    def test_a_real_dialog_reports_a_refused_import_as_a_failure_with_or_without_an_escape(
        self,
    ):
        for escape in (False, True):
            with self.subTest(escape=escape):
                service = _import_workflow_FakeImportService()
                service.next_result = False
                service, info, warning, critical, window, _logger = (
                    self._import_through_a_real_dialog(
                        escape_after_result=escape, service=service
                    )
                )
                self.assertEqual(service.reloads, [])
                info.assert_not_called()
                warning.assert_not_called()
                critical.assert_called_once_with(
                    window, "Import Error", self.FAILED_TEXT
                )

    def test_a_real_dialog_reports_a_raising_worker_as_a_failure_with_or_without_an_escape(
        self,
    ):
        for escape in (False, True):
            with self.subTest(escape=escape):
                failure = OSError("source is unreadable")
                service, info, warning, critical, window, logger = (
                    self._import_through_a_real_dialog(
                        escape_after_result=escape, fail_with=failure
                    )
                )
                self.assertEqual(service.reloads, [])
                info.assert_not_called()
                warning.assert_not_called()
                critical.assert_called_once_with(
                    window, "Import Error", self.FAILED_TEXT
                )
                logger.error.assert_called_once()
                self.assertIs(logger.error.call_args.args[2], failure)
