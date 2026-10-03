import os
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.annotation_style import AnnotationStyle
from ost_visualizer.presentation.managers.icon_manager import (
    ICON_SPECS,
    IconId,
    IconManager,
)
from ost_visualizer.presentation.utils.annotation_defaults import (
    get_annotation_style_for_tool,
    set_annotation_style_for_tool,
)
from ost_visualizer.presentation.utils.annotation_style_controls import (
    apply_annotation_tool_icon_color,
    create_annotation_style_button,
    create_annotation_style_menu,
    create_annotation_tool_split_button,
)
from ost_visualizer.presentation.utils.plan_tool_registry import (
    PLAN_ANNOTATION_TOOL_SPECS,
    PLAN_TOOL_SPECS,
)
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete
from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
    _submenu_by_title as _preferences_support__submenu_by_title,
)


class AnnotationStyleControlsPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_annotation_tool_icon_color_updates_only_annotation_actions(self):
        actions = {}
        for spec in PLAN_TOOL_SPECS:
            action = QtGui.QAction(spec.label, None)
            IconManager.apply(action, spec.icon_id)
            actions[spec.action_key] = action
        select_key = actions["select_tool"].icon().cacheKey()
        dimension_key = actions["dimension_tool"].icon().cacheKey()
        rect_key = actions["rectangle_annotation_tool"].icon().cacheKey()
        set_annotation_style_for_tool("dimension", color="#336699")
        set_annotation_style_for_tool("rect", color="#00aa00")
        try:
            apply_annotation_tool_icon_color(actions, "dimension")
            self.assertEqual(actions["select_tool"].icon().cacheKey(), select_key)
            self.assertNotEqual(
                actions["dimension_tool"].icon().cacheKey(), dimension_key
            )
            self.assertEqual(
                actions["rectangle_annotation_tool"].icon().cacheKey(), rect_key
            )
            apply_annotation_tool_icon_color(actions)
            self.assertNotEqual(
                actions["rectangle_annotation_tool"].icon().cacheKey(), rect_key
            )
            for spec in PLAN_ANNOTATION_TOOL_SPECS:
                self.assertTrue(actions[spec.action_key].icon().cacheKey())
        finally:
            set_annotation_style_for_tool("dimension", color="#ff0000", line_width=4.0)
            set_annotation_style_for_tool("rect", color="#ff0000", line_width=4.0)

    def test_annotation_tool_icon_color_applies_each_tools_own_style_color(self):
        targets = {
            spec.action_key: QtGui.QAction(spec.label, None)
            for spec in PLAN_ANNOTATION_TOOL_SPECS
        }
        del targets["rectangle_annotation_tool"]
        set_annotation_style_for_tool("dimension", color="#336699")
        set_annotation_style_for_tool("text", color="#00aa00")
        try:
            with mock.patch.object(IconManager, "apply_colored") as apply_colored:
                apply_annotation_tool_icon_color(targets, "dimension")
                apply_colored.assert_called_once_with(
                    targets["dimension_tool"], IconId.DIMENSION_TOOL, "#336699"
                )
                apply_colored.reset_mock()
                apply_annotation_tool_icon_color(targets)
            expected = [
                mock.call(
                    targets[spec.action_key],
                    spec.icon_id,
                    get_annotation_style_for_tool(spec.annotation_type).color,
                )
                for spec in PLAN_ANNOTATION_TOOL_SPECS
                if spec.action_key in targets
            ]
            self.assertEqual(apply_colored.call_args_list, expected)
            self.assertEqual(len(expected), len(PLAN_ANNOTATION_TOOL_SPECS) - 1)
            colors = {call.args[2] for call in expected}
            self.assertIn("#336699", colors)
            self.assertIn("#00aa00", colors)
            # Pin the literal per-tool colors so the expected list above is
            # not the only oracle for which tool received which color.
            color_by_target = {
                call.args[0].text(): call.args[2]
                for call in apply_colored.call_args_list
            }
            labels = {
                spec.annotation_type: spec.label for spec in PLAN_ANNOTATION_TOOL_SPECS
            }
            self.assertEqual(color_by_target[labels["dimension"]], "#336699")
            self.assertEqual(color_by_target[labels["text"]], "#00aa00")
            self.assertEqual(color_by_target[labels["line"]], "#ff0000")
        finally:
            set_annotation_style_for_tool("dimension", color="#ff0000")
            set_annotation_style_for_tool("text", color="#ff0000")

    def test_highlight_annotation_style_button_opens_direct_color_picker(self):
        _preferences_support__app()
        selected = []
        current = AnnotationStyle("#ff0000", 4.0)

        def get_style():
            return current

        def set_style(**style_updates):
            nonlocal current
            current = AnnotationStyle(
                color=style_updates.get("color", current.color),
                line_width=current.line_width,
            )
            selected.append(current)
            return current

        parent = QtWidgets.QWidget()
        button = create_annotation_style_button(
            parent, get_style, set_style, annotation_type="highlight"
        )
        try:
            self.assertTrue(button.property("highlightAnnotationDefaultColorPicker"))
            self.assertIsNone(button.menu())
            with mock.patch.object(
                QtWidgets.QColorDialog,
                "getColor",
                return_value=QtGui.QColor("#445566"),
            ) as get_color:
                button.click()
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[-1].color, "#445566")
            self.assertEqual(selected[-1].line_width, 4.0)
            initial_color, dialog_parent = get_color.call_args.args
            self.assertEqual(initial_color.name(), "#ff0000")
            self.assertIs(dialog_parent, parent)
        finally:
            parent.deleteLater()

    def test_cancelled_color_picker_leaves_style_unchanged(self):
        _preferences_support__app()
        selected = []
        parent = QtWidgets.QWidget()
        highlight_button = create_annotation_style_button(
            parent,
            lambda: AnnotationStyle("#ff0000", 4.0),
            lambda **updates: selected.append(updates),
            annotation_type="highlight",
        )
        rect_button = create_annotation_style_button(
            parent,
            lambda: AnnotationStyle("#ff0000", 4.0),
            lambda **updates: selected.append(updates),
        )
        try:
            with mock.patch.object(
                QtWidgets.QColorDialog,
                "getColor",
                return_value=QtGui.QColor(),
            ):
                highlight_button.click()
                rect_button.menu().actions()[-1].trigger()
            self.assertEqual(selected, [])
        finally:
            parent.deleteLater()

    def test_annotation_style_color_picker_drops_result_after_owner_destruction(self):
        _preferences_support__app()
        selected = []
        parent = QtWidgets.QWidget()
        button = create_annotation_style_button(
            parent,
            lambda: AnnotationStyle("#ff0000", 4.0),
            lambda **updates: selected.append(updates),
            annotation_type="highlight",
        )

        def destroy_owner(*_args, **_kwargs):
            delete(parent)
            return QtGui.QColor("#445566")

        with mock.patch.object(
            QtWidgets.QColorDialog,
            "getColor",
            side_effect=destroy_owner,
        ):
            button.click()
        self.assertEqual(selected, [])

    def test_annotation_style_button_exposes_widths_and_updates_style(self):
        _preferences_support__app()
        selected = []
        current = AnnotationStyle("#ff0000", 4.0)

        def get_style():
            return current

        def set_style(**style_updates):
            nonlocal current
            current = AnnotationStyle(
                style_updates.get("color", current.color),
                style_updates.get("line_width", current.line_width),
            )
            selected.append(current)
            return current

        parent = QtWidgets.QWidget()
        button = create_annotation_style_button(parent, get_style, set_style)
        try:
            self.assertTrue(button.property("annotationDefaultStyleDropdown"))
            menu = button.menu()
            self.assertTrue(menu.property("annotationDefaultStyleMenu"))
            width_actions = [
                action for action in menu.actions() if isinstance(action.data(), int)
            ]
            self.assertEqual(
                [action.text() for action in width_actions],
                [f"{width}px" for width in range(1, 17)],
            )
            self.assertEqual(
                [action.isChecked() for action in width_actions],
                [width == 4 for width in range(1, 17)],
            )
            width_actions[7].trigger()
            self.assertEqual(selected[-1].line_width, 8.0)
            self.assertEqual(
                [action.isChecked() for action in width_actions],
                [width == 8 for width in range(1, 17)],
            )
            self.assertEqual(menu.actions()[-1].text(), "Select Color...")
            with mock.patch.object(
                QtWidgets.QColorDialog,
                "getColor",
                return_value=QtGui.QColor("#445566"),
            ):
                menu.actions()[-1].trigger()
            self.assertEqual(selected[-1].color, "#445566")
            self.assertEqual(selected[-1].line_width, 8.0)
            self.assertEqual(len(selected), 2)
        finally:
            parent.deleteLater()

    def test_annotation_style_menu_color_drops_result_after_menu_destruction(self):
        _preferences_support__app()
        selected = []
        parent = QtWidgets.QWidget()
        button = create_annotation_style_button(
            parent,
            lambda: AnnotationStyle("#ff0000", 4.0),
            lambda **updates: selected.append(updates),
        )
        menu = button.menu()

        def destroy_owner(*_args, **_kwargs):
            delete(parent)
            return QtGui.QColor("#445566")

        with mock.patch.object(
            QtWidgets.QColorDialog,
            "getColor",
            side_effect=destroy_owner,
        ):
            menu.actions()[-1].trigger()
        self.assertEqual(selected, [])

    def test_text_annotation_style_button_exposes_text_controls_without_widths(self):
        _preferences_support__app()
        selected = []
        current = AnnotationStyle("#ff0000", 4.0)

        def get_style():
            return current

        def set_style(**style_updates):
            nonlocal current
            current = AnnotationStyle(
                color=style_updates.get("color", current.color),
                line_width=current.line_width,
                font_name=style_updates.get("font_name", current.font_name),
                font_size=style_updates.get("font_size", current.font_size),
                font_bold=style_updates.get("font_bold", current.font_bold),
                font_italic=style_updates.get("font_italic", current.font_italic),
                font_underline=style_updates.get(
                    "font_underline", current.font_underline
                ),
                text_align=style_updates.get("text_align", current.text_align),
            )
            selected.append(current)
            return current

        parent = QtWidgets.QWidget()
        button = create_annotation_style_button(
            parent, get_style, set_style, annotation_type="text"
        )
        try:
            menu = button.menu()
            self.assertTrue(menu.property("textAnnotationDefaultStyleMenu"))
            self.assertNotIn(
                "px",
                " ".join(action.text() for action in menu.actions()),
            )
            self.assertIn("Select Font Color...", [a.text() for a in menu.actions()])
            font_widgets = [
                action.defaultWidget()
                for action in menu.actions()
                if isinstance(action, QtWidgets.QWidgetAction)
            ]
            self.assertTrue(
                any(
                    isinstance(widget, QtWidgets.QFontComboBox)
                    for widget in font_widgets
                )
            )
            size_menu = _preferences_support__submenu_by_title(menu, "Font Size")
            font_sizes = [action.data() for action in size_menu.actions()]
            self.assertEqual(
                font_sizes,
                [8, 9, 10, 11, 12, 14, 16, 18, 24, 36, 48, 72],
            )
            for size in (48, 72):
                size_action = next(
                    action for action in size_menu.actions() if action.data() == size
                )
                size_action.trigger()
                self.assertEqual(selected[-1].font_size, size)
            bold_action = next(
                action for action in menu.actions() if action.text() == "Bold"
            )
            italic_action = next(
                action for action in menu.actions() if action.text() == "Italic"
            )
            underline_action = next(
                action for action in menu.actions() if action.text() == "Underline"
            )
            for action in (bold_action, italic_action, underline_action):
                self.assertFalse(action.icon().isNull())
            alignment_menu = _preferences_support__submenu_by_title(menu, "Alignment")
            for action in alignment_menu.actions():
                self.assertFalse(action.icon().isNull())
            bold_action.trigger()
            italic_action.trigger()
            self.assertTrue(selected[-2].font_bold)
            self.assertFalse(selected[-2].font_italic)
            self.assertTrue(selected[-1].font_bold)
            self.assertTrue(selected[-1].font_italic)
            underline_action.trigger()
            self.assertTrue(selected[-1].font_underline)
            bold_action.trigger()
            self.assertFalse(selected[-1].font_bold)
            self.assertTrue(selected[-1].font_italic)
            self.assertEqual(
                [(a.text(), a.data()) for a in alignment_menu.actions()],
                [("Left", 0), ("Center", 1), ("Right", 2)],
            )
            alignment_menu.actions()[2].trigger()
            self.assertEqual(selected[-1].text_align, 2)
            self.assertEqual(
                [a.isChecked() for a in alignment_menu.actions()],
                [False, False, True],
            )
            font_combo = next(
                widget
                for widget in font_widgets
                if isinstance(widget, QtWidgets.QFontComboBox)
            )
            self.assertEqual(selected[-1].font_name, "Arial")
            font_combo.setCurrentFont(QtGui.QFont("Courier New"))
            self.assertEqual(selected[-1].font_name, "Courier New")
            with mock.patch.object(
                QtWidgets.QColorDialog,
                "getColor",
                return_value=QtGui.QColor("#445566"),
            ):
                next(
                    action
                    for action in menu.actions()
                    if action.text() == "Select Font Color..."
                ).trigger()
            self.assertEqual(selected[-1].color, "#445566")
        finally:
            parent.deleteLater()

    def test_dimension_annotation_style_button_exposes_font_controls_without_widths(
        self,
    ):
        _preferences_support__app()
        selected = []
        current = AnnotationStyle("#ff0000", 4.0)

        def get_style():
            return current

        def set_style(**style_updates):
            nonlocal current
            current = AnnotationStyle(
                color=style_updates.get("color", current.color),
                line_width=style_updates.get("line_width", current.line_width),
                font_name=style_updates.get("font_name", current.font_name),
                font_size=style_updates.get("font_size", current.font_size),
                font_bold=style_updates.get("font_bold", current.font_bold),
                font_italic=style_updates.get("font_italic", current.font_italic),
                font_underline=style_updates.get(
                    "font_underline", current.font_underline
                ),
                text_align=current.text_align,
            )
            selected.append(current)
            return current

        parent = QtWidgets.QWidget()
        button = create_annotation_style_button(
            parent, get_style, set_style, annotation_type="dimension"
        )
        try:
            menu = button.menu()
            self.assertTrue(menu.property("dimensionAnnotationDefaultStyleMenu"))
            self.assertIn(
                "Select Color...", [action.text() for action in menu.actions()]
            )
            self.assertNotIn("Alignment", [action.text() for action in menu.actions()])
            width_actions = [
                action for action in menu.actions() if isinstance(action.data(), int)
            ]
            self.assertEqual(width_actions, [])
            size_menu = _preferences_support__submenu_by_title(menu, "Font Size")
            self.assertEqual(
                [action.data() for action in size_menu.actions()],
                [8, 9, 10, 11, 12, 14, 16, 18, 24, 36, 48, 72],
            )
            for size in (48, 72):
                size_action = next(
                    action for action in size_menu.actions() if action.data() == size
                )
                size_action.trigger()
                self.assertEqual(selected[-1].font_size, size)
            for action_text, selected_state in (
                ("Bold", lambda style: style.font_bold),
                ("Italic", lambda style: style.font_italic),
                ("Underline", lambda style: style.font_underline),
            ):
                with self.subTest(action_text=action_text):
                    action = next(
                        action
                        for action in menu.actions()
                        if action.text() == action_text
                    )
                    self.assertFalse(action.icon().isNull())
                    action.trigger()
                    self.assertTrue(selected_state(selected[-1]))
        finally:
            parent.deleteLater()

    def test_annotation_split_tool_buttons_keep_activation_and_style_menu(self):
        _preferences_support__app()
        parent = QtWidgets.QWidget()
        selected = []
        current = AnnotationStyle("#ff0000", 4.0)

        def get_style():
            return current

        def set_style(**style_updates):
            nonlocal current
            current = AnnotationStyle(
                style_updates.get("color", current.color),
                style_updates.get("line_width", current.line_width),
            )
            selected.append(current)
            return current

        covered = set()
        try:
            for spec in PLAN_ANNOTATION_TOOL_SPECS:
                covered.add(spec.annotation_type)
                with self.subTest(action_key=spec.action_key):
                    triggered = []
                    action = QtGui.QAction(spec.label, parent)
                    action.setCheckable(True)
                    IconManager.apply(action, spec.icon_id)
                    action.triggered.connect(
                        lambda checked=False, key=spec.action_key: triggered.append(
                            (key, checked)
                        )
                    )
                    button = QtWidgets.QToolButton(parent)
                    button.setDefaultAction(action)
                    split_button, dropdown = create_annotation_tool_split_button(
                        parent,
                        button,
                        get_style,
                        set_style,
                        icon_size=QtCore.QSize(24, 24),
                        annotation_type=spec.annotation_type,
                    )
                    self.assertTrue(split_button.property("annotationToolSplitButton"))
                    self.assertTrue(button.property("annotationToolMainButton"))
                    self.assertTrue(dropdown.property("annotationStyleDropdown"))
                    self.assertEqual(
                        dropdown.popupMode(),
                        QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup,
                    )
                    button.click()
                    self.assertEqual(triggered, [(spec.action_key, True)])
                    if spec.annotation_type == "text":
                        self.assertTrue(
                            dropdown.menu().property("textAnnotationDefaultStyleMenu")
                        )
                        self.assertNotIn(
                            "px",
                            " ".join(
                                action.text() for action in dropdown.menu().actions()
                            ),
                        )
                    elif spec.annotation_type == "dimension":
                        menu = dropdown.menu()
                        self.assertTrue(
                            menu.property("dimensionAnnotationDefaultStyleMenu")
                        )
                        self.assertIsNone(
                            next(
                                (
                                    action
                                    for action in menu.actions()
                                    if action.text() == "Alignment"
                                ),
                                None,
                            )
                        )
                        width_actions = [
                            action
                            for action in menu.actions()
                            if isinstance(action.data(), int)
                        ]
                        self.assertEqual(width_actions, [])
                    elif spec.annotation_type in ("highlight", "hotlink", "namedview"):
                        self.assertIsNone(dropdown.menu())
                        self.assertTrue(
                            dropdown.property("annotationDefaultColorPicker")
                        )
                        if spec.annotation_type == "highlight":
                            self.assertTrue(
                                dropdown.property(
                                    "highlightAnnotationDefaultColorPicker"
                                )
                            )
                    else:
                        width_actions = [
                            action
                            for action in dropdown.menu().actions()
                            if isinstance(action.data(), int)
                        ]
                        self.assertEqual(len(width_actions), 16)
                        width_actions[11].trigger()
                        self.assertEqual(selected[-1].line_width, 12.0)
            self.assertEqual(
                covered,
                {
                    "dimension",
                    "text",
                    "highlight",
                    "arrow",
                    "line",
                    "rect",
                    "oval",
                    "polygon",
                    "cloud",
                    "ink",
                    "hotlink",
                    "namedview",
                },
            )
        finally:
            parent.deleteLater()

    def test_split_button_marks_only_its_own_tool_button_as_annotation_main(self):
        _preferences_support__app()
        parent = QtWidgets.QWidget()
        try:
            plain = QtWidgets.QToolButton(parent)
            plain.setDefaultAction(QtGui.QAction("Select", parent))
            tool = QtWidgets.QToolButton(parent)
            tool.setDefaultAction(QtGui.QAction("Rect", parent))
            self.assertFalse(bool(tool.property("annotationToolMainButton")))
            container, dropdown = create_annotation_tool_split_button(
                parent,
                tool,
                lambda: AnnotationStyle("#ff0000", 4.0),
                lambda **updates: AnnotationStyle(),
                annotation_type="rect",
            )
            self.assertTrue(tool.property("annotationToolMainButton"))
            self.assertIs(tool.parentWidget(), container)
            self.assertIs(dropdown.parentWidget(), container)
            self.assertEqual(dropdown.property("annotationType"), "rect")
            self.assertFalse(bool(plain.property("annotationStyleDropdown")))
            self.assertFalse(bool(plain.property("annotationToolMainButton")))
            self.assertFalse(bool(tool.property("annotationStyleDropdown")))
            self.assertFalse(bool(dropdown.property("annotationToolMainButton")))
            self.assertFalse(bool(parent.property("annotationToolMainButton")))
            self.assertTrue(container.property("annotationToolSplitButton"))
        finally:
            parent.deleteLater()

    def test_style_controls_require_tool_specific_getter_and_setter(self):
        _preferences_support__app()
        parent = QtWidgets.QWidget()
        try:
            # The button delegates to the menu factory, so the message must
            # name the control that rejected the missing callback itself.
            for factory, control in (
                (create_annotation_style_button, "button"),
                (create_annotation_style_menu, "menu"),
            ):
                with self.subTest(factory=factory.__name__):
                    with self.assertRaisesRegex(
                        ValueError, f"style {control} requires .*getter"
                    ):
                        factory(parent, None, lambda **updates: None)
                    with self.assertRaisesRegex(
                        ValueError, f"style {control} requires .*setter"
                    ):
                        factory(parent, lambda: AnnotationStyle(), None)
        finally:
            parent.deleteLater()
