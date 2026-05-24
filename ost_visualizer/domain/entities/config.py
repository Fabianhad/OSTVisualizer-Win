from __future__ import annotations
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class Config:
    DEFAULT_COLOR_MODE: ClassVar[str] = "Solid"
    DEFAULT_ROPING_SELECTION_METHOD: ClassVar[str] = "touching"
    DEFAULT_HOTLINK_TARGET: ClassVar[str] = "annotation"
    DEFAULT_AUTO_ZOOM_LEVEL: ClassVar[int] = 0
    DEFAULT_CROSSHAIR_COLOR: ClassVar[str] = "#00ff00"
    DEFAULT_CROSSHAIR_LINE_THICKNESS: ClassVar[int] = 1
    DEFAULT_MOUSE_UNPRESSED_SNAP_ANGLE: ClassVar[int] = 15
    DEFAULT_MOUSE_PRESSED_SNAP_ANGLE: ClassVar[int] = 0
    DEFAULT_SNAP_THRESHOLD_PX: ClassVar[int] = 8
    color_mode: str = DEFAULT_COLOR_MODE
    grayscale_enabled: bool = True
    roping_selection_method: str = DEFAULT_ROPING_SELECTION_METHOD
    display_page_index_with_sheet_name: bool = False
    display_sheet_number_with_sheet_name: bool = False
    hotlink_target: str = DEFAULT_HOTLINK_TARGET
    show_toolbar_text: bool = False
    disable_high_resolution_images: bool = False
    enable_intelligent_paste: bool = True
    enable_advanced_mouse_controls: bool = True
    default_auto_zoom_level: int = DEFAULT_AUTO_ZOOM_LEVEL
    show_right_angle_line_indicator: bool = False
    connect_linear_takeoff: bool = True
    use_full_window_crosshairs: bool = False
    crosshair_color: str = DEFAULT_CROSSHAIR_COLOR
    crosshair_line_thickness: int = DEFAULT_CROSSHAIR_LINE_THICKNESS
    allow_add_page_from_takeoff_tab: bool = False
    enable_auto_dimension_lines: bool = False
    mouse_unpressed_snap_angle: int = DEFAULT_MOUSE_UNPRESSED_SNAP_ANGLE
    mouse_pressed_snap_angle: int = DEFAULT_MOUSE_PRESSED_SNAP_ANGLE
    snap_to_grid_enabled: bool = True
    snap_to_grid_threshold_px: int = DEFAULT_SNAP_THRESHOLD_PX
    snap_to_pdf_lines_enabled: bool = True
    snap_to_pdf_lines_threshold_px: int = DEFAULT_SNAP_THRESHOLD_PX
    snap_to_takeoffs_enabled: bool = True
    snap_to_takeoffs_threshold_px: int = DEFAULT_SNAP_THRESHOLD_PX
    right_angle_indicator_threshold_px: int = DEFAULT_SNAP_THRESHOLD_PX

    def to_dict(self) -> dict:
        return {
            "color_mode": self.color_mode,
            "grayscale_enabled": self.grayscale_enabled,
            "roping_selection_method": self.roping_selection_method,
            "display_page_index_with_sheet_name": (
                self.display_page_index_with_sheet_name
            ),
            "display_sheet_number_with_sheet_name": (
                self.display_sheet_number_with_sheet_name
            ),
            "hotlink_target": self.hotlink_target,
            "show_toolbar_text": self.show_toolbar_text,
            "disable_high_resolution_images": self.disable_high_resolution_images,
            "enable_intelligent_paste": self.enable_intelligent_paste,
            "enable_advanced_mouse_controls": self.enable_advanced_mouse_controls,
            "default_auto_zoom_level": self.default_auto_zoom_level,
            "show_right_angle_line_indicator": self.show_right_angle_line_indicator,
            "connect_linear_takeoff": self.connect_linear_takeoff,
            "use_full_window_crosshairs": self.use_full_window_crosshairs,
            "crosshair_color": self.crosshair_color,
            "crosshair_line_thickness": self.crosshair_line_thickness,
            "allow_add_page_from_takeoff_tab": self.allow_add_page_from_takeoff_tab,
            "enable_auto_dimension_lines": self.enable_auto_dimension_lines,
            "mouse_unpressed_snap_angle": self.mouse_unpressed_snap_angle,
            "mouse_pressed_snap_angle": self.mouse_pressed_snap_angle,
            "snap_to_grid_enabled": self.snap_to_grid_enabled,
            "snap_to_grid_threshold_px": self.snap_to_grid_threshold_px,
            "snap_to_pdf_lines_enabled": self.snap_to_pdf_lines_enabled,
            "snap_to_pdf_lines_threshold_px": self.snap_to_pdf_lines_threshold_px,
            "snap_to_takeoffs_enabled": self.snap_to_takeoffs_enabled,
            "snap_to_takeoffs_threshold_px": self.snap_to_takeoffs_threshold_px,
            "right_angle_indicator_threshold_px": (
                self.right_angle_indicator_threshold_px
            ),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Config:
        config = cls()
        if not data:
            return config
        if "color_mode" in data:
            config.color_mode = str(data["color_mode"])
        if "grayscale_enabled" in data:
            config.grayscale_enabled = bool(data["grayscale_enabled"])
        if "roping_selection_method" in data:
            config.roping_selection_method = str(data["roping_selection_method"])
        if "display_page_index_with_sheet_name" in data:
            config.display_page_index_with_sheet_name = bool(
                data["display_page_index_with_sheet_name"]
            )
        if "display_sheet_number_with_sheet_name" in data:
            config.display_sheet_number_with_sheet_name = bool(
                data["display_sheet_number_with_sheet_name"]
            )
        if "hotlink_target" in data:
            config.hotlink_target = str(data["hotlink_target"])
        if "show_toolbar_text" in data:
            config.show_toolbar_text = bool(data["show_toolbar_text"])
        if "disable_high_resolution_images" in data:
            config.disable_high_resolution_images = bool(
                data["disable_high_resolution_images"]
            )
        if "enable_intelligent_paste" in data:
            config.enable_intelligent_paste = bool(data["enable_intelligent_paste"])
        if "enable_advanced_mouse_controls" in data:
            config.enable_advanced_mouse_controls = bool(
                data["enable_advanced_mouse_controls"]
            )
        if "default_auto_zoom_level" in data:
            config.default_auto_zoom_level = int(data["default_auto_zoom_level"])
        if "show_right_angle_line_indicator" in data:
            config.show_right_angle_line_indicator = bool(
                data["show_right_angle_line_indicator"]
            )
        if "connect_linear_takeoff" in data:
            config.connect_linear_takeoff = bool(data["connect_linear_takeoff"])
        if "use_full_window_crosshairs" in data:
            config.use_full_window_crosshairs = bool(data["use_full_window_crosshairs"])
        if "crosshair_color" in data:
            config.crosshair_color = str(data["crosshair_color"])
        if "crosshair_line_thickness" in data:
            config.crosshair_line_thickness = int(data["crosshair_line_thickness"])
        if "allow_add_page_from_takeoff_tab" in data:
            config.allow_add_page_from_takeoff_tab = bool(
                data["allow_add_page_from_takeoff_tab"]
            )
        if "enable_auto_dimension_lines" in data:
            config.enable_auto_dimension_lines = bool(
                data["enable_auto_dimension_lines"]
            )
        if "mouse_unpressed_snap_angle" in data:
            config.mouse_unpressed_snap_angle = int(data["mouse_unpressed_snap_angle"])
        if "mouse_pressed_snap_angle" in data:
            config.mouse_pressed_snap_angle = int(data["mouse_pressed_snap_angle"])
        if "snap_to_grid_enabled" in data:
            config.snap_to_grid_enabled = bool(data["snap_to_grid_enabled"])
        if "snap_to_grid_threshold_px" in data:
            config.snap_to_grid_threshold_px = int(data["snap_to_grid_threshold_px"])
        if "snap_to_pdf_lines_enabled" in data:
            config.snap_to_pdf_lines_enabled = bool(data["snap_to_pdf_lines_enabled"])
        if "snap_to_pdf_lines_threshold_px" in data:
            config.snap_to_pdf_lines_threshold_px = int(
                data["snap_to_pdf_lines_threshold_px"]
            )
        if "snap_to_takeoffs_enabled" in data:
            config.snap_to_takeoffs_enabled = bool(data["snap_to_takeoffs_enabled"])
        if "snap_to_takeoffs_threshold_px" in data:
            config.snap_to_takeoffs_threshold_px = int(
                data["snap_to_takeoffs_threshold_px"]
            )
        if "right_angle_indicator_threshold_px" in data:
            config.right_angle_indicator_threshold_px = int(
                data["right_angle_indicator_threshold_px"]
            )
        return config
