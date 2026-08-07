import logging
from dataclasses import replace
from typing import Optional
from ..entities.annotation_caption import SUPPORTED_ANNOTATION_CAPTION_IDS
from ..entities.config import Config
from ..entities.font_definition import FontDefinition
from ..repositories.i_config_repository import IConfigRepository


class ConfigAggregate:
    VALID_DISPLAY_MODES = frozenset(
        {
            Config.DISPLAY_MODE_SOLID,
            Config.DISPLAY_MODE_ORIGINAL,
            Config.DISPLAY_MODE_TRANSPARENT,
        }
    )
    VALID_ROPING_SELECTION_METHODS = frozenset(
        {Config.ROPING_SELECTION_TOUCHING, Config.ROPING_SELECTION_INCLUSIVE}
    )
    VALID_HOTLINK_TARGETS = frozenset(
        {
            Config.HOTLINK_TARGET_ANNOTATION,
            Config.HOTLINK_TARGET_VIEW,
            Config.HOTLINK_TARGET_MAIN,
        }
    )
    MIN_AUTO_ZOOM_LEVEL = 0
    MAX_AUTO_ZOOM_LEVEL = 1600
    VALID_MOUSE_SNAP_ANGLES = frozenset({0, 1, 2, 3, 4, 5, 10, 15, 30, 45, 90})
    MIN_CROSSHAIR_LINE_THICKNESS = 1
    MAX_CROSSHAIR_LINE_THICKNESS = 10
    MIN_SNAP_THRESHOLD_PX = 0
    MAX_SNAP_THRESHOLD_PX = 100

    def __init__(
        self,
        repository: IConfigRepository,
        logger: Optional[logging.Logger] = None,
    ):
        self.logger = logger or logging.getLogger(__name__)
        self.repository = repository
        self._config = Config()
        self._load_config()

    @property
    def display_modes_synced(self) -> bool:
        return self._config.display_modes_synced

    @property
    def display_mode_3d(self) -> str:
        return self._config.display_mode_3d

    @property
    def display_mode_2d(self) -> str:
        return self._config.display_mode_2d

    @property
    def grayscale_enabled(self) -> bool:
        return self._config.grayscale_enabled

    @property
    def roping_selection_method(self) -> str:
        return self._config.roping_selection_method

    @property
    def display_page_index_with_sheet_name(self) -> bool:
        return self._config.display_page_index_with_sheet_name

    @property
    def display_sheet_number_with_sheet_name(self) -> bool:
        return self._config.display_sheet_number_with_sheet_name

    @property
    def hotlink_target(self) -> str:
        return self._config.hotlink_target

    @property
    def show_toolbar_text(self) -> bool:
        return self._config.show_toolbar_text

    @property
    def disable_high_resolution_images(self) -> bool:
        return self._config.disable_high_resolution_images

    @property
    def enable_intelligent_paste(self) -> bool:
        return self._config.enable_intelligent_paste

    @property
    def enable_advanced_mouse_controls(self) -> bool:
        return self._config.enable_advanced_mouse_controls

    @property
    def default_auto_zoom_level(self) -> int:
        return self._config.default_auto_zoom_level

    @property
    def use_full_window_crosshairs(self) -> bool:
        return self._config.use_full_window_crosshairs

    @property
    def crosshair_color(self) -> str:
        return self._config.crosshair_color

    @property
    def crosshair_line_thickness(self) -> int:
        return self._config.crosshair_line_thickness

    @property
    def allow_add_page_from_takeoff_tab(self) -> bool:
        return self._config.allow_add_page_from_takeoff_tab

    @property
    def mouse_unpressed_snap_angle(self) -> int:
        return self._config.mouse_unpressed_snap_angle

    @property
    def mouse_pressed_snap_angle(self) -> int:
        return self._config.mouse_pressed_snap_angle

    @property
    def snap_to_grid_enabled(self) -> bool:
        return self._config.snap_to_grid_enabled

    @property
    def snap_to_grid_threshold_px(self) -> int:
        return self._config.snap_to_grid_threshold_px

    @property
    def snap_to_pdf_lines_enabled(self) -> bool:
        return self._config.snap_to_pdf_lines_enabled

    @property
    def snap_to_pdf_lines_threshold_px(self) -> int:
        return self._config.snap_to_pdf_lines_threshold_px

    @property
    def snap_to_takeoffs_enabled(self) -> bool:
        return self._config.snap_to_takeoffs_enabled

    @property
    def snap_to_takeoffs_threshold_px(self) -> int:
        return self._config.snap_to_takeoffs_threshold_px

    @property
    def snap_to_right_angle_enabled(self) -> bool:
        return self._config.snap_to_right_angle_enabled

    @property
    def snap_to_right_angle_threshold_px(self) -> int:
        return self._config.snap_to_right_angle_threshold_px

    @property
    def default_text_font(self) -> FontDefinition:
        return self._config.default_text_font

    @property
    def default_area_label_font(self) -> FontDefinition:
        return self._config.default_area_label_font

    @property
    def default_dimension_annotation_font(self) -> FontDefinition:
        return self._config.default_dimension_annotation_font

    @property
    def default_style_label_font(self) -> FontDefinition:
        return self._config.default_style_label_font

    @property
    def default_text_color(self) -> str:
        return self._config.default_text_color

    @property
    def default_area_label_color(self) -> str:
        return self._config.default_area_label_color

    @property
    def default_dimension_annotation_color(self) -> str:
        return self._config.default_dimension_annotation_color

    @property
    def default_style_label_color(self) -> str:
        return self._config.default_style_label_color

    @property
    def default_highlight_color(self) -> str:
        return self._config.default_highlight_color

    @property
    def default_hotlink_color(self) -> str:
        return self._config.default_hotlink_color

    @property
    def inactive_object_color(self) -> str:
        return self._config.inactive_object_color

    def snapshot(self) -> Config:
        return replace(self._config)

    def _load_config(self) -> None:
        try:
            config = self.repository.load()
            self._apply_config(config)
        except FileNotFoundError:
            self._reset_to_defaults(save=True)
        except (TypeError, ValueError) as exc:
            self.logger.error("%s; resetting to defaults", exc)
            self._reset_to_defaults(save=True)
        except OSError as exc:
            self.logger.error("Error reading configuration: %s", exc)
            self._reset_to_defaults(save=False)

    def _apply_config(self, config: Config, *, save_corrections: bool = True) -> None:
        display_mode_3d, mode_3d_changed = self._validated_display_mode(
            config.display_mode_3d,
            "display_mode_3d",
        )
        display_mode_2d, mode_2d_changed = self._validated_display_mode(
            config.display_mode_2d,
            "display_mode_2d",
        )
        display_modes_synced = bool(config.display_modes_synced)
        config_changed = mode_3d_changed or mode_2d_changed
        if display_modes_synced and display_mode_2d != display_mode_3d:
            display_mode_2d = display_mode_3d
            config_changed = True
        roping_selection_method = config.roping_selection_method
        if roping_selection_method not in self.VALID_ROPING_SELECTION_METHODS:
            self.logger.warning(
                "Invalid roping_selection_method '%s' in config; using default '%s'",
                config.roping_selection_method,
                Config.DEFAULT_ROPING_SELECTION_METHOD,
            )
            roping_selection_method = Config.DEFAULT_ROPING_SELECTION_METHOD
            config_changed = True
        hotlink_target = config.hotlink_target
        if hotlink_target not in self.VALID_HOTLINK_TARGETS:
            self.logger.warning(
                "Invalid hotlink_target '%s' in config; using default '%s'",
                config.hotlink_target,
                Config.DEFAULT_HOTLINK_TARGET,
            )
            hotlink_target = Config.DEFAULT_HOTLINK_TARGET
            config_changed = True
        auto_zoom_level = int(config.default_auto_zoom_level)
        if auto_zoom_level < self.MIN_AUTO_ZOOM_LEVEL:
            auto_zoom_level = self.MIN_AUTO_ZOOM_LEVEL
            config_changed = True
        elif auto_zoom_level > self.MAX_AUTO_ZOOM_LEVEL:
            auto_zoom_level = self.MAX_AUTO_ZOOM_LEVEL
            config_changed = True
        colors, colors_changed = self._validated_color_fields(config)
        if colors_changed:
            config_changed = True
        fonts, fonts_changed = self._validated_font_fields(config)
        if fonts_changed:
            config_changed = True
        crosshair_line_thickness = int(config.crosshair_line_thickness)
        if crosshair_line_thickness < self.MIN_CROSSHAIR_LINE_THICKNESS:
            crosshair_line_thickness = self.MIN_CROSSHAIR_LINE_THICKNESS
            config_changed = True
        elif crosshair_line_thickness > self.MAX_CROSSHAIR_LINE_THICKNESS:
            crosshair_line_thickness = self.MAX_CROSSHAIR_LINE_THICKNESS
            config_changed = True
        mouse_unpressed_snap_angle = self._validated_snap_angle(
            config.mouse_unpressed_snap_angle,
            Config.DEFAULT_MOUSE_UNPRESSED_SNAP_ANGLE,
        )
        if mouse_unpressed_snap_angle != config.mouse_unpressed_snap_angle:
            config_changed = True
        mouse_pressed_snap_angle = self._validated_snap_angle(
            config.mouse_pressed_snap_angle,
            Config.DEFAULT_MOUSE_PRESSED_SNAP_ANGLE,
        )
        if mouse_pressed_snap_angle != config.mouse_pressed_snap_angle:
            config_changed = True
        snap_thresholds, snap_thresholds_changed = self._validated_snap_thresholds(
            config
        )
        if snap_thresholds_changed:
            config_changed = True
        caption_ids = tuple(
            caption_id
            for caption_id in SUPPORTED_ANNOTATION_CAPTION_IDS
            if caption_id in config.pdf_annotation_caption_ids
        )
        if caption_ids != config.pdf_annotation_caption_ids:
            self.logger.warning(
                "Invalid or duplicate PDF annotation caption identifiers in config; "
                "using the supported identifiers in canonical order"
            )
            config_changed = True
        validated = Config(
            display_modes_synced=display_modes_synced,
            display_mode_3d=display_mode_3d,
            display_mode_2d=display_mode_2d,
            grayscale_enabled=bool(config.grayscale_enabled),
            roping_selection_method=roping_selection_method,
            display_page_index_with_sheet_name=bool(
                config.display_page_index_with_sheet_name
            ),
            display_sheet_number_with_sheet_name=bool(
                config.display_sheet_number_with_sheet_name
            ),
            hotlink_target=hotlink_target,
            show_toolbar_text=bool(config.show_toolbar_text),
            disable_high_resolution_images=bool(config.disable_high_resolution_images),
            enable_intelligent_paste=bool(config.enable_intelligent_paste),
            enable_advanced_mouse_controls=bool(config.enable_advanced_mouse_controls),
            default_auto_zoom_level=auto_zoom_level,
            use_full_window_crosshairs=bool(config.use_full_window_crosshairs),
            crosshair_color=colors["crosshair_color"],
            crosshair_line_thickness=crosshair_line_thickness,
            allow_add_page_from_takeoff_tab=bool(
                config.allow_add_page_from_takeoff_tab
            ),
            mouse_unpressed_snap_angle=mouse_unpressed_snap_angle,
            mouse_pressed_snap_angle=mouse_pressed_snap_angle,
            snap_to_grid_enabled=bool(config.snap_to_grid_enabled),
            snap_to_grid_threshold_px=snap_thresholds["snap_to_grid_threshold_px"],
            snap_to_pdf_lines_enabled=bool(config.snap_to_pdf_lines_enabled),
            snap_to_pdf_lines_threshold_px=(
                snap_thresholds["snap_to_pdf_lines_threshold_px"]
            ),
            snap_to_takeoffs_enabled=bool(config.snap_to_takeoffs_enabled),
            snap_to_takeoffs_threshold_px=(
                snap_thresholds["snap_to_takeoffs_threshold_px"]
            ),
            snap_to_right_angle_enabled=bool(config.snap_to_right_angle_enabled),
            snap_to_right_angle_threshold_px=(
                snap_thresholds["snap_to_right_angle_threshold_px"]
            ),
            pdf_annotation_captions_enabled=bool(
                config.pdf_annotation_captions_enabled
            ),
            pdf_annotation_caption_ids=caption_ids,
            html_elevation_callouts_enabled=bool(
                config.html_elevation_callouts_enabled
            ),
            pdf_elevation_callouts_enabled=bool(config.pdf_elevation_callouts_enabled),
            elevation_callout_include_condition=bool(
                config.elevation_callout_include_condition
            ),
            elevation_callout_include_top=bool(config.elevation_callout_include_top),
            elevation_callout_include_bottom=bool(
                config.elevation_callout_include_bottom
            ),
            elevation_callout_include_cubic_yards=bool(
                config.elevation_callout_include_cubic_yards
            ),
            html_elevation_callout_color=colors["html_elevation_callout_color"],
            pdf_elevation_callout_color=colors["pdf_elevation_callout_color"],
            default_text_font=fonts["default_text_font"],
            default_area_label_font=fonts["default_area_label_font"],
            default_dimension_annotation_font=(
                fonts["default_dimension_annotation_font"]
            ),
            default_style_label_font=fonts["default_style_label_font"],
            default_text_color=colors["default_text_color"],
            default_area_label_color=colors["default_area_label_color"],
            default_dimension_annotation_color=(
                colors["default_dimension_annotation_color"]
            ),
            default_style_label_color=colors["default_style_label_color"],
            default_highlight_color=colors["default_highlight_color"],
            default_hotlink_color=colors["default_hotlink_color"],
            inactive_object_color=colors["inactive_object_color"],
        )
        self._config = validated
        if config_changed and save_corrections:
            try:
                self._save_config()
            except OSError:
                self.logger.warning("Failed to save corrected config", exc_info=True)

    def _save_config(self) -> None:
        try:
            self.repository.save(self._config)
        except OSError as exc:
            self.logger.error("Error saving configuration: %s", exc)
            raise

    def _reset_to_defaults(self, save: bool) -> None:
        self._config = Config()
        if save:
            try:
                self.repository.save(self._config)
            except OSError as exc:
                self.logger.exception(
                    "Failed to save default configuration to %s: %s",
                    self.repository.config_path,
                    exc,
                )

    def update_options(self, config: Config) -> list[str]:
        previous = self._config.to_dict()
        self._apply_config(config, save_corrections=False)
        current = self._config.to_dict()
        changed = [key for key, value in current.items() if previous.get(key) != value]
        if changed:
            self._save_config()
        return changed

    def _validated_snap_angle(self, value: int, default: int) -> int:
        angle = int(value)
        if angle in self.VALID_MOUSE_SNAP_ANGLES:
            return angle
        self.logger.warning(
            "Invalid mouse snap angle '%s' in config; using default '%s'",
            value,
            default,
        )
        return default

    def _validated_display_mode(self, value: str, field_name: str) -> tuple[str, bool]:
        display_mode = str(value)
        if display_mode in self.VALID_DISPLAY_MODES:
            return display_mode, False
        self.logger.warning(
            "Invalid %s '%s' in config; using default '%s'",
            field_name,
            value,
            Config.DEFAULT_DISPLAY_MODE,
        )
        return Config.DEFAULT_DISPLAY_MODE, True

    def _validated_snap_threshold_px(
        self, value: int, default: int, field_name: str
    ) -> int:
        threshold = int(value)
        if self.MIN_SNAP_THRESHOLD_PX <= threshold <= self.MAX_SNAP_THRESHOLD_PX:
            return threshold
        self.logger.warning(
            "Invalid %s '%s' in config; using default '%s'",
            field_name,
            value,
            default,
        )
        return default

    def _validated_snap_thresholds(self, config: Config) -> tuple[dict[str, int], bool]:
        raw_thresholds = {
            "snap_to_grid_threshold_px": config.snap_to_grid_threshold_px,
            "snap_to_pdf_lines_threshold_px": config.snap_to_pdf_lines_threshold_px,
            "snap_to_takeoffs_threshold_px": config.snap_to_takeoffs_threshold_px,
            "snap_to_right_angle_threshold_px": (
                config.snap_to_right_angle_threshold_px
            ),
        }
        validated = {}
        changed = False
        for field_name, value in raw_thresholds.items():
            threshold = self._validated_snap_threshold_px(
                value,
                Config.DEFAULT_SNAP_THRESHOLD_PX,
                field_name,
            )
            validated[field_name] = threshold
            if threshold != value:
                changed = True
        return validated, changed

    def _validated_color_fields(self, config: Config) -> tuple[dict[str, str], bool]:
        color_fields = (
            (
                "crosshair_color",
                config.crosshair_color,
                Config.DEFAULT_CROSSHAIR_COLOR,
            ),
            (
                "html_elevation_callout_color",
                config.html_elevation_callout_color,
                Config.DEFAULT_ELEVATION_CALLOUT_COLOR,
            ),
            (
                "pdf_elevation_callout_color",
                config.pdf_elevation_callout_color,
                Config.DEFAULT_ELEVATION_CALLOUT_COLOR,
            ),
            (
                "default_text_color",
                config.default_text_color,
                Config.DEFAULT_TEXT_COLOR,
            ),
            (
                "default_area_label_color",
                config.default_area_label_color,
                Config.DEFAULT_AREA_LABEL_COLOR,
            ),
            (
                "default_dimension_annotation_color",
                config.default_dimension_annotation_color,
                Config.DEFAULT_DIMENSION_ANNOTATION_COLOR,
            ),
            (
                "default_style_label_color",
                config.default_style_label_color,
                Config.DEFAULT_STYLE_LABEL_COLOR,
            ),
            (
                "default_highlight_color",
                config.default_highlight_color,
                Config.DEFAULT_HIGHLIGHT_COLOR,
            ),
            (
                "default_hotlink_color",
                config.default_hotlink_color,
                Config.DEFAULT_HOTLINK_COLOR,
            ),
            (
                "inactive_object_color",
                config.inactive_object_color,
                Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            ),
        )
        colors = {}
        changed = False
        for field_name, raw_color, default in color_fields:
            color = self._validated_hex_color(raw_color, default, field_name)
            colors[field_name] = color
            if color != raw_color:
                changed = True
        return colors, changed

    def _validated_font_fields(
        self, config: Config
    ) -> tuple[dict[str, FontDefinition], bool]:
        font_fields = (
            ("default_text_font", config.default_text_font, Config.DEFAULT_TEXT_FONT),
            (
                "default_area_label_font",
                config.default_area_label_font,
                Config.DEFAULT_AREA_LABEL_FONT,
            ),
            (
                "default_dimension_annotation_font",
                config.default_dimension_annotation_font,
                Config.DEFAULT_DIMENSION_ANNOTATION_FONT,
            ),
            (
                "default_style_label_font",
                config.default_style_label_font,
                Config.DEFAULT_STYLE_LABEL_FONT,
            ),
        )
        fonts: dict[str, FontDefinition] = {}
        changed = False
        for field_name, value, default in font_fields:
            font, font_changed = self._validated_font_definition(
                value, default, field_name
            )
            fonts[field_name] = font
            changed = changed or font_changed
        return fonts, changed

    def _validated_font_definition(
        self,
        value: FontDefinition,
        default: FontDefinition,
        field_name: str,
    ) -> tuple[FontDefinition, bool]:
        valid = (
            isinstance(value, FontDefinition)
            and isinstance(value.family, str)
            and bool(value.family.strip())
            and isinstance(value.style_name, str)
            and bool(value.style_name.strip())
            and type(value.point_size) is int
            and 1 <= value.point_size <= 144
            and type(value.weight) is int
            and value.weight in (400, 700)
            and type(value.italic) is bool
            and type(value.underline) is bool
        )
        if not valid:
            self.logger.warning(
                "Invalid %s '%s' in config; using canonical default",
                field_name,
                value,
            )
            return default, True
        normalized = replace(
            value,
            family=value.family.strip(),
            style_name=value.style_name.strip(),
        )
        return normalized, normalized != value

    def _validated_hex_color(self, value: str, default: str, field_name: str) -> str:
        color = value.strip() if isinstance(value, str) else ""
        if (
            len(color) == 7
            and color[0] == "#"
            and all(ch in "0123456789abcdefABCDEF" for ch in color[1:])
        ):
            return color.lower()
        self.logger.warning(
            "Invalid %s '%s' in config; using default '%s'",
            field_name,
            value,
            default,
        )
        return default
