from collections.abc import Mapping
from ...domain.aggregates.config_aggregate import ConfigAggregate
from ...domain.entities.config import Config
from ..events.app_events import AppEvents


class ConfigService:
    def __init__(self, config_model: ConfigAggregate, event_bus):
        self.config_model = config_model
        self.event_bus = event_bus

    def get_config_snapshot(self):
        return self.config_model.snapshot()

    def update_app_options(self, config):
        config = self._config_from_update(config)
        changed = self.config_model.update_options(config)
        if changed:
            current = self.config_model.snapshot().to_dict()
            self.event_bus.publish(
                AppEvents.APP_CONFIG_UPDATED,
                setting="options",
                value={key: current[key] for key in changed},
            )
        return changed

    def _config_from_update(self, config) -> Config:
        if isinstance(config, Config):
            return config
        if not isinstance(config, Mapping):
            raise TypeError("App config updates must be a Config or mapping")
        current = self.config_model.snapshot().to_dict()
        current.update(config)
        return Config.from_dict(current)
