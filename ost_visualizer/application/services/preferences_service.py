from ...domain.aggregates.config_aggregate import ConfigAggregate
from ..events.app_events import AppEvents


class PreferencesService:
    def __init__(self, config_model: ConfigAggregate, event_bus):
        self.config_model = config_model
        self.event_bus = event_bus

    def set_color_mode(self, color_mode: str):
        try:
            self.config_model.set_color_mode(color_mode)
            self.event_bus.publish(
                AppEvents.PREFERENCES_UPDATED, setting="color_mode", value=color_mode
            )
            return color_mode
        except ValueError:
            return self.config_model.color_mode

    def toggle_grayscale(self, value=None):
        if value is None:
            value = not self.config_model.grayscale_enabled
        self.config_model.set_grayscale_enabled(value)
        self.event_bus.publish(
            AppEvents.PREFERENCES_UPDATED, setting="grayscale_enabled", value=value
        )
        return value
