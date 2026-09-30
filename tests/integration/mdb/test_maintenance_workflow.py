import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.services.database_maintenance_service import (
    DatabaseMaintenanceService,
)
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
from ost_visualizer.infrastructure.mdb.database_maintenance import (
    MdbDatabaseMaintenance,
)
from types import SimpleNamespace
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.maintenance_router import (
    DatabaseMaintenanceRouter,
)
from ost_visualizer.presentation.components.progress_dialog import ProgressDialog
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from shiboken6 import delete


class DatabaseMaintenanceFailureWorkflowTests(unittest.TestCase):
    def test_compaction_and_validation_failure_leave_original_intact(self):
        for failure in ("compact", "validation", "replace"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / "test.mdb"
                source.write_bytes(b"original database contents")
                engine = Mock()

                def compact(_source, destination):
                    Path(destination).write_bytes(b"compacted")
                    if failure == "compact":
                        raise RuntimeError("engine failure")

                engine.CompactDatabase.side_effect = compact
                counts = [{"Data": 2}, {"Data": 1 if failure == "validation" else 2}]
                with patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                    return_value=engine,
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                    side_effect=counts,
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance._replace_file",
                    side_effect=OSError("replacement failed"),
                ):
                    service = DatabaseMaintenanceService(
                        MdbDatabaseMaintenance(MdbConnectionManager()), Mock(), Mock()
                    )
                    result = service.compact(str(source))
                self.assertFalse(result.success)
                self.assertEqual(source.read_bytes(), b"original database contents")
                self.assertEqual(list(Path(folder).iterdir()), [source])

    def test_source_change_during_compaction_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "test.mdb"
            source.write_bytes(b"original")
            engine = Mock()

            def compact(_source, destination):
                Path(destination).write_bytes(b"compacted")
                source.write_bytes(b"newer external contents")

            engine.CompactDatabase.side_effect = compact
            with patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                return_value=engine,
            ), patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                return_value={"Data": 1},
            ):
                result = DatabaseMaintenanceService(
                    MdbDatabaseMaintenance(MdbConnectionManager()), Mock(), Mock()
                ).compact(str(source))
            self.assertFalse(result.success)
            self.assertEqual(source.read_bytes(), b"newer external contents")


class MaintenanceCapturedOwnerWorkflowTests(unittest.TestCase):
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
