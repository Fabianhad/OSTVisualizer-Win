import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.plan_tool_registry import (
    PAGE_SELECTOR_ITEM,
    PAGE_SETTINGS_ITEM,
    PLAN_ANNOTATION_TOOL_SPECS,
    TAKEOFF_TOOLBAR_ITEMS,
    ZOOM_SELECTOR_ITEM,
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
        self.bundle, self.zoom = self._main_components()
        self.controller = self.bundle.takeoff_toolbar_visibility
        self.toolbar = self.controller.parent()
        self.controller.apply_hidden_items(())

    def item(self, key):
        result = self.toolbar.findChild(QtWidgets.QWidgetAction, key)
        self.assertIsNotNone(result)
        return result

    def test_default_layout_and_each_registered_item(self):
        self.controller.apply_hidden_items(("removed_or_future_tool",))
        keys = [a.objectName() for a in self.toolbar.actions() if a.objectName()]
        self.assertEqual(keys, [s.key for s in TAKEOFF_TOOLBAR_ITEMS])
        self.assertEqual(len(keys), 24)
        self.assertTrue(all(self.item(key).isVisible() for key in keys))
        self.assertFalse(any(a.isSeparator() for a in self.toolbar.actions()))
        self.assertEqual(len(self.toolbar.actions()), 25)  # Includes existing spacer.

    def test_buttons_and_embedded_widgets_hide_without_destruction(self):
        for key in (
            "line_annotation_tool",
            "arrow_annotation_tool",
            "dimension_tool",
            PAGE_SELECTOR_ITEM,
            ZOOM_SELECTOR_ITEM,
            PAGE_SETTINGS_ITEM,
        ):
            with self.subTest(key=key):
                action = self.item(key)
                widget = self.toolbar.widgetForAction(action)
                self.assertIsNotNone(widget)
                self.controller.apply_hidden_items((key,))
                self.assertFalse(action.isVisible())
                self.assertTrue(isValid(widget))
                self.controller.apply_hidden_items(())
                self.assertTrue(action.isVisible())
                self.assertIs(self.toolbar.widgetForAction(action), widget)

    def test_action_refresh_keeps_mask_and_restores_current_command_state(self):
        command = self.bundle.plan_tool_actions["line_annotation_tool"]
        triggered = []
        command.triggered.connect(triggered.append)
        self.controller.apply_hidden_items(("line_annotation_tool",))
        for enabled in (False, True, False):
            command.setEnabled(enabled)
            command.setChecked(True)
            self.assertFalse(self.item("line_annotation_tool").isVisible())
            self.assertTrue(command.isVisible())
        self.controller.apply_hidden_items(())
        self.assertFalse(command.isEnabled())
        self.assertTrue(command.isChecked())
        self.assertEqual(triggered, [])

    def test_hide_show_preserves_widget_enablement_and_updates_while_hidden(self):
        for key in ("select_tool", "zoom_in", PAGE_SELECTOR_ITEM, ZOOM_SELECTOR_ITEM):
            with self.subTest(key=key):
                action = self.item(key)
                widget = self.toolbar.widgetForAction(action)
                command = (
                    widget.defaultAction()
                    if isinstance(widget, QtWidgets.QToolButton)
                    else None
                )
                owner = command if command is not None else widget
                owner.setEnabled(False)
                self.controller.apply_hidden_items((key,))
                self.controller.apply_hidden_items(())
                self.assertFalse(widget.isEnabled())
                self.controller.apply_hidden_items((key,))
                owner.setEnabled(True)
                self.controller.apply_hidden_items(())
                self.assertTrue(widget.isEnabled())
                self.controller.apply_hidden_items((key,))
                owner.setEnabled(False)
                self.controller.apply_hidden_items(())
                self.assertFalse(widget.isEnabled())

    def test_hide_show_during_toolbar_disable_does_not_disable_children_permanently(
        self,
    ):
        combo = self.toolbar.widgetForAction(self.item(ZOOM_SELECTOR_ITEM))
        combo.setEnabled(True)
        self.toolbar.setEnabled(False)
        self.controller.apply_hidden_items((ZOOM_SELECTOR_ITEM,))
        self.controller.apply_hidden_items(())
        self.toolbar.setEnabled(True)
        self.assertTrue(combo.isEnabled())

    def test_spacing_empty_strip_and_restoration(self):
        spacer = next(a for a in self.toolbar.actions() if not a.objectName())
        navigation = tuple(
            s.key for s in TAKEOFF_TOOLBAR_ITEMS if s.group == "Page navigation"
        )
        rest = tuple(
            s.key for s in TAKEOFF_TOOLBAR_ITEMS if s.group != "Page navigation"
        )
        for hidden in (navigation, rest, navigation + rest):
            self.controller.apply_hidden_items(hidden)
            self.assertFalse(spacer.isVisible())
        self.assertTrue(self.toolbar.isHidden())
        self.controller.apply_hidden_items(())
        self.assertFalse(self.toolbar.isHidden())
        self.assertTrue(spacer.isVisible())

    def test_repeated_annotation_group_cycles_preserve_ownership_and_other_toolbars(
        self,
    ):
        originals = [
            (a, self.toolbar.widgetForAction(a)) for a in self.toolbar.actions()
        ]
        other_actions = [
            (a, a.isVisible())
            for toolbar in (
                self.bundle.main_toolbar,
                self.bundle.view_toolbar,
                self.bundle.plan_tools_toolbar,
                self.bundle.overlay_tools_toolbar,
            )
            for a in toolbar.actions()
        ]
        hidden = tuple(spec.action_key for spec in PLAN_ANNOTATION_TOOL_SPECS)
        default_hint = self.toolbar.sizeHint()
        for _ in range(20):
            self.controller.apply_hidden_items(hidden)
            self.controller.apply_hidden_items(())
        self.assertEqual(self.toolbar.actions(), [a for a, _w in originals])
        for action, widget in originals:
            self.assertIs(self.toolbar.widgetForAction(action), widget)
            self.assertTrue(isValid(widget))
        self.assertEqual(self.toolbar.sizeHint(), default_hint)
        self.assertTrue(all(a.isVisible() == visible for a, visible in other_actions))

    def test_source_visibility_still_limits_user_visible_item(self):
        command = self.bundle.plan_tool_actions["dimension_tool"]
        command.setVisible(False)
        self.controller.apply_hidden_items(())
        self.assertFalse(self.item("dimension_tool").isVisible())
        command.setVisible(True)
        self.assertTrue(self.item("dimension_tool").isVisible())
        self.controller.apply_hidden_items(("dimension_tool",))
        command.setVisible(False)
        command.setVisible(True)
        self.assertFalse(self.item("dimension_tool").isVisible())
