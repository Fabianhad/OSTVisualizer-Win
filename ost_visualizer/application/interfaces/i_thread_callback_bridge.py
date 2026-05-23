from typing import Callable, Protocol


class IThreadCallbackBridge(Protocol):
    def request_callback(
        self, callback: Callable[[bool, str], None], success: bool, message: str
    ) -> None: ...
