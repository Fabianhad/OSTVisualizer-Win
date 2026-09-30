import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.interfaces.i_database_maintenance import (
    DatabaseMaintenanceResult,
)
from ost_visualizer.application.services.database_maintenance_service import (
    DatabaseMaintenanceService,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.maintenance_router import (
    DatabaseMaintenanceRouter,
)
from ost_visualizer.infrastructure.sql.database_maintenance import (
    SqlDatabaseMaintenance,
)
from ost_visualizer.presentation.dialogs.open_files_dialog import OpenFilesDialog
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)
from PySide6 import QtWidgets
from shiboken6 import delete
from tests.helpers.workspace_state import make_workspace_state_model
from types import SimpleNamespace
from PySide6 import QtCore, QtGui, QtTest, QtWidgets


class DatabaseMaintenanceUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_sql_result_is_explicit_and_access_denial_is_inert(self):
        host = QtWidgets.QWidget()
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(
                server="server",
                database="db",
                database_guid="00000000-0000-0000-0000-000000000001",
            ),
            schema_version=1,
        )
        registry.register(descriptor)
        access = Mock()
        service = DatabaseMaintenanceService(
            DatabaseMaintenanceRouter(registry, access, SqlDatabaseMaintenance()),
            Mock(),
            Mock(),
        )
        handler = FileOperationHandler(
            host,
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            make_workspace_state_model(),
            database_maintenance_service=service,
        )
        handler._ui_access_manager.can_maintain_database.return_value = True
        dialog = OpenFilesDialog(
            Mock(),
            host,
            [FileEntry(descriptor=descriptor)],
            Mock(),
            make_workspace_state_model(),
            maintenance_allowed_fn=handler._maintenance_allowed,
        )
        try:
            dialog.table.setCurrentItem(dialog.table.topLevelItem(0))
            dialog.maintenance_requested.connect(
                lambda entry: handler._compact_database(dialog, entry)
            )
            with patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
            ) as warning:
                dialog.compact_button.click()
                warning.assert_called_once()
                self.assertIn("not available for SQL Server", warning.call_args.args[2])
            access.compact.assert_not_called()
            handler._ui_access_manager.can_maintain_database.return_value = False
            dialog._update_remove_button_state()
            self.assertFalse(dialog.compact_button.isEnabled())
            with patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
            ) as warning:
                dialog._on_compact()
                warning.assert_not_called()
        finally:
            dialog.cleanup()
            delete(host)

    def test_actions_and_single_result_without_rebuilding_selection(self):
        for succeeds in (True, False):
            with self.subTest(succeeds=succeeds):
                host = QtWidgets.QWidget()
                service = Mock()
                service.unavailable_reason.return_value = ""
                service.finish.return_value = DatabaseMaintenanceResult(
                    succeeds, "result"
                )
                handler = FileOperationHandler(
                    host,
                    Mock(),
                    Mock(),
                    Mock(),
                    Mock(),
                    Mock(),
                    Mock(),
                    Mock(),
                    Mock(),
                    Mock(),
                    Mock(),
                    make_workspace_state_model(),
                    database_maintenance_service=service,
                )
                handler._ui_access_manager.can_maintain_database.return_value = True
                handler._deferred_persistence.flush_for_file.return_value = True
                dialog = OpenFilesDialog(
                    Mock(),
                    host,
                    [FileEntry(file_path="test.mdb")],
                    Mock(),
                    make_workspace_state_model(),
                    maintenance_allowed_fn=handler._maintenance_allowed,
                )
                try:
                    self.assertEqual(
                        dialog.findChild(QtWidgets.QGroupBox).title(),
                        "Database Actions",
                    )
                    self.assertFalse(dialog.compact_button.isEnabled())
                    dialog.compact_button.click()
                    service.compact.assert_not_called()
                    item = dialog.table.topLevelItem(0)
                    dialog.table.setCurrentItem(item)
                    self.assertTrue(dialog.compact_button.isEnabled())
                    dialog.maintenance_requested.connect(
                        lambda entry: handler._compact_database(dialog, entry)
                    )

                    def exec_progress(progress):
                        dialog.compact_button.click()
                        progress._result = progress._task_fn()
                        return QtWidgets.QDialog.DialogCode.Accepted

                    with patch(
                        "ost_visualizer.presentation.handlers.file_operation_handler.confirm",
                        return_value=True,
                    ), patch(
                        "ost_visualizer.presentation.handlers.file_operation_handler.ProgressDialog.exec",
                        exec_progress,
                    ), patch(
                        "ost_visualizer.presentation.handlers.file_operation_handler.show_info"
                    ) as info, patch(
                        "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
                    ) as warning:
                        dialog.compact_button.click()
                    service.prepare.assert_called_once_with(
                        service.capture_target.return_value
                    )
                    service.finish.assert_called_once_with(
                        service.capture_target.return_value,
                        service.prepare.return_value,
                        handler._unload_file_fn,
                    )
                    self.assertEqual(info.call_count, int(succeeds))
                    self.assertEqual(warning.call_count, int(not succeeds))
                    self.assertIs(dialog.table.currentItem(), item)
                    self.assertTrue(dialog.compact_button.isEnabled())
                    self.assertFalse(handler._file_operation_pending)
                finally:
                    dialog.cleanup()
                    delete(host)


class MaintenanceUiOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _run_ordering(self, transition, during_progress, *, before_prepare=False):
        host = QtWidgets.QWidget()
        entry = FileEntry("test.mdb")
        owner = SimpleNamespace(file_path=entry.runtime_locator)
        hierarchy = SimpleNamespace(loaded_files=[owner])
        files = Mock()
        files.data_service.get_hierarchy.side_effect = lambda: hierarchy
        files.is_loaded.return_value = True
        files.reload_database.return_value.success = True
        backend = Mock()
        backend.unavailable_reason.return_value = ""
        backend.capture_target.return_value = "source-A"
        backend.is_target_current.side_effect = (
            lambda _locator, identity: backend.capture_target.return_value == identity
        )
        committed = Mock(return_value=DatabaseMaintenanceResult(True, "done"))
        staged = Mock()
        staged.commit.side_effect = committed
        backend.prepare.return_value = staged
        if transition == "engine":
            backend.prepare.side_effect = RuntimeError("DAO failed")
        backend.compact.side_effect = committed
        service = DatabaseMaintenanceService(backend, files, Mock())
        access = Mock()
        access.can_maintain_database.return_value = True
        handler = FileOperationHandler(
            host,
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            files,
            Mock(),
            Mock(),
            Mock(),
            access,
            Mock(),
            make_workspace_state_model(),
            database_maintenance_service=service,
        )
        handler._deferred_persistence.flush_for_file.return_value = True
        dialog = OpenFilesDialog(
            Mock(),
            host,
            [entry],
            Mock(),
            make_workspace_state_model(),
            maintenance_allowed_fn=handler._maintenance_allowed,
        )
        dialog.table.setCurrentItem(dialog.table.topLevelItem(0))
        target = dialog.maintenance_target()

        def change():
            if transition == "access":
                access.can_maintain_database.return_value = False
            elif transition == "replacement":
                hierarchy.loaded_files = [
                    SimpleNamespace(file_path=entry.runtime_locator)
                ]
            elif transition == "unload":
                hierarchy.loaded_files = []
            elif transition == "source":
                backend.capture_target.return_value = "source-B"
            elif transition == "cleanup":
                dialog.cleanup()
            elif transition == "cleanup_failure":
                access.can_maintain_database.return_value = False
                staged.close.side_effect = OSError("temporary file is locked")

        def confirm(*_args):
            if not during_progress:
                change()
            return transition != "cancel"

        def progress_exec(progress):
            if before_prepare:
                change()
            try:
                progress._result = progress._task_fn()
            except Exception as exc:
                progress._result = False
                progress._error = exc
            if during_progress and not before_prepare:
                change()
            return QtWidgets.QDialog.DialogCode.Accepted

        if transition == "initial_selection":
            dialog.table.clearSelection()
        try:
            with patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.confirm",
                confirm,
            ), patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.ProgressDialog.exec",
                progress_exec,
            ), patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.show_info"
            ) as info, patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
            ) as warning:
                handler._compact_database(dialog, target)
            if transition == "current":
                committed.assert_called_once()
                files.reload_database.assert_called_once_with(entry.runtime_locator)
                info.assert_called_once()
                self.assertIs(dialog.maintenance_target(), target)
            else:
                committed.assert_not_called()
                files.reload_database.assert_not_called()
                info.assert_not_called()
            self.assertFalse(service._operation_lock.locked())
            if transition != "initial_selection":
                backend.release_target.assert_called_with(
                    entry.runtime_locator, "source-A"
                )
                backend.capture_target.assert_called_once()
            if before_prepare:
                backend.prepare.assert_not_called()
            if transition == "initial_selection":
                handler._deferred_persistence.flush_for_file.assert_not_called()
            self.assertLessEqual(warning.call_count, 1)
            self.assertFalse(handler._file_operation_pending)
            self.assertFalse(handler.maintenance_pending)
            self.assertFalse(dialog._maintenance_busy)
        finally:
            dialog.cleanup()
            delete(host)

    def test_stale_confirmation_and_progress_never_replace_database(self):
        for during_progress in (False, True):
            for transition in (
                "access",
                "replacement",
                "unload",
                "source",
                "cleanup",
                "current",
                "engine",
                "initial_selection",
                "cleanup_failure",
                "cancel",
            ):
                with self.subTest(
                    during_progress=during_progress, transition=transition
                ):
                    self._run_ordering(transition, during_progress)

    def test_database_switch_during_progress_startup_rejects_before_prepare(self):
        for transition in ("replacement", "unload", "source"):
            with self.subTest(transition=transition):
                self._run_ordering(transition, True, before_prepare=True)

    def test_open_files_projects_access_changes_and_unsubscribes(self):
        host = QtWidgets.QWidget()
        entries = [FileEntry("test.mdb")]
        state = Mock()
        state.file_entries = entries
        access = Mock()
        access.can_maintain_database.return_value = True
        callbacks = []
        access.subscribe_access_state_changed.side_effect = callbacks.append
        handler = FileOperationHandler(
            host,
            Mock(),
            Mock(),
            state,
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            access,
            Mock(),
            make_workspace_state_model(),
            database_maintenance_service=Mock(),
        )
        dialog = OpenFilesDialog(
            Mock(),
            host,
            entries,
            Mock(),
            make_workspace_state_model(),
            maintenance_allowed_fn=handler._maintenance_allowed,
        )
        item = dialog.table.topLevelItem(0)
        dialog.table.setCurrentItem(item)

        def run():
            self.assertEqual(len(callbacks), 1)
            access.can_maintain_database.return_value = False
            callbacks[0]()
            self.assertFalse(dialog.compact_button.isEnabled())
            access.can_maintain_database.return_value = True
            callbacks[0]()
            self.assertTrue(dialog.compact_button.isEnabled())
            self.assertIs(dialog.table.currentItem(), item)
            return QtWidgets.QDialog.DialogCode.Rejected

        try:
            with patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.OpenFilesDialog",
                return_value=dialog,
            ), patch.object(dialog, "exec", run):
                handler.open_files()
            access.unsubscribe_access_state_changed.assert_called_once_with(
                callbacks[0]
            )
            callbacks[
                0
            ]()  # A delivery copied before unsubscribe is inert after cleanup.
        finally:
            delete(host)
