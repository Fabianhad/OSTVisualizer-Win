import json
import os
import tempfile
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.config_service import ConfigService
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.infrastructure.persistence.repositories.json_config_repository import (
    JsonConfigRepository,
)
from ost_visualizer.presentation.dialogs.options.dialog import OptionsDialog
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.app_config_presentation_manager import (
    AppConfigPresentationManager,
)
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from shiboken6 import delete, isValid
import tests.integration.surfaces.test_presentation as cross_surface
from tests.presentation.components.toolbar_visibility_support import (
    register_test_fonts as _toolbar_visibility_support_register_test_fonts,
)


class TakeoffToolbarVisibilityTests(unittest.TestCase):
    _main_components = cross_surface.SceneControlPresentationTests._main_components

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        _toolbar_visibility_support_register_test_fonts()

    def setUp(self):
        # Exceptions raised inside Qt slots reach sys.excepthook and would otherwise
        # be swallowed; fail the test if any occur.
        errors = []
        hook = patch("sys.excepthook", side_effect=lambda *error: errors.append(error))
        hook.start()
        self.addCleanup(hook.stop)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        self.bundle, self.zoom = self._main_components()
        self.controller = self.bundle.takeoff_toolbar_visibility
        self.toolbar = self.controller.parent()
        self.controller.apply_hidden_items(())

    def item(self, key):
        result = self.toolbar.findChild(QtWidgets.QWidgetAction, key)
        self.assertIsNotNone(result)
        return result

    def test_options_apply_projects_saved_state_and_recreated_toolbar_restores_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            model = ConfigAggregate(JsonConfigRepository(path))
            bus = EventBus()
            service = ConfigService(model, bus)
            manager = AppConfigPresentationManager()
            detached = SimpleNamespace(apply_config_preferences=Mock())
            window = SimpleNamespace(
                _takeoff_toolbar_visibility=self.controller,
                _refresh_annotation_style_controls=Mock(),
                get_workspace_toolbars=lambda: [self.bundle.main_toolbar],
                get_toolbar_text_buttons=lambda: [],
                takeoff_sidebar=None,
                plan_view=self.bundle.plan_view,
                get_annotation_window=lambda: detached,
                get_view_window=lambda: None,
            )
            window.apply_takeoff_toolbar_visibility = MethodType(
                MainWindow.apply_takeoff_toolbar_visibility, window
            )
            refresh_required = []

            def project(setting, value):
                self.assertEqual(setting, "options")
                refresh_required.append(
                    manager.apply_updated_options(window, model, value)
                )

            bus.subscribe(AppEvents.APP_CONFIG_UPDATED, project)
            manager.apply(window, model)
            dialog = OptionsDialog(
                model.snapshot(), apply_callback=service.update_app_options
            )
            self.addCleanup(lambda: delete(dialog) if isValid(dialog) else None)
            check = dialog.findChild(
                QtWidgets.QCheckBox, "takeoff_toolbar_line_annotation_tool"
            )
            check.setChecked(False)
            self.assertTrue(self.item("line_annotation_tool").isVisible())
            dialog._apply_button.click()
            self.assertFalse(self.item("line_annotation_tool").isVisible())
            # Only the unchecked tool is hidden; its neighbours stay visible.
            self.assertTrue(self.item("arrow_annotation_tool").isVisible())
            self.assertEqual(refresh_required, [False])
            # The saved file (under the temporary directory) holds the literal
            # hidden list that the recreated toolbar is later restored from.
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))[
                    "hidden_takeoff_toolbar_items"
                ],
                ["line_annotation_tool"],
            )
            dialog.reject()
            self.assertNotIn(
                "hidden_takeoff_toolbar_items",
                detached.apply_config_preferences.call_args.kwargs,
            )
            recreated, _zoom = self._main_components()
            window._takeoff_toolbar_visibility = recreated.takeoff_toolbar_visibility
            window.plan_view = recreated.plan_view
            reloaded = ConfigAggregate(JsonConfigRepository(path))
            manager.apply(window, reloaded)
            recreated_toolbar = recreated.takeoff_toolbar_visibility.parent()
            self.assertFalse(
                recreated_toolbar.findChild(
                    QtWidgets.QWidgetAction, "line_annotation_tool"
                ).isVisible()
            )
            self.assertTrue(
                recreated_toolbar.findChild(
                    QtWidgets.QWidgetAction, "arrow_annotation_tool"
                ).isVisible()
            )
