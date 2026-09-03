from typing import Dict, Iterable, List, Tuple


class EventCoordinator:
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self._subscriptions: List[Tuple[type, callable]] = []

    def register(self, event_type: type, callback) -> None:
        self.event_bus.subscribe(event_type, callback)
        self._subscriptions.append((event_type, callback))

    def register_many(
        self, subscriptions: Dict[type, callable] | Iterable[Tuple[type, callable]]
    ) -> None:
        if isinstance(subscriptions, dict):
            items = subscriptions.items()
        else:
            items = subscriptions
        for event_type, callback in items:
            self.register(event_type, callback)

    def cleanup(self) -> None:
        event_bus = self.event_bus
        subscriptions = tuple(self._subscriptions)
        errors = []
        failed_subscriptions = []
        if event_bus is not None:
            for event_type, callback in subscriptions:
                try:
                    event_bus.unsubscribe(event_type, callback)
                except Exception as exc:
                    errors.append(exc)
                    failed_subscriptions.append((event_type, callback))
        self._subscriptions = failed_subscriptions
        self.event_bus = event_bus if failed_subscriptions else None
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise ExceptionGroup("EventBus subscription cleanup failed", errors)
