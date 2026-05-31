from dataclasses import dataclass
from PySide6 import QtGui, QtWidgets
from ...domain.entities.condition import Condition
from ..config import (
    ACTION_PAN_LABEL,
    ACTION_PLACE_LABEL,
    ACTION_RESET_VIEW_LABEL,
    ACTION_SELECT_LABEL,
    ACTION_ZOOM_IN_LABEL,
    ACTION_ZOOM_LABEL,
    ACTION_ZOOM_OUT_LABEL,
)
from ..managers.context_menu_manager import ContextMenuManager
from .condition_icon import make_condition_color_icon
from .overlay_context_menu import add_overlay_submenu_with_select

CONTEXT_TOOLS_ACTIONS = (
    (ACTION_SELECT_LABEL, "select_tool"),
    (ACTION_PLACE_LABEL, "place_tool"),
    (ACTION_ZOOM_LABEL, "zoom_tool"),
    (ACTION_PAN_LABEL, "pan_tool"),
    None,
    ("Backout", "backout_mode"),
)
CONTEXT_ZOOM_ACTIONS = (
    (ACTION_ZOOM_IN_LABEL, "zoom_in"),
    (ACTION_ZOOM_OUT_LABEL, "zoom_out"),
    (ACTION_RESET_VIEW_LABEL, "reset_view"),
)
CONTEXT_ROTATE_FLIP_ACTIONS = (
    ("Rotate Takeoff Left", "rotate_takeoff_left"),
    ("Rotate Takeoff Right", "rotate_takeoff_right"),
    ("Flip Takeoff Horizontal", "flip_takeoff_horizontal"),
    ("Flip Takeoff Vertical", "flip_takeoff_vertical"),
    None,
    ("Rotate Image Left", "rotate_image_left"),
    ("Rotate Image Right", "rotate_image_right"),
    ("Flip Image Horizontal", "flip_image_horizontal"),
    ("Flip Image Vertical", "flip_image_vertical"),
)
CONTEXT_CLIPBOARD_ACTIONS = (
    ("Cut", "cut"),
    ("Copy", "copy"),
    ("Paste", "paste"),
    ("Delete", "delete"),
)


@dataclass(frozen=True)
class SelectedTakeoffContextState:
    takeoff_uids: list[str]
    show_assign: bool
    show_negative: bool
    show_curved: bool
    all_negative: bool
    all_curved: bool


@dataclass(frozen=True)
class ReassignConditionSubmenu:
    submenu: QtWidgets.QMenu
    actions: dict[QtGui.QAction, str]


def build_selected_takeoff_context_state(
    takeoff_uids: list[str],
    resolve_takeoff,
    conditions: dict,
) -> SelectedTakeoffContextState:
    selected_takeoffs = []
    regular_takeoffs = []
    hole_takeoffs = []
    for uid in takeoff_uids:
        takeoff = resolve_takeoff(uid)
        if takeoff is None:
            continue
        selected_takeoffs.append((uid, takeoff))
        if takeoff.is_hole:
            hole_takeoffs.append((uid, takeoff))
        else:
            regular_takeoffs.append((uid, takeoff))
    single_linear = False
    all_curved = False
    if len(selected_takeoffs) == 1 and len(regular_takeoffs) == 1:
        _uid, takeoff = regular_takeoffs[0]
        condition = conditions.get(takeoff.condition_uid)
        single_linear = bool(condition and condition.is_linear and not condition.trim)
        all_curved = takeoff.curve >= 0
    return SelectedTakeoffContextState(
        takeoff_uids=[uid for uid, _takeoff in selected_takeoffs],
        show_assign=bool(regular_takeoffs),
        show_negative=bool(regular_takeoffs) and not hole_takeoffs,
        show_curved=single_linear,
        all_negative=bool(regular_takeoffs)
        and all(takeoff.is_negative for _uid, takeoff in regular_takeoffs),
        all_curved=all_curved,
    )


def context_command_state(action_state_fn, action_key: str, fallback_text: str) -> dict:
    if action_state_fn:
        state = dict(action_state_fn(action_key) or {})
    else:
        state = {}
    return {
        "text": state.get("text") or fallback_text,
        "enabled": bool(state.get("enabled", False)),
        "checkable": bool(state.get("checkable", False)),
        "checked": bool(state.get("checked", False)),
    }


def trigger_context_command(trigger_fn, action_key: str) -> None:
    if trigger_fn:
        trigger_fn(action_key)


def add_context_command(
    menu: QtWidgets.QMenu,
    label: str,
    action_key: str,
    trigger_fn,
    action_state_fn,
) -> QtGui.QAction:
    state = context_command_state(action_state_fn, action_key, label)
    return ContextMenuManager.add_action(
        menu,
        ContextMenuManager.action_spec(
            None,
            state["text"],
            callback=lambda key=action_key: trigger_context_command(trigger_fn, key),
            enabled=state["enabled"],
            checkable=state["checkable"],
            checked=state["checked"],
            action_key=action_key,
        ),
    )


def add_context_command_submenu(
    menu: QtWidgets.QMenu,
    title: str,
    entries: tuple,
    trigger_fn,
    action_state_fn,
) -> QtWidgets.QMenu:
    submenu = menu.addMenu(title)
    for entry in entries:
        if entry is None:
            submenu.addSeparator()
            continue
        label, action_key = entry
        add_context_command(submenu, label, action_key, trigger_fn, action_state_fn)
    return submenu


def _condition_menu_label(condition: Condition) -> str:
    name = condition.name or condition.uid
    if condition.ref_no:
        return f"{condition.ref_no} - {name}"
    return name


def add_reassign_condition_submenu(
    menu: QtWidgets.QMenu,
    conditions: dict[str, Condition],
) -> ReassignConditionSubmenu:
    submenu = menu.addMenu("Reassign Condition")
    actions: dict[QtGui.QAction, str] = {}
    ordered = sorted(
        conditions.values(),
        key=lambda condition: (
            condition.ref_no,
            condition.name.lower(),
            condition.uid,
        ),
    )
    if not ordered:
        submenu.setEnabled(False)
        return ReassignConditionSubmenu(submenu, actions)
    for condition in ordered:
        action = submenu.addAction(_condition_menu_label(condition))
        action.setIcon(
            make_condition_color_icon(
                condition.color_fill,
                condition.pattern,
                not condition.layer_visible,
            )
        )
        actions[action] = condition.uid
    return ReassignConditionSubmenu(submenu, actions)


def add_common_context_submenus(
    menu: QtWidgets.QMenu,
    current_mode: int,
    trigger_fn,
    action_state_fn,
    has_overlay_image: bool | None = None,
) -> tuple[QtGui.QAction, QtGui.QAction]:
    add_context_command_submenu(
        menu, "Tools", CONTEXT_TOOLS_ACTIONS, trigger_fn, action_state_fn
    )
    add_context_command_submenu(
        menu, "Zoom", CONTEXT_ZOOM_ACTIONS, trigger_fn, action_state_fn
    )
    add_context_command_submenu(
        menu,
        "Rotate/Flip",
        CONTEXT_ROTATE_FLIP_ACTIONS,
        trigger_fn,
        action_state_fn,
    )
    select_state = context_command_state(
        action_state_fn, "select_overlay_image", "Select Overlay Image"
    )
    original_state = context_command_state(
        action_state_fn, "show_original_image", "Show Original Image"
    )
    overlay_state = context_command_state(
        action_state_fn, "show_overlay_image", "Show Overlay Image"
    )
    if has_overlay_image is None:
        has_overlay_image = overlay_state["enabled"] or overlay_state["checked"]
    _select_overlay_action, overlay_action, original_action = (
        add_overlay_submenu_with_select(
            menu,
            current_mode,
            lambda: trigger_context_command(trigger_fn, "select_overlay_image"),
            select_state["enabled"],
            has_overlay_image,
            original_state["enabled"],
            overlay_state["enabled"],
        )
    )
    return overlay_action, original_action


def add_context_clipboard_actions(
    menu: QtWidgets.QMenu, trigger_fn, action_state_fn
) -> None:
    for label, action_key in CONTEXT_CLIPBOARD_ACTIONS:
        add_context_command(menu, label, action_key, trigger_fn, action_state_fn)


def add_context_page_actions(
    menu: QtWidgets.QMenu,
    trigger_fn,
    action_state_fn,
    separate_delete: bool = False,
) -> None:
    add_context_command(
        menu, "Rename Page...", "rename_page", trigger_fn, action_state_fn
    )
    if separate_delete:
        menu.addSeparator()
    add_context_command(menu, "Delete Page", "delete_page", trigger_fn, action_state_fn)
