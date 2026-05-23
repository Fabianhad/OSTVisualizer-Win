from PySide6 import QtGui, QtWidgets
from ..managers.context_menu_manager import ContextActionId, ContextMenuManager
from .image_show_mode import mode_to_flags, resolve_toggled_mode

IMAGE_FILE_FILTER = "Images (*.pdf *.tif *.tiff);;All Files (*)"


def select_overlay_image_path(parent: QtWidgets.QWidget, current_path: str = "") -> str:
    path, _ = QtWidgets.QFileDialog.getOpenFileName(
        parent,
        "Select Overlay Image",
        current_path,
        IMAGE_FILE_FILTER,
    )
    return path


def resolve_overlay_visibility_mode(
    current_mode: int, target: str, checked: bool
) -> int:
    return resolve_toggled_mode(current_mode, target, checked)


def _overlay_checked_state(
    current_mode: int, has_overlay_image: bool
) -> tuple[bool, bool]:
    show_original, show_overlay = mode_to_flags(current_mode)
    if not has_overlay_image:
        return True, False
    return show_original, show_overlay


def add_overlay_submenu(
    menu: QtWidgets.QMenu,
    current_mode: int,
    has_overlay_image: bool = True,
    show_original_enabled: bool = True,
    show_overlay_enabled: bool = True,
) -> tuple[QtGui.QAction, QtGui.QAction]:
    show_original, show_overlay = _overlay_checked_state(
        current_mode, has_overlay_image
    )
    _submenu, actions = ContextMenuManager.add_submenu(
        menu,
        "Overlay",
        (
            ContextMenuManager.action_spec(
                ContextActionId.SHOW_OVERLAY_IMAGE,
                "Show Overlay Image",
                enabled=show_overlay_enabled and has_overlay_image,
                checkable=True,
                checked=show_overlay,
            ),
            ContextMenuManager.action_spec(
                ContextActionId.SHOW_ORIGINAL_IMAGE,
                "Show Original Image",
                enabled=show_original_enabled,
                checkable=True,
                checked=show_original,
            ),
        ),
    )
    overlay_action = actions[ContextActionId.SHOW_OVERLAY_IMAGE]
    original_action = actions[ContextActionId.SHOW_ORIGINAL_IMAGE]
    return (overlay_action, original_action)


def add_overlay_submenu_with_select(
    menu: QtWidgets.QMenu,
    current_mode: int,
    select_callback,
    select_enabled: bool,
    has_overlay_image: bool,
    show_original_enabled: bool = True,
    show_overlay_enabled: bool = True,
) -> tuple[QtGui.QAction, QtGui.QAction, QtGui.QAction]:
    show_original, show_overlay = _overlay_checked_state(
        current_mode, has_overlay_image
    )
    _submenu, actions = ContextMenuManager.add_submenu(
        menu,
        "Overlay",
        (
            ContextMenuManager.action_spec(
                ContextActionId.SELECT_OVERLAY_IMAGE,
                "Select Overlay Image",
                callback=select_callback,
                enabled=select_enabled,
                action_key="select_overlay_image",
            ),
            ContextMenuManager.separator(),
            ContextMenuManager.action_spec(
                ContextActionId.SHOW_OVERLAY_IMAGE,
                "Show Overlay Image",
                enabled=show_overlay_enabled and has_overlay_image,
                checkable=True,
                checked=show_overlay,
            ),
            ContextMenuManager.action_spec(
                ContextActionId.SHOW_ORIGINAL_IMAGE,
                "Show Original Image",
                enabled=show_original_enabled,
                checkable=True,
                checked=show_original,
            ),
        ),
    )
    return (
        actions[ContextActionId.SELECT_OVERLAY_IMAGE],
        actions[ContextActionId.SHOW_OVERLAY_IMAGE],
        actions[ContextActionId.SHOW_ORIGINAL_IMAGE],
    )


def resolve_overlay_menu_action(
    action: QtGui.QAction,
    current_mode: int,
    overlay_action: QtGui.QAction,
    original_action: QtGui.QAction,
) -> int | None:
    if action == overlay_action:
        if not overlay_action.isEnabled():
            return None
        return resolve_overlay_visibility_mode(
            current_mode, "overlay", overlay_action.isChecked()
        )
    if action == original_action:
        if not original_action.isEnabled():
            return None
        if not overlay_action.isEnabled() and not original_action.isChecked():
            return None
        return resolve_overlay_visibility_mode(
            current_mode, "original", original_action.isChecked()
        )
    return None
