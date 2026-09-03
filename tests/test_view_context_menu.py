import os
import unittest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.managers.icon_manager import IconId, IconManager
from ost_visualizer.presentation.utils.annotation_defaults import (
    get_annotation_style_for_tool,
    set_annotation_style_for_tool,
)
from ost_visualizer.presentation.utils.compact_context_menu import (
    COMPACT_CONTEXT_MENU_MAX_VISIBLE_ROWS,
    COMPACT_CONTEXT_MENU_NEXT_TEXT,
    COMPACT_CONTEXT_MENU_PREVIOUS_TEXT,
)
from ost_visualizer.presentation.utils.view_context_menu import (
    add_common_context_submenus,
    add_reassign_condition_submenu,
    add_selected_annotation_style_actions,
    build_selected_annotation_style_context_state,
    build_selected_takeoff_context_state,
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
                    "20": Condition(
                        uid="20",
                        name="Second",
                        ref_no=2,
                        condition_type=Condition.TYPE_LINEAR,
                    ),
                    "10": Condition(
                        uid="10",
                        name="First",
                        ref_no=1,
                        condition_type=Condition.TYPE_LINEAR,
                    ),
                },
                Condition.TYPE_LINEAR,
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
    def test_reassign_condition_submenu_uses_compact_overflow_menu(self):
        menu = QtWidgets.QMenu()
        try:
            conditions = {
                str(index): Condition(
                    uid=str(index),
                    name=f"Condition {index}",
                    ref_no=index,
                    condition_type=Condition.TYPE_LINEAR,
                )
                for index in range(1, 81)
            }
            reassign_menu = add_reassign_condition_submenu(
                menu, conditions, Condition.TYPE_LINEAR
            )
            submenu = reassign_menu.submenu
            self.assertTrue(submenu.property("ost_compact_overflow_menu"))
            self.assertEqual(
                submenu.property("ost_compact_overflow_max_visible_rows"),
                COMPACT_CONTEXT_MENU_MAX_VISIBLE_ROWS,
            )
            self.assertEqual(submenu.property("ost_compact_overflow_item_count"), 80)
            self.assertEqual(
                len(submenu.actions()), COMPACT_CONTEXT_MENU_MAX_VISIBLE_ROWS
            )
            self.assertEqual(reassign_menu.actions[submenu.actions()[0]], "1")
            self.assertEqual(
                submenu.actions()[-1].text(), COMPACT_CONTEXT_MENU_NEXT_TEXT
            )
            submenu.actions()[-1].defaultWidget().click()
            self.app.processEvents()
            self.assertEqual(
                submenu.actions()[0].text(), COMPACT_CONTEXT_MENU_PREVIOUS_TEXT
            )
            self.assertEqual(
                submenu.actions()[-1].text(), COMPACT_CONTEXT_MENU_NEXT_TEXT
            )
            self.assertEqual(reassign_menu.actions[submenu.actions()[1]], "22")
            self.assertEqual(
                set(reassign_menu.actions.values()),
                {str(index) for index in range(22, 42)},
            )
        finally:
            menu.deleteLater()
    def test_reassign_condition_submenu_sizes_naturally_when_under_limit(self):
        menu = QtWidgets.QMenu()
        try:
            reassign_menu = add_reassign_condition_submenu(
                menu,
                {
                    "1": Condition(
                        uid="1",
                        name="First",
                        ref_no=1,
                        condition_type=Condition.TYPE_LINEAR,
                    ),
                    "2": Condition(
                        uid="2",
                        name="Second",
                        ref_no=2,
                        condition_type=Condition.TYPE_LINEAR,
                    ),
                },
                Condition.TYPE_LINEAR,
            )
            submenu = reassign_menu.submenu
            self.assertTrue(submenu.property("ost_compact_overflow_menu"))
            self.assertEqual(
                [action.text() for action in submenu.actions()],
                ["1 - First", "2 - Second"],
            )
        finally:
            menu.deleteLater()
    def test_reassign_condition_submenu_filters_to_selected_geometry_type(self):
        conditions = {
            "linear": Condition(
                uid="linear",
                name="Linear",
                ref_no=1,
                condition_type=Condition.TYPE_LINEAR,
            ),
            "area": Condition(
                uid="area",
                name="Area",
                ref_no=2,
                condition_type=Condition.TYPE_AREA,
            ),
            "count": Condition(
                uid="count",
                name="Count",
                ref_no=3,
                condition_type=Condition.TYPE_COUNT,
            ),
            "attachment": Condition(
                uid="attachment",
                name="Attachment",
                ref_no=4,
                condition_type=Condition.TYPE_ATTACHMENT,
            ),
        }
        cases = (
            (Condition.TYPE_LINEAR, ["linear"]),
            (Condition.TYPE_AREA, ["area"]),
            (Condition.TYPE_COUNT, ["count", "attachment"]),
        )
        for geometry_type, expected_uids in cases:
            with self.subTest(geometry_type=geometry_type):
                menu = QtWidgets.QMenu()
                try:
                    reassign_menu = add_reassign_condition_submenu(
                        menu,
                        conditions,
                        geometry_type,
                    )
                    self.assertEqual(
                        [
                            reassign_menu.actions[action]
                            for action in reassign_menu.submenu.actions()
                        ],
                        expected_uids,
                    )
                finally:
                    menu.deleteLater()
    def test_reassign_condition_submenu_is_not_added_when_no_targets_match(self):
        menu = QtWidgets.QMenu()
        try:
            reassign_menu = add_reassign_condition_submenu(
                menu,
                {
                    "count": Condition(
                        uid="count",
                        name="Count",
                        condition_type=Condition.TYPE_COUNT,
                    )
                },
                Condition.TYPE_LINEAR,
            )
            self.assertEqual(menu.actions(), [])
            self.assertEqual(reassign_menu.actions, {})
        finally:
            menu.deleteLater()
    def test_selected_takeoff_context_state_tracks_common_reassign_geometry(self):
        conditions = {
            "linear": Condition(uid="linear", condition_type=Condition.TYPE_LINEAR),
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
        }
        takeoffs = {
            "l1": Takeoff(uid="l1", condition_uid="linear"),
            "l2": Takeoff(uid="l2", condition_uid="linear"),
            "a1": Takeoff(uid="a1", condition_uid="area"),
        }
        linear_state = build_selected_takeoff_context_state(
            ["l1", "l2"], takeoffs.get, conditions
        )
        self.assertEqual(linear_state.reassign_geometry_type, Condition.TYPE_LINEAR)
        mixed_state = build_selected_takeoff_context_state(
            ["l1", "a1"], takeoffs.get, conditions
        )
        self.assertIsNone(mixed_state.reassign_geometry_type)
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
    def test_invalid_annotation_width_leaves_context_width_unchecked(self):
        for invalid_width in (None, float("nan"), float("inf"), "invalid"):
            with self.subTest(width=invalid_width):
                annotation = BidAnnotation(
                    uid="line-1",
                    annotation_type="line",
                    width=invalid_width,
                )
                state = build_selected_annotation_style_context_state(
                    ["line-1"],
                    lambda _uid: annotation,
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
                    self.assertIsNone(state.current_line_width)
                    self.assertTrue(actions.width_actions)
                    self.assertFalse(
                        any(action.isChecked() for action in actions.width_actions)
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
