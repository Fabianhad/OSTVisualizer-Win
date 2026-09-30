from shiboken6 import delete
from PySide6 import QtWidgets
from ost_visualizer.presentation.components.condition_summary import ConditionSummaryTab
from ost_visualizer.application.dtos.condition_summary_dtos import (
    SUMMARY_NODE_CONDITION,
    SUMMARY_NODE_FOLDER,
    SUMMARY_NODE_ROOT,
    ConditionSummaryGrouping,
    ConditionSummaryNode,
    ConditionSummaryValues,
)
from unittest.mock import patch
import unittest
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.condition_summary_dtos import (
    SUMMARY_GROUP_AREA,
    SUMMARY_GROUP_PAGE,
    SUMMARY_GROUP_TYPE,
    SUMMARY_MULTI_AREA_TOTAL_LABEL,
    SUMMARY_NO_PAGE_LABEL,
    SUMMARY_NODE_AREA_DETAIL,
    SUMMARY_NODE_CONDITION,
    SUMMARY_NODE_FOLDER,
    SUMMARY_NODE_GROUP,
    SUMMARY_NODE_MULTI_AREA_TOTAL,
    SUMMARY_NODE_ROOT,
    ConditionSummaryGrouping,
)
from ost_visualizer.application.use_cases.project.condition_summary_service import (
    ConditionSummaryService,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.uom_service import CALC_COUNT, UOM_EACH
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.managers.icon_manager import IconId, IconManager
from ost_visualizer.presentation.utils.condition_tree_style import (
    CONDITION_TREE_INDENTATION,
    CONDITION_TREE_ROW_HEIGHT,
)
from ost_visualizer.presentation.utils.persistent_header import (
    PersistentHeaderController,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.workspace_state import make_workspace_state_model


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _tree_items(item):
    result = [item]
    for index in range(item.childCount()):
        result.extend(_tree_items(item.child(index)))
    return result


def _top_level_items(tree):
    return [tree.topLevelItem(index) for index in range(tree.topLevelItemCount())]


def _has_alignment(alignment, flag):
    return bool(alignment & flag)


def _attach_summary_header(tab):
    controller = PersistentHeaderController(
        tab.tree,
        "condition_summary_test",
        tab.column_keys,
        make_workspace_state_model(),
        sorting=True,
        movable=True,
        default_sort_column="name",
    )
    tab.columns_about_to_change.connect(controller.begin_columns_update)
    tab.columns_changed.connect(controller.end_columns_update)
    return controller


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class SummaryReactivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_inactive_summary_projects_folder_rename_delete_and_first_content(self):
        for change in ("rename", "delete", "first_content"):
            with self.subTest(change=change):
                tabs = QtWidgets.QTabWidget()
                summary = ConditionSummaryTab(
                    copy_allowed_fn=lambda: True, delete_allowed_fn=lambda: True
                )
                tabs.addTab(summary, "Summary")
                tabs.addTab(QtWidgets.QWidget(), "Other")

                def root(name, populated=True):
                    condition = ConditionSummaryNode(
                        kind=SUMMARY_NODE_CONDITION,
                        condition_uid="c1",
                        copyable=True,
                        deletable=True,
                        values=ConditionSummaryValues(
                            name="Current Condition", quantity1=3
                        ),
                    )
                    return ConditionSummaryNode(
                        kind=SUMMARY_NODE_ROOT,
                        children=(
                            [
                                ConditionSummaryNode(
                                    kind=SUMMARY_NODE_FOLDER,
                                    folder_uid="f1",
                                    label=name,
                                    children=[condition],
                                )
                            ]
                            if populated
                            else []
                        ),
                    )

                try:
                    summary.load_summary(
                        root("Old", change != "first_content"),
                        ConditionSummaryGrouping(),
                    )
                    tabs.resize(600, 350)
                    tabs.show()
                    self.app.processEvents()
                    if change != "first_content":
                        summary.tree.setCurrentItem(summary._condition_items["c1"][0])
                        self.assertTrue(summary.can_delete_current_row())
                    tabs.setCurrentIndex(1)
                    self.assertFalse(summary.isVisible())
                    with patch.object(
                        summary, "_rebuild_tree", wraps=summary._rebuild_tree
                    ) as rebuild:
                        summary.load_summary(
                            root("Renamed", change != "delete"),
                            ConditionSummaryGrouping(),
                        )
                        tabs.setCurrentIndex(0)
                        self.app.processEvents()
                        self.assertEqual(rebuild.call_count, 1)
                    if change == "rename":
                        self.assertIs(
                            summary.tree.currentItem(),
                            summary._condition_items["c1"][0],
                        )
                        self.assertTrue(summary.can_delete_current_row())
                        self.assertTrue(summary.tree.topLevelItem(0).isExpanded())
                        self.assertEqual(
                            summary.tree.topLevelItem(0).text(0), "Renamed"
                        )
                    elif change == "delete":
                        self.assertIsNone(summary.tree.currentItem())
                        self.assertFalse(summary.can_delete_current_row())
                        self.assertFalse(summary.can_copy_current_row())
                    else:
                        self.assertTrue(summary.tree.topLevelItem(0).isExpanded())
                        summary.tree.setCurrentItem(summary._condition_items["c1"][0])
                        self.assertTrue(summary.can_delete_current_row())
                        self.assertTrue(summary.can_copy_current_row())
                finally:
                    tabs.close()
                    delete(tabs)


class ConditionSummaryTabTests(unittest.TestCase):
    def setUp(self):
        _app()
        self.service = ConditionSummaryService()
        self.condition = Condition(
            uid="c1",
            name="Fdn1",
            condition_type=Condition.TYPE_COUNT,
            height=24.0,
            color_fill=0x336699,
            cdn_type_uid="t1",
            cdn_type_name="AB - Spread Interior FTG",
            uom1=UOM_EACH,
            calc_type1=CALC_COUNT,
            ref_no=1,
        )
        self.conditions = {"c1": self.condition}
        self.pages = [Page(uid="p1", name="S-100.pdf", sequence=1)]
        self.areas = [
            BidArea(uid="a1", bid_uid="b1", parent_uid="", name="L-0 FDN", sequence=1),
            BidArea(uid="a2", bid_uid="b1", parent_uid="", name="L-2 FDN", sequence=2),
        ]
        self.takeoffs = [
            Takeoff(uid="tk1", condition_uid="c1", page_uid="p1", area_uid="a1"),
            Takeoff(uid="tk2", condition_uid="c1", page_uid="p1", area_uid="a2"),
        ]
        self.tab = ConditionSummaryTab(
            None,
            uom_label_fn=lambda code: "EA" if code == UOM_EACH else "",
            copy_allowed_fn=lambda: True,
            delete_allowed_fn=lambda: True,
        )
        self.header_controller = _attach_summary_header(self.tab)

    def tearDown(self):
        self.tab.deleteLater()

    def test_default_grouping_is_type_area(self):
        self.assertEqual(
            self.tab.grouping,
            ConditionSummaryGrouping(by_type=True, by_area=True),
        )

    def _load(self, grouping=None):
        grouping = grouping or ConditionSummaryGrouping()
        root = self.service.build_summary(
            conditions=self.conditions,
            folders={},
            takeoffs=self.takeoffs,
            pages=self.pages,
            areas=self.areas,
            grouping=grouping,
        )
        self.tab.load_summary(root, grouping)

    def _item_for_kind(self, kind):
        for root_item in _top_level_items(self.tab.tree):
            for item in _tree_items(root_item):
                node = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
                if node and node.kind == kind:
                    return item
        return None

    def _item_for_condition_uid(self, condition_uid):
        for root_item in _top_level_items(self.tab.tree):
            for item in _tree_items(root_item):
                node = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
                if node and node.condition_uid == condition_uid:
                    return item
        return None

    def _action_by_text(self, menu, text):
        for action in menu.actions():
            if action.text() == text:
                return action
        return None

    def _column_index(self, header_text):
        for index in range(self.tab.tree.columnCount()):
            if self.tab.tree.headerItem().text(index) == header_text:
                return index
        self.fail(f"Missing Summary column {header_text!r}")

    def _show_and_process(self):
        self.tab.resize(900, 400)
        self.tab.show()
        _app().processEvents()

    def _visible_row_heights(self):
        heights = []
        for root_item in _top_level_items(self.tab.tree):
            for item in _tree_items(root_item):
                height = self.tab.tree.visualItemRect(item).height()
                if height > 0:
                    heights.append(height)
        return heights

    def test_area_column_is_present_unless_area_grouped(self):
        self._load()
        headers = [
            self.tab.tree.headerItem().text(index)
            for index in range(self.tab.tree.columnCount())
        ]
        self.assertIn("Area", headers)
        self._load(ConditionSummaryGrouping(by_area=True))
        headers = [
            self.tab.tree.headerItem().text(index)
            for index in range(self.tab.tree.columnCount())
        ]
        self.assertNotIn("Area", headers)

    def test_headers_are_center_aligned(self):
        self._load()
        for index in range(self.tab.tree.columnCount()):
            alignment = self.tab.tree.headerItem().textAlignment(index)
            self.assertTrue(
                _has_alignment(alignment, QtCore.Qt.AlignmentFlag.AlignHCenter)
            )
        self._load(ConditionSummaryGrouping(by_area=True))
        for index in range(self.tab.tree.columnCount()):
            alignment = self.tab.tree.headerItem().textAlignment(index)
            self.assertTrue(
                _has_alignment(alignment, QtCore.Qt.AlignmentFlag.AlignHCenter)
            )

    def test_value_columns_use_requested_alignment(self):
        self._load()
        total_item = self._item_for_kind(SUMMARY_NODE_MULTI_AREA_TOTAL)
        left_headers = ["No.", "Name", "Notes"]
        right_headers = [
            "Height",
            "Area",
            "Quantity 1",
            "UOM1",
            "Quantity 2",
            "UOM2",
            "Quantity 3",
            "UOM3",
        ]
        for header in left_headers:
            alignment = total_item.textAlignment(self._column_index(header))
            self.assertTrue(
                _has_alignment(alignment, QtCore.Qt.AlignmentFlag.AlignLeft)
            )
        for header in right_headers:
            alignment = total_item.textAlignment(self._column_index(header))
            self.assertTrue(
                _has_alignment(alignment, QtCore.Qt.AlignmentFlag.AlignRight)
            )

    def test_area_grouping_keeps_right_alignment_after_area_column_is_hidden(self):
        self._load(ConditionSummaryGrouping(by_area=True))
        condition_item = self._item_for_kind(SUMMARY_NODE_CONDITION)
        self.assertNotIn(
            "Area",
            [
                self.tab.tree.headerItem().text(index)
                for index in range(self.tab.tree.columnCount())
            ],
        )
        alignment = condition_item.textAlignment(self._column_index("Height"))
        self.assertTrue(_has_alignment(alignment, QtCore.Qt.AlignmentFlag.AlignRight))

    def test_summary_tree_uses_condition_sidebar_tree_style(self):
        sidebar = ConditionsSidebar(None, uom_label_fn=lambda _code: "")
        try:
            self.assertEqual(self.tab.tree.iconSize(), sidebar.tree.iconSize())
            self.assertEqual(self.tab.tree.indentation(), CONDITION_TREE_INDENTATION)
            self.assertEqual(self.tab.tree.indentation(), sidebar.tree.indentation())
            self.assertEqual(
                self.tab.tree.uniformRowHeights(), sidebar.tree.uniformRowHeights()
            )
        finally:
            sidebar.deleteLater()

    def test_summary_items_use_condition_sidebar_row_size_hints(self):
        self._load(ConditionSummaryGrouping(by_area=True))
        sidebar = ConditionsSidebar(None, uom_label_fn=lambda _code: "")
        try:
            sidebar.load_conditions(
                {
                    "c1": Condition(
                        uid="c1",
                        name="Fdn1",
                        ref_no=1,
                        color_fill=0x336699,
                    )
                },
                {},
                "Project",
            )
            summary_item = self._item_for_kind(SUMMARY_NODE_CONDITION)
            sidebar_item = sidebar._condition_items["c1"]
            self.assertEqual(summary_item.sizeHint(0), sidebar_item.sizeHint(0))
            self.assertEqual(
                summary_item.sizeHint(0).height(), CONDITION_TREE_ROW_HEIGHT
            )
        finally:
            sidebar.deleteLater()

    def test_summary_condition_row_height_matches_condition_sidebar(self):
        self._load(ConditionSummaryGrouping(by_area=True))
        sidebar = ConditionsSidebar(None, uom_label_fn=lambda _code: "")
        try:
            sidebar.load_conditions(
                {
                    "c1": Condition(
                        uid="c1",
                        name="Fdn1",
                        ref_no=1,
                        color_fill=0x336699,
                    )
                },
                {},
                "Project",
            )
            self.tab.resize(900, 400)
            sidebar.resize(420, 300)
            self.tab.show()
            sidebar.show()
            _app().processEvents()
            summary_item = self._item_for_kind(SUMMARY_NODE_CONDITION)
            sidebar_item = sidebar._condition_items["c1"]
            self.assertEqual(
                self.tab.tree.visualItemRect(summary_item).height(),
                sidebar.tree.visualItemRect(sidebar_item).height(),
            )
        finally:
            sidebar.deleteLater()

    def test_group_total_and_detail_rows_have_uniform_body_height(self):
        self._load(ConditionSummaryGrouping(by_page=True))
        self._show_and_process()
        heights = self._visible_row_heights()
        self.assertGreater(len(heights), 2)
        self.assertEqual(len(set(heights)), 1)

    def test_group_and_condition_rows_have_uniform_body_height(self):
        self._load(ConditionSummaryGrouping(by_area=True))
        self._show_and_process()
        heights = self._visible_row_heights()
        self.assertGreater(len(heights), 2)
        self.assertEqual(len(set(heights)), 1)

    def test_condition_folders_are_visible_top_level_items(self):
        self.condition.folder_uid = "f1"
        root = self.service.build_summary(
            conditions=self.conditions,
            folders={"f1": BidConditionFolder(uid="f1", name="CONDITION FOLDER")},
            takeoffs=self.takeoffs,
            pages=self.pages,
            areas=self.areas,
            grouping=ConditionSummaryGrouping(),
        )
        self.tab.load_summary(root, ConditionSummaryGrouping())
        top_items = _top_level_items(self.tab.tree)
        self.assertEqual(len(top_items), 1)
        top_node = top_items[0].data(0, QtCore.Qt.ItemDataRole.UserRole)
        self.assertEqual(top_node.kind, SUMMARY_NODE_FOLDER)
        self.assertEqual(top_node.label, "CONDITION FOLDER")

    def test_summary_folder_rows_use_sidebar_folder_icon_source(self):
        self.condition.folder_uid = "f1"
        root = self.service.build_summary(
            conditions=self.conditions,
            folders={"f1": BidConditionFolder(uid="f1", name="CONDITION FOLDER")},
            takeoffs=self.takeoffs,
            pages=self.pages,
            areas=self.areas,
            grouping=ConditionSummaryGrouping(),
        )
        self.tab.load_summary(root, ConditionSummaryGrouping())
        folder_item = self.tab.tree.topLevelItem(0)
        sidebar = ConditionsSidebar(None)
        try:
            self.assertEqual(self.tab.tree.iconSize(), sidebar.tree.iconSize())
            self.assertEqual(
                folder_item.icon(0).cacheKey(),
                IconManager.icon(IconId.FOLDER).cacheKey(),
            )
        finally:
            sidebar.deleteLater()

    def test_logical_root_node_is_not_visible(self):
        self._load()
        top_node = self.tab.tree.topLevelItem(0).data(
            0, QtCore.Qt.ItemDataRole.UserRole
        )
        self.assertNotEqual(top_node.kind, SUMMARY_NODE_ROOT)

    def test_refresh_while_hidden_renders_rows_when_shown(self):
        self._load()
        self.tab.hide()
        self._load(ConditionSummaryGrouping(by_page=True))
        self.assertGreater(self.tab.tree.topLevelItemCount(), 0)
        self.tab.show()
        _app().processEvents()
        self.assertGreater(self.tab.tree.topLevelItemCount(), 0)
        top_node = self.tab.tree.topLevelItem(0).data(
            0, QtCore.Qt.ItemDataRole.UserRole
        )
        self.assertNotEqual(top_node.kind, SUMMARY_NODE_ROOT)

    def test_grouping_state_survives_refresh(self):
        self.conditions["unused"] = Condition(uid="unused", name="Unused", ref_no=2)
        grouping = ConditionSummaryGrouping(by_page=True, by_type=True)
        self._load(grouping)
        self._load(self.tab.grouping)
        self.assertEqual(self.tab.grouping, grouping)

    def test_authoritative_refresh_preserves_current_row_and_expansion(self):
        grouping = ConditionSummaryGrouping(by_area=True)
        self._load(grouping)
        current = self._item_for_condition_uid("c1")
        parent = current.parent()
        self.assertIsNotNone(parent)
        self.tab.tree.setCurrentItem(current)
        parent.setExpanded(False)
        self.takeoffs[0].x = 12.0
        self._load(grouping)
        rebuilt_current = self.tab.tree.currentItem()
        self.assertIsNotNone(rebuilt_current)
        rebuilt_node = rebuilt_current.data(0, QtCore.Qt.ItemDataRole.UserRole)
        self.assertEqual(rebuilt_node.condition_uid, "c1")
        self.assertFalse(rebuilt_current.parent().isExpanded())
        self.assertTrue(self.tab.can_copy_current_row())
        self.assertTrue(self.tab.can_delete_current_row())

    def test_condition_layer_visibility_updates_only_matching_summary_rows(self):
        self.condition.layer_uid = "layer-a"
        self.condition.color_fill = 0x336699
        self.conditions["c2"] = Condition(
            uid="c2",
            name="Fdn2",
            condition_type=Condition.TYPE_COUNT,
            height=12.0,
            color_fill=0x993366,
            layer_uid="layer-b",
            cdn_type_uid="t2",
            cdn_type_name="ZZ - Other",
            uom1=UOM_EACH,
            calc_type1=CALC_COUNT,
            ref_no=2,
        )
        self.takeoffs = [
            Takeoff(uid="tk1", condition_uid="c1", page_uid="p1", area_uid="a1"),
            Takeoff(uid="tk2", condition_uid="c2", page_uid="p1", area_uid="a1"),
        ]
        grouping = ConditionSummaryGrouping(by_type=True)
        self._load(grouping)
        self.tab.tree.header().resizeSection(self._column_index("Name"), 222)
        self.tab.tree.header().resizeSection(self._column_index("Quantity 1"), 91)
        self._show_and_process()
        item_a = self._item_for_condition_uid("c1")
        item_b = self._item_for_condition_uid("c2")
        self.assertIsNotNone(item_a)
        self.assertIsNotNone(item_b)
        parent_a = item_a.parent()
        parent_a.setExpanded(False)
        self.tab.tree.setCurrentItem(item_b)
        item_b.setSelected(True)
        name_col = self._column_index("Name")
        quantity_col = self._column_index("Quantity 1")
        scroll_bar = self.tab.tree.verticalScrollBar()
        scroll_pos = scroll_bar.value()
        icon_a_before = item_a.icon(0).cacheKey()
        icon_b_before = item_b.icon(0).cacheKey()
        self.conditions["c1"].layer_visible = False
        self.tab.apply_layer_visibility_state(
            self.conditions,
            grayscale=False,
            layer_uid="layer-a",
        )
        same_item_a = self._item_for_condition_uid("c1")
        same_item_b = self._item_for_condition_uid("c2")
        node_a = same_item_a.data(0, QtCore.Qt.ItemDataRole.UserRole)
        node_b = same_item_b.data(0, QtCore.Qt.ItemDataRole.UserRole)
        self.assertIs(same_item_a, item_a)
        self.assertIs(same_item_b, item_b)
        self.assertFalse(node_a.layer_visible)
        self.assertTrue(node_b.layer_visible)
        self.assertNotEqual(same_item_a.icon(0).cacheKey(), icon_a_before)
        self.assertEqual(same_item_b.icon(0).cacheKey(), icon_b_before)
        self.assertFalse(parent_a.isExpanded())
        self.assertIs(self.tab.tree.currentItem(), item_b)
        self.assertTrue(item_b.isSelected())
        self.assertEqual(scroll_bar.value(), scroll_pos)
        self.assertEqual(self.tab.tree.header().sectionSize(name_col), 222)
        self.assertEqual(self.tab.tree.header().sectionSize(quantity_col), 91)
        self.assertEqual(self.tab.grouping, grouping)

    def test_column_widths_survive_refresh_and_grouping_changes(self):
        self.conditions["unused"] = Condition(uid="unused", name="Unused", ref_no=2)
        self._load()
        name_col = self._column_index("Name")
        quantity_col = self._column_index("Quantity 1")
        self.tab.tree.header().resizeSection(name_col, 222)
        self.tab.tree.header().resizeSection(quantity_col, 97)
        self._load()
        self.assertEqual(self.tab.tree.header().sectionSize(name_col), 222)
        self.assertEqual(self.tab.tree.header().sectionSize(quantity_col), 97)
        self._load(ConditionSummaryGrouping(by_area=True))
        name_col = self._column_index("Name")
        quantity_col = self._column_index("Quantity 1")
        self.assertEqual(self.tab.tree.header().sectionSize(name_col), 222)
        self.assertEqual(self.tab.tree.header().sectionSize(quantity_col), 97)

    def test_column_widths_survive_tab_hide_show(self):
        self._load()
        name_col = self._column_index("Name")
        self.tab.tree.header().resizeSection(name_col, 211)
        self.tab.hide()
        self.tab.show()
        _app().processEvents()
        self.assertEqual(self.tab.tree.header().sectionSize(name_col), 211)

    def test_hidden_area_column_width_is_preserved_and_restored(self):
        self._load()
        self.tab.tree.header().resizeSection(self._column_index("Area"), 233)
        self.tab.tree.header().resizeSection(self._column_index("Name"), 211)
        self._load(ConditionSummaryGrouping(by_area=True))
        self.assertNotIn(
            "Area",
            [
                self.tab.tree.headerItem().text(index)
                for index in range(self.tab.tree.columnCount())
            ],
        )
        self.assertEqual(
            self.tab.tree.header().sectionSize(self._column_index("Name")), 211
        )
        self._load(ConditionSummaryGrouping())
        self.assertEqual(
            self.tab.tree.header().sectionSize(self._column_index("Area")), 233
        )

    def test_restored_grouping_drives_context_menu_checked_state(self):
        grouping = ConditionSummaryGrouping(by_page=True, by_type=False, by_area=False)
        self.tab.set_grouping(grouping)
        self._load(self.tab.grouping)
        menu = self.tab.build_context_menu(self.tab.tree.topLevelItem(0))
        self.assertFalse(self._action_by_text(menu, "Group By Area").isChecked())
        self.assertFalse(self._action_by_text(menu, "Group By Type").isChecked())
        self.assertTrue(self._action_by_text(menu, "Group By Page").isChecked())

    def test_context_menu_delete_rules(self):
        self._load()
        total_item = self._item_for_kind(SUMMARY_NODE_MULTI_AREA_TOTAL)
        detail_item = self._item_for_kind(SUMMARY_NODE_AREA_DETAIL)
        self.assertTrue(
            self._action_by_text(
                self.tab.build_context_menu(total_item), "Delete"
            ).isEnabled()
        )
        self.assertFalse(
            self._action_by_text(
                self.tab.build_context_menu(detail_item), "Delete"
            ).isEnabled()
        )
        self._load(ConditionSummaryGrouping(by_page=True))
        group_item = self._item_for_kind(SUMMARY_NODE_GROUP)
        self.assertFalse(
            self._action_by_text(
                self.tab.build_context_menu(group_item), "Delete"
            ).isEnabled()
        )

    def test_context_menu_and_main_state_agree_for_summary_copy_delete(self):
        self._load()
        total_item = self._item_for_kind(SUMMARY_NODE_MULTI_AREA_TOTAL)
        self.tab.tree.setCurrentItem(total_item)
        total_menu = self.tab.build_context_menu(total_item)
        self.assertEqual(
            self._action_by_text(total_menu, "Copy").isEnabled(),
            self.tab.can_copy_current_row(),
        )
        self.assertEqual(
            self._action_by_text(total_menu, "Delete").isEnabled(),
            self.tab.can_delete_current_row(),
        )
        detail_item = self._item_for_kind(SUMMARY_NODE_AREA_DETAIL)
        self.tab.tree.setCurrentItem(detail_item)
        detail_menu = self.tab.build_context_menu(detail_item)
        self.assertEqual(
            self._action_by_text(detail_menu, "Copy").isEnabled(),
            self.tab.can_copy_current_row(),
        )
        self.assertEqual(
            self._action_by_text(detail_menu, "Delete").isEnabled(),
            self.tab.can_delete_current_row(),
        )

    def test_summary_copy_respects_shared_copy_condition_permission(self):
        tab = ConditionSummaryTab(
            None,
            uom_label_fn=lambda code: "EA" if code == UOM_EACH else "",
            copy_allowed_fn=lambda: False,
            delete_allowed_fn=lambda: True,
        )
        self.addCleanup(tab.deleteLater)
        root = self.service.build_summary(
            conditions=self.conditions,
            folders={},
            takeoffs=self.takeoffs,
            pages=self.pages,
            areas=self.areas,
            grouping=ConditionSummaryGrouping(),
        )
        tab.load_summary(root, ConditionSummaryGrouping())
        detail_item = next(
            item
            for root_item in _top_level_items(tab.tree)
            for item in _tree_items(root_item)
            if (
                item.data(0, QtCore.Qt.ItemDataRole.UserRole)
                and item.data(0, QtCore.Qt.ItemDataRole.UserRole).kind
                == SUMMARY_NODE_AREA_DETAIL
            )
        )
        tab.tree.setCurrentItem(detail_item)
        self.assertFalse(tab.can_copy_current_row())
        self.assertFalse(
            self._action_by_text(
                tab.build_context_menu(detail_item), "Copy"
            ).isEnabled()
        )

    def test_copy_uses_only_visible_non_empty_cells(self):
        self._load()
        detail_item = self._item_for_kind(SUMMARY_NODE_AREA_DETAIL)
        self.tab.tree.setCurrentItem(detail_item)
        self.tab.copy_current_row()
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "L-0 FDN\t1\tEA")

    def test_context_copy_uses_clicked_row_after_current_row_changes(self):
        self._load()
        detail_items = [
            item
            for root_item in _top_level_items(self.tab.tree)
            for item in _tree_items(root_item)
            if (
                item.data(0, QtCore.Qt.ItemDataRole.UserRole)
                and item.data(0, QtCore.Qt.ItemDataRole.UserRole).kind
                == SUMMARY_NODE_AREA_DETAIL
            )
        ]
        self.tab.tree.setCurrentItem(detail_items[0])
        menu = self.tab.build_context_menu(detail_items[0])
        self.tab.tree.setCurrentItem(detail_items[1])
        self._action_by_text(menu, "Copy").trigger()
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "L-0 FDN\t1\tEA")

    def test_context_delete_rejects_replaced_summary_owner(self):
        self._load()
        deleted = []
        self.tab.delete_requested.connect(lambda uids: deleted.append(list(uids)))
        total_item = self._item_for_kind(SUMMARY_NODE_MULTI_AREA_TOTAL)
        menu = self.tab.build_context_menu(total_item)
        self._load()
        self._action_by_text(menu, "Delete").trigger()
        self.assertEqual(deleted, [])

    def test_delete_current_row_emits_condition_delete_request(self):
        self._load()
        deleted = []
        self.tab.delete_requested.connect(lambda uids: deleted.append(list(uids)))
        self.tab.tree.setCurrentItem(self._item_for_kind(SUMMARY_NODE_MULTI_AREA_TOTAL))
        self.tab.delete_current_row()
        self.assertEqual(deleted, [["c1"]])

    def test_group_actions_are_checkable_and_request_rebuild(self):
        self._load()
        calls = []
        self.tab.set_grouping_rebuild_callback(calls.append)
        menu = self.tab.build_context_menu(self.tab.tree.topLevelItem(0))
        area_action = self._action_by_text(menu, "Group By Area")
        self.assertTrue(area_action.isCheckable())
        self.assertFalse(area_action.isChecked())
        area_action.trigger()
        self.assertEqual(calls, [ConditionSummaryGrouping(by_area=True)])

    def test_expand_and_collapse_actions_affect_tree(self):
        self._load()
        root_item = self.tab.tree.topLevelItem(0)
        menu = self.tab.build_context_menu(root_item)
        self._action_by_text(menu, "Collapse All").trigger()
        self.assertFalse(root_item.isExpanded())
        self._action_by_text(menu, "Expand All").trigger()
        self.assertTrue(root_item.isExpanded())
