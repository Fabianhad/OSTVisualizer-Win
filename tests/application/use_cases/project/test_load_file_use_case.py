import logging
import unittest
from types import SimpleNamespace
from ost_visualizer.application.use_cases.project.load_file_use_case import (
    LoadFileUseCase,
)
from ost_visualizer.domain.entities.file_results import FileLoadResult
from PySide6 import QtCore, QtWidgets


class StartupLoadFileFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_failed_database_load_preserves_existing_access_projection(self):
        class _DataService:
            reset_count = 0

            def reset(self):
                self.reset_count += 1

        data_service = _DataService()
        model = SimpleNamespace(projects=["access-project"])
        file_manager = SimpleNamespace(
            load_file=lambda _locator: FileLoadResult(
                success=False, error_message="server unavailable"
            )
        )
        use_case = LoadFileUseCase(
            model,
            data_service,
            file_manager,
            logging.getLogger("test.startup.load"),
        )
        self.assertFalse(use_case.execute("sql-database-id"))
        self.assertEqual(data_service.reset_count, 0)
        self.assertEqual(model.projects, ["access-project"])
