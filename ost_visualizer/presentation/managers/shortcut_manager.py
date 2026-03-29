from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional
from PySide6 import QtCore, QtGui, QtWidgets


class ShortcutId(Enum):
    OPEN_FILES = "open_files"
    SELECT_ALL = "select_all"
    COPY = "copy"
    CUT = "cut"
    PASTE = "paste"
    DUPLICATE = "duplicate"
    DELETE = "delete"
    UNDO = "undo"
    REDO = "redo"
    NEXT_PAGE = "next_page"
    PREVIOUS_PAGE = "previous_page"
    LAYERS_SIDEBAR = "layers_sidebar"
    ANNOTATION_WINDOW = "annotation_window"
    ADJUST_IMAGES = "adjust_images"


@dataclass(frozen=True)
class ShortcutSpec:
    sequence: str
    description: str
    scope: str


_SHORTCUTS = {
    ShortcutId.OPEN_FILES: ShortcutSpec("Ctrl+O", "Open files", "main_window"),
    ShortcutId.SELECT_ALL: ShortcutSpec("Ctrl+A", "Select all", "takeoff_or_menu"),
    ShortcutId.COPY: ShortcutSpec("Ctrl+C", "Copy", "focused_command"),
    ShortcutId.CUT: ShortcutSpec("Ctrl+X", "Cut", "focused_command"),
    ShortcutId.PASTE: ShortcutSpec("Ctrl+V", "Paste", "focused_command"),
    ShortcutId.DUPLICATE: ShortcutSpec("Ctrl+D", "Duplicate", "focused_command"),
    ShortcutId.DELETE: ShortcutSpec("Del", "Delete", "focused_command"),
    ShortcutId.UNDO: ShortcutSpec("Ctrl+Z", "Undo", "focused_command"),
    ShortcutId.REDO: ShortcutSpec("Ctrl+Y", "Redo", "focused_command"),
    ShortcutId.NEXT_PAGE: ShortcutSpec("PgDown", "Next page", "takeoff_tab"),
    ShortcutId.PREVIOUS_PAGE: ShortcutSpec("PgUp", "Previous page", "takeoff_tab"),
    ShortcutId.LAYERS_SIDEBAR: ShortcutSpec(
        "Ctrl+L", "Toggle Layers Sidebar", "takeoff_tab"
    ),
    ShortcutId.ANNOTATION_WINDOW: ShortcutSpec(
        "Ctrl+2", "Toggle Annotation and View Window", "takeoff_tab"
    ),
    ShortcutId.ADJUST_IMAGES: ShortcutSpec(
        "Ctrl+I", "Adjust page images", "takeoff_tab"
    ),
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
