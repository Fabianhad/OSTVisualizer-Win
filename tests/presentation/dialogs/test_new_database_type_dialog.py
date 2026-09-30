import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.presentation.dialogs.new_database_type_dialog import (
    NewDatabaseTypeDialog,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.sql.database_foundation_support import (
    _IconProvider as _database_foundation_support__IconProvider,
    _app as _database_foundation_support__app,
)


class NewDatabaseTypeDialogSqlDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()
        cls.icon_provider = _database_foundation_support__IconProvider()

    def test_new_database_type_panels_select_expected_backend(self):
        access = NewDatabaseTypeDialog(self.icon_provider)
        try:
            access.access_button.click()
            self.assertEqual(access.selected_backend(), DatabaseBackend.ACCESS)
        finally:
            access.cleanup()
            access.deleteLater()
        sql = NewDatabaseTypeDialog(self.icon_provider)
        try:
            sql.sql_server_button.click()
            self.assertEqual(sql.selected_backend(), DatabaseBackend.SQL_SERVER)
        finally:
            sql.cleanup()
            sql.deleteLater()
