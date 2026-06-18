import math
from dataclasses import dataclass
from PySide6 import QtGui, QtWidgets
from ...domain.entities.annotation import BidAnnotation
from ...domain.entities.condition import Condition
from ..config import (
    ACTION_RESET_VIEW_LABEL,
    ACTION_ZOOM_IN_LABEL,
    ACTION_ZOOM_OUT_LABEL,
)
from ..managers.context_menu_manager import ContextMenuManager
from .annotation_style_controls import apply_annotation_tool_icon_color
from .plan_tool_registry import PLAN_ANNOTATION_TOOL_SPECS, PLAN_TOOL_CONTEXT_ACTIONS
from .condition_icon import make_condition_color_icon
from .overlay_context_menu import add_overlay_submenu_with_select
from .takeoff_condition_compatibility import (
    common_reassign_geometry_type,
    condition_matches_reassign_geometry,
)

CONTEXT_TOOLS_ACTIONS = (
    *PLAN_TOOL_CONTEXT_ACTIONS,
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
    reassign_geometry_type: int | None = None


@dataclass(frozen=True)
class ReassignConditionSubmenu:
    submenu: QtWidgets.QMenu
    actions: dict[QtGui.QAction, str]


@dataclass(frozen=True)
class SelectedAnnotationStyleContextState:
    annotation_uids: list[str]
    show_color: bool
    show_line_width: bool
    current_line_width: float | None = None


@dataclass(frozen=True)
class AnnotationStyleContextActions:
    color_action: QtGui.QAction | None
    width_actions: dict[QtGui.QAction, float]


@dataclass(frozen=True)
class ContextCommandSubmenu:
    submenu: QtWidgets.QMenu
    actions_by_key: dict[str, QtGui.QAction]


_ANNOTATION_CONTEXT_GENERIC_STYLE_EXCLUDED_TYPES = frozenset(
    {"hotlink", "namedview", "text"}
)
_ANNOTATION_CONTEXT_WIDTH_EXCLUDED_TYPES = frozenset(
    {"dimension", "highlight", "hotlink", "namedview", "text"}
)
_ANNOTATION_CONTEXT_COLOR_TYPES = frozenset(
    spec.annotation_type
    for spec in PLAN_ANNOTATION_TOOL_SPECS
    if spec.annotation_type
    and spec.annotation_type not in _ANNOTATION_CONTEXT_GENERIC_STYLE_EXCLUDED_TYPES
)
_ANNOTATION_CONTEXT_WIDTH_TYPES = frozenset(
    spec.annotation_type
    for spec in PLAN_ANNOTATION_TOOL_SPECS
    if spec.annotation_type
    and spec.annotation_type not in _ANNOTATION_CONTEXT_WIDTH_EXCLUDED_TYPES
)


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
        reassign_geometry_type=common_reassign_geometry_type(
            (takeoff for _uid, takeoff in selected_takeoffs),
            conditions,
        ),
    )


def build_selected_annotation_style_context_state(
    annotation_uids: list[str],
    resolve_annotation,
) -> SelectedAnnotationStyleContextState:
    selected_annotations: list[BidAnnotation] = []
    selected_uids: list[str] = []
    for uid in annotation_uids:
        annotation = resolve_annotation(uid)
        if annotation is None:
            continue
        selected_annotations.append(annotation)
        selected_uids.append(uid)
    if not selected_annotations:
        return SelectedAnnotationStyleContextState([], False, False, None)
    annotation_types = {
        annotation.annotation_type for annotation in selected_annotations
    }
    show_line_width = annotation_types <= _ANNOTATION_CONTEXT_WIDTH_TYPES
    current_line_width = None
    if show_line_width:
        widths = [float(annotation.width) for annotation in selected_annotations]
        first_width = widths[0]
        if all(
            math.isclose(width, first_width, rel_tol=0.0, abs_tol=1e-6)
            for width in widths
        ):
            current_line_width = first_width
    return SelectedAnnotationStyleContextState(
        annotation_uids=selected_uids,
        show_color=annotation_types <= _ANNOTATION_CONTEXT_COLOR_TYPES,
        show_line_width=show_line_width,
        current_line_width=current_line_width,
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


def add_selected_annotation_style_actions(
    menu: QtWidgets.QMenu,
    state: SelectedAnnotationStyleContextState,
    *,
    select_color_callback,
    line_width_callback,
    enabled: bool,
) -> AnnotationStyleContextActions:
    color_action = None
    width_actions: dict[QtGui.QAction, float] = {}
    if state.show_line_width:
        line_width_menu = QtWidgets.QMenu("Line Width", menu)
        menu.addMenu(line_width_menu)
        width_group = QtGui.QActionGroup(line_width_menu)
        width_group.setExclusive(True)
        checked_width = None
        if state.current_line_width is not None:
            rounded_width = int(round(state.current_line_width))
            if 1 <= rounded_width <= 16 and math.isclose(
                state.current_line_width,
                float(rounded_width),
                rel_tol=0.0,
                abs_tol=1e-6,
            ):
                checked_width = rounded_width
        for width in range(1, 17):
            action = QtGui.QAction(f"{width}px", line_width_menu)
            action.setCheckable(True)
            action.setChecked(width == checked_width)
            action.setData(float(width))
            action.setEnabled(enabled)
            width_group.addAction(action)
            line_width_menu.addAction(action)
            action.triggered.connect(
                lambda _checked=False, selected_width=float(width): (
                    line_width_callback(selected_width)
                )
            )
            width_actions[action] = float(width)
    if state.show_color:
        color_action = ContextMenuManager.add_action(
            menu,
            ContextMenuManager.action_spec(
                None,
                "Select Color...",
                callback=select_color_callback,
                enabled=enabled,
            ),
        )
    return AnnotationStyleContextActions(color_action, width_actions)


def add_context_command_submenu(
    menu: QtWidgets.QMenu,
    title: str,
    entries: tuple,
    trigger_fn,
    action_state_fn,
) -> ContextCommandSubmenu:
    submenu = QtWidgets.QMenu(title, menu)
    menu.addMenu(submenu)
    actions_by_key: dict[str, QtGui.QAction] = {}
    for entry in entries:
        if entry is None:
            submenu.addSeparator()
            continue
        label, action_key = entry
        actions_by_key[action_key] = add_context_command(
            submenu, label, action_key, trigger_fn, action_state_fn
        )
    return ContextCommandSubmenu(submenu, actions_by_key)


def _condition_menu_label(condition: Condition) -> str:
    name = condition.name or condition.uid
    if condition.ref_no:
        return f"{condition.ref_no} - {name}"
    return name


def add_reassign_condition_submenu(
    menu: QtWidgets.QMenu,
    conditions: dict[str, Condition],
    reassign_geometry_type: int,
) -> ReassignConditionSubmenu:
    submenu = QtWidgets.QMenu("Reassign Condition", menu)
    actions: dict[QtGui.QAction, str] = {}
    ordered = sorted(
        (
            condition
            for condition in conditions.values()
            if condition_matches_reassign_geometry(condition, reassign_geometry_type)
        ),
        key=lambda condition: (
            condition.ref_no,
            condition.name.lower(),
            condition.uid,
        ),
    )
    if not ordered:
        return ReassignConditionSubmenu(submenu, actions)
    menu.addMenu(submenu)
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
    tools_submenu = add_context_command_submenu(
        menu, "Tools", CONTEXT_TOOLS_ACTIONS, trigger_fn, action_state_fn
    )
    apply_annotation_tool_icon_color(tools_submenu.actions_by_key)
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
