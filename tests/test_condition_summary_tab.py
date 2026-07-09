import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
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
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.condition_quantity_service import (
    compute_page_quantities,
)
from ost_visualizer.domain.services.uom_service import CALC_COUNT, UOM_EACH
from ost_visualizer.presentation.components.condition_summary import ConditionSummaryTab
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.config import (
    TAB_INDEX_PROJECTS,
    TAB_INDEX_SUMMARY,
    TAB_INDEX_TAKEOFF,
)
from ost_visualizer.presentation.coordinators.navigation_state_machine import NavState
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.handlers.condition_action_handler import (
    ConditionActionHandler,
)
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.icon_manager import IconId, IconManager
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.utils.condition_tree_style import (
    CONDITION_TREE_INDENTATION,
    CONDITION_TREE_ROW_HEIGHT,
)


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _children(node):
    return list(node.children)


def _first_descendant(node, kind):
    if node.kind == kind:
        return node
    for child in node.children:
        found = _first_descendant(child, kind)
        if found is not None:
            return found
    return None


def _tree_items(item):
    result = [item]
    for index in range(item.childCount()):
        result.extend(_tree_items(item.child(index)))
    return result


def _top_level_items(tree):
    return [tree.topLevelItem(index) for index in range(tree.topLevelItemCount())]


def _has_alignment(alignment, flag):
    return bool(alignment & flag)


def _summary_nodes(node):
    result = [node]
    for child in node.children:
        result.extend(_summary_nodes(child))
    return result


def _condition_row_uids(node):
    return [
        child.condition_uid
        for child in _summary_nodes(node)
        if child.kind in (SUMMARY_NODE_CONDITION, SUMMARY_NODE_MULTI_AREA_TOTAL)
    ]


def _group_labels(node, level=None):
    return [
        child.label
        for child in _summary_nodes(node)
        if child.kind == SUMMARY_NODE_GROUP
        and (level is None or child.group_level == level)
    ]


class _FakeSummaryAccess:
    def __init__(self, allowed):
        self._allowed = set(allowed)

    def is_allowed(self, feature):
        return feature in self._allowed


class ConditionSummaryServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = ConditionSummaryService()
        self.folder = BidConditionFolder(uid="f1", name="CONDITION FOLDER")
        self.condition = Condition(
            uid="c1",
            name="Fdn1",
            condition_type=Condition.TYPE_COUNT,
            height=24.0,
            color_fill=0x336699,
            cdn_type_uid="t1",
            cdn_type_name="AB - Spread Interior FTG",
            folder_uid="f1",
            uom1=UOM_EACH,
            calc_type1=CALC_COUNT,
            ref_no=1,
            notes="noteshere",
        )
        self.conditions = {"c1": self.condition}
        self.folders = {"f1": self.folder}
        self.pages = [
            Page(uid="p1", name="S-100.pdf", sequence=1),
            Page(uid="p2", name="S-200.pdf", sequence=2),
        ]
        self.areas = [
            BidArea(uid="a1", bid_uid="b1", parent_uid="", name="L-0 FDN", sequence=1),
            BidArea(uid="a2", bid_uid="b1", parent_uid="", name="L-2 FDN", sequence=2),
        ]
        self.takeoffs = [
            Takeoff(uid="tk1", condition_uid="c1", page_uid="p1", area_uid="a1"),
            Takeoff(uid="tk2", condition_uid="c1", page_uid="p1", area_uid="a2"),
        ]

    def _build(self, grouping=None, takeoffs=None):
        return self.service.build_summary(
            conditions=self.conditions,
            folders=self.folders,
            takeoffs=self.takeoffs if takeoffs is None else takeoffs,
            pages=self.pages,
            areas=self.areas,
            project_name="Project",
            grouping=grouping or ConditionSummaryGrouping(),
        )

    def test_no_grouping_uses_multi_area_total_inside_folder(self):
        root = self._build()
        folder = _first_descendant(root, SUMMARY_NODE_FOLDER)
        self.assertEqual(folder.label, "CONDITION FOLDER")
        condition = _first_descendant(root, SUMMARY_NODE_MULTI_AREA_TOTAL)
        self.assertEqual(condition.values.area, SUMMARY_MULTI_AREA_TOTAL_LABEL)
        self.assertEqual(condition.values.number, "1")
        self.assertEqual(condition.values.name, "Fdn1")
        self.assertEqual(condition.values.height, "2' 0\"")
        self.assertEqual(condition.values.quantity1, 2.0)
        self.assertEqual(
            [child.kind for child in condition.children], [SUMMARY_NODE_AREA_DETAIL] * 2
        )
        self.assertEqual(
            [child.values.area for child in condition.children], ["L-0 FDN", "L-2 FDN"]
        )
        self.assertEqual(condition.children[0].values.name, "")

    def test_area_grouping_hides_multi_area_total(self):
        root = self._build(ConditionSummaryGrouping(by_area=True))
        groups = [
            node
            for node in _children(_first_descendant(root, SUMMARY_NODE_FOLDER))
            if node.kind == SUMMARY_NODE_GROUP
        ]
        self.assertEqual(
            [group.group_level for group in groups],
            [SUMMARY_GROUP_AREA, SUMMARY_GROUP_AREA],
        )
        self.assertEqual([group.label for group in groups], ["L-0 FDN", "L-2 FDN"])
        self.assertIsNone(_first_descendant(root, SUMMARY_NODE_MULTI_AREA_TOTAL))
        self.assertEqual(groups[0].children[0].kind, SUMMARY_NODE_CONDITION)

    def test_condition_without_placed_takeoffs_is_excluded(self):
        self.conditions["c2"] = Condition(
            uid="c2",
            name="Unused",
            condition_type=Condition.TYPE_COUNT,
            uom1=UOM_EACH,
            calc_type1=CALC_COUNT,
            ref_no=2,
        )
        root = self._build()
        self.assertEqual(_condition_row_uids(root), ["c1"])

    def test_condition_with_placed_takeoffs_is_included(self):
        root = self._build(takeoffs=[self.takeoffs[0]])
        self.assertEqual(_condition_row_uids(root), ["c1"])
        row = _first_descendant(root, SUMMARY_NODE_CONDITION)
        self.assertEqual(row.values.quantity1, 1.0)

    def test_folder_with_only_unused_conditions_is_hidden(self):
        self.conditions = {
            "c2": Condition(uid="c2", name="Unused", folder_uid="f2", ref_no=2)
        }
        self.folders = {"f2": BidConditionFolder(uid="f2", name="UNUSED FOLDER")}
        root = self._build(takeoffs=[])
        self.assertEqual(root.children, [])

    def test_folder_with_used_and_unused_conditions_shows_only_used_condition(self):
        self.conditions["c2"] = Condition(
            uid="c2",
            name="Unused",
            folder_uid="f1",
            ref_no=2,
        )
        root = self._build()
        folder = _first_descendant(root, SUMMARY_NODE_FOLDER)
        self.assertEqual(folder.label, "CONDITION FOLDER")
        self.assertEqual(_condition_row_uids(folder), ["c1"])

    def test_type_grouping_hides_type_groups_for_unused_conditions(self):
        self.conditions["c2"] = Condition(
            uid="c2",
            name="Unused",
            cdn_type_uid="t2",
            cdn_type_name="Unused Type",
            ref_no=2,
        )
        root = self._build(ConditionSummaryGrouping(by_type=True))
        self.assertEqual(
            _group_labels(root, SUMMARY_GROUP_TYPE),
            ["AB - Spread Interior FTG"],
        )

    def test_area_grouping_hides_area_groups_for_unused_conditions(self):
        self.conditions["c2"] = Condition(uid="c2", name="Unused", ref_no=2)
        self.areas.append(
            BidArea(
                uid="a3",
                bid_uid="b1",
                parent_uid="",
                name="Unused Area",
                sequence=3,
            )
        )
        root = self._build(ConditionSummaryGrouping(by_area=True))
        self.assertEqual(
            _group_labels(root, SUMMARY_GROUP_AREA), ["L-0 FDN", "L-2 FDN"]
        )

    def test_page_grouping_hides_no_page_group_for_unused_conditions(self):
        self.conditions["c2"] = Condition(uid="c2", name="Unused", ref_no=2)
        root = self._build(ConditionSummaryGrouping(by_page=True))
        self.assertEqual(_group_labels(root, SUMMARY_GROUP_PAGE), ["S-100.pdf"])
        self.assertNotIn(SUMMARY_NO_PAGE_LABEL, _group_labels(root, SUMMARY_GROUP_PAGE))

    def test_multi_area_total_ignores_unused_conditions(self):
        self.conditions["c2"] = Condition(uid="c2", name="Unused", ref_no=2)
        root = self._build()
        total = _first_descendant(root, SUMMARY_NODE_MULTI_AREA_TOTAL)
        self.assertEqual(total.condition_uid, "c1")
        self.assertEqual(total.values.quantity1, 2.0)
        self.assertEqual(_condition_row_uids(root), ["c1"])

    def test_rebuild_after_last_takeoff_delete_removes_condition_row(self):
        populated = self._build(takeoffs=[self.takeoffs[0]])
        self.assertEqual(_condition_row_uids(populated), ["c1"])
        empty = self._build(takeoffs=[])
        self.assertEqual(_condition_row_uids(empty), [])
        self.assertEqual(empty.children, [])

    def test_rebuild_after_first_takeoff_add_shows_condition_row(self):
        empty = self._build(takeoffs=[])
        self.assertEqual(_condition_row_uids(empty), [])
        populated = self._build(takeoffs=[self.takeoffs[0]])
        self.assertEqual(_condition_row_uids(populated), ["c1"])

    def test_grouping_order_is_page_then_type_then_area(self):
        root = self._build(
            ConditionSummaryGrouping(by_page=True, by_type=True, by_area=True)
        )
        folder = _first_descendant(root, SUMMARY_NODE_FOLDER)
        page = folder.children[0]
        type_group = page.children[0]
        area = type_group.children[0]
        self.assertEqual(page.group_level, SUMMARY_GROUP_PAGE)
        self.assertEqual(page.label, "S-100.pdf")
        self.assertEqual(type_group.group_level, SUMMARY_GROUP_TYPE)
        self.assertEqual(type_group.label, "AB - Spread Interior FTG")
        self.assertEqual(area.group_level, SUMMARY_GROUP_AREA)
        self.assertEqual(area.label, "L-0 FDN")

    def test_area_type_grouping_uses_type_then_area(self):
        root = self._build(ConditionSummaryGrouping(by_type=True, by_area=True))
        folder = _first_descendant(root, SUMMARY_NODE_FOLDER)
        type_group = folder.children[0]
        area_group = type_group.children[0]
        self.assertEqual(type_group.group_level, SUMMARY_GROUP_TYPE)
        self.assertEqual(area_group.group_level, SUMMARY_GROUP_AREA)

    def test_area_page_grouping_uses_page_then_area(self):
        root = self._build(ConditionSummaryGrouping(by_page=True, by_area=True))
        folder = _first_descendant(root, SUMMARY_NODE_FOLDER)
        page_group = folder.children[0]
        area_group = page_group.children[0]
        self.assertEqual(page_group.group_level, SUMMARY_GROUP_PAGE)
        self.assertEqual(area_group.group_level, SUMMARY_GROUP_AREA)

    def test_type_page_grouping_uses_page_then_type(self):
        root = self._build(ConditionSummaryGrouping(by_page=True, by_type=True))
        folder = _first_descendant(root, SUMMARY_NODE_FOLDER)
        page_group = folder.children[0]
        type_group = page_group.children[0]
        self.assertEqual(page_group.group_level, SUMMARY_GROUP_PAGE)
        self.assertEqual(type_group.group_level, SUMMARY_GROUP_TYPE)
        self.assertEqual(type_group.children[0].kind, SUMMARY_NODE_MULTI_AREA_TOTAL)

    def test_type_group_keeps_multi_area_total_when_area_not_grouped(self):
        root = self._build(ConditionSummaryGrouping(by_type=True))
        type_group = _first_descendant(root, SUMMARY_NODE_GROUP)
        self.assertEqual(type_group.group_level, SUMMARY_GROUP_TYPE)
        self.assertEqual(type_group.children[0].kind, SUMMARY_NODE_MULTI_AREA_TOTAL)

    def test_page_group_repeats_condition_per_page(self):
        takeoffs = [
            Takeoff(uid="tk1", condition_uid="c1", page_uid="p1", area_uid="a1"),
            Takeoff(uid="tk2", condition_uid="c1", page_uid="p2", area_uid="a1"),
        ]
        root = self._build(ConditionSummaryGrouping(by_page=True), takeoffs=takeoffs)
        folder = _first_descendant(root, SUMMARY_NODE_FOLDER)
        self.assertEqual(
            [child.label for child in folder.children], ["S-100.pdf", "S-200.pdf"]
        )
        self.assertEqual(
            [child.children[0].values.quantity1 for child in folder.children],
            [1.0, 1.0],
        )

    def test_service_totals_match_compute_page_quantities(self):
        takeoffs = [
            Takeoff(uid="tk1", condition_uid="c1", page_uid="p1", area_uid="a1"),
            Takeoff(
                uid="tk2",
                condition_uid="c1",
                page_uid="p1",
                area_uid="a1",
                is_negative=True,
            ),
        ]
        root = self._build(takeoffs=takeoffs)
        row = _first_descendant(root, SUMMARY_NODE_CONDITION)
        expected = compute_page_quantities(self.conditions, takeoffs, {"c1"})["c1"]
        self.assertEqual(row.values.quantity1, expected[0])

    def test_summary_tab_index_is_third_tab(self):
        self.assertEqual(TAB_INDEX_SUMMARY, 2)


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
            None, uom_label_fn=lambda code: "EA" if code == UOM_EACH else ""
        )

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
        self.tab.set_column_widths({"name": 222, "quantity1": 91})
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

    def test_column_widths_can_be_restored_from_workspace_state(self):
        self._load()
        self.tab.set_column_widths({"name": 211, "area": 233, "bad": 400})
        self.assertEqual(
            self.tab.tree.header().sectionSize(self._column_index("Name")), 211
        )
        self.assertEqual(
            self.tab.tree.header().sectionSize(self._column_index("Area")), 233
        )
        widths = self.tab.get_column_widths()
        self.assertEqual(widths["name"], 211)
        self.assertNotIn("bad", widths)

    def test_hidden_area_column_width_is_preserved_and_restored(self):
        self._load()
        self.tab.set_column_widths({"area": 233, "name": 211})
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

    def test_copy_uses_only_visible_non_empty_cells(self):
        self._load()
        detail_item = self._item_for_kind(SUMMARY_NODE_AREA_DETAIL)
        self.tab.tree.setCurrentItem(detail_item)
        self.tab.copy_current_row()
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "L-0 FDN\t1\tEA")

    def test_delete_current_row_emits_condition_delete_request(self):
        self._load()
        deleted = []
        self.tab.delete_requested.connect(lambda uids: deleted.append(list(uids)))
        self.tab.tree.setCurrentItem(self._item_for_kind(SUMMARY_NODE_MULTI_AREA_TOTAL))
        self.tab.delete_current_row()
        self.assertEqual(deleted, [["c1"]])

    def test_main_window_summary_delete_routes_to_summary_tab(self):
        calls = []
        window = MainWindow.__new__(MainWindow)
        window._handle_inline_text_shortcut = lambda _action: False
        window.tab_widget = SimpleNamespace(currentIndex=lambda: TAB_INDEX_SUMMARY)
        window._condition_summary_tab = SimpleNamespace(
            delete_current_row=lambda: calls.append("summary-delete")
        )
        window.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: (_ for _ in ()).throw(
                AssertionError("project delete should not be queried")
            )
        )
        window.project_view = SimpleNamespace(
            get_delete_replacement_selection_state=lambda: (_ for _ in ()).throw(
                AssertionError("project tree delete should not run")
            )
        )
        window.handlers = SimpleNamespace(
            delete=SimpleNamespace(
                delete_selected=lambda *_args: (_ for _ in ()).throw(
                    AssertionError("bid delete should not run")
                )
            )
        )
        MainWindow._delete_selected(window)
        self.assertEqual(calls, ["summary-delete"])

    def test_main_window_summary_copy_routes_to_summary_tab(self):
        calls = []
        window = MainWindow.__new__(MainWindow)
        window._handle_inline_text_shortcut = lambda _action: False
        window.tab_widget = SimpleNamespace(currentIndex=lambda: TAB_INDEX_SUMMARY)
        window._condition_summary_tab = SimpleNamespace(
            copy_current_row=lambda: calls.append("summary-copy")
        )
        window.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: (_ for _ in ()).throw(
                AssertionError("bid copy should not be queried")
            )
        )
        window.ui_state_manager = SimpleNamespace(
            get_selected_bid_refs=lambda: (_ for _ in ()).throw(
                AssertionError("project selection should not be read")
            )
        )
        window._bid_clipboard = SimpleNamespace(
            copy=lambda *_args: (_ for _ in ()).throw(
                AssertionError("bid clipboard should not be used")
            )
        )
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(refresh_toolbar=lambda: None)
        )
        MainWindow._copy_selected(window)
        self.assertEqual(calls, ["summary-copy"])

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

    def test_conditions_sidebar_still_shows_unused_conditions(self):
        sidebar = ConditionsSidebar(None, uom_label_fn=lambda _code: "")
        try:
            sidebar.load_conditions(
                {
                    "c1": self.condition,
                    "unused": Condition(uid="unused", name="Unused", ref_no=2),
                },
                {},
                "Project",
            )
            self.assertEqual(
                set(sidebar.collect_ordered_condition_uids()), {"c1", "unused"}
            )
        finally:
            sidebar.deleteLater()


class SummaryTabCoordinatorTests(unittest.TestCase):
    def test_condition_layer_visibility_path_updates_summary_without_reload(self):
        conditions = {
            "c1": Condition(uid="c1", name="A", layer_uid="layer-a"),
            "c2": Condition(uid="c2", name="B", layer_uid="layer-b"),
        }

        class FakeProjectData:
            def get_bid_conditions(self):
                return conditions

            def is_image_layer_uid(self, _layer_uid):
                return False

            def update_layer_visibility(self, layer_uid, show):
                for condition in conditions.values():
                    if str(condition.layer_uid or "") == str(layer_uid):
                        condition.layer_visible = bool(show)
                return []

            def get_selected_page_uids(self):
                return []

        class FakeConditionsSidebar:
            def __init__(self):
                self.calls = []

            def apply_layer_visibility_state(
                self, applied_conditions, grayscale, layer_uid=None
            ):
                self.calls.append((applied_conditions, grayscale, layer_uid))

        class FakeSummaryTab:
            def __init__(self):
                self.calls = []

            def apply_layer_visibility_state(
                self, applied_conditions, grayscale, layer_uid=None
            ):
                self.calls.append((applied_conditions, grayscale, layer_uid))

        class FakeLayersSidebar:
            def __init__(self):
                self.calls = []

            def set_layer_visible(self, layer_uid, show):
                self.calls.append((layer_uid, show))

        loads = []
        layers_sidebar = FakeLayersSidebar()
        conditions_sidebar = FakeConditionsSidebar()
        summary_tab = FakeSummaryTab()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.project_data = FakeProjectData()
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="",
            get_selected_bid_ref=lambda: BidRef("db.mdb", "bid-1"),
            state=SimpleNamespace(grayscale_enabled=False),
        )
        coordinator._sidebar = SimpleNamespace(bid_layers_sidebar=layers_sidebar)
        coordinator.conditions_sidebar = conditions_sidebar
        coordinator.condition_summary_tab = summary_tab
        coordinator.event_bus = SimpleNamespace(
            publish=lambda *_args, **_call_options: None
        )
        coordinator._deferred_persistence = SimpleNamespace(
            schedule_layer_show=lambda *_args: None
        )
        coordinator.plan_view = None
        coordinator._viewer = SimpleNamespace(update_viewers=lambda *_args: None)
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._mesh_scene_dirty = False
        coordinator._dirty_mesh_page_uids = set()
        coordinator._pending_dirty_mesh_refresh = False
        coordinator._last_mesh_args = None
        coordinator._last_mesh_options = None
        coordinator.visualization_service = SimpleNamespace(
            refresh_mesh_view=lambda *_args: None
        )
        coordinator._toolbar = SimpleNamespace(refresh=lambda: None)
        coordinator._suspend_active_layer_tool = lambda *_args: None
        coordinator._restore_suspended_layer_tool = lambda *_args: None
        coordinator._update_export_menu_state = lambda: None
        coordinator._load_condition_summary = lambda: loads.append("load")
        self.assertTrue(
            UIEventCoordinator.update_layer_visibility_deferred(
                coordinator, "layer-a", False
            )
        )
        self.assertFalse(conditions["c1"].layer_visible)
        self.assertTrue(conditions["c2"].layer_visible)
        self.assertEqual(layers_sidebar.calls, [("layer-a", False)])
        self.assertEqual(conditions_sidebar.calls, [(conditions, False, "layer-a")])
        self.assertEqual(summary_tab.calls, [(conditions, False, "layer-a")])
        self.assertEqual(loads, [])

    def test_summary_tab_visibility_tracks_takeoff_tab(self):
        class FakeTabWidget:
            def __init__(self):
                self.visible = {}
                self.current = TAB_INDEX_SUMMARY

            def setTabVisible(self, index, visible):
                self.visible[index] = visible

            def currentIndex(self):
                return self.current

            def count(self):
                return 3

            def setCurrentIndex(self, index):
                self.current = index

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._tab_widget = FakeTabWidget()
        UIEventCoordinator._set_takeoff_tab_visible(coordinator, True)
        self.assertTrue(coordinator._tab_widget.visible[TAB_INDEX_TAKEOFF])
        self.assertTrue(coordinator._tab_widget.visible[TAB_INDEX_SUMMARY])
        UIEventCoordinator._set_takeoff_tab_visible(coordinator, False)
        self.assertFalse(coordinator._tab_widget.visible[TAB_INDEX_TAKEOFF])
        self.assertFalse(coordinator._tab_widget.visible[TAB_INDEX_SUMMARY])
        self.assertEqual(coordinator._tab_widget.current, TAB_INDEX_PROJECTS)

    def test_ost_status_path_does_not_clear_populated_summary_tree(self):
        _app()
        tab = ConditionSummaryTab(None, uom_label_fn=lambda _code: "EA")
        service = ConditionSummaryService()
        grouping = ConditionSummaryGrouping(by_page=True, by_type=True)
        root = service.build_summary(
            conditions={
                "c1": Condition(
                    uid="c1",
                    name="Fdn1",
                    condition_type=Condition.TYPE_COUNT,
                    uom1=UOM_EACH,
                    calc_type1=CALC_COUNT,
                    ref_no=1,
                ),
                "unused": Condition(
                    uid="unused",
                    name="Unused",
                    condition_type=Condition.TYPE_COUNT,
                    uom1=UOM_EACH,
                    calc_type1=CALC_COUNT,
                    ref_no=2,
                ),
            },
            folders={},
            takeoffs=[Takeoff(uid="tk1", condition_uid="c1", page_uid="p1")],
            pages=[Page(uid="p1", name="S-100.pdf", sequence=1)],
            areas=[],
            grouping=grouping,
        )
        tab.load_summary(root, grouping)
        tab.set_column_widths({"name": 211, "quantity1": 97})
        tab.resize(900, 400)
        tab.show()
        _app().processEvents()
        name_col = next(
            index
            for index in range(tab.tree.columnCount())
            if tab.tree.headerItem().text(index) == "Name"
        )
        quantity_col = next(
            index
            for index in range(tab.tree.columnCount())
            if tab.tree.headerItem().text(index) == "Quantity 1"
        )
        refreshes = []
        original_refresh = tab.refresh_view
        tab.refresh_view = lambda: (refreshes.append("refresh"), original_refresh())
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.condition_summary_tab = tab
        coordinator.ensure_select_mode = lambda: None
        coordinator._menu_state_signaler = type(
            "FakeSignaler", (), {"request_update": lambda self: None}
        )()
        UIEventCoordinator._on_ost_status_changed(coordinator, active=True)
        _app().processEvents()
        self.assertEqual(refreshes, ["refresh"])
        self.assertGreater(tab.tree.topLevelItemCount(), 0)
        self.assertGreater(
            tab.tree.visualItemRect(tab.tree.topLevelItem(0)).height(), 0
        )
        self.assertEqual(tab.grouping, grouping)
        self.assertEqual(tab.tree.header().sectionSize(name_col), 211)
        self.assertEqual(tab.tree.header().sectionSize(quantity_col), 97)
        self.assertEqual(_condition_row_uids(root), ["c1"])
        tab.deleteLater()

    def test_database_refresh_after_ost_status_keeps_summary_tree_visible(self):
        _app()
        tab = ConditionSummaryTab(None, uom_label_fn=lambda _code: "EA")
        service = ConditionSummaryService()
        grouping = ConditionSummaryGrouping(by_type=True, by_area=True)
        root = service.build_summary(
            conditions={
                "c1": Condition(
                    uid="c1",
                    name="Fdn1",
                    condition_type=Condition.TYPE_COUNT,
                    uom1=UOM_EACH,
                    calc_type1=CALC_COUNT,
                    ref_no=1,
                ),
                "unused": Condition(uid="unused", name="Unused", ref_no=2),
            },
            folders={},
            takeoffs=[Takeoff(uid="tk1", condition_uid="c1", page_uid="p1")],
            pages=[Page(uid="p1", name="S-100.pdf", sequence=1)],
            areas=[BidArea(uid="0", bid_uid="b1", parent_uid="", name="", sequence=1)],
            grouping=grouping,
        )
        tab.load_summary(root, grouping)
        tab.set_column_widths({"name": 211})
        tab.resize(900, 400)
        tab.show()
        _app().processEvents()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.condition_summary_tab = tab
        coordinator.ensure_select_mode = lambda: None
        coordinator._menu_state_signaler = type(
            "FakeSignaler", (), {"request_update": lambda self: None}
        )()
        UIEventCoordinator._on_ost_status_changed(coordinator, active=True)
        coordinator._deferred_persistence = SimpleNamespace(
            flush_for_file=lambda _file_path: True
        )
        coordinator._nav = SimpleNamespace(
            start_refresh=lambda *_args, **_call_options: True
        )
        coordinator.ui_state_manager = SimpleNamespace(selected_area_uid="")
        coordinator._placement = SimpleNamespace()
        coordinator._do_file_refresh = lambda: None
        coordinator._finish_refresh = lambda: None
        UIEventCoordinator._on_database_refreshed(coordinator, file_path="a.mdb")
        _app().processEvents()
        self.assertGreater(tab.tree.topLevelItemCount(), 0)
        self.assertGreater(
            tab.tree.visualItemRect(tab.tree.topLevelItem(0)).height(), 0
        )
        self.assertEqual(tab.grouping, grouping)
        self.assertEqual(_condition_row_uids(root), ["c1"])
        tab.deleteLater()

    def test_database_refresh_while_summary_tab_active_reloads_cleared_summary(self):
        _app()
        bid_ref = BidRef("a.mdb", "bid-1")
        tab = ConditionSummaryTab(None, uom_label_fn=lambda _code: "EA")
        service = ConditionSummaryService()
        grouping = ConditionSummaryGrouping(by_type=True, by_area=True)
        conditions = {
            "c1": Condition(
                uid="c1",
                name="Fdn1",
                condition_type=Condition.TYPE_COUNT,
                uom1=UOM_EACH,
                calc_type1=CALC_COUNT,
                ref_no=1,
            ),
            "unused": Condition(uid="unused", name="Unused", ref_no=2),
        }
        takeoffs = [Takeoff(uid="tk1", condition_uid="c1", page_uid="p1")]
        pages = [Page(uid="p1", name="S-100.pdf", sequence=1)]

        def build_root():
            return service.build_summary(
                conditions=conditions,
                folders={},
                takeoffs=takeoffs,
                pages=pages,
                areas=[],
                grouping=grouping,
            )

        tab.load_summary(build_root(), grouping)
        self.assertGreater(tab.tree.topLevelItemCount(), 0)

        class FakeSidebar:
            def __init__(self):
                self.loads = 0

            def clear_sidebars(self):
                tab.clear()

            def load_condition_summary(self):
                self.loads += 1
                tab.load_summary(build_root(), grouping)

        class FakeTabWidget:
            def currentIndex(self):
                return TAB_INDEX_SUMMARY

        class FakeProjectView:
            def restore_bid_selection(self, _bid_ref):
                pass

        class FakeNav:
            def __init__(self):
                self.refresh_snapshot = SimpleNamespace(
                    bid_ref=bid_ref,
                    page_uids=["p1"],
                    active_page_uid="p1",
                    highlighted_condition_uids=set(),
                    project_uid=None,
                    database_selected=False,
                    selected_file_path="a.mdb",
                    place_condition_uid=None,
                    place_condition_uids=[],
                    selected_area_uid="",
                )

            def compute_state_for(self, **_call_options):
                return NavState.BID_ACTIVE_PAGES_SELECTED

            def finish_refresh(self, _state):
                self.refresh_snapshot = None

        fake_sidebar = FakeSidebar()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._nav = FakeNav()
        coordinator._sidebar = fake_sidebar
        coordinator._tab_widget = FakeTabWidget()
        coordinator._page_settings_bar = None
        coordinator._takeoff_workspace_bid_ref = bid_ref
        coordinator._last_takeoff_selection_context_by_source = {}
        coordinator._clear_staged_takeoff_restore = lambda: None
        coordinator._resolve_bid_lock_state = lambda _bid_ref: None
        coordinator._is_condition_placeable = lambda _condition_uid: True
        coordinator._stage_takeoff_restore = lambda **_call_options: None
        coordinator._activate_takeoff_workspace = lambda: None
        coordinator._set_takeoff_tab_visible = lambda _visible: None
        coordinator._sync_undo_bid = lambda: None
        coordinator._reset_to_select_mode = lambda: None
        coordinator._update_export_menu_state = lambda: None
        coordinator.condition_summary_tab = tab
        coordinator.ui_access_manager = SimpleNamespace(refresh=lambda: None)
        coordinator.ui_state_manager = SimpleNamespace(
            set_highlighted_conditions=lambda _uids: None,
            set_bid_selection=lambda _bid_ref: None,
        )
        coordinator.project_data = SimpleNamespace(
            get_current_file_path=lambda: "a.mdb",
            get_bid=lambda _bid_ref: object(),
            get_current_bid_ref=lambda: bid_ref,
            get_bid_conditions=lambda: conditions,
            deselect_pages=lambda: None,
        )
        coordinator.main_window = SimpleNamespace(project_view=FakeProjectView())
        coordinator._toolbar = SimpleNamespace(refresh=lambda: None)
        UIEventCoordinator._finish_refresh(coordinator)
        self.assertEqual(fake_sidebar.loads, 1)
        self.assertGreater(tab.tree.topLevelItemCount(), 0)
        self.assertEqual(_condition_row_uids(tab._root_node), ["c1"])
        tab.deleteLater()

    def test_delete_condition_flow_refreshes_summary_via_shared_ui_refresh(self):
        from ost_visualizer.presentation.handlers import condition_action_handler

        conditions = {
            "c1": Condition(uid="c1", name="Fdn1"),
            "c2": Condition(uid="c2", name="Fdn2"),
        }
        takeoffs = [Takeoff(uid="tk1", condition_uid="c1", page_uid="p1")]
        tab = ConditionSummaryTab(None, uom_label_fn=lambda _code: "EA")
        service = ConditionSummaryService()

        def reload_summary():
            root = service.build_summary(
                conditions=conditions,
                folders={},
                takeoffs=takeoffs,
                pages=[Page(uid="p1", name="S-100.pdf", sequence=1)],
                areas=[],
                grouping=tab.grouping,
            )
            tab.load_summary(root, tab.grouping)

        class FakeWriteService:
            def delete_conditions(self, _file_path, _bid_uid, condition_uids):
                for uid in condition_uids:
                    conditions.pop(uid, None)
                return True

        class FakeSidebar:
            def window(self):
                return None

            def get_condition_name(self, uid):
                return conditions[uid].name

            def condition_selection_after_delete(self, _condition_uids):
                return None

        refreshes = []
        coordinator = type(
            "FakeCoordinator",
            (),
            {
                "ui_access_manager": _FakeSummaryAccess({Feature.DELETE_CONDITION}),
                "conditions_sidebar": FakeSidebar(),
                "placement": type(
                    "FakePlacement", (), {"force_exit": lambda self: None}
                )(),
                "flush_deferred_for_file": lambda self, _file_path: True,
                "highlight_sidebar": lambda self, _uids, reveal=True: None,
                "ensure_select_mode": lambda self: None,
                "refresh_conditions_ui": lambda self: (
                    refreshes.append("refresh"),
                    reload_summary(),
                ),
            },
        )()
        ui_state = type(
            "FakeUiState",
            (),
            {
                "highlighted_condition_uids": {"c1", "c2"},
                "get_selected_bid_ref": lambda self: BidRef("db.mdb", "bid-1"),
            },
        )()
        handler = ConditionActionHandler(
            coordinator=coordinator,
            project_write_service=FakeWriteService(),
            project_read_service=None,
            project_data=type("FakeProjectData", (), {})(),
            ui_state_manager=ui_state,
        )
        original_confirm = condition_action_handler.confirm_delete_conditions
        condition_action_handler.confirm_delete_conditions = lambda _parent, names: [
            uid for uid, _name in names
        ]
        try:
            reload_summary()
            handler.on_delete_requested(["c1"])
        finally:
            condition_action_handler.confirm_delete_conditions = original_confirm
            tab.deleteLater()
        self.assertEqual(refreshes, ["refresh"])
        self.assertNotIn("c1", conditions)
        self.assertEqual(tab.tree.topLevelItemCount(), 0)


if __name__ == "__main__":
    unittest.main()
