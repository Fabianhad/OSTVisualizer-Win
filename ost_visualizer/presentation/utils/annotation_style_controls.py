from __future__ import annotations
from collections.abc import Callable, Mapping
from PySide6 import QtCore, QtGui, QtWidgets
from ...domain.entities.annotation_style import AnnotationStyle
from ..managers.icon_manager import IconManager
from .annotation_defaults import get_annotation_style
from .plan_tool_registry import PLAN_ANNOTATION_TOOL_SPECS

StyleGetter = Callable[[], AnnotationStyle]
StyleSetter = Callable[..., AnnotationStyle | None]


def apply_annotation_tool_icon_color(
    targets: Mapping[str, QtGui.QAction | QtWidgets.QAbstractButton],
    color: str | None = None,
) -> None:
    style_color = color or get_annotation_style().color
    for spec in PLAN_ANNOTATION_TOOL_SPECS:
        target = targets.get(spec.action_key)
        if target is not None:
            IconManager.apply_colored(target, spec.icon_id, style_color)


def create_annotation_style_menu(
    parent: QtWidgets.QWidget,
    get_style: StyleGetter | None = None,
    set_style: StyleSetter | None = None,
) -> QtWidgets.QMenu:
    get_style = get_style or get_annotation_style
    menu = QtWidgets.QMenu(parent)
    width_group = QtGui.QActionGroup(menu)
    width_group.setExclusive(True)
    width_actions: dict[int, QtGui.QAction] = {}

    def _apply_width(width: int) -> None:
        if set_style is not None:
            set_style(line_width=float(width))
        _refresh_checked_width()

    for width in range(1, 17):
        action = QtGui.QAction(f"{width}px", menu)
        action.setCheckable(True)
        action.setData(width)
        width_group.addAction(action)
        menu.addAction(action)
        action.triggered.connect(
            lambda _checked=False, selected_width=width: _apply_width(selected_width)
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

    def _choose_color() -> None:
        style = get_style()
        color = QtWidgets.QColorDialog.getColor(QtGui.QColor(style.color), parent)
        if color.isValid() and set_style is not None:
            set_style(color=color.name())
        _refresh_checked_width()

    color_action.triggered.connect(lambda _checked=False: _choose_color())
    menu.aboutToShow.connect(_refresh_checked_width)
    _refresh_checked_width()
    return menu


def create_annotation_style_button(
    parent: QtWidgets.QWidget,
    get_style: StyleGetter | None = None,
    set_style: StyleSetter | None = None,
    *,
    icon_size: QtCore.QSize | None = None,
) -> QtWidgets.QToolButton:
    button = QtWidgets.QToolButton(parent)
    button.setArrowType(QtCore.Qt.ArrowType.DownArrow)
    button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
    button.setToolTip("Annotation style")
    button.setAutoRaise(True)
    button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
    button.setProperty("annotationStyleDropdown", True)
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
    menu = create_annotation_style_menu(button, get_style, set_style)
    button.setMenu(menu)
    return button


def create_annotation_tool_split_button(
    parent: QtWidgets.QWidget,
    tool_button: QtWidgets.QToolButton,
    get_style: StyleGetter | None = None,
    set_style: StyleSetter | None = None,
    *,
    icon_size: QtCore.QSize | None = None,
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
        container, get_style, set_style, icon_size=icon_size
    )
    layout.addWidget(tool_button)
    layout.addWidget(dropdown)
    return container, dropdown
