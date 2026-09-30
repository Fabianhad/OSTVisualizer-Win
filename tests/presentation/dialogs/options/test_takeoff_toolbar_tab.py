import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.services.config_service import ConfigService
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.infrastructure.persistence.repositories.json_config_repository import (
    JsonConfigRepository,
)
from ost_visualizer.presentation.config import RELAXED_SPACING
from ost_visualizer.presentation.dialogs.options.dialog import OptionsDialog
from ost_visualizer.presentation.utils.plan_tool_registry import (
    PAGE_SELECTOR_ITEM,
    PAGE_SETTINGS_ITEM,
    PLAN_ANNOTATION_TOOL_SPECS,
    TAKEOFF_TOOLBAR_ITEMS,
    ZOOM_SELECTOR_ITEM,
)
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

    def dialog(self):
        dialog = OptionsDialog(
            self.model.snapshot(),
            apply_callback=self.service.update_app_options,
            reset_callback=lambda: (
                self.service.update_app_options(Config()),
                self.model.snapshot(),
            )[1],
        )
        self.addCleanup(lambda: delete(dialog) if isValid(dialog) else None)
        return dialog

    def test_takeoff_toolbar_tab_uses_options_tab_layout_design(self):
        dialog = self.dialog()
        tab = dialog._takeoff_toolbar_tab
        self.assertIsInstance(tab.layout(), QtWidgets.QVBoxLayout)
        self.assertEqual(tab.findChildren(QtWidgets.QScrollArea), [])
        groups = {
            group.title(): group for group in tab.findChildren(QtWidgets.QGroupBox)
        }
        self.assertEqual(
            set(groups),
            {
                "Annotation tools",
                "Page navigation",
                "Cursor tools",
                "View controls",
                "Page Settings",
            },
        )
        annotation_layout = groups["Annotation tools"].layout()
        self.assertIsInstance(annotation_layout, QtWidgets.QHBoxLayout)
        self.assertEqual(annotation_layout.count(), 2)
        lower_layout = tab.layout().itemAt(1).layout()
        self.assertIsInstance(lower_layout, QtWidgets.QHBoxLayout)
        self.assertEqual(lower_layout.count(), 2)
        lower_columns = tuple(
            lower_layout.itemAt(index).layout() for index in range(lower_layout.count())
        )
        self.assertTrue(
            all(isinstance(column, QtWidgets.QVBoxLayout) for column in lower_columns)
        )
        self.assertEqual(tab.layout().spacing(), RELAXED_SPACING)
        self.assertEqual(lower_layout.spacing(), RELAXED_SPACING)
        self.assertTrue(
            all(column.spacing() == RELAXED_SPACING for column in lower_columns)
        )
        self.assertEqual(len(tab.checks), len(TAKEOFF_TOOLBAR_ITEMS))
