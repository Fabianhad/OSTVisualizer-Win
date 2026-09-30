import os
import unittest
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
from ost_visualizer.domain.services.condition_quantity_service import (
    compute_page_quantities,
)
from ost_visualizer.domain.services.uom_service import CALC_COUNT, UOM_EACH
from ost_visualizer.domain.services.uom_service import (
    CALC_AREA,
    CALC_COUNT,
    UOM_SQUARE_INCHES,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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


class TakeoffLifecycleQuantityTests(unittest.TestCase):
    def setUp(self):
        self.conditions = {
            "area": Condition(
                uid="area",
                condition_type=Condition.TYPE_AREA,
                calc_type1=CALC_AREA,
                uom1=UOM_SQUARE_INCHES,
            ),
            "backout": Condition(
                uid="backout",
                condition_type=Condition.TYPE_AREA,
                calc_type1=CALC_AREA,
                uom1=UOM_SQUARE_INCHES,
            ),
            "attachment": Condition(
                uid="attachment",
                condition_type=Condition.TYPE_ATTACHMENT,
                width=2,
                depth=2,
                calc_type1=CALC_COUNT,
            ),
        }
        self.takeoffs = [
            Takeoff(
                uid="parent",
                condition_uid="area",
                page_uid="page",
                position=[0, 0, 10, 0, 10, 10, 0, 10],
            ),
            Takeoff(
                uid="hole",
                condition_uid="backout",
                page_uid="page",
                parent_uid="parent",
                position=[1, 1, 3, 1, 3, 3, 1, 3],
            ),
            Takeoff(
                uid="point",
                condition_uid="attachment",
                page_uid="page",
                parent_uid="parent",
                position=[5, 5],
            ),
        ]

    def test_summary_attachment_context_retains_own_condition_and_parent_area_dependencies(
        self,
    ):
        service = ConditionSummaryService()
        contexts = service._build_takeoff_contexts(self.conditions, self.takeoffs)
        by_condition = {context.condition_uid: context for context in contexts}
        self.assertIn("attachment", by_condition)
        self.assertEqual(
            service._quantities_for_contexts(
                self.conditions, "attachment", [by_condition["attachment"]]
            )[0],
            1,
        )
        self.assertEqual(
            service._quantities_for_contexts(
                self.conditions, "area", [by_condition["area"]]
            )[0],
            96,
        )
