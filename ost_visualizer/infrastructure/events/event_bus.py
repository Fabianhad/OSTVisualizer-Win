from collections import defaultdict
from typing import Any, Callable, Dict, List, Type
from ...application.interfaces.i_event_bus import IEventBus

EventType = Type[Any]


class EventBus(IEventBus):
    def __init__(self) -> None:
        self._subscribers: Dict[EventType, List[Callable[..., None]]] = defaultdict(
            list
        )

    def subscribe(self, event_type: EventType, callback: Callable[..., None]) -> None:
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: EventType, callback: Callable[..., None]) -> None:
        callbacks = self._subscribers.get(event_type)
        if not callbacks:
            return
        try:
            callbacks.remove(callback)
        except ValueError:
            return
        if not callbacks:
            del self._subscribers[event_type]

    def publish(self, event_type: EventType, **data: Any) -> None:
        callbacks = list(self._subscribers.get(event_type, []))
        if not callbacks:
            return
        event = event_type(**data)
        payload = vars(event).copy()
        for callback in callbacks:
            callback(**payload)
