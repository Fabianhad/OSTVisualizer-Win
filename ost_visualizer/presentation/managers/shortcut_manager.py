from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional
from PySide6 import QtCore, QtGui, QtWidgets
from ..actions.action_ids import (
    ACTION_ADJUST_IMAGES,
    ACTION_ANNOTATION_WINDOW,
    ACTION_COPY,
    ACTION_CUT,
    ACTION_DELETE,
    ACTION_DUPLICATE,
    ACTION_LAYERS_SIDEBAR,
    ACTION_NEXT_PAGE,
    ACTION_OPEN_FILES,
    ACTION_PASTE,
    ACTION_PREVIOUS_PAGE,
    ACTION_REDO,
    ACTION_SELECT_ALL,
    ACTION_UNDO,
)


class ShortcutId(Enum):
    OPEN_FILES = ACTION_OPEN_FILES
    SELECT_ALL = ACTION_SELECT_ALL
    COPY = ACTION_COPY
    CUT = ACTION_CUT
    PASTE = ACTION_PASTE
    DUPLICATE = ACTION_DUPLICATE
    DELETE = ACTION_DELETE
    UNDO = ACTION_UNDO
    REDO = ACTION_REDO
    NEXT_PAGE = ACTION_NEXT_PAGE
    PREVIOUS_PAGE = ACTION_PREVIOUS_PAGE
    LAYERS_SIDEBAR = ACTION_LAYERS_SIDEBAR
    ANNOTATION_WINDOW = ACTION_ANNOTATION_WINDOW
    ADJUST_IMAGES = ACTION_ADJUST_IMAGES


@dataclass(frozen=True)
class ShortcutSpec:
    sequence: str
    description: str


_SHORTCUTS = {
    ShortcutId.OPEN_FILES: ShortcutSpec("Ctrl+O", "Open files"),
    ShortcutId.SELECT_ALL: ShortcutSpec("Ctrl+A", "Select all"),
    ShortcutId.COPY: ShortcutSpec("Ctrl+C", "Copy"),
    ShortcutId.CUT: ShortcutSpec("Ctrl+X", "Cut"),
    ShortcutId.PASTE: ShortcutSpec("Ctrl+V", "Paste"),
    ShortcutId.DUPLICATE: ShortcutSpec("Ctrl+D", "Duplicate"),
    ShortcutId.DELETE: ShortcutSpec("Del", "Delete"),
    ShortcutId.UNDO: ShortcutSpec("Ctrl+Z", "Undo"),
    ShortcutId.REDO: ShortcutSpec("Ctrl+Y", "Redo"),
    ShortcutId.NEXT_PAGE: ShortcutSpec("PgDown", "Next page"),
    ShortcutId.PREVIOUS_PAGE: ShortcutSpec("PgUp", "Previous page"),
    ShortcutId.LAYERS_SIDEBAR: ShortcutSpec("Ctrl+L", "Toggle Layers Sidebar"),
    ShortcutId.ANNOTATION_WINDOW: ShortcutSpec(
        "Ctrl+2", "Toggle Annotation and View Window"
    ),
    ShortcutId.ADJUST_IMAGES: ShortcutSpec("Ctrl+I", "Adjust page images"),
}
_SHORTCUTS_BY_ACTION_KEY = {shortcut.value: shortcut for shortcut in _SHORTCUTS}
_TEXT_EDITING_WIDGETS = (
    QtWidgets.QLineEdit,
    QtWidgets.QTextEdit,
    QtWidgets.QPlainTextEdit,
    QtWidgets.QSpinBox,
    QtWidgets.QDoubleSpinBox,
)


class ShortcutManager:
    @staticmethod
    def spec(shortcut_id_or_action_key) -> Optional[ShortcutSpec]:
        shortcut_id = ShortcutManager._resolve_id(shortcut_id_or_action_key)
        return _SHORTCUTS.get(shortcut_id) if shortcut_id else None

    @staticmethod
    def sequence(shortcut_id_or_action_key) -> QtGui.QKeySequence:
        spec = ShortcutManager.spec(shortcut_id_or_action_key)
        return QtGui.QKeySequence(spec.sequence if spec else "")

    @staticmethod
    def apply_to_action(
        action: QtGui.QAction,
        shortcut_id_or_action_key,
    ) -> None:
        spec = ShortcutManager.spec(shortcut_id_or_action_key)
        if spec:
            action.setShortcut(QtGui.QKeySequence(spec.sequence))

    @staticmethod
    def register_shortcut(
        parent: QtWidgets.QWidget,
        shortcut_id_or_action_key,
        callback: Callable[[], None],
        context: QtCore.Qt.ShortcutContext = QtCore.Qt.ShortcutContext.WindowShortcut,
        ignore_when_text_input: bool = False,
    ) -> QtGui.QShortcut:
        spec = ShortcutManager.spec(shortcut_id_or_action_key)
        if spec is None:
            raise ValueError(f"Unknown shortcut: {shortcut_id_or_action_key}")
        shortcut = QtGui.QShortcut(QtGui.QKeySequence(spec.sequence), parent)
        shortcut.setContext(context)

        def on_activated() -> None:
            if (
                ignore_when_text_input
                and ShortcutManager.should_ignore_for_text_input()
            ):
                return
            callback()

        shortcut.activated.connect(on_activated)
        return shortcut

    @staticmethod
    def should_ignore_for_text_input(
        widget: Optional[QtWidgets.QWidget] = None,
    ) -> bool:
        focus_widget = widget or QtWidgets.QApplication.focusWidget()
        return ShortcutManager.is_text_editing_widget(focus_widget)

    @staticmethod
    def is_text_editing_widget(widget: Optional[QtWidgets.QWidget]) -> bool:
        if widget is None:
            return False
        if isinstance(widget, _TEXT_EDITING_WIDGETS):
            return True
        if isinstance(widget, QtWidgets.QComboBox):
            return widget.isEditable()
        return False

    @staticmethod
    def _resolve_id(shortcut_id_or_action_key) -> Optional[ShortcutId]:
        if isinstance(shortcut_id_or_action_key, ShortcutId):
            return shortcut_id_or_action_key
        return _SHORTCUTS_BY_ACTION_KEY.get(str(shortcut_id_or_action_key))
