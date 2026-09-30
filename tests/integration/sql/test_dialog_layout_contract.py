import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
    SqlDatabaseCatalogEntry,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.infrastructure.sql.schema_definition import (
    SQL_SCHEMA_V1,
    schema_record_is_canonical,
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
from ost_visualizer.presentation.dialogs.new_database_type_dialog import (
    NewDatabaseTypeDialog,
)
from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
    SqlConnectionDialog,
    SqlConnectionDialogResult,
)
from ost_visualizer.presentation.dialogs.sql_database_dialog import (
    SqlDatabasePropertiesDialog,
    SqlDatabasePropertiesMode,
    SqlDatabasePropertiesResult,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.sql.database_foundation_support import (
    _Catalog as _database_foundation_support__Catalog,
    _IconProvider as _database_foundation_support__IconProvider,
    _SqlDatabaseCreator as _database_foundation_support__SqlDatabaseCreator,
    _app as _database_foundation_support__app,
)
from types import SimpleNamespace
from unittest.mock import Mock, patch
from ost_visualizer.application.interfaces.i_sql_database_creator import (
    SqlDatabaseCreationResult,
    SqlDatabaseRuntimeCredentials,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    validate_sql_database_creation_name,
    validate_sql_database_name,
)
from ost_visualizer.presentation.dialogs.sql_database_dialog import (
    SqlDatabasePropertiesDialog,
    SqlDatabasePropertiesMode,
)
from tests.helpers.sql.creation_handoff_support import (
    _CREATOR as _creation_handoff_support__CREATOR,
    _RUNTIME as _creation_handoff_support__RUNTIME,
)


class DialogLayoutContractSqlDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()
        cls.icon_provider = _database_foundation_support__IconProvider()

    def test_sql_dialog_titles_dimensions_and_modes(self):
        self.assertEqual(SQL_CONNECTION_DIALOG_WIDTH, 320)
        self.assertEqual(SQL_DATABASE_PROPERTIES_DIALOG_WIDTH, 320)
        self.assertEqual(NEW_DATABASE_TYPE_DIALOG_WIDTH, 350)
        connection = SqlConnectionDialog(self.icon_provider)
        margins = connection.layout().contentsMargins()
        self.assertEqual(
            (margins.left(), margins.top(), margins.right(), margins.bottom()),
            RELAXED_MARGINS,
        )
        self.assertEqual(connection.layout().spacing(), RELAXED_SPACING)
        self.assertEqual(connection.windowTitle(), "Connect to SQL Server")
        self.assertEqual(connection.size().width(), SQL_CONNECTION_DIALOG_WIDTH)
        self.assertEqual(connection.minimumSize(), connection.maximumSize())
        connection.cleanup()
        connection.deleteLater()
        initial = SqlConnectionDialogResult(
            SqlServerDatabaseLocation(server="localhost", database="")
        )
        selected = SqlDatabaseCatalogEntry(
            name="OSTV_TEST_VALID",
            database_guid="00000000-0000-0000-0000-000000000123",
            state="ONLINE",
            is_compatible=True,
            schema_version=SQL_SCHEMA_V1.version,
        )
        dialog = SqlDatabasePropertiesDialog(
            self.icon_provider,
            SqlDatabasePropertiesMode.OPEN,
            _database_foundation_support__Catalog([selected]),
            _database_foundation_support__SqlDatabaseCreator(),
            connection=initial,
            databases=[selected],
        )
        try:
            self.assertEqual(dialog.windowTitle(), "Database Properties (SQL Server)")
            self.assertEqual(
                dialog.size().width(), SQL_DATABASE_PROPERTIES_DIALOG_WIDTH
            )
            self.assertEqual(
                dialog.size().height(), dialog.layout().sizeHint().height()
            )
            self.assertEqual(dialog.minimumSize(), dialog.maximumSize())
            self.assertTrue(dialog.server_input.isReadOnly())
            self.assertFalse(dialog.database_combo.isHidden())
            self.assertTrue(dialog.database_name_input.isHidden())
            self.assertEqual(dialog.database_combo.count(), 1)
            self.assertTrue(dialog.trust_certificate_checkbox.isChecked())
        finally:
            dialog.cleanup()
            dialog.deleteLater()
        create_dialog = SqlDatabasePropertiesDialog(
            self.icon_provider,
            SqlDatabasePropertiesMode.CREATE,
            _database_foundation_support__Catalog([]),
            _database_foundation_support__SqlDatabaseCreator(),
        )
        try:
            self.assertFalse(create_dialog.server_input.isReadOnly())
            self.assertTrue(create_dialog.database_combo.isHidden())
            self.assertFalse(create_dialog.database_name_input.isHidden())
            self.assertTrue(create_dialog.trust_certificate_checkbox.isChecked())
        finally:
            create_dialog.cleanup()
            create_dialog.deleteLater()
        type_dialog = NewDatabaseTypeDialog(self.icon_provider)
        try:
            margins = type_dialog.layout().contentsMargins()
            self.assertEqual(
                (margins.left(), margins.top(), margins.right(), margins.bottom()),
                RELAXED_MARGINS,
            )
            self.assertEqual(type_dialog.layout().spacing(), RELAXED_SPACING)
            option_margins = type_dialog.access_button.layout().contentsMargins()
            self.assertEqual(
                (
                    option_margins.left(),
                    option_margins.top(),
                    option_margins.right(),
                    option_margins.bottom(),
                ),
                COMPACT_MARGINS,
            )
            self.assertEqual(
                type_dialog.access_button.layout().spacing(), COMPACT_SPACING
            )
            self.assertEqual(type_dialog.windowTitle(), "New Database Type")
            self.assertEqual(type_dialog.size().width(), NEW_DATABASE_TYPE_DIALOG_WIDTH)
            self.assertEqual(type_dialog.minimumSize(), type_dialog.maximumSize())
            self.assertEqual(
                type_dialog.access_button.layout().itemAt(0).widget().text(),
                "Microsoft Access Database (Most Users)",
            )
            self.assertEqual(
                type_dialog.sql_server_button.layout().itemAt(0).widget().text(),
                "Microsoft SQL Server Database",
            )
        finally:
            type_dialog.cleanup()
            type_dialog.deleteLater()


class DialogLayoutContractCreationDialogIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _dialog(self, creator, *, own_cleanup=True, prompt_creator=False):
        dialog = SqlDatabasePropertiesDialog(
            SimpleNamespace(set_window_icon=lambda _widget: None),
            SqlDatabasePropertiesMode.CREATE,
            None,
            creator,
            schema_change_allowed_fn=lambda: True,
        )
        if own_cleanup:
            self.addCleanup(dialog.deleteLater)
            self.addCleanup(dialog.cleanup)
        dialog.server_input.setText(_creation_handoff_support__CREATOR.server)
        dialog.database_name_input.setText("Test database")
        dialog.sql_auth_radio.setChecked(True)
        dialog.username_input.setText(_creation_handoff_support__RUNTIME.username)
        dialog.password_input.setText(_creation_handoff_support__RUNTIME.password)
        if not prompt_creator:
            prompt = patch.object(
                dialog,
                "_request_creator_connection",
                return_value=(
                    SqlConnectionDialogResult(
                        _creation_handoff_support__CREATOR, "creator-test-secret"
                    )
                ),
            )
            prompt.start()
            self.addCleanup(prompt.stop)
        return dialog

    def test_both_dialog_heights_follow_font_metrics(self):
        from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
            SqlConnectionDialog,
        )

        original_font = self.app.font()
        larger_font = self.app.font()
        larger_font.setPointSize(original_font.pointSize() + 4)
        normal = (self._dialog(Mock()), SqlConnectionDialog(Mock()))
        self.addCleanup(normal[1].deleteLater)
        self.addCleanup(normal[1].cleanup)
        try:
            self.app.setFont(larger_font)
            larger = (self._dialog(Mock()), SqlConnectionDialog(Mock()))
            self.addCleanup(larger[1].deleteLater)
            self.addCleanup(larger[1].cleanup)
            for before, after in zip(normal, larger):
                self.assertGreater(after.height(), before.height())
                self.assertEqual(after.height(), after.layout().sizeHint().height())
                self.assertFalse(hasattr(after, "options_button"))
        finally:
            self.app.setFont(original_font)
