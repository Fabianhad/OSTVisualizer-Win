import os
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.snap_preferences_dto import SnapPreferencesDto
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.config_service import ConfigService
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.annotation_caption import (
    ANNOTATION_CAPTION_ORDER,
    DEFAULT_ANNOTATION_CAPTION_IDS,
    AnnotationCaptionId,
)
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.presentation.controllers.menu_controller import MenuController
from ost_visualizer.presentation.dialogs.options.dialog import OptionsDialog
from PySide6 import QtCore, QtGui, QtWidgets
from tests.helpers.call_recorder import SingleCallRecorder
from tests.presentation.dialogs.options.preference_support import (
    FakeConfigRepository as _preferences_support_FakeConfigRepository,
    FakeEventBus as _preferences_support_FakeEventBus,
    SNAP_PREF_UPDATE as _preferences_support_SNAP_PREF_UPDATE,
    _app as _preferences_support__app,
    _app_config_event as _preferences_support__app_config_event,
    _apply_button as _preferences_support__apply_button,
    _assert_snap_pref_update_applied as _preferences_support__assert_snap_pref_update_applied,
)


class SaveWorkflowsPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_options_dialog_apply_saves_and_keeps_dialog_open(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        apply_callback = SingleCallRecorder(service.update_app_options)
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=apply_callback,
        )
        dialog.show()
        apply_button = _preferences_support__apply_button(dialog)
        dialog._disable_high_res_check.setChecked(True)
        apply_button.click()
        apply_callback.assert_called_once(self, "Options Apply click")
        self.assertTrue(dialog.isVisible())
        self.assertFalse(apply_button.isEnabled())
        self.assertTrue(aggregate.disable_high_resolution_images)
        self.assertEqual(
            event_bus.events,
            [
                _preferences_support__app_config_event(
                    {"disable_high_resolution_images": True}
                )
            ],
        )
        dialog.close()

    def test_options_dialog_apply_noop_does_not_publish(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=service.update_app_options,
        )
        dialog._apply_pending_changes()
        self.assertEqual(event_bus.events, [])
        self.assertFalse(_preferences_support__apply_button(dialog).isEnabled())
        dialog.close()

    def test_export_callout_options_apply_independently_and_cancel_is_nonmutating(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        service = ConfigService(aggregate, _preferences_support_FakeEventBus())
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=service.update_app_options,
        )
        dialog._html_elevation_callouts_check.setChecked(False)
        dialog._pdf_elevation_callouts_check.setChecked(True)
        dialog._elevation_callout_top_check.setChecked(False)
        dialog._html_elevation_callout_color_button.set_color(QtGui.QColor("#123456"))
        dialog._pdf_elevation_callout_color_button.set_color(QtGui.QColor("#abcdef"))
        _preferences_support__apply_button(dialog).click()
        self.assertFalse(aggregate.snapshot().html_elevation_callouts_enabled)
        self.assertTrue(aggregate.snapshot().pdf_elevation_callouts_enabled)
        self.assertFalse(aggregate.snapshot().elevation_callout_include_top)
        self.assertEqual(aggregate.snapshot().html_elevation_callout_color, "#123456")
        self.assertEqual(aggregate.snapshot().pdf_elevation_callout_color, "#abcdef")
        dialog._html_elevation_callouts_check.setChecked(True)
        dialog._pdf_elevation_callouts_check.setChecked(False)
        dialog._elevation_callout_top_check.setChecked(True)
        dialog.reject()
        self.assertFalse(aggregate.snapshot().html_elevation_callouts_enabled)
        self.assertTrue(aggregate.snapshot().pdf_elevation_callouts_enabled)
        self.assertFalse(aggregate.snapshot().elevation_callout_include_top)
        dialog.close()

    def test_export_caption_apply_saves_and_cancel_keeps_persisted_config(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        service = ConfigService(aggregate, _preferences_support_FakeEventBus())
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=service.update_app_options,
        )
        dialog._caption_master_check.setChecked(True)
        dialog._caption_checks[AnnotationCaptionId.AREA].setChecked(True)
        dialog._caption_checks[AnnotationCaptionId.VOLUME].setChecked(True)
        dialog._caption_checks[AnnotationCaptionId.VOLUME].setChecked(False)
        _preferences_support__apply_button(dialog).click()
        config = aggregate.snapshot()
        self.assertTrue(config.pdf_annotation_captions_enabled)
        self.assertNotIn("volume", config.pdf_annotation_caption_ids)
        dialog._caption_checks[AnnotationCaptionId.AREA].setChecked(False)
        dialog.reject()
        self.assertIn("area", aggregate.snapshot().pdf_annotation_caption_ids)
        dialog.close()

    def test_menu_grayscale_toggle_uses_general_app_config_update_path(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        controller = MenuController.__new__(MenuController)
        controller.config_service = service
        result = controller._toggle_takeoff_grayscale()
        self.assertTrue(result)
        self.assertTrue(aggregate.grayscale_enabled)
        self.assertEqual(
            event_bus.events,
            [_preferences_support__app_config_event({"grayscale_enabled": True})],
        )

    def test_options_dialog_loads_and_saves_main_hotlink_target(self):
        dialog = OptionsDialog(Config(hotlink_target="main"))
        self.assertTrue(dialog._hotlink_main_radio.isChecked())
        self.assertTrue(dialog._hotlink_main_radio.isEnabled())
        dialog.close()
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=service.update_app_options,
        )
        dialog._hotlink_main_radio.setChecked(True)
        _preferences_support__apply_button(dialog).click()
        self.assertEqual(aggregate.hotlink_target, "main")
        self.assertEqual(
            event_bus.events,
            [_preferences_support__app_config_event({"hotlink_target": "main"})],
        )
        dialog.close()

    def test_menu_display_modes_use_general_app_config_update_path(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        controller = MenuController.__new__(MenuController)
        controller.config_service = service
        controller._set_takeoff_display_mode_3d(Config.DISPLAY_MODE_TRANSPARENT)
        self.assertEqual(aggregate.display_mode_3d, Config.DISPLAY_MODE_TRANSPARENT)
        self.assertEqual(aggregate.display_mode_2d, Config.DISPLAY_MODE_TRANSPARENT)
        self.assertEqual(
            event_bus.events,
            [
                _preferences_support__app_config_event(
                    {
                        "display_mode_3d": Config.DISPLAY_MODE_TRANSPARENT,
                        "display_mode_2d": Config.DISPLAY_MODE_TRANSPARENT,
                    }
                )
            ],
        )

    def test_menu_options_reset_uses_config_service_and_resets_workspace(self):
        repo = _preferences_support_FakeConfigRepository(
            Config(
                show_toolbar_text=False,
                disable_high_resolution_images=True,
            )
        )
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        workspace_resets = []
        controller = MenuController.__new__(MenuController)
        controller.config_service = service
        controller.window = SimpleNamespace(
            reset_workspace_state_to_defaults=lambda: workspace_resets.append("reset")
        )
        result = controller._reset_all_settings()
        self.assertEqual(result, Config())
        self.assertEqual(service.get_config_snapshot(), Config())
        self.assertEqual(workspace_resets, ["reset"])
        self.assertEqual(
            event_bus.events,
            [
                _preferences_support__app_config_event(
                    {
                        "show_toolbar_text": True,
                        "disable_high_resolution_images": False,
                    }
                )
            ],
        )

    def test_options_dialog_ok_saves_implemented_preferences(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        dialog = OptionsDialog(service.get_config_snapshot())
        dialog._display_mode_3d_original_radio.setChecked(True)
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
        dialog._crosshair_color_button.set_color(QtGui.QColor("#123456"))
        dialog._crosshair_line_thickness_spin.setValue(4)
        dialog._allow_add_page_from_takeoff_check.setChecked(True)
        dialog._mouse_unpressed_snap_angle_combo.setCurrentIndex(
            dialog._mouse_unpressed_snap_angle_combo.findData(30)
        )
        dialog._mouse_pressed_snap_angle_combo.setCurrentIndex(
            dialog._mouse_pressed_snap_angle_combo.findData(45)
        )
        dialog._snap_to_grid_check.setChecked(
            _preferences_support_SNAP_PREF_UPDATE["snap_to_grid_enabled"]
        )
        dialog._snap_to_grid_threshold_spin.setValue(
            _preferences_support_SNAP_PREF_UPDATE["snap_to_grid_threshold_px"]
        )
        dialog._snap_to_pdf_lines_check.setChecked(
            _preferences_support_SNAP_PREF_UPDATE["snap_to_pdf_lines_enabled"]
        )
        dialog._snap_to_pdf_lines_threshold_spin.setValue(
            _preferences_support_SNAP_PREF_UPDATE["snap_to_pdf_lines_threshold_px"]
        )
        dialog._snap_to_takeoffs_check.setChecked(
            _preferences_support_SNAP_PREF_UPDATE["snap_to_takeoffs_enabled"]
        )
        dialog._snap_to_takeoffs_threshold_spin.setValue(
            _preferences_support_SNAP_PREF_UPDATE["snap_to_takeoffs_threshold_px"]
        )
        dialog._snap_to_right_angle_check.setChecked(
            _preferences_support_SNAP_PREF_UPDATE["snap_to_right_angle_enabled"]
        )
        dialog._snap_to_right_angle_threshold_spin.setValue(
            _preferences_support_SNAP_PREF_UPDATE["snap_to_right_angle_threshold_px"]
        )
        dialog._auto_zoom_spin.setValue(125)
        dialog.accept()
        changed = service.update_app_options(dialog.get_config())
        self.assertIn("roping_selection_method", changed)
        self.assertEqual(aggregate.display_mode_3d, Config.DISPLAY_MODE_ORIGINAL)
        self.assertEqual(aggregate.display_mode_2d, Config.DISPLAY_MODE_ORIGINAL)
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
        _preferences_support__assert_snap_pref_update_applied(self, aggregate)
        self.assertEqual(aggregate.default_auto_zoom_level, 125)
        self.assertEqual(event_bus.events[0][0], AppEvents.APP_CONFIG_UPDATED)
        dialog.close()

    def test_options_dialog_ok_callback_saves_and_closes(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        apply_callback = SingleCallRecorder(service.update_app_options)
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=apply_callback,
        )
        finished_results = []
        dialog.finished.connect(finished_results.append)
        dialog._disable_high_res_check.setChecked(True)
        button_box = dialog.findChild(QtWidgets.QDialogButtonBox)
        button_box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).click()
        apply_callback.assert_called_once(self, "Options OK click")
        self.assertEqual(
            dialog.result(),
            QtWidgets.QDialog.DialogCode.Accepted,
        )
        self.assertEqual(finished_results, [QtWidgets.QDialog.DialogCode.Accepted])
        self.assertTrue(aggregate.disable_high_resolution_images)
        self.assertEqual(
            event_bus.events,
            [
                _preferences_support__app_config_event(
                    {"disable_high_resolution_images": True}
                )
            ],
        )

    def test_options_dialog_cancel_does_not_save_changes(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        service = ConfigService(aggregate, _preferences_support_FakeEventBus())
        dialog = OptionsDialog(service.get_config_snapshot())
        dialog._display_mode_3d_transparent_radio.setChecked(True)
        dialog._grayscale_check.setChecked(True)
        dialog._roping_inclusive_radio.setChecked(True)
        dialog.reject()
        self.assertEqual(aggregate.display_mode_3d, Config.DISPLAY_MODE_ORIGINAL)
        self.assertEqual(aggregate.display_mode_2d, Config.DISPLAY_MODE_ORIGINAL)
        self.assertFalse(aggregate.grayscale_enabled)
        self.assertEqual(aggregate.roping_selection_method, "touching")
        self.assertEqual(repo.saved, [])
        dialog.close()

    def test_options_dialog_apply_then_cancel_keeps_only_applied_changes(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        service = ConfigService(aggregate, _preferences_support_FakeEventBus())
        dialog = OptionsDialog(
            service.get_config_snapshot(),
            apply_callback=service.update_app_options,
        )
        dialog._page_index_check.setChecked(True)
        _preferences_support__apply_button(dialog).click()
        dialog._grayscale_check.setChecked(True)
        dialog.reject()
        self.assertTrue(aggregate.display_page_index_with_sheet_name)
        self.assertFalse(aggregate.grayscale_enabled)
        dialog.close()

    def test_options_dialog_color_settings_publish_same_app_config_payload(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        dialog = OptionsDialog(service.get_config_snapshot())
        dialog._display_mode_3d_transparent_radio.setChecked(True)
        dialog._grayscale_check.setChecked(True)
        dialog.accept()
        changed = service.update_app_options(dialog.get_config())
        self.assertEqual(
            changed,
            ["display_mode_3d", "display_mode_2d", "grayscale_enabled"],
        )
        self.assertEqual(
            event_bus.events,
            [
                _preferences_support__app_config_event(
                    {
                        "display_mode_3d": Config.DISPLAY_MODE_TRANSPARENT,
                        "display_mode_2d": Config.DISPLAY_MODE_TRANSPARENT,
                        "grayscale_enabled": True,
                    }
                )
            ],
        )
        dialog.close()
