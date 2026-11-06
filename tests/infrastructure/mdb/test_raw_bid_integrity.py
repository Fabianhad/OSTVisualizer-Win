import dataclasses
import unittest
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.infrastructure.mdb import raw_bid_integrity
from ost_visualizer.infrastructure.mdb.raw_bid_integrity import (
    BID_RELATIONSHIPS,
    RAW_BID_RELATIONSHIPS,
    RawBidCardinalityIssue,
    RawBidDuplicateUid,
    RawBidIntegrityIssue,
    RawBidMalformedUid,
    RawBidParentCycle,
    RawBidRelationship,
    RawBidTakeoffPageMismatch,
    TakeoffGraphResolution,
    clear_missing_annotation_takeoff_references,
    clear_missing_selected_page_references,
    clone_raw_bid_data,
    format_integrity_issues,
    prepare_raw_bid_data_for_export,
    raw_bid_table_rows,
    resolve_takeoff_graph,
    validate_raw_bid_integrity,
)
from ost_visualizer.infrastructure.mdb.schema_contract import (
    GLOBAL_SECTIONS,
    PAGE_SECTIONS,
)
from tests.helpers.mdb.import_export_support import (
    _orphan_named_view_hotlink_raw_data as _import_export_support__orphan_named_view_hotlink_raw_data,
    _raw_data_with_row as _import_export_support__raw_data_with_row,
)


class RawBidIntegrityRelationshipTests(unittest.TestCase):
    def test_raw_bid_integrity_map_reports_each_declared_relationship(self):
        self.assertEqual(len(RAW_BID_RELATIONSHIPS), 96)
        self.assertIn(
            ("BidTakeoffs", "BidPageUID", "BidPages"),
            {
                (r.child_table, r.child_column, r.parent_table)
                for r in RAW_BID_RELATIONSHIPS
            },
        )
        for relationship in RAW_BID_RELATIONSHIPS:
            with self.subTest(
                table=relationship.child_table,
                column=relationship.child_column,
                parent=relationship.parent_table,
            ):
                raw_data = _import_export_support__raw_data_with_row(
                    relationship.child_table,
                    {"UID": "1", relationship.child_column: "999"},
                )
                issues = validate_raw_bid_integrity(raw_data)
                self.assertTrue(
                    any(
                        issue.table == relationship.child_table
                        and issue.column == relationship.child_column
                        and issue.missing_uid == "999"
                        and issue.parent_table == relationship.parent_table
                        for issue in issues
                    ),
                    issues,
                )

    def test_raw_bid_integrity_ignores_null_references_and_import_reconciled_masters(
        self,
    ):
        raw_data = RawBidData(
            bid_row={
                "UID": "1",
                "JobStatusUID": "999",
                "EstimatorUID": "999",
                "PrManagerUID": "999",
                "JobSiteManagerUID": "999",
            },
            bid_tables={
                "BidAreas": [
                    {"UID": "2", "BidUID": "1", "ParentUID": "0"},
                    {"UID": "3", "BidUID": "1", "ParentUID": ""},
                    {"UID": "4", "BidUID": "1", "ParentUID": "NULL"},
                    {"UID": "5", "BidUID": "1", "ParentUID": "2"},
                ]
            },
        )
        self.assertEqual(validate_raw_bid_integrity(raw_data), [])
        self.assertNotIn(
            ("Bids", "JobStatusUID"),
            {(r.child_table, r.child_column) for r in RAW_BID_RELATIONSHIPS},
        )

    def test_raw_bid_integrity_requires_takeoff_page_and_condition_references(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidConditions": [{"UID": "5", "BidUID": "1"}],
                "BidPages": [{"UID": "3", "BidUID": "1"}],
            },
            page_tables={
                "BidTakeoffs": [
                    {"UID": "7", "BidUID": "1", "BidConditionUID": "5"},
                    {
                        "UID": "8",
                        "BidUID": "1",
                        "BidConditionUID": "0",
                        "BidPageUID": "3",
                    },
                ]
            },
        )
        self.assertEqual(
            [
                (issue.table, issue.row_uid, issue.column, issue.missing_uid)
                for issue in validate_raw_bid_integrity(raw_data)
            ],
            [
                ("BidTakeoffs", "7", "BidPageUID", "<missing>"),
                ("BidTakeoffs", "8", "BidConditionUID", "<missing>"),
            ],
        )

    def test_raw_bid_integrity_rejects_duplicate_and_malformed_authoritative_uids(
        self,
    ):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidPages": [
                    {"UID": "3", "BidUID": "1"},
                    {"UID": "03", "BidUID": "1"},
                    {"UID": "0", "BidUID": "1"},
                    {"UID": "x", "BidUID": "1"},
                ]
            },
        )
        self.assertEqual(
            [issue.format() for issue in validate_raw_bid_integrity(raw_data)],
            [
                "BidPages.UID=0 has malformed UID=0",
                "BidPages.UID=x has malformed UID=x",
                "BidPages.UID=3 occurs 2 times",
            ],
        )

    def test_raw_bid_integrity_rejects_hierarchy_parent_cycles(self):
        for table in ("BidAreas", "BidConditionFolders", "BidPageFolders"):
            with self.subTest(table=table):
                raw_data = RawBidData(
                    bid_row={"UID": "1"},
                    bid_tables={
                        table: [
                            {"UID": "7", "BidUID": "1", "ParentUID": "8"},
                            {"UID": "8", "BidUID": "1", "ParentUID": "7"},
                        ]
                    },
                )
                issues = validate_raw_bid_integrity(raw_data)
                self.assertEqual(
                    [issue.format() for issue in issues],
                    [
                        f"{table}.UID=7 participates in a ParentUID cycle",
                        f"{table}.UID=8 participates in a ParentUID cycle",
                    ],
                )

    def test_raw_bid_integrity_accepts_acyclic_hierarchy_and_reports_self_parent(self):
        for table in ("BidAreas", "BidConditionFolders", "BidPageFolders"):
            with self.subTest(table=table):
                chain = RawBidData(
                    bid_row={"UID": "1"},
                    bid_tables={
                        table: [
                            {"UID": "7", "BidUID": "1", "ParentUID": "8"},
                            {"UID": "8", "BidUID": "1", "ParentUID": "0"},
                        ]
                    },
                )
                self.assertEqual(validate_raw_bid_integrity(chain), [])
                self_parent = RawBidData(
                    bid_row={"UID": "1"},
                    bid_tables={table: [{"UID": "7", "BidUID": "1", "ParentUID": "7"}]},
                )
                self.assertEqual(
                    [
                        issue.format()
                        for issue in validate_raw_bid_integrity(self_parent)
                    ],
                    [f"{table}.UID=7 participates in a ParentUID cycle"],
                )

    def test_raw_bid_integrity_rejects_multiple_bid_settings_rows(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidSettings": [
                    {"UID": "10", "BidUID": "1"},
                    {"UID": "11", "BidUID": "1"},
                ]
            },
        )
        issues = validate_raw_bid_integrity(raw_data)
        self.assertEqual(
            [issue.format() for issue in issues],
            ["BidSettings has 2 rows for Bids.UID=1; expected at most 1"],
        )
        single = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={"BidSettings": [{"UID": "10", "BidUID": "1"}]},
        )
        self.assertEqual(validate_raw_bid_integrity(single), [])

    def test_prepare_export_prunes_named_views_and_hotlinks_for_missing_pages(self):
        original = _import_export_support__orphan_named_view_hotlink_raw_data()
        prepared = prepare_raw_bid_data_for_export(original)
        self.assertEqual(len(original.bid_tables["BidNamedViews"]), 2)
        self.assertEqual(len(original.bid_tables["BidHotLinks"]), 4)
        self.assertEqual(
            [row["Name"] for row in prepared.bid_tables["BidNamedViews"]],
            ["Valid"],
        )
        self.assertEqual(
            [row["Name"] for row in prepared.bid_tables["BidHotLinks"]],
            ["Valid Link"],
        )
        self.assertEqual(validate_raw_bid_integrity(prepared), [])

    def test_prepare_export_clears_missing_selected_page_without_pruning_settings(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidPages": [{"UID": "20", "BidUID": "1"}],
                "BidSettings": [
                    {"UID": "10", "BidUID": "1", "BidPageSelectedUID": "99"}
                ],
            },
        )
        prepared = prepare_raw_bid_data_for_export(raw_data)
        self.assertEqual(
            prepared.bid_tables["BidSettings"],
            [{"UID": "10", "BidUID": "1", "BidPageSelectedUID": "0"}],
        )
        self.assertEqual(
            raw_data.bid_tables["BidSettings"][0]["BidPageSelectedUID"], "99"
        )
        self.assertEqual(validate_raw_bid_integrity(prepared), [])

    def test_prepare_export_rejects_takeoff_graph_cycles(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidConditions": [{"UID": "5", "BidUID": "1"}],
                "BidPages": [{"UID": "3", "BidUID": "1"}],
            },
            page_tables={
                "BidTakeoffs": [
                    {
                        "UID": uid,
                        "BidUID": "1",
                        "BidConditionUID": "5",
                        "BidPageUID": "3",
                        "ParentUID": parent,
                    }
                    for uid, parent in (("7", "8"), ("8", "7"))
                ]
            },
        )
        with self.assertRaisesRegex(
            ValueError,
            "Cannot export invalid takeoff graph: "
            "BidTakeoffs.UID=7 participates in a ParentUID cycle; "
            "BidTakeoffs.UID=8 participates in a ParentUID cycle",
        ):
            prepare_raw_bid_data_for_export(raw_data)


class TakeoffLifecycleOwnershipTests(unittest.TestCase):
    def test_raw_import_export_rejects_cross_page_parent(self):
        raw = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidConditions": [{"UID": "5", "BidUID": "1"}],
                "BidPages": [{"UID": "3", "BidUID": "1"}, {"UID": "4", "BidUID": "1"}],
            },
            page_tables={
                "BidTakeoffs": [
                    {
                        "UID": "7",
                        "BidUID": "1",
                        "BidConditionUID": "5",
                        "BidPageUID": "3",
                        "ParentUID": "0",
                    },
                    {
                        "UID": "8",
                        "BidUID": "1",
                        "BidConditionUID": "5",
                        "BidPageUID": "4",
                        "ParentUID": "7",
                    },
                ]
            },
        )
        issues = validate_raw_bid_integrity(raw)
        self.assertEqual(
            [issue.format() for issue in issues],
            ["BidTakeoffs.UID=8 has a parent on another Page"],
        )
        raw.page_tables["BidTakeoffs"][1]["BidPageUID"] = "3"
        self.assertEqual(validate_raw_bid_integrity(raw), [])


def _issue_tuples(issues):
    return [
        (issue.table, issue.row_uid, issue.column, issue.missing_uid)
        for issue in issues
    ]


def _takeoff(uid, parent="0", page="3", condition="5"):
    return {
        "UID": uid,
        "BidUID": "1",
        "BidConditionUID": condition,
        "BidPageUID": page,
        "ParentUID": parent,
    }


def _takeoff_raw_data(*takeoffs, pages=("3",)):
    return RawBidData(
        bid_row={"UID": "1"},
        bid_tables={
            "BidConditions": [{"UID": "5", "BidUID": "1"}],
            "BidPages": [{"UID": page, "BidUID": "1"} for page in pages],
        },
        page_tables={"BidTakeoffs": list(takeoffs)},
    )


# Every declared child -> parent edge as "<ChildTable>.<ChildColumn> <ParentTable>".
# Written out independently of the production tuple; the parent column is UID for
# all of them (asserted separately).
_EXPECTED_RELATIONSHIPS = """
Bids.BidProjectUID BidProjects
Bids.OrigBidProjectUID BidProjects
Bids.JobStatusUID JobStatuses
Bids.EstimatorUID Employees
Bids.PrManagerUID Employees
Bids.JobSiteManagerUID Employees
AffectDPCTypGroupViews.BidTypGroupViewUID BidTypGroupViews
AffectDPCTypGroupViews.BidUID Bids
BidPlanRooms.BidUID Bids
BidAreas.BidUID Bids
BidAreas.ParentUID BidAreas
BidTypAreas.BidUID Bids
BidConditionFolders.BidUID Bids
BidConditionFolders.ParentUID BidConditionFolders
BidPageFolders.BidUID Bids
BidPageFolders.ParentUID BidPageFolders
BidSettings.BidUID Bids
BidSettings.BidPageSelectedUID BidPages
BidEmployees.BidUID Bids
BidEmployees.EmployeeUID Employees
BidEmployees.PayClassUID PayClasses
BidLayers.BidUID Bids
BidTypAreaCounts.BidAreaUID BidAreas
BidTypAreaCounts.BidTypAreaUID BidTypAreas
BidConditions.BidUID Bids
BidConditions.BidConditionFolderUID BidConditionFolders
BidConditions.BidLayerUID BidLayers
BidConditions.CdnTypeUID CdnTypes
BidConditionUser.BidUID Bids
BidConditionUser.ConditionUID BidConditions
BidDPCSubscribers.BidUID Bids
BidDPCSubscribers.BidEmployeeUID Employees
BidLaborActivity.BidUID Bids
BidLaborActivity.BidConditionUID BidConditions
BidLaborActivity.BidLaborCostCodeUID BidLaborCostCodes
BidLaborCostCodes.BidUID Bids
BidLaborCostCodes.CostCodeUID CostCodes
BidLaborCostCodeTotals.BidUID Bids
BidLaborCostCodeTotals.BidPageUID BidPages
BidLaborCostCodeTotals.BidAreaUID BidAreas
BidLaborCostCodeTotals.BidLaborCostCodeUID BidLaborCostCodes
BidNotes.BidUID Bids
BidPercents.BidTimeCardStateUID BidTimeCardStates
BidPercents.BidLaborCostCodeUID BidLaborCostCodes
BidPercents.BidLaborActivityUID BidLaborActivity
BidPercents.BidTakeoffUID BidTakeoffs
BidPercents.BidPageUID BidPages
BidZones.BidUID Bids
BidZones.BidLayerUID BidLayers
BidTypGroupViews.BidUID Bids
BidTypGroupViews.BidPageUID BidPages
BidTypGroupViews.BidConditionUID BidConditions
BidPages.BidUID Bids
BidPages.BidPageFolderUID BidPageFolders
BidPages.MasterPageUID BidPages
BidTakeoffs.BidUID Bids
BidTakeoffs.BidPageUID BidPages
BidTakeoffs.BidConditionUID BidConditions
BidTakeoffs.BidZoneUID BidZones
BidTakeoffs.BidAreaUID BidAreas
BidTakeoffs.BidTypAreaUID BidTypAreas
BidTakeoffs.ParentUID BidTakeoffs
BidTakeoffs.TypGroupTakeoffUID BidTakeoffs
BidTakeoffs.TypPageTakeoffUID BidTakeoffs
BidTakeoffs.TypGroupMarkerUID BidTakeoffs
BidTakeoffTotals.BidUID Bids
BidTakeoffTotals.BidPageUID BidPages
BidTakeoffTotals.BidZoneUID BidZones
BidTakeoffTotals.BidAreaUID BidAreas
BidTakeoffTotals.BidTypAreaUID BidTypAreas
BidTakeoffTotals.BidConditionUID BidConditions
BidTimeCardStates.BidUID Bids
BidTimeCards.BidTimeCardStateUID BidTimeCardStates
BidTimeCards.BidEmployeeUID BidEmployees
BidTimeCards.BidAreaUID BidAreas
BidTimeCards.BidTypicalAreaUID BidTypAreas
BidTimeCards.BidLaborCostCodeUID BidLaborCostCodes
BidTransactionsHistory.BidUID Bids
BidHighlights.BidUID Bids
BidHighlights.BidPageUID BidPages
BidHighlights.BidLayerUID BidLayers
BidTexts.BidUID Bids
BidTexts.BidPageUID BidPages
BidTexts.BidLayerUID BidLayers
BidDimensions.BidUID Bids
BidDimensions.BidPageUID BidPages
BidDimensions.BidTakeoffFromUID BidTakeoffs
BidDimensions.BidTakeoffToUID BidTakeoffs
BidArrows.BidUID Bids
BidArrows.BidPageUID BidPages
BidArrows.BidTakeoffFromUID BidTakeoffs
BidArrows.BidTakeoffToUID BidTakeoffs
BidALines.BidUID Bids
BidALines.BidPageUID BidPages
BidALines.BidTakeoffFromUID BidTakeoffs
BidALines.BidTakeoffToUID BidTakeoffs
BidCallOuts.BidUID Bids
BidCallOuts.BidPageUID BidPages
BidCallOuts.BidLayerUID BidLayers
BidAnnotationRects.BidUID Bids
BidAnnotationRects.BidPageUID BidPages
BidAnnotationRects.BidLayerUID BidLayers
BidAnnotationOvals.BidUID Bids
BidAnnotationOvals.BidPageUID BidPages
BidAnnotationOvals.BidLayerUID BidLayers
BidAnnotationPolygons.BidUID Bids
BidAnnotationPolygons.BidPageUID BidPages
BidAnnotationPolygons.BidLayerUID BidLayers
BidAnnotationClouds.BidUID Bids
BidAnnotationClouds.BidPageUID BidPages
BidAnnotationClouds.BidLayerUID BidLayers
BidAnnoInk.BidUID Bids
BidAnnoInk.BidPageUID BidPages
BidLegends.BidUID Bids
BidLegends.BidPageUID BidPages
BidPageSettings.BidPageUID BidPages
BidPageSettings.BidAreaUID BidAreas
BidPageSettings.BidTypAreaUID BidTypAreas
BidAreaTranslations.BidPageUID BidPages
BidAreaTranslations.MasterAreaUID BidAreas
BidAreaTranslations.TranslateAreaUID BidAreas
BidMarkedPages.BidPageUID BidPages
BidComments.BidUID Bids
BidComments.BidPageUID BidPages
BidComments.BidLayerUID BidLayers
BidComments.ParentCommentUID BidComments
BidNamedViews.BidUID Bids
BidNamedViews.BidPageUID BidPages
BidHotLinks.BidUID Bids
BidHotLinks.BidPageUID BidPages
BidHotLinks.BidPageViewUID BidNamedViews
BidHotLinks.BidLayerUID BidLayers
BidTypicalGroupTotals.BidUID Bids
BidTypicalGroupTotals.BidPageUID BidPages
BidTypicalGroupTotals.BidZoneUID BidZones
BidTypicalGroupTotals.BidAreaUID BidAreas
BidTypicalGroupTotals.BidConditionUID BidConditions
Boost.BidUID Bids
Boost.BidPageUID BidPages
DPCCalcFilter.BidUID Bids
DPCCalcFilter.BidPageUID BidPages
STSTransactionHistory.BidUID Bids
Employees.PayClassUID PayClasses
Employees.AccessLevelUID AccessLevels
"""

_RAW_TABLES = frozenset(
    {
        "Bids",
        "BidPlanRooms",
        "BidAreas",
        "BidTypAreas",
        "BidConditionFolders",
        "BidPageFolders",
        "BidSettings",
        "BidEmployees",
        "BidLayers",
        "BidTypAreaCounts",
        "BidConditions",
        "UserMasterConditions",
        "BidConditionUser",
        "BidZones",
        "BidTypGroupViews",
        "OCRProps",
        "BidPages",
        "BidNamedViews",
        "BidHotLinks",
        "BidTakeoffs",
        "BidHighlights",
        "BidTexts",
        "BidDimensions",
        "BidArrows",
        "BidALines",
        "BidCallOuts",
        "BidAnnotationRects",
        "BidAnnotationOvals",
        "BidAnnotationPolygons",
        "BidAnnotationClouds",
        "BidAnnoInk",
        "BidLegends",
        "BidPageSettings",
        "BidAreaTranslations",
        "BidMarkedPages",
        "BidComments",
        "Employees",
        "PayClasses",
        "AccessLevels",
        "CdnTypes",
        "JobStatuses",
    }
)
_IMPORT_RECONCILED = frozenset(
    {
        ("Bids", "JobStatusUID"),
        ("Bids", "EstimatorUID"),
        ("Bids", "PrManagerUID"),
        ("Bids", "JobSiteManagerUID"),
    }
)


def _edge(line):
    child, parent = line.split(" ")
    table, column = child.split(".")
    return (table, column, parent)


def _rows_for(raw_data, table):
    if table == "Bids":
        return [raw_data.bid_row]
    for source in (raw_data.bid_tables, raw_data.page_tables, raw_data.global_tables):
        if table in source:
            return source[table]
    return []


def _add_row(raw_data, table, row):
    if table == "Bids":
        raw_data.bid_row = row
    elif table in PAGE_SECTIONS:
        raw_data.page_tables.setdefault(table, []).append(row)
    elif table in GLOBAL_SECTIONS:
        raw_data.global_tables.setdefault(table, []).append(row)
    else:
        raw_data.bid_tables.setdefault(table, []).append(row)


class RelationshipCatalogLiteralTests(unittest.TestCase):
    def test_bid_relationship_catalog_equals_the_literal_edge_list(self):
        expected = [_edge(line) for line in _EXPECTED_RELATIONSHIPS.split("\n") if line]
        self.assertEqual(len(expected), 144)
        self.assertEqual(len(set(expected)), 144)
        actual = [
            (r.child_table, r.child_column, r.parent_table)
            for r in BID_RELATIONSHIPS
        ]
        self.assertEqual(actual, expected)
        for relationship in BID_RELATIONSHIPS:
            self.assertEqual(relationship.parent_column, "UID")

    def test_only_takeoff_page_and_condition_edges_are_required(self):
        self.assertEqual(
            [
                (r.child_table, r.child_column)
                for r in BID_RELATIONSHIPS
                if r.required
            ],
            [("BidTakeoffs", "BidPageUID"), ("BidTakeoffs", "BidConditionUID")],
        )
        for relationship in BID_RELATIONSHIPS:
            self.assertIs(type(relationship.required), bool)

    def test_raw_relationships_keep_only_raw_table_edges_and_drop_reconciled_ones(
        self,
    ):
        expected = [
            relationship
            for relationship in BID_RELATIONSHIPS
            if relationship.child_table in _RAW_TABLES
            and relationship.parent_table in _RAW_TABLES
            and (relationship.child_table, relationship.child_column)
            not in _IMPORT_RECONCILED
        ]
        self.assertEqual(len(expected), 96)
        self.assertEqual(list(RAW_BID_RELATIONSHIPS), expected)
        self.assertIsInstance(RAW_BID_RELATIONSHIPS, tuple)
        dropped = [r for r in BID_RELATIONSHIPS if r not in RAW_BID_RELATIONSHIPS]
        self.assertEqual(len(dropped), 48)
        self.assertEqual(
            {r.child_table for r in dropped},
            {
                "Bids",
                "AffectDPCTypGroupViews",
                "BidDPCSubscribers",
                "BidLaborActivity",
                "BidLaborCostCodes",
                "BidLaborCostCodeTotals",
                "BidNotes",
                "BidPercents",
                "BidTakeoffTotals",
                "BidTimeCardStates",
                "BidTimeCards",
                "BidTransactionsHistory",
                "BidTypicalGroupTotals",
                "Boost",
                "DPCCalcFilter",
                "STSTransactionHistory",
            },
        )

    def test_each_raw_relationship_accepts_a_matching_parent_and_flags_a_missing_one(
        self,
    ):
        for relationship in RAW_BID_RELATIONSHIPS:
            table = relationship.child_table
            column = relationship.child_column
            parent = relationship.parent_table
            with self.subTest(table=table, column=column, parent=parent):
                resolved = RawBidData()
                _add_row(resolved, table, {"UID": "1", column: "7"})
                _add_row(resolved, parent, {"UID": "7"})
                self.assertEqual(
                    [
                        issue
                        for issue in validate_raw_bid_integrity(resolved)
                        if issue.table == table and issue.column == column
                    ],
                    [],
                )
                dangling = RawBidData()
                _add_row(dangling, table, {"UID": "1", column: "7"})
                _add_row(dangling, parent, {"UID": "8"})
                matching = [
                    issue
                    for issue in validate_raw_bid_integrity(dangling)
                    if issue.table == table and issue.column == column
                ]
                self.assertEqual(
                    [
                        (i.row_uid, i.missing_uid, i.parent_table, i.format())
                        for i in matching
                    ],
                    [
                        (
                            "1",
                            "7",
                            parent,
                            f"{table}.UID=1 {column}=7 missing {parent}.UID",
                        )
                    ],
                )


class IssueFormattingTests(unittest.TestCase):
    def test_integrity_issue_format_names_row_column_value_and_parent(self):
        issue = RawBidIntegrityIssue(
            table="BidTakeoffs",
            row_uid="7",
            column="BidPageUID",
            missing_uid="99",
            parent_table="BidPages",
        )
        self.assertEqual(
            issue.format(), "BidTakeoffs.UID=7 BidPageUID=99 missing BidPages.UID"
        )
        anonymous = RawBidIntegrityIssue("BidTakeoffs", "", "BidPageUID", "9", "BidPages")
        self.assertEqual(
            anonymous.format(),
            "BidTakeoffs.UID=<no UID> BidPageUID=9 missing BidPages.UID",
        )

    def test_duplicate_malformed_cycle_mismatch_and_cardinality_formats(self):
        self.assertEqual(
            RawBidDuplicateUid("BidPages", "3", 2).format(),
            "BidPages.UID=3 occurs 2 times",
        )
        self.assertEqual(
            RawBidMalformedUid("BidPages", "4", "UID", "x").format(),
            "BidPages.UID=4 has malformed UID=x",
        )
        self.assertEqual(
            RawBidMalformedUid("BidTakeoffs", "", "ParentUID", "").format(),
            "BidTakeoffs.UID=<no UID> has malformed ParentUID=<missing>",
        )
        self.assertEqual(
            RawBidParentCycle("BidAreas", "7").format(),
            "BidAreas.UID=7 participates in a ParentUID cycle",
        )
        self.assertEqual(
            RawBidTakeoffPageMismatch("BidTakeoffs", "8").format(),
            "BidTakeoffs.UID=8 has a parent on another Page",
        )
        self.assertEqual(
            RawBidCardinalityIssue("BidSettings", "Bids", "1", 3, 1).format(),
            "BidSettings has 3 rows for Bids.UID=1; expected at most 1",
        )

    def test_issue_records_are_immutable_value_objects(self):
        issue = RawBidDuplicateUid("BidPages", "3", 2)
        self.assertEqual(issue, RawBidDuplicateUid("BidPages", "3", 2))
        self.assertNotEqual(issue, RawBidDuplicateUid("BidPages", "3", 3))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            issue.count = 5

    def test_format_integrity_issues_joins_and_truncates_with_a_remainder_count(self):
        issues = [RawBidDuplicateUid("T", str(n), 2) for n in range(1, 13)]
        lines = [f"T.UID={n} occurs 2 times" for n in range(1, 13)]
        self.assertEqual(format_integrity_issues([]), "")
        self.assertEqual(format_integrity_issues(issues[:1]), lines[0])
        self.assertEqual(format_integrity_issues(issues[:10]), "; ".join(lines[:10]))
        self.assertEqual(
            format_integrity_issues(issues[:11]),
            "; ".join(lines[:10]) + "; +1 more",
        )
        self.assertEqual(
            format_integrity_issues(issues),
            "; ".join(lines[:10]) + "; +2 more",
        )
        self.assertEqual(
            format_integrity_issues(issues[:5], limit=2),
            "; ".join(lines[:2]) + "; +3 more",
        )
        self.assertEqual(
            format_integrity_issues(issues[:2], limit=2), "; ".join(lines[:2])
        )

    def test_takeoff_graph_resolution_defaults_and_skipped_count(self):
        empty = TakeoffGraphResolution()
        self.assertEqual(empty.fatal_issues, ())
        self.assertEqual(empty.missing_parent_roots, ())
        self.assertEqual(empty.dependent_descendants, ())
        self.assertEqual(empty.skipped_count, 0)
        root = RawBidIntegrityIssue("BidTakeoffs", "7", "ParentUID", "99", "BidTakeoffs")
        child = RawBidIntegrityIssue("BidTakeoffs", "8", "ParentUID", "7", "BidTakeoffs")
        grandchild = RawBidIntegrityIssue(
            "BidTakeoffs", "9", "ParentUID", "8", "BidTakeoffs"
        )
        resolution = TakeoffGraphResolution(
            missing_parent_roots=(root,),
            dependent_descendants=(child, grandchild),
        )
        self.assertEqual(resolution.skipped_count, 3)
        fatal_only = TakeoffGraphResolution(
            fatal_issues=(RawBidParentCycle("BidTakeoffs", "7"),)
        )
        self.assertEqual(fatal_only.skipped_count, 0)


class RawTableHelperTests(unittest.TestCase):
    def _sample(self):
        return RawBidData(
            bid_row={"UID": "1", "Name": "Bid"},
            bid_tables={"BidPages": [{"UID": "3", "BidUID": "1"}]},
            page_tables={"BidTakeoffs": [{"UID": "7"}]},
            global_tables={"Employees": [{"UID": "9"}]},
        )

    def test_clone_is_a_deep_copy_of_every_container(self):
        original = self._sample()
        clone = clone_raw_bid_data(original)
        self.assertEqual(clone, original)
        clone.bid_row["Name"] = "Changed"
        clone.bid_tables["BidPages"][0]["UID"] = "30"
        clone.bid_tables["BidPages"].append({"UID": "31"})
        clone.page_tables["BidTakeoffs"][0]["UID"] = "70"
        clone.global_tables["Employees"][0]["UID"] = "90"
        clone.global_tables["PayClasses"] = []
        self.assertEqual(original, self._sample())
        self.assertIsNot(clone.bid_row, original.bid_row)
        self.assertIsNot(clone.bid_tables, original.bid_tables)
        self.assertIsNot(clone.page_tables, original.page_tables)
        self.assertIsNot(clone.global_tables, original.global_tables)

    def test_clone_of_an_empty_bundle_is_empty(self):
        clone = clone_raw_bid_data(RawBidData())
        self.assertEqual(clone, RawBidData())

    def test_table_rows_cover_every_raw_table_and_place_the_bid_row_under_bids(self):
        rows = raw_bid_table_rows(RawBidData())
        self.assertEqual(set(rows), _RAW_TABLES)
        self.assertEqual(len(rows), 41)
        self.assertTrue(all(value == [] for value in rows.values()))
        populated = raw_bid_table_rows(self._sample())
        self.assertEqual(populated["Bids"], [{"UID": "1", "Name": "Bid"}])
        self.assertEqual(populated["BidPages"], [{"UID": "3", "BidUID": "1"}])
        self.assertEqual(populated["BidTakeoffs"], [{"UID": "7"}])
        self.assertEqual(populated["Employees"], [{"UID": "9"}])
        self.assertEqual(populated["BidAreas"], [])

    def test_table_rows_keep_unknown_tables_and_concatenate_repeated_ones(self):
        raw_data = RawBidData(
            bid_tables={"Custom": [{"UID": "1"}], "BidPages": [{"UID": "3"}]},
            page_tables={"Custom": [{"UID": "2"}], "BidPages": [{"UID": "4"}]},
            global_tables={"Custom": [{"UID": "3"}]},
        )
        rows = raw_bid_table_rows(raw_data)
        self.assertEqual(rows["Custom"], [{"UID": "1"}, {"UID": "2"}, {"UID": "3"}])
        self.assertEqual(rows["BidPages"], [{"UID": "3"}, {"UID": "4"}])
        self.assertEqual(len(rows), 42)

    def test_table_rows_do_not_alias_the_source_row_lists(self):
        raw_data = self._sample()
        rows = raw_bid_table_rows(raw_data)
        rows["BidPages"].append({"UID": "99"})
        rows["BidTakeoffs"].clear()
        self.assertEqual(raw_data.bid_tables["BidPages"], [{"UID": "3", "BidUID": "1"}])
        self.assertEqual(raw_data.page_tables["BidTakeoffs"], [{"UID": "7"}])
        self.assertIs(
            raw_bid_table_rows(raw_data)["BidPages"][0],
            raw_data.bid_tables["BidPages"][0],
        )


class ValidateUidRuleTests(unittest.TestCase):
    def test_authoritative_tables_reject_every_non_positive_ascii_decimal_uid(self):
        bad_uids = ("", "0", "-1", "+1", "1.5", " 1", "1 ", "x", "NULL", "٣")
        for uid in bad_uids:
            with self.subTest(uid=uid):
                raw_data = RawBidData(
                    bid_row={"UID": "1"},
                    bid_tables={"BidPages": [{"UID": uid, "BidUID": "1"}]},
                )
                issues = validate_raw_bid_integrity(raw_data)
                self.assertEqual(
                    issues, [RawBidMalformedUid("BidPages", uid, "UID", uid)]
                )

    def test_authoritative_table_row_without_uid_is_malformed_and_formats_as_missing(
        self,
    ):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={"BidPages": [{"BidUID": "1"}]},
        )
        issues = validate_raw_bid_integrity(raw_data)
        self.assertEqual(
            [issue.format() for issue in issues],
            ["BidPages.UID=<no UID> has malformed UID=<missing>"],
        )

    def test_bid_row_is_checked_as_the_authoritative_bids_table(self):
        self.assertEqual(
            [
                issue.format()
                for issue in validate_raw_bid_integrity(
                    RawBidData(bid_row={"UID": "0"})
                )
            ],
            ["Bids.UID=0 has malformed UID=0"],
        )
        self.assertEqual(validate_raw_bid_integrity(RawBidData()), [])
        self.assertEqual(validate_raw_bid_integrity(RawBidData(bid_row={"UID": "12"})), [])

    def test_authoritative_uids_are_compared_numerically_so_padding_collides(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidLayers": [
                    {"UID": "7", "BidUID": "1"},
                    {"UID": "007", "BidUID": "1"},
                    {"UID": "7", "BidUID": "1"},
                ]
            },
        )
        self.assertEqual(
            validate_raw_bid_integrity(raw_data),
            [RawBidDuplicateUid("BidLayers", "7", 3)],
        )

    def test_non_authoritative_tables_count_uids_as_text_and_ignore_blank_ones(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "Employees": [
                    {"UID": "5"},
                    {"UID": "5"},
                    {"UID": "05"},
                    {"UID": ""},
                    {"UID": ""},
                    {"UID": "0"},
                    {"UID": "0"},
                    {"UID": "NULL"},
                    {"UID": "NULL"},
                    {},
                    {},
                ],
                "PayClasses": [{"UID": "9"}, {"UID": "9"}, {"UID": "9"}],
            },
        )
        self.assertEqual(
            validate_raw_bid_integrity(raw_data),
            [
                RawBidDuplicateUid("Employees", "5", 2),
                RawBidDuplicateUid("PayClasses", "9", 3),
            ],
        )

    def test_duplicate_reports_are_sorted_by_uid_text_within_a_table(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidAreas": [
                    {"UID": uid, "BidUID": "1"} for uid in ("9", "10", "9", "10", "2", "2")
                ]
            },
        )
        self.assertEqual(
            [issue.format() for issue in validate_raw_bid_integrity(raw_data)],
            [
                "BidAreas.UID=10 occurs 2 times",
                "BidAreas.UID=2 occurs 2 times",
                "BidAreas.UID=9 occurs 2 times",
            ],
        )

    def test_uid_values_may_be_ints_and_are_compared_as_text(self):
        raw_data = RawBidData(
            bid_row={"UID": 1},
            bid_tables={
                "BidPages": [
                    {"UID": 3, "BidUID": 1},
                    {"UID": "3", "BidUID": "1"},
                ],
                "BidSettings": [{"UID": 10, "BidUID": 1, "BidPageSelectedUID": 99}],
            },
        )
        self.assertEqual(
            [issue.format() for issue in validate_raw_bid_integrity(raw_data)],
            [
                "BidPages.UID=3 occurs 2 times",
                "BidSettings.UID=10 BidPageSelectedUID=99 missing BidPages.UID",
            ],
        )


class ValidateGraphRuleTests(unittest.TestCase):
    def test_issue_groups_are_reported_in_a_fixed_order(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidConditions": [{"UID": "5", "BidUID": "1"}],
                "BidPages": [
                    {"UID": "3", "BidUID": "1"},
                    {"UID": "4", "BidUID": "1"},
                    {"UID": "x", "BidUID": "1"},
                    {"UID": "3", "BidUID": "1"},
                ],
                "BidAreas": [
                    {"UID": "7", "BidUID": "1", "ParentUID": "8"},
                    {"UID": "8", "BidUID": "1", "ParentUID": "7"},
                ],
                "BidSettings": [
                    {"UID": "10", "BidUID": "1", "BidPageSelectedUID": "88"},
                    {"UID": "11", "BidUID": "1", "BidPageSelectedUID": "0"},
                ],
            },
            page_tables={
                "BidTakeoffs": [
                    _takeoff("20", parent="0", page="3"),
                    _takeoff("21", parent="20", page="4"),
                    _takeoff("22", parent="0", page="99"),
                ]
            },
        )
        self.assertEqual(
            [issue.format() for issue in validate_raw_bid_integrity(raw_data)],
            [
                "BidPages.UID=x has malformed UID=x",
                "BidPages.UID=3 occurs 2 times",
                "BidAreas.UID=7 participates in a ParentUID cycle",
                "BidAreas.UID=8 participates in a ParentUID cycle",
                "BidTakeoffs.UID=21 has a parent on another Page",
                "BidSettings has 2 rows for Bids.UID=1; expected at most 1",
                "BidSettings.UID=10 BidPageSelectedUID=88 missing BidPages.UID",
                "BidTakeoffs.UID=22 BidPageUID=99 missing BidPages.UID",
            ],
        )

    def test_hierarchy_cycles_ignore_rows_without_a_present_uid_or_parent(self):
        for null_parent in ("", "0", "NULL"):
            with self.subTest(parent=null_parent):
                raw_data = RawBidData(
                    bid_row={"UID": "1"},
                    bid_tables={
                        "BidAreas": [
                            {"UID": "7", "BidUID": "1", "ParentUID": null_parent},
                            {"UID": "8", "BidUID": "1"},
                        ]
                    },
                )
                self.assertEqual(validate_raw_bid_integrity(raw_data), [])

    def test_cycle_report_names_only_cycle_members_not_their_descendants(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidPageFolders": [
                    {"UID": "1", "BidUID": "1", "ParentUID": "3"},
                    {"UID": "2", "BidUID": "1", "ParentUID": "1"},
                    {"UID": "3", "BidUID": "1", "ParentUID": "2"},
                    {"UID": "4", "BidUID": "1", "ParentUID": "1"},
                    {"UID": "10", "BidUID": "1", "ParentUID": "0"},
                ]
            },
        )
        self.assertEqual(
            [issue.format() for issue in validate_raw_bid_integrity(raw_data)],
            [
                "BidPageFolders.UID=1 participates in a ParentUID cycle",
                "BidPageFolders.UID=2 participates in a ParentUID cycle",
                "BidPageFolders.UID=3 participates in a ParentUID cycle",
            ],
        )

    def test_cycles_are_only_checked_for_the_three_hierarchy_tables(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidLayers": [
                    {"UID": "7", "BidUID": "1", "ParentUID": "8"},
                    {"UID": "8", "BidUID": "1", "ParentUID": "7"},
                ]
            },
        )
        self.assertEqual(validate_raw_bid_integrity(raw_data), [])

    def test_cross_page_parent_is_only_flagged_when_the_parent_row_exists(self):
        raw_data = _takeoff_raw_data(
            _takeoff("7", parent="0", page="3"),
            _takeoff("8", parent="99", page="4"),
            _takeoff("9", parent="NULL", page="4"),
            pages=("3", "4"),
        )
        self.assertEqual(
            [issue.format() for issue in validate_raw_bid_integrity(raw_data)],
            ["BidTakeoffs.UID=8 ParentUID=99 missing BidTakeoffs.UID"],
        )

    def test_cross_page_mismatches_are_reported_sorted_by_uid_text(self):
        raw_data = _takeoff_raw_data(
            _takeoff("7", parent="0", page="3"),
            _takeoff("10", parent="7", page="4"),
            _takeoff("9", parent="7", page="4"),
            pages=("3", "4"),
        )
        self.assertEqual(
            [issue.format() for issue in validate_raw_bid_integrity(raw_data)],
            [
                "BidTakeoffs.UID=10 has a parent on another Page",
                "BidTakeoffs.UID=9 has a parent on another Page",
            ],
        )

    def test_bid_settings_cardinality_counts_each_bid_and_ignores_blank_owners(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidSettings": [
                    {"UID": "10", "BidUID": "9"},
                    {"UID": "11", "BidUID": "9"},
                    {"UID": "12", "BidUID": "9"},
                    {"UID": "13", "BidUID": "10"},
                    {"UID": "14", "BidUID": "10"},
                    {"UID": "15", "BidUID": "0"},
                    {"UID": "16", "BidUID": "0"},
                    {"UID": "17", "BidUID": ""},
                    {"UID": "18"},
                    {"UID": "19", "BidUID": "11"},
                ]
            },
        )
        cardinality = [
            issue
            for issue in validate_raw_bid_integrity(raw_data)
            if isinstance(issue, RawBidCardinalityIssue)
        ]
        self.assertEqual(
            cardinality,
            [
                RawBidCardinalityIssue("BidSettings", "Bids", "10", 2, 1),
                RawBidCardinalityIssue("BidSettings", "Bids", "9", 3, 1),
            ],
        )


class ValidateRelationshipRuleTests(unittest.TestCase):
    def test_custom_relationship_list_replaces_the_default_catalog(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={"BidPages": [{"UID": "3", "BidUID": "99"}]},
        )
        self.assertEqual(
            [i.format() for i in validate_raw_bid_integrity(raw_data)],
            ["BidPages.UID=3 BidUID=99 missing Bids.UID"],
        )
        self.assertEqual(validate_raw_bid_integrity(raw_data, relationships=()), [])
        only_area_parent = (RawBidRelationship("BidAreas", "ParentUID", "BidAreas"),)
        self.assertEqual(
            validate_raw_bid_integrity(raw_data, only_area_parent), []
        )

    def test_custom_parent_column_is_used_for_the_lookup_set(self):
        raw_data = RawBidData(
            bid_tables={
                "BidAreas": [
                    {"UID": "1", "Code": "A", "BidUID": "A"},
                    {"UID": "2", "Code": "", "BidUID": "B"},
                ],
                "BidZones": [{"UID": "3", "BidUID": "1", "Code": "7"}],
            },
        )
        relationships = (
            RawBidRelationship("BidAreas", "BidUID", "BidZones", "Code"),
        )
        self.assertEqual(
            [
                issue.format()
                for issue in validate_raw_bid_integrity(raw_data, relationships)
            ],
            [
                "BidAreas.UID=1 BidUID=A missing BidZones.UID",
                "BidAreas.UID=2 BidUID=B missing BidZones.UID",
            ],
        )
        raw_data.bid_tables["BidZones"].append({"UID": "4", "Code": "A"})
        self.assertEqual(
            [
                issue.format()
                for issue in validate_raw_bid_integrity(raw_data, relationships)
            ],
            ["BidAreas.UID=2 BidUID=B missing BidZones.UID"],
        )

    def test_blank_parent_values_never_satisfy_a_reference(self):
        raw_data = RawBidData(
            bid_tables={
                "BidAreas": [{"UID": "1", "BidUID": "5"}],
                "BidZones": [{"UID": "2", "Code": ""}, {"UID": "3", "Code": "5"}],
            },
        )
        relationships = (RawBidRelationship("BidAreas", "BidUID", "BidZones", "Code"),)
        self.assertEqual(validate_raw_bid_integrity(raw_data, relationships), [])
        raw_data.bid_tables["BidZones"][1]["Code"] = "6"
        self.assertEqual(
            [i.format() for i in validate_raw_bid_integrity(raw_data, relationships)],
            ["BidAreas.UID=1 BidUID=5 missing BidZones.UID"],
        )

    def test_reference_check_is_skipped_for_rows_missing_the_column_or_null_values(
        self,
    ):
        for row in (
            {"UID": "1"},
            {"UID": "1", "ParentUID": ""},
            {"UID": "1", "ParentUID": "0"},
            {"UID": "1", "ParentUID": "NULL"},
        ):
            with self.subTest(row=row):
                raw_data = RawBidData(bid_tables={"BidComments": [row]})
                relationships = (
                    RawBidRelationship("BidComments", "ParentUID", "BidComments"),
                )
                self.assertEqual(
                    validate_raw_bid_integrity(raw_data, relationships), []
                )

    def test_required_reference_reports_missing_column_and_null_values(self):
        relationships = (
            RawBidRelationship("BidComments", "BidPageUID", "BidPages", required=True),
        )
        for label, row in (
            ("absent", {"UID": "4"}),
            ("blank", {"UID": "4", "BidPageUID": ""}),
            ("zero", {"UID": "4", "BidPageUID": "0"}),
            ("null", {"UID": "4", "BidPageUID": "NULL"}),
        ):
            with self.subTest(label):
                raw_data = RawBidData(bid_tables={"BidComments": [row]})
                self.assertEqual(
                    validate_raw_bid_integrity(raw_data, relationships),
                    [
                        RawBidIntegrityIssue(
                            "BidComments", "4", "BidPageUID", "<missing>", "BidPages"
                        )
                    ],
                )
        satisfied = RawBidData(
            bid_tables={
                "BidComments": [{"UID": "4", "BidPageUID": "3"}],
                "BidPages": [{"UID": "3"}],
            }
        )
        self.assertEqual(validate_raw_bid_integrity(satisfied, relationships), [])

    def test_required_reference_without_row_uid_formats_as_no_uid(self):
        relationships = (
            RawBidRelationship("BidEmployees", "PayClassUID", "PayClasses", required=True),
        )
        raw_data = RawBidData(bid_tables={"BidEmployees": [{}]})
        issues = validate_raw_bid_integrity(raw_data, relationships)
        self.assertEqual(
            [i.format() for i in issues],
            [
                "BidEmployees.UID=<no UID> PayClassUID=<missing> missing PayClasses.UID",
            ],
        )
        blank = RawBidData(bid_tables={"BidEmployees": [{"PayClassUID": "0"}]})
        self.assertEqual(
            [i.row_uid for i in validate_raw_bid_integrity(blank, relationships)], [""]
        )

    def test_optional_reference_with_a_missing_parent_row_is_reported_per_row(self):
        relationships = (RawBidRelationship("BidComments", "BidPageUID", "BidPages"),)
        raw_data = RawBidData(
            bid_tables={
                "BidComments": [
                    {"UID": "4", "BidPageUID": "3"},
                    {"UID": "5", "BidPageUID": "8"},
                    {"UID": "6", "BidPageUID": "8"},
                    {"UID": "7"},
                ],
                "BidPages": [{"UID": "3"}],
            }
        )
        self.assertEqual(
            _issue_tuples(validate_raw_bid_integrity(raw_data, relationships)),
            [
                ("BidComments", "5", "BidPageUID", "8"),
                ("BidComments", "6", "BidPageUID", "8"),
            ],
        )

    def test_default_catalog_ignores_edges_to_tables_outside_the_raw_bundle(self):
        raw_data = RawBidData(
            bid_row={
                "UID": "1",
                "BidProjectUID": "999",
                "OrigBidProjectUID": "999",
            },
            bid_tables={
                "BidLaborActivity": [{"UID": "2", "BidUID": "77"}],
            },
            page_tables={
                "BidPercents": [{"UID": "3", "BidPageUID": "88"}],
            },
        )
        self.assertEqual(validate_raw_bid_integrity(raw_data), [])

    def test_default_catalog_checks_global_master_references(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidEmployees": [
                    {"UID": "2", "BidUID": "1", "EmployeeUID": "50", "PayClassUID": "60"}
                ]
            },
            global_tables={
                "Employees": [{"UID": "50", "PayClassUID": "61", "AccessLevelUID": "70"}],
                "PayClasses": [{"UID": "60"}],
                "AccessLevels": [{"UID": "70"}],
            },
        )
        self.assertEqual(
            [issue.format() for issue in validate_raw_bid_integrity(raw_data)],
            ["Employees.UID=50 PayClassUID=61 missing PayClasses.UID"],
        )


def _graph_issue(uid, missing_parent):
    return RawBidIntegrityIssue(
        table="BidTakeoffs",
        row_uid=uid,
        column="ParentUID",
        missing_uid=missing_parent,
        parent_table="BidTakeoffs",
    )


class ResolveTakeoffGraphTests(unittest.TestCase):
    def test_missing_or_empty_takeoff_table_resolves_to_an_empty_result(self):
        for raw_data in (RawBidData(), RawBidData(page_tables={"BidTakeoffs": []})):
            with self.subTest(raw_data=raw_data):
                resolution = resolve_takeoff_graph(raw_data)
                self.assertEqual(resolution, TakeoffGraphResolution())
                self.assertEqual(resolution.skipped_count, 0)

    def test_valid_forest_is_left_untouched(self):
        rows = [
            _takeoff("7", parent="0"),
            _takeoff("8", parent="7"),
            _takeoff("9", parent=""),
            _takeoff("10", parent="NULL"),
            {"UID": "11", "BidUID": "1"},
        ]
        raw_data = _takeoff_raw_data(*rows)
        original_list = raw_data.page_tables["BidTakeoffs"]
        resolution = resolve_takeoff_graph(raw_data)
        self.assertEqual(resolution, TakeoffGraphResolution())
        self.assertIs(raw_data.page_tables["BidTakeoffs"], original_list)
        self.assertEqual(raw_data.page_tables["BidTakeoffs"], rows)

    def test_malformed_uids_are_fatal_and_leave_rows_untouched(self):
        for uid in ("", "0", "-1", "x", "1.5", " 7", "٣"):
            with self.subTest(uid=uid):
                rows = [_takeoff("7"), {"UID": uid, "BidUID": "1"}]
                raw_data = _takeoff_raw_data(*rows)
                resolution = resolve_takeoff_graph(raw_data)
                self.assertEqual(
                    resolution.fatal_issues,
                    (RawBidMalformedUid("BidTakeoffs", uid, "UID", uid),),
                )
                self.assertEqual(resolution.missing_parent_roots, ())
                self.assertEqual(resolution.dependent_descendants, ())
                self.assertEqual(raw_data.page_tables["BidTakeoffs"], rows)

    def test_row_without_uid_is_malformed(self):
        raw_data = _takeoff_raw_data({"BidUID": "1"})
        resolution = resolve_takeoff_graph(raw_data)
        self.assertEqual(
            [issue.format() for issue in resolution.fatal_issues],
            ["BidTakeoffs.UID=<no UID> has malformed UID=<missing>"],
        )

    def test_duplicate_uids_are_fatal_with_exact_counts_sorted_by_text(self):
        raw_data = _takeoff_raw_data(
            _takeoff("9"),
            _takeoff("9"),
            _takeoff("10"),
            _takeoff("10"),
            _takeoff("10"),
            _takeoff("7"),
            _takeoff("9"),
        )
        resolution = resolve_takeoff_graph(raw_data)
        self.assertEqual(
            resolution.fatal_issues,
            (
                RawBidDuplicateUid("BidTakeoffs", "10", 3),
                RawBidDuplicateUid("BidTakeoffs", "9", 3),
            ),
        )
        self.assertEqual(len(raw_data.page_tables["BidTakeoffs"]), 7)
        two = _takeoff_raw_data(_takeoff("4"), _takeoff("4"))
        self.assertEqual(
            resolve_takeoff_graph(two).fatal_issues,
            (RawBidDuplicateUid("BidTakeoffs", "4", 2),),
        )

    def test_malformed_uids_come_before_duplicates_and_stop_parent_checks(self):
        raw_data = _takeoff_raw_data(
            _takeoff("7"),
            _takeoff("7"),
            _takeoff("x"),
            _takeoff("8", parent="bad"),
        )
        resolution = resolve_takeoff_graph(raw_data)
        self.assertEqual(
            [issue.format() for issue in resolution.fatal_issues],
            [
                "BidTakeoffs.UID=x has malformed UID=x",
                "BidTakeoffs.UID=7 occurs 2 times",
            ],
        )

    def test_malformed_parent_uids_are_fatal_naming_the_parent_column(self):
        raw_data = _takeoff_raw_data(
            _takeoff("7"),
            _takeoff("8", parent="abc"),
            _takeoff("9", parent="-4"),
            _takeoff("10", parent="1.5"),
            _takeoff("11", parent="7"),
        )
        rows = list(raw_data.page_tables["BidTakeoffs"])
        resolution = resolve_takeoff_graph(raw_data)
        self.assertEqual(
            resolution.fatal_issues,
            (
                RawBidMalformedUid("BidTakeoffs", "8", "ParentUID", "abc"),
                RawBidMalformedUid("BidTakeoffs", "9", "ParentUID", "-4"),
                RawBidMalformedUid("BidTakeoffs", "10", "ParentUID", "1.5"),
            ),
        )
        self.assertEqual(resolution.missing_parent_roots, ())
        self.assertEqual(raw_data.page_tables["BidTakeoffs"], rows)

    def test_parent_cycles_are_fatal_sorted_and_prevent_pruning(self):
        raw_data = _takeoff_raw_data(
            _takeoff("9", parent="10"),
            _takeoff("10", parent="9"),
            _takeoff("2", parent="2"),
            _takeoff("3", parent="99"),
            _takeoff("4", parent="9"),
        )
        rows = list(raw_data.page_tables["BidTakeoffs"])
        resolution = resolve_takeoff_graph(raw_data)
        self.assertEqual(
            resolution.fatal_issues,
            (
                RawBidParentCycle("BidTakeoffs", "10"),
                RawBidParentCycle("BidTakeoffs", "2"),
                RawBidParentCycle("BidTakeoffs", "9"),
            ),
        )
        self.assertEqual(resolution.missing_parent_roots, ())
        self.assertEqual(resolution.dependent_descendants, ())
        self.assertEqual(raw_data.page_tables["BidTakeoffs"], rows)

    def test_missing_parent_prunes_the_row_and_all_descendants_breadth_first(self):
        rows = [
            _takeoff("20", parent="0"),
            _takeoff("9", parent="8"),
            _takeoff("8", parent="7"),
            _takeoff("7", parent="99"),
            _takeoff("12", parent="11"),
            _takeoff("11", parent="7"),
            _takeoff("21", parent="20"),
        ]
        raw_data = _takeoff_raw_data(*rows)
        resolution = resolve_takeoff_graph(raw_data)
        self.assertEqual(resolution.fatal_issues, ())
        self.assertEqual(resolution.missing_parent_roots, (_graph_issue("7", "99"),))
        self.assertEqual(
            resolution.dependent_descendants,
            (
                _graph_issue("8", "7"),
                _graph_issue("11", "7"),
                _graph_issue("9", "8"),
                _graph_issue("12", "11"),
            ),
        )
        self.assertEqual(resolution.skipped_count, 5)
        self.assertEqual(
            raw_data.page_tables["BidTakeoffs"], [rows[0], rows[6]]
        )
        self.assertIs(raw_data.page_tables["BidTakeoffs"][0], rows[0])

    def test_each_missing_parent_root_is_reported_in_row_order(self):
        raw_data = _takeoff_raw_data(
            _takeoff("30", parent="98"),
            _takeoff("31", parent="30"),
            _takeoff("10", parent="97"),
            _takeoff("11", parent="0"),
        )
        resolution = resolve_takeoff_graph(raw_data)
        self.assertEqual(
            resolution.missing_parent_roots,
            (_graph_issue("30", "98"), _graph_issue("10", "97")),
        )
        self.assertEqual(resolution.dependent_descendants, (_graph_issue("31", "30"),))
        self.assertEqual(
            [row["UID"] for row in raw_data.page_tables["BidTakeoffs"]], ["11"]
        )

    def test_pruning_everything_leaves_an_empty_list_rather_than_a_missing_key(self):
        raw_data = _takeoff_raw_data(_takeoff("7", parent="99"))
        resolution = resolve_takeoff_graph(raw_data)
        self.assertEqual(resolution.skipped_count, 1)
        self.assertEqual(raw_data.page_tables["BidTakeoffs"], [])

    def test_integer_uid_values_are_compared_as_text(self):
        rows = [
            {"UID": 7, "ParentUID": 99},
            {"UID": 8, "ParentUID": 7},
            {"UID": 9, "ParentUID": 0},
        ]
        raw_data = RawBidData(page_tables={"BidTakeoffs": list(rows)})
        resolution = resolve_takeoff_graph(raw_data)
        self.assertEqual(
            resolution.missing_parent_roots, (_graph_issue("7", "99"),)
        )
        self.assertEqual(resolution.dependent_descendants, (_graph_issue("8", "7"),))
        self.assertEqual(raw_data.page_tables["BidTakeoffs"], [rows[2]])

    def test_uid_validity_rule_requires_ascii_decimal_greater_than_zero(self):
        for uid, valid in (
            ("1", True),
            ("10", True),
            ("0", False),
            ("00", False),
            ("-1", False),
            ("+1", False),
            ("١", False),
            ("1_0", False),
            ("", False),
        ):
            with self.subTest(uid=uid):
                raw_data = RawBidData(page_tables={"BidTakeoffs": [{"UID": uid}]})
                resolution = resolve_takeoff_graph(raw_data)
                self.assertEqual(resolution.fatal_issues == (), valid)


class ClearMissingReferenceTests(unittest.TestCase):
    def _settings_data(self, *selected, pages=("20",)):
        return RawBidData(
            bid_tables={
                "BidPages": [{"UID": page, "BidUID": "1"} for page in pages],
                "BidSettings": [
                    {"UID": str(10 + index), "BidUID": "1", "BidPageSelectedUID": value}
                    for index, value in enumerate(selected)
                ],
            }
        )

    def test_dangling_selected_page_is_reported_and_reset_to_zero(self):
        raw_data = self._settings_data("99", "20", "88")
        cleared = clear_missing_selected_page_references(raw_data)
        self.assertEqual(
            cleared,
            [
                RawBidIntegrityIssue(
                    "BidSettings", "10", "BidPageSelectedUID", "99", "BidPages"
                ),
                RawBidIntegrityIssue(
                    "BidSettings", "12", "BidPageSelectedUID", "88", "BidPages"
                ),
            ],
        )
        self.assertEqual(
            [r["BidPageSelectedUID"] for r in raw_data.bid_tables["BidSettings"]],
            ["0", "20", "0"],
        )

    def test_null_present_and_non_decimal_selections_are_left_alone(self):
        values = ("", "0", "NULL", "20", "abc", "-5", "2.5")
        raw_data = self._settings_data(*values)
        self.assertEqual(clear_missing_selected_page_references(raw_data), [])
        self.assertEqual(
            [r["BidPageSelectedUID"] for r in raw_data.bid_tables["BidSettings"]],
            list(values),
        )

    def test_missing_selected_key_is_not_added(self):
        raw_data = RawBidData(
            bid_tables={"BidSettings": [{"UID": "10", "BidUID": "1"}]}
        )
        self.assertEqual(clear_missing_selected_page_references(raw_data), [])
        self.assertEqual(
            raw_data.bid_tables["BidSettings"], [{"UID": "10", "BidUID": "1"}]
        )

    def test_selection_clears_when_no_pages_exist_and_blank_page_uids_do_not_count(
        self,
    ):
        raw_data = self._settings_data("5", pages=())
        self.assertEqual(len(clear_missing_selected_page_references(raw_data)), 1)
        blank_pages = self._settings_data("7", pages=("", "0", "NULL"))
        self.assertEqual(len(clear_missing_selected_page_references(blank_pages)), 1)
        no_tables = RawBidData()
        self.assertEqual(clear_missing_selected_page_references(no_tables), [])

    def test_pages_are_read_from_bid_tables_only(self):
        raw_data = self._settings_data("30", pages=())
        raw_data.page_tables["BidPages"] = [{"UID": "30"}]
        self.assertEqual(len(clear_missing_selected_page_references(raw_data)), 1)

    def test_integer_selection_values_are_compared_as_text_and_rewritten_as_text(self):
        raw_data = self._settings_data(99, 20)
        cleared = clear_missing_selected_page_references(raw_data)
        self.assertEqual([c.missing_uid for c in cleared], ["99"])
        self.assertEqual(
            [r["BidPageSelectedUID"] for r in raw_data.bid_tables["BidSettings"]],
            ["0", 20],
        )

    def test_row_without_uid_reports_a_blank_row_uid(self):
        raw_data = RawBidData(
            bid_tables={"BidSettings": [{"BidPageSelectedUID": "9"}]}
        )
        cleared = clear_missing_selected_page_references(raw_data)
        self.assertEqual(cleared[0].row_uid, "")
        self.assertEqual(
            cleared[0].format(),
            "BidSettings.UID=<no UID> BidPageSelectedUID=9 missing BidPages.UID",
        )


class ClearMissingAnnotationTakeoffReferenceTests(unittest.TestCase):
    def test_dangling_takeoff_endpoints_are_reported_per_table_and_zeroed(self):
        raw_data = RawBidData(
            page_tables={
                "BidTakeoffs": [{"UID": "7"}, {"UID": "8"}],
                "BidALines": [
                    {"UID": "1", "BidTakeoffFromUID": "7", "BidTakeoffToUID": "50"}
                ],
                "BidDimensions": [
                    {"UID": "2", "BidTakeoffFromUID": "51", "BidTakeoffToUID": "8"},
                    {"UID": "3", "BidTakeoffFromUID": "52", "BidTakeoffToUID": "53"},
                ],
                "BidArrows": [
                    {"UID": "4", "BidTakeoffFromUID": "7", "BidTakeoffToUID": "8"}
                ],
            }
        )
        cleared = clear_missing_annotation_takeoff_references(raw_data)
        self.assertEqual(
            [(c.table, c.row_uid, c.column, c.missing_uid) for c in cleared],
            [
                ("BidDimensions", "2", "BidTakeoffFromUID", "51"),
                ("BidDimensions", "3", "BidTakeoffFromUID", "52"),
                ("BidDimensions", "3", "BidTakeoffToUID", "53"),
                ("BidALines", "1", "BidTakeoffToUID", "50"),
            ],
        )
        self.assertTrue(all(c.parent_table == "BidTakeoffs" for c in cleared))
        self.assertEqual(
            raw_data.page_tables["BidDimensions"],
            [
                {"UID": "2", "BidTakeoffFromUID": "0", "BidTakeoffToUID": "8"},
                {"UID": "3", "BidTakeoffFromUID": "0", "BidTakeoffToUID": "0"},
            ],
        )
        self.assertEqual(
            raw_data.page_tables["BidALines"],
            [{"UID": "1", "BidTakeoffFromUID": "7", "BidTakeoffToUID": "0"}],
        )
        self.assertEqual(
            raw_data.page_tables["BidArrows"],
            [{"UID": "4", "BidTakeoffFromUID": "7", "BidTakeoffToUID": "8"}],
        )

    def test_null_present_non_decimal_and_other_table_values_are_left_alone(self):
        endpoints = ("", "0", "NULL", "7", "abc", "-3", "4.5")
        rows = [
            {"UID": str(n), "BidTakeoffFromUID": value, "BidTakeoffToUID": value}
            for n, value in enumerate(endpoints)
        ]
        raw_data = RawBidData(
            page_tables={
                "BidTakeoffs": [{"UID": "7"}],
                "BidArrows": [dict(row) for row in rows],
                "BidTexts": [{"UID": "1", "BidTakeoffFromUID": "99"}],
            }
        )
        self.assertEqual(clear_missing_annotation_takeoff_references(raw_data), [])
        self.assertEqual(raw_data.page_tables["BidArrows"], rows)
        self.assertEqual(
            raw_data.page_tables["BidTexts"], [{"UID": "1", "BidTakeoffFromUID": "99"}]
        )

    def test_absent_columns_and_empty_bundles_are_ignored(self):
        raw_data = RawBidData(
            page_tables={"BidDimensions": [{"UID": "1"}], "BidArrows": []}
        )
        self.assertEqual(clear_missing_annotation_takeoff_references(raw_data), [])
        self.assertEqual(raw_data.page_tables["BidDimensions"], [{"UID": "1"}])
        self.assertEqual(clear_missing_annotation_takeoff_references(RawBidData()), [])

    def test_takeoffs_are_read_from_page_tables_and_row_without_uid_formats_blank(self):
        raw_data = RawBidData(
            bid_tables={"BidTakeoffs": [{"UID": "50"}]},
            page_tables={"BidArrows": [{"BidTakeoffFromUID": "50"}]},
        )
        cleared = clear_missing_annotation_takeoff_references(raw_data)
        self.assertEqual(
            [c.format() for c in cleared],
            ["BidArrows.UID=<no UID> BidTakeoffFromUID=50 missing BidTakeoffs.UID"],
        )

    def test_integer_endpoint_values_are_compared_as_text(self):
        raw_data = RawBidData(
            page_tables={
                "BidTakeoffs": [{"UID": 7}],
                "BidArrows": [
                    {"UID": 1, "BidTakeoffFromUID": 7, "BidTakeoffToUID": 8}
                ],
            }
        )
        cleared = clear_missing_annotation_takeoff_references(raw_data)
        self.assertEqual([c.missing_uid for c in cleared], ["8"])
        self.assertEqual(
            raw_data.page_tables["BidArrows"],
            [{"UID": 1, "BidTakeoffFromUID": 7, "BidTakeoffToUID": "0"}],
        )


class PrepareExportTests(unittest.TestCase):
    def _bundle(self):
        return RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidConditions": [{"UID": "5", "BidUID": "1"}],
                "BidPages": [
                    {"UID": "3", "BidUID": "1"},
                    {"UID": "4", "BidUID": "1", "BidPageFolderUID": "99"},
                ],
                "BidSettings": [
                    {"UID": "10", "BidUID": "1", "BidPageSelectedUID": "4"}
                ],
            },
            page_tables={},
            global_tables={},
        )

    def test_valid_bundle_is_returned_as_an_equal_independent_clone(self):
        raw_data = _takeoff_raw_data(
            _takeoff("7"), _takeoff("8", parent="7"), pages=("3",)
        )
        prepared = prepare_raw_bid_data_for_export(raw_data)
        self.assertEqual(prepared, raw_data)
        self.assertIsNot(prepared, raw_data)
        self.assertIsNot(prepared.bid_row, raw_data.bid_row)
        self.assertIsNot(
            prepared.page_tables["BidTakeoffs"][0],
            raw_data.page_tables["BidTakeoffs"][0],
        )

    def test_rows_with_dangling_non_clearable_references_are_dropped_not_kept(self):
        raw_data = self._bundle()
        prepared = prepare_raw_bid_data_for_export(raw_data)
        self.assertEqual(
            [row["UID"] for row in prepared.bid_tables["BidPages"]], ["3"]
        )
        self.assertEqual(
            [row["UID"] for row in raw_data.bid_tables["BidPages"]], ["3", "4"]
        )

    def test_selected_page_pointing_at_a_pruned_page_is_cleared_after_the_prune(self):
        prepared = prepare_raw_bid_data_for_export(self._bundle())
        self.assertEqual(
            prepared.bid_tables["BidSettings"],
            [{"UID": "10", "BidUID": "1", "BidPageSelectedUID": "0"}],
        )
        self.assertEqual(validate_raw_bid_integrity(prepared), [])

    def test_missing_selected_page_is_cleared_for_every_non_null_spelling(self):
        for value in ("99", "abc", "-1", "2.5"):
            with self.subTest(value=value):
                raw_data = RawBidData(
                    bid_row={"UID": "1"},
                    bid_tables={
                        "BidPages": [{"UID": "3", "BidUID": "1"}],
                        "BidSettings": [
                            {"UID": "10", "BidUID": "1", "BidPageSelectedUID": value},
                            {"UID": "11", "BidUID": "1", "BidPageSelectedUID": "3"},
                            {"UID": "12", "BidUID": "1", "BidPageSelectedUID": "NULL"},
                            {"UID": "13", "BidUID": "1", "BidPageSelectedUID": ""},
                        ],
                    },
                )
                prepared = prepare_raw_bid_data_for_export(raw_data)
                self.assertEqual(
                    [r["BidPageSelectedUID"] for r in prepared.bid_tables["BidSettings"]],
                    ["0", "3", "NULL", ""],
                )

    def test_pruning_cascades_through_hierarchy_children(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidAreas": [
                    {"UID": "2", "BidUID": "1", "ParentUID": "0"},
                    {"UID": "3", "BidUID": "1", "ParentUID": "99"},
                    {"UID": "4", "BidUID": "1", "ParentUID": "3"},
                    {"UID": "5", "BidUID": "1", "ParentUID": "4"},
                    {"UID": "6", "BidUID": "1", "ParentUID": "2"},
                ],
            },
        )
        prepared = prepare_raw_bid_data_for_export(raw_data)
        self.assertEqual(
            [row["UID"] for row in prepared.bid_tables["BidAreas"]], ["2", "6"]
        )
        self.assertEqual(validate_raw_bid_integrity(prepared), [])

    def test_pruned_takeoff_cascades_into_annotations_that_reference_it(self):
        raw_data = _takeoff_raw_data(
            _takeoff("7", page="4"),
            _takeoff("8", page="3"),
            pages=("3",),
        )
        raw_data.page_tables["BidDimensions"] = [
            {
                "UID": "20",
                "BidUID": "1",
                "BidPageUID": "3",
                "BidTakeoffFromUID": "7",
                "BidTakeoffToUID": "0",
            },
            {
                "UID": "21",
                "BidUID": "1",
                "BidPageUID": "3",
                "BidTakeoffFromUID": "8",
                "BidTakeoffToUID": "0",
            },
        ]
        prepared = prepare_raw_bid_data_for_export(raw_data)
        self.assertEqual(
            [row["UID"] for row in prepared.page_tables["BidTakeoffs"]], ["8"]
        )
        self.assertEqual(
            [row["UID"] for row in prepared.page_tables["BidDimensions"]], ["21"]
        )
        self.assertEqual(validate_raw_bid_integrity(prepared), [])

    def test_takeoffs_with_missing_parents_are_pruned_with_descendants_and_dependents(
        self,
    ):
        raw_data = _takeoff_raw_data(
            _takeoff("7", parent="99"),
            _takeoff("8", parent="7"),
            _takeoff("9", parent="0"),
        )
        raw_data.page_tables["BidArrows"] = [
            {
                "UID": "30",
                "BidUID": "1",
                "BidPageUID": "3",
                "BidTakeoffFromUID": "8",
                "BidTakeoffToUID": "9",
            },
            {
                "UID": "31",
                "BidUID": "1",
                "BidPageUID": "3",
                "BidTakeoffFromUID": "9",
                "BidTakeoffToUID": "0",
            },
        ]
        prepared = prepare_raw_bid_data_for_export(raw_data)
        self.assertEqual(
            [row["UID"] for row in prepared.page_tables["BidTakeoffs"]], ["9"]
        )
        self.assertEqual(
            [row["UID"] for row in prepared.page_tables["BidArrows"]], ["31"]
        )
        self.assertEqual(len(raw_data.page_tables["BidTakeoffs"]), 3)
        self.assertEqual(validate_raw_bid_integrity(prepared), [])

    def test_global_tables_and_references_to_global_parents_are_never_pruned(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidEmployees": [
                    {"UID": "2", "BidUID": "1", "EmployeeUID": "77", "PayClassUID": "78"}
                ],
            },
            global_tables={
                "Employees": [{"UID": "50", "PayClassUID": "99", "AccessLevelUID": "98"}],
            },
        )
        prepared = prepare_raw_bid_data_for_export(raw_data)
        self.assertEqual(prepared, raw_data)

    def test_unknown_tables_are_passed_through_unchanged(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={"Custom": [{"UID": "2", "BidUID": "99", "BidPageUID": "88"}]},
            page_tables={"Mystery": [{"UID": "3", "BidUID": "99"}]},
        )
        prepared = prepare_raw_bid_data_for_export(raw_data)
        self.assertEqual(prepared, raw_data)

    def test_rows_with_a_wrong_bid_uid_are_dropped(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidLayers": [
                    {"UID": "2", "BidUID": "1"},
                    {"UID": "3", "BidUID": "9"},
                    {"UID": "4"},
                ]
            },
        )
        prepared = prepare_raw_bid_data_for_export(raw_data)
        self.assertEqual(
            [row["UID"] for row in prepared.bid_tables["BidLayers"]], ["2", "4"]
        )

    def test_input_bundle_is_not_mutated_by_any_phase(self):
        raw_data = _takeoff_raw_data(
            _takeoff("7", parent="99"), _takeoff("8", parent="7"), pages=("3",)
        )
        raw_data.bid_tables["BidSettings"] = [
            {"UID": "10", "BidUID": "1", "BidPageSelectedUID": "55"}
        ]
        snapshot = clone_raw_bid_data(raw_data)
        prepare_raw_bid_data_for_export(raw_data)
        self.assertEqual(raw_data, snapshot)

    def test_invalid_takeoff_graph_failure_lists_the_first_ten_issues_and_a_count(self):
        raw_data = _takeoff_raw_data(
            *[_takeoff(str(n), parent=str(n % 11 + 1)) for n in range(1, 12)]
        )
        with self.assertRaises(ValueError) as caught:
            prepare_raw_bid_data_for_export(raw_data)
        message = str(caught.exception)
        ids = sorted((str(n) for n in range(1, 12)))
        expected = "; ".join(
            f"BidTakeoffs.UID={uid} participates in a ParentUID cycle"
            for uid in ids[:10]
        )
        self.assertEqual(
            message,
            f"Cannot export invalid takeoff graph: {expected}; +1 more",
        )

    def test_duplicate_and_malformed_takeoff_uids_abort_the_export(self):
        duplicate = _takeoff_raw_data(_takeoff("7"), _takeoff("7"))
        with self.assertRaisesRegex(
            ValueError,
            r"^Cannot export invalid takeoff graph: "
            r"BidTakeoffs\.UID=7 occurs 2 times$",
        ):
            prepare_raw_bid_data_for_export(duplicate)
        malformed = _takeoff_raw_data(_takeoff("7", parent="abc"))
        with self.assertRaisesRegex(
            ValueError,
            r"^Cannot export invalid takeoff graph: "
            r"BidTakeoffs\.UID=7 has malformed ParentUID=abc$",
        ):
            prepare_raw_bid_data_for_export(malformed)


_AUTHORITATIVE_TABLES = (
    "Bids",
    "BidAreas",
    "BidTypAreas",
    "BidConditionFolders",
    "BidPageFolders",
    "BidLayers",
    "BidConditions",
    "BidZones",
    "BidPages",
    "BidAnnotationClouds",
    "BidAnnotationOvals",
    "BidAnnotationPolygons",
    "BidAnnotationRects",
    "BidAnnoInk",
    "BidALines",
    "BidDimensions",
    "BidArrows",
    "BidTexts",
    "BidHighlights",
    "BidNamedViews",
    "BidHotLinks",
    "BidCallOuts",
    "BidComments",
)
_NON_AUTHORITATIVE_TABLES = (
    "BidPlanRooms",
    "BidSettings",
    "BidEmployees",
    "BidTypAreaCounts",
    "UserMasterConditions",
    "BidConditionUser",
    "BidTypGroupViews",
    "OCRProps",
    "BidTakeoffs",
    "BidLegends",
    "BidPageSettings",
    "BidAreaTranslations",
    "BidMarkedPages",
    "Employees",
    "PayClasses",
    "AccessLevels",
    "CdnTypes",
    "JobStatuses",
)


class AuthoritativeUidScopeTests(unittest.TestCase):
    def test_exactly_the_bid_owned_entity_tables_have_strict_uid_validation(self):
        for table in _AUTHORITATIVE_TABLES:
            with self.subTest(strict=table):
                raw_data = RawBidData()
                _add_row(raw_data, table, {"UID": "0"})
                issues = validate_raw_bid_integrity(raw_data, relationships=())
                self.assertEqual(
                    issues, [RawBidMalformedUid(table, "0", "UID", "0")]
                )
                if table == "Bids":
                    continue
                padded = RawBidData()
                _add_row(padded, table, {"UID": "5"})
                _add_row(padded, table, {"UID": "05"})
                self.assertEqual(
                    validate_raw_bid_integrity(padded, relationships=()),
                    [RawBidDuplicateUid(table, "5", 2)],
                )
        self.assertEqual(len(_AUTHORITATIVE_TABLES), 23)

    def test_other_tables_do_not_report_zero_or_padded_uids(self):
        for table in _NON_AUTHORITATIVE_TABLES:
            with self.subTest(lenient=table):
                raw_data = RawBidData()
                _add_row(raw_data, table, {"UID": "0"})
                _add_row(raw_data, table, {"UID": "5"})
                _add_row(raw_data, table, {"UID": "05"})
                self.assertEqual(
                    validate_raw_bid_integrity(raw_data, relationships=()), []
                )


class FrozenIssueRecordTests(unittest.TestCase):
    def test_every_issue_and_catalog_record_is_frozen(self):
        records = (
            RawBidRelationship("A", "b", "C"),
            RawBidIntegrityIssue("A", "1", "b", "2", "C"),
            RawBidDuplicateUid("A", "1", 2),
            RawBidMalformedUid("A", "1", "UID", "x"),
            RawBidParentCycle("A", "1"),
            RawBidTakeoffPageMismatch("A", "1"),
            RawBidCardinalityIssue("A", "B", "1", 2, 1),
            TakeoffGraphResolution(),
        )
        for record in records:
            with self.subTest(record=type(record).__name__):
                field = dataclasses.fields(record)[0].name
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    setattr(record, field, "changed")
                self.assertIsInstance(hash(record), int)


class MissingKeyDefaultTests(unittest.TestCase):
    """Rows lacking a key behave as blank, never as a literal sentinel value."""

    def test_hierarchy_cycle_check_treats_null_spellings_consistently(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidAreas": [
                    {"UID": "7", "BidUID": "1", "ParentUID": "NULL"},
                    {"UID": "NULL", "BidUID": "1", "ParentUID": "7"},
                ]
            },
        )
        self.assertEqual(
            [issue.format() for issue in validate_raw_bid_integrity(raw_data)],
            ["BidAreas.UID=NULL has malformed UID=NULL"],
        )

    def test_takeoff_without_uid_is_matched_to_its_parent_page_under_a_blank_uid(self):
        same_page = _takeoff_raw_data(
            _takeoff("7", parent="0", page="3"),
            {"BidUID": "1", "BidConditionUID": "5", "BidPageUID": "3", "ParentUID": "7"},
        )
        self.assertEqual(validate_raw_bid_integrity(same_page), [])
        other_page = _takeoff_raw_data(
            _takeoff("7", parent="0", page="3"),
            {"BidUID": "1", "BidConditionUID": "5", "BidPageUID": "4", "ParentUID": "7"},
            pages=("3", "4"),
        )
        self.assertEqual(
            [issue.format() for issue in validate_raw_bid_integrity(other_page)],
            ["BidTakeoffs.UID= has a parent on another Page"],
        )

    def test_takeoff_without_parent_column_is_a_root_even_if_a_takeoff_uid_is_xx(self):
        raw_data = _takeoff_raw_data(
            {"UID": "5", "BidUID": "1", "BidConditionUID": "5", "BidPageUID": "3"},
            _takeoff("XX", parent="0", page="4"),
            pages=("3", "4"),
        )
        self.assertEqual(validate_raw_bid_integrity(raw_data), [])

    def test_takeoff_without_page_column_does_not_match_a_page_named_xx(self):
        raw_data = _takeoff_raw_data(
            _takeoff("7", parent="0", page="XX"),
            {"UID": "8", "BidUID": "1", "BidConditionUID": "5", "ParentUID": "7"},
            pages=("XX",),
        )
        self.assertEqual(
            [issue.format() for issue in validate_raw_bid_integrity(raw_data)],
            [
                "BidPages.UID=XX has malformed UID=XX",
                "BidTakeoffs.UID=8 has a parent on another Page",
                "BidTakeoffs.UID=8 BidPageUID=<missing> missing BidPages.UID",
            ],
        )

    def test_settings_rows_without_an_owner_are_never_counted_as_one_owner(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidSettings": [{"UID": "10"}, {"UID": "11"}, {"UID": "12"}],
            },
        )
        self.assertEqual(validate_raw_bid_integrity(raw_data), [])

    def test_dangling_reference_on_a_row_without_uid_reports_a_blank_row_uid(self):
        relationships = (RawBidRelationship("BidPlanRooms", "BidPageUID", "BidPages"),)
        raw_data = RawBidData(bid_tables={"BidPlanRooms": [{"BidPageUID": "8"}]})
        issues = validate_raw_bid_integrity(raw_data, relationships)
        self.assertEqual(
            issues,
            [RawBidIntegrityIssue("BidPlanRooms", "", "BidPageUID", "8", "BidPages")],
        )

    def test_parent_rows_without_the_key_do_not_provide_a_blank_or_xx_target(self):
        relationships = (RawBidRelationship("BidAreas", "BidUID", "BidZones", "Code"),)
        raw_data = RawBidData(
            bid_tables={
                "BidAreas": [{"UID": "1", "BidUID": "XX"}],
                "BidZones": [{"UID": "2"}],
            }
        )
        self.assertEqual(
            [i.format() for i in validate_raw_bid_integrity(raw_data, relationships)],
            ["BidAreas.UID=1 BidUID=XX missing BidZones.UID"],
        )

    def test_reference_scan_continues_past_rows_that_lack_the_column(self):
        relationships = (RawBidRelationship("BidComments", "BidPageUID", "BidPages"),)
        raw_data = RawBidData(
            bid_tables={
                "BidComments": [
                    {"UID": "1"},
                    {"UID": "2", "BidPageUID": "0"},
                    {"UID": "3", "BidPageUID": "8"},
                ]
            }
        )
        self.assertEqual(
            _issue_tuples(validate_raw_bid_integrity(raw_data, relationships)),
            [("BidComments", "3", "BidPageUID", "8")],
        )

    def test_takeoff_resolution_scans_all_rows_after_a_malformed_one(self):
        raw_data = _takeoff_raw_data(
            _takeoff("x"), _takeoff("7"), _takeoff("7"), _takeoff("y")
        )
        resolution = resolve_takeoff_graph(raw_data)
        self.assertEqual(
            [issue.format() for issue in resolution.fatal_issues],
            [
                "BidTakeoffs.UID=x has malformed UID=x",
                "BidTakeoffs.UID=y has malformed UID=y",
                "BidTakeoffs.UID=7 occurs 2 times",
            ],
        )

    def test_takeoff_resolution_scans_all_rows_after_a_null_parent(self):
        raw_data = _takeoff_raw_data(
            _takeoff("7", parent="0"),
            _takeoff("8", parent=""),
            _takeoff("9", parent="99"),
            _takeoff("10", parent="abc"),
        )
        resolution = resolve_takeoff_graph(raw_data)
        self.assertEqual(
            resolution.fatal_issues,
            (RawBidMalformedUid("BidTakeoffs", "10", "ParentUID", "abc"),),
        )

    def test_export_clearing_does_not_add_a_selected_page_column(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={"BidSettings": [{"UID": "10", "BidUID": "1"}]},
        )
        prepared = prepare_raw_bid_data_for_export(raw_data)
        self.assertEqual(
            prepared.bid_tables["BidSettings"], [{"UID": "10", "BidUID": "1"}]
        )


class AnnotationEndpointColumnTests(unittest.TestCase):
    def test_each_annotation_table_checks_both_endpoint_columns(self):
        for table in ("BidDimensions", "BidArrows", "BidALines"):
            for column in ("BidTakeoffFromUID", "BidTakeoffToUID"):
                with self.subTest(table=table, column=column):
                    raw_data = RawBidData(
                        page_tables={
                            "BidTakeoffs": [{"UID": "7"}],
                            table: [{"UID": "1", column: "50"}],
                        }
                    )
                    cleared = clear_missing_annotation_takeoff_references(raw_data)
                    self.assertEqual(
                        cleared,
                        [RawBidIntegrityIssue(table, "1", column, "50", "BidTakeoffs")],
                    )
                    self.assertEqual(raw_data.page_tables[table][0][column], "0")


class ExportOrphanPruneContractTests(unittest.TestCase):
    """Direct contract of the private orphan pruner used by the export prepare."""

    def test_rows_without_any_relationship_are_returned_and_never_pruned(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "OCRProps": [{"UID": "2", "BidUID": "99"}],
                "UserMasterConditions": [{"UID": "3"}],
            },
        )
        self.assertIs(raw_bid_integrity._prune_export_orphans(raw_data), False)
        self.assertEqual(
            raw_data.bid_tables["OCRProps"], [{"UID": "2", "BidUID": "99"}]
        )
        self.assertEqual(raw_data.bid_tables["UserMasterConditions"], [{"UID": "3"}])

    def test_selected_page_and_takeoff_parent_references_are_not_orphan_pruned(self):
        raw_data = _takeoff_raw_data(_takeoff("8", parent="99"), pages=("3",))
        raw_data.bid_tables["BidSettings"] = [
            {"UID": "10", "BidUID": "1", "BidPageSelectedUID": "77"}
        ]
        self.assertIs(raw_bid_integrity._prune_export_orphans(raw_data), False)
        self.assertEqual(len(raw_data.bid_tables["BidSettings"]), 1)
        self.assertEqual(len(raw_data.page_tables["BidTakeoffs"]), 1)

    def test_prune_reports_true_for_bid_or_page_table_changes_and_false_otherwise(
        self,
    ):
        bid_only = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={"BidLayers": [{"UID": "2", "BidUID": "9"}]},
        )
        self.assertIs(raw_bid_integrity._prune_export_orphans(bid_only), True)
        self.assertEqual(bid_only.bid_tables["BidLayers"], [])
        self.assertIs(raw_bid_integrity._prune_export_orphans(bid_only), False)
        page_only = _takeoff_raw_data(_takeoff("7", page="99"))
        self.assertIs(raw_bid_integrity._prune_export_orphans(page_only), True)
        self.assertEqual(page_only.page_tables["BidTakeoffs"], [])
        self.assertIs(raw_bid_integrity._prune_export_orphans(page_only), False)

    def test_a_null_reference_does_not_stop_later_references_being_checked(self):
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidPages": [
                    {"UID": "3", "BidPageFolderUID": "99"},
                    {"UID": "4", "BidUID": "0", "BidPageFolderUID": "99"},
                    {"UID": "5", "BidUID": "1", "BidPageFolderUID": "0"},
                ]
            },
        )
        prepared = prepare_raw_bid_data_for_export(raw_data)
        self.assertEqual([row["UID"] for row in prepared.bid_tables["BidPages"]], ["5"])
