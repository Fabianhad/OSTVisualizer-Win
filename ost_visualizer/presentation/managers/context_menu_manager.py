from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Sequence, Union
from PySide6 import QtGui, QtWidgets
from ..actions.action_ids import (
    ACTION_COPY,
    ACTION_PASTE,
    ACTION_SELECT_OVERLAY_IMAGE,
    ACTION_SHOW_ORIGINAL_IMAGE,
    ACTION_SHOW_OVERLAY_IMAGE,
)
from .icon_manager import IconManager
from .shortcut_manager import ShortcutManager


class ContextActionId(Enum):
    COPY = ACTION_COPY
    PASTE = ACTION_PASTE
    SELECT_OVERLAY_IMAGE = ACTION_SELECT_OVERLAY_IMAGE
    SHOW_OVERLAY_IMAGE = ACTION_SHOW_OVERLAY_IMAGE
    SHOW_ORIGINAL_IMAGE = ACTION_SHOW_ORIGINAL_IMAGE


@dataclass(frozen=True)
class ContextActionSpec:
    action_id: Optional[ContextActionId]
    text: str
    callback: Optional[Callable] = None
    enabled: bool = True
    checkable: bool = False
    checked: bool = False
    action_key: Optional[str] = None


@dataclass(frozen=True)
class ContextSeparatorSpec:
    """Marks a separator entry in a context-menu specification."""


ContextMenuEntry = Union[ContextActionSpec, ContextSeparatorSpec]


class ContextMenuManager:
    @staticmethod
    def action_spec(
        action_id: Optional[ContextActionId],
        text: str,
        callback: Optional[Callable] = None,
        enabled: bool = True,
        checkable: bool = False,
        checked: bool = False,
        action_key: Optional[str] = None,
    ) -> ContextActionSpec:
        return ContextActionSpec(
            action_id=action_id,
            text=text,
            callback=callback,
            enabled=enabled,
            checkable=checkable,
            checked=checked,
            action_key=action_key,
        )

    @staticmethod
    def separator() -> ContextSeparatorSpec:
        return ContextSeparatorSpec()

    @staticmethod
    def add_action(menu: QtWidgets.QMenu, spec: ContextActionSpec) -> QtGui.QAction:
        action = menu.addAction(spec.text)
        action_key = spec.action_key or (
            spec.action_id.value if spec.action_id else None
        )
        if action_key:
            ShortcutManager.apply_to_action(action, action_key)
            IconManager.apply_to_action(action, action_key)
        if spec.checkable:
            action.setCheckable(True)
            action.setChecked(spec.checked)
        action.setEnabled(spec.enabled)
        if spec.callback:
            action.triggered.connect(
                lambda _checked=False, callback=spec.callback: callback()
            )
        return action

    @staticmethod
    def add_command_action(
        menu: QtWidgets.QMenu,
        text: str,
        action_key: str,
        callback: Callable,
        enabled: bool = True,
        action_id: Optional[ContextActionId] = None,
    ) -> QtGui.QAction:
        spec = ContextMenuManager.action_spec(
            action_id,
            text=text,
            callback=callback,
            enabled=enabled,
            action_key=action_key,
        )
        return ContextMenuManager.add_action(menu, spec)

    @staticmethod
    def build(
        menu: QtWidgets.QMenu, entries: Sequence[ContextMenuEntry]
    ) -> dict[ContextActionId, QtGui.QAction]:
        actions: dict[ContextActionId, QtGui.QAction] = {}
        for entry in entries:
            if isinstance(entry, ContextSeparatorSpec):
                menu.addSeparator()
                continue
            action = ContextMenuManager.add_action(menu, entry)
            if entry.action_id is not None:
                actions[entry.action_id] = action
        return actions

    @staticmethod
    def add_submenu(
        menu: QtWidgets.QMenu,
        text: str,
        entries: Sequence[ContextMenuEntry],
    ) -> tuple[QtWidgets.QMenu, dict[ContextActionId, QtGui.QAction]]:
        submenu = QtWidgets.QMenu(text, menu)
        menu.addMenu(submenu)
        return submenu, ContextMenuManager.build(submenu, entries)
