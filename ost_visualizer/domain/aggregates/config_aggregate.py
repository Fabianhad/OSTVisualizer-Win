import logging
from typing import Optional
from ..entities.config import Config
from ..repositories.i_config_repository import IConfigRepository


class ConfigAggregate:
    VALID_COLOR_MODES = {"Solid", "Original", "Transparent"}

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

    def _load_config(self) -> None:
        try:
            config = self.repository.load()
            self._apply_config(config)
        except FileNotFoundError:
            self._reset_to_defaults(save=True)
        except ValueError as exc:
            self.logger.error("%s; resetting to defaults", exc)
            self._reset_to_defaults(save=True)
        except OSError as exc:
            self.logger.error("Error reading configuration: %s", exc)
            self._reset_to_defaults(save=False)
        except Exception as exc:
            self.logger.exception("Unexpected error loading configuration: %s", exc)
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
        validated = Config(
            color_mode=color_mode,
            grayscale_enabled=bool(config.grayscale_enabled),
        )
        self._config = validated
        if config_changed:
            try:
                self._save_config()
            except Exception:
                self.logger.warning("Failed to save corrected config", exc_info=True)

    def _save_config(self) -> None:
        try:
            self.repository.save(self._config)
        except OSError as exc:
            self.logger.error("Error saving configuration: %s", exc)
            raise
        except Exception as exc:
            self.logger.exception("Unexpected error saving configuration: %s", exc)
            raise

    def _reset_to_defaults(self, save: bool) -> None:
        self._config = Config()
        if save:
            try:
                self.repository.save(self._config)
            except Exception as exc:
                self.logger.exception(
                    "Failed to save default configuration to %s: %s",
                    self.repository.config_path,
                    exc,
                )

    def set_color_mode(self, color_mode: str) -> None:
        if color_mode not in self.VALID_COLOR_MODES:
            raise ValueError(f"Invalid color mode: {color_mode}")
        self._config.color_mode = color_mode
        self._save_config()

    def set_grayscale_enabled(self, grayscale_enabled: bool) -> None:
        self._config.grayscale_enabled = bool(grayscale_enabled)
        self._save_config()
