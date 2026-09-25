from PySide6 import QtCore, QtWidgets
from ..utils.plan_tool_registry import TAKEOFF_TOOLBAR_ITEMS
from .toolbar_overflow import ToolbarOverflowWidgetAction, set_widget_action_visible


class TakeoffToolbarVisibilityController(QtCore.QObject):
    def __init__(
        self,
        toolbar: QtWidgets.QToolBar,
        items: dict[str, QtWidgets.QWidgetAction],
        navigation_spacer: QtWidgets.QWidgetAction,
    ) -> None:
        super().__init__(toolbar)
        if tuple(items) != tuple(spec.key for spec in TAKEOFF_TOOLBAR_ITEMS):
            raise ValueError(
                "Takeoff toolbar bindings must match its ordered item catalog"
            )
        self._toolbar = toolbar
        self._items = dict(items)
        self._navigation_spacer = navigation_spacer
        self._applying = False
        for key, action in self._items.items():
            action.setObjectName(key)
            action.visibleChanged.connect(self._normalize_layout)

    def apply_hidden_items(self, hidden: tuple[str, ...]) -> None:
        hidden_keys = set(hidden)
        self._applying = True
        try:
            for key, action in self._items.items():
                if isinstance(action, ToolbarOverflowWidgetAction):
                    action.set_toolbar_visible(key not in hidden_keys)
                else:
                    set_widget_action_visible(action, key not in hidden_keys)
        finally:
            self._applying = False
        self._normalize_layout()

    def _normalize_layout(self) -> None:
        if self._applying:
            return
        navigation = [
            self._items[spec.key].isVisible()
            for spec in TAKEOFF_TOOLBAR_ITEMS
            if spec.group == "Page navigation"
        ]
        remaining = [
            self._items[spec.key].isVisible()
            for spec in TAKEOFF_TOOLBAR_ITEMS
            if spec.group != "Page navigation"
        ]
        self._navigation_spacer.setVisible(any(navigation) and any(remaining))
        self._toolbar.setVisible(any(navigation) or any(remaining))
