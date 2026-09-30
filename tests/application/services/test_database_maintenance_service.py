import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.interfaces.i_database_maintenance import (
    DatabaseMaintenanceResult,
)
from ost_visualizer.application.services.database_maintenance_service import (
    DatabaseMaintenanceService,
)
from PySide6 import QtCore, QtGui, QtTest, QtWidgets


class MaintenanceRefreshTests(unittest.TestCase):
    def test_duplicate_operation_and_main_thread_refresh(self):
        backend, files, events = Mock(), Mock(), Mock()
        backend.unavailable_reason.return_value = ""
        service = DatabaseMaintenanceService(backend, files, events)
        overlapping = []

        def compact(_locator):
            overlapping.append(service.compact("db.mdb"))
            return DatabaseMaintenanceResult(True, "done")

        backend.compact.side_effect = compact
        self.assertFalse(service.compact("").success)
        self.assertTrue(service.compact("db.mdb").success)
        self.assertFalse(overlapping[0].success)
        backend.compact.assert_called_once()
        files.is_loaded.return_value = True
        files.data_service.get_hierarchy.return_value.loaded_files = [
            SimpleNamespace(file_path="db.mdb")
        ]
        files.reload_database.return_value.success = True
        self.assertTrue(service.refresh_loaded_database("db.mdb", Mock()).success)
        files.reload_database.assert_called_once_with("db.mdb")
        events.publish.assert_called_once()


class MaintenanceServiceOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

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
