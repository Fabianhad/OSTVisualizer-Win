import os
import unittest
from ost_visualizer.application.dtos.condition_summary_dtos import (
    SUMMARY_COLUMN_AREA,
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
    SUMMARY_QUANTITY_COLUMNS,
    SUMMARY_UNASSIGNED_LABEL,
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
from ost_visualizer.domain.services.uom_service import (
    CALC_AREA,
    CALC_COUNT,
    UOM_EACH,
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

    def _build(self, grouping=None, takeoffs=None, metric=False):
        return self.service.build_summary(
            conditions=self.conditions,
            folders=self.folders,
            takeoffs=self.takeoffs if takeoffs is None else takeoffs,
            pages=self.pages,
            areas=self.areas,
            project_name="Project",
            grouping=grouping or ConditionSummaryGrouping(),
            metric=metric,
        )

    def test_no_grouping_uses_multi_area_total_inside_folder(self):
        root = self._build()
        self.assertEqual(root.kind, SUMMARY_NODE_ROOT)
        self.assertEqual(root.label, "Conditions - Project")
        folder = _first_descendant(root, SUMMARY_NODE_FOLDER)
        self.assertEqual(folder.label, "CONDITION FOLDER")
        self.assertEqual(folder.folder_uid, "f1")
        condition = _first_descendant(root, SUMMARY_NODE_MULTI_AREA_TOTAL)
        self.assertEqual(condition.condition_uid, "c1")
        self.assertEqual(condition.values.area, SUMMARY_MULTI_AREA_TOTAL_LABEL)
        self.assertEqual(condition.values.number, "1")
        self.assertEqual(condition.values.name, "Fdn1")
        self.assertEqual(condition.values.type_name, "AB - Spread Interior FTG")
        self.assertEqual(condition.values.height, "2' 0\"")
        self.assertEqual(condition.values.height_inches, 24.0)
        self.assertEqual(condition.values.notes, "noteshere")
        self.assertEqual(condition.values.quantity1, 2.0)
        self.assertEqual(condition.values.uom1, UOM_EACH)
        self.assertEqual(condition.color_fill, 0x336699)
        self.assertEqual(
            condition.bold_columns, (SUMMARY_COLUMN_AREA, *SUMMARY_QUANTITY_COLUMNS)
        )
        self.assertTrue(condition.copyable)
        self.assertTrue(condition.deletable)
        self.assertEqual(
            [child.kind for child in condition.children], [SUMMARY_NODE_AREA_DETAIL] * 2
        )
        self.assertEqual(
            [child.values.area for child in condition.children], ["L-0 FDN", "L-2 FDN"]
        )
        self.assertEqual(
            [child.values.quantity1 for child in condition.children], [1.0, 1.0]
        )
        self.assertEqual(
            [child.deletable for child in condition.children], [False, False]
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
        self.assertIsNone(_first_descendant(root, SUMMARY_NODE_AREA_DETAIL))
        for group in groups:
            self.assertEqual([child.kind for child in group.children], ["condition"])
            self.assertEqual(group.children[0].condition_uid, "c1")
            self.assertEqual(group.children[0].values.quantity1, 1.0)
            self.assertEqual(group.children[0].values.area, "")

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
        ghost = Takeoff(uid="tk9", condition_uid="ghost", page_uid="p1", area_uid="a1")
        root = self._build(takeoffs=[*self.takeoffs, ghost])
        self.assertEqual(_condition_row_uids(root), ["c1"])

    def test_condition_with_placed_takeoffs_is_included(self):
        root = self._build(takeoffs=[self.takeoffs[0]])
        self.assertEqual(_condition_row_uids(root), ["c1"])
        row = _first_descendant(root, SUMMARY_NODE_CONDITION)
        self.assertEqual(row.values.quantity1, 1.0)
        self.assertEqual(row.values.area, "L-0 FDN")
        self.assertIsNone(_first_descendant(root, SUMMARY_NODE_MULTI_AREA_TOTAL))

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
        self.assertEqual([child.label for child in folder.children], ["S-100.pdf"])
        page = folder.children[0]
        self.assertEqual(
            [child.label for child in page.children], ["AB - Spread Interior FTG"]
        )
        type_group = page.children[0]
        self.assertEqual(
            [child.label for child in type_group.children], ["L-0 FDN", "L-2 FDN"]
        )
        area = type_group.children[0]
        self.assertEqual(page.group_level, SUMMARY_GROUP_PAGE)
        self.assertEqual(page.label, "S-100.pdf")
        self.assertEqual(type_group.group_level, SUMMARY_GROUP_TYPE)
        self.assertEqual(type_group.label, "AB - Spread Interior FTG")
        self.assertEqual(area.group_level, SUMMARY_GROUP_AREA)
        self.assertEqual(area.label, "L-0 FDN")
        self.assertEqual([child.kind for child in area.children], ["condition"])
        self.assertEqual(area.children[0].values.quantity1, 1.0)

    def test_area_type_grouping_uses_type_then_area(self):
        root = self._build(ConditionSummaryGrouping(by_type=True, by_area=True))
        folder = _first_descendant(root, SUMMARY_NODE_FOLDER)
        self.assertEqual(
            [child.group_level for child in folder.children], [SUMMARY_GROUP_TYPE]
        )
        type_group = folder.children[0]
        self.assertEqual(
            [child.group_level for child in type_group.children],
            [SUMMARY_GROUP_AREA, SUMMARY_GROUP_AREA],
        )
        self.assertEqual(
            [child.label for child in type_group.children], ["L-0 FDN", "L-2 FDN"]
        )
        self.assertEqual(
            [child.children[0].kind for child in type_group.children],
            ["condition", "condition"],
        )

    def test_area_page_grouping_uses_page_then_area(self):
        root = self._build(ConditionSummaryGrouping(by_page=True, by_area=True))
        folder = _first_descendant(root, SUMMARY_NODE_FOLDER)
        self.assertEqual(
            [child.group_level for child in folder.children], [SUMMARY_GROUP_PAGE]
        )
        page_group = folder.children[0]
        self.assertEqual(page_group.label, "S-100.pdf")
        self.assertEqual(
            [child.group_level for child in page_group.children],
            [SUMMARY_GROUP_AREA, SUMMARY_GROUP_AREA],
        )
        self.assertEqual(
            [child.label for child in page_group.children], ["L-0 FDN", "L-2 FDN"]
        )

    def test_type_page_grouping_uses_page_then_type(self):
        root = self._build(ConditionSummaryGrouping(by_page=True, by_type=True))
        folder = _first_descendant(root, SUMMARY_NODE_FOLDER)
        self.assertEqual(
            [child.group_level for child in folder.children], [SUMMARY_GROUP_PAGE]
        )
        page_group = folder.children[0]
        self.assertEqual(
            [child.group_level for child in page_group.children], [SUMMARY_GROUP_TYPE]
        )
        type_group = page_group.children[0]
        self.assertEqual(type_group.label, "AB - Spread Interior FTG")
        self.assertEqual(
            [child.kind for child in type_group.children],
            [SUMMARY_NODE_MULTI_AREA_TOTAL],
        )
        self.assertEqual(type_group.children[0].values.quantity1, 2.0)

    def test_type_group_keeps_multi_area_total_when_area_not_grouped(self):
        root = self._build(ConditionSummaryGrouping(by_type=True))
        type_group = _first_descendant(root, SUMMARY_NODE_GROUP)
        self.assertEqual(type_group.group_level, SUMMARY_GROUP_TYPE)
        self.assertEqual(
            [child.kind for child in type_group.children],
            [SUMMARY_NODE_MULTI_AREA_TOTAL],
        )
        self.assertEqual(
            [child.kind for child in type_group.children[0].children],
            [SUMMARY_NODE_AREA_DETAIL] * 2,
        )

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
        self.assertEqual(
            [child.children[0].condition_uid for child in folder.children],
            ["c1", "c1"],
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
        self.assertEqual(row.values.quantity1, 0.0)
        takeoffs = [
            Takeoff(uid="tk1", condition_uid="c1", page_uid="p1", area_uid="a1"),
            Takeoff(uid="tk2", condition_uid="c1", page_uid="p1", area_uid="a1"),
            Takeoff(
                uid="tk3",
                condition_uid="c1",
                page_uid="p1",
                area_uid="a1",
                is_negative=True,
            ),
        ]
        row = _first_descendant(self._build(takeoffs=takeoffs), SUMMARY_NODE_CONDITION)
        self.assertEqual(row.values.quantity1, 1.0)

    def test_groups_sort_by_sequence_then_name_with_unassigned_area_last(self):
        self.pages = [
            Page(uid="p1", name="A-first-by-name", sequence=2),
            Page(uid="p2", name="Z-second-by-name", sequence=1),
        ]
        self.areas = [
            BidArea(uid="a1", bid_uid="b1", parent_uid="", name="Area A", sequence=2),
            BidArea(uid="a2", bid_uid="b1", parent_uid="", name="Area B", sequence=1),
        ]
        self.conditions["c2"] = Condition(
            uid="c2",
            name="Second",
            cdn_type_uid="t0",
            cdn_type_name="Aa Type",
            folder_uid="f1",
            uom1=UOM_EACH,
            calc_type1=CALC_COUNT,
            ref_no=2,
        )
        takeoffs = [
            Takeoff(uid="tk1", condition_uid="c1", page_uid="p1", area_uid="a1"),
            Takeoff(uid="tk2", condition_uid="c1", page_uid="p2", area_uid="a2"),
            Takeoff(uid="tk3", condition_uid="c2", page_uid="p1", area_uid=""),
        ]
        root = self._build(ConditionSummaryGrouping(by_page=True), takeoffs=takeoffs)
        self.assertEqual(
            _group_labels(root, SUMMARY_GROUP_PAGE),
            ["Z-second-by-name", "A-first-by-name"],
        )
        root = self._build(ConditionSummaryGrouping(by_area=True), takeoffs=takeoffs)
        self.assertEqual(
            _group_labels(root, SUMMARY_GROUP_AREA),
            ["Area B", "Area A", SUMMARY_UNASSIGNED_LABEL],
        )
        root = self._build(ConditionSummaryGrouping(by_type=True), takeoffs=takeoffs)
        self.assertEqual(
            _group_labels(root, SUMMARY_GROUP_TYPE),
            ["Aa Type", "AB - Spread Interior FTG"],
        )

    def test_condition_rows_sort_by_ref_no_then_name_and_label_unassigned_area(self):
        self.folders = {}
        self.conditions = {
            "c1": Condition(uid="c1", name="B", ref_no=5, calc_type1=CALC_COUNT),
            "c2": Condition(uid="c2", name="Z", ref_no=2, calc_type1=CALC_COUNT),
            "c3": Condition(uid="c3", name="a", ref_no=2, calc_type1=CALC_COUNT),
        }
        takeoffs = [
            Takeoff(uid=f"tk-{uid}", condition_uid=uid, page_uid="p1", area_uid="")
            for uid in ("c1", "c2", "c3")
        ]
        root = self._build(takeoffs=takeoffs)
        self.assertEqual(
            [child.kind for child in root.children], [SUMMARY_NODE_CONDITION] * 3
        )
        self.assertEqual(_condition_row_uids(root), ["c3", "c2", "c1"])
        self.assertEqual(
            [child.values.area for child in root.children],
            [SUMMARY_UNASSIGNED_LABEL] * 3,
        )
        self.assertEqual(
            [child.values.number for child in root.children], ["2", "2", "5"]
        )

    def test_unassigned_takeoffs_form_their_own_area_detail_row(self):
        takeoffs = [
            Takeoff(uid="tk1", condition_uid="c1", page_uid="p1", area_uid="a1"),
            Takeoff(uid="tk2", condition_uid="c1", page_uid="p1", area_uid=""),
        ]
        root = self._build(takeoffs=takeoffs)
        total = _first_descendant(root, SUMMARY_NODE_MULTI_AREA_TOTAL)
        self.assertEqual(
            [child.values.area for child in total.children],
            ["L-0 FDN", SUMMARY_UNASSIGNED_LABEL],
        )
        self.assertEqual(total.values.quantity1, 2.0)

    def test_nested_folders_sort_by_name_and_unknown_folders_fall_back_to_root(self):
        def count_condition(uid, ref_no, folder_uid):
            return Condition(
                uid=uid,
                name=uid,
                folder_uid=folder_uid,
                ref_no=ref_no,
                calc_type1=CALC_COUNT,
            )

        self.folders = {
            "fA": BidConditionFolder(uid="fA", name="Alpha"),
            "fB": BidConditionFolder(uid="fB", name="Beta", parent_uid="fA"),
            "fC": BidConditionFolder(uid="fC", name="charlie"),
            "fD": BidConditionFolder(uid="fD", name="Delta", parent_uid="missing"),
        }
        self.conditions = {
            "c1": count_condition("c1", 1, "fB"),
            "c2": count_condition("c2", 2, "fC"),
            "c3": count_condition("c3", 3, "gone"),
            "c4": count_condition("c4", 4, "fD"),
            "c5": count_condition("c5", 5, "fA"),
        }
        takeoffs = [
            Takeoff(uid=f"tk-{uid}", condition_uid=uid, page_uid="p1", area_uid="a1")
            for uid in self.conditions
        ]
        root = self._build(takeoffs=takeoffs)
        self.assertEqual(
            [
                (child.kind, child.label or child.condition_uid)
                for child in root.children
            ],
            [
                (SUMMARY_NODE_FOLDER, "Alpha"),
                (SUMMARY_NODE_FOLDER, "charlie"),
                (SUMMARY_NODE_FOLDER, "Delta"),
                (SUMMARY_NODE_CONDITION, "c3"),
            ],
        )
        alpha, charlie, delta = root.children[:3]
        self.assertEqual(
            [
                (child.kind, child.label or child.condition_uid)
                for child in alpha.children
            ],
            [(SUMMARY_NODE_FOLDER, "Beta"), (SUMMARY_NODE_CONDITION, "c5")],
        )
        self.assertEqual(_condition_row_uids(alpha.children[0]), ["c1"])
        self.assertEqual(_condition_row_uids(charlie), ["c2"])
        self.assertEqual(_condition_row_uids(delta), ["c4"])

    def test_metric_summary_formats_condition_height_in_millimetres(self):
        row = _first_descendant(
            self._build(takeoffs=[self.takeoffs[0]], metric=True),
            SUMMARY_NODE_CONDITION,
        )
        self.assertEqual(row.values.height, "609.6")
        self.assertEqual(row.values.height_inches, 24.0)


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
            [takeoff.uid for takeoff in by_condition["area"].takeoffs],
            ["parent", "hole", "point"],
        )
        self.assertEqual(
            [takeoff.uid for takeoff in by_condition["attachment"].takeoffs],
            ["point"],
        )
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

    def test_summary_rows_net_child_backouts_and_hide_child_area_rows(self):
        root = ConditionSummaryService().build_summary(
            conditions=self.conditions,
            folders={},
            takeoffs=self.takeoffs,
            pages=[Page(uid="page", name="Page 1", sequence=1)],
            areas=[],
        )
        self.assertEqual(root.label, "Conditions")
        self.assertEqual(_condition_row_uids(root), ["area", "attachment"])
        self.assertEqual(
            [(row.condition_uid, row.values.quantity1) for row in root.children],
            [("area", 96.0), ("attachment", 1.0)],
        )
