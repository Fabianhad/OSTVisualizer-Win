from typing import Any, Protocol


class IWindowIconProvider(Protocol):
    def set_window_icon(self, widget: Any) -> None: ...
