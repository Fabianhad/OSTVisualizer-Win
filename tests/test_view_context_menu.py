import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.presentation.managers.icon_manager import IconManager, IconId
from ost_visualizer.presentation.utils.annotation_defaults import (
    get_annotation_style_for_tool,
    set_annotation_style_for_tool,
)
from ost_visualizer.presentation.utils.view_context_menu import (
    add_common_context_submenus,
    add_reassign_condition_submenu,
    add_selected_annotation_style_actions,
    build_selected_annotation_style_context_state,
)


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _build_tools_context_menu():
    menu = QtWidgets.QMenu()
    add_common_context_submenus(
        menu,
        current_mode=0,
        trigger_fn=lambda _key: None,
        action_state_fn=lambda _key: {
            "enabled": True,
        },
        has_overlay_image=False,
    )
    return menu, menu.actions()[0].menu()


class ViewContextMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        self.app.processEvents()

    def test_reassign_condition_submenu_lists_conditions_by_ref_no(self):
        menu = QtWidgets.QMenu()
        try:
            reassign_menu = add_reassign_condition_submenu(
                menu,
                {
                    "20": Condition(uid="20", name="Second", ref_no=2),
                    "10": Condition(uid="10", name="First", ref_no=1),
                },
            )
            self.assertEqual(menu.actions()[0].text(), "Reassign Condition")
            self.assertEqual(
                [action.text() for action in reassign_menu.submenu.actions()],
                [
                    "1 - First",
                    "2 - Second",
                ],
            )
            self.assertEqual(
                [
                    reassign_menu.actions[action]
                    for action in reassign_menu.submenu.actions()
                ],
                ["10", "20"],
            )
            self.assertTrue(
                all(
                    not action.icon().isNull()
                    for action in reassign_menu.submenu.actions()
                )
            )
        finally:
            menu.deleteLater()

    def test_plan_tools_context_submenu_uses_shared_tool_registry(self):
        menu, tools_menu = _build_tools_context_menu()
        try:
            self.assertEqual(tools_menu.title(), "Tools")
            self.assertEqual(
                [action.text() for action in tools_menu.actions()],
                [
                    "Select",
                    "Place",
                    "Pan",
                    "Zoom",
                    "Dimension",
                    "Text",
                    "Highlight",
                    "Arrow",
                    "Line",
                    "Rectangle",
                    "Oval",
                    "Polygon",
                    "Cloud",
                    "Ink",
                    "Hotlink",
                    "Named View",
                    "",
                    "Backout",
                ],
            )
        finally:
            menu.deleteLater()

    def test_context_menu_annotation_tool_icons_use_per_tool_colors(self):
        original_rect_style = get_annotation_style_for_tool("rect")
        original_cloud_style = get_annotation_style_for_tool("cloud")
        original_ink_style = get_annotation_style_for_tool("ink")
        try:
            set_annotation_style_for_tool("rect", color="#00aa00")
            set_annotation_style_for_tool("cloud", color="#336699")
            set_annotation_style_for_tool("ink", color="#8844cc")
            menu, tools_menu = _build_tools_context_menu()
            try:
                actions = {action.text(): action for action in tools_menu.actions()}
                rect_key = actions["Rectangle"].icon().cacheKey()
                cloud_key = actions["Cloud"].icon().cacheKey()
                ink_key = actions["Ink"].icon().cacheKey()
                select_key = actions["Select"].icon().cacheKey()
                self.assertEqual(
                    rect_key,
                    IconManager.colored_icon(
                        IconId.RECTANGLE_ANNOTATION_TOOL, "#00aa00"
                    ).cacheKey(),
                )
                self.assertEqual(
                    cloud_key,
                    IconManager.colored_icon(
                        IconId.CLOUD_ANNOTATION_TOOL, "#336699"
                    ).cacheKey(),
                )
                self.assertEqual(
                    ink_key,
                    IconManager.colored_icon(
                        IconId.INK_ANNOTATION_TOOL, "#8844cc"
                    ).cacheKey(),
                )
            finally:
                menu.deleteLater()

            set_annotation_style_for_tool("rect", color="#ff0000")
            menu, tools_menu = _build_tools_context_menu()
            try:
                actions = {action.text(): action for action in tools_menu.actions()}
                self.assertNotEqual(
                    actions["Rectangle"].icon().cacheKey(),
                    rect_key,
                )
                self.assertEqual(actions["Cloud"].icon().cacheKey(), cloud_key)
                self.assertEqual(actions["Ink"].icon().cacheKey(), ink_key)
                self.assertEqual(actions["Select"].icon().cacheKey(), select_key)
            finally:
                menu.deleteLater()
        finally:
            set_annotation_style_for_tool(
                "rect",
                color=original_rect_style.color,
                line_width=original_rect_style.line_width,
                font_name=original_rect_style.font_name,
                font_size=original_rect_style.font_size,
                font_bold=original_rect_style.font_bold,
                font_italic=original_rect_style.font_italic,
                font_underline=original_rect_style.font_underline,
                text_align=original_rect_style.text_align,
            )
            set_annotation_style_for_tool(
                "cloud",
                color=original_cloud_style.color,
                line_width=original_cloud_style.line_width,
                font_name=original_cloud_style.font_name,
                font_size=original_cloud_style.font_size,
                font_bold=original_cloud_style.font_bold,
                font_italic=original_cloud_style.font_italic,
                font_underline=original_cloud_style.font_underline,
                text_align=original_cloud_style.text_align,
            )
            set_annotation_style_for_tool(
                "ink",
                color=original_ink_style.color,
                line_width=original_ink_style.line_width,
                font_name=original_ink_style.font_name,
                font_size=original_ink_style.font_size,
                font_bold=original_ink_style.font_bold,
                font_italic=original_ink_style.font_italic,
                font_underline=original_ink_style.font_underline,
                text_align=original_ink_style.text_align,
            )

    def test_selected_line_annotation_context_shows_color_and_width(self):
        annotations = {
            "line-1": BidAnnotation(uid="line-1", annotation_type="line", width=8.0),
        }
        state = build_selected_annotation_style_context_state(
            ["line-1"], annotations.get
        )
        menu = QtWidgets.QMenu()
        try:
            actions = add_selected_annotation_style_actions(
                menu,
                state,
                select_color_callback=lambda: None,
                line_width_callback=lambda _width: None,
                enabled=True,
            )
            self.assertTrue(state.show_color)
            self.assertTrue(state.show_line_width)
            self.assertEqual(state.current_line_width, 8.0)
            self.assertIsNotNone(actions.color_action)
            self.assertEqual(menu.actions()[0].text(), "Line Width")
            self.assertEqual(menu.actions()[1].text(), "Select Color...")
            width_actions = menu.actions()[0].menu().actions()
            self.assertEqual(
                [action.text() for action in width_actions],
                [f"{width}px" for width in range(1, 17)],
            )
            self.assertEqual(
                [action.text() for action in width_actions if action.isChecked()],
                ["8px"],
            )
        finally:
            menu.deleteLater()

    def test_selected_rectangle_context_checks_current_width(self):
        annotations = {
            "rect-1": BidAnnotation(uid="rect-1", annotation_type="rect", width=4.0),
        }
        state = build_selected_annotation_style_context_state(
            ["rect-1"], annotations.get
        )
        menu = QtWidgets.QMenu()
        try:
            add_selected_annotation_style_actions(
                menu,
                state,
                select_color_callback=lambda: None,
                line_width_callback=lambda _width: None,
                enabled=True,
            )
            width_actions = menu.actions()[0].menu().actions()
            self.assertEqual(
                [action.text() for action in width_actions if action.isChecked()],
                ["4px"],
            )
        finally:
            menu.deleteLater()

    def test_selected_shape_annotation_context_capabilities(self):
        for annotation_type in ("arrow", "rect", "oval", "polygon", "cloud", "ink"):
            with self.subTest(annotation_type=annotation_type):
                annotations = {
                    "ann-1": BidAnnotation(
                        uid="ann-1", annotation_type=annotation_type
                    ),
                }
                state = build_selected_annotation_style_context_state(
                    ["ann-1"], annotations.get
                )
                self.assertTrue(state.show_color)
                self.assertTrue(state.show_line_width)

    def test_selected_highlight_context_shows_color_only(self):
        annotations = {
            "highlight-1": BidAnnotation(
                uid="highlight-1", annotation_type="highlight"
            ),
        }
        state = build_selected_annotation_style_context_state(
            ["highlight-1"], annotations.get
        )
        menu = QtWidgets.QMenu()
        try:
            actions = add_selected_annotation_style_actions(
                menu,
                state,
                select_color_callback=lambda: None,
                line_width_callback=lambda _width: None,
                enabled=True,
            )
            self.assertTrue(state.show_color)
            self.assertFalse(state.show_line_width)
            self.assertIsNotNone(actions.color_action)
            self.assertEqual(
                [action.text() for action in menu.actions()],
                ["Select Color..."],
            )
        finally:
            menu.deleteLater()

    def test_selected_dimension_context_shows_color_only(self):
        annotations = {
            "dimension-1": BidAnnotation(
                uid="dimension-1", annotation_type="dimension"
            ),
        }
        state = build_selected_annotation_style_context_state(
            ["dimension-1"], annotations.get
        )
        self.assertTrue(state.show_color)
        self.assertFalse(state.show_line_width)

    def test_selected_annotation_style_actions_respect_disabled_state(self):
        annotations = {
            "line-1": BidAnnotation(uid="line-1", annotation_type="line"),
        }
        state = build_selected_annotation_style_context_state(
            ["line-1"], annotations.get
        )
        menu = QtWidgets.QMenu()
        try:
            actions = add_selected_annotation_style_actions(
                menu,
                state,
                select_color_callback=lambda: None,
                line_width_callback=lambda _width: None,
                enabled=False,
            )
            self.assertFalse(actions.color_action.isEnabled())
            self.assertTrue(
                all(not action.isEnabled() for action in actions.width_actions)
            )
        finally:
            menu.deleteLater()

    def test_selected_text_context_shows_no_generic_style_actions(self):
        annotations = {
            "text-1": BidAnnotation(uid="text-1", annotation_type="text"),
        }
        state = build_selected_annotation_style_context_state(
            ["text-1"], annotations.get
        )
        menu = QtWidgets.QMenu()
        try:
            actions = add_selected_annotation_style_actions(
                menu,
                state,
                select_color_callback=lambda: None,
                line_width_callback=lambda _width: None,
                enabled=True,
            )
            self.assertFalse(state.show_color)
            self.assertFalse(state.show_line_width)
            self.assertIsNone(actions.color_action)
            self.assertEqual(actions.width_actions, {})
            self.assertEqual(menu.actions(), [])
        finally:
            menu.deleteLater()

    def test_mixed_annotation_context_intersects_style_capabilities(self):
        annotations = {
            "line-1": BidAnnotation(uid="line-1", annotation_type="line"),
            "highlight-1": BidAnnotation(
                uid="highlight-1", annotation_type="highlight"
            ),
            "text-1": BidAnnotation(uid="text-1", annotation_type="text"),
        }
        line_and_highlight = build_selected_annotation_style_context_state(
            ["line-1", "highlight-1"], annotations.get
        )
        with_text = build_selected_annotation_style_context_state(
            ["line-1", "text-1"], annotations.get
        )
        empty = build_selected_annotation_style_context_state([], annotations.get)
        self.assertTrue(line_and_highlight.show_color)
        self.assertFalse(line_and_highlight.show_line_width)
        self.assertFalse(with_text.show_color)
        self.assertFalse(with_text.show_line_width)
        self.assertEqual(empty.annotation_uids, [])
        self.assertFalse(empty.show_color)
        self.assertFalse(empty.show_line_width)

    def test_mixed_same_width_annotation_context_checks_shared_width(self):
        annotations = {
            "line-1": BidAnnotation(uid="line-1", annotation_type="line", width=6.0),
            "rect-1": BidAnnotation(uid="rect-1", annotation_type="rect", width=6.0),
        }
        state = build_selected_annotation_style_context_state(
            ["line-1", "rect-1"], annotations.get
        )
        menu = QtWidgets.QMenu()
        try:
            add_selected_annotation_style_actions(
                menu,
                state,
                select_color_callback=lambda: None,
                line_width_callback=lambda _width: None,
                enabled=True,
            )
            width_actions = menu.actions()[0].menu().actions()
            self.assertEqual(state.current_line_width, 6.0)
            self.assertEqual(
                [action.text() for action in width_actions if action.isChecked()],
                ["6px"],
            )
        finally:
            menu.deleteLater()

    def test_mixed_different_width_annotation_context_checks_no_width(self):
        annotations = {
            "line-1": BidAnnotation(uid="line-1", annotation_type="line", width=6.0),
            "rect-1": BidAnnotation(uid="rect-1", annotation_type="rect", width=7.0),
        }
        state = build_selected_annotation_style_context_state(
            ["line-1", "rect-1"], annotations.get
        )
        menu = QtWidgets.QMenu()
        try:
            add_selected_annotation_style_actions(
                menu,
                state,
                select_color_callback=lambda: None,
                line_width_callback=lambda _width: None,
                enabled=True,
            )
            width_actions = menu.actions()[0].menu().actions()
            self.assertIsNone(state.current_line_width)
            self.assertEqual(
                [action.text() for action in width_actions if action.isChecked()],
                [],
            )
        finally:
            menu.deleteLater()


if __name__ == "__main__":
    unittest.main()
