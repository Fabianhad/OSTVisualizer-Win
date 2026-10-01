import os
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.managers.app_config_presentation_manager import (
    AppConfigPresentationManager,
)
from PySide6 import QtCore, QtGui, QtWidgets
from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)


class AppConfigPresentationManagerPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_toolbar_text_preference_updates_cover_sheet_button_only(self):
        manager = AppConfigPresentationManager()
        window = SimpleNamespace()
        config = SimpleNamespace(show_toolbar_text=True)
        toolbars = [QtWidgets.QToolBar(), QtWidgets.QToolBar()]
        cover_sheet_button = QtWidgets.QToolButton()
        untouched_button = QtWidgets.QToolButton()
        # QToolBar defaults to icon-only, so start from a different style to
        # prove the manager actively resets the workspace toolbars.
        for toolbar in toolbars:
            toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        untouched_button.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon
        )
        window.get_workspace_toolbars = lambda: toolbars
        window.get_toolbar_text_buttons = lambda: [cover_sheet_button]
        manager.apply_toolbar_text(window, config)
        self.assertEqual(
            untouched_button.toolButtonStyle(),
            QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon,
        )
        self.assertTrue(
            all(
                toolbar.toolButtonStyle()
                == QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
                for toolbar in toolbars
            )
        )
        self.assertEqual(
            cover_sheet_button.toolButtonStyle(),
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon,
        )
        config.show_toolbar_text = False
        manager.apply_toolbar_text(window, config)
        self.assertTrue(
            all(
                toolbar.toolButtonStyle()
                == QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
                for toolbar in toolbars
            )
        )
        self.assertEqual(
            cover_sheet_button.toolButtonStyle(),
            QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly,
        )
