from typing import Any
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ..configurators.window_configurator import set_window_icon


class QtWindowIconProvider(IWindowIconProvider):
    def set_window_icon(self, widget: Any) -> None:
        set_window_icon(widget)
