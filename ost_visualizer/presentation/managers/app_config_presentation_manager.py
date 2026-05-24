from PySide6 import QtCore
from ...application.dtos.snap_preferences_dto import SnapPreferencesDto


class AppConfigPresentationManager:
    """Applies app-config preferences to live presentation components."""

    _CONDITION_DISPLAY_REFRESH_KEYS = frozenset(
        {
            "color_mode",
            "grayscale_enabled",
        }
    )

    def apply(self, window, config_model) -> None:
        self.apply_toolbar_text(window, config_model)
        if window.takeoff_sidebar:
            window.takeoff_sidebar.set_label_options(
                config_model.display_page_index_with_sheet_name,
                config_model.display_sheet_number_with_sheet_name,
            )
        if window.plan_view:
            self.apply_plan_view_config(window.plan_view, config_model)
        for detached_window in (
            window.get_annotation_window(),
            window.get_view_window(),
        ):
            if detached_window is not None:
                self.apply_detached_window_config(detached_window, config_model)

    def apply_updated_options(self, window, config_model, changed_values: dict) -> bool:
        self.apply(window, config_model)
        return self.requires_condition_display_refresh(changed_values)

    def requires_condition_display_refresh(self, changed_values: dict) -> bool:
        return bool(self._CONDITION_DISPLAY_REFRESH_KEYS.intersection(changed_values))

    def apply_toolbar_text(self, window, config_model) -> None:
        style = (
            QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon
            if config_model.show_toolbar_text
            else QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        for toolbar in window.get_workspace_toolbars():
            toolbar.setToolButtonStyle(style)

    def apply_plan_view_config(self, plan_view, config_model) -> None:
        plan_view.set_roping_selection_method(config_model.roping_selection_method)
        plan_view.set_disable_high_resolution_images(
            config_model.disable_high_resolution_images
        )
        plan_view.set_intelligent_paste_enabled(config_model.enable_intelligent_paste)
        plan_view.set_advanced_mouse_controls_enabled(
            config_model.enable_advanced_mouse_controls
        )
        plan_view.set_default_auto_zoom_level(config_model.default_auto_zoom_level)
        plan_view.set_right_angle_line_indicator_enabled(
            config_model.show_right_angle_line_indicator
        )
        plan_view.set_full_window_crosshairs(
            config_model.use_full_window_crosshairs,
            config_model.crosshair_color,
            config_model.crosshair_line_thickness,
        )
        plan_view.set_mouse_snap_angles(
            config_model.mouse_unpressed_snap_angle,
            config_model.mouse_pressed_snap_angle,
        )
        plan_view.set_snap_preferences(
            **self._snap_preferences(config_model).to_kwargs()
        )

    def _snap_preferences(self, config_model) -> SnapPreferencesDto:
        return SnapPreferencesDto.from_config(config_model)

    def apply_detached_window_config(self, detached_window, config_model) -> None:
        detached_window.apply_config_preferences(
            show_page_index=config_model.display_page_index_with_sheet_name,
            show_sheet_number=config_model.display_sheet_number_with_sheet_name,
            roping_selection_method=config_model.roping_selection_method,
            disable_high_resolution_images=config_model.disable_high_resolution_images,
            intelligent_paste_enabled=config_model.enable_intelligent_paste,
            advanced_mouse_controls_enabled=config_model.enable_advanced_mouse_controls,
            default_auto_zoom_level=config_model.default_auto_zoom_level,
            show_right_angle_line_indicator=(
                config_model.show_right_angle_line_indicator
            ),
            use_full_window_crosshairs=config_model.use_full_window_crosshairs,
            crosshair_color=config_model.crosshair_color,
            crosshair_line_thickness=config_model.crosshair_line_thickness,
            mouse_unpressed_snap_angle=config_model.mouse_unpressed_snap_angle,
            mouse_pressed_snap_angle=config_model.mouse_pressed_snap_angle,
            **self._snap_preferences(config_model).to_kwargs(),
        )
