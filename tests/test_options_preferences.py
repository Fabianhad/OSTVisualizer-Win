import os
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets

from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.application.dtos.snap_preferences_dto import \
    SnapPreferencesDto
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.config_service import ConfigService
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.page import Page, build_pages_from_bid_data
from ost_visualizer.domain.entities.page_info import BidPageInfo
from ost_visualizer.presentation.components.menu_builder import MenuBuilder
from ost_visualizer.presentation.components.page_combo import (
    PageComboBox, SinglePageComboBox)
from ost_visualizer.presentation.components.plan_view.components.graphics_items import \
    TileKey
from ost_visualizer.presentation.components.plan_view.components.zoom_handler import \
    ZoomHandlerMixin
from ost_visualizer.presentation.components.plan_view.view import \
    TakeoffPlanView
from ost_visualizer.presentation.config import (OPTIONS_TAB_MCP_SETUP,
                                                OPTIONS_TAB_OPTIONS,
                                                OPTIONS_WINDOW_HEIGHT,
                                                OPTIONS_WINDOW_WIDTH)
from ost_visualizer.presentation.controllers.menu_controller import \
    MenuController
from ost_visualizer.presentation.coordinators.ui_event_coordinator import \
    UIEventCoordinator
from ost_visualizer.presentation.dialogs.options import \
    components as options_components
from ost_visualizer.presentation.dialogs.options.dialog import OptionsDialog
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.utils.color_swatch import rounded_color_swatch
from ost_visualizer.presentation.utils.mcp_setup_config import (
    build_claude_desktop_config, build_codex_mcp_add_command)
from ost_visualizer.presentation.visualization.pdf.services.composite_renderer import \
    CompositeRenderer

REPO_ROOT = Path(__file__).resolve().parents[1]


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class FakeConfigRepository:
    config_path = "memory"

    def __init__(self, config=None):
        self.saved = []
        self._config = config or Config()

    def load(self):
        return self._config

    def save(self, config):
        self._config = config
        self.saved.append(config.to_dict())


class FakeEventBus:
    def __init__(self):
        self.events = []

    def publish(self, event_type, **kwargs):
        self.events.append((event_type, kwargs))


def _app_config_event(value):
    return (AppEvents.APP_CONFIG_UPDATED, {"setting": "options", "value": value})


SNAP_PREF_UPDATE = SnapPreferencesDto(
    snap_to_grid_enabled=False,
    snap_to_grid_threshold_px=0,
    snap_to_pdf_lines_enabled=False,
    snap_to_pdf_lines_threshold_px=12,
    snap_to_takeoffs_enabled=False,
    snap_to_takeoffs_threshold_px=16,
    snap_to_right_angle_enabled=True,
    snap_to_right_angle_threshold_px=20,
).to_kwargs()
SNAP_PREF_CHANGED_KEYS = list(SNAP_PREF_UPDATE)


def _assert_snap_pref_update_applied(test_case, aggregate):
    test_case.assertEqual(
        aggregate.snap_to_grid_enabled,
        SNAP_PREF_UPDATE["snap_to_grid_enabled"],
    )
    test_case.assertEqual(
        aggregate.snap_to_grid_threshold_px,
        SNAP_PREF_UPDATE["snap_to_grid_threshold_px"],
    )
    test_case.assertEqual(
        aggregate.snap_to_pdf_lines_enabled,
        SNAP_PREF_UPDATE["snap_to_pdf_lines_enabled"],
    )
    test_case.assertEqual(
        aggregate.snap_to_pdf_lines_threshold_px,
        SNAP_PREF_UPDATE["snap_to_pdf_lines_threshold_px"],
    )
    test_case.assertEqual(
        aggregate.snap_to_takeoffs_enabled,
        SNAP_PREF_UPDATE["snap_to_takeoffs_enabled"],
    )
    test_case.assertEqual(
        aggregate.snap_to_takeoffs_threshold_px,
        SNAP_PREF_UPDATE["snap_to_takeoffs_threshold_px"],
    )
    test_case.assertEqual(
        aggregate.snap_to_right_angle_enabled,
        SNAP_PREF_UPDATE["snap_to_right_angle_enabled"],
    )
    test_case.assertEqual(
        aggregate.snap_to_right_angle_threshold_px,
        SNAP_PREF_UPDATE["snap_to_right_angle_threshold_px"],
    )


def _visible_texts(dialog):
    texts = []
    for widget_type in (QtWidgets.QLabel, QtWidgets.QCheckBox, QtWidgets.QRadioButton):
        texts.extend(
            widget.text()
            for widget in dialog.findChildren(widget_type)
            if widget.text()
        )
    return texts


def _apply_button(dialog):
    buttons = dialog.findChild(QtWidgets.QDialogButtonBox)
    return buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Apply)


class FakeTrackingViewport:
    def __init__(self):
        self.tracking = []
        self.updates = 0

    def setMouseTracking(self, enabled):
        self.tracking.append(enabled)

    def update(self):
        self.updates += 1


def _plan_view_with_tracking_viewport(cursor_mode="select"):
    viewport = FakeTrackingViewport()
    view = TakeoffPlanView.__new__(TakeoffPlanView)
    view.viewport = lambda: viewport
    view._cursor_mode = cursor_mode
    view._use_full_window_crosshairs = False
    view._pdf_text_runs = []
    view._persistent_cursor_mode = cursor_mode
    view._right_pan_active = False
    view._pre_zoom_persistent_mode = None
    view._update_cursor = lambda: None
    return view, viewport


class OptionsPreferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        self.app.processEvents()

    def test_options_dialog_loads_persisted_preferences(self):
        dialog = OptionsDialog(
            Config(
                color_mode="Original",
                grayscale_enabled=False,
                roping_selection_method="inclusive",
                display_page_index_with_sheet_name=True,
                display_sheet_number_with_sheet_name=True,
                hotlink_target="view",
                show_toolbar_text=True,
                disable_high_resolution_images=True,
                enable_intelligent_paste=False,
                enable_advanced_mouse_controls=False,
                use_full_window_crosshairs=True,
                crosshair_color="#123456",
                crosshair_line_thickness=3,
                allow_add_page_from_takeoff_tab=True,
                mouse_unpressed_snap_angle=30,
                mouse_pressed_snap_angle=45,
                snap_to_grid_enabled=False,
                snap_to_grid_threshold_px=12,
                snap_to_pdf_lines_enabled=False,
                snap_to_pdf_lines_threshold_px=13,
                snap_to_takeoffs_enabled=False,
                snap_to_takeoffs_threshold_px=14,
                snap_to_right_angle_enabled=True,
                snap_to_right_angle_threshold_px=15,
                default_auto_zoom_level=150,
            )
        )
        self.assertTrue(dialog._color_original_radio.isChecked())
        self.assertFalse(dialog._grayscale_check.isChecked())
        self.assertTrue(dialog._roping_inclusive_radio.isChecked())
        self.assertTrue(dialog._page_index_check.isChecked())
        self.assertTrue(dialog._sheet_number_check.isChecked())
        self.assertTrue(dialog._hotlink_view_radio.isChecked())
        self.assertFalse(dialog._hotlink_main_radio.isChecked())
        self.assertTrue(dialog._hotlink_main_radio.isEnabled())
        self.assertTrue(dialog._toolbar_text_check.isChecked())
        self.assertTrue(dialog._disable_high_res_check.isChecked())
        self.assertFalse(dialog._intelligent_paste_check.isChecked())
        self.assertFalse(dialog._advanced_mouse_controls_check.isChecked())
        self.assertTrue(dialog._full_window_crosshairs_check.isChecked())
        self.assertEqual(dialog._crosshair_color_button.color(), "#123456")
        self.assertEqual(dialog._crosshair_line_thickness_spin.value(), 3)
        self.assertTrue(dialog._allow_add_page_from_takeoff_check.isChecked())
        self.assertEqual(dialog._mouse_unpressed_snap_angle_combo.currentData(), 30)
        self.assertEqual(dialog._mouse_pressed_snap_angle_combo.currentData(), 45)
        self.assertFalse(dialog._snap_to_grid_check.isChecked())
        self.assertEqual(dialog._snap_to_grid_threshold_spin.value(), 12)
        self.assertFalse(dialog._snap_to_pdf_lines_check.isChecked())
        self.assertEqual(dialog._snap_to_pdf_lines_threshold_spin.value(), 13)
        self.assertFalse(dialog._snap_to_takeoffs_check.isChecked())
        self.assertEqual(dialog._snap_to_takeoffs_threshold_spin.value(), 14)
        self.assertTrue(dialog._snap_to_right_angle_check.isChecked())
        self.assertEqual(dialog._snap_to_right_angle_threshold_spin.value(), 15)
        self.assertEqual(dialog._auto_zoom_spin.value(), 150)
        dialog.close()

    def test_options_crosshair_color_preview_is_square_and_not_stylesheet_colored(self):
        dialog = OptionsDialog(Config(crosshair_color="#123456"))
        button = dialog._crosshair_color_button
        self.assertEqual(button.minimumWidth(), button.minimumHeight())
        self.assertEqual(button.maximumWidth(), button.maximumHeight())
        self.assertEqual(button.styleSheet(), "")
        button.set_color("#abcdef")
        self.assertEqual(button.color(), "#abcdef")
        self.assertEqual(button.styleSheet(), "")
        dialog.close()

    def test_options_dialog_does_not_show_auto_dimension_lines_preference(self):
        dialog = OptionsDialog(Config())
        labels = {
            checkbox.text() for checkbox in dialog.findChildren(QtWidgets.QCheckBox)
        }
        self.assertNotIn("Enable auto dimension lines", labels)
        self.assertNotIn("Show right angle line indicator", labels)
        dialog.close()

    def test_color_preview_swatch_has_rounded_transparent_corners(self):
        pixmap = rounded_color_swatch(QtGui.QColor("#123456"), 24)
        image = pixmap.toImage()
        self.assertEqual(image.pixelColor(12, 12).name(), "#123456")
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)

    def test_options_crosshair_color_picker_accept_updates_pending_color_only(self):
        dialog = OptionsDialog(Config(crosshair_color="#123456"))
        button = dialog._crosshair_color_button
        created_dialogs = []

        class FakeColorDialog:
            def __init__(self, color, parent=None):
                self.initial_color = color.name()
                self.parent = parent
                self.window_title = ""
                self.stylesheet_calls = []
                created_dialogs.append(self)

            def isVisible(self):
                return False

            def setWindowFlag(self, *_args):
                pass

            def winId(self):
                raise RuntimeError("no native window in test")

            def setWindowTitle(self, title):
                self.window_title = title

            def setStyleSheet(self, stylesheet):
                self.stylesheet_calls.append(stylesheet)

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def currentColor(self):
                return QtGui.QColor("#abcdef")

        original_dialog = options_components.QtWidgets.QColorDialog
        options_components.QtWidgets.QColorDialog = FakeColorDialog
        try:
            button._choose_color()
        finally:
            options_components.QtWidgets.QColorDialog = original_dialog
        self.assertEqual(button.color(), "#abcdef")
        self.assertEqual(dialog.get_config().crosshair_color, "#123456")
        self.assertEqual(dialog._collect_widget_config().crosshair_color, "#abcdef")
        self.assertTrue(_apply_button(dialog).isEnabled())
        self.assertEqual(created_dialogs[0].initial_color, "#123456")
        self.assertIs(created_dialogs[0].parent, button)
        self.assertEqual(created_dialogs[0].parent.styleSheet(), "")
        self.assertEqual(created_dialogs[0].stylesheet_calls, [])
        dialog.close()

    def test_options_crosshair_color_picker_cancel_keeps_previous_color(self):
        dialog = OptionsDialog(Config(crosshair_color="#123456"))
        button = dialog._crosshair_color_button
        changed = []
        button.colorChanged.connect(lambda: changed.append(button.color()))

        class FakeColorDialog:
            def __init__(self, _color, parent=None):
                self.parent = parent

            def isVisible(self):
                return False

            def setWindowFlag(self, *_args):
                pass

            def winId(self):
                raise RuntimeError("no native window in test")

            def setWindowTitle(self, _title):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Rejected

            def currentColor(self):
                return QtGui.QColor("#abcdef")

        original_dialog = options_components.QtWidgets.QColorDialog
        options_components.QtWidgets.QColorDialog = FakeColorDialog
        try:
            button._choose_color()
        finally:
            options_components.QtWidgets.QColorDialog = original_dialog
        self.assertEqual(button.color(), "#123456")
        self.assertEqual(changed, [])
        self.assertFalse(_apply_button(dialog).isEnabled())
        dialog.close()

    def test_options_dialog_removes_inactive_unsupported_options(self):
        dialog = OptionsDialog(Config())
        texts = _visible_texts(dialog)
        self.assertNotIn("Digitizer unpressed angle", texts)
        self.assertNotIn("Digitizer pressed angle", texts)
        self.assertNotIn("Turn on all quick start dialogs", texts)
        self.assertNotIn("Turn on bid wizard", texts)
        self.assertNotIn("Prompt to refresh worksheet before closing project", texts)
        self.assertNotIn("Connect linear takeoff", texts)
        dialog.close()

    def test_options_dialog_apply_button_starts_disabled(self):
        dialog = OptionsDialog(Config())
        apply_button = _apply_button(dialog)
        self.assertIsNotNone(apply_button)
        self.assertFalse(apply_button.isEnabled())
        dialog.close()

    def test_options_dialog_enables_apply_for_implemented_changes(self):
        dialog = OptionsDialog(Config())
        apply_button = _apply_button(dialog)
        dialog._disable_high_res_check.setChecked(True)
        self.assertTrue(apply_button.isEnabled())
        dialog.close()

    def test_options_dialog_apply_saves_and_keeps_dialog_open(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=service.update_app_options,
        )
        dialog.show()
        apply_button = _apply_button(dialog)
        dialog._disable_high_res_check.setChecked(True)
        apply_button.click()
        self.assertTrue(dialog.isVisible())
        self.assertFalse(apply_button.isEnabled())
        self.assertTrue(aggregate.disable_high_resolution_images)
        self.assertEqual(
            event_bus.events,
            [_app_config_event({"disable_high_resolution_images": True})],
        )
        dialog.close()

    def test_options_dialog_apply_noop_does_not_publish(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=service.update_app_options,
        )
        dialog._apply_pending_changes()
        self.assertEqual(event_bus.events, [])
        self.assertFalse(_apply_button(dialog).isEnabled())
        dialog.close()

    def test_options_dialog_uses_x_only_window_chrome(self):
        dialog = OptionsDialog(Config())
        flags = dialog.windowFlags()
        self.assertFalse(bool(flags & QtCore.Qt.WindowType.WindowMinimizeButtonHint))
        self.assertFalse(bool(flags & QtCore.Qt.WindowType.WindowMaximizeButtonHint))
        self.assertEqual(dialog.minimumWidth(), OPTIONS_WINDOW_WIDTH)
        self.assertEqual(dialog.minimumHeight(), OPTIONS_WINDOW_HEIGHT)
        self.assertEqual(dialog.maximumWidth(), OPTIONS_WINDOW_WIDTH)
        self.assertEqual(dialog.maximumHeight(), OPTIONS_WINDOW_HEIGHT)
        dialog.close()

    def test_options_dialog_contains_options_and_mcp_setup_tabs(self):
        dialog = OptionsDialog(Config())
        self.assertEqual(dialog._tabs.count(), 2)
        self.assertEqual(dialog._tabs.tabText(0), OPTIONS_TAB_OPTIONS)
        self.assertEqual(dialog._tabs.tabText(1), OPTIONS_TAB_MCP_SETUP)
        dialog.close()

    def test_mcp_setup_tab_contains_existing_setup_controls(self):
        helper_path = Path("C:/Tools/ostv-mcp.exe")
        dialog = OptionsDialog(Config(), mcp_helper_path=helper_path)
        tab = dialog._mcp_setup_tab
        texts = _visible_texts(dialog)
        self.assertIn("Connect AI tools", texts)
        self.assertIn("Claude Desktop or Cursor", texts)
        self.assertIn("Codex CLI", texts)
        self.assertEqual(
            tab.claude_config_edit.toPlainText(),
            build_claude_desktop_config(helper_path),
        )
        self.assertEqual(
            tab.codex_command_edit.toPlainText(),
            build_codex_mcp_add_command(helper_path),
        )
        self.assertEqual(tab.copy_claude_button.text(), "Copy Setup JSON")
        self.assertEqual(tab.copy_codex_button.text(), "Copy Setup Command")
        dialog.close()

    def test_mcp_setup_tab_copy_action_preserves_options_apply_state(self):
        helper_path = Path("C:/Tools/ostv-mcp.exe")
        dialog = OptionsDialog(Config(), mcp_helper_path=helper_path)
        apply_button = _apply_button(dialog)
        dialog._tabs.setCurrentWidget(dialog._mcp_setup_tab)
        dialog._mcp_setup_tab.copy_codex_button.click()
        self.assertEqual(
            QtWidgets.QApplication.clipboard().text(),
            build_codex_mcp_add_command(helper_path),
        )
        self.assertIn("Copied to clipboard.", dialog._mcp_setup_tab.status_label.text())
        self.assertFalse(apply_button.isEnabled())
        dialog.close()

    def test_menu_builder_no_longer_exposes_mcp_setup_action(self):
        builder = MenuBuilder(None, {})
        tools_items = builder._get_menu_definition()["Tools"]
        old_label = "MCP " + "Setup..."
        old_key = "mcp_" + "setup"
        self.assertIn(("cmd", "Options...", "options"), tools_items)
        self.assertNotIn(("cmd", old_label, old_key), tools_items)

    def test_update_app_options_updates_color_mode_and_publishes_changed_payload(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options({"color_mode": "Original"})
        self.assertEqual(changed, ["color_mode"])
        self.assertEqual(aggregate.color_mode, "Original")
        self.assertEqual(repo.saved[-1]["color_mode"], "Original")
        self.assertEqual(
            event_bus.events,
            [_app_config_event({"color_mode": "Original"})],
        )

    def test_update_app_options_updates_grayscale_and_publishes_changed_payload(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options({"grayscale_enabled": False})
        self.assertEqual(changed, ["grayscale_enabled"])
        self.assertFalse(aggregate.grayscale_enabled)
        self.assertFalse(repo.saved[-1]["grayscale_enabled"])
        self.assertEqual(
            event_bus.events,
            [_app_config_event({"grayscale_enabled": False})],
        )

    def test_update_app_options_updates_snap_preferences_and_publishes_payload(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options(SNAP_PREF_UPDATE)
        self.assertEqual(changed, SNAP_PREF_CHANGED_KEYS)
        _assert_snap_pref_update_applied(self, aggregate)
        self.assertEqual(event_bus.events, [_app_config_event(SNAP_PREF_UPDATE)])

    def test_config_service_public_api_is_single_app_config_write_path(self):
        public_methods = {
            name
            for name, value in ConfigService.__dict__.items()
            if callable(value) and not name.startswith("_")
        }
        self.assertEqual(
            public_methods,
            {"get_config_snapshot", "update_app_options"},
        )

    def test_menu_grayscale_toggle_uses_general_app_config_update_path(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        controller = MenuController.__new__(MenuController)
        controller.config_service = service
        result = controller._toggle_takeoff_grayscale()
        self.assertFalse(result)
        self.assertFalse(aggregate.grayscale_enabled)
        self.assertEqual(
            event_bus.events,
            [_app_config_event({"grayscale_enabled": False})],
        )

    def test_grayscale_noop_does_not_publish(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options({"grayscale_enabled": True})
        self.assertEqual(changed, [])
        self.assertEqual(event_bus.events, [])

    def test_options_dialog_loads_and_saves_main_hotlink_target(self):
        dialog = OptionsDialog(Config(hotlink_target="main"))
        self.assertTrue(dialog._hotlink_main_radio.isChecked())
        self.assertTrue(dialog._hotlink_main_radio.isEnabled())
        dialog.close()
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=service.update_app_options,
        )
        dialog._hotlink_main_radio.setChecked(True)
        _apply_button(dialog).click()
        self.assertEqual(aggregate.hotlink_target, "main")
        self.assertEqual(
            event_bus.events,
            [_app_config_event({"hotlink_target": "main"})],
        )
        dialog.close()

    def test_update_app_options_accepts_main_hotlink_target(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options({"hotlink_target": "main"})
        self.assertEqual(changed, ["hotlink_target"])
        self.assertEqual(aggregate.hotlink_target, "main")
        self.assertEqual(
            event_bus.events,
            [_app_config_event({"hotlink_target": "main"})],
        )

    def test_menu_color_mode_uses_general_app_config_update_path(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        controller = MenuController.__new__(MenuController)
        controller.config_service = service
        controller._set_takeoff_color_mode("Original")
        self.assertEqual(aggregate.color_mode, "Original")
        self.assertEqual(
            event_bus.events,
            [_app_config_event({"color_mode": "Original"})],
        )

    def test_update_app_options_does_not_publish_when_nothing_changed(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options({"color_mode": aggregate.color_mode})
        self.assertEqual(changed, [])
        self.assertEqual(event_bus.events, [])

    def test_app_config_updated_is_published_only_by_config_service(self):
        publishers = []
        for path in (REPO_ROOT / "ost_visualizer").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "AppEvents.APP_CONFIG_UPDATED" in text and ".publish(" in text:
                publishers.append(path.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(
            publishers,
            ["ost_visualizer/application/services/config_service.py"],
        )

    def test_invalid_color_mode_uses_config_aggregate_validation_policy(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        with self.assertLogs(
            "ost_visualizer.domain.aggregates.config_aggregate",
            level="WARNING",
        ):
            changed = service.update_app_options({"color_mode": "BadMode"})
        self.assertEqual(changed, [])
        self.assertEqual(aggregate.color_mode, Config.DEFAULT_COLOR_MODE)
        self.assertEqual(event_bus.events, [])

    def test_invalid_snap_threshold_uses_config_aggregate_validation_policy(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        with self.assertLogs(
            "ost_visualizer.domain.aggregates.config_aggregate",
            level="WARNING",
        ):
            changed = service.update_app_options({"snap_to_grid_threshold_px": 101})
        self.assertEqual(changed, [])
        self.assertEqual(
            aggregate.snap_to_grid_threshold_px, Config.DEFAULT_SNAP_THRESHOLD_PX
        )
        self.assertEqual(event_bus.events, [])

    def test_project_database_write_paths_do_not_depend_on_config_service(self):
        write_path_roots = [
            REPO_ROOT / "ost_visualizer" / "infrastructure",
            REPO_ROOT / "ost_visualizer" / "application" / "services",
        ]
        scanned = []
        for root in write_path_roots:
            for path in root.rglob("*.py"):
                if path.name == "config_service.py":
                    continue
                text = path.read_text(encoding="utf-8")
                if "write" in path.name.lower() or "mdb" in path.parts:
                    scanned.append(path)
                    self.assertNotIn("config_service", text)
                    self.assertNotIn("ConfigService", text)
        self.assertTrue(scanned)

    def test_options_dialog_ok_saves_implemented_preferences(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        dialog = OptionsDialog(service.get_config_snapshot())
        dialog._color_original_radio.setChecked(True)
        dialog._grayscale_check.setChecked(False)
        dialog._roping_inclusive_radio.setChecked(True)
        dialog._page_index_check.setChecked(True)
        dialog._sheet_number_check.setChecked(True)
        dialog._hotlink_view_radio.setChecked(True)
        dialog._toolbar_text_check.setChecked(True)
        dialog._disable_high_res_check.setChecked(True)
        dialog._intelligent_paste_check.setChecked(False)
        dialog._advanced_mouse_controls_check.setChecked(False)
        dialog._full_window_crosshairs_check.setChecked(True)
        dialog._crosshair_color_button.set_color("#123456")
        dialog._crosshair_line_thickness_spin.setValue(4)
        dialog._allow_add_page_from_takeoff_check.setChecked(True)
        dialog._mouse_unpressed_snap_angle_combo.setCurrentIndex(
            dialog._mouse_unpressed_snap_angle_combo.findData(30)
        )
        dialog._mouse_pressed_snap_angle_combo.setCurrentIndex(
            dialog._mouse_pressed_snap_angle_combo.findData(45)
        )
        dialog._snap_to_grid_check.setChecked(SNAP_PREF_UPDATE["snap_to_grid_enabled"])
        dialog._snap_to_grid_threshold_spin.setValue(
            SNAP_PREF_UPDATE["snap_to_grid_threshold_px"]
        )
        dialog._snap_to_pdf_lines_check.setChecked(
            SNAP_PREF_UPDATE["snap_to_pdf_lines_enabled"]
        )
        dialog._snap_to_pdf_lines_threshold_spin.setValue(
            SNAP_PREF_UPDATE["snap_to_pdf_lines_threshold_px"]
        )
        dialog._snap_to_takeoffs_check.setChecked(
            SNAP_PREF_UPDATE["snap_to_takeoffs_enabled"]
        )
        dialog._snap_to_takeoffs_threshold_spin.setValue(
            SNAP_PREF_UPDATE["snap_to_takeoffs_threshold_px"]
        )
        dialog._snap_to_right_angle_check.setChecked(
            SNAP_PREF_UPDATE["snap_to_right_angle_enabled"]
        )
        dialog._snap_to_right_angle_threshold_spin.setValue(
            SNAP_PREF_UPDATE["snap_to_right_angle_threshold_px"]
        )
        dialog._auto_zoom_spin.setValue(125)
        dialog.accept()
        changed = service.update_app_options(dialog.get_config())
        self.assertIn("roping_selection_method", changed)
        self.assertEqual(aggregate.color_mode, "Original")
        self.assertFalse(aggregate.grayscale_enabled)
        self.assertEqual(aggregate.roping_selection_method, "inclusive")
        self.assertTrue(aggregate.display_page_index_with_sheet_name)
        self.assertTrue(aggregate.display_sheet_number_with_sheet_name)
        self.assertEqual(aggregate.hotlink_target, "view")
        self.assertTrue(aggregate.show_toolbar_text)
        self.assertTrue(aggregate.disable_high_resolution_images)
        self.assertFalse(aggregate.enable_intelligent_paste)
        self.assertFalse(aggregate.enable_advanced_mouse_controls)
        self.assertTrue(aggregate.use_full_window_crosshairs)
        self.assertEqual(aggregate.crosshair_color, "#123456")
        self.assertEqual(aggregate.crosshair_line_thickness, 4)
        self.assertTrue(aggregate.allow_add_page_from_takeoff_tab)
        self.assertEqual(aggregate.mouse_unpressed_snap_angle, 30)
        self.assertEqual(aggregate.mouse_pressed_snap_angle, 45)
        _assert_snap_pref_update_applied(self, aggregate)
        self.assertEqual(aggregate.default_auto_zoom_level, 125)
        self.assertEqual(event_bus.events[0][0], AppEvents.APP_CONFIG_UPDATED)
        dialog.close()

    def test_options_dialog_ok_callback_saves_and_closes(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        service = ConfigService(aggregate, FakeEventBus())
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=service.update_app_options,
        )
        dialog._disable_high_res_check.setChecked(True)
        dialog.accept()
        self.assertEqual(
            dialog.result(),
            QtWidgets.QDialog.DialogCode.Accepted,
        )
        self.assertTrue(aggregate.disable_high_resolution_images)

    def test_options_dialog_result_path_runs_lifecycle_cleanup(self):
        dialog = OptionsDialog(Config())
        mcp_tab = dialog._mcp_setup_tab
        cleanup_calls = []
        mcp_tab.cleanup = lambda: cleanup_calls.append("mcp")
        dialog.reject()
        self.assertEqual(cleanup_calls, ["mcp"])
        self.assertIsNone(dialog._tabs)
        self.assertIsNone(dialog._options_tab)
        self.assertIsNone(dialog._mcp_setup_tab)

    def test_options_dialog_cancel_does_not_save_changes(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        service = ConfigService(aggregate, FakeEventBus())
        dialog = OptionsDialog(service.get_config_snapshot())
        dialog._color_original_radio.setChecked(True)
        dialog._grayscale_check.setChecked(False)
        dialog._roping_inclusive_radio.setChecked(True)
        dialog.reject()
        self.assertEqual(aggregate.color_mode, "Solid")
        self.assertTrue(aggregate.grayscale_enabled)
        self.assertEqual(aggregate.roping_selection_method, "touching")
        self.assertEqual(repo.saved, [])
        dialog.close()

    def test_options_dialog_apply_then_cancel_keeps_only_applied_changes(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        service = ConfigService(aggregate, FakeEventBus())
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=service.update_app_options,
        )
        dialog._page_index_check.setChecked(True)
        _apply_button(dialog).click()
        dialog._grayscale_check.setChecked(False)
        dialog.reject()
        self.assertTrue(aggregate.display_page_index_with_sheet_name)
        self.assertTrue(aggregate.grayscale_enabled)
        dialog.close()

    def test_options_dialog_disabled_controls_do_not_enable_apply(self):
        dialog = OptionsDialog(Config())
        apply_button = _apply_button(dialog)
        disabled_checks = [
            check
            for check in dialog.findChildren(QtWidgets.QCheckBox)
            if not check.isEnabled()
        ]
        self.assertTrue(disabled_checks)
        disabled_checks[0].click()
        self.assertFalse(apply_button.isEnabled())
        dialog.close()

    def test_options_dialog_color_settings_publish_same_app_config_payload(self):
        repo = FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        dialog = OptionsDialog(service.get_config_snapshot())
        dialog._color_transparent_radio.setChecked(True)
        dialog._grayscale_check.setChecked(False)
        dialog.accept()
        changed = service.update_app_options(dialog.get_config())
        self.assertEqual(changed, ["color_mode", "grayscale_enabled"])
        self.assertEqual(
            event_bus.events,
            [
                _app_config_event(
                    {
                        "color_mode": "Transparent",
                        "grayscale_enabled": False,
                    }
                )
            ],
        )
        dialog.close()

    def test_roping_preference_changes_selection_mode(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view.set_roping_selection_method("inclusive")
        self.assertEqual(
            view._roping_item_selection_mode(),
            QtCore.Qt.ItemSelectionMode.ContainsItemShape,
        )
        view.set_roping_selection_method("touching")
        self.assertEqual(
            view._roping_item_selection_mode(),
            QtCore.Qt.ItemSelectionMode.IntersectsItemShape,
        )

    def test_config_defaults_preserve_existing_enabled_behaviors(self):
        config = Config()
        self.assertFalse(config.disable_high_resolution_images)
        self.assertTrue(config.enable_intelligent_paste)
        self.assertTrue(config.enable_advanced_mouse_controls)
        self.assertFalse(config.use_full_window_crosshairs)
        self.assertEqual(config.crosshair_color, "#00ff00")
        self.assertEqual(config.crosshair_line_thickness, 1)
        self.assertFalse(config.allow_add_page_from_takeoff_tab)
        self.assertEqual(config.mouse_unpressed_snap_angle, 15)
        self.assertEqual(config.mouse_pressed_snap_angle, 0)
        self.assertTrue(config.snap_to_grid_enabled)
        self.assertEqual(
            config.snap_to_grid_threshold_px, Config.DEFAULT_SNAP_THRESHOLD_PX
        )
        self.assertTrue(config.snap_to_pdf_lines_enabled)
        self.assertEqual(
            config.snap_to_pdf_lines_threshold_px, Config.DEFAULT_SNAP_THRESHOLD_PX
        )
        self.assertTrue(config.snap_to_takeoffs_enabled)
        self.assertEqual(
            config.snap_to_takeoffs_threshold_px, Config.DEFAULT_SNAP_THRESHOLD_PX
        )
        self.assertFalse(config.snap_to_right_angle_enabled)
        self.assertEqual(
            config.snap_to_right_angle_threshold_px, Config.DEFAULT_SNAP_THRESHOLD_PX
        )
        self.assertEqual(config.default_auto_zoom_level, 0)

    def test_crosshair_preference_updates_plan_view_overlay_state(self):
        view, viewport = _plan_view_with_tracking_viewport()
        TakeoffPlanView.set_full_window_crosshairs(view, True, "#123456", 4)
        self.assertTrue(view._use_full_window_crosshairs)
        self.assertEqual(view._crosshair_color, "#123456")
        self.assertEqual(view._crosshair_line_thickness, 4)
        self.assertEqual(viewport.tracking, [True])
        self.assertEqual(viewport.updates, 1)
        TakeoffPlanView.set_full_window_crosshairs(view, False, "#654321", 2)
        self.assertFalse(view._use_full_window_crosshairs)
        self.assertEqual(viewport.tracking, [True, False])
        self.assertEqual(viewport.updates, 2)

    def test_crosshair_disabled_keeps_mouse_tracking_on_during_placement(self):
        view, viewport = _plan_view_with_tracking_viewport("place")
        TakeoffPlanView.set_full_window_crosshairs(view, False, "#123456", 4)
        self.assertFalse(view._use_full_window_crosshairs)
        self.assertEqual(viewport.tracking, [True])
        self.assertEqual(viewport.updates, 1)

    def test_cursor_mode_changes_refresh_preview_mouse_tracking(self):
        view, viewport = _plan_view_with_tracking_viewport()
        TakeoffPlanView._apply_cursor_mode(view, "place")
        TakeoffPlanView._apply_cursor_mode(view, "paste_backout")
        TakeoffPlanView._apply_cursor_mode(view, "select")
        self.assertEqual(viewport.tracking, [True, True, False])
        self.assertEqual(viewport.updates, 3)

    def test_crosshair_repaints_on_vertical_and_horizontal_scroll(self):
        class FakeViewport:
            def __init__(self):
                self.updates = 0

            def update(self):
                self.updates += 1

        class BaseScrollView:
            def scrollContentsBy(self, dx, dy):
                self.base_scrolls.append((dx, dy))

        class FakeScrollView(ZoomHandlerMixin, BaseScrollView):
            def __init__(self):
                self.base_scrolls = []
                self._viewport = FakeViewport()
                self._use_full_window_crosshairs = True
                self._selected_uids = set()
                self._cursor_mode = "select"
                self._place_preview_items = []
                self._paste_backout_active = False
                self._can_zoom_rerender = False

            def viewport(self):
                return self._viewport

            def _request_crosshair_repaint(self):
                if self._use_full_window_crosshairs:
                    self._viewport.update()

            def _uses_dynamic_tile_coverage(self):
                return self._can_zoom_rerender

        view = FakeScrollView()
        view.scrollContentsBy(0, 12)
        view.scrollContentsBy(15, 0)
        self.assertEqual(view.base_scrolls, [(0, 12), (15, 0)])
        self.assertEqual(view._viewport.updates, 2)
        view._use_full_window_crosshairs = False
        view.scrollContentsBy(3, 4)
        self.assertEqual(view._viewport.updates, 2)

    def test_overlay_only_pdf_panning_refreshes_tile_coverage(self):
        class BaseScrollView:
            def scrollContentsBy(self, dx, dy):
                self.base_scrolls.append((dx, dy))

        class FakeZoomDebouncer:
            def __init__(self):
                self.scales = []

            def handle_scale_changed(self, scale):
                self.scales.append(scale)

        class FakeScrollView(ZoomHandlerMixin, BaseScrollView):
            def __init__(self):
                self.base_scrolls = []
                self._use_full_window_crosshairs = False
                self._selected_uids = set()
                self._cursor_mode = "select"
                self._place_preview_items = []
                self._paste_backout_active = False
                self._zoom_debouncer = FakeZoomDebouncer()

            def viewport(self):
                return SimpleNamespace(update=lambda: None)

            def transform(self):
                return SimpleNamespace(m11=lambda: 4.0)

            def _request_crosshair_repaint(self):
                return None

            def _uses_dynamic_tile_coverage(self):
                return True

        view = FakeScrollView()
        view.scrollContentsBy(8, 0)

        self.assertEqual(view.base_scrolls, [(8, 0)])
        self.assertEqual(view._zoom_debouncer.scales, [4.0])

    def test_takeoff_next_page_allows_add_only_on_last_page_when_enabled(self):
        class FakePageCombo:
            def __init__(self, active_uid):
                self.active_uid = active_uid
                self.next_calls = 0

            def get_page_order(self):
                return ["p1", "p2"]

            def get_active_page_uid(self):
                return self.active_uid

            def go_next(self):
                self.next_calls += 1

        add_calls = []
        window = MainWindow.__new__(MainWindow)
        window._config_model = SimpleNamespace(allow_add_page_from_takeoff_tab=True)
        window.tab_widget = SimpleNamespace(currentIndex=lambda: 1)
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        window._project_data_service = SimpleNamespace(
            is_current_bid_locked=lambda: False
        )
        window.ui_state_manager = SimpleNamespace(get_selected_bid_ref=lambda: object())
        window.handlers = SimpleNamespace(
            cover_sheet=SimpleNamespace(
                add_blank_page_from_takeoff_tab=lambda: add_calls.append("add")
            )
        )
        window.takeoff_sidebar = FakePageCombo("p2")
        self.assertTrue(MainWindow.can_go_next_takeoff_page(window))
        MainWindow.go_next_takeoff_page(window)
        self.assertEqual(add_calls, ["add"])
        self.assertEqual(window.takeoff_sidebar.next_calls, 0)
        add_calls.clear()
        window.takeoff_sidebar = FakePageCombo("p1")
        MainWindow.go_next_takeoff_page(window)
        self.assertEqual(add_calls, [])
        self.assertEqual(window.takeoff_sidebar.next_calls, 1)

    def test_takeoff_next_page_does_not_offer_add_when_preference_disabled(self):
        window = MainWindow.__new__(MainWindow)
        window._config_model = SimpleNamespace(allow_add_page_from_takeoff_tab=False)
        window.tab_widget = SimpleNamespace(currentIndex=lambda: 1)
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        window._project_data_service = SimpleNamespace(
            is_current_bid_locked=lambda: False
        )
        window.ui_state_manager = SimpleNamespace(get_selected_bid_ref=lambda: object())
        window.takeoff_sidebar = SimpleNamespace(
            get_page_order=lambda: ["p1"],
            get_active_page_uid=lambda: "p1",
        )
        self.assertFalse(MainWindow.can_go_next_takeoff_page(window))

    def test_high_resolution_preference_caps_pdf_rerendering(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._can_zoom_rerender = True
        view._disable_high_resolution_images = True
        view._current_page = None
        view._loaded_visual_kind = None
        self.assertEqual(view._target_base_raster_scale(1.0, view_m11=4.0), 1.0)
        view._disable_high_resolution_images = False
        view._scene_scale = 2.0
        view._pdf_width_pts = 100.0
        view._pdf_height_pts = 100.0
        view._device_pixel_ratio = lambda: 1.0
        self.assertGreater(view._target_base_raster_scale(1.0, view_m11=4.0), 1.0)

    def test_high_resolution_preference_disables_tiles(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._can_zoom_rerender = True
        view._disable_high_resolution_images = True
        view._current_page = object()
        view._loaded_visual_kind = None
        view._clear_tiles = lambda: calls.append("clear")
        view._cancel_optional_base_correction = lambda: calls.append("cancel")
        view._update_tile_coverage(4.0)
        self.assertEqual(calls, ["clear", "cancel"])

    def test_high_resolution_preference_change_refreshes_current_page_immediately(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._current_page = object()
        view._loaded_visual_kind = None
        view._disable_high_resolution_images = False
        view._can_zoom_rerender = True
        view._is_composite_mode = False
        view._background_item = object()
        view._base_raster_scale = 3.0
        view._scene_scale = 2.0
        view._clear_tiles = lambda: calls.append("clear")
        view._cancel_optional_base_correction = lambda: calls.append("cancel")
        view._advance_render_generation = lambda: 7
        view._request_optional_base_correction = lambda scale, generation: calls.append(
            ("base", scale, generation)
        )
        view.viewport = lambda: SimpleNamespace(update=lambda: calls.append("viewport"))
        view.set_disable_high_resolution_images(True)
        self.assertEqual(
            calls,
            ["clear", "cancel", ("base", 2.0, 7), "viewport"],
        )

    def test_composite_base_pdf_overlay_uses_stable_overlay_scale(self):
        class FakePageCache:
            def __init__(self):
                self.calls = []

            def get_tinted_page(
                self, file_path, page_index, scale, rotation, tint_rgb
            ):
                self.calls.append((file_path, page_index, scale, rotation, tint_rgb))
                return QtGui.QImage(300, 300, QtGui.QImage.Format.Format_ARGB32)

        page_cache = FakePageCache()
        renderer = CompositeRenderer(page_cache)
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
        )

        renderer.render_composite(
            page,
            bid_ref=None,
            render_scale=3.0,
            raster_rotation=0,
        )

        self.assertEqual(page_cache.calls[0][2], 3.0)
        self.assertEqual(page_cache.calls[1][2], 2.0)

    def test_composite_tile_pdf_overlay_uses_tile_scale(self):
        class FakePageCache:
            def __init__(self):
                self.calls = []

            def render_region_uncached(
                self,
                file_path,
                page_index,
                scale,
                tile_x,
                tile_y,
                tile_w,
                tile_h,
                rotation,
            ):
                self.calls.append(
                    (file_path, page_index, scale, tile_x, tile_y, tile_w, tile_h)
                )
                return QtGui.QImage(tile_w, tile_h, QtGui.QImage.Format.Format_ARGB32)

        page_cache = FakePageCache()
        renderer = CompositeRenderer(page_cache)
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
        )

        renderer.render_composite_region(
            page,
            scale=4.0,
            tile_x=100,
            tile_y=120,
            tile_w=256,
            tile_h=256,
            rotation=0,
        )

        self.assertEqual(page_cache.calls[0][2], 4.0)
        self.assertEqual(page_cache.calls[1][2], 4.0)

    def test_overlay_pdf_item_keeps_scene_size_when_rendered_above_view_scale(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        page = Page(
            uid="page-1",
            name="Page 1",
            overlay_image_path="overlay.pdf",
            width_pts=100.0,
            height_pts=100.0,
            image_show_mode=1,
        )
        pixmap = QtGui.QPixmap(400, 200)

        item = view._create_overlay_graphics_item(
            pixmap,
            page,
            view_scale=2.0,
            show_mode=1,
            render_scale=4.0,
        )

        self.assertEqual(item.scale(), 0.5)
        self.assertEqual(
            item.transformationMode(),
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )

    def test_overlay_raster_item_keeps_default_transformation_mode(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        page = Page(
            uid="page-1",
            name="Page 1",
            overlay_image_path="overlay.png",
            width_pts=100.0,
            height_pts=100.0,
            image_show_mode=1,
        )
        pixmap = QtGui.QPixmap(200, 200)

        item = view._create_overlay_graphics_item(
            pixmap,
            page,
            view_scale=2.0,
            show_mode=1,
            render_scale=2.0,
        )

        self.assertEqual(
            item.transformationMode(),
            QtCore.Qt.TransformationMode.FastTransformation,
        )

    def test_overlay_only_pdf_zoom_requests_dynamic_tile_coverage(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._current_page = Page(
            uid="page-1",
            name="Page 1",
            overlay_image_path="overlay.pdf",
            image_show_mode=1,
            width_pts=100.0,
            height_pts=100.0,
        )
        view._loaded_visual_kind = "overlay"
        view._can_zoom_rerender = False
        view._disable_high_resolution_images = False
        view._pending_page_data = None
        view._base_raster_scale = 2.0
        view._base_raster_request_scale = 0.0
        view._base_correction_request_generation_id = 0
        view._page_render_generation_id = 0
        view._scene_scale = 2.0
        view._pdf_width_pts = 100.0
        view._pdf_height_pts = 100.0
        view._overlay_pdf_width_pts = 100.0
        view._overlay_pdf_height_pts = 100.0
        view._tile_scale = 0.0
        view._tile_items = {}
        view._tile_requests = {}
        view._device_pixel_ratio = lambda: 1.0
        view._cancel_tile_requests = lambda: calls.append("cancel_tiles")
        view._cancel_optional_base_correction = lambda: calls.append("cancel_base")
        view._demote_old_scale_tiles = lambda: calls.append("demote")
        view._overlay_pdf_tile_transform = lambda: QtGui.QTransform()
        view.mapToScene = lambda _rect: QtGui.QPolygonF(QtCore.QRectF(0, 0, 50, 50))
        view.viewport = lambda: SimpleNamespace(rect=lambda: QtCore.QRect(0, 0, 50, 50))
        view._partition_visible_and_buffered_tiles = (
            lambda _rect, _scale: ({TileKey(0, 0, 8.0)}, set())
        )
        view._tile_keys_local_rect = lambda _keys: QtCore.QRectF(0, 0, 50, 50)
        view._evict_old_scale_tiles_outside = lambda _rect: calls.append("evict_old")
        view._evict_tiles_at_scale = lambda _scale, _keys: calls.append("evict_scale")
        view._request_tile = (
            lambda key, generation, priority: calls.append(
                ("tile", key.scale, generation, priority)
            )
        )

        view._update_tile_coverage(4.0)

        self.assertEqual(
            calls,
            [
                "demote",
                "cancel_tiles",
                "cancel_base",
                "evict_old",
                "evict_scale",
                ("tile", 8.0, 1, 1),
            ],
        )

    def test_overlay_only_pdf_tile_request_renders_overlay_source(self):
        class FakeRenderingService:
            def __init__(self):
                self.calls = []

            def render_region_async(self, **kwargs):
                self.calls.append(kwargs)
                return "tile-request"

        rendering_service = FakeRenderingService()
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._current_page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            image_show_mode=1,
            width_pts=100.0,
            height_pts=100.0,
            invert=True,
            bitonal=True,
        )
        view._loaded_visual_kind = "overlay"
        view._is_composite_mode = False
        view._scene_scale = 2.0
        view._overlay_pdf_width_pts = 100.0
        view._overlay_pdf_height_pts = 100.0
        view._tile_items = {}
        view._tile_requests = {}
        view._current_load_token = "load-1"
        view._current_render_identity = {"page": "page-1"}
        view._current_bid_ref = None
        view._rendering_service = rendering_service

        view._request_tile(TileKey(0, 0, 4.0), generation_id=1, priority=2)

        self.assertEqual(len(rendering_service.calls), 1)
        call = rendering_service.calls[0]
        self.assertEqual(call["file_path"], "overlay.pdf")
        self.assertEqual(call["page_index"], 0)
        self.assertEqual(call["scale"], 4.0)
        self.assertTrue(call["invert"])
        self.assertTrue(call["bitonal"])

    def test_overlay_only_pdf_high_resolution_disabled_requests_low_scale_base(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._current_page = Page(
            uid="page-1",
            name="Page 1",
            overlay_image_path="overlay.pdf",
            image_show_mode=1,
            width_pts=100.0,
            height_pts=100.0,
        )
        view._loaded_visual_kind = "overlay"
        view._can_zoom_rerender = False
        view._disable_high_resolution_images = True
        view._base_raster_scale = 3.0
        view._scene_scale = 2.0
        view._clear_tiles = lambda: calls.append("clear")
        view._cancel_optional_base_correction = lambda: calls.append("cancel")
        view._advance_render_generation = lambda: 5
        view._request_optional_overlay_base_correction = (
            lambda scale, generation: calls.append(("overlay_base", scale, generation))
        )

        view._update_tile_coverage(4.0)

        self.assertEqual(calls, ["clear", "cancel", ("overlay_base", 2.0, 5)])

    def test_high_resolution_reenabled_requests_current_tile_coverage(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._current_page = object()
        view._disable_high_resolution_images = True
        view._can_zoom_rerender = True
        view._clear_tiles = lambda: calls.append("clear")
        view._cancel_optional_base_correction = lambda: calls.append("cancel")
        view._update_tile_coverage = lambda scale: calls.append(("tiles", scale))
        view.transform = lambda: SimpleNamespace(m11=lambda: 4.0)
        view.viewport = lambda: SimpleNamespace(update=lambda: calls.append("viewport"))
        view.set_disable_high_resolution_images(False)
        self.assertEqual(calls, ["clear", "cancel", ("tiles", 4.0), "viewport"])

    def test_high_resolution_refresh_on_blank_page_does_not_error(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        calls = []
        view._current_page = Page(uid="blank", name="Blank")
        view._loaded_visual_kind = None
        view._disable_high_resolution_images = False
        view._can_zoom_rerender = False
        view._clear_tiles = lambda: calls.append("clear")
        view._cancel_optional_base_correction = lambda: calls.append("cancel")
        view.viewport = lambda: SimpleNamespace(update=lambda: calls.append("viewport"))
        view.set_disable_high_resolution_images(True)
        self.assertEqual(calls, ["clear", "cancel", "viewport"])

    def test_failed_page_render_releases_pending_request_id(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._current_render_requests = ["req-1"]
        view._pending_page_data = {"load_token": "token", "render_identity": {}}
        with self.assertLogs(
            "ost_visualizer.presentation.components.plan_view.components.page_loader",
            level="WARNING",
        ):
            data = view._resolve_pending_render(
                RenderResult(
                    request_id="req-1",
                    success=False,
                    image=None,
                    error="render failed",
                ),
                "Page",
            )
        self.assertIsNone(data)
        self.assertEqual(view._current_render_requests, [])

    def test_advanced_mouse_controls_preference_toggles_shortcuts(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._ctrl_held = False
        view._zoom_press_ctrl = False
        view._advanced_mouse_controls_enabled = True
        self.assertTrue(view._advanced_mouse_controls_active())
        view.set_advanced_mouse_controls_enabled(False)
        self.assertFalse(view._advanced_mouse_controls_active())

    def test_auto_zoom_preference_applies_only_without_saved_page_zoom(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._default_auto_zoom_level = 125
        page = Page(uid="p1", name="A101")
        view._begin_load_cycle(page, preserve_current_view=False)
        self.assertEqual(view._load_initial_view_mode, "auto_zoom")
        page.zoom_fac = 300.0
        view._begin_load_cycle(page, preserve_current_view=False)
        self.assertEqual(view._load_initial_view_mode, "restore")
        view._default_auto_zoom_level = 0
        page.zoom_fac = 0.0
        view._begin_load_cycle(page, preserve_current_view=False)
        self.assertEqual(view._load_initial_view_mode, "fit")

    def _make_intelligent_paste_snap_view(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._scene = QtWidgets.QGraphicsScene()
        view._scene_builder = SimpleNamespace(
            get_coordinate_system=lambda: SimpleNamespace(
                scale_ratio=72.0,
                view_scale=1.0,
            )
        )
        view._current_page_transform = lambda: None
        view._page_scene_rect = lambda: QtCore.QRectF(0.0, 0.0, 200.0, 200.0)
        view.mapFromScene = lambda point: QtCore.QPoint(
            int(round(point.x())),
            int(round(point.y())),
        )
        view._intelligent_paste_enabled = True
        view._intelligent_paste_pending_uids = []
        view._intelligent_paste_pending_source_anchor_ost = None
        view._intelligent_paste_active = True
        view._intelligent_paste_source_anchor_ost = (10.0, 20.0)
        view._intelligent_paste_anchor_start_ost = (50.0, 75.0)
        view._intelligent_paste_drag_positions_start_ost = {
            "pasted": [50.0, 75.0, 54.0, 79.0]
        }
        view._intelligent_paste_guide_items = []
        view._current_annotations = {}
        view._snap_increments = 0.0
        return view

    def _guide_lines(self, view):
        return [item.line() for item in view._intelligent_paste_guide_items]

    def test_intelligent_paste_pending_state_does_not_start_drag_or_rubber_band(self):
        view = self._make_intelligent_paste_snap_view()
        view._intelligent_paste_active = False
        view._intelligent_paste_source_anchor_ost = None
        view._intelligent_paste_anchor_start_ost = None
        view._selected_uids = {"pasted"}
        view._select_band_origin = None
        view._select_band_dragged = False
        view._drag_multi_orig_positions = {}
        self.assertTrue(
            view.mark_intelligent_paste_drag_pending(["pasted"], (10.0, 20.0))
        )
        self.assertFalse(view._intelligent_paste_active)
        self.assertIsNone(view._select_band_origin)
        self.assertFalse(view._select_band_dragged)
        self.assertEqual(view._drag_multi_orig_positions, {})

    def test_intelligent_paste_pending_state_only_snaps_during_first_drag(self):
        view = self._make_intelligent_paste_snap_view()
        view._intelligent_paste_active = False
        view._intelligent_paste_source_anchor_ost = None
        view._intelligent_paste_anchor_start_ost = None
        view.mark_intelligent_paste_drag_pending(["pasted"], (10.0, 20.0))
        dx, dy = view.apply_intelligent_paste_axis_snap(0.0, -50.0)
        self.assertEqual((dx, dy), (0.0, -50.0))
        self.assertEqual(view._intelligent_paste_guide_items, [])
        self.assertTrue(
            view.begin_intelligent_paste_drag_if_pending(
                {"pasted": [50.0, 75.0, 54.0, 79.0]}
            )
        )
        dx, dy = view.apply_intelligent_paste_axis_snap(0.0, -50.0)
        self.assertEqual((dx, dy), (0.0, -55.0))
        view.finish_intelligent_paste_placement()
        self.assertEqual(view._intelligent_paste_pending_uids, [])
        self.assertFalse(view._intelligent_paste_active)

    def test_intelligent_paste_pending_state_clears_on_other_selection_drag(self):
        view = self._make_intelligent_paste_snap_view()
        view._intelligent_paste_active = False
        view.mark_intelligent_paste_drag_pending(["pasted"], (10.0, 20.0))
        self.assertFalse(
            view.begin_intelligent_paste_drag_if_pending(
                {"other": [50.0, 75.0, 54.0, 79.0]}
            )
        )
        self.assertEqual(view._intelligent_paste_pending_uids, [])
        self.assertFalse(view._intelligent_paste_active)

    def test_intelligent_paste_snaps_to_original_x_axis_and_shows_edge_guides(self):
        view = self._make_intelligent_paste_snap_view()
        dx, dy = view.apply_intelligent_paste_axis_snap(0.0, -50.0)
        self.assertEqual((dx, dy), (0.0, -55.0))
        self.assertEqual(len(view._intelligent_paste_guide_items), 2)
        lines = self._guide_lines(view)
        self.assertTrue(all(line.y1() == line.y2() for line in lines))
        self.assertEqual([line.y1() for line in lines], [20.0, 24.0])
        pen = view._intelligent_paste_guide_items[0].pen()
        self.assertEqual(pen.style(), QtCore.Qt.PenStyle.DashLine)
        self.assertEqual(pen.color().name(), "#1f9d45")
        view.finish_intelligent_paste_placement()
        self.assertEqual(view._intelligent_paste_guide_items, [])

    def test_intelligent_paste_snaps_to_original_y_axis_and_shows_edge_guides(self):
        view = self._make_intelligent_paste_snap_view()
        dx, dy = view.apply_intelligent_paste_axis_snap(-35.0, 0.0)
        self.assertEqual((dx, dy), (-40.0, 0.0))
        self.assertEqual(len(view._intelligent_paste_guide_items), 2)
        lines = self._guide_lines(view)
        self.assertTrue(all(line.x1() == line.x2() for line in lines))
        self.assertEqual([line.x1() for line in lines], [10.0, 14.0])
        view.finish_intelligent_paste_placement()
        dx, dy = view.apply_intelligent_paste_axis_snap(-35.0, 0.0)
        self.assertEqual((dx, dy), (-35.0, 0.0))
        self.assertEqual(view._intelligent_paste_guide_items, [])

    def test_intelligent_paste_snaps_to_both_axes_and_shows_four_edge_guides(self):
        view = self._make_intelligent_paste_snap_view()
        dx, dy = view.apply_intelligent_paste_axis_snap(-35.0, -50.0)
        self.assertEqual((dx, dy), (-40.0, -55.0))
        self.assertEqual(len(view._intelligent_paste_guide_items), 4)
        lines = self._guide_lines(view)
        horizontal = [line for line in lines if line.y1() == line.y2()]
        vertical = [line for line in lines if line.x1() == line.x2()]
        self.assertEqual([line.y1() for line in horizontal], [20.0, 24.0])
        self.assertEqual([line.x1() for line in vertical], [10.0, 14.0])

    def test_intelligent_paste_multi_object_y_axis_guides_use_preview_union_bounds(
        self,
    ):
        view = self._make_intelligent_paste_snap_view()
        view._snap_increments = 10.0
        view._intelligent_paste_anchor_start_ost = (51.0, 75.0)
        view._intelligent_paste_drag_positions_start_ost = {
            "pasted-a": [51.0, 75.0, 55.0, 79.0],
            "pasted-b": [85.0, 100.0, 89.0, 104.0],
        }
        dx, dy = view.apply_intelligent_paste_axis_snap(-35.0, 0.0)
        self.assertEqual((dx, dy), (-41.0, 0.0))
        lines = self._guide_lines(view)
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(line.x1() == line.x2() for line in lines))
        self.assertEqual([line.x1() for line in lines], [10.0, 44.0])

    def test_intelligent_paste_multi_object_x_axis_guides_use_preview_union_bounds(
        self,
    ):
        view = self._make_intelligent_paste_snap_view()
        view._snap_increments = 10.0
        view._intelligent_paste_anchor_start_ost = (51.0, 75.0)
        view._intelligent_paste_drag_positions_start_ost = {
            "pasted-a": [51.0, 75.0, 55.0, 79.0],
            "pasted-b": [85.0, 100.0, 89.0, 104.0],
        }
        dx, dy = view.apply_intelligent_paste_axis_snap(0.0, -50.0)
        self.assertEqual((dx, dy), (0.0, -55.0))
        lines = self._guide_lines(view)
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(line.y1() == line.y2() for line in lines))
        self.assertEqual([line.y1() for line in lines], [20.0, 44.0])

    def test_intelligent_paste_multi_object_both_axis_guides_use_preview_union_bounds(
        self,
    ):
        view = self._make_intelligent_paste_snap_view()
        view._snap_increments = 10.0
        view._intelligent_paste_anchor_start_ost = (51.0, 75.0)
        view._intelligent_paste_drag_positions_start_ost = {
            "pasted-a": [51.0, 75.0, 55.0, 79.0],
            "pasted-b": [85.0, 100.0, 89.0, 104.0],
        }
        dx, dy = view.apply_intelligent_paste_axis_snap(-35.0, -50.0)
        self.assertEqual((dx, dy), (-41.0, -55.0))
        lines = self._guide_lines(view)
        self.assertEqual(len(lines), 4)
        horizontal = [line for line in lines if line.y1() == line.y2()]
        vertical = [line for line in lines if line.x1() == line.x2()]
        self.assertEqual([line.y1() for line in horizontal], [20.0, 44.0])
        self.assertEqual([line.x1() for line in vertical], [10.0, 44.0])

    def test_page_label_preferences_update_page_combo_labels(self):
        combo = PageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(
                    uid="p1",
                    name="A101",
                    sheet_no="S1",
                    sequence=3,
                    page_index=0,
                )
            ],
        )
        combo.load_bid(bid)
        self.assertEqual(combo._page_items["p1"].text(), "A101")
        combo.set_label_options(True, False)
        self.assertEqual(combo._page_items["p1"].text(), "3 - A101")
        combo.set_label_options(False, True)
        self.assertEqual(combo._page_items["p1"].text(), "S1 - A101")
        combo.set_label_options(True, True)
        self.assertEqual(combo._page_items["p1"].text(), "3 - S1 - A101")
        combo.set_label_options(False, False)
        self.assertEqual(combo._page_items["p1"].text(), "A101")
        combo.close()

    def test_page_label_index_uses_sequence_not_pdf_page_index(self):
        combo = PageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(uid="p1", name="A101", sequence=7, page_index=0),
                Page(uid="p2", name="A102", sequence=8, page_index=0),
            ],
        )
        combo.set_label_options(True, False)
        combo.load_bid(bid)
        self.assertEqual(combo._page_items["p1"].text(), "7 - A101")
        self.assertEqual(combo._page_items["p2"].text(), "8 - A102")
        self.assertNotEqual(combo._page_items["p1"].text(), "1 - A101")
        self.assertNotEqual(combo._page_items["p2"].text(), "1 - A102")
        combo.restore_selection(["p2"], active_uid="p2")
        self.assertEqual(combo.get_selected_page_uids(), ["p2"])
        self.assertEqual(combo.get_active_page_uid(), "p2")
        self.assertEqual(combo.lineEdit().text(), "8 - A102")
        combo.close()

    def test_page_label_missing_sequence_does_not_show_duplicate_one(self):
        combo = PageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(uid="p1", name="A101", page_index=0),
                Page(uid="p2", name="A102", page_index=0),
            ],
        )
        combo.set_label_options(True, False)
        combo.load_bid(bid)
        self.assertEqual(combo._page_items["p1"].text(), "A101")
        self.assertEqual(combo._page_items["p2"].text(), "A102")
        combo.close()

    def test_single_page_combo_uses_shared_page_label_format(self):
        combo = SinglePageComboBox()
        bid = Bid(
            uid="bid-1",
            name="Bid",
            pages_without_folder=[
                Page(uid="p1", name="A101", sheet_no="S1", sequence=3)
            ],
        )
        combo.set_label_options(True, True)
        combo.load_bid(bid)
        combo.set_current_page_uid("p1")
        self.assertEqual(combo.lineEdit().text(), "3 - S1 - A101")
        combo.close()

    def test_bid_page_info_sequence_populates_page_label_source(self):
        pages = build_pages_from_bid_data(
            {
                "p1": BidPageInfo(
                    name="A101",
                    sheet_no="S1",
                    sequence=12,
                    page_index=0,
                )
            },
            [],
        )
        self.assertEqual(pages["p1"].sequence, 12)
        self.assertEqual(pages["p1"].page_index, 0)

    def test_toolbar_text_preference_updates_workspace_toolbars(self):
        window = MainWindow.__new__(MainWindow)
        window._config_model = SimpleNamespace(show_toolbar_text=True)
        toolbars = [QtWidgets.QToolBar(), QtWidgets.QToolBar()]
        window.get_workspace_toolbars = lambda: toolbars
        MainWindow.apply_toolbar_text_preference(window)
        self.assertTrue(
            all(
                toolbar.toolButtonStyle()
                == QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon
                for toolbar in toolbars
            )
        )
        window._config_model = SimpleNamespace(show_toolbar_text=False)
        MainWindow.apply_toolbar_text_preference(window)
        self.assertTrue(
            all(
                toolbar.toolButtonStyle()
                == QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
                for toolbar in toolbars
            )
        )

    def test_main_window_applies_new_plan_view_preferences(self):
        class FakePlanView:
            def __init__(self):
                self.calls = []

            def set_roping_selection_method(self, value):
                self.calls.append(("roping", value))

            def set_disable_high_resolution_images(self, value):
                self.calls.append(("high_res", value))

            def set_intelligent_paste_enabled(self, value):
                self.calls.append(("paste", value))

            def set_advanced_mouse_controls_enabled(self, value):
                self.calls.append(("mouse", value))

            def set_default_auto_zoom_level(self, value):
                self.calls.append(("auto_zoom", value))

            def set_full_window_crosshairs(self, enabled, color, line_thickness):
                self.calls.append(("crosshair", enabled, color, line_thickness))

            def set_mouse_snap_angles(self, unpressed_angle, pressed_angle):
                self.calls.append(("snap_angles", unpressed_angle, pressed_angle))

            def set_snap_preferences(self, **kwargs):
                self.calls.append(("snap_preferences", kwargs))

        class FakeDetachedWindow:
            def __init__(self):
                self.calls = []

            def apply_config_preferences(self, **kwargs):
                self.calls.append(kwargs)

        window = MainWindow.__new__(MainWindow)
        window.get_workspace_toolbars = lambda: []
        window.takeoff_sidebar = None
        window.plan_view = FakePlanView()
        annotation_window = FakeDetachedWindow()
        view_window = FakeDetachedWindow()
        window.get_annotation_window = lambda: annotation_window
        window.get_view_window = lambda: view_window
        window._config_model = SimpleNamespace(
            show_toolbar_text=False,
            display_page_index_with_sheet_name=True,
            display_sheet_number_with_sheet_name=True,
            roping_selection_method="inclusive",
            disable_high_resolution_images=True,
            enable_intelligent_paste=False,
            enable_advanced_mouse_controls=False,
            use_full_window_crosshairs=True,
            crosshair_color="#123456",
            crosshair_line_thickness=4,
            mouse_unpressed_snap_angle=30,
            mouse_pressed_snap_angle=45,
            **SNAP_PREF_UPDATE,
            default_auto_zoom_level=125,
        )
        MainWindow.apply_config_preferences(window)
        self.assertEqual(
            window.plan_view.calls,
            [
                ("roping", "inclusive"),
                ("high_res", True),
                ("paste", False),
                ("mouse", False),
                ("auto_zoom", 125),
                ("crosshair", True, "#123456", 4),
                ("snap_angles", 30, 45),
                (
                    "snap_preferences",
                    SNAP_PREF_UPDATE,
                ),
            ],
        )
        expected_detached = {
            "show_page_index": True,
            "show_sheet_number": True,
            "roping_selection_method": "inclusive",
            "disable_high_resolution_images": True,
            "intelligent_paste_enabled": False,
            "advanced_mouse_controls_enabled": False,
            "default_auto_zoom_level": 125,
            "use_full_window_crosshairs": True,
            "crosshair_color": "#123456",
            "crosshair_line_thickness": 4,
            "mouse_unpressed_snap_angle": 30,
            "mouse_pressed_snap_angle": 45,
            **SNAP_PREF_UPDATE,
        }
        self.assertEqual(annotation_window.calls, [expected_detached])
        self.assertEqual(view_window.calls, [expected_detached])

    def test_ui_event_coordinator_delegates_app_config_application(self):
        class FakeAppConfigPresentation:
            def __init__(self):
                self.calls = []

            def apply_updated_options(self, window, config_model, changed_values):
                self.calls.append((window, config_model, changed_values))
                return False

        class FakeMenuController:
            def __init__(self):
                self.updated = False

            def update_menu_states(self):
                self.updated = True

        fake_config = SimpleNamespace(show_toolbar_text=True)
        menu_controller = FakeMenuController()
        main_window = SimpleNamespace(
            _config_model=fake_config,
            menu_controller=menu_controller,
        )
        sync_calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = main_window
        coordinator.ui_state_manager = SimpleNamespace(
            sync_from_config=lambda: sync_calls.append("sync"),
            highlighted_condition_uids=[],
        )
        coordinator._app_config_presentation = FakeAppConfigPresentation()
        coordinator._on_app_config_updated(value={"show_toolbar_text": True})
        self.assertEqual(sync_calls, ["sync"])
        self.assertTrue(menu_controller.updated)
        self.assertEqual(
            coordinator._app_config_presentation.calls,
            [(main_window, fake_config, {"show_toolbar_text": True})],
        )

    def test_ui_event_coordinator_keeps_condition_display_refresh_orchestration(self):
        class FakeAppConfigPresentation:
            def apply_updated_options(self, window, config_model, changed_values):
                return True

        class FakeUiAccess:
            def is_allowed(self, feature):
                return True

        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.main_window = SimpleNamespace(
            _config_model=SimpleNamespace(),
            menu_controller=SimpleNamespace(
                update_menu_states=lambda: calls.append("menu")
            ),
        )
        coordinator.ui_state_manager = SimpleNamespace(
            sync_from_config=lambda: calls.append("sync"),
            highlighted_condition_uids=["cond-1"],
        )
        coordinator._app_config_presentation = FakeAppConfigPresentation()
        coordinator._sidebar = SimpleNamespace(
            load_conditions_sidebar=lambda: calls.append("conditions")
        )
        coordinator.conditions_sidebar = SimpleNamespace(
            highlight_conditions=lambda uids: calls.append(("highlight", list(uids)))
        )
        coordinator.ui_access_manager = FakeUiAccess()
        coordinator.project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["page-1"]
        )
        coordinator._viewer = SimpleNamespace(
            update_viewers=lambda page_uids: calls.append(("viewers", page_uids))
        )
        coordinator._update_plan_view_for_active = lambda: calls.append("plan_view")
        coordinator._on_app_config_updated(value={"color_mode": "Original"})
        self.assertEqual(
            calls,
            [
                "sync",
                "menu",
                "conditions",
                ("highlight", ["cond-1"]),
                ("viewers", ["page-1"]),
                "plan_view",
            ],
        )


if __name__ == "__main__":
    unittest.main()
