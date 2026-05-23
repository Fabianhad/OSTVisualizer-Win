from typing import Any, Callable, Protocol, TypeVar

E = TypeVar("E")


class IEventBus(Protocol):
    def subscribe(self, event_type: type[E], callback: Callable[..., None]) -> None: ...
    def unsubscribe(
        self, event_type: type[E], callback: Callable[..., None]
    ) -> None: ...
    def publish(self, event_type: type[E], **data: Any) -> None: ...
