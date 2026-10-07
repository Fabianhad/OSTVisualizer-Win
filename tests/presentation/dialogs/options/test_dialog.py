from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
    _apply_button as _preferences_support__apply_button,
    _reset_all_button as _preferences_support__reset_all_button,
    _visible_texts as _preferences_support__visible_texts,
)
from tests.helpers.call_recorder import SingleCallRecorder
from shiboken6 import delete, isValid
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from ost_visualizer.presentation.utils.mcp_setup_config import (
    build_claude_desktop_config,
    build_codex_config_toml,
    build_codex_mcp_add_command,
)
from ost_visualizer.presentation.dialogs.options.dialog import OptionsDialog
from ost_visualizer.presentation.dialogs.options.font_dialog import FontDialog
from ost_visualizer.domain.entities.font_definition import FontDefinition
from ost_visualizer.presentation.config import (
    COMPACT_SPACING,
    OPTIONS_DEFERRED_CONFIRMATION_CHECKS,
    OPTIONS_DEFERRED_PREFERENCE_CHECKS,
    OPTIONS_DIALOG_TITLE,
    OPTIONS_GROUP_AUTO_ZOOM,
    OPTIONS_GROUP_CONDITION_NAMES,
    OPTIONS_GROUP_ELEVATION_CALLOUTS,
    OPTIONS_GROUP_PDF_ANNOTATION_CAPTIONS,
    OPTIONS_GROUP_CONFIRMATIONS,
    OPTIONS_GROUP_PREFERENCES,
    OPTIONS_GROUP_SNAP_ANGLE,
    OPTIONS_LABEL_CSV_DROP_ELEVATION,
    OPTIONS_LABEL_GRAYSCALE,
    OPTIONS_LABEL_OST_OSP_DROP_ELEVATION,
    OPTIONS_LABEL_RESET_ALL_SETTINGS,
    OPTIONS_TAB_EXPORT,
    OPTIONS_TAB_FONTS_COLORS,
    OPTIONS_TAB_MCP_SETUP,
    OPTIONS_TAB_OPTIONS,
    OPTIONS_TAB_TAKEOFF_TOOLBAR,
    OPTIONS_WARNING_CSV_DROP_ELEVATION,
    OPTIONS_WARNING_OST_OSP_DROP_ELEVATION,
    OPTIONS_WARNING_TITLE_DROP_ELEVATION,
    OPTIONS_WINDOW_WIDTH,
    RELAXED_SPACING,
    TAB_INDEX_TAKEOFF,
)
from ost_visualizer.presentation.components import color_button as color_button_module
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.annotation_caption import (
    ANNOTATION_CAPTION_ORDER,
    DEFAULT_ANNOTATION_CAPTION_IDS,
    AnnotationCaptionId,
)
from ost_visualizer.application.dtos.annotation_caption_dto import (
    ANNOTATION_CAPTION_SPECS,
)
from dataclasses import replace
from unittest import mock
from pathlib import Path
import unittest
import os
from ost_visualizer.presentation.dialogs.options.fonts_colors_tab import (
    COLOR_CATEGORIES,
    COLOR_CATEGORY_INACTIVE_OBJECTS,
    FONT_CATEGORIES,
    FONT_CATEGORY_TEXT,
    FontsColorsTab,
)
from ost_visualizer.presentation.utils.annotation_defaults import (
    apply_config_owned_annotation_defaults,
    build_placed_annotation_spec,
    set_annotation_styles_by_tool,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class DialogPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_options_group_boxes_use_explicit_density_spacing(self):
        dialog = OptionsDialog(Config())
        try:
            options_tab = dialog._options_tab
            options_layout = options_tab.layout()
            lower_layout = options_layout.itemAt(1).layout()
            lower_columns = tuple(
                lower_layout.itemAt(index).layout()
                for index in range(lower_layout.count())
            )
            self.assertEqual(options_layout.spacing(), RELAXED_SPACING)
            self.assertEqual(lower_layout.spacing(), RELAXED_SPACING)
            self.assertEqual(len(lower_columns), 2)
            self.assertTrue(
                all(column.spacing() == RELAXED_SPACING for column in lower_columns)
            )
            self.assertEqual(
                {
                    group.title(): group.layout().spacing()
                    for group in options_tab.findChildren(QtWidgets.QGroupBox)
                },
                {
                    OPTIONS_GROUP_PREFERENCES: RELAXED_SPACING,
                    OPTIONS_GROUP_SNAP_ANGLE: COMPACT_SPACING,
                    OPTIONS_GROUP_CONFIRMATIONS: COMPACT_SPACING,
                    OPTIONS_GROUP_AUTO_ZOOM: COMPACT_SPACING,
                },
            )
            export_tab = dialog._export_tab
            self.assertEqual(export_tab.layout().spacing(), RELAXED_SPACING)
            export_groups = export_tab.findChildren(QtWidgets.QGroupBox)
            self.assertEqual(len(export_groups), 3)
            self.assertEqual(
                [group.layout().spacing() for group in export_groups],
                [COMPACT_SPACING] * 3,
            )
        finally:
            dialog.close()
            delete(dialog)

    def test_options_dialog_loads_persisted_preferences(self):
        persisted = Config(
            display_modes_synced=False,
            display_mode_3d=Config.DISPLAY_MODE_ORIGINAL,
            display_mode_2d=Config.DISPLAY_MODE_TRANSPARENT,
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
            pdf_annotation_captions_enabled=True,
            pdf_annotation_caption_ids=("area", "volume"),
        )
        dialog = OptionsDialog(persisted)
        self.assertFalse(dialog._display_modes_sync_check.isChecked())
        self.assertTrue(dialog._display_mode_3d_original_radio.isChecked())
        self.assertTrue(dialog._display_mode_2d_transparent_radio.isChecked())
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
        self.assertEqual(dialog._crosshair_color_button.color().name(), "#123456")
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
        self.assertTrue(dialog._caption_master_check.isChecked())
        self.assertTrue(dialog._caption_checks[AnnotationCaptionId.AREA].isChecked())
        self.assertTrue(dialog._caption_checks[AnnotationCaptionId.VOLUME].isChecked())
        self.assertFalse(dialog._caption_checks[AnnotationCaptionId.LENGTH].isChecked())
        self.assertTrue(
            all(check.isEnabled() for check in dialog._caption_checks.values())
        )
        self.assertFalse(dialog._roping_touching_radio.isChecked())
        self.assertFalse(dialog._hotlink_annotation_radio.isChecked())
        self.assertFalse(dialog._display_mode_3d_solid_radio.isChecked())
        self.assertFalse(dialog._display_mode_2d_original_radio.isChecked())
        self.assertEqual(dialog._collect_widget_config(), persisted)
        self.assertFalse(_preferences_support__apply_button(dialog).isEnabled())
        dialog.close()

    def test_options_crosshair_color_preview_is_square_and_not_stylesheet_colored(self):
        dialog = OptionsDialog(Config(crosshair_color="#123456"))
        button = dialog._crosshair_color_button
        self.assertEqual(button.minimumWidth(), button.minimumHeight())
        self.assertEqual(button.maximumWidth(), button.maximumHeight())
        self.assertEqual(button.styleSheet(), "")
        button.set_color(QtGui.QColor("#abcdef"))
        self.assertEqual(button.color().name(), "#abcdef")
        self.assertEqual(button.styleSheet(), "")
        dialog.close()

    def test_options_dialog_does_not_show_auto_dimension_lines_preference(self):
        dialog = OptionsDialog(Config())
        labels = {
            checkbox.text() for checkbox in dialog.findChildren(QtWidgets.QCheckBox)
        }
        self.assertIn(OPTIONS_LABEL_GRAYSCALE, labels)
        self.assertNotIn("Enable auto dimension lines", labels)
        self.assertNotIn("Show right angle line indicator", labels)
        dialog.close()

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

            def deleteLater(self):
                pass

        original_dialog = color_button_module.QtWidgets.QColorDialog
        color_button_module.QtWidgets.QColorDialog = FakeColorDialog
        try:
            button._choose_color()
        finally:
            color_button_module.QtWidgets.QColorDialog = original_dialog
        self.assertEqual(button.color().name(), "#abcdef")
        self.assertEqual(dialog.get_config().crosshair_color, "#123456")
        self.assertEqual(dialog._collect_widget_config().crosshair_color, "#abcdef")
        self.assertTrue(_preferences_support__apply_button(dialog).isEnabled())
        self.assertEqual(created_dialogs[0].initial_color, "#123456")
        self.assertIs(created_dialogs[0].parent, button)
        self.assertEqual(created_dialogs[0].parent.styleSheet(), "")
        self.assertEqual(created_dialogs[0].stylesheet_calls, [])
        dialog.close()

    def test_options_crosshair_color_picker_cancel_keeps_previous_color(self):
        dialog = OptionsDialog(Config(crosshair_color="#123456"))
        button = dialog._crosshair_color_button
        changed = []
        button.colorChanged.connect(lambda: changed.append(button.color().name()))

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

            def deleteLater(self):
                pass

        original_dialog = color_button_module.QtWidgets.QColorDialog
        color_button_module.QtWidgets.QColorDialog = FakeColorDialog
        try:
            button._choose_color()
        finally:
            color_button_module.QtWidgets.QColorDialog = original_dialog
        self.assertEqual(button.color().name(), "#123456")
        self.assertEqual(changed, [])
        self.assertFalse(_preferences_support__apply_button(dialog).isEnabled())
        dialog.close()

    def test_options_color_picker_stops_when_button_is_destroyed(self):
        dialog = OptionsDialog(Config(crosshair_color="#123456"))
        button = dialog._crosshair_color_button

        class DestroyingColorDialog(QtWidgets.QColorDialog):
            def exec(self):
                delete(self.parent())
                return QtWidgets.QDialog.DialogCode.Accepted

            def currentColor(self):
                raise AssertionError("destroyed color dialog must not be read")

        with mock.patch.object(
            color_button_module.QtWidgets,
            "QColorDialog",
            DestroyingColorDialog,
        ):
            button._choose_color()
        self.assertFalse(isValid(button))
        dialog.close()

    def test_repeated_options_color_picker_cancellation_releases_dialogs(self):
        dialog = OptionsDialog(Config(crosshair_color="#123456"))
        button = dialog._crosshair_color_button
        real_color_dialog = QtWidgets.QColorDialog
        try:
            with (
                mock.patch.object(
                    color_button_module.QtWidgets,
                    "QColorDialog",
                    side_effect=lambda color, parent: real_color_dialog(color, parent),
                ),
                mock.patch.object(
                    real_color_dialog,
                    "exec",
                    return_value=QtWidgets.QDialog.DialogCode.Rejected,
                ),
            ):
                for _ in range(100):
                    button._choose_color()
            self.assertEqual(len(button.findChildren(real_color_dialog)), 100)
            self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            self.app.processEvents()
            self.assertEqual(button.findChildren(real_color_dialog), [])
        finally:
            dialog.deleteLater()

    def test_options_dialog_removes_inactive_unsupported_options(self):
        dialog = OptionsDialog(Config())
        texts = _preferences_support__visible_texts(dialog)
        self.assertIn(OPTIONS_LABEL_GRAYSCALE, texts)
        self.assertIn("Mouse unpressed angle", texts)
        self.assertNotIn("Digitizer unpressed angle", texts)
        self.assertNotIn("Digitizer pressed angle", texts)
        self.assertNotIn("Turn on all quick start dialogs", texts)
        self.assertNotIn("Turn on bid wizard", texts)
        self.assertNotIn("Prompt to refresh worksheet before closing project", texts)
        dialog.close()

    def test_options_dialog_apply_button_starts_disabled(self):
        dialog = OptionsDialog(Config())
        apply_button = _preferences_support__apply_button(dialog)
        self.assertIsNotNone(apply_button)
        self.assertFalse(apply_button.isEnabled())
        dialog.close()

    def test_options_dialog_contains_reset_all_settings_button(self):
        dialog = OptionsDialog(Config())
        reset_button = _preferences_support__reset_all_button(dialog)
        self.assertIsNotNone(reset_button)
        self.assertEqual(reset_button.text(), OPTIONS_LABEL_RESET_ALL_SETTINGS)
        dialog.close()

    def test_options_dialog_enables_apply_for_implemented_changes(self):
        dialog = OptionsDialog(Config())
        apply_button = _preferences_support__apply_button(dialog)
        dialog._disable_high_res_check.setChecked(True)
        self.assertTrue(apply_button.isEnabled())
        dialog._disable_high_res_check.setChecked(False)
        self.assertFalse(apply_button.isEnabled())
        dialog.close()

    def test_options_dialog_apply_success_commits_config_and_clears_pending(self):
        applied = []
        initial = Config(disable_high_resolution_images=False)
        dialog = OptionsDialog(initial, apply_callback=applied.append)
        apply_button = _preferences_support__apply_button(dialog)
        dialog._disable_high_res_check.setChecked(True)
        dialog._auto_zoom_spin.setValue(175)
        apply_button.click()
        self.assertEqual(
            applied,
            [
                Config(
                    disable_high_resolution_images=True,
                    default_auto_zoom_level=175,
                )
            ],
        )
        self.assertEqual(dialog.get_config(), applied[0])
        self.assertFalse(apply_button.isEnabled())
        dialog.accept()
        self.assertEqual(len(applied), 1)
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)

    def test_options_dialog_applied_config_becomes_new_pending_baseline(self):
        dialog = OptionsDialog(Config(), apply_callback=lambda _config: None)
        apply_button = _preferences_support__apply_button(dialog)
        dialog._disable_high_res_check.setChecked(True)
        apply_button.click()
        self.assertFalse(apply_button.isEnabled())
        dialog._disable_high_res_check.setChecked(False)
        self.assertTrue(apply_button.isEnabled())
        dialog.close()

    def test_options_dialog_ok_without_changes_accepts_without_callback(self):
        applied = []
        dialog = OptionsDialog(Config(), apply_callback=applied.append)
        dialog.accept()
        self.assertEqual(applied, [])
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)

    def test_options_dialog_reset_all_settings_restores_defaults(self):
        reset_callback = SingleCallRecorder(lambda: Config())
        dialog = OptionsDialog(
            Config(
                show_toolbar_text=False,
                display_mode_3d=Config.DISPLAY_MODE_SOLID,
                display_mode_2d=Config.DISPLAY_MODE_SOLID,
                grayscale_enabled=True,
                disable_high_resolution_images=True,
                default_auto_zoom_level=125,
                snap_to_right_angle_enabled=False,
            ),
            reset_callback=reset_callback,
        )
        dialog._disable_high_res_check.setChecked(False)
        self.assertTrue(_preferences_support__apply_button(dialog).isEnabled())
        with mock.patch(
            "ost_visualizer.presentation.dialogs.options.dialog.confirm",
            return_value=True,
        ) as confirm:
            _preferences_support__reset_all_button(dialog).click()
        reset_callback.assert_called_once(self, "Options reset click")
        confirm.assert_called_once()
        args = confirm.call_args.args
        self.assertIs(args[0], dialog)
        self.assertEqual(args[1], OPTIONS_LABEL_RESET_ALL_SETTINGS)
        self.assertEqual(
            args[2],
            (
                "This will reset all the program options and window settings\n"
                "to the original defaults.\n"
                "This cannot be undone. Do you want to reset these now?"
            ),
        )
        self.assertEqual(dialog.get_config(), Config())
        self.assertFalse(_preferences_support__apply_button(dialog).isEnabled())
        self.assertTrue(dialog._toolbar_text_check.isChecked())
        self.assertTrue(dialog._display_modes_sync_check.isChecked())
        self.assertTrue(dialog._display_mode_3d_original_radio.isChecked())
        self.assertTrue(dialog._display_mode_2d_original_radio.isChecked())
        self.assertFalse(dialog._grayscale_check.isChecked())
        self.assertTrue(dialog._snap_to_right_angle_check.isChecked())
        self.assertFalse(dialog._disable_high_res_check.isChecked())
        self.assertEqual(dialog._auto_zoom_spin.value(), Config.DEFAULT_AUTO_ZOOM_LEVEL)
        self.assertFalse(dialog._caption_master_check.isChecked())
        self.assertFalse(
            any(check.isChecked() for check in dialog._caption_checks.values())
        )
        dialog.close()

    def test_options_dialog_reset_all_settings_loads_callback_result(self):
        reset_result = Config(
            show_toolbar_text=False,
            default_auto_zoom_level=125,
            hotlink_target=Config.HOTLINK_TARGET_MAIN,
        )
        dialog = OptionsDialog(
            Config(grayscale_enabled=True), reset_callback=lambda: reset_result
        )
        dialog._disable_high_res_check.setChecked(True)
        with mock.patch(
            "ost_visualizer.presentation.dialogs.options.dialog.confirm",
            return_value=True,
        ):
            _preferences_support__reset_all_button(dialog).click()
        self.assertEqual(dialog.get_config(), reset_result)
        self.assertEqual(dialog._collect_widget_config(), reset_result)
        self.assertFalse(dialog._toolbar_text_check.isChecked())
        self.assertTrue(dialog._hotlink_main_radio.isChecked())
        self.assertEqual(dialog._auto_zoom_spin.value(), 125)
        self.assertFalse(dialog._grayscale_check.isChecked())
        self.assertFalse(dialog._disable_high_res_check.isChecked())
        self.assertFalse(_preferences_support__apply_button(dialog).isEnabled())
        dialog.close()

    def test_options_dialog_reset_all_settings_no_keeps_pending_changes(self):
        reset_callback = SingleCallRecorder(lambda: Config())
        initial = Config(show_toolbar_text=False)
        dialog = OptionsDialog(initial, reset_callback=reset_callback)
        dialog._disable_high_res_check.setChecked(True)
        self.assertTrue(_preferences_support__apply_button(dialog).isEnabled())
        with mock.patch(
            "ost_visualizer.presentation.dialogs.options.dialog.confirm",
            return_value=False,
        ) as confirm:
            _preferences_support__reset_all_button(dialog).click()
        confirm.assert_called_once()
        self.assertEqual(reset_callback.call_count, 0)
        self.assertEqual(dialog.get_config(), initial)
        self.assertTrue(_preferences_support__apply_button(dialog).isEnabled())
        self.assertTrue(dialog._disable_high_res_check.isChecked())
        dialog.close()

    def test_options_dialog_apply_failure_keeps_pending_changes(self):
        initial = Config(disable_high_resolution_images=False)
        dialog = OptionsDialog(
            initial,
            apply_callback=lambda _config: (_ for _ in ()).throw(
                OSError("disk unavailable")
            ),
        )
        dialog.show()
        try:
            dialog._disable_high_res_check.setChecked(True)
            with mock.patch(
                "ost_visualizer.presentation.dialogs.options.dialog.show_warning"
            ) as warning:
                _preferences_support__apply_button(dialog).click()
            self.assertTrue(dialog.isVisible())
            self.assertTrue(_preferences_support__apply_button(dialog).isEnabled())
            self.assertEqual(dialog.get_config(), initial)
            warning.assert_called_once_with(
                dialog,
                OPTIONS_DIALOG_TITLE,
                "Failed to apply settings. Reopen Options and try again.",
            )
        finally:
            dialog.close()

    def test_options_dialog_ok_failure_does_not_accept(self):
        dialog = OptionsDialog(
            Config(),
            apply_callback=lambda _config: (_ for _ in ()).throw(
                OSError("disk unavailable")
            ),
        )
        dialog._disable_high_res_check.setChecked(True)
        with mock.patch(
            "ost_visualizer.presentation.dialogs.options.dialog.show_warning"
        ) as warning:
            dialog.accept()
        warning.assert_called_once_with(
            dialog,
            OPTIONS_DIALOG_TITLE,
            "Failed to apply settings. Reopen Options and try again.",
        )
        self.assertNotEqual(
            dialog.result(),
            QtWidgets.QDialog.DialogCode.Accepted,
        )
        self.assertEqual(dialog.get_config(), Config())
        self.assertTrue(_preferences_support__apply_button(dialog).isEnabled())
        dialog.close()

    def test_options_dialog_uses_x_only_window_chrome(self):
        dialog = OptionsDialog(Config())
        flags = dialog.windowFlags()
        self.assertFalse(bool(flags & QtCore.Qt.WindowType.WindowMinimizeButtonHint))
        self.assertFalse(bool(flags & QtCore.Qt.WindowType.WindowMaximizeButtonHint))
        self.assertEqual(dialog.minimumWidth(), OPTIONS_WINDOW_WIDTH)
        self.assertEqual(dialog.maximumWidth(), OPTIONS_WINDOW_WIDTH)
        self.assertEqual(dialog.minimumHeight(), dialog.maximumHeight())
        dialog.close()

    def test_options_dialog_contains_options_export_and_mcp_setup_tabs(self):
        dialog = OptionsDialog(Config())
        self.assertEqual(dialog._tabs.count(), 5)
        self.assertEqual(dialog._tabs.tabText(0), OPTIONS_TAB_OPTIONS)
        self.assertEqual(dialog._tabs.tabText(1), OPTIONS_TAB_TAKEOFF_TOOLBAR)
        self.assertEqual(dialog._tabs.tabText(2), OPTIONS_TAB_FONTS_COLORS)
        self.assertEqual(dialog._tabs.tabText(3), OPTIONS_TAB_EXPORT)
        self.assertEqual(dialog._tabs.tabText(4), OPTIONS_TAB_MCP_SETUP)
        dialog.close()

    def test_export_tab_defaults_off_with_every_caption_unselected_and_disabled(self):
        dialog = OptionsDialog(Config())
        self.assertFalse(dialog._caption_master_check.isChecked())
        self.assertEqual(len(dialog._caption_checks), len(ANNOTATION_CAPTION_SPECS))
        for caption_id in ANNOTATION_CAPTION_ORDER:
            spec = ANNOTATION_CAPTION_SPECS[caption_id]
            check = dialog._caption_checks[caption_id]
            self.assertEqual(check.text(), spec.title)
            self.assertFalse(check.isChecked())
            self.assertFalse(check.isEnabled())
        dialog.close()

    def test_export_tab_callout_defaults_preserve_html_and_leave_pdf_disabled(self):
        dialog = OptionsDialog(Config())
        self.assertTrue(dialog._html_elevation_callouts_check.isChecked())
        self.assertFalse(dialog._pdf_elevation_callouts_check.isChecked())
        self.assertTrue(dialog._html_elevation_callouts_check.isEnabled())
        self.assertTrue(dialog._pdf_elevation_callouts_check.isEnabled())
        self.assertTrue(dialog._elevation_callout_condition_check.isChecked())
        self.assertTrue(dialog._elevation_callout_top_check.isChecked())
        self.assertTrue(dialog._elevation_callout_bottom_check.isChecked())
        self.assertTrue(dialog._elevation_callout_cubic_yards_check.isChecked())
        self.assertTrue(dialog._elevation_callout_condition_check.isEnabled())
        self.assertTrue(dialog._html_elevation_callout_color_button.isEnabled())
        self.assertFalse(dialog._pdf_elevation_callout_color_button.isEnabled())
        self.assertEqual(
            dialog._html_elevation_callout_color_button.color().name(), "#ff0000"
        )
        self.assertEqual(
            dialog._pdf_elevation_callout_color_button.color().name(), "#ff0000"
        )
        self.assertEqual(
            dialog._html_elevation_callouts_check.text(),
            "Include elevation callouts in HTML export",
        )
        self.assertEqual(
            dialog._pdf_elevation_callouts_check.text(),
            "Include elevation callouts in PDF export",
        )
        dialog.close()

    def test_export_callout_options_ok_and_reset_use_existing_lifecycle(self):
        saved = []
        dialog = OptionsDialog(
            Config(
                html_elevation_callouts_enabled=False,
                pdf_elevation_callouts_enabled=True,
            ),
            apply_callback=saved.append,
            reset_callback=Config,
        )
        with mock.patch(
            "ost_visualizer.presentation.dialogs.options.dialog.confirm",
            return_value=True,
        ):
            _preferences_support__reset_all_button(dialog).click()
        self.assertTrue(dialog._html_elevation_callouts_check.isChecked())
        self.assertFalse(dialog._pdf_elevation_callouts_check.isChecked())
        self.assertTrue(dialog._elevation_callout_condition_check.isEnabled())
        self.assertTrue(dialog._html_elevation_callout_color_button.isEnabled())
        self.assertFalse(dialog._pdf_elevation_callout_color_button.isEnabled())
        dialog._html_elevation_callouts_check.setChecked(False)
        dialog._pdf_elevation_callouts_check.setChecked(True)
        dialog._elevation_callout_cubic_yards_check.setChecked(False)
        dialog.accept()
        self.assertEqual(len(saved), 1)
        self.assertFalse(saved[0].html_elevation_callouts_enabled)
        self.assertTrue(saved[0].pdf_elevation_callouts_enabled)
        self.assertFalse(saved[0].elevation_callout_include_cubic_yards)
        dialog.close()

    def test_export_callout_content_preserved_while_both_exports_disabled(self):
        dialog = OptionsDialog(Config())
        dialog._elevation_callout_condition_check.setChecked(False)
        dialog._html_elevation_callouts_check.setChecked(False)
        dialog._pdf_elevation_callouts_check.setChecked(False)
        self.assertFalse(dialog._elevation_callout_condition_check.isEnabled())
        self.assertFalse(dialog._html_elevation_callout_color_button.isEnabled())
        self.assertFalse(dialog._pdf_elevation_callout_color_button.isEnabled())
        dialog._pdf_elevation_callouts_check.setChecked(True)
        self.assertTrue(dialog._elevation_callout_condition_check.isEnabled())
        self.assertFalse(dialog._elevation_callout_condition_check.isChecked())
        dialog.close()

    def test_export_caption_selections_survive_master_disable_and_reenable(self):
        dialog = OptionsDialog(Config())
        dialog._caption_master_check.setChecked(True)
        area_check = dialog._caption_checks[AnnotationCaptionId.AREA]
        volume_check = dialog._caption_checks[AnnotationCaptionId.VOLUME]
        area_check.setChecked(False)
        volume_check.setChecked(True)
        dialog._caption_master_check.setChecked(False)
        self.assertFalse(area_check.isEnabled())
        self.assertFalse(volume_check.isEnabled())
        dialog._caption_master_check.setChecked(True)
        self.assertFalse(area_check.isChecked())
        self.assertTrue(volume_check.isChecked())
        self.assertTrue(area_check.isEnabled())
        config = dialog._collect_widget_config()
        self.assertTrue(config.pdf_annotation_captions_enabled)
        self.assertNotIn("area", config.pdf_annotation_caption_ids)
        self.assertIn("volume", config.pdf_annotation_caption_ids)
        dialog.close()

    def test_mcp_setup_tab_contains_existing_setup_controls(self):
        helper_path = Path("C:/Tools/ostv-mcp.exe")
        dialog = OptionsDialog(Config(), mcp_helper_path=helper_path)
        tab = dialog._mcp_setup_tab
        texts = _preferences_support__visible_texts(dialog)
        self.assertIn("Connect AI tools", texts)
        self.assertIn("Claude Desktop or Cursor", texts)
        self.assertIn("Codex", texts)
        self.assertIn("Codex config.toml", texts)
        self.assertIn("Codex CLI command", texts)
        self.assertEqual(
            tab.claude_config_edit.toPlainText(),
            build_claude_desktop_config(helper_path),
        )
        self.assertEqual(
            tab.codex_config_edit.toPlainText(),
            build_codex_config_toml(helper_path),
        )
        self.assertEqual(
            tab.codex_command_edit.toPlainText(),
            build_codex_mcp_add_command(helper_path),
        )
        self.assertEqual(tab.copy_claude_button.text(), "Copy Setup JSON")
        self.assertEqual(tab.copy_codex_config_button.text(), "Copy Codex TOML")
        self.assertEqual(tab.copy_codex_button.text(), "Copy Setup Command")
        dialog.close()

    def test_mcp_setup_tab_copy_action_preserves_options_apply_state(self):
        helper_path = Path("C:/Tools/ostv-mcp.exe")
        dialog = OptionsDialog(Config(), mcp_helper_path=helper_path)
        apply_button = _preferences_support__apply_button(dialog)
        dialog._tabs.setCurrentWidget(dialog._mcp_setup_tab)
        dialog._mcp_setup_tab.copy_claude_button.click()
        self.assertEqual(
            QtWidgets.QApplication.clipboard().text(),
            build_claude_desktop_config(helper_path),
        )
        dialog._mcp_setup_tab.copy_codex_config_button.click()
        self.assertEqual(
            QtWidgets.QApplication.clipboard().text(),
            build_codex_config_toml(helper_path),
        )
        dialog._mcp_setup_tab.copy_codex_button.click()
        self.assertEqual(
            QtWidgets.QApplication.clipboard().text(),
            build_codex_mcp_add_command(helper_path),
        )
        self.assertIn("Copied to clipboard.", dialog._mcp_setup_tab.status_label.text())
        self.assertFalse(apply_button.isEnabled())
        dialog.close()

    def test_options_dialog_result_path_runs_lifecycle_cleanup(self):
        dialog = OptionsDialog(
            Config(),
            apply_callback=lambda _config: None,
            reset_callback=lambda: Config(),
        )
        mcp_tab = dialog._mcp_setup_tab
        cleanup_calls = []
        mcp_tab.cleanup = lambda: cleanup_calls.append("mcp")
        dialog.reject()
        self.assertEqual(cleanup_calls, ["mcp"])
        self.assertIsNone(dialog._tabs)
        self.assertIsNone(dialog._options_tab)
        self.assertIsNone(dialog._mcp_setup_tab)
        self.assertIsNone(dialog._apply_callback)
        self.assertIsNone(dialog._reset_callback)

    def test_options_dialog_accept_and_close_paths_run_lifecycle_cleanup(self):
        accepted = OptionsDialog(Config(), apply_callback=lambda _config: None)
        accepted_mcp_tab = accepted._mcp_setup_tab
        accepted.accept()
        self.assertEqual(accepted.result(), QtWidgets.QDialog.DialogCode.Accepted)
        self.assertIsNone(accepted._tabs)
        self.assertIsNone(accepted._mcp_setup_tab)
        self.assertIsNone(accepted._apply_callback)
        self.assertIsNone(accepted_mcp_tab.helper_path)
        self.assertIsNone(accepted_mcp_tab.status_label)
        closed = OptionsDialog(Config())
        closed_mcp_tab = closed._mcp_setup_tab
        closed.show()
        closed.close()
        self.assertIsNone(closed._tabs)
        self.assertIsNone(closed._mcp_setup_tab)
        self.assertIsNone(closed_mcp_tab.helper_path)

    def test_options_dialog_reset_failure_keeps_current_settings(self):
        initial = Config(show_toolbar_text=False)
        dialog = OptionsDialog(
            initial,
            reset_callback=lambda: (_ for _ in ()).throw(OSError("disk unavailable")),
        )
        dialog._disable_high_res_check.setChecked(True)
        with (
            mock.patch(
                "ost_visualizer.presentation.dialogs.options.dialog.confirm",
                return_value=True,
            ),
            mock.patch(
                "ost_visualizer.presentation.dialogs.options.dialog.show_warning"
            ) as warning,
        ):
            _preferences_support__reset_all_button(dialog).click()
        self.assertEqual(dialog.get_config(), initial)
        self.assertTrue(dialog._disable_high_res_check.isChecked())
        self.assertTrue(_preferences_support__apply_button(dialog).isEnabled())
        warning.assert_called_once_with(
            dialog,
            OPTIONS_LABEL_RESET_ALL_SETTINGS,
            "Failed to reset settings. Reopen Options and try again.",
        )
        dialog.close()

    def test_options_dialog_disabled_controls_do_not_enable_apply(self):
        dialog = OptionsDialog(Config())
        apply_button = _preferences_support__apply_button(dialog)
        deferred_labels = (
            *OPTIONS_DEFERRED_PREFERENCE_CHECKS,
            *OPTIONS_DEFERRED_CONFIRMATION_CHECKS,
        )
        deferred_checks = [
            check
            for check in dialog.findChildren(QtWidgets.QCheckBox)
            if check.text() in deferred_labels
        ]
        self.assertEqual(
            sorted(check.text() for check in deferred_checks), sorted(deferred_labels)
        )
        for check in deferred_checks:
            self.assertFalse(check.isEnabled())
            check.click()
            self.assertFalse(check.isChecked())
            check.setChecked(True)
            self.assertFalse(apply_button.isEnabled())
        self.assertEqual(dialog._collect_widget_config(), Config())
        dialog.close()


class OptionsDialogFontColorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        set_annotation_styles_by_tool({}, Config())
        self.app.processEvents()

    def test_options_tab_order_rows_and_stable_ids(self):
        dialog = OptionsDialog(Config())
        try:
            self.assertEqual(
                [dialog._tabs.tabText(i) for i in range(dialog._tabs.count())],
                ["Options", "Takeoff Toolbar", "Fonts/Colors", "Export", "MCP Setup"],
            )
            tab = dialog._fonts_colors_tab
            self.assertEqual(
                [tab.font_list.item(i).text() for i in range(tab.font_list.count())],
                ["Text", "Area Label", "Dimension Line", "Default Style Label"],
            )
            self.assertEqual(
                [tab.color_list.item(i).text() for i in range(tab.color_list.count())],
                [
                    "Text",
                    "Area Label",
                    "Default Style Label",
                    "Highlight",
                    "Hot Link",
                    "Inactive Objects",
                ],
            )
            all_labels = {
                *(label for _key, label in FONT_CATEGORIES),
                *(label for _key, label in COLOR_CATEGORIES),
            }
            self.assertTrue(
                {"Image Legend", "Legend", "Callout", "AutoName"}.isdisjoint(all_labels)
            )
            self.assertEqual(
                tab.font_list.item(0).data(QtCore.Qt.ItemDataRole.UserRole),
                FONT_CATEGORY_TEXT,
            )
            self.assertEqual(
                tab.color_list.item(5).data(QtCore.Qt.ItemDataRole.UserRole),
                COLOR_CATEGORY_INACTIVE_OBJECTS,
            )
        finally:
            dialog.close()

    def test_options_font_color_values_are_staged_through_apply(self):
        applied = []
        dialog = OptionsDialog(Config(), apply_callback=applied.append)
        real_color_dialog = QtWidgets.QColorDialog
        created_dialogs = []

        def create_color_dialog(color, parent):
            color_dialog = real_color_dialog(color, parent)
            created_dialogs.append(color_dialog)
            return color_dialog

        try:
            tab = dialog._fonts_colors_tab
            tab.color_list.setCurrentRow(5)
            with (
                mock.patch(
                    "ost_visualizer.presentation.dialogs.options.fonts_colors_tab."
                    "QtWidgets.QColorDialog",
                    side_effect=create_color_dialog,
                ),
                mock.patch.object(
                    real_color_dialog,
                    "exec",
                    return_value=QtWidgets.QDialog.DialogCode.Accepted,
                ),
                mock.patch.object(
                    real_color_dialog,
                    "currentColor",
                    return_value=QtGui.QColor("#123456"),
                ),
            ):
                tab.change_color_button.click()
            self.assertTrue(dialog._apply_button.isEnabled())
            self.assertEqual(applied, [])
            self.assertEqual(
                dialog._collect_widget_config().inactive_object_color, "#123456"
            )
            self.assertEqual(
                dialog.get_config().inactive_object_color,
                Config().inactive_object_color,
            )
            dialog._apply_button.click()
            self.assertEqual(len(applied), 1)
            self.assertEqual(applied[0].inactive_object_color, "#123456")
            self.assertEqual(
                replace(
                    applied[0], inactive_object_color=Config().inactive_object_color
                ),
                Config(),
            )
            self.assertIs(created_dialogs[0].parent(), tab.change_color_button)
            dialog.reject()
            self.assertEqual(len(applied), 1)
        finally:
            dialog.close()

    def test_options_font_values_are_staged_through_apply(self):
        applied = []
        dialog = OptionsDialog(Config(), apply_callback=applied.append)
        initial_font = Config().default_text_font

        def choose_font_size_48(font_dialog):
            size_item = font_dialog.size_list.findItems(
                "48", QtCore.Qt.MatchFlag.MatchFixedString
            )[0]
            font_dialog.size_list.setCurrentItem(size_item)
            font_dialog.ok_button.click()
            return font_dialog.result()

        try:
            tab = dialog._fonts_colors_tab
            tab.font_list.setCurrentRow(0)
            with mock.patch.object(FontDialog, "exec", choose_font_size_48):
                tab.change_font_button.click()
            self.assertTrue(dialog._apply_button.isEnabled())
            self.assertEqual(applied, [])
            self.assertEqual(dialog.get_config().default_text_font, initial_font)
            self.assertEqual(
                dialog._collect_widget_config().default_text_font,
                replace(initial_font, point_size=48),
            )
            dialog._apply_button.click()
            self.assertEqual(len(applied), 1)
            self.assertEqual(
                applied[0].default_text_font, replace(initial_font, point_size=48)
            )
            self.assertEqual(
                replace(applied[0], default_text_font=initial_font), Config()
            )
        finally:
            dialog.close()


_DIALOG_CONFIRM = "ost_visualizer.presentation.dialogs.options.dialog.confirm"


class ConditionElevationExportOptionDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def make(self, config=None, **kwargs):
        saved = []
        dialog = OptionsDialog(
            config or Config(), apply_callback=saved.append, **kwargs
        )
        self.addCleanup(lambda: delete(dialog) if isValid(dialog) else None)
        self.addCleanup(dialog.close)
        return dialog, saved

    def test_both_checkboxes_live_in_the_export_tab_and_default_off(self):
        dialog, _saved = self.make()
        export_tab = dialog._export_tab
        self.assertIs(
            dialog._ost_osp_drop_elevation_check,
            export_tab.ost_osp_drop_elevation_check,
        )
        self.assertIs(
            dialog._csv_drop_elevation_check, export_tab.csv_drop_elevation_check
        )
        for check in (
            dialog._ost_osp_drop_elevation_check,
            dialog._csv_drop_elevation_check,
        ):
            self.assertTrue(export_tab.isAncestorOf(check))
            self.assertFalse(check.isChecked())
            self.assertTrue(check.isEnabled())
        self.assertIn(
            OPTIONS_GROUP_CONDITION_NAMES,
            [group.title() for group in export_tab.findChildren(QtWidgets.QGroupBox)],
        )
        self.assertFalse(_preferences_support__apply_button(dialog).isEnabled())
        self.assertNotEqual(
            dialog._ost_osp_drop_elevation_check.text(),
            dialog._csv_drop_elevation_check.text(),
        )

    def test_the_option_labels_name_their_export(self):
        dialog, _saved = self.make()
        self.assertEqual(
            dialog._ost_osp_drop_elevation_check.text(),
            OPTIONS_LABEL_OST_OSP_DROP_ELEVATION,
        )
        self.assertEqual(
            dialog._csv_drop_elevation_check.text(), OPTIONS_LABEL_CSV_DROP_ELEVATION
        )
        self.assertIn("OST", OPTIONS_LABEL_OST_OSP_DROP_ELEVATION)
        self.assertIn("OSP", OPTIONS_LABEL_OST_OSP_DROP_ELEVATION)
        self.assertIn("Summary CSV", OPTIONS_LABEL_CSV_DROP_ELEVATION)

    def test_enabling_the_ost_osp_option_warns_and_confirming_keeps_it(self):
        dialog, saved = self.make()
        with mock.patch(_DIALOG_CONFIRM, return_value=True) as confirm:
            dialog._ost_osp_drop_elevation_check.click()
        self.assertEqual(confirm.call_count, 1)
        args = confirm.call_args.args
        self.assertIs(args[0], dialog)
        self.assertEqual(args[1], OPTIONS_WARNING_TITLE_DROP_ELEVATION)
        self.assertEqual(args[2], OPTIONS_WARNING_OST_OSP_DROP_ELEVATION)
        self.assertTrue(dialog._ost_osp_drop_elevation_check.isChecked())
        self.assertFalse(dialog._csv_drop_elevation_check.isChecked())
        self.assertTrue(_preferences_support__apply_button(dialog).isEnabled())
        dialog.accept()
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0].ost_osp_export_drop_condition_elevation)
        self.assertFalse(saved[0].csv_export_drop_condition_elevation)

    def test_cancelling_the_ost_osp_warning_leaves_the_option_off(self):
        dialog, saved = self.make()
        with mock.patch(_DIALOG_CONFIRM, return_value=False) as confirm:
            dialog._ost_osp_drop_elevation_check.click()
        self.assertEqual(confirm.call_count, 1)
        self.assertFalse(dialog._ost_osp_drop_elevation_check.isChecked())
        self.assertFalse(_preferences_support__apply_button(dialog).isEnabled())
        dialog.accept()
        self.assertEqual(saved, [])

    def test_enabling_the_csv_option_warns_and_confirm_or_cancel_decide(self):
        dialog, saved = self.make()
        with mock.patch(_DIALOG_CONFIRM, return_value=False) as confirm:
            dialog._csv_drop_elevation_check.click()
        self.assertEqual(confirm.call_args.args[2], OPTIONS_WARNING_CSV_DROP_ELEVATION)
        self.assertFalse(dialog._csv_drop_elevation_check.isChecked())
        with mock.patch(_DIALOG_CONFIRM, return_value=True) as confirm:
            dialog._csv_drop_elevation_check.click()
        self.assertEqual(confirm.call_count, 1)
        self.assertTrue(dialog._csv_drop_elevation_check.isChecked())
        dialog.accept()
        self.assertTrue(saved[0].csv_export_drop_condition_elevation)
        self.assertFalse(saved[0].ost_osp_export_drop_condition_elevation)

    def test_the_two_warnings_explain_their_own_option_and_the_unchanged_exports(self):
        ost = OPTIONS_WARNING_OST_OSP_DROP_ELEVATION
        csv = OPTIONS_WARNING_CSV_DROP_ELEVATION
        self.assertIn("lose all elevation data", ost)
        self.assertIn("without its elevation", ost)
        self.assertIn("On-Screen Takeoff", ost)
        self.assertIn("expect CSV data without elevations", csv)
        for message in (ost, csv):
            self.assertIn("3D", message)
            self.assertIn("HTML", message)
            self.assertIn("PDF", message)
            self.assertIn("unchanged", message)

    def test_loading_a_saved_enabled_option_does_not_warn(self):
        with mock.patch(_DIALOG_CONFIRM) as confirm:
            dialog, _saved = self.make(
                Config(
                    ost_osp_export_drop_condition_elevation=True,
                    csv_export_drop_condition_elevation=True,
                )
            )
            self.app.processEvents()
        confirm.assert_not_called()
        self.assertTrue(dialog._ost_osp_drop_elevation_check.isChecked())
        self.assertTrue(dialog._csv_drop_elevation_check.isChecked())
        self.assertFalse(_preferences_support__apply_button(dialog).isEnabled())

    def test_disabling_an_enabled_option_does_not_warn(self):
        dialog, saved = self.make(
            Config(
                ost_osp_export_drop_condition_elevation=True,
                csv_export_drop_condition_elevation=True,
            )
        )
        with mock.patch(_DIALOG_CONFIRM) as confirm:
            dialog._ost_osp_drop_elevation_check.click()
            dialog._csv_drop_elevation_check.click()
        confirm.assert_not_called()
        self.assertFalse(dialog._ost_osp_drop_elevation_check.isChecked())
        self.assertFalse(dialog._csv_drop_elevation_check.isChecked())
        dialog.accept()
        self.assertFalse(saved[0].ost_osp_export_drop_condition_elevation)
        self.assertFalse(saved[0].csv_export_drop_condition_elevation)

    def test_programmatic_changes_never_warn(self):
        dialog, _saved = self.make()
        with mock.patch(_DIALOG_CONFIRM) as confirm:
            dialog._ost_osp_drop_elevation_check.setChecked(True)
            dialog._csv_drop_elevation_check.setChecked(True)
        confirm.assert_not_called()

    def test_reset_all_settings_turns_both_off_without_a_second_warning(self):
        dialog, _saved = self.make(
            Config(
                ost_osp_export_drop_condition_elevation=True,
                csv_export_drop_condition_elevation=True,
            ),
            reset_callback=Config,
        )
        with mock.patch(_DIALOG_CONFIRM, return_value=True) as confirm:
            _preferences_support__reset_all_button(dialog).click()
        self.assertEqual(confirm.call_count, 1)
        self.assertEqual(confirm.call_args.args[1], OPTIONS_LABEL_RESET_ALL_SETTINGS)
        self.assertFalse(dialog._ost_osp_drop_elevation_check.isChecked())
        self.assertFalse(dialog._csv_drop_elevation_check.isChecked())

    def test_cancelling_the_dialog_after_confirming_discards_the_option(self):
        dialog, saved = self.make()
        with mock.patch(_DIALOG_CONFIRM, return_value=True):
            dialog._ost_osp_drop_elevation_check.click()
        dialog.reject()
        self.assertEqual(saved, [])

    def test_the_two_options_change_independently_in_the_collected_config(self):
        dialog, _saved = self.make()
        with mock.patch(_DIALOG_CONFIRM, return_value=True):
            dialog._csv_drop_elevation_check.click()
        collected = dialog._collect_widget_config()
        self.assertTrue(collected.csv_export_drop_condition_elevation)
        self.assertFalse(collected.ost_osp_export_drop_condition_elevation)
        with mock.patch(_DIALOG_CONFIRM, return_value=True):
            dialog._ost_osp_drop_elevation_check.click()
        collected = dialog._collect_widget_config()
        self.assertTrue(collected.ost_osp_export_drop_condition_elevation)
        self.assertTrue(collected.csv_export_drop_condition_elevation)

    def press_space(self, check):
        QtTest.QTest.keyClick(check, QtCore.Qt.Key.Key_Space)
        self.app.processEvents()

    def test_keyboard_activation_warns_exactly_like_a_click(self):
        for name, message in (
            ("_ost_osp_drop_elevation_check", OPTIONS_WARNING_OST_OSP_DROP_ELEVATION),
            ("_csv_drop_elevation_check", OPTIONS_WARNING_CSV_DROP_ELEVATION),
        ):
            with self.subTest(check=name):
                dialog, saved = self.make()
                dialog.show()
                check = getattr(dialog, name)
                with mock.patch(_DIALOG_CONFIRM, return_value=False) as confirm:
                    self.press_space(check)
                self.assertEqual(confirm.call_count, 1)
                self.assertEqual(confirm.call_args.args[2], message)
                self.assertFalse(check.isChecked())
                with mock.patch(_DIALOG_CONFIRM, return_value=True) as confirm:
                    self.press_space(check)
                self.assertEqual(confirm.call_count, 1)
                self.assertTrue(check.isChecked())
                with mock.patch(_DIALOG_CONFIRM) as confirm:
                    self.press_space(check)
                confirm.assert_not_called()
                self.assertFalse(check.isChecked())
                self.assertEqual(saved, [])

    def test_a_cancelled_warning_leaves_no_pending_changes_for_either_option(self):
        for name in ("_ost_osp_drop_elevation_check", "_csv_drop_elevation_check"):
            with self.subTest(check=name):
                dialog, saved = self.make()
                with mock.patch(_DIALOG_CONFIRM, return_value=False):
                    getattr(dialog, name).click()
                self.assertFalse(dialog._has_pending_changes())
                self.assertEqual(
                    dialog._collect_widget_config(), dialog._applied_config
                )
                self.assertFalse(_preferences_support__apply_button(dialog).isEnabled())
                dialog.accept()
                self.assertEqual(saved, [])

    def test_the_checkboxes_are_labelled_focusable_and_follow_the_callout_controls(
        self,
    ):
        dialog, _saved = self.make()
        export_tab = dialog._export_tab
        order = [
            widget
            for widget in export_tab.findChildren(QtWidgets.QCheckBox)
            if widget.focusPolicy() != QtCore.Qt.FocusPolicy.NoFocus
        ]
        ost = dialog._ost_osp_drop_elevation_check
        csv = dialog._csv_drop_elevation_check
        self.assertEqual(order[-2:], [ost, csv])
        self.assertLess(
            order.index(dialog._pdf_elevation_callouts_check), order.index(ost)
        )
        for check in (ost, csv):
            self.assertTrue(check.text())
            self.assertNotEqual(check.focusPolicy(), QtCore.Qt.FocusPolicy.NoFocus)
            self.assertEqual(check.accessibleName(), "")
            self.assertTrue(check.text().startswith("Drop elevations"))


class ExportTabSideBySideLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def make_shown_tab(self):
        dialog = OptionsDialog(Config())
        self.addCleanup(lambda: delete(dialog) if isValid(dialog) else None)
        self.addCleanup(dialog.close)
        dialog._tabs.setCurrentWidget(dialog._export_tab)
        dialog.show()
        self.app.processEvents()
        return dialog, dialog._export_tab

    def groups_by_title(self, export_tab):
        return {
            group.title(): group
            for group in export_tab.findChildren(QtWidgets.QGroupBox)
        }

    def assert_nothing_clipped(self, export_tab):
        for group in export_tab.findChildren(QtWidgets.QGroupBox):
            self.assertGreaterEqual(
                group.width(), group.minimumSizeHint().width(), group.title()
            )
            self.assertGreaterEqual(
                group.height(), group.minimumSizeHint().height(), group.title()
            )
            self.assertTrue(export_tab.rect().contains(group.geometry()), group.title())
        for widget in (
            *export_tab.findChildren(QtWidgets.QCheckBox),
            *export_tab.findChildren(QtWidgets.QLabel),
            *export_tab.findChildren(QtWidgets.QAbstractButton),
        ):
            group = next(
                parent
                for parent in iter_parents(widget)
                if isinstance(parent, QtWidgets.QGroupBox)
            )
            top_left = widget.mapTo(group, QtCore.QPoint(0, 0))
            visible = QtCore.QRect(top_left, widget.size())
            self.assertTrue(
                group.rect().contains(visible),
                widget.text() if hasattr(widget, "text") else widget,
            )
            if isinstance(widget, (QtWidgets.QCheckBox, QtWidgets.QLabel)):
                self.assertGreaterEqual(
                    widget.width(), widget.minimumSizeHint().width(), repr(widget)
                )
                self.assertGreaterEqual(
                    widget.width(), widget.sizeHint().width(), repr(widget)
                )

    def test_captions_and_callouts_boxes_share_one_top_aligned_row(self):
        _dialog, export_tab = self.make_shown_tab()
        groups = self.groups_by_title(export_tab)
        captions = groups[OPTIONS_GROUP_PDF_ANNOTATION_CAPTIONS]
        callouts = groups[OPTIONS_GROUP_ELEVATION_CALLOUTS]
        self.assertEqual(captions.geometry().y(), callouts.geometry().y())
        self.assertLess(captions.geometry().right(), callouts.geometry().left())
        self.assertLessEqual(
            abs(captions.width() - callouts.width()),
            1,
        )
        gap = callouts.geometry().left() - captions.geometry().right() - 1
        self.assertEqual(gap, RELAXED_SPACING)

    def test_condition_names_box_sits_below_and_spans_the_row(self):
        _dialog, export_tab = self.make_shown_tab()
        groups = self.groups_by_title(export_tab)
        captions = groups[OPTIONS_GROUP_PDF_ANNOTATION_CAPTIONS]
        callouts = groups[OPTIONS_GROUP_ELEVATION_CALLOUTS]
        names = groups[OPTIONS_GROUP_CONDITION_NAMES]
        self.assertGreater(
            names.geometry().top(),
            max(captions.geometry().bottom(), callouts.geometry().bottom()),
        )
        self.assertEqual(names.geometry().left(), captions.geometry().left())
        self.assertEqual(names.geometry().right(), callouts.geometry().right())
        self.assertEqual(
            names.width(), captions.width() + RELAXED_SPACING + callouts.width()
        )
        self.assertEqual(
            names.geometry().top()
            - max(captions.geometry().bottom(), callouts.geometry().bottom())
            - 1,
            RELAXED_SPACING,
        )

    def test_nothing_is_clipped_at_the_dialog_size_and_at_larger_sizes(self):
        dialog, export_tab = self.make_shown_tab()
        self.assertGreaterEqual(
            export_tab.width(), export_tab.minimumSizeHint().width()
        )
        self.assert_nothing_clipped(export_tab)
        dialog.setMinimumSize(0, 0)
        dialog.setMaximumSize(QtCore.QSize(16777215, 16777215))
        dialog.resize(1300, 900)
        self.app.processEvents()
        self.assert_nothing_clipped(export_tab)

    def test_export_tab_fits_at_its_own_minimum_size_and_when_widened(self):
        from ost_visualizer.presentation.dialogs.options.export_tab import ExportTab

        export_tab = ExportTab()
        self.addCleanup(lambda: delete(export_tab) if isValid(export_tab) else None)
        export_tab.show()
        export_tab.resize(export_tab.minimumSizeHint())
        self.app.processEvents()
        self.assertLessEqual(
            export_tab.minimumSizeHint().width(), OPTIONS_WINDOW_WIDTH - 2 * 9
        )
        self.assert_nothing_clipped(export_tab)
        export_tab.resize(1400, 900)
        self.app.processEvents()
        self.assert_nothing_clipped(export_tab)

    def test_tab_order_still_walks_the_controls_in_creation_order(self):
        dialog, export_tab = self.make_shown_tab()
        expected = [
            export_tab.captions_enabled_check,
            *(export_tab.caption_checks[cid] for cid in ANNOTATION_CAPTION_ORDER),
            export_tab.html_elevation_callouts_check,
            export_tab.pdf_elevation_callouts_check,
            export_tab.elevation_callout_condition_check,
            export_tab.elevation_callout_top_check,
            export_tab.elevation_callout_bottom_check,
            export_tab.elevation_callout_cubic_yards_check,
            export_tab.html_elevation_callout_color_button,
            export_tab.pdf_elevation_callout_color_button,
            export_tab.ost_osp_drop_elevation_check,
            export_tab.csv_drop_elevation_check,
        ]
        chain = []
        widget = export_tab.captions_enabled_check
        while True:
            if export_tab.isAncestorOf(widget) and (
                widget.focusPolicy() != QtCore.Qt.FocusPolicy.NoFocus
            ):
                chain.append(widget)
            widget = widget.nextInFocusChain()
            if widget is export_tab.captions_enabled_check:
                break
        self.assertEqual(chain, expected)

    def test_group_boxes_keep_their_internal_spacing_and_the_tab_spacing(self):
        _dialog, export_tab = self.make_shown_tab()
        self.assertEqual(export_tab.layout().spacing(), RELAXED_SPACING)
        self.assertEqual(
            [
                group.layout().spacing()
                for group in export_tab.findChildren(QtWidgets.QGroupBox)
            ],
            [COMPACT_SPACING] * 3,
        )


def iter_parents(widget):
    parent = widget.parentWidget()
    while parent is not None:
        yield parent
        parent = parent.parentWidget()
