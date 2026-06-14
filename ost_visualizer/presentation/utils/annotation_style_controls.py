from __future__ import annotations
from collections.abc import Callable, Mapping
from PySide6 import QtCore, QtGui, QtWidgets
from ...domain.entities.annotation_style import AnnotationStyle
from ..managers.icon_manager import IconId, IconManager
from .annotation_defaults import get_annotation_style_for_tool
from .plan_tool_registry import PLAN_ANNOTATION_TOOL_SPECS

StyleGetter = Callable[[], AnnotationStyle]
StyleSetter = Callable[..., AnnotationStyle]
_TEXT_FONT_SIZES = (8, 9, 10, 11, 12, 14, 16, 18, 24, 36)
_COLOR_ONLY_ANNOTATION_TYPES = frozenset({"highlight", "hotlink", "namedview"})


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
    if annotation_type == "text":
        return _create_font_annotation_style_menu(
            parent,
            get_style,
            set_style,
            include_alignment=True,
            color_label="Select Font Color...",
            menu_property="textAnnotationDefaultStyleMenu",
        )
    if annotation_type == "dimension":
        return _create_font_annotation_style_menu(
            parent,
            get_style,
            set_style,
            include_alignment=False,
            color_label="Select Color...",
            menu_property="dimensionAnnotationDefaultStyleMenu",
        )
    menu = QtWidgets.QMenu(parent)
    menu.setProperty("annotationDefaultStyleMenu", True)
    refresh_shape_width_actions = _add_shape_line_width_menu_items(
        menu, get_style, set_style
    )
    menu.addSeparator()
    color_action = QtGui.QAction("Select Color...", menu)
    menu.addAction(color_action)

    def _choose_default_color() -> None:
        style = get_style()
        color = QtWidgets.QColorDialog.getColor(QtGui.QColor(style.color), parent)
        if color.isValid():
            set_style(color=color.name())
        refresh_shape_width_actions()

    color_action.triggered.connect(lambda _checked=False: _choose_default_color())
    menu.aboutToShow.connect(refresh_shape_width_actions)
    refresh_shape_width_actions()
    return menu


def _add_shape_line_width_menu_items(
    menu: QtWidgets.QMenu,
    get_style: StyleGetter,
    set_style: StyleSetter,
) -> Callable[[], None]:
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

    def _refresh_checked_width() -> None:
        style = get_style()
        width = int(round(style.line_width))
        for option_width, action in width_actions.items():
            action.setChecked(option_width == width)

    return _refresh_checked_width


def _create_font_annotation_style_menu(
    parent: QtWidgets.QWidget,
    get_style: StyleGetter,
    set_style: StyleSetter,
    *,
    include_alignment: bool,
    color_label: str,
    menu_property: str,
) -> QtWidgets.QMenu:
    menu = QtWidgets.QMenu(parent)
    menu.setProperty("annotationDefaultStyleMenu", True)
    menu.setProperty("fontAnnotationDefaultStyleMenu", True)
    menu.setProperty(menu_property, True)
    menu_refs: list[object] = []
    font_action = QtWidgets.QWidgetAction(menu)
    font_combo = QtWidgets.QFontComboBox(menu)
    font_combo.setToolTip("Font family")
    font_action.setDefaultWidget(font_combo)
    menu.addAction(font_action)
    size_menu = menu.addMenu("Font Size")
    menu_refs.extend((font_combo, size_menu))
    size_group = QtGui.QActionGroup(size_menu)
    size_group.setExclusive(True)
    size_actions: dict[int, QtGui.QAction] = {}

    def _set_font_size(size: int) -> None:
        set_style(font_size=size)
        _refresh_text_menu_state()

    for size in _TEXT_FONT_SIZES:
        action = QtGui.QAction(str(size), size_menu)
        action.setCheckable(True)
        action.setData(size)
        size_group.addAction(action)
        size_menu.addAction(action)
        action.triggered.connect(
            lambda _checked=False, selected_size=size: _set_font_size(selected_size)
        )
        size_actions[size] = action
    menu.addSeparator()
    color_action = QtGui.QAction(color_label, menu)
    menu.addAction(color_action)
    bold_action = QtGui.QAction("Bold", menu)
    bold_action.setCheckable(True)
    IconManager.apply(bold_action, IconId.FORMAT_BOLD)
    italic_action = QtGui.QAction("Italic", menu)
    italic_action.setCheckable(True)
    IconManager.apply(italic_action, IconId.FORMAT_ITALIC)
    underline_action = QtGui.QAction("Underline", menu)
    underline_action.setCheckable(True)
    IconManager.apply(underline_action, IconId.FORMAT_UNDERLINE)
    menu.addAction(bold_action)
    menu.addAction(italic_action)
    menu.addAction(underline_action)
    align_actions: dict[int, QtGui.QAction] = {}
    if include_alignment:
        align_menu = menu.addMenu("Alignment")
        menu_refs.append(align_menu)
        align_group = QtGui.QActionGroup(align_menu)
        align_group.setExclusive(True)

        def _set_text_align(align: int) -> None:
            set_style(text_align=align)
            _refresh_text_menu_state()

        for value, label, icon_id in (
            (0, "Left", IconId.FORMAT_ALIGN_LEFT),
            (1, "Center", IconId.FORMAT_ALIGN_CENTER),
            (2, "Right", IconId.FORMAT_ALIGN_RIGHT),
        ):
            action = QtGui.QAction(label, align_menu)
            action.setCheckable(True)
            action.setData(value)
            IconManager.apply(action, icon_id)
            align_group.addAction(action)
            align_menu.addAction(action)
            action.triggered.connect(
                lambda _checked=False, selected_align=value: _set_text_align(
                    selected_align
                )
            )
            align_actions[value] = action
        menu_refs.append(align_group)
    menu._text_menu_refs = tuple(menu_refs)

    def _refresh_text_menu_state() -> None:
        style = get_style()
        font_combo.blockSignals(True)
        font_combo.setCurrentFont(QtGui.QFont(style.font_name))
        font_combo.blockSignals(False)
        for size, action in size_actions.items():
            action.setChecked(size == int(style.font_size))
        bold_action.setChecked(bool(style.font_bold))
        italic_action.setChecked(bool(style.font_italic))
        underline_action.setChecked(bool(style.font_underline))
        for align, action in align_actions.items():
            action.setChecked(align == int(style.text_align))

    def _choose_default_text_color() -> None:
        style = get_style()
        color = QtWidgets.QColorDialog.getColor(QtGui.QColor(style.color), parent)
        if color.isValid():
            set_style(color=color.name())
        _refresh_text_menu_state()

    def _set_font_name(font: QtGui.QFont) -> None:
        set_style(font_name=font.family())
        _refresh_text_menu_state()

    def _set_bold(checked: bool = False) -> None:
        set_style(font_bold=bool(checked))
        _refresh_text_menu_state()

    def _set_italic(checked: bool = False) -> None:
        set_style(font_italic=bool(checked))
        _refresh_text_menu_state()

    def _set_underline(checked: bool = False) -> None:
        set_style(font_underline=bool(checked))
        _refresh_text_menu_state()

    font_combo.currentFontChanged.connect(_set_font_name)
    color_action.triggered.connect(lambda _checked=False: _choose_default_text_color())
    bold_action.triggered.connect(_set_bold)
    italic_action.triggered.connect(_set_italic)
    underline_action.triggered.connect(_set_underline)
    menu.aboutToShow.connect(_refresh_text_menu_state)
    _refresh_text_menu_state()
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
    button.setProperty("annotationType", annotation_type or "")
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
    if annotation_type in _COLOR_ONLY_ANNOTATION_TYPES:
        button.setProperty("annotationDefaultColorPicker", True)
        if annotation_type == "highlight":
            button.setProperty("highlightAnnotationDefaultColorPicker", True)

        def _choose_default_color() -> None:
            style = get_style()
            color = QtWidgets.QColorDialog.getColor(QtGui.QColor(style.color), parent)
            if color.isValid():
                set_style(color=color.name())

        button.clicked.connect(_choose_default_color)
        return button
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
