from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional
from PySide6 import QtWidgets
from ....application.dtos.annotation_caption_dto import ANNOTATION_CAPTION_SPECS
from ....domain.entities.annotation_caption import ANNOTATION_CAPTION_ORDER
from ....domain.entities.config import Config
from ...config import (
    OPTIONS_DIALOG_TITLE,
    OPTIONS_LABEL_RESET_ALL_SETTINGS,
    OPTIONS_TAB_EXPORT,
    OPTIONS_TAB_MCP_SETUP,
    OPTIONS_TAB_OPTIONS,
    OPTIONS_WINDOW_HEIGHT,
    OPTIONS_WINDOW_WIDTH,
)
from ...utils.messagebox import confirm
from ...utils.windows import remove_minimize_maximize
from .components import ExportTab, McpSetupTab, OptionsTab


class OptionsDialog(QtWidgets.QDialog):
    _RESET_ALL_SETTINGS_MESSAGE = (
        "This will reset all the program options and window settings\n"
        "to the original defaults.\n"
        "This cannot be undone. Do you want to reset these now?"
    )

    def __init__(
        self,
        config: Config,
        parent=None,
        apply_callback: Optional[Callable[[Config], object]] = None,
        reset_callback: Optional[Callable[[], Config]] = None,
        mcp_helper_path: Optional[Path] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(OPTIONS_DIALOG_TITLE)
        self.setFixedSize(OPTIONS_WINDOW_WIDTH, OPTIONS_WINDOW_HEIGHT)
        remove_minimize_maximize(self)
        self._applied_config = replace(config)
        self._config = replace(config)
        self._apply_callback = apply_callback
        self._reset_callback = reset_callback
        self._apply_button: Optional[QtWidgets.QPushButton] = None
        self._reset_all_button: Optional[QtWidgets.QPushButton] = None
        self._tabs: Optional[QtWidgets.QTabWidget] = None
        self._options_tab: Optional[OptionsTab] = None
        self._export_tab: Optional[ExportTab] = None
        self._mcp_setup_tab: Optional[McpSetupTab] = None
        self._mcp_helper_path = Path(mcp_helper_path) if mcp_helper_path else None
        self._cleaned_up = False
        self._build_ui()
        self._load_config()
        self._connect_change_signals()
        self._update_apply_enabled()

    def get_config(self) -> Config:
        return replace(self._config)

    def accept(self) -> None:
        self._apply_pending_changes()
        super().accept()

    def _build_ui(self) -> None:
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(main_layout.contentsMargins().bottom())
        self._tabs = QtWidgets.QTabWidget(self)
        self._options_tab = OptionsTab(self._tabs)
        self._bind_options_tab_widgets()
        self._tabs.addTab(self._options_tab, OPTIONS_TAB_OPTIONS)
        self._export_tab = ExportTab(self._tabs)
        self._caption_master_check = self._export_tab.captions_enabled_check
        self._caption_checks = self._export_tab.caption_checks
        self._html_elevation_callouts_check = (
            self._export_tab.html_elevation_callouts_check
        )
        self._pdf_elevation_callouts_check = (
            self._export_tab.pdf_elevation_callouts_check
        )
        self._tabs.addTab(self._export_tab, OPTIONS_TAB_EXPORT)
        self._mcp_setup_tab = McpSetupTab(
            self._tabs,
            helper_path=self._mcp_helper_path,
        )
        self._tabs.addTab(self._mcp_setup_tab, OPTIONS_TAB_MCP_SETUP)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        main_layout.addWidget(self._tabs)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self._apply_button = buttons.addButton(
            QtWidgets.QDialogButtonBox.StandardButton.Apply
        )
        self._apply_button.setEnabled(False)
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._apply_button.clicked.connect(self._apply_pending_changes)
        button_row = QtWidgets.QHBoxLayout()
        self._reset_all_button = QtWidgets.QPushButton(
            OPTIONS_LABEL_RESET_ALL_SETTINGS,
            self,
        )
        self._reset_all_button.clicked.connect(self._reset_all_settings)
        button_row.addWidget(self._reset_all_button)
        button_row.addStretch(1)
        button_row.addWidget(buttons)
        main_layout.addLayout(button_row)

    def _bind_options_tab_widgets(self) -> None:
        tab = self._options_tab
        self._toolbar_text_check = tab.toolbar_text_check
        self._display_modes_sync_check = tab.display_modes_sync_check
        self._display_mode_3d_transparent_radio = tab.display_mode_3d_transparent_radio
        self._display_mode_3d_solid_radio = tab.display_mode_3d_solid_radio
        self._display_mode_3d_original_radio = tab.display_mode_3d_original_radio
        self._display_mode_2d_transparent_radio = tab.display_mode_2d_transparent_radio
        self._display_mode_2d_solid_radio = tab.display_mode_2d_solid_radio
        self._display_mode_2d_original_radio = tab.display_mode_2d_original_radio
        self._grayscale_check = tab.grayscale_check
        self._roping_touching_radio = tab.roping_touching_radio
        self._roping_inclusive_radio = tab.roping_inclusive_radio
        self._hotlink_view_radio = tab.hotlink_view_radio
        self._hotlink_annotation_radio = tab.hotlink_annotation_radio
        self._hotlink_main_radio = tab.hotlink_main_radio
        self._page_index_check = tab.page_index_check
        self._sheet_number_check = tab.sheet_number_check
        self._disable_high_res_check = tab.disable_high_res_check
        self._intelligent_paste_check = tab.intelligent_paste_check
        self._advanced_mouse_controls_check = tab.advanced_mouse_controls_check
        self._full_window_crosshairs_check = tab.full_window_crosshairs_check
        self._crosshair_color_button = tab.crosshair_color_button
        self._crosshair_line_thickness_spin = tab.crosshair_line_thickness_spin
        self._allow_add_page_from_takeoff_check = tab.allow_add_page_from_takeoff_check
        self._snap_to_grid_check = tab.snap_to_grid_check
        self._snap_to_grid_threshold_spin = tab.snap_to_grid_threshold_spin
        self._snap_to_pdf_lines_check = tab.snap_to_pdf_lines_check
        self._snap_to_pdf_lines_threshold_spin = tab.snap_to_pdf_lines_threshold_spin
        self._snap_to_takeoffs_check = tab.snap_to_takeoffs_check
        self._snap_to_takeoffs_threshold_spin = tab.snap_to_takeoffs_threshold_spin
        self._snap_to_right_angle_check = tab.snap_to_right_angle_check
        self._snap_to_right_angle_threshold_spin = (
            tab.snap_to_right_angle_threshold_spin
        )
        self._mouse_unpressed_snap_angle_combo = tab.mouse_unpressed_snap_angle_combo
        self._mouse_pressed_snap_angle_combo = tab.mouse_pressed_snap_angle_combo
        self._auto_zoom_spin = tab.auto_zoom_spin

    def _on_tab_changed(self, index: int) -> None:
        if (
            self._tabs is not None
            and self._mcp_setup_tab is not None
            and self._tabs.widget(index) is self._mcp_setup_tab
        ):
            self._mcp_setup_tab.refresh_status()

    def _load_config(self) -> None:
        self._toolbar_text_check.setChecked(self._applied_config.show_toolbar_text)
        self._display_modes_sync_check.setChecked(
            self._applied_config.display_modes_synced
        )
        self._set_display_mode_radios("3d", self._applied_config.display_mode_3d)
        self._set_display_mode_radios("2d", self._applied_config.display_mode_2d)
        self._sync_display_modes_when_enabled()
        self._grayscale_check.setChecked(self._applied_config.grayscale_enabled)
        self._roping_inclusive_radio.setChecked(
            self._applied_config.roping_selection_method
            == Config.ROPING_SELECTION_INCLUSIVE
        )
        self._roping_touching_radio.setChecked(
            self._applied_config.roping_selection_method
            == Config.ROPING_SELECTION_TOUCHING
        )
        self._hotlink_view_radio.setChecked(
            self._applied_config.hotlink_target == Config.HOTLINK_TARGET_VIEW
        )
        self._hotlink_annotation_radio.setChecked(
            self._applied_config.hotlink_target == Config.HOTLINK_TARGET_ANNOTATION
        )
        self._hotlink_main_radio.setChecked(
            self._applied_config.hotlink_target == Config.HOTLINK_TARGET_MAIN
        )
        self._page_index_check.setChecked(
            self._applied_config.display_page_index_with_sheet_name
        )
        self._sheet_number_check.setChecked(
            self._applied_config.display_sheet_number_with_sheet_name
        )
        self._disable_high_res_check.setChecked(
            self._applied_config.disable_high_resolution_images
        )
        self._intelligent_paste_check.setChecked(
            self._applied_config.enable_intelligent_paste
        )
        self._advanced_mouse_controls_check.setChecked(
            self._applied_config.enable_advanced_mouse_controls
        )
        self._auto_zoom_spin.setValue(self._applied_config.default_auto_zoom_level)
        self._full_window_crosshairs_check.setChecked(
            self._applied_config.use_full_window_crosshairs
        )
        self._crosshair_color_button.set_color(self._applied_config.crosshair_color)
        self._crosshair_line_thickness_spin.setValue(
            self._applied_config.crosshair_line_thickness
        )
        self._allow_add_page_from_takeoff_check.setChecked(
            self._applied_config.allow_add_page_from_takeoff_tab
        )
        self._snap_to_grid_check.setChecked(self._applied_config.snap_to_grid_enabled)
        self._snap_to_grid_threshold_spin.setValue(
            self._applied_config.snap_to_grid_threshold_px
        )
        self._snap_to_pdf_lines_check.setChecked(
            self._applied_config.snap_to_pdf_lines_enabled
        )
        self._snap_to_pdf_lines_threshold_spin.setValue(
            self._applied_config.snap_to_pdf_lines_threshold_px
        )
        self._snap_to_takeoffs_check.setChecked(
            self._applied_config.snap_to_takeoffs_enabled
        )
        self._snap_to_takeoffs_threshold_spin.setValue(
            self._applied_config.snap_to_takeoffs_threshold_px
        )
        self._snap_to_right_angle_check.setChecked(
            self._applied_config.snap_to_right_angle_enabled
        )
        self._snap_to_right_angle_threshold_spin.setValue(
            self._applied_config.snap_to_right_angle_threshold_px
        )
        self._set_combo_by_data(
            self._mouse_unpressed_snap_angle_combo,
            self._applied_config.mouse_unpressed_snap_angle,
        )
        self._set_combo_by_data(
            self._mouse_pressed_snap_angle_combo,
            self._applied_config.mouse_pressed_snap_angle,
        )
        self._caption_master_check.setChecked(
            self._applied_config.pdf_annotation_captions_enabled
        )
        selected_caption_ids = self._applied_config.pdf_annotation_caption_ids
        for caption_id in ANNOTATION_CAPTION_ORDER:
            self._caption_checks[caption_id].setChecked(
                caption_id.value in selected_caption_ids
            )
        self._html_elevation_callouts_check.setChecked(
            self._applied_config.html_elevation_callouts_enabled
        )
        self._pdf_elevation_callouts_check.setChecked(
            self._applied_config.pdf_elevation_callouts_enabled
        )

    def _connect_change_signals(self) -> None:
        buttons = (
            self._toolbar_text_check,
            self._display_modes_sync_check,
            self._display_mode_3d_transparent_radio,
            self._display_mode_3d_solid_radio,
            self._display_mode_3d_original_radio,
            self._display_mode_2d_transparent_radio,
            self._display_mode_2d_solid_radio,
            self._display_mode_2d_original_radio,
            self._grayscale_check,
            self._roping_touching_radio,
            self._roping_inclusive_radio,
            self._hotlink_view_radio,
            self._hotlink_annotation_radio,
            self._hotlink_main_radio,
            self._page_index_check,
            self._sheet_number_check,
            self._disable_high_res_check,
            self._intelligent_paste_check,
            self._advanced_mouse_controls_check,
            self._full_window_crosshairs_check,
            self._allow_add_page_from_takeoff_check,
            self._snap_to_grid_check,
            self._snap_to_pdf_lines_check,
            self._snap_to_takeoffs_check,
            self._snap_to_right_angle_check,
            self._caption_master_check,
            *self._caption_checks.values(),
            self._html_elevation_callouts_check,
            self._pdf_elevation_callouts_check,
        )
        for button in buttons:
            button.toggled.connect(self._update_apply_enabled)
        self._display_modes_sync_check.toggled.connect(
            self._sync_display_modes_when_enabled
        )
        for button in (
            self._display_mode_3d_transparent_radio,
            self._display_mode_3d_solid_radio,
            self._display_mode_3d_original_radio,
        ):
            button.toggled.connect(self._sync_2d_display_mode_when_synced)
        for button in (
            self._display_mode_2d_transparent_radio,
            self._display_mode_2d_solid_radio,
            self._display_mode_2d_original_radio,
        ):
            button.toggled.connect(self._sync_3d_display_mode_when_synced)
        self._crosshair_color_button.colorChanged.connect(self._update_apply_enabled)
        self._crosshair_line_thickness_spin.valueChanged.connect(
            self._update_apply_enabled
        )
        self._mouse_unpressed_snap_angle_combo.currentIndexChanged.connect(
            self._update_apply_enabled
        )
        self._mouse_pressed_snap_angle_combo.currentIndexChanged.connect(
            self._update_apply_enabled
        )
        self._snap_to_grid_threshold_spin.valueChanged.connect(
            self._update_apply_enabled
        )
        self._snap_to_pdf_lines_threshold_spin.valueChanged.connect(
            self._update_apply_enabled
        )
        self._snap_to_takeoffs_threshold_spin.valueChanged.connect(
            self._update_apply_enabled
        )
        self._snap_to_right_angle_threshold_spin.valueChanged.connect(
            self._update_apply_enabled
        )
        self._auto_zoom_spin.valueChanged.connect(self._update_apply_enabled)

    def _collect_widget_config(self) -> Config:
        display_mode_3d = self._selected_display_mode("3d")
        display_mode_2d = self._selected_display_mode("2d")
        display_modes_synced = self._display_modes_sync_check.isChecked()
        if display_modes_synced:
            display_mode_2d = display_mode_3d
        return replace(
            self._applied_config,
            display_modes_synced=display_modes_synced,
            display_mode_3d=display_mode_3d,
            display_mode_2d=display_mode_2d,
            grayscale_enabled=self._grayscale_check.isChecked(),
            show_toolbar_text=self._toolbar_text_check.isChecked(),
            roping_selection_method=(
                Config.ROPING_SELECTION_INCLUSIVE
                if self._roping_inclusive_radio.isChecked()
                else Config.ROPING_SELECTION_TOUCHING
            ),
            hotlink_target=self._selected_hotlink_target(),
            display_page_index_with_sheet_name=self._page_index_check.isChecked(),
            display_sheet_number_with_sheet_name=self._sheet_number_check.isChecked(),
            disable_high_resolution_images=self._disable_high_res_check.isChecked(),
            enable_intelligent_paste=self._intelligent_paste_check.isChecked(),
            enable_advanced_mouse_controls=(
                self._advanced_mouse_controls_check.isChecked()
            ),
            default_auto_zoom_level=self._auto_zoom_spin.value(),
            use_full_window_crosshairs=self._full_window_crosshairs_check.isChecked(),
            crosshair_color=self._crosshair_color_button.color(),
            crosshair_line_thickness=self._crosshair_line_thickness_spin.value(),
            allow_add_page_from_takeoff_tab=(
                self._allow_add_page_from_takeoff_check.isChecked()
            ),
            mouse_unpressed_snap_angle=(
                self._mouse_unpressed_snap_angle_combo.currentData()
            ),
            mouse_pressed_snap_angle=self._mouse_pressed_snap_angle_combo.currentData(),
            snap_to_grid_enabled=self._snap_to_grid_check.isChecked(),
            snap_to_grid_threshold_px=self._snap_to_grid_threshold_spin.value(),
            snap_to_pdf_lines_enabled=self._snap_to_pdf_lines_check.isChecked(),
            snap_to_pdf_lines_threshold_px=(
                self._snap_to_pdf_lines_threshold_spin.value()
            ),
            snap_to_takeoffs_enabled=self._snap_to_takeoffs_check.isChecked(),
            snap_to_takeoffs_threshold_px=(
                self._snap_to_takeoffs_threshold_spin.value()
            ),
            snap_to_right_angle_enabled=self._snap_to_right_angle_check.isChecked(),
            snap_to_right_angle_threshold_px=(
                self._snap_to_right_angle_threshold_spin.value()
            ),
            pdf_annotation_captions_enabled=self._caption_master_check.isChecked(),
            pdf_annotation_caption_ids=tuple(
                caption_id.value
                for caption_id in ANNOTATION_CAPTION_ORDER
                if self._caption_checks[caption_id].isChecked()
            ),
            html_elevation_callouts_enabled=(
                self._html_elevation_callouts_check.isChecked()
            ),
            pdf_elevation_callouts_enabled=(
                self._pdf_elevation_callouts_check.isChecked()
            ),
        )

    def _selected_display_mode(self, target: str) -> str:
        if target == "3d":
            if self._display_mode_3d_transparent_radio.isChecked():
                return Config.DISPLAY_MODE_TRANSPARENT
            if self._display_mode_3d_original_radio.isChecked():
                return Config.DISPLAY_MODE_ORIGINAL
            return Config.DISPLAY_MODE_SOLID
        if self._display_mode_2d_transparent_radio.isChecked():
            return Config.DISPLAY_MODE_TRANSPARENT
        if self._display_mode_2d_original_radio.isChecked():
            return Config.DISPLAY_MODE_ORIGINAL
        return Config.DISPLAY_MODE_SOLID

    def _set_display_mode_radios(self, target: str, display_mode: str) -> None:
        transparent = display_mode == Config.DISPLAY_MODE_TRANSPARENT
        original = display_mode == Config.DISPLAY_MODE_ORIGINAL
        if target == "3d":
            self._display_mode_3d_transparent_radio.setChecked(transparent)
            self._display_mode_3d_original_radio.setChecked(original)
            self._display_mode_3d_solid_radio.setChecked(
                not transparent and not original
            )
            return
        self._display_mode_2d_transparent_radio.setChecked(transparent)
        self._display_mode_2d_original_radio.setChecked(original)
        self._display_mode_2d_solid_radio.setChecked(not transparent and not original)

    def _sync_display_modes_when_enabled(self, *_args) -> None:
        if self._display_modes_sync_check.isChecked():
            self._set_display_mode_radios("2d", self._selected_display_mode("3d"))

    def _sync_2d_display_mode_when_synced(self, checked: bool = False) -> None:
        if checked and self._display_modes_sync_check.isChecked():
            self._set_display_mode_radios("2d", self._selected_display_mode("3d"))

    def _sync_3d_display_mode_when_synced(self, checked: bool = False) -> None:
        if checked and self._display_modes_sync_check.isChecked():
            self._set_display_mode_radios("3d", self._selected_display_mode("2d"))

    def _selected_hotlink_target(self) -> str:
        if self._hotlink_view_radio.isChecked():
            return Config.HOTLINK_TARGET_VIEW
        if self._hotlink_main_radio.isChecked():
            return Config.HOTLINK_TARGET_MAIN
        return Config.HOTLINK_TARGET_ANNOTATION

    def _set_combo_by_data(self, combo: QtWidgets.QComboBox, data: int) -> None:
        index = combo.findData(data)
        if index < 0:
            raise ValueError(f"Unsupported Options combo value: {data!r}")
        combo.setCurrentIndex(index)

    def _has_pending_changes(self) -> bool:
        return self._collect_widget_config() != self._applied_config

    def _update_apply_enabled(self, *_args) -> None:
        if self._apply_button is not None:
            self._apply_button.setEnabled(self._has_pending_changes())

    def _apply_pending_changes(self) -> Config:
        next_config = self._collect_widget_config()
        if next_config != self._applied_config and self._apply_callback is not None:
            self._apply_callback(next_config)
        self._config = replace(next_config)
        self._applied_config = replace(next_config)
        self._update_apply_enabled()
        return self.get_config()

    def _reset_all_settings(self) -> None:
        if not confirm(
            self,
            OPTIONS_LABEL_RESET_ALL_SETTINGS,
            self._RESET_ALL_SETTINGS_MESSAGE,
        ):
            return
        next_config = self._reset_callback() if self._reset_callback else Config()
        self._config = replace(next_config)
        self._applied_config = replace(next_config)
        self._load_config()
        self._update_apply_enabled()

    def cleanup(self) -> None:
        if self._cleaned_up:
            return
        self._cleaned_up = True
        if self._tabs is not None:
            try:
                self._tabs.currentChanged.disconnect(self._on_tab_changed)
            except (TypeError, RuntimeError):
                pass
        if self._mcp_setup_tab is not None:
            self._mcp_setup_tab.cleanup()
        self._options_tab = None
        self._export_tab = None
        self._mcp_setup_tab = None
        self._tabs = None

    def done(self, result: int) -> None:
        self.cleanup()
        super().done(result)

    def closeEvent(self, event) -> None:
        self.cleanup()
        super().closeEvent(event)
