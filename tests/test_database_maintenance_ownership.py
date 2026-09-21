import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading
import tempfile
from pathlib import Path
from ost_visualizer.infrastructure.mdb.database_maintenance import (
    MdbDatabaseMaintenance,
)
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.maintenance_router import (
    DatabaseMaintenanceRouter,
)
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from shiboken6 import delete
from ost_visualizer.application.interfaces.i_database_maintenance import (
    DatabaseMaintenanceResult,
)
from ost_visualizer.application.services.database_maintenance_service import (
    DatabaseMaintenanceService,
)
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.presentation.components.progress_dialog import ProgressDialog
from ost_visualizer.presentation.dialogs.open_files_dialog import OpenFilesDialog
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)
from ost_visualizer.presentation.main_window import MainWindow
from tests.workspace_state_test_support import make_workspace_state_model


class MaintenanceOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_first_request_captures_source_after_cached_writer_finalizes(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"before writer closes")
            manager = MdbConnectionManager()
            backend = MdbDatabaseMaintenance(manager)
            files = Mock()
            owner = SimpleNamespace(file_path=str(source))
            files.data_service.get_hierarchy.return_value.loaded_files = [owner]
            files.reload_database.return_value.success = True
            router = DatabaseMaintenanceRouter(
                DatabaseDescriptorRegistry(), backend, Mock()
            )
            service = DatabaseMaintenanceService(router, files, Mock())
            engine = Mock()
            engine.CompactDatabase.side_effect = lambda src, dst: Path(dst).write_bytes(
                Path(src).read_bytes()
            )

            def replace(src, dst, backup):
                os.rename(src, backup)
                os.rename(dst, src)

            with patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                return_value=engine,
            ), patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                return_value={"Data": 1},
            ), patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance._replace_file",
                replace,
            ):
                for operation in range(2):
                    writer = Mock()
                    finalized = f"committed writer {operation}".encode()
                    writer.close.side_effect = lambda: source.write_bytes(finalized)
                    manager._write_conns[os.path.normcase(str(source))] = writer
                    target = service.capture_target(str(source))
                    progress = ProgressDialog(
                        str(source), lambda: service.prepare(target)
                    )
                    try:
                        progress.exec()
                        if progress.error is not None:
                            raise progress.error
                        prepared = progress.result
                    finally:
                        progress.cleanup()
                        delete(progress)
                    self.assertTrue(service.finish(target, prepared, Mock()).success)
                    self.assertEqual(source.read_bytes(), finalized)
                    writer.close.assert_called_once()
                    self.assertFalse(manager._maintenance_paths)
                    self.assertFalse(manager._write_conns)
                    self.assertFalse(service._operation_lock.locked())
            self.assertEqual(files.reload_database.call_count, 2)

    def test_changed_owner_or_source_before_prepare_never_starts_compaction(self):
        for change in ("owner", "unload", "source", "replacement"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / "db.mdb"
                source.write_bytes(b"original")
                manager = MdbConnectionManager()
                backend = MdbDatabaseMaintenance(manager)
                files = Mock()
                hierarchy = SimpleNamespace(
                    loaded_files=[SimpleNamespace(file_path=str(source))]
                )
                files.data_service.get_hierarchy.return_value = hierarchy
                service = DatabaseMaintenanceService(backend, files, Mock())
                target = service.capture_target(str(source))
                if change == "owner":
                    hierarchy.loaded_files = [SimpleNamespace(file_path=str(source))]
                elif change == "unload":
                    hierarchy.loaded_files = []
                elif change == "source":
                    source.write_bytes(b"new external contents")
                else:
                    replacement = source.with_suffix(".replacement")
                    replacement.write_bytes(source.read_bytes())
                    stamp = source.stat()
                    os.utime(replacement, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                    os.replace(replacement, source)
                with patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch"
                ) as engine:
                    with self.assertRaisesRegex(
                        RuntimeError, "selected database changed"
                    ):
                        service.prepare(target)
                    engine.assert_not_called()
                self.assertFalse(manager._maintenance_paths)
                self.assertFalse(service._operation_lock.locked())
                files.reload_database.assert_not_called()
                service.release_target(target)

    def test_capture_reserves_closed_handles_until_cancelled(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            manager = MdbConnectionManager()
            backend = MdbDatabaseMaintenance(manager)
            identity = backend.capture_target(str(source))
            try:
                for mode in (True, False):
                    with self.assertRaisesRegex(RuntimeError, "maintenance"):
                        with manager.connection(str(source), autocommit=mode):
                            self.fail("confirmation reopened an MDB connection")
                self.assertTrue(backend.is_target_current(str(source), identity))
                with self.assertRaisesRegex(RuntimeError, "active operations"):
                    backend.capture_target(str(source))
            finally:
                backend.release_target(str(source), identity)
            backend.release_target(str(source), identity)
            self.assertFalse(manager._maintenance_paths)
            self.assertFalse(backend.is_target_current(str(source), identity))
            replacement = backend.capture_target(str(source))
            backend.release_target(str(source), replacement)
            self.assertFalse(manager._maintenance_paths)

    def test_replacement_during_handle_release_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            replacement = source.with_suffix(".replacement")
            replacement.write_bytes(b"replacement")
            manager = MdbConnectionManager()
            writer = Mock()
            writer.close.side_effect = lambda: os.replace(replacement, source)
            manager._write_conns[os.path.normcase(str(source))] = writer
            with self.assertRaisesRegex(RuntimeError, "selected database changed"):
                MdbDatabaseMaintenance(manager).capture_target(str(source))
            self.assertFalse(manager._maintenance_paths)
            self.assertFalse(manager._write_conns)
            self.assertEqual(source.read_bytes(), b"replacement")

    def test_escape_cannot_finish_progress_before_worker(self):
        release = threading.Event()
        dialog = ProgressDialog("database", lambda: release.wait(2))
        timer = threading.Timer(0.15, release.set)
        timer.start()
        QtCore.QTimer.singleShot(
            20, lambda: QtTest.QTest.keyClick(dialog, QtCore.Qt.Key.Key_Escape)
        )
        try:
            dialog.exec()
            self.assertTrue(
                release.is_set(), "Escape returned while maintenance still runs"
            )
            self.assertTrue(dialog.result)
        finally:
            release.set()
            timer.join()
            dialog.cleanup()
            delete(dialog)

    def test_shutdown_does_not_start_during_maintenance(self):
        host = SimpleNamespace(
            _application_shutdown_finalized=False,
            _collaboration_shutdown_pending=False,
            _collaboration_shutdown_failed=False,
            _collaboration_shutdown_complete=False,
            handlers=SimpleNamespace(
                file_ops=SimpleNamespace(maintenance_pending=True)
            ),
            hide=Mock(),
            _begin_application_shutdown=Mock(),
        )
        event = QtGui.QCloseEvent()
        with patch(
            "ost_visualizer.presentation.main_window.QtCore.QTimer.singleShot"
        ) as queued:
            MainWindow.closeEvent(host, event)
        self.assertFalse(event.isAccepted())
        host.hide.assert_not_called()
        queued.assert_not_called()

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

    def test_staging_holds_leases_until_commit_or_discard(self):
        for failure in ("fsync", "replace", "partial_replace", "restore", "none"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / "db.mdb"
                source.write_bytes(b"original")
                manager = MdbConnectionManager()
                engine = Mock()
                engine.CompactDatabase.side_effect = lambda _src, dst: Path(
                    dst
                ).write_bytes(b"compacted")
                real_rename = os.rename

                def replace(src, dst, backup):
                    if failure in ("partial_replace", "restore"):
                        real_rename(src, backup)
                    if failure != "none":
                        raise OSError("replacement failure")
                    real_rename(src, backup)
                    real_rename(dst, src)

                def rename(src, dst):
                    if failure == "restore":
                        raise OSError("recovery blocked")
                    real_rename(src, dst)

                with patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                    return_value=engine,
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                    return_value={"Data": 1},
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance.os.fsync",
                    side_effect=OSError("fsync") if failure == "fsync" else None,
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance._replace_file",
                    replace,
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance.os.rename",
                    rename,
                ):
                    backend = MdbDatabaseMaintenance(manager)
                    if failure == "fsync":
                        with self.assertRaises(OSError):
                            backend.prepare(
                                str(source), backend.capture_target(str(source))
                            )
                    else:
                        staged = backend.prepare(
                            str(source), backend.capture_target(str(source))
                        )
                        try:
                            self.assertEqual(source.read_bytes(), b"original")
                            with self.assertRaisesRegex(RuntimeError, "maintenance"):
                                with manager.connection(str(source)):
                                    self.fail("lease escaped staging exclusion")
                            if failure == "none":
                                self.assertTrue(staged.commit().success)
                            else:
                                with self.assertRaises((OSError, RuntimeError)):
                                    staged.commit()
                        finally:
                            staged.close()
                self.assertFalse(manager._maintenance_paths)
                if failure == "restore":
                    backups = list(Path(folder).glob(".ost-compact-*/original.backup"))
                    self.assertEqual(len(backups), 1)
                    self.assertEqual(backups[0].read_bytes(), b"original")
                else:
                    self.assertEqual(
                        source.read_bytes(),
                        b"compacted" if failure == "none" else b"original",
                    )
                    self.assertEqual(list(Path(folder).iterdir()), [source])

    def test_maintenance_exclusion_covers_authoritative_reload(self):
        files, backend = Mock(), Mock()
        files.data_service.get_hierarchy.return_value.loaded_files = [
            SimpleNamespace(file_path="db.mdb")
        ]
        files.is_loaded.return_value = True
        backend.capture_target.return_value = "source"
        staged = backend.prepare.return_value
        staged.commit.return_value = DatabaseMaintenanceResult(True, "done")
        service = DatabaseMaintenanceService(backend, files, Mock())
        target = service.capture_target("db.mdb")
        service.prepare(target)

        def reload(_locator):
            with self.assertRaisesRegex(RuntimeError, "already running"):
                service.prepare(target)
            return SimpleNamespace(success=True)

        files.reload_database.side_effect = reload
        self.assertTrue(service.finish(target, staged, Mock()).success)
        self.assertFalse(service._operation_lock.locked())

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

    def test_last_moment_external_write_is_not_lost(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            manager = MdbConnectionManager()
            engine = Mock()
            engine.CompactDatabase.side_effect = lambda _src, dst: Path(
                dst
            ).write_bytes(b"compacted")
            calls = []

            def replace(src, dst, backup):
                if not calls:
                    source.write_bytes(b"newer external data")
                calls.append(True)
                os.rename(src, backup)
                os.rename(dst, src)

            with patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                return_value=engine,
            ), patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                return_value={"Data": 1},
            ), patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance._replace_file",
                replace,
            ):
                with self.assertRaisesRegex(RuntimeError, "changed"):
                    MdbDatabaseMaintenance(manager).compact(str(source))
            self.assertEqual(source.read_bytes(), b"newer external data")
            self.assertEqual(list(Path(folder).iterdir()), [source])
            self.assertFalse(manager._maintenance_paths)

    def test_refresh_uses_loaded_owner_path_for_case_equivalent_target(self):
        files = Mock()
        owner = SimpleNamespace(file_path="C:/Data/Project.mdb")
        files.data_service.get_hierarchy.return_value.loaded_files = [owner]
        files.is_loaded.return_value = False  # Existing is_loaded uses exact spelling.
        files.reload_database.return_value.success = True
        events = Mock()
        service = DatabaseMaintenanceService(Mock(), files, events)
        self.assertTrue(
            service.refresh_loaded_database("c:/data/project.mdb", Mock()).success
        )
        files.reload_database.assert_called_once_with(owner.file_path)
        events.publish.assert_called_once()

    def test_reload_failure_clears_old_authoritative_projection(self):
        files = Mock()
        files.is_loaded.return_value = True
        files.reload_database.return_value.success = False
        files.unload_file.return_value.success = True
        files.data_service.get_hierarchy.return_value.loaded_files = [
            SimpleNamespace(file_path="db.mdb")
        ]
        service = DatabaseMaintenanceService(Mock(), files, Mock())
        unload = Mock(return_value=True)
        self.assertFalse(service.refresh_loaded_database("db.mdb", unload).success)
        unload.assert_called_once_with("db.mdb")
