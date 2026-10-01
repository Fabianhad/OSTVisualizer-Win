import unittest
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.infrastructure.mdb.raw_bid_integrity import (
    RAW_BID_RELATIONSHIPS,
    prepare_raw_bid_data_for_export,
    validate_raw_bid_integrity,
)
from ost_visualizer.infrastructure.mdb.schema_contract import (
    BID_SECTIONS,
    BID_TAIL_SECTIONS,
    GLOBAL_SECTIONS,
    PAGE_SECTIONS,
)
from tests.helpers.mdb.import_export_support import (
    _orphan_named_view_hotlink_raw_data as _import_export_support__orphan_named_view_hotlink_raw_data,
    _raw_data_with_row as _import_export_support__raw_data_with_row,
)
from ost_visualizer.infrastructure.mdb.raw_bid_integrity import (
    validate_raw_bid_integrity,
)


class RawBidIntegrityRelationshipTests(unittest.TestCase):
    def test_raw_bid_integrity_map_reports_each_declared_relationship(self):
        self.assertGreater(len(RAW_BID_RELATIONSHIPS), 90)
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
