import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from ost_visualizer.application.dtos.condition_summary_dtos import (
    SUMMARY_NODE_CONDITION,
    SUMMARY_NODE_ROOT,
    ConditionSummaryGrouping,
    ConditionSummaryNode,
    ConditionSummaryValues,
)
from ost_visualizer.application.services.summary_csv_export_service import (
    SummaryCsvExportService,
)
from ost_visualizer.application.use_cases.project.condition_summary_service import (
    ConditionSummaryService,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.uom_service import (
    CALC_COUNT,
    UOM_CUBIC_YARDS,
    UOM_EACH,
    UOM_SQUARE_FEET,
)


class SummaryCsvExportServiceTests(unittest.TestCase):
    def setUp(self):
        self.summary_service = ConditionSummaryService()
        self.csv_service = SummaryCsvExportService(
            SimpleNamespace(),
            SimpleNamespace(),
            self.summary_service,
        )
        self.folders = {
            "building": BidConditionFolder(uid="building", name="BLDG"),
            "level": BidConditionFolder(
                uid="level", name="L1 FDN", parent_uid="building"
            ),
        }
        self.conditions = {
            "c1": self._condition(
                "c1",
                ref_no=1,
                name="Cond B",
                type_name="Type B",
                height=0.0,
                notes="note b",
            ),
            "c2": self._condition(
                "c2",
                ref_no=2,
                name="Cond A",
                type_name="Type A",
                height=12.0,
                notes="note a",
            ),
            "unused": self._condition(
                "unused",
                ref_no=3,
                name="Unused",
                type_name="Type A",
                height=24.0,
                notes="unused",
            ),
        }
        self.pages = [
            Page(uid="p1", name="Z-First.pdf", sequence=1),
            Page(uid="p2", name="A-Second.pdf", sequence=2),
        ]
        self.areas = [
            BidArea(
                uid="a1", bid_uid="bid", parent_uid="", name="Area One", sequence=1
            ),
            BidArea(
                uid="a2", bid_uid="bid", parent_uid="", name="Area Two", sequence=2
            ),
        ]
        self.takeoffs = [
            Takeoff(uid="t1", condition_uid="c1", page_uid="p1", area_uid="a2"),
            Takeoff(uid="t2", condition_uid="c2", page_uid="p2", area_uid="a1"),
        ]

    def _condition(self, uid, *, ref_no, name, type_name, height, notes):
        return Condition(
            uid=uid,
            name=name,
            condition_type=Condition.TYPE_COUNT,
            height=height,
            cdn_type_uid=f"type-{type_name}",
            cdn_type_name=type_name,
            folder_uid="level",
            uom1=UOM_EACH,
            calc_type1=CALC_COUNT,
            uom2=UOM_SQUARE_FEET,
            uom3=UOM_CUBIC_YARDS,
            ref_no=ref_no,
            notes=notes,
        )

    def _rows(self, grouping):
        root = self.summary_service.build_summary(
            conditions=self.conditions,
            folders=self.folders,
            takeoffs=self.takeoffs,
            pages=self.pages,
            areas=self.areas,
            project_name="Bid",
            grouping=grouping,
        )
        return self.csv_service.to_csv_rows(root, grouping)

    def _row(
        self,
        *,
        page,
        type_name,
        number,
        name,
        height,
        group_label="L1 FDN",
        area="(unassigned)",
        notes,
    ):
        cells = ["BLDG", page, group_label, type_name, number, name, height]
        if area is not None:
            cells.append(area)
        cells.extend(["1", "EA", "0", "SF", "0", "CY", notes])
        return cells

    def test_no_grouping_csv_matches_example_structure(self):
        self.assertEqual(
            self._rows(ConditionSummaryGrouping()),
            [
                self._row(
                    page="",
                    group_label="Area Two",
                    type_name="Type B",
                    number="1",
                    name="Cond B",
                    height="0",
                    notes="note b",
                ),
                self._row(
                    page="",
                    group_label="Area One",
                    type_name="Type A",
                    number="2",
                    name="Cond A",
                    height="12.00000",
                    notes="note a",
                ),
            ],
        )

    def test_group_by_area_csv_puts_area_before_type_without_page_grouping(self):
        self.assertEqual(
            self._rows(ConditionSummaryGrouping(by_area=True)),
            [
                self._row(
                    page="",
                    group_label="Area One",
                    type_name="Type A",
                    number="2",
                    name="Cond A",
                    height="12.00000",
                    area=None,
                    notes="note a",
                ),
                self._row(
                    page="",
                    group_label="Area Two",
                    type_name="Type B",
                    number="1",
                    name="Cond B",
                    height="0",
                    area=None,
                    notes="note b",
                ),
            ],
        )

    def test_group_by_type_csv_matches_example_structure(self):
        self.assertEqual(
            self._rows(ConditionSummaryGrouping(by_type=True)),
            [
                self._row(
                    page="",
                    group_label="Area One",
                    type_name="Type A",
                    number="2",
                    name="Cond A",
                    height="12.00000",
                    notes="note a",
                ),
                self._row(
                    page="",
                    group_label="Area Two",
                    type_name="Type B",
                    number="1",
                    name="Cond B",
                    height="0",
                    notes="note b",
                ),
            ],
        )

    def test_group_by_page_csv_matches_example_structure(self):
        self.assertEqual(
            self._rows(ConditionSummaryGrouping(by_page=True)),
            [
                self._row(
                    page="Z-First.pdf",
                    group_label="Area Two",
                    type_name="Type B",
                    number="1",
                    name="Cond B",
                    height="0",
                    notes="note b",
                ),
                self._row(
                    page="A-Second.pdf",
                    group_label="Area One",
                    type_name="Type A",
                    number="2",
                    name="Cond A",
                    height="12.00000",
                    notes="note a",
                ),
            ],
        )

    def test_group_by_type_area_csv_matches_example_structure(self):
        self.assertEqual(
            self._rows(ConditionSummaryGrouping(by_type=True, by_area=True)),
            [
                self._row(
                    page="",
                    group_label="Area One",
                    type_name="Type A",
                    number="2",
                    name="Cond A",
                    height="12.00000",
                    area=None,
                    notes="note a",
                ),
                self._row(
                    page="",
                    group_label="Area Two",
                    type_name="Type B",
                    number="1",
                    name="Cond B",
                    height="0",
                    area=None,
                    notes="note b",
                ),
            ],
        )

    def test_group_by_page_area_csv_includes_area_column_like_examples(self):
        self.assertEqual(
            self._rows(ConditionSummaryGrouping(by_page=True, by_area=True)),
            [
                self._row(
                    page="Z-First.pdf",
                    group_label="Area Two",
                    type_name="Type B",
                    number="1",
                    name="Cond B",
                    height="0",
                    notes="note b",
                ),
                self._row(
                    page="A-Second.pdf",
                    group_label="Area One",
                    type_name="Type A",
                    number="2",
                    name="Cond A",
                    height="12.00000",
                    notes="note a",
                ),
            ],
        )

    def test_group_by_page_type_csv_matches_example_type_first_order(self):
        rows = self._rows(ConditionSummaryGrouping(by_page=True, by_type=True))
        self.assertEqual(
            rows,
            [
                self._row(
                    page="A-Second.pdf",
                    group_label="Area One",
                    type_name="Type A",
                    number="2",
                    name="Cond A",
                    height="12.00000",
                    notes="note a",
                ),
                self._row(
                    page="Z-First.pdf",
                    group_label="Area Two",
                    type_name="Type B",
                    number="1",
                    name="Cond B",
                    height="0",
                    notes="note b",
                ),
            ],
        )

    def test_group_by_page_type_area_csv_matches_example_page_area_order(self):
        self.assertEqual(
            self._rows(
                ConditionSummaryGrouping(by_page=True, by_type=True, by_area=True)
            ),
            [
                self._row(
                    page="Z-First.pdf",
                    group_label="Area Two",
                    type_name="Type B",
                    number="1",
                    name="Cond B",
                    height="0",
                    notes="note b",
                ),
                self._row(
                    page="A-Second.pdf",
                    group_label="Area One",
                    type_name="Type A",
                    number="2",
                    name="Cond A",
                    height="12.00000",
                    notes="note a",
                ),
            ],
        )

    def test_conditions_without_placed_takeoffs_are_excluded(self):
        rows = self._rows(ConditionSummaryGrouping(by_type=True))
        self.assertNotIn("Unused", [cell for row in rows for cell in row])

    def test_multi_area_total_and_detail_rows_export(self):
        root = self.summary_service.build_summary(
            conditions={"c2": self.conditions["c2"]},
            folders=self.folders,
            takeoffs=[
                Takeoff(uid="t2", condition_uid="c2", page_uid="p1", area_uid="a1"),
                Takeoff(uid="t3", condition_uid="c2", page_uid="p1", area_uid="a2"),
            ],
            pages=self.pages,
            areas=self.areas,
            project_name="Bid",
            grouping=ConditionSummaryGrouping(),
        )
        rows = self.csv_service.to_csv_rows(root, ConditionSummaryGrouping())
        self.assertEqual(
            rows[0][2:10],
            [
                "Area Two",
                "Type A",
                "2",
                "Cond A",
                "12.00000",
                "(unassigned)",
                "1",
                "EA",
            ],
        )
        self.assertEqual(
            rows[1][2:10],
            [
                "Area One",
                "Type A",
                "2",
                "Cond A",
                "12.00000",
                "(unassigned)",
                "1",
                "EA",
            ],
        )
        self.assertEqual(rows[2][:8], ["", "", "", "", "", "", "", "Total"])
        self.assertEqual(rows[2][8:10], ["2", "EA"])

    def test_quantity_cells_use_summary_plain_number_format(self):
        root = ConditionSummaryNode(
            kind=SUMMARY_NODE_ROOT,
            children=[
                ConditionSummaryNode(
                    kind=SUMMARY_NODE_CONDITION,
                    values=ConditionSummaryValues(
                        number="4",
                        name="Cond D",
                        type_name="Type D",
                        height_inches=6.25,
                        area="Area One",
                        quantity1=504.0,
                        uom1=UOM_EACH,
                        quantity2=37.0,
                        uom2=UOM_SQUARE_FEET,
                        quantity3=0.0,
                        uom3=UOM_CUBIC_YARDS,
                    ),
                )
            ],
        )
        rows = self.csv_service.to_csv_rows(root, ConditionSummaryGrouping())
        self.assertEqual(rows[0][8:14], ["504", "EA", "37", "SF", "0", "CY"])
        self.assertEqual(rows[0][6], "6.25000")

    def test_to_csv_text_has_no_header_and_quotes_all_cells(self):
        text = self.csv_service.to_csv_text(
            self.summary_service.build_summary(
                conditions=self.conditions,
                folders=self.folders,
                takeoffs=self.takeoffs,
                pages=self.pages,
                areas=self.areas,
                project_name="Bid",
                grouping=ConditionSummaryGrouping(),
            ),
            ConditionSummaryGrouping(),
        )
        self.assertTrue(text.startswith('"BLDG",""'))
        parsed = list(csv.reader(text.splitlines()))
        self.assertEqual(parsed[0][3], "Type B")

    def test_to_csv_text_preserves_quotes_in_condition_names(self):
        self.conditions["c1"].name = 'Cond "B"'
        text = self.csv_service.to_csv_text(
            self.summary_service.build_summary(
                conditions=self.conditions,
                folders=self.folders,
                takeoffs=self.takeoffs,
                pages=self.pages,
                areas=self.areas,
                project_name="Bid",
                grouping=ConditionSummaryGrouping(),
            ),
            ConditionSummaryGrouping(),
        )
        parsed = list(csv.reader(text.splitlines()))
        self.assertEqual(parsed[0][5], 'Cond "B"')

    def test_export_current_summary_writes_selected_csv_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "summary.csv"
            service = SummaryCsvExportService(
                SimpleNamespace(
                    get_current_bid_ref=lambda: SimpleNamespace(
                        file_path="db.mdb", bid_uid="bid"
                    ),
                    get_bid=lambda _ref: SimpleNamespace(
                        name="Bid", measure_base=False
                    ),
                    get_bid_conditions=lambda: self.conditions,
                    get_bid_condition_folders=lambda: self.folders,
                    get_all_takeoffs=lambda: self.takeoffs,
                    get_all_pages=lambda: self.pages,
                ),
                SimpleNamespace(get_bid_areas=lambda _file, _bid: self.areas),
                self.summary_service,
            )
            result = service.export_current_summary(
                ConditionSummaryGrouping(by_type=True),
                str(output),
            )
            self.assertTrue(result.success)
            self.assertTrue(output.exists())
            self.assertIn('"Type A"', output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
