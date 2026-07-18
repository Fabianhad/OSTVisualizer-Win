from typing import Callable, Protocol, TypeVar

T = TypeVar("T")


class IThreadCallbackBridge(Protocol):
    def request_callback(
        self, callback: Callable[[bool, str], None], success: bool, message: str
    ) -> None: ...
    def dispatch(self, callback: Callable[[T], None], payload: T) -> None: ...
