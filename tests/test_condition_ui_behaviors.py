import math
import os
import unittest
from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsTextItem
from ost_visualizer.domain.entities import pattern as pattern_values
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.condition_quantity_service import (
    compute_page_quantities,
)
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.components import (
    conditions_sidebar as conditions_sidebar_module,
)
from ost_visualizer.presentation.components.area_combo import AreaComboBox
from ost_visualizer.presentation.dialogs.edit_condition_dialog import (
    EditConditionDialog,
)
from ost_visualizer.presentation.handlers.condition_action_handler import (
    ConditionActionHandler,
)
from ost_visualizer.presentation.managers.icon_manager import IconId, IconManager
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.utils.compact_context_menu import (
    COMPACT_CONTEXT_MENU_MAX_VISIBLE_ROWS,
    COMPACT_CONTEXT_MENU_NEXT_TEXT,
    COMPACT_CONTEXT_MENU_PREVIOUS_TEXT,
)
from ost_visualizer.presentation.utils.view_context_menu import (
    build_selected_takeoff_context_state,
)
from ost_visualizer.presentation.visualization.pdf.renderers.takeoff_renderer import (
    TakeoffRenderer,
)
from single_action import SingleCallRecorder


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class FakeReadService:
    def display_to_inches(self, text, _metric):
        try:
            return float(text)
        except ValueError:
            return None

    def inches_to_display(self, value, _metric):
        return "" if not value else str(value)

    def get_quantity_options_for_type(self, _condition_type):
        return []

    def get_valid_uoms_for_calc_type(self, _calc_type, _metric):
        return []


class FakeCoordinateSystem:
    page_info = {"view_scale": 1.0}

    def update_page_info(self, page_info):
        self.page_info.update(page_info)

    def parse_position(self, position):
        return list(position)

    def transform_vertices_to_2d(self, position):
        return list(position)

    def ost_to_pdf_points(self, value):
        return float(value)


class FakeColorService:
    def should_gray_out_takeoff(self, _takeoff, _page_area_selections):
        return False


class ConditionUiBehaviorTests(unittest.TestCase):
    def _make_conditions(self, count: int, prefix: str = "c"):
        return {
            f"{prefix}{index}": Condition(
                uid=f"{prefix}{index}",
                name=f"Condition {index}",
                ref_no=index,
            )
            for index in range(1, count + 1)
        }

    def _foldered_conditions(self):
        conditions = {
            "c1": Condition(uid="c1", name="Condition 1", ref_no=1, folder_uid="f1"),
            "c2": Condition(uid="c2", name="Condition 2", ref_no=2, folder_uid="f2"),
        }
        folders = {
            "f1": BidConditionFolder(uid="f1", name="Folder 1"),
            "f2": BidConditionFolder(uid="f2", name="Folder 2"),
        }
        return conditions, folders

    def _show_compact_sidebar(self, sidebar: ConditionsSidebar) -> None:
        sidebar.resize(260, 180)
        sidebar.show()
        self.app.processEvents()

    def _path_line_angle(self, item):
        path = item.path()
        first = path.elementAt(0)
        second = path.elementAt(1)
        return math.atan2(second.y - first.y, second.x - first.x)

    def _line_path_items(self, items):
        return [
            item
            for item in items
            if isinstance(item, QGraphicsPathItem) and item.path().elementCount() >= 2
        ]

    def _path_midpoint(self, item):
        path = item.path()
        first = path.elementAt(0)
        second = path.elementAt(1)
        return ((first.x + second.x) / 2.0, (first.y + second.y) / 2.0)

    def _line_spacing(self, first_item, second_item):
        line_angle = self._path_line_angle(first_item)
        normal_angle = line_angle + math.pi / 2.0
        first_projection = self._point_projection(
            self._path_midpoint(first_item), normal_angle
        )
        second_projection = self._point_projection(
            self._path_midpoint(second_item), normal_angle
        )
        return abs(second_projection - first_projection)

    def test_condition_assignment_context_submenus_use_compact_overflow_menus(self):
        sidebar = ConditionsSidebar(None)
        try:
            sidebar._conditions = {
                "c1": Condition(
                    uid="c1",
                    layer_uid="layer-10",
                    cdn_type_uid="type-10",
                )
            }
            sidebar.set_available_layers(
                [
                    BidLayer(
                        uid=f"layer-{index}",
                        bid_uid="bid",
                        name=f"Layer {index:02d}",
                        show=True,
                        sequence=index,
                    )
                    for index in range(1, 81)
                ]
            )
            sidebar.set_available_condition_types(
                [
                    CdnType(uid=f"type-{index}", name=f"Type {index:02d}")
                    for index in range(1, 81)
                ]
            )
            menu = QtWidgets.QMenu()
            try:
                sidebar._add_condition_assignment_submenus(menu, ["c1"], True)
                submenus = [action.menu() for action in menu.actions()]
                self.assertEqual(
                    [submenu.title() for submenu in submenus],
                    ["Set Layer", "Set Type"],
                )
                for submenu in submenus:
                    with self.subTest(submenu=submenu.title()):
                        self.assertTrue(submenu.property("ost_compact_overflow_menu"))
                        self.assertEqual(
                            submenu.property("ost_compact_overflow_max_visible_rows"),
                            COMPACT_CONTEXT_MENU_MAX_VISIBLE_ROWS,
                        )
                        self.assertEqual(
                            submenu.property("ost_compact_overflow_item_count"), 80
                        )
                        self.assertEqual(
                            len(submenu.actions()),
                            COMPACT_CONTEXT_MENU_MAX_VISIBLE_ROWS,
                        )
                        self.assertEqual(
                            submenu.actions()[-1].text(),
                            COMPACT_CONTEXT_MENU_NEXT_TEXT,
                        )
                        checked = [
                            action.data()
                            for action in submenu.actions()
                            if action.isChecked()
                        ]
                        self.assertEqual(len(checked), 1)
                        self.assertTrue(str(checked[0]).endswith("-10"))
                        submenu.actions()[-1].defaultWidget().click()
                        self.app.processEvents()
                        self.assertEqual(
                            submenu.actions()[0].text(),
                            COMPACT_CONTEXT_MENU_PREVIOUS_TEXT,
                        )
            finally:
                menu.deleteLater()
        finally:
            sidebar.deleteLater()

    def _point_projection(self, point, angle):
        return point[0] * math.cos(angle) + point[1] * math.sin(angle)

    def _assert_parallel_angle(self, actual, expected):
        diff = abs((actual - expected + math.pi / 2.0) % math.pi - math.pi / 2.0)
        self.assertLess(diff, 0.01)

    def _assert_line_avoids_rect(self, item, left, top, right, bottom):
        path = item.path()
        first = path.elementAt(0)
        second = path.elementAt(1)
        for step in range(1, 10):
            ratio = step / 10.0
            x = first.x + (second.x - first.x) * ratio
            y = first.y + (second.y - first.y) * ratio
            self.assertFalse(left < x < right and top < y < bottom)

    def _render_takeoff_items(self, condition, takeoff):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        rendered = renderer.create_all_path_items(
            [takeoff],
            {condition.uid: condition},
            {condition.uid: SimpleNamespace(hex="#123456", opacity=1.0)},
        )
        items = rendered[0][1]
        return items if isinstance(items, list) else [items]

    def test_condition_entity_does_not_expose_label_style_fields(self):
        condition_fields = {field.name for field in fields(Condition)}
        self.assertFalse(
            {
                "name_font_name",
                "name_font_color",
                "name_font_size",
                "name_font_bold",
                "name_font_italic",
                "name_font_underline",
            }
            & condition_fields
        )

    def test_condition_sidebar_rebuild_clears_stale_selection_cache(self):
        sidebar = ConditionsSidebar(None)
        sidebar.load_conditions(
            {"c1": Condition(uid="c1", name="Condition 1", ref_no=1)},
            {},
            "Project",
        )
        sidebar.highlight_conditions({"c1"})
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])
        sidebar.load_conditions(
            {"c2": Condition(uid="c2", name="Condition 2", ref_no=2)},
            {},
            "Project",
        )
        self.assertEqual(sidebar.get_selected_condition_uids(), [])

    def test_condition_sidebar_passive_reload_does_not_reapply_stale_scroll(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        self._show_compact_sidebar(sidebar)
        sidebar.load_conditions(self._make_conditions(80, "a"), {}, "Project A")
        self.app.processEvents()
        scrollbar = sidebar.tree.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.assertGreater(scrollbar.value(), 0)
        sidebar.load_conditions(self._make_conditions(80, "b"), {}, "Project B")
        self.app.processEvents()
        self.assertEqual(scrollbar.value(), 0)

    def test_condition_sidebar_highlight_scrolls_to_revealed_condition(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        self._show_compact_sidebar(sidebar)
        sidebar.load_conditions(self._make_conditions(80), {}, "Project")
        self.app.processEvents()
        scrollbar = sidebar.tree.verticalScrollBar()
        scrollbar.setValue(0)
        sidebar.highlight_conditions({"c80"})
        self.app.processEvents()
        self.assertGreater(scrollbar.value(), 0)
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c80"])

    def test_condition_sidebar_explicit_highlight_expands_condition_path(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions, folders = self._foldered_conditions()
        sidebar.load_conditions(conditions, folders, "Project")
        folder = sidebar._folder_items["f1"]
        cdn_type = folder.child(0)
        folder.setExpanded(False)
        cdn_type.setExpanded(False)
        sidebar.highlight_conditions({"c1"})
        self.assertTrue(folder.isExpanded())
        self.assertTrue(cdn_type.isExpanded())
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])

    def test_condition_sidebar_passive_restore_does_not_expand_condition_path(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions, folders = self._foldered_conditions()
        sidebar.load_conditions(conditions, folders, "Project")
        folder = sidebar._folder_items["f1"]
        folder.setExpanded(False)
        sidebar._restore_context_selection(["c1"], [])
        self.assertFalse(folder.isExpanded())
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])

    def test_condition_sidebar_passive_reload_preserves_visible_highlight_without_scroll(
        self,
    ):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        self._show_compact_sidebar(sidebar)
        sidebar.load_conditions(self._make_conditions(80), {}, "Project")
        self.app.processEvents()
        scrollbar = sidebar.tree.verticalScrollBar()
        scrollbar.setValue(0)
        sidebar.highlight_conditions({"c1"}, reveal=False)
        self.app.processEvents()
        sidebar.load_conditions(self._make_conditions(80), {}, "Project")
        self.app.processEvents()
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])
        self.assertTrue(sidebar._condition_items["c1"].isSelected())
        self.assertEqual(scrollbar.value(), 0)

    def test_condition_sidebar_passive_reload_preserves_hidden_selection_without_expanding(
        self,
    ):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions, folders = self._foldered_conditions()
        sidebar.load_conditions(conditions, folders, "Project")
        folder = sidebar._folder_items["f1"]
        folder.setExpanded(False)
        sidebar._restore_context_selection(["c1"], [])
        sidebar.load_conditions(dict(conditions), folders, "Project")
        self.assertFalse(sidebar._folder_items["f1"].isExpanded())
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])

    def test_condition_sidebar_passive_reload_preserves_scroll_for_same_project(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        self._show_compact_sidebar(sidebar)
        sidebar.load_conditions(self._make_conditions(80), {}, "Project")
        self.app.processEvents()
        scrollbar = sidebar.tree.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum() // 2)
        expected = scrollbar.value()
        sidebar.load_conditions(self._make_conditions(80), {}, "Project")
        self.app.processEvents()
        self.assertEqual(scrollbar.value(), expected)

    def test_condition_sidebar_highlight_visible_condition_does_not_scroll(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        self._show_compact_sidebar(sidebar)
        sidebar.load_conditions(self._make_conditions(80), {}, "Project")
        self.app.processEvents()
        scrollbar = sidebar.tree.verticalScrollBar()
        scrollbar.setValue(0)
        sidebar.highlight_conditions({"c1"})
        self.app.processEvents()
        self.assertEqual(scrollbar.value(), 0)

    def test_condition_sidebar_reveal_above_viewport_positions_near_top(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        self._show_compact_sidebar(sidebar)
        sidebar.load_conditions(self._make_conditions(80), {}, "Project")
        self.app.processEvents()
        sidebar.tree.verticalScrollBar().setValue(
            sidebar.tree.verticalScrollBar().maximum()
        )
        sidebar.highlight_conditions({"c1"})
        self.app.processEvents()
        rect = sidebar.tree.visualItemRect(sidebar._condition_items["c1"])
        self.assertLess(rect.center().y(), sidebar.tree.viewport().rect().center().y())

    def test_condition_sidebar_reveal_below_viewport_positions_near_bottom(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        self._show_compact_sidebar(sidebar)
        sidebar.load_conditions(self._make_conditions(80), {}, "Project")
        self.app.processEvents()
        sidebar.tree.verticalScrollBar().setValue(0)
        sidebar.highlight_conditions({"c80"})
        self.app.processEvents()
        rect = sidebar.tree.visualItemRect(sidebar._condition_items["c80"])
        self.assertGreater(
            rect.center().y(), sidebar.tree.viewport().rect().center().y()
        )

    def test_condition_sidebar_reload_preserves_expanded_state(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions, folders = self._foldered_conditions()
        sidebar.load_conditions(conditions, folders, "Project")
        sidebar._folder_items["f1"].setExpanded(False)
        sidebar._folder_items["f2"].setExpanded(True)
        sidebar.load_conditions(dict(conditions), folders, "Project")
        self.assertFalse(sidebar._folder_items["f1"].isExpanded())
        self.assertTrue(sidebar._folder_items["f2"].isExpanded())

    def test_condition_sidebar_delete_refresh_preserves_expanded_state(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions, folders = self._foldered_conditions()
        sidebar.load_conditions(conditions, folders, "Project")
        sidebar._folder_items["f1"].setExpanded(False)
        sidebar._folder_items["f2"].setExpanded(False)
        replacement_uid = sidebar.condition_selection_after_delete(["c2"])
        remaining = {"c1": conditions["c1"]}
        sidebar.load_conditions(remaining, folders, "Project")
        if replacement_uid:
            sidebar.highlight_conditions({replacement_uid}, reveal=False)
        self.assertFalse(sidebar._folder_items["f1"].isExpanded())
        self.assertFalse(sidebar._folder_items["f2"].isExpanded())
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])

    def test_condition_sidebar_duplicate_refresh_preserves_expanded_state(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions, folders = self._foldered_conditions()
        sidebar.load_conditions(conditions, folders, "Project")
        sidebar._folder_items["f1"].setExpanded(False)
        sidebar._folder_items["f2"].setExpanded(False)
        duplicated = dict(conditions)
        duplicated["c3"] = Condition(
            uid="c3", name="Condition 3", ref_no=3, folder_uid="f2"
        )
        sidebar.load_conditions(duplicated, folders, "Project")
        sidebar.highlight_conditions({"c3"}, reveal=False)
        self.assertFalse(sidebar._folder_items["f1"].isExpanded())
        self.assertFalse(sidebar._folder_items["f2"].isExpanded())
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c3"])

    def test_condition_sidebar_delete_replacement_selects_previous_logical_condition(
        self,
    ):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(4)
        sidebar.load_conditions(conditions, {}, "Project")
        self.assertEqual(sidebar.condition_selection_after_delete(["c3"]), "c2")

    def test_condition_sidebar_delete_replacement_uses_next_when_no_previous(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(3)
        sidebar.load_conditions(conditions, {}, "Project")
        self.assertEqual(sidebar.condition_selection_after_delete(["c1"]), "c2")

    def test_condition_sidebar_delete_replacement_uses_previous_for_multi_delete(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(5)
        sidebar.load_conditions(conditions, {}, "Project")
        self.assertEqual(sidebar.condition_selection_after_delete(["c3", "c4"]), "c2")

    def test_condition_sidebar_delete_replacement_clears_when_all_deleted(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(2)
        sidebar.load_conditions(conditions, {}, "Project")
        self.assertIsNone(sidebar.condition_selection_after_delete(["c1", "c2"]))

    def _make_condition_delete_handler(self, sidebar, conditions, highlighted):
        class Access:
            def is_allowed(self, feature):
                return feature == Feature.DELETE_CONDITION

        class WriteService:
            def delete_conditions(self, _file_path, _bid_uid, condition_uids):
                for uid in condition_uids:
                    conditions.pop(uid, None)
                sidebar.load_conditions(conditions, {}, "Project")
                return True

        coordinator = SimpleNamespace(
            ui_access_manager=Access(),
            conditions_sidebar=sidebar,
            placement=SimpleNamespace(force_exit=lambda: None),
            flush_deferred_for_file=lambda _file_path: True,
            highlight_sidebar=lambda uids, reveal=True: sidebar.highlight_conditions(
                set(uids), reveal=reveal
            ),
            ensure_select_mode=lambda: None,
            refresh_conditions_ui=lambda: sidebar.load_conditions(
                conditions, {}, "Project"
            ),
        )
        ui_state = SimpleNamespace(
            highlighted_condition_uids=set(highlighted),
            get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1"),
        )
        return ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=WriteService(),
            project_read_service=None,
            project_data=SimpleNamespace(),
            ui_state_manager=ui_state,
        )

    def test_condition_delete_handler_selects_previous_after_write_refresh(self):
        from ost_visualizer.presentation.handlers import condition_action_handler

        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(4)
        sidebar.load_conditions(conditions, {}, "Project")
        handler = self._make_condition_delete_handler(sidebar, conditions, {"c3"})
        original_confirm = condition_action_handler.confirm_delete_conditions
        condition_action_handler.confirm_delete_conditions = lambda _parent, names: [
            uid for uid, _name in names
        ]
        try:
            handler.on_delete_requested(["c3"])
        finally:
            condition_action_handler.confirm_delete_conditions = original_confirm
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c2"])

    def test_condition_delete_handler_selects_previous_after_multi_write_refresh(self):
        from ost_visualizer.presentation.handlers import condition_action_handler

        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(5)
        sidebar.load_conditions(conditions, {}, "Project")
        handler = self._make_condition_delete_handler(sidebar, conditions, {"c3", "c4"})
        original_confirm = condition_action_handler.confirm_delete_conditions
        condition_action_handler.confirm_delete_conditions = lambda _parent, names: [
            uid for uid, _name in names
        ]
        try:
            handler.on_delete_requested(["c3", "c4"])
        finally:
            condition_action_handler.confirm_delete_conditions = original_confirm
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c2"])

    def test_condition_sidebar_layer_visibility_update_preserves_quantities(self):
        sidebar = ConditionsSidebar(None)
        condition = Condition(uid="c1", name="Condition 1", ref_no=1)
        sidebar.load_conditions({"c1": condition}, {}, "Project")
        sidebar.update_quantities({"c1": (12.0, 0.0, 0.0)})
        item = sidebar._condition_items["c1"]
        before = [item.text(col) for col in range(2, 5)]
        condition.layer_visible = False
        sidebar.apply_layer_visibility_state({"c1": condition})
        self.assertEqual([item.text(col) for col in range(2, 5)], before)
        self.assertFalse(sidebar.is_condition_placeable("c1"))

    def test_condition_sidebar_layer_visibility_updates_only_matching_layer_rows(self):
        sidebar = ConditionsSidebar(None)
        condition_a = Condition(
            uid="c1", name="Condition 1", ref_no=1, layer_uid="layer-a"
        )
        condition_b = Condition(
            uid="c2", name="Condition 2", ref_no=2, layer_uid="layer-b"
        )
        try:
            sidebar.load_conditions(
                {"c1": condition_a, "c2": condition_b}, {}, "Project"
            )
            condition_a.layer_visible = False
            with patch.object(
                conditions_sidebar_module,
                "make_condition_color_icon",
                wraps=conditions_sidebar_module.make_condition_color_icon,
            ) as make_icon:
                sidebar.apply_layer_visibility_state(
                    {"c1": condition_a, "c2": condition_b},
                    layer_uid="layer-a",
                )
            self.assertEqual(make_icon.call_count, 1)
            self.assertFalse(sidebar.is_condition_placeable("c1"))
            self.assertTrue(sidebar.is_condition_placeable("c2"))
        finally:
            sidebar.deleteLater()

    def test_takeoff_renderer_creates_items_for_hidden_condition_layers(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1",
            name="Hidden Layer Condition",
            condition_type=Condition.TYPE_LINEAR,
            layer_visible=False,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 10.0, 0.0],
        )
        rendered = renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
        )
        self.assertEqual([uid for uid, _item in rendered], ["t1"])

    def test_condition_cut_paste_to_root_and_folder_uses_edit_permission(self):
        sidebar = ConditionsSidebar(None)
        pasted = []
        sidebar.paste_requested.connect(
            lambda uids, target: pasted.append((list(uids), dict(target)))
        )
        sidebar.load_conditions(
            {"c1": Condition(uid="c1", name="Condition 1", ref_no=1)},
            {"f1": BidConditionFolder(uid="f1", name="Folder")},
            "Project",
        )
        sidebar.set_duplicate_enabled(False)
        sidebar.set_edit_enabled(True)
        sidebar.highlight_conditions({"c1"})
        sidebar._cut_selected_conditions()
        root = sidebar.tree.topLevelItem(0)
        folder = sidebar._folder_items["f1"]
        self.assertTrue(sidebar._can_paste_to_item(root))
        self.assertTrue(sidebar._can_paste_context_target("root", root))
        sidebar._paste_copied_conditions(folder)
        self.assertEqual(pasted[0][0], ["c1"])
        self.assertEqual(pasted[0][1]["kind"], "folder")
        self.assertEqual(pasted[0][1]["folder_uid"], "f1")
        self.assertTrue(pasted[0][1]["cut"])

    def test_condition_folder_nodes_use_folder_icon(self):
        sidebar = ConditionsSidebar(None)
        sidebar.load_conditions(
            {},
            {"f1": BidConditionFolder(uid="f1", name="Folder")},
            "Project",
        )
        folder = sidebar._folder_items["f1"]
        self.assertFalse(folder.icon(0).isNull())
        self.assertEqual(
            folder.icon(0).cacheKey(),
            IconManager.icon(IconId.FOLDER).cacheKey(),
        )

    def test_condition_sidebar_cdn_type_group_rows_are_bold(self):
        sidebar = ConditionsSidebar(None)
        sidebar.load_conditions(
            {
                "c1": Condition(
                    uid="c1",
                    name="Condition 1",
                    ref_no=1,
                    cdn_type_uid="type-1",
                    cdn_type_name="Type 1",
                )
            },
            {},
            "Project",
        )
        root = sidebar.tree.topLevelItem(0)
        cdn_type_item = root.child(0)
        condition_item = cdn_type_item.child(0)
        self.assertEqual(cdn_type_item.text(0), "Type 1")
        self.assertTrue(cdn_type_item.font(0).bold())
        self.assertFalse(condition_item.font(0).bold())

    def test_area_combo_clears_deleted_selected_area_uid_on_reload(self):
        combo = AreaComboBox(None)
        combo.load_areas(
            [BidArea(uid="a1", bid_uid="b1", parent_uid="", name="Area 1", sequence=1)],
            selected_uid="a1",
        )
        self.assertEqual(combo.get_current_area_uid(), "a1")
        combo.load_areas([], selected_uid=None)
        self.assertEqual(combo.get_current_area_uid(), "")
        combo.set_current_area_uid("deleted")
        self.assertEqual(combo.get_current_area_uid(), "")

    def test_area_combo_popup_bold_state_does_not_style_display_text(self):
        combo = AreaComboBox(None)
        combo.load_areas(
            [BidArea(uid="a1", bid_uid="b1", parent_uid="", name="Area 1", sequence=1)],
            areas_with_takeoff={"0"},
            selected_uid="0",
        )
        self.assertTrue(combo._area_items["0"].font().bold())
        self.assertEqual(combo.lineEdit().text(), "(Unassigned)")
        self.assertFalse(combo.lineEdit().font().bold())
        combo.set_current_area_uid("")
        self.assertEqual(combo.lineEdit().text(), "(All Areas)")
        self.assertFalse(combo.lineEdit().font().bold())

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        self.app.processEvents()

    def _make_sidebar_with_selected_condition(self):
        sidebar = ConditionsSidebar(None)
        deleted = []
        sidebar.delete_requested.connect(lambda uids: deleted.append(list(uids)))
        sidebar.load_conditions(
            {"c1": Condition(uid="c1", name="Condition 1", ref_no=1)},
            {},
            "Project",
        )
        sidebar.set_delete_enabled(True)
        sidebar.highlight_conditions({"c1"})
        return sidebar, deleted

    def _make_dialog(self, condition):
        return EditConditionDialog(
            None,
            None,
            condition,
            ["c1"],
            {"c1": condition},
            {},
            {},
            lambda _uid: False,
            lambda _uid, _dto: True,
            read_service=FakeReadService(),
        )

    def test_edit_condition_ok_click_saves_once(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        save_calls = SingleCallRecorder(
            lambda _uid, _dto: SimpleNamespace(success=True)
        )
        dialog = EditConditionDialog(
            None,
            None,
            condition,
            ["c1"],
            {"c1": condition},
            {},
            {},
            lambda _uid: False,
            save_calls,
            read_service=FakeReadService(),
        )
        dialog._name_edit.setText("Updated Condition")
        dialog._ok_btn.click()
        save_calls.assert_called_once(self, "Edit Condition OK click")
        self.assertEqual(save_calls.calls[0][0][0], "c1")
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        dialog.close()

    def test_edit_condition_dimension_inputs_use_consistent_heights(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_COUNT,
            height=12.0,
            width=24.0,
            depth=6.0,
            display_size=100.0,
        )
        dialog = self._make_dialog(condition)
        dialog.show()
        self.app.processEvents()
        expected_height = dialog._display_size_edit.height()
        self.assertEqual(dialog._dim_r0c1_stack.height(), expected_height)
        self.assertEqual(dialog._dim_r0c3_stack.height(), expected_height)
        self.assertEqual(dialog._height_edit.height(), expected_height)
        self.assertEqual(dialog._width_edit.height(), expected_height)
        dialog.close()

    def test_delete_key_invokes_condition_delete_for_tree_selection(self):
        sidebar, deleted = self._make_sidebar_with_selected_condition()
        sidebar.show()
        sidebar.tree.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        self.app.processEvents()
        QTest.keyClick(sidebar.tree, Qt.Key.Key_Delete)
        self.app.processEvents()
        self.assertEqual(deleted, [["c1"]])
        sidebar.close()

    def test_delete_key_is_ignored_while_text_input_has_focus(self):
        sidebar, deleted = self._make_sidebar_with_selected_condition()
        text_input = QtWidgets.QLineEdit(sidebar.tree)
        text_input.setText("typing")
        text_input.show()
        sidebar.show()
        text_input.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        self.app.processEvents()
        QTest.keyClick(text_input, Qt.Key.Key_Delete)
        self.app.processEvents()
        self.assertEqual(deleted, [])
        sidebar.close()

    def test_double_click_non_name_condition_cell_requests_edit_dialog(self):
        sidebar, _deleted = self._make_sidebar_with_selected_condition()
        edits = []
        sidebar.edit_requested.connect(lambda uids: edits.append(list(uids)))
        sidebar.set_edit_enabled(True)
        sidebar._on_item_double_clicked(sidebar._condition_items["c1"], 0)
        self.assertEqual(edits, [["c1"]])
        sidebar.close()

    def test_double_click_name_condition_cell_keeps_inline_rename_behavior(self):
        sidebar, _deleted = self._make_sidebar_with_selected_condition()
        edits = []
        sidebar.edit_requested.connect(lambda uids: edits.append(list(uids)))
        sidebar.set_edit_enabled(True)
        sidebar._on_item_double_clicked(sidebar._condition_items["c1"], 1)
        self.assertEqual(edits, [])
        sidebar.close()

    def test_edit_condition_dialog_initializes_style_locked_when_takeoffs_exist(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_AREA,
            ref_no=1,
        )
        dialog = EditConditionDialog(
            None,
            None,
            condition,
            ["c1"],
            {"c1": condition},
            {},
            {},
            lambda uid: uid == "c1",
            lambda _uid, _dto: True,
            read_service=FakeReadService(),
        )
        self.assertFalse(dialog._style_combo.isEnabled())
        self.assertEqual(
            dialog._style_combo.toolTip(),
            "Condition style cannot be changed after takeoffs have been placed.",
        )
        dialog.close()

    def test_condition_properties_cancel_does_not_refresh_or_highlight_sidebar(self):
        condition = Condition(uid="c1", name="Condition 1", ref_no=1)
        refreshes = []
        highlights = []

        class Access:
            def is_allowed(self, feature):
                return feature == Feature.EDIT_CONDITION

            def has_license(self):
                return True

        class Sidebar:
            def window(self):
                return None

            def collect_ordered_condition_uids(self):
                return ["c1"]

        class ProjectData:
            def is_current_bid_locked(self):
                return False

            def get_bid_conditions(self):
                return {"c1": condition}

            def get_all_takeoffs(self):
                return []

            def get_current_bid(self):
                return SimpleNamespace(measure_base=0)

        class ReadService:
            def get_cdn_types(self, _file_path):
                return {}

            def get_merged_bid_layers(self, _file_path, _bid_uid):
                return []

        class Dialog:
            condition_navigated = SimpleNamespace(connect=lambda _callback: None)

            def __init__(self, *args, **_dialog_options):
                pass

            def deleteLater(self):
                pass

        coordinator = SimpleNamespace(
            ui_access_manager=Access(),
            conditions_sidebar=Sidebar(),
            main_window=SimpleNamespace(icon_provider=None),
            event_bus=object(),
            refresh_conditions_ui=lambda: refreshes.append(True),
            highlight_sidebar=lambda uids, reveal=True: highlights.append(set(uids)),
            placement=SimpleNamespace(is_active=False),
            _is_takeoff_2d_view_active=lambda: True,
            flush_deferred_for_file=lambda _file_path: True,
        )
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=SimpleNamespace(),
            project_read_service=ReadService(),
            project_data=ProjectData(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1")
            ),
        )
        with patch(
            "ost_visualizer.presentation.handlers.condition_action_handler.EditConditionDialog",
            Dialog,
        ), patch(
            "ost_visualizer.presentation.handlers.condition_action_handler.exec_with_ost_blocking",
            lambda _dialog, _event_bus: QtWidgets.QDialog.DialogCode.Rejected,
        ):
            handler.on_edit_requested(["c1"])
        self.assertEqual(refreshes, [])
        self.assertEqual(highlights, [])

    def test_count_attachment_advanced_properties_show_only_display_name(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_COUNT,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        self.assertIsNotNone(dialog._display_name_check)
        dialog.close()

    def test_linear_advanced_properties_show_measurement_controls(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        self.assertIsNotNone(dialog._round_qty_check)
        self.assertIsNotNone(dialog._round_to_edit)
        self.assertIsNotNone(dialog._drop_run_check)
        self.assertIsNotNone(dialog._add_length_edit)
        self.assertIsNotNone(dialog._trim_check)
        self.assertIsNotNone(dialog._curved_check)
        dialog.close()

    def test_linear_advanced_groups_use_equal_layout_stretch(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        layout = dialog._advanced_tab.layout()
        self.assertEqual(layout.count(), 2)
        self.assertEqual(layout.stretch(0), 1)
        self.assertEqual(layout.stretch(1), 1)
        self.assertEqual(layout.itemAt(0).widget().title(), "Measurement")
        self.assertEqual(layout.itemAt(1).widget().title(), "Properties")
        dialog.close()

    def test_area_advanced_properties_show_grid_and_display_controls(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_AREA,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        self.assertIsNotNone(dialog._grid_check)
        self.assertIsNotNone(dialog._tile1_edit)
        self.assertIsNotNone(dialog._tile2_edit)
        self.assertIsNotNone(dialog._display_pattern_check)
        self.assertIsNotNone(dialog._display_dim_check)
        self.assertIsNotNone(dialog._display_name_check)
        dialog.close()

    def test_trim_disables_curved_segment_control(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        dialog._trim_check.setChecked(True)
        self.assertFalse(dialog._curved_check.isChecked())
        self.assertFalse(dialog._curved_check.isEnabled())
        dialog._dirty = False
        dialog.close()

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

    def test_new_area_condition_does_not_enable_display_dimension_by_default(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_AREA,
            ref_no=1,
        )
        dialog = EditConditionDialog(
            None,
            None,
            condition,
            ["c1"],
            {"c1": condition},
            {},
            {},
            lambda _uid: False,
            lambda _uid, _dto: True,
            read_service=FakeReadService(),
        )
        dialog._populate_defaults_for_type(Condition.TYPE_AREA)
        self.assertFalse(dialog._display_dim_check.isChecked())
        dialog.close()

    def test_round_quantity_rounds_linear_and_area_results_without_mutating_geometry(
        self,
    ):
        linear = Condition(
            uid="linear",
            condition_type=Condition.TYPE_LINEAR,
            calc_type1=1,
            uom1=1,
            round_quantity=True,
            round_up=12.0,
        )
        area = Condition(
            uid="area",
            condition_type=Condition.TYPE_AREA,
            calc_type1=11,
            uom1=4,
            round_quantity=True,
            round_up=12.0,
        )
        linear_takeoff = Takeoff(
            uid="t1", condition_uid="linear", position=[0.0, 0.0, 13.0, 0.0]
        )
        area_takeoff = Takeoff(
            uid="t2",
            condition_uid="area",
            position=[0.0, 0.0, 13.0, 0.0, 13.0, 13.0, 0.0, 13.0],
        )
        results = compute_page_quantities(
            {"linear": linear, "area": area}, [linear_takeoff, area_takeoff]
        )
        self.assertEqual(results["linear"][0], 24.0)
        self.assertEqual(results["area"][0], 180.0)
        self.assertEqual(linear_takeoff.position, [0.0, 0.0, 13.0, 0.0])

    def test_partial_quantity_request_returns_zero_for_condition_without_takeoffs(self):
        condition = Condition(uid="c1", condition_type=Condition.TYPE_AREA)
        results = compute_page_quantities(
            {"c1": condition}, [], only_condition_uids={"c1"}
        )
        self.assertEqual(results, {"c1": (0.0, 0.0, 0.0)})

    def test_display_name_dimension_and_grid_render_as_scene_items(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1",
            name="Area Label",
            condition_type=Condition.TYPE_AREA,
            color_fill=0,
            pattern=0,
            spacing=0.0,
            grid=True,
            grid_size1=3.0,
            grid_size2=3.0,
            display_name=True,
            display_dimension=True,
            calc_type1=11,
            uom1=4,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0],
        )
        rendered = renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
        )
        items = rendered[0][1]
        items = items if isinstance(items, list) else [items]
        text_items = [item for item in items if isinstance(item, QGraphicsTextItem)]
        grid_items = [
            item
            for item in items
            if isinstance(item, QGraphicsPathItem)
            and item.data(2) != "condition_label"
            and not item.path().boundingRect().isNull()
        ]
        dimension_label = next(
            item for item in text_items if item.data(3) == "display_dimension"
        )
        name_label = next(item for item in text_items if item.data(3) == "display_name")
        self.assertIn("Area Label", name_label.toPlainText())
        self.assertIn("144.00 SQ IN", dimension_label.toPlainText())
        name_center = name_label.mapToScene(name_label.boundingRect().center())
        dimension_center = dimension_label.mapToScene(
            dimension_label.boundingRect().center()
        )
        self.assertAlmostEqual(dimension_center.x(), 6.0)
        self.assertAlmostEqual(dimension_center.y(), 6.0)
        self.assertAlmostEqual(name_center.x(), dimension_center.x())
        self.assertGreater(name_center.y(), dimension_center.y())
        self.assertNotEqual(name_center, dimension_center)
        self.assertGreater(len(grid_items), 1)

    def test_linear_horizontal_pattern_follows_linear_direction(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_LINEAR,
            color_fill=0,
            pattern=pattern_values.HORIZONTAL,
            spacing=2.0,
            thickness=8.0,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 20.0, 20.0],
        )
        items = self._render_takeoff_items(condition, takeoff)
        pattern_item = items[1]
        self._assert_parallel_angle(self._path_line_angle(pattern_item), math.pi / 4.0)

    def test_linear_vertical_pattern_is_perpendicular_to_linear_direction(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_LINEAR,
            color_fill=0,
            pattern=pattern_values.VERTICAL,
            spacing=2.0,
            thickness=8.0,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 20.0, 20.0],
        )
        items = self._render_takeoff_items(condition, takeoff)
        pattern_item = items[1]
        self._assert_parallel_angle(self._path_line_angle(pattern_item), -math.pi / 4.0)

    def test_oriented_linear_diagonal_pattern_uses_configured_spacing(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_LINEAR,
            color_fill=0,
            pattern=pattern_values.BACKWARD_DIAG,
            spacing=2.0,
            thickness=12.0,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 20.0, 20.0],
        )
        items = self._render_takeoff_items(condition, takeoff)
        pattern_items = self._line_path_items(items[1:])
        self.assertGreaterEqual(len(pattern_items), 2)
        self.assertAlmostEqual(
            self._line_spacing(pattern_items[0], pattern_items[1]), 2.0, delta=0.01
        )

    def test_fixed_axis_area_diagonal_pattern_keeps_configured_spacing(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_AREA,
            color_fill=0,
            pattern=pattern_values.BACKWARD_DIAG,
            spacing=2.0,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0, 0.0, 20.0],
        )
        items = self._render_takeoff_items(condition, takeoff)
        pattern_items = self._line_path_items(items[1:])
        self.assertGreaterEqual(len(pattern_items), 2)
        self.assertAlmostEqual(
            self._line_spacing(pattern_items[0], pattern_items[1]), 2.0, delta=0.01
        )

    def test_area_linear_patterns_exclude_backout_hole(self):
        line_patterns = [
            pattern_values.HORIZONTAL,
            pattern_values.VERTICAL,
            pattern_values.BACKWARD_DIAG,
            pattern_values.FORWARD_DIAG,
        ]
        for pattern in line_patterns:
            with self.subTest(pattern=pattern):
                condition = Condition(
                    uid="c1",
                    condition_type=Condition.TYPE_AREA,
                    color_fill=0,
                    pattern=pattern,
                    spacing=2.0,
                )
                parent = Takeoff(
                    uid="parent",
                    condition_uid="c1",
                    position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0, 0.0, 20.0],
                )
                backout = Takeoff(
                    uid="backout",
                    condition_uid="c1",
                    parent_uid="parent",
                    position=[8.0, 8.0, 12.0, 8.0, 12.0, 12.0, 8.0, 12.0],
                )
                renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
                rendered = renderer.create_all_path_items(
                    [parent, backout],
                    {"c1": condition},
                    {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
                )
                items = rendered[0][1]
                items = items if isinstance(items, list) else [items]
                pattern_items = self._line_path_items(items[1:])
                self.assertGreater(len(pattern_items), 0)
                for item in pattern_items:
                    self.assertEqual(item.pen().capStyle(), Qt.PenCapStyle.FlatCap)
                    self._assert_line_avoids_rect(item, 8.0, 8.0, 12.0, 12.0)

    def test_area_linear_pattern_without_backout_still_renders_lines(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_AREA,
            color_fill=0,
            pattern=pattern_values.HORIZONTAL,
            spacing=2.0,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0, 0.0, 20.0],
        )
        items = self._render_takeoff_items(condition, takeoff)
        pattern_items = self._line_path_items(items[1:])
        self.assertGreater(len(pattern_items), 0)

    def test_area_solid_fill_excludes_backout_hole(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_AREA,
            color_fill=0,
            pattern=pattern_values.SOLID,
        )
        parent = Takeoff(
            uid="parent",
            condition_uid="c1",
            position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0, 0.0, 20.0],
        )
        backout = Takeoff(
            uid="backout",
            condition_uid="c1",
            parent_uid="parent",
            position=[8.0, 8.0, 12.0, 8.0, 12.0, 12.0, 8.0, 12.0],
        )
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        rendered = renderer.create_all_path_items(
            [parent, backout],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
        )
        items = rendered[0][1]
        items = items if isinstance(items, list) else [items]
        area_item = items[0]
        self.assertIsInstance(area_item, QGraphicsPathItem)
        self.assertFalse(area_item.path().contains(QtCore.QPointF(10.0, 10.0)))
        self.assertNotEqual(area_item.brush().style(), Qt.BrushStyle.NoBrush)

    def test_area_display_name_uses_centroid_when_dimension_is_not_present(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1",
            name="Area Label",
            condition_type=Condition.TYPE_AREA,
            color_fill=0,
            pattern=0,
            spacing=0.0,
            display_name=True,
            display_dimension=False,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0],
        )
        rendered = renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
        )
        items = rendered[0][1]
        items = items if isinstance(items, list) else [items]
        name_label = next(
            item
            for item in items
            if isinstance(item, QGraphicsTextItem) and item.data(3) == "display_name"
        )
        name_center = name_label.mapToScene(name_label.boundingRect().center())
        self.assertAlmostEqual(name_center.x(), 6.0)
        self.assertAlmostEqual(name_center.y(), 6.0)

    def test_area_display_dimension_uses_negative_indicator_centroid_anchor(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1",
            name="Area Label",
            condition_type=Condition.TYPE_AREA,
            color_fill=0,
            pattern=0,
            spacing=0.0,
            display_dimension=True,
            calc_type1=11,
            uom1=4,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0],
            is_negative=True,
        )
        rendered = renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
        )
        items = rendered[0][1]
        items = items if isinstance(items, list) else [items]
        dimension_label = next(
            item
            for item in items
            if isinstance(item, QGraphicsTextItem)
            and item.data(3) == "display_dimension"
        )
        negative_box = next(
            item
            for item in items
            if isinstance(item, QGraphicsPathItem) and item.zValue() == 10
        )
        dimension_center = dimension_label.mapToScene(
            dimension_label.boundingRect().center()
        )
        self.assertEqual(dimension_center, negative_box.pos())

    def test_condition_label_style_fields_render_after_overlay_rebuild(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1",
            name="Area Label",
            condition_type=Condition.TYPE_AREA,
            display_name=True,
            display_dimension=True,
            calc_type1=11,
            uom1=4,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0],
            dimension_font_name="Segoe UI",
            dimension_font_color=0x332211,
            dimension_font_size=24,
            dimension_font_bold=True,
            dimension_font_italic=True,
            dimension_font_underline=True,
            name_font_name="Calibri",
            name_font_color=0x665544,
            name_font_size=18,
            name_font_bold=True,
            name_font_italic=False,
            name_font_underline=True,
        )
        rendered = renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
        )
        items = rendered[0][1]
        items = items if isinstance(items, list) else [items]
        dimension_label = next(
            item
            for item in items
            if isinstance(item, QGraphicsTextItem)
            and item.data(3) == "display_dimension"
        )
        name_label = next(
            item
            for item in items
            if isinstance(item, QGraphicsTextItem) and item.data(3) == "display_name"
        )
        self.assertEqual(dimension_label.defaultTextColor().name(), "#112233")
        self.assertEqual(dimension_label.font().family(), "Segoe UI")
        self.assertEqual(dimension_label.font().pointSize(), 24)
        self.assertTrue(dimension_label.font().bold())
        self.assertTrue(dimension_label.font().italic())
        self.assertTrue(dimension_label.font().underline())
        self.assertEqual(name_label.defaultTextColor().name(), "#445566")
        self.assertEqual(name_label.font().family(), "Calibri")
        self.assertEqual(name_label.font().pointSize(), 18)
        self.assertTrue(name_label.font().bold())
        self.assertFalse(name_label.font().italic())
        self.assertTrue(name_label.font().underline())


if __name__ == "__main__":
    unittest.main()
