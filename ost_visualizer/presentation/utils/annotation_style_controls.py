from __future__ import annotations
from collections.abc import Callable, Mapping
from PySide6 import QtCore, QtGui, QtWidgets
from ...domain.entities.annotation_style import AnnotationStyle
from ..managers.icon_manager import IconManager
from .annotation_defaults import get_annotation_style_for_tool
from .plan_tool_registry import PLAN_ANNOTATION_TOOL_SPECS

StyleGetter = Callable[[], AnnotationStyle]
StyleSetter = Callable[..., AnnotationStyle]


def apply_annotation_tool_icon_color(
    targets: Mapping[str, QtGui.QAction | QtWidgets.QAbstractButton],
    annotation_type: str | None = None,
) -> None:
    for spec in PLAN_ANNOTATION_TOOL_SPECS:
        if annotation_type is not None and spec.annotation_type != annotation_type:
            continue
        target = targets.get(spec.action_key)
        if target is not None:
            style_color = get_annotation_style_for_tool(spec.annotation_type).color
            IconManager.apply_colored(target, spec.icon_id, style_color)


def create_annotation_style_menu(
    parent: QtWidgets.QWidget,
    get_style: StyleGetter,
    set_style: StyleSetter,
    *,
    annotation_type: str | None = None,
) -> QtWidgets.QMenu:
    if get_style is None:
        raise ValueError("Annotation style menu requires a tool-specific getter")
    if set_style is None:
        raise ValueError("Annotation style menu requires a tool-specific setter")
    menu = QtWidgets.QMenu(parent)
    menu.setProperty("annotationDefaultStyleMenu", True)
    width_group = QtGui.QActionGroup(menu)
    width_group.setExclusive(True)
    width_actions: dict[int, QtGui.QAction] = {}

    def _apply_default_width(width: int) -> None:
        set_style(line_width=float(width))
        _refresh_checked_width()

    for width in range(1, 17):
        action = QtGui.QAction(f"{width}px", menu)
        action.setCheckable(True)
        action.setData(width)
        width_group.addAction(action)
        menu.addAction(action)
        action.triggered.connect(
            lambda _checked=False, selected_width=width: _apply_default_width(
                selected_width
            )
        )
        width_actions[width] = action
    menu.addSeparator()
    color_action = QtGui.QAction("Select Color...", menu)
    menu.addAction(color_action)

    def _refresh_checked_width() -> None:
        style = get_style()
        width = int(round(style.line_width))
        for option_width, action in width_actions.items():
            action.setChecked(option_width == width)

    def _on_menu_about_to_show() -> None:
        _refresh_checked_width()

    def _choose_default_color() -> None:
        style = get_style()
        color = QtWidgets.QColorDialog.getColor(QtGui.QColor(style.color), parent)
        if color.isValid():
            set_style(color=color.name())
        _refresh_checked_width()

    color_action.triggered.connect(lambda _checked=False: _choose_default_color())
    menu.aboutToShow.connect(_on_menu_about_to_show)
    _refresh_checked_width()
    return menu


def create_annotation_style_button(
    parent: QtWidgets.QWidget,
    get_style: StyleGetter,
    set_style: StyleSetter,
    *,
    icon_size: QtCore.QSize | None = None,
    annotation_type: str | None = None,
) -> QtWidgets.QToolButton:
    if get_style is None:
        raise ValueError("Annotation style button requires a tool-specific getter")
    if set_style is None:
        raise ValueError("Annotation style button requires a tool-specific setter")
    button = QtWidgets.QToolButton(parent)
    button.setArrowType(QtCore.Qt.ArrowType.DownArrow)
    button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
    button.setToolTip("Default annotation style")
    button.setAutoRaise(True)
    button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
    button.setProperty("annotationStyleDropdown", True)
    button.setProperty("annotationDefaultStyleDropdown", True)
    button.setStyleSheet(
        """
        QToolButton {
            padding: 0px;
            margin: 0px;
        }
        QToolButton::menu-indicator {
            image: none;
            width: 0px;
            height: 0px;
        }
        """
    )
    if icon_size is not None:
        button.setIconSize(icon_size)
        button.setFixedWidth(max(14, min(18, icon_size.width() // 2 + 4)))
    menu = create_annotation_style_menu(
        button,
        get_style,
        set_style,
        annotation_type=annotation_type,
    )
    button.setMenu(menu)
    return button


def create_annotation_tool_split_button(
    parent: QtWidgets.QWidget,
    tool_button: QtWidgets.QToolButton,
    get_style: StyleGetter,
    set_style: StyleSetter,
    *,
    icon_size: QtCore.QSize | None = None,
    annotation_type: str | None = None,
) -> tuple[QtWidgets.QWidget, QtWidgets.QToolButton]:
    container = QtWidgets.QWidget(parent)
    container.setProperty("annotationToolSplitButton", True)
    layout = QtWidgets.QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    tool_button.setParent(container)
    tool_button.setAutoRaise(True)
    tool_button.setProperty("annotationToolMainButton", True)
    if icon_size is not None:
        tool_button.setIconSize(icon_size)
    dropdown = create_annotation_style_button(
        container,
        get_style,
        set_style,
        icon_size=icon_size,
        annotation_type=annotation_type,
    )
    layout.addWidget(tool_button)
    layout.addWidget(dropdown)
    return container, dropdown
