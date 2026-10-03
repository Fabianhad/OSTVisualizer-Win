import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.services.config_service import ConfigService
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.infrastructure.persistence.repositories.json_config_repository import (
    JsonConfigRepository,
)
from ost_visualizer.presentation.components.toolbar_overflow import add_overflow_widget
from ost_visualizer.presentation.managers.shortcut_manager import ShortcutManager
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from shiboken6 import delete, isValid
import tests.presentation.components.test_toolbar_overflow as component_tests
from tests.presentation.components.toolbar_visibility_support import (
    register_test_fonts as _toolbar_visibility_support_register_test_fonts,
)


class TakeoffToolbarPreferencesTests(unittest.TestCase):
    _overflow_toolbar = component_tests.ToolbarOverflowTests._overflow_toolbar
    _use_extension_menu = component_tests.ToolbarOverflowTests._use_extension_menu

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        _toolbar_visibility_support_register_test_fonts()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "config.json"
        self.repository = JsonConfigRepository(self.path)
        self.model = ConfigAggregate(self.repository)
        self.bus = EventBus()
        self.service = ConfigService(self.model, self.bus)

    def test_hidden_toolbar_command_keeps_real_shortcut_and_menu(self):
        window = QtWidgets.QMainWindow()
        self.addCleanup(lambda: delete(window) if isValid(window) else None)
        menu = window.menuBar().addMenu("View")
        toolbar = QtWidgets.QToolBar(window)
        window.addToolBar(toolbar)
        command = QtGui.QAction("Next Page", window)
        ShortcutManager.apply_to_action(command, "next_page")
        menu.addAction(command)
        calls = []
        command.triggered.connect(lambda: calls.append(True))

        def button(parent):
            widget = QtWidgets.QToolButton(parent)
            widget.setDefaultAction(command)
            return widget

        wrapper = add_overflow_widget(
            toolbar,
            button(toolbar),
            overflow_factory=button,
            text=command.text(),
            visibility_action=command,
        )
        window.show()
        window.activateWindow()
        self.app.processEvents()
        # The command's own shortcut, not a literal key, drives the keystrokes.
        combination = command.shortcut()[0]
        self.assertNotEqual(combination.key(), QtCore.Qt.Key.Key_unknown)

        def press_shortcut():
            QtTest.QTest.keyClick(
                window, combination.key(), combination.keyboardModifiers()
            )

        # Positive control: shown in the toolbar and triggerable by shortcut.
        self.assertTrue(wrapper.isVisible())
        press_shortcut()
        self.assertEqual(calls, [True])
        wrapper.set_toolbar_visible(False)
        self.assertFalse(wrapper.isVisible())
        self.assertTrue(command.isVisible())
        press_shortcut()
        self.assertEqual(calls, [True, True])
        self.assertTrue(menu.actions()[0].isVisible())
        command.setEnabled(False)
        press_shortcut()
        self.assertEqual(calls, [True, True])
        self.assertFalse(wrapper.isVisible())
        window.close()
