import logging
from dataclasses import replace
from typing import Optional
from ..entities.config import Config
from ..repositories.i_config_repository import IConfigRepository


class ConfigAggregate:
    VALID_COLOR_MODES = frozenset(
        {
            Config.COLOR_MODE_SOLID,
            Config.COLOR_MODE_ORIGINAL,
            Config.COLOR_MODE_TRANSPARENT,
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
    def color_mode(self) -> str:
        return self._config.color_mode

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

    def _apply_config(self, config: Config) -> None:
        color_mode = config.color_mode
        config_changed = color_mode not in self.VALID_COLOR_MODES
        if config_changed:
            self.logger.warning(
                "Invalid color_mode '%s' in config; using default '%s'",
                config.color_mode,
                Config.DEFAULT_COLOR_MODE,
            )
            color_mode = Config.DEFAULT_COLOR_MODE
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
        crosshair_color = self._validated_crosshair_color(config.crosshair_color)
        if crosshair_color != config.crosshair_color:
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
        validated = Config(
            color_mode=color_mode,
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
            crosshair_color=crosshair_color,
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
        )
        self._config = validated
        if config_changed:
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
        self._apply_config(config)
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

    def _validated_crosshair_color(self, value: str) -> str:
        color = str(value or "").strip()
        if (
            len(color) == 7
            and color[0] == "#"
            and all(ch in "0123456789abcdefABCDEF" for ch in color[1:])
        ):
            return color.lower()
        self.logger.warning(
            "Invalid crosshair_color '%s' in config; using default '%s'",
            value,
            Config.DEFAULT_CROSSHAIR_COLOR,
        )
        return Config.DEFAULT_CROSSHAIR_COLOR
