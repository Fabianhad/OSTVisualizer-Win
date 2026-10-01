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
from ost_visualizer.presentation.config import (
    COMPACT_MARGINS,
    COMPACT_SPACING,
    NEW_DATABASE_TYPE_DIALOG_WIDTH,
    RELAXED_MARGINS,
    RELAXED_SPACING,
    SELECT_DATABASE_TYPE_DIALOG_WIDTH,
    SQL_CONNECTION_DIALOG_WIDTH,
    SQL_DATABASE_PROPERTIES_DIALOG_WIDTH,
)
from ost_visualizer.presentation.dialogs.select_database_type_dialog import (
    SelectDatabaseTypeDialog,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.sql.database_foundation_support import (
    _IconProvider as _database_foundation_support__IconProvider,
    _app as _database_foundation_support__app,
)


class SelectDatabaseTypeDialogSqlDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()
        cls.icon_provider = _database_foundation_support__IconProvider()

    def test_database_type_defaults_to_access(self):
        self.assertEqual(SELECT_DATABASE_TYPE_DIALOG_WIDTH, 270)
        dialog = SelectDatabaseTypeDialog(self.icon_provider)
        try:
            margins = dialog.layout().contentsMargins()
            self.assertEqual(
                (margins.left(), margins.top(), margins.right(), margins.bottom()),
                COMPACT_MARGINS,
            )
            self.assertEqual(dialog.layout().spacing(), COMPACT_SPACING)
            self.assertEqual(dialog.size().width(), SELECT_DATABASE_TYPE_DIALOG_WIDTH)
            self.assertEqual(dialog.minimumSize(), dialog.maximumSize())
            self.assertEqual(
                dialog.button_box.orientation(), QtCore.Qt.Orientation.Vertical
            )
            self.assertEqual(
                dialog.layout().itemAt(1).alignment(),
                QtCore.Qt.AlignmentFlag.AlignBottom,
            )
            self.assertTrue(dialog.access_radio.isChecked())
            self.assertEqual(dialog.selected_backend(), DatabaseBackend.ACCESS)
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
            dialog.sql_server_radio.setChecked(True)
            self.assertFalse(dialog.access_radio.isChecked())
            self.assertEqual(dialog.selected_backend(), DatabaseBackend.SQL_SERVER)
            dialog.button_box.button(
                QtWidgets.QDialogButtonBox.StandardButton.Ok
            ).click()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        finally:
            dialog.cleanup()
            dialog.deleteLater()
