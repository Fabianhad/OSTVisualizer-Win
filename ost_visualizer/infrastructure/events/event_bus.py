from collections import defaultdict
from typing import Any, Callable, Dict, List, Type
from ...application.interfaces.i_event_bus import IEventBus

EventType = Type[Any]
Subscription = tuple[Callable[..., None], object]


class EventBus(IEventBus):
    def __init__(self) -> None:
        self._subscribers: Dict[EventType, List[Subscription]] = defaultdict(list)

    def subscribe(self, event_type: EventType, callback: Callable[..., None]) -> None:
        self._subscribers[event_type].append((callback, object()))

    def unsubscribe(self, event_type: EventType, callback: Callable[..., None]) -> None:
        callbacks = self._subscribers.get(event_type)
        if not callbacks:
            return
        subscription = next(
            (item for item in callbacks if item[0] == callback),
            None,
        )
        if subscription is None:
            return
        callbacks.remove(subscription)
        if not callbacks:
            del self._subscribers[event_type]

    def publish(self, event_type: EventType, **data: Any) -> None:
        subscriptions = list(self._subscribers.get(event_type, []))
        if not subscriptions:
            return
        event = event_type(**data)
        payload = vars(event).copy()
        for subscription in subscriptions:
            if subscription not in self._subscribers.get(event_type, ()):
                continue
            callback = subscription[0]
            callback(**payload)
