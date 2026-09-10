import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from shiboken6 import delete, isValid
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)
from ost_visualizer.application.services.config_service import ConfigService
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.infrastructure.persistence.repositories.json_config_repository import (
    JsonConfigRepository,
)
from ost_visualizer.presentation.components.toolbar_overflow import add_overflow_widget
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
)
from ost_visualizer.presentation.coordinators.toolbar_state_coordinator import (
    ToolbarStateCoordinator,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.dialogs.options.dialog import OptionsDialog
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.app_config_presentation_manager import (
    AppConfigPresentationManager,
)
from ost_visualizer.presentation.managers.shortcut_manager import ShortcutManager
from ost_visualizer.presentation.utils.plan_tool_registry import (
    TAKEOFF_TOOLBAR_ITEMS,
    PLAN_ANNOTATION_TOOL_SPECS,
    PAGE_SELECTOR_ITEM,
    ZOOM_SELECTOR_ITEM,
    PAGE_SETTINGS_ITEM,
)
from tests import test_cross_surface_presentation as cross_surface
from tests import test_component_builder as component_tests
from tests import test_toolbar_state_coordinator as state_tests
from tests import test_remote_plan_update_pipeline as remote_tests


def register_test_fonts():
    font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
        QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))


class TakeoffToolbarVisibilityTests(unittest.TestCase):
    _main_components = cross_surface.SceneControlPresentationTests._main_components

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        register_test_fonts()

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

    def test_navigation_replacement_clear_and_view_refresh_retain_visibility(self):
        hidden = ("line_annotation_tool", PAGE_SETTINGS_ITEM, ZOOM_SELECTOR_ITEM)
        self.controller.apply_hidden_items(hidden)
        for transition in ("page", "bid", "clear", "reload"):
            with self.subTest(transition=transition):
                if transition == "page":
                    self.main_data.page = replace(self.main_data.page, uid="page-2")
                if transition == "bid":
                    self.main_data.bid = replace(self.main_data.bid)
                if transition == "clear":
                    self.main_sync.clear_plan_view()
                else:
                    self.main_data.bid.pages_without_folder = [self.main_data.page]
                    self.main_state.active_page_uid = self.main_data.page.uid
                    self.main_sync.update_plan_view(self.main_data.page.uid)
                self.bundle.view_stack.setCurrentIndex(1)
                self.bundle.view_stack.setCurrentIndex(0)
                self.app.processEvents()
                self.assertTrue(all(not self.item(key).isVisible() for key in hidden))

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

    def test_access_and_tool_refresh_keep_visibility_independent(self):
        access = state_tests._SelectiveAccess(
            {Feature.PLACE_ANNOTATIONS, Feature.SELECT_PLAN_ITEMS}
        )
        coordinator = ToolbarStateCoordinator(
            state_tests._UiState(
                active_page_uid=self.bundle.plan_view.current_page_uid
            ),
            access,
            state_tests._ProjectData(),
        )
        self.addCleanup(coordinator.cleanup)
        coordinator.set_plan_view(self.bundle.plan_view)
        coordinator.set_tab_widget(
            state_tests._IndexWidget(state_tests.TAB_INDEX_TAKEOFF)
        )
        coordinator.set_view_stack(state_tests._IndexWidget(1))
        line = self.bundle.plan_tool_actions["line_annotation_tool"]
        coordinator.set_annotation_tool_actions([line])
        coordinator.set_select_action(self.bundle.plan_tool_actions["select_tool"])
        self.controller.apply_hidden_items(("line_annotation_tool",))
        coordinator.refresh()
        self.assertTrue(line.isEnabled())
        access.allowed.clear()
        coordinator.refresh()
        self.assertFalse(line.isEnabled())
        self.assertFalse(self.item("line_annotation_tool").isVisible())
        self.controller.apply_hidden_items(())
        self.assertFalse(line.isEnabled())
        access.allowed.update({Feature.PLACE_ANNOTATIONS, Feature.SELECT_PLAN_ITEMS})
        coordinator.refresh()
        self.assertTrue(line.isEnabled())

    def test_deferred_remote_projection_retains_hidden_widgets(self):
        bridge = remote_tests._QueuedBridge()
        pool = remote_tests._ManualThreadPool()
        viewer = ViewerSyncCoordinator(
            self.main_state,
            SimpleNamespace(is_allowed=lambda _feature: True),
            cross_surface.FakeColorService(),
            self.main_data,
            bridge,
            pool,
        )
        viewer.plan_view = self.bundle.plan_view
        self.addCleanup(viewer.cleanup)
        ref = self.main_state.get_selected_bid_ref()
        completed = []
        barrier = RemoteProjectionBarrier(
            database_id=ref.file_path,
            runtime_generation=1,
            is_runtime_current=lambda _database, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertTrue(
            viewer.request_remote_plan_update(
                database_id=ref.file_path,
                bid_uid=ref.bid_uid,
                runtime_generation=1,
                resource_uids_by_family={"takeoffs": ()},
                barrier=barrier,
                completion=completed.append,
            )
        )
        hidden = (PAGE_SELECTOR_ITEM, ZOOM_SELECTOR_ITEM, "line_annotation_tool")
        self.controller.apply_hidden_items(hidden)
        pool.run_next()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertEqual(completed, [True])
        self.assertTrue(all(not self.item(key).isVisible() for key in hidden))

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

    def test_wrapped_command_buttons_preserve_native_toolbar_presentation(self):
        reference = QtWidgets.QToolBar()
        self.addCleanup(lambda: delete(reference))
        native_action = reference.addAction("Select")
        native_button = reference.widgetForAction(native_action)
        for key in (
            "select_tool",
            "place_tool",
            "pan_tool",
            "zoom_tool",
            "reset_view",
            "zoom_in",
            "zoom_out",
        ):
            button = self.toolbar.widgetForAction(self.item(key))
            with self.subTest(key=key):
                self.assertEqual(button.autoRaise(), native_button.autoRaise())
                self.assertEqual(button.focusPolicy(), native_button.focusPolicy())
                self.assertEqual(
                    button.toolButtonStyle(), native_button.toolButtonStyle()
                )

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
            self.assertEqual(refresh_required, [False])
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


class TakeoffToolbarPreferencesTests(unittest.TestCase):
    _overflow_toolbar = component_tests.ComponentBuilderTests._overflow_toolbar
    _use_extension_menu = component_tests.ComponentBuilderTests._use_extension_menu

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        register_test_fonts()

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

    def test_normalization_missing_and_unknown_keys_round_trip(self):
        self.assertEqual(Config.from_dict({}).hidden_takeoff_toolbar_items, ())
        self.service.update_app_options(
            {
                "hidden_takeoff_toolbar_items": [
                    "future_tool",
                    "",
                    " line_annotation_tool ",
                    "future_tool",
                ]
            }
        )
        expected = ("future_tool", "line_annotation_tool")
        self.assertEqual(self.model.snapshot().hidden_takeoff_toolbar_items, expected)
        self.assertEqual(
            ConfigAggregate(JsonConfigRepository(self.path))
            .snapshot()
            .hidden_takeoff_toolbar_items,
            expected,
        )
        self.assertEqual(
            json.loads(self.path.read_text())["hidden_takeoff_toolbar_items"],
            list(expected),
        )
        dialog = self.dialog()
        self.assertTrue(
            dialog._takeoff_toolbar_tab.checks["arrow_annotation_tool"].isChecked()
        )
        dialog._takeoff_toolbar_tab.checks["line_annotation_tool"].setChecked(True)
        dialog.accept()
        self.assertEqual(
            self.model.snapshot().hidden_takeoff_toolbar_items, ("future_tool",)
        )

    def test_apply_ok_cancel_and_restore_defaults_use_one_config_write(self):
        changes = []
        self.bus.subscribe(
            AppEvents.APP_CONFIG_UPDATED, lambda **event: changes.append(event)
        )
        dialog = self.dialog()
        tab = dialog._takeoff_toolbar_tab
        tab.checks["line_annotation_tool"].setChecked(False)
        self.assertEqual(self.model.snapshot().hidden_takeoff_toolbar_items, ())
        dialog._apply_button.click()
        self.assertEqual(
            self.model.snapshot().hidden_takeoff_toolbar_items,
            ("line_annotation_tool",),
        )
        tab.checks["arrow_annotation_tool"].setChecked(False)
        dialog.reject()
        self.assertEqual(len(changes), 1)
        restored = self.dialog()
        self.assertFalse(
            restored._takeoff_toolbar_tab.checks["line_annotation_tool"].isChecked()
        )
        restored._takeoff_toolbar_tab.restore_button.click()
        self.assertEqual(
            self.model.snapshot().hidden_takeoff_toolbar_items,
            ("line_annotation_tool",),
        )
        restored.accept()
        self.assertEqual(self.model.snapshot().hidden_takeoff_toolbar_items, ())
        self.assertEqual(len(changes), 2)

    def test_scoped_restore_clears_unknown_entries_without_resetting_other_preferences(
        self,
    ):
        self.service.update_app_options(
            {
                "show_toolbar_text": False,
                "hidden_takeoff_toolbar_items": ["obsolete", "line_annotation_tool"],
            }
        )
        dialog = self.dialog()
        dialog._takeoff_toolbar_tab.restore_button.click()
        dialog.accept()
        self.assertFalse(self.model.snapshot().show_toolbar_text)
        self.assertEqual(self.model.snapshot().hidden_takeoff_toolbar_items, ())

    def test_reset_all_uses_existing_reset_lifecycle(self):
        self.service.update_app_options(
            {"hidden_takeoff_toolbar_items": ["line_annotation_tool"]}
        )
        dialog = self.dialog()
        with patch(
            "ost_visualizer.presentation.dialogs.options.dialog.confirm",
            return_value=True,
        ):
            dialog._reset_all_button.click()
        self.assertEqual(self.model.snapshot().hidden_takeoff_toolbar_items, ())
        self.assertTrue(
            all(
                check.isChecked()
                for check in dialog._takeoff_toolbar_tab.checks.values()
            )
        )

    def test_invalid_preference_uses_existing_config_validation_contract(self):
        for value in (None, "line_annotation_tool", [False]):
            with self.subTest(value=value), self.assertRaises(TypeError):
                Config.from_dict({"hidden_takeoff_toolbar_items": value})

    def test_failed_apply_preserves_saved_state_and_retry_persists_and_publishes(self):
        original = self.model.snapshot()
        saved = self.path.read_bytes()
        events = []
        self.bus.subscribe(
            AppEvents.APP_CONFIG_UPDATED, lambda **event: events.append(event)
        )
        dialog = self.dialog()
        dialog._takeoff_toolbar_tab.checks["line_annotation_tool"].setChecked(False)
        with patch.object(
            self.repository, "save", side_effect=OSError("disk unavailable")
        ), patch(
            "ost_visualizer.presentation.dialogs.options.dialog.show_warning"
        ) as warning:
            dialog._apply_button.click()
        warning.assert_called_once()
        self.assertTrue(dialog._apply_button.isEnabled())
        self.assertEqual(events, [])
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertEqual(self.model.snapshot(), original)
        dialog._apply_button.click()
        self.assertFalse(dialog._apply_button.isEnabled())
        self.assertEqual(len(events), 1)
        self.assertEqual(
            ConfigAggregate(JsonConfigRepository(self.path))
            .snapshot()
            .hidden_takeoff_toolbar_items,
            ("line_annotation_tool",),
        )
        dialog.accept()
        self.assertEqual(len(events), 1)

    def test_failed_reset_all_preserves_hidden_settings_until_retry(self):
        self.service.update_app_options(
            {"hidden_takeoff_toolbar_items": ["line_annotation_tool"]}
        )
        original = self.model.snapshot()
        saved = self.path.read_bytes()
        dialog = self.dialog()
        with patch(
            "ost_visualizer.presentation.dialogs.options.dialog.confirm",
            return_value=True,
        ):
            with patch.object(
                self.repository, "save", side_effect=OSError("disk unavailable")
            ), patch(
                "ost_visualizer.presentation.dialogs.options.dialog.show_warning"
            ) as warning:
                dialog._reset_all_button.click()
            warning.assert_called_once()
            self.assertEqual(self.model.snapshot(), original)
            self.assertEqual(self.path.read_bytes(), saved)
            self.assertFalse(
                dialog._takeoff_toolbar_tab.checks["line_annotation_tool"].isChecked()
            )
            dialog._reset_all_button.click()
        self.assertEqual(
            ConfigAggregate(JsonConfigRepository(self.path))
            .snapshot()
            .hidden_takeoff_toolbar_items,
            (),
        )

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
        wrapper.set_toolbar_visible(False)
        QtTest.QTest.keyClick(window, QtCore.Qt.Key.Key_PageDown)
        self.assertEqual(calls, [True])
        self.assertTrue(menu.actions()[0].isVisible())
        command.setEnabled(False)
        QtTest.QTest.keyClick(window, QtCore.Qt.Key.Key_PageDown)
        self.assertEqual(calls, [True])
        self.assertFalse(wrapper.isVisible())
        window.close()

    def test_overflow_hide_show_cycles_reuse_command_without_duplicate_signals(self):
        host, toolbar = self._overflow_toolbar()
        self.addCleanup(lambda: delete(host) if isValid(host) else None)
        command = QtGui.QAction("Select", host)
        calls = []
        command.triggered.connect(lambda: calls.append(True))

        def button(parent):
            result = QtWidgets.QToolButton(parent)
            result.setObjectName("visibilityOverflowButton")
            result.setDefaultAction(command)
            return result

        original = button(toolbar)
        wrapper = add_overflow_widget(
            toolbar,
            original,
            overflow_factory=button,
            text="Select",
            visibility_action=command,
        )
        original_actions = toolbar.actions()
        host.resize(180, 100)
        self.app.processEvents()

        def click(menu):
            proxy = menu.findChild(QtWidgets.QToolButton, "visibilityOverflowButton")
            self.assertIsNotNone(proxy)
            self.assertIs(proxy.defaultAction(), command)
            proxy.click()

        for cycle in range(5):
            wrapper.set_toolbar_visible(False)
            command.setEnabled(False)
            command.setEnabled(True)
            self.app.processEvents()
            self.assertFalse(wrapper.isVisible())
            wrapper.set_toolbar_visible(True)
            self.app.processEvents()
            self._use_extension_menu(toolbar, click)
            self.assertEqual(len(calls), cycle + 1)
            self.assertEqual(toolbar.actions(), original_actions)
            self.assertIs(toolbar.widgetForAction(wrapper), original)
            self.assertTrue(isValid(original))
        host.close()

    def test_disabled_command_stays_disabled_when_visibility_changes_in_open_overflow(
        self,
    ):
        host, toolbar = self._overflow_toolbar()
        self.addCleanup(lambda: delete(host) if isValid(host) else None)
        command = QtGui.QAction("Select", host)
        command.setEnabled(False)

        def button(parent):
            result = QtWidgets.QToolButton(parent)
            result.setDefaultAction(command)
            return result

        original = button(toolbar)
        wrapper = add_overflow_widget(
            toolbar,
            original,
            overflow_factory=button,
            text="Select",
            visibility_action=command,
        )
        host.resize(180, 100)
        self.app.processEvents()

        def inspect(menu):
            for _ in range(3):
                wrapper.set_toolbar_visible(False)
                wrapper.set_toolbar_visible(True)
                proxies = [
                    w for w in wrapper.createdWidgets() if w.parentWidget() is menu
                ]
                self.assertEqual(len(proxies), 1)
                self.assertFalse(proxies[0].isEnabled())
                self.assertFalse(original.isEnabled())
                self.assertIs(proxies[0].defaultAction(), command)

        self._use_extension_menu(toolbar, inspect)
        host.close()
