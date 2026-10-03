from PySide6 import QtWidgets
from ost_visualizer.presentation.utils.view_context_menu import (
    CONTEXT_CLIPBOARD_ACTIONS,
    add_common_context_submenus,
    add_context_clipboard_actions,
    add_context_command_submenu,
    add_context_page_actions,
    context_command_state,
    add_reassign_condition_submenu,
    add_selected_annotation_style_actions,
    build_selected_annotation_style_context_state,
    build_selected_takeoff_context_state,
)
from ost_visualizer.presentation.utils.compact_context_menu import (
    COMPACT_CONTEXT_MENU_MAX_VISIBLE_ROWS,
    COMPACT_CONTEXT_MENU_NEXT_TEXT,
    COMPACT_CONTEXT_MENU_PREVIOUS_TEXT,
)
from ost_visualizer.presentation.utils.annotation_defaults import (
    get_annotation_style_for_tool,
    set_annotation_style_for_tool,
)
from ost_visualizer.presentation.actions.action_ids import (
    ACTION_COPY,
    ACTION_CUT,
    ACTION_DELETE,
    ACTION_DELETE_PAGE,
    ACTION_PASTE,
)
from ost_visualizer.presentation.managers.icon_manager import IconId, IconManager
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.pattern import SOLID
import unittest
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.view_context_menu import (
    build_selected_takeoff_context_state,
)
from PySide6 import QtCore, QtGui, QtWidgets


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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

    def test_reassign_condition_submenu_icons_show_each_condition_color(self):
        menu = QtWidgets.QMenu()
        try:
            reassign_menu = add_reassign_condition_submenu(
                menu,
                {
                    "red": Condition(
                        uid="red",
                        name="Red",
                        ref_no=1,
                        condition_type=Condition.TYPE_LINEAR,
                        color_fill=0x0000FF,
                        pattern=SOLID,
                    ),
                    "green": Condition(
                        uid="green",
                        name="Green",
                        ref_no=2,
                        condition_type=Condition.TYPE_LINEAR,
                        color_fill=0x00FF00,
                        pattern=SOLID,
                    ),
                    "hidden": Condition(
                        uid="hidden",
                        name="Hidden",
                        ref_no=3,
                        condition_type=Condition.TYPE_LINEAR,
                        color_fill=0x0000FF,
                        pattern=SOLID,
                        layer_visible=False,
                    ),
                },
                Condition.TYPE_LINEAR,
            )
            colors = {
                reassign_menu.actions[action]: action.icon()
                .pixmap(12, 12)
                .toImage()
                .pixelColor(6, 6)
                for action in reassign_menu.submenu.actions()
            }
            self.assertEqual(colors["red"].name(), "#ff0000")
            self.assertEqual(colors["green"].name(), "#00ff00")
            # Hidden layers use the luminance gray of the red fill:
            # int(0.299 * 255) == 76 == 0x4c on every channel.
            self.assertEqual(colors["hidden"].name(), "#4c4c4c")
        finally:
            menu.deleteLater()

    def test_reassign_condition_labels_use_name_or_uid_when_ref_no_is_missing(self):
        menu = QtWidgets.QMenu()
        try:
            reassign_menu = add_reassign_condition_submenu(
                menu,
                {
                    "named": Condition(
                        uid="named", name="Named", condition_type=Condition.TYPE_AREA
                    ),
                    "unnamed": Condition(
                        uid="unnamed", name="", condition_type=Condition.TYPE_AREA
                    ),
                    "numbered": Condition(
                        uid="numbered",
                        name="",
                        ref_no=7,
                        condition_type=Condition.TYPE_AREA,
                    ),
                },
                Condition.TYPE_AREA,
            )
            self.assertEqual(
                [action.text() for action in reassign_menu.submenu.actions()],
                ["unnamed", "Named", "7 - numbered"],
            )
        finally:
            menu.deleteLater()

    def test_reassign_condition_submenu_can_be_disabled(self):
        menu = QtWidgets.QMenu()
        try:
            for enabled in (True, False):
                with self.subTest(enabled=enabled):
                    reassign_menu = add_reassign_condition_submenu(
                        menu,
                        {
                            "1": Condition(
                                uid="1",
                                name="One",
                                ref_no=1,
                                condition_type=Condition.TYPE_LINEAR,
                            )
                        },
                        Condition.TYPE_LINEAR,
                        enabled=enabled,
                    )
                    self.assertEqual(reassign_menu.submenu.isEnabled(), enabled)
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
            submenu.show()
            submenu.actions()[-1].defaultWidget().click()
            self.app.processEvents()
            submenu.close()
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

    def test_reassign_condition_submenu_lists_all_conditions_without_overflow_under_limit(
        self,
    ):
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
            self.assertEqual(submenu.property("ost_compact_overflow_item_count"), 2)
            self.assertEqual(
                [action.text() for action in submenu.actions()],
                ["1 - First", "2 - Second"],
            )
            self.assertEqual(
                [
                    action
                    for action in submenu.actions()
                    if isinstance(action, QtWidgets.QWidgetAction)
                ],
                [],
            )
            self.assertEqual(set(reassign_menu.actions.values()), {"1", "2"})
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
            self.assertEqual(reassign_menu.submenu.actions(), [])
            empty_menu = add_reassign_condition_submenu(menu, {}, Condition.TYPE_LINEAR)
            self.assertEqual(menu.actions(), [])
            self.assertEqual(empty_menu.actions, {})
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
        self.assertEqual(linear_state.takeoff_uids, ["l1", "l2"])
        self.assertTrue(linear_state.show_assign)
        self.assertTrue(linear_state.show_negative)
        self.assertFalse(linear_state.show_curved)
        mixed_state = build_selected_takeoff_context_state(
            ["l1", "a1"], takeoffs.get, conditions
        )
        self.assertIsNone(mixed_state.reassign_geometry_type)
        self.assertEqual(mixed_state.takeoff_uids, ["l1", "a1"])
        unknown_condition = build_selected_takeoff_context_state(
            ["l1", "orphan"],
            {**takeoffs, "orphan": Takeoff(uid="orphan", condition_uid="gone")}.get,
            conditions,
        )
        self.assertIsNone(unknown_condition.reassign_geometry_type)
        count_conditions = {
            "count": Condition(uid="count", condition_type=Condition.TYPE_COUNT),
            "attachment": Condition(
                uid="attachment", condition_type=Condition.TYPE_ATTACHMENT
            ),
        }
        count_state = build_selected_takeoff_context_state(
            ["c1", "c2"],
            {
                "c1": Takeoff(uid="c1", condition_uid="count"),
                "c2": Takeoff(uid="c2", condition_uid="attachment"),
            }.get,
            count_conditions,
        )
        self.assertEqual(count_state.reassign_geometry_type, Condition.TYPE_COUNT)

    def test_selected_takeoff_context_state_skips_unresolved_uids(self):
        conditions = {
            "linear": Condition(uid="linear", condition_type=Condition.TYPE_LINEAR)
        }
        takeoffs = {"l1": Takeoff(uid="l1", condition_uid="linear")}
        state = build_selected_takeoff_context_state(
            ["missing", "l1"], takeoffs.get, conditions
        )
        self.assertEqual(state.takeoff_uids, ["l1"])
        self.assertTrue(state.show_curved)
        empty = build_selected_takeoff_context_state(
            ["missing"], takeoffs.get, conditions
        )
        self.assertEqual(empty.takeoff_uids, [])
        self.assertFalse(empty.show_assign)
        self.assertFalse(empty.show_negative)
        self.assertFalse(empty.show_curved)
        self.assertFalse(empty.all_negative)
        self.assertFalse(empty.all_curved)
        self.assertIsNone(empty.reassign_geometry_type)

    def test_selected_takeoff_context_state_tracks_curve_and_negative_flags(self):
        conditions = {
            "linear": Condition(uid="linear", condition_type=Condition.TYPE_LINEAR),
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
        }
        straight = Takeoff(uid="s", condition_uid="linear", curve=-1)
        curved = Takeoff(uid="c", condition_uid="linear", curve=0)
        negative_a = Takeoff(uid="n1", condition_uid="area", is_negative=True)
        negative_b = Takeoff(uid="n2", condition_uid="area", is_negative=True)
        positive = Takeoff(uid="p", condition_uid="area")
        every = {t.uid: t for t in (straight, curved, negative_a, negative_b, positive)}

        def state_for(*uids):
            return build_selected_takeoff_context_state(
                list(uids), every.get, conditions
            )

        self.assertTrue(state_for("s").show_curved)
        self.assertFalse(state_for("s").all_curved)
        self.assertTrue(state_for("c").all_curved)
        self.assertFalse(state_for("s", "c").show_curved)
        self.assertFalse(state_for("s", "c").all_curved)
        self.assertFalse(state_for("p").show_curved)
        self.assertTrue(state_for("n1", "n2").all_negative)
        self.assertFalse(state_for("n1", "p").all_negative)
        self.assertFalse(state_for("p").all_negative)

    def test_selected_hole_takeoffs_hide_assign_and_negative_actions(self):
        conditions = {
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
            "linear": Condition(uid="linear", condition_type=Condition.TYPE_LINEAR),
        }
        parent = Takeoff(uid="parent", condition_uid="area")
        hole = Takeoff(uid="hole", condition_uid="area", parent_uid="parent")
        linear = Takeoff(uid="linear-1", condition_uid="linear")
        linear_hole = Takeoff(
            uid="linear-hole", condition_uid="linear", parent_uid="linear-1"
        )
        every = {
            "parent": parent,
            "hole": hole,
            "linear-1": linear,
            "linear-hole": linear_hole,
        }

        def state_for(*uids):
            return build_selected_takeoff_context_state(
                list(uids), every.get, conditions
            )

        only_hole = state_for("hole")
        self.assertEqual(only_hole.takeoff_uids, ["hole"])
        self.assertFalse(only_hole.show_assign)
        self.assertFalse(only_hole.show_negative)
        self.assertFalse(only_hole.all_negative)
        both = state_for("parent", "hole")
        self.assertTrue(both.show_assign)
        self.assertFalse(both.show_negative)
        only_parent = state_for("parent")
        self.assertTrue(only_parent.show_assign)
        self.assertTrue(only_parent.show_negative)
        # The curved toggle needs exactly one selected takeoff: a linear
        # takeoff selected together with its hole does not offer it.
        self.assertTrue(state_for("linear-1").show_curved)
        self.assertFalse(state_for("linear-1", "linear-hole").show_curved)

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

    def test_command_submenu_triggers_with_action_key_and_applies_state(self):
        menu = QtWidgets.QMenu()
        triggered = []
        states = {
            "first": {"text": "First (shortcut)", "enabled": True},
            "second": {"enabled": True, "checkable": True, "checked": True},
        }
        try:
            result = add_context_command_submenu(
                menu,
                "Group",
                (("First", "first"), None, ("Second", "second"), ("Third", "third")),
                triggered.append,
                lambda key: states.get(key),
            )
            self.assertEqual(menu.actions()[0].menu(), result.submenu)
            self.assertEqual(result.submenu.title(), "Group")
            self.assertEqual(
                [(a.text(), a.isSeparator()) for a in result.submenu.actions()],
                [
                    ("First (shortcut)", False),
                    ("", True),
                    ("Second", False),
                    ("Third", False),
                ],
            )
            self.assertEqual(set(result.actions_by_key), {"first", "second", "third"})
            self.assertTrue(result.actions_by_key["first"].isEnabled())
            self.assertTrue(result.actions_by_key["second"].isCheckable())
            self.assertTrue(result.actions_by_key["second"].isChecked())
            self.assertFalse(result.actions_by_key["third"].isEnabled())
            self.assertFalse(result.actions_by_key["third"].isCheckable())
            result.actions_by_key["first"].trigger()
            result.actions_by_key["second"].trigger()
            self.assertEqual(triggered, ["first", "second"])
        finally:
            menu.deleteLater()

    def test_context_command_state_defaults_to_disabled_with_fallback_text(self):
        self.assertEqual(
            context_command_state(None, "key", "Fallback"),
            {
                "text": "Fallback",
                "enabled": False,
                "checkable": False,
                "checked": False,
            },
        )
        self.assertEqual(
            context_command_state(lambda _key: None, "key", "Fallback")["enabled"],
            False,
        )
        coerced = context_command_state(
            lambda key: {"text": "", "enabled": 1, "checked": 1}, "key", "Fallback"
        )
        self.assertEqual(
            coerced,
            {
                "text": "Fallback",
                "enabled": True,
                "checkable": False,
                "checked": True,
            },
        )
        # 1 == True, so pin that the flags are real bools, not truthy values.
        self.assertTrue(
            all(type(value) is bool for key, value in coerced.items() if key != "text")
        )

    def test_clipboard_and_page_actions_trigger_their_action_keys(self):
        triggered = []
        menu = QtWidgets.QMenu()
        try:
            add_context_clipboard_actions(
                menu, triggered.append, lambda _key: {"enabled": True}
            )
            self.assertEqual(
                [action.text() for action in menu.actions()],
                ["Cut", "Copy", "Paste", "Delete"],
            )
            # The action key also selects each command's icon.
            self.assertTrue(all(not a.icon().isNull() for a in menu.actions()))
            for action in menu.actions():
                action.trigger()
            self.assertEqual(
                triggered, [ACTION_CUT, ACTION_COPY, ACTION_PASTE, ACTION_DELETE]
            )
            page_menu = QtWidgets.QMenu()
            page_triggered = []
            try:
                add_context_page_actions(
                    page_menu,
                    page_triggered.append,
                    lambda _key: {"enabled": True},
                    separate_delete=True,
                )
                self.assertEqual(
                    [
                        (action.text(), action.isSeparator())
                        for action in page_menu.actions()
                    ],
                    [("Rename Page...", False), ("", True), ("Delete Page", False)],
                )
                for action in page_menu.actions():
                    if not action.isSeparator():
                        action.trigger()
                self.assertEqual(page_triggered, ["rename_page", ACTION_DELETE_PAGE])
                plain_menu = QtWidgets.QMenu()
                try:
                    add_context_page_actions(
                        plain_menu, lambda _key: None, lambda _key: {"enabled": True}
                    )
                    self.assertEqual(
                        [action.text() for action in plain_menu.actions()],
                        ["Rename Page...", "Delete Page"],
                    )
                finally:
                    plain_menu.deleteLater()
            finally:
                page_menu.deleteLater()
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
            self.assertTrue(actions.color_action.isEnabled())
            self.assertTrue(all(action.isEnabled() for action in width_actions))
            self.assertEqual(
                sorted(actions.width_actions.values()),
                [float(width) for width in range(1, 17)],
            )
        finally:
            menu.deleteLater()

    def test_selected_annotation_style_actions_invoke_callbacks(self):
        annotations = {
            "line-1": BidAnnotation(uid="line-1", annotation_type="line", width=8.0),
        }
        state = build_selected_annotation_style_context_state(
            ["line-1"], annotations.get
        )
        menu = QtWidgets.QMenu()
        widths = []
        colors = []
        try:
            actions = add_selected_annotation_style_actions(
                menu,
                state,
                select_color_callback=lambda: colors.append("color"),
                line_width_callback=widths.append,
                enabled=True,
            )
            width_menu_actions = menu.actions()[0].menu().actions()
            width_menu_actions[11].trigger()
            width_menu_actions[0].trigger()
            actions.color_action.trigger()
            self.assertEqual(widths, [12.0, 1.0])
            self.assertEqual(colors, ["color"])
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

    def test_context_width_checks_only_exact_integer_widths_in_range(self):
        for width, expected in (
            (1.0, ["1px"]),
            (16.0, ["16px"]),
            (4.0000001, ["4px"]),
            (4.5, []),
            (0.0, []),
            (0.5, []),
            (17.0, []),
            (100.0, []),
        ):
            with self.subTest(width=width):
                annotation = BidAnnotation(
                    uid="rect-1", annotation_type="rect", width=width
                )
                state = build_selected_annotation_style_context_state(
                    ["rect-1"], lambda _uid: annotation
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
                        [a.text() for a in width_actions if a.isChecked()], expected
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

    def test_hotlink_namedview_and_unknown_annotations_show_no_generic_style(self):
        for annotation_type in ("hotlink", "namedview", "callout"):
            with self.subTest(annotation_type=annotation_type):
                annotation = BidAnnotation(uid="a", annotation_type=annotation_type)
                state = build_selected_annotation_style_context_state(
                    ["a"], lambda _uid: annotation
                )
                self.assertEqual(state.annotation_uids, ["a"])
                self.assertFalse(state.show_color)
                self.assertFalse(state.show_line_width)
                menu = QtWidgets.QMenu()
                try:
                    actions = add_selected_annotation_style_actions(
                        menu,
                        state,
                        select_color_callback=lambda: None,
                        line_width_callback=lambda _width: None,
                        enabled=True,
                    )
                    self.assertEqual(menu.actions(), [])
                    self.assertIsNone(actions.color_action)
                finally:
                    menu.deleteLater()

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
        menu = QtWidgets.QMenu()
        try:
            actions = add_selected_annotation_style_actions(
                menu,
                state,
                select_color_callback=lambda: None,
                line_width_callback=lambda _width: None,
                enabled=True,
            )
            self.assertEqual(
                [action.text() for action in menu.actions()], ["Select Color..."]
            )
            self.assertEqual(actions.width_actions, {})
        finally:
            menu.deleteLater()

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
        self.assertEqual(line_and_highlight.annotation_uids, ["line-1", "highlight-1"])
        only_unresolved = build_selected_annotation_style_context_state(
            ["gone"], annotations.get
        )
        self.assertEqual(only_unresolved.annotation_uids, [])
        self.assertFalse(only_unresolved.show_color)
        partly_unresolved = build_selected_annotation_style_context_state(
            ["gone", "line-1"], annotations.get
        )
        self.assertEqual(partly_unresolved.annotation_uids, ["line-1"])
        self.assertTrue(partly_unresolved.show_color)
        self.assertTrue(partly_unresolved.show_line_width)

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

    def test_widths_within_tolerance_are_treated_as_shared(self):
        annotations = {
            "line-1": BidAnnotation(uid="line-1", annotation_type="line", width=6.0),
            "rect-1": BidAnnotation(
                uid="rect-1", annotation_type="rect", width=6.0000001
            ),
            "oval-1": BidAnnotation(uid="oval-1", annotation_type="oval", width=6.01),
        }
        close = build_selected_annotation_style_context_state(
            ["line-1", "rect-1"], annotations.get
        )
        apart = build_selected_annotation_style_context_state(
            ["line-1", "rect-1", "oval-1"], annotations.get
        )
        self.assertEqual(close.current_line_width, 6.0)
        self.assertIsNone(apart.current_line_width)


class ViewContextMenuConditionBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls._quit_on_last_window_closed = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls._quit_on_last_window_closed)

    def tearDown(self):
        self.app.processEvents()

    def test_trim_condition_hides_curved_context_action(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            trim=True,
        )
        takeoff = Takeoff(uid="t1", condition_uid="c1", position=[0, 0, 12, 0])
        state = build_selected_takeoff_context_state(
            ["t1"], lambda _uid: takeoff, {"c1": condition}
        )
        self.assertFalse(state.show_curved)
        untrimmed = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            trim=False,
        )
        control = build_selected_takeoff_context_state(
            ["t1"], lambda _uid: takeoff, {"c1": untrimmed}
        )
        self.assertTrue(control.show_curved)
        self.assertTrue(control.show_assign)
