from collections.abc import Callable, Sequence
from typing import TypeVar
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import isValid

COMPACT_CONTEXT_MENU_MAX_VISIBLE_ROWS = 22
COMPACT_CONTEXT_MENU_PREVIOUS_TEXT = "▲"
COMPACT_CONTEXT_MENU_NEXT_TEXT = "▼"
_OVERFLOW_ACTION_ROLE = "__compact_context_menu_overflow__"
T = TypeVar("T")


class _OverflowMenuButton(QtWidgets.QPushButton):
    def __init__(self, text: str, parent: QtWidgets.QWidget):
        super().__init__(text, parent)
        self.setFlat(True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        self.setStyleSheet(
            "QPushButton {"
            " border: none;"
            " padding: 4px 24px;"
            " text-align: center;"
            " background: transparent;"
            "}"
            "QPushButton:hover, QPushButton:pressed, QPushButton:focus {"
            " background: transparent;"
            " color: palette(window-text);"
            "}"
        )


def _add_overflow_action(
    menu: QtWidgets.QMenu,
    text: str,
    target_start: int,
    render_page: Callable[[int], None],
) -> QtGui.QAction:
    action = QtWidgets.QWidgetAction(menu)
    action.setText(text)
    action.setData(_OVERFLOW_ACTION_ROLE)
    button = _OverflowMenuButton(text, menu)
    action.setDefaultWidget(button)
    menu.addAction(action)

    def _show_target_page() -> None:
        QtCore.QTimer.singleShot(
            0,
            lambda: render_page(target_start) if isValid(menu) else None,
        )

    button.clicked.connect(_show_target_page)
    return action


def _visible_window(item_count: int, start: int) -> tuple[int, int, bool, bool]:
    if item_count <= COMPACT_CONTEXT_MENU_MAX_VISIBLE_ROWS:
        return 0, item_count, False, False
    start = max(0, min(start, item_count - 1))
    has_previous = start > 0
    slots = COMPACT_CONTEXT_MENU_MAX_VISIBLE_ROWS - (1 if has_previous else 0)
    end = min(item_count, start + slots)
    has_next = end < item_count
    if has_next:
        slots -= 1
        end = min(item_count, start + slots)
    return start, end, has_previous, end < item_count


def populate_compact_context_menu(
    menu: QtWidgets.QMenu,
    items: Sequence[T],
    add_item_action: Callable[[QtWidgets.QMenu, T], QtGui.QAction],
) -> QtWidgets.QMenu:
    menu.setProperty("ost_compact_overflow_menu", True)
    menu.setProperty(
        "ost_compact_overflow_max_visible_rows",
        COMPACT_CONTEXT_MENU_MAX_VISIBLE_ROWS,
    )
    menu.setProperty("ost_compact_overflow_item_count", len(items))

    def render_page(start: int = 0) -> None:
        menu.clear()
        page_start, page_end, has_previous, has_next = _visible_window(
            len(items), start
        )
        page_size = max(1, page_end - page_start)
        if has_previous:
            previous_start = max(0, page_start - page_size)
            _add_overflow_action(
                menu, COMPACT_CONTEXT_MENU_PREVIOUS_TEXT, previous_start, render_page
            )
        for item in items[page_start:page_end]:
            add_item_action(menu, item)
        if has_next:
            _add_overflow_action(
                menu, COMPACT_CONTEXT_MENU_NEXT_TEXT, page_end, render_page
            )

    render_page()
    return menu
