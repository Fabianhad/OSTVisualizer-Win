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
                self.assertTrue(
                    any(
                        issue.table == table and "ParentUID cycle" in issue.format()
                        for issue in issues
                    ),
                    issues,
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
        self.assertTrue(
            any(
                issue.format()
                == "BidSettings has 2 rows for Bids.UID=1; expected at most 1"
                for issue in issues
            ),
            issues,
        )

    def test_prepare_export_prunes_named_views_and_hotlinks_for_missing_pages(self):
        prepared = prepare_raw_bid_data_for_export(
            _import_export_support__orphan_named_view_hotlink_raw_data()
        )
        self.assertEqual(
            [row["Name"] for row in prepared.bid_tables["BidNamedViews"]],
            ["Valid"],
        )
        self.assertEqual(
            [row["Name"] for row in prepared.bid_tables["BidHotLinks"]],
            ["Valid Link"],
        )
        self.assertEqual(validate_raw_bid_integrity(prepared), [])


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
        self.assertTrue(
            any("Page" in issue.format() and "8" in issue.format() for issue in issues),
            issues,
        )
