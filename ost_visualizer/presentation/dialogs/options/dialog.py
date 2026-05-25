from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional
from PySide6 import QtWidgets
from ....domain.entities.config import Config
from ...config import (
    OPTIONS_DIALOG_TITLE,
    OPTIONS_TAB_MCP_SETUP,
    OPTIONS_TAB_OPTIONS,
    OPTIONS_WINDOW_HEIGHT,
    OPTIONS_WINDOW_WIDTH,
)
from ...utils.windows import remove_minimize_maximize
from .components import McpSetupTab, OptionsTab


class OptionsDialog(QtWidgets.QDialog):
    def __init__(
        self,
        config: Config,
        parent=None,
        apply_callback: Optional[Callable[[Config], object]] = None,
        mcp_helper_path: Optional[Path] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(OPTIONS_DIALOG_TITLE)
        self.setFixedSize(OPTIONS_WINDOW_WIDTH, OPTIONS_WINDOW_HEIGHT)
        remove_minimize_maximize(self)
        self._applied_config = replace(config)
        self._config = replace(config)
        self._apply_callback = apply_callback
        self._apply_button: Optional[QtWidgets.QPushButton] = None
        self._tabs: Optional[QtWidgets.QTabWidget] = None
        self._options_tab: Optional[OptionsTab] = None
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
        main_layout.addWidget(buttons)

    def _bind_options_tab_widgets(self) -> None:
        tab = self._options_tab
        self._toolbar_text_check = tab.toolbar_text_check
        self._color_transparent_radio = tab.color_transparent_radio
        self._color_solid_radio = tab.color_solid_radio
        self._color_original_radio = tab.color_original_radio
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
        self._color_transparent_radio.setChecked(
            self._applied_config.color_mode == "Transparent"
        )
        self._color_solid_radio.setChecked(self._applied_config.color_mode == "Solid")
        self._color_original_radio.setChecked(
            self._applied_config.color_mode == "Original"
        )
        self._grayscale_check.setChecked(self._applied_config.grayscale_enabled)
        self._roping_inclusive_radio.setChecked(
            self._applied_config.roping_selection_method == "inclusive"
        )
        self._roping_touching_radio.setChecked(
            self._applied_config.roping_selection_method == "touching"
        )
        self._hotlink_view_radio.setChecked(
            self._applied_config.hotlink_target == "view"
        )
        self._hotlink_annotation_radio.setChecked(
            self._applied_config.hotlink_target == "annotation"
        )
        self._hotlink_main_radio.setChecked(
            self._applied_config.hotlink_target == "main"
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

    def _connect_change_signals(self) -> None:
        buttons = (
            self._toolbar_text_check,
            self._color_transparent_radio,
            self._color_solid_radio,
            self._color_original_radio,
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
        )
        for button in buttons:
            button.toggled.connect(self._update_apply_enabled)
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
        color_mode = "Solid"
        if self._color_transparent_radio.isChecked():
            color_mode = "Transparent"
        elif self._color_original_radio.isChecked():
            color_mode = "Original"
        return replace(
            self._applied_config,
            color_mode=color_mode,
            grayscale_enabled=self._grayscale_check.isChecked(),
            show_toolbar_text=self._toolbar_text_check.isChecked(),
            roping_selection_method=(
                "inclusive" if self._roping_inclusive_radio.isChecked() else "touching"
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
        )

    def _selected_hotlink_target(self) -> str:
        if self._hotlink_view_radio.isChecked():
            return "view"
        if self._hotlink_main_radio.isChecked():
            return "main"
        return "annotation"

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
        self._mcp_setup_tab = None
        self._tabs = None

    def done(self, result: int) -> None:
        self.cleanup()
        super().done(result)

    def closeEvent(self, event) -> None:
        self.cleanup()
        super().closeEvent(event)
