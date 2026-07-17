from __future__ import annotations
from dataclasses import dataclass
from typing import ClassVar
from .annotation_caption import DEFAULT_ANNOTATION_CAPTION_IDS
from .elevation_callout import ElevationCalloutSettings


@dataclass
class Config:
    DISPLAY_MODE_SOLID: ClassVar[str] = "Solid"
    DISPLAY_MODE_ORIGINAL: ClassVar[str] = "Original"
    DISPLAY_MODE_TRANSPARENT: ClassVar[str] = "Transparent"
    ROPING_SELECTION_TOUCHING: ClassVar[str] = "touching"
    ROPING_SELECTION_INCLUSIVE: ClassVar[str] = "inclusive"
    HOTLINK_TARGET_ANNOTATION: ClassVar[str] = "annotation"
    HOTLINK_TARGET_VIEW: ClassVar[str] = "view"
    HOTLINK_TARGET_MAIN: ClassVar[str] = "main"
    DEFAULT_DISPLAY_MODE: ClassVar[str] = DISPLAY_MODE_ORIGINAL
    DEFAULT_ROPING_SELECTION_METHOD: ClassVar[str] = ROPING_SELECTION_TOUCHING
    DEFAULT_HOTLINK_TARGET: ClassVar[str] = HOTLINK_TARGET_ANNOTATION
    DEFAULT_AUTO_ZOOM_LEVEL: ClassVar[int] = 0
    DEFAULT_CROSSHAIR_COLOR: ClassVar[str] = "#00ff00"
    DEFAULT_CROSSHAIR_LINE_THICKNESS: ClassVar[int] = 1
    DEFAULT_MOUSE_UNPRESSED_SNAP_ANGLE: ClassVar[int] = 15
    DEFAULT_MOUSE_PRESSED_SNAP_ANGLE: ClassVar[int] = 0
    DEFAULT_SNAP_THRESHOLD_PX: ClassVar[int] = 8
    DEFAULT_ELEVATION_CALLOUT_COLOR: ClassVar[str] = "#ff0000"
    display_modes_synced: bool = True
    display_mode_3d: str = DEFAULT_DISPLAY_MODE
    display_mode_2d: str = DEFAULT_DISPLAY_MODE
    grayscale_enabled: bool = False
    roping_selection_method: str = DEFAULT_ROPING_SELECTION_METHOD
    display_page_index_with_sheet_name: bool = False
    display_sheet_number_with_sheet_name: bool = False
    hotlink_target: str = DEFAULT_HOTLINK_TARGET
    show_toolbar_text: bool = True
    disable_high_resolution_images: bool = False
    enable_intelligent_paste: bool = True
    enable_advanced_mouse_controls: bool = True
    default_auto_zoom_level: int = DEFAULT_AUTO_ZOOM_LEVEL
    use_full_window_crosshairs: bool = False
    crosshair_color: str = DEFAULT_CROSSHAIR_COLOR
    crosshair_line_thickness: int = DEFAULT_CROSSHAIR_LINE_THICKNESS
    allow_add_page_from_takeoff_tab: bool = False
    mouse_unpressed_snap_angle: int = DEFAULT_MOUSE_UNPRESSED_SNAP_ANGLE
    mouse_pressed_snap_angle: int = DEFAULT_MOUSE_PRESSED_SNAP_ANGLE
    snap_to_grid_enabled: bool = True
    snap_to_grid_threshold_px: int = DEFAULT_SNAP_THRESHOLD_PX
    snap_to_pdf_lines_enabled: bool = True
    snap_to_pdf_lines_threshold_px: int = DEFAULT_SNAP_THRESHOLD_PX
    snap_to_takeoffs_enabled: bool = True
    snap_to_takeoffs_threshold_px: int = DEFAULT_SNAP_THRESHOLD_PX
    snap_to_right_angle_enabled: bool = True
    snap_to_right_angle_threshold_px: int = DEFAULT_SNAP_THRESHOLD_PX
    pdf_annotation_captions_enabled: bool = False
    pdf_annotation_caption_ids: tuple[str, ...] = DEFAULT_ANNOTATION_CAPTION_IDS
    html_elevation_callouts_enabled: bool = True
    pdf_elevation_callouts_enabled: bool = False
    elevation_callout_include_condition: bool = True
    elevation_callout_include_top: bool = True
    elevation_callout_include_bottom: bool = True
    elevation_callout_include_cubic_yards: bool = True
    html_elevation_callout_color: str = DEFAULT_ELEVATION_CALLOUT_COLOR
    pdf_elevation_callout_color: str = DEFAULT_ELEVATION_CALLOUT_COLOR

    def to_dict(self) -> dict:
        return {
            "display_modes_synced": self.display_modes_synced,
            "display_mode_3d": self.display_mode_3d,
            "display_mode_2d": self.display_mode_2d,
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
            "use_full_window_crosshairs": self.use_full_window_crosshairs,
            "crosshair_color": self.crosshair_color,
            "crosshair_line_thickness": self.crosshair_line_thickness,
            "allow_add_page_from_takeoff_tab": self.allow_add_page_from_takeoff_tab,
            "mouse_unpressed_snap_angle": self.mouse_unpressed_snap_angle,
            "mouse_pressed_snap_angle": self.mouse_pressed_snap_angle,
            "snap_to_grid_enabled": self.snap_to_grid_enabled,
            "snap_to_grid_threshold_px": self.snap_to_grid_threshold_px,
            "snap_to_pdf_lines_enabled": self.snap_to_pdf_lines_enabled,
            "snap_to_pdf_lines_threshold_px": self.snap_to_pdf_lines_threshold_px,
            "snap_to_takeoffs_enabled": self.snap_to_takeoffs_enabled,
            "snap_to_takeoffs_threshold_px": self.snap_to_takeoffs_threshold_px,
            "snap_to_right_angle_enabled": self.snap_to_right_angle_enabled,
            "snap_to_right_angle_threshold_px": self.snap_to_right_angle_threshold_px,
            "pdf_annotation_captions_enabled": self.pdf_annotation_captions_enabled,
            "pdf_annotation_caption_ids": list(self.pdf_annotation_caption_ids),
            "html_elevation_callouts_enabled": self.html_elevation_callouts_enabled,
            "pdf_elevation_callouts_enabled": self.pdf_elevation_callouts_enabled,
            "elevation_callout_include_condition": (
                self.elevation_callout_include_condition
            ),
            "elevation_callout_include_top": self.elevation_callout_include_top,
            "elevation_callout_include_bottom": self.elevation_callout_include_bottom,
            "elevation_callout_include_cubic_yards": (
                self.elevation_callout_include_cubic_yards
            ),
            "html_elevation_callout_color": self.html_elevation_callout_color,
            "pdf_elevation_callout_color": self.pdf_elevation_callout_color,
        }

    def elevation_callout_settings(self) -> ElevationCalloutSettings:
        return ElevationCalloutSettings(
            include_condition=self.elevation_callout_include_condition,
            include_top=self.elevation_callout_include_top,
            include_bottom=self.elevation_callout_include_bottom,
            include_cubic_yards=self.elevation_callout_include_cubic_yards,
        )

    @classmethod
    def from_dict(cls, data: dict) -> Config:
        config = cls()
        if not data:
            return config
        if "display_modes_synced" in data:
            config.display_modes_synced = bool(data["display_modes_synced"])
        if "display_mode_3d" in data:
            config.display_mode_3d = str(data["display_mode_3d"])
        if "display_mode_2d" in data:
            config.display_mode_2d = str(data["display_mode_2d"])
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
        if "snap_to_right_angle_enabled" in data:
            config.snap_to_right_angle_enabled = bool(
                data["snap_to_right_angle_enabled"]
            )
        if "snap_to_right_angle_threshold_px" in data:
            config.snap_to_right_angle_threshold_px = int(
                data["snap_to_right_angle_threshold_px"]
            )
        if "pdf_annotation_captions_enabled" in data:
            config.pdf_annotation_captions_enabled = bool(
                data["pdf_annotation_captions_enabled"]
            )
        if "pdf_annotation_caption_ids" in data:
            caption_ids = data["pdf_annotation_caption_ids"]
            if not isinstance(caption_ids, (list, tuple)):
                raise TypeError("pdf_annotation_caption_ids must be a list")
            config.pdf_annotation_caption_ids = tuple(
                str(value) for value in caption_ids
            )
        if "html_elevation_callouts_enabled" in data:
            config.html_elevation_callouts_enabled = bool(
                data["html_elevation_callouts_enabled"]
            )
        if "pdf_elevation_callouts_enabled" in data:
            config.pdf_elevation_callouts_enabled = bool(
                data["pdf_elevation_callouts_enabled"]
            )
        if "elevation_callout_include_condition" in data:
            config.elevation_callout_include_condition = bool(
                data["elevation_callout_include_condition"]
            )
        if "elevation_callout_include_top" in data:
            config.elevation_callout_include_top = bool(
                data["elevation_callout_include_top"]
            )
        if "elevation_callout_include_bottom" in data:
            config.elevation_callout_include_bottom = bool(
                data["elevation_callout_include_bottom"]
            )
        if "elevation_callout_include_cubic_yards" in data:
            config.elevation_callout_include_cubic_yards = bool(
                data["elevation_callout_include_cubic_yards"]
            )
        if "html_elevation_callout_color" in data:
            config.html_elevation_callout_color = str(
                data["html_elevation_callout_color"]
            )
        if "pdf_elevation_callout_color" in data:
            config.pdf_elevation_callout_color = str(
                data["pdf_elevation_callout_color"]
            )
        return config
