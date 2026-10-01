import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.application.dtos.condition_summary_dtos import (
    SUMMARY_NODE_CONDITION,
    SUMMARY_NODE_FOLDER,
    SUMMARY_NODE_ROOT,
    ConditionSummaryGrouping,
    ConditionSummaryNode,
    ConditionSummaryValues,
)
from ost_visualizer.application.dtos.export_dto import ExportErrorCode, ExportResultDto
from ost_visualizer.application.services.summary_csv_export_service import (
    SummaryCsvExportService,
)
from ost_visualizer.application.use_cases.project.condition_summary_service import (
    ConditionSummaryService,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.identity_refs import BidRef
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


class _ProjectData:
    def __init__(self, conditions, folders, takeoffs, pages):
        self.bid = Bid(uid="bid", name="Bid", measure_base=False)
        self.bid_ref = BidRef("db.mdb", "bid")
        self.conditions = conditions
        self.folders = folders
        self.takeoffs = takeoffs
        self.pages = pages

    def get_current_bid(self):
        return self.bid

    def get_current_bid_ref(self):
        return self.bid_ref

    def get_bid(self, ref):
        if ref != self.bid_ref:
            raise AssertionError("Summary read borrowed another Bid")
        return self.bid

    def get_bid_conditions(self):
        return self.conditions

    def get_bid_condition_folders(self):
        return self.folders

    def get_all_takeoffs(self):
        return self.takeoffs

    def get_all_pages(self):
        return self.pages


class _ProjectRead:
    def __init__(self, areas):
        self.areas = areas
        self.calls = []

    def get_bid_areas(self, file_path, bid_uid):
        self.calls.append((file_path, bid_uid))
        if (file_path, bid_uid) != ("db.mdb", "bid"):
            raise AssertionError("Summary read borrowed another database/Bid")
        return list(self.areas)


class SummaryCsvExportServiceTests(unittest.TestCase):
    def setUp(self):
        self.summary_service = ConditionSummaryService()
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
        self.project_data = _ProjectData(
            self.conditions, self.folders, self.takeoffs, self.pages
        )
        self.project_read = _ProjectRead(self.areas)
        self.csv_service = SummaryCsvExportService(
            self.project_data, self.project_read, self.summary_service
        )

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
        self.assertEqual([row[5] for row in rows], ["Cond A", "Cond B"])
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
            rows,
            [
                self._row(
                    page="",
                    group_label="Area Two",
                    type_name="Type A",
                    number="2",
                    name="Cond A",
                    height="12.00000",
                    notes="note a",
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
                [
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "Total",
                    "2",
                    "EA",
                    "0",
                    "SF",
                    "0",
                    "CY",
                    "note a",
                ],
            ],
        )

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
                        quantity1=1504.4,
                        uom1=UOM_EACH,
                        quantity2=37.6,
                        uom2=UOM_SQUARE_FEET,
                        quantity3=-0.6,
                        uom3=UOM_CUBIC_YARDS,
                    ),
                )
            ],
        )
        rows = self.csv_service.to_csv_rows(root, ConditionSummaryGrouping())
        self.assertEqual(rows[0][8:14], ["1504", "EA", "38", "SF", "-1", "CY"])
        self.assertEqual(rows[0][6], "6.25000")

    def test_area_only_places_unassigned_first_but_page_grouping_keeps_page_order(self):
        self.takeoffs[0].area_uid = "a1"
        self.takeoffs[1].area_uid = ""
        self.assertEqual(
            self._rows(ConditionSummaryGrouping(by_area=True)),
            [
                self._row(
                    page="",
                    group_label="(unassigned)",
                    type_name="Type A",
                    number="2",
                    name="Cond A",
                    height="12.00000",
                    area=None,
                    notes="note a",
                ),
                self._row(
                    page="",
                    group_label="Area One",
                    type_name="Type B",
                    number="1",
                    name="Cond B",
                    height="0",
                    area=None,
                    notes="note b",
                ),
            ],
        )
        self.assertEqual(
            self._rows(ConditionSummaryGrouping(by_page=True, by_area=True)),
            [
                self._row(
                    page="Z-First.pdf",
                    group_label="Area One",
                    type_name="Type B",
                    number="1",
                    name="Cond B",
                    height="0",
                    notes="note b",
                ),
                self._row(
                    page="A-Second.pdf",
                    group_label="(unassigned)",
                    type_name="Type A",
                    number="2",
                    name="Cond A",
                    height="12.00000",
                    notes="note a",
                ),
            ],
        )

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
        expected_rows = self._rows(ConditionSummaryGrouping())
        expected_text = "".join(
            ",".join('"' + cell.replace('"', '""') + '"' for cell in row) + "\r\n"
            for row in expected_rows
        )
        self.assertEqual(text, expected_text)
        self.assertEqual(list(csv.reader(io.StringIO(text))), expected_rows)

    def test_to_csv_text_preserves_quotes_in_condition_names(self):
        self.conditions["c1"].name = 'Cond "B"'
        self.conditions["c1"].notes = 'Notes, caf\u00e9\r\nSecond "line"'
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
        parsed = list(csv.reader(io.StringIO(text)))
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0][5], 'Cond "B"')
        self.assertEqual(parsed[0][-1], 'Notes, caf\u00e9\r\nSecond "line"')

    def test_export_current_summary_writes_selected_csv_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "summary.csv"
            result = self.csv_service.export_current_summary(
                ConditionSummaryGrouping(by_type=True),
                str(output),
            )
            self.assertEqual(
                result, ExportResultDto(True, page_count=1, format_name="Summary CSV")
            )
            with output.open(encoding="utf-8", newline="") as handle:
                self.assertEqual(
                    list(csv.reader(handle)),
                    self._rows(ConditionSummaryGrouping(by_type=True)),
                )
            self.assertEqual(self.project_read.calls, [("db.mdb", "bid")])

    def test_default_filename_uses_current_bid_with_empty_and_missing_fallback(self):
        self.project_data.bid.name = "Building One"
        self.assertEqual(
            self.csv_service.default_filename(), "Building One Summary.csv"
        )
        self.project_data.bid.name = ""
        self.assertEqual(self.csv_service.default_filename(), "Bid Summary.csv")
        self.project_data.bid = None
        self.assertEqual(self.csv_service.default_filename(), "Bid Summary.csv")
        self.assertEqual(self.project_read.calls, [])

    def test_no_data_does_not_create_or_overwrite_destination(self):
        for missing_bid in (False, True):
            with self.subTest(
                missing_bid=missing_bid
            ), tempfile.TemporaryDirectory() as temp_dir:
                self.takeoffs.clear()
                self.project_read.calls.clear()
                if missing_bid:
                    self.project_data.bid_ref = None
                output = Path(temp_dir) / "summary.csv"
                for existing in (False, True):
                    if existing:
                        output.write_bytes(b"preserve existing export")
                    result = self.csv_service.export_current_summary(
                        ConditionSummaryGrouping(), str(output)
                    )
                    self.assertEqual(
                        result,
                        ExportResultDto(
                            False,
                            format_name="Summary CSV",
                            error_message="No summary rows are available to export.",
                            error_code=ExportErrorCode.NO_DATA,
                        ),
                    )
                    if existing:
                        self.assertEqual(
                            output.read_bytes(), b"preserve existing export"
                        )
                    else:
                        self.assertFalse(output.exists())
                self.assertEqual(
                    self.project_read.calls,
                    [] if missing_bid else [("db.mdb", "bid")] * 2,
                )

    def test_nonempty_folder_without_export_rows_is_no_data(self):
        empty = ConditionSummaryNode(
            kind=SUMMARY_NODE_ROOT,
            children=[ConditionSummaryNode(kind=SUMMARY_NODE_FOLDER, label="Empty")],
        )
        with patch.object(self.summary_service, "build_summary", return_value=empty):
            with tempfile.TemporaryDirectory() as temp_dir:
                output = Path(temp_dir) / "empty.csv"
                result = self.csv_service.export_current_summary(
                    ConditionSummaryGrouping(), str(output)
                )
                self.assertEqual(
                    result,
                    ExportResultDto(
                        False,
                        format_name="Summary CSV",
                        error_message="No summary rows are available to export.",
                        error_code=ExportErrorCode.NO_DATA,
                    ),
                )
                self.assertFalse(output.exists())

    def test_destination_failure_is_reported_and_retry_writes_complete_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "missing" / "summary.csv"
            failed = self.csv_service.export_current_summary(
                ConditionSummaryGrouping(), str(output)
            )
            self.assertFalse(failed.success)
            self.assertEqual(failed.error_code, ExportErrorCode.WRITE_FAILED)
            self.assertEqual(failed.format_name, "Summary CSV")
            self.assertEqual(failed.page_count, 0)
            self.assertTrue(failed.error_message)
            self.assertFalse(output.exists())
            output.parent.mkdir()
            succeeded = self.csv_service.export_current_summary(
                ConditionSummaryGrouping(), str(output)
            )
            self.assertEqual(
                succeeded,
                ExportResultDto(True, page_count=1, format_name="Summary CSV"),
            )
            with output.open(encoding="utf-8", newline="") as handle:
                self.assertEqual(
                    list(csv.reader(handle)), self._rows(ConditionSummaryGrouping())
                )

    def test_invalid_quantity_returns_unexpected_without_overwriting_destination(self):
        invalid = ConditionSummaryNode(
            kind=SUMMARY_NODE_ROOT,
            children=[
                ConditionSummaryNode(
                    kind=SUMMARY_NODE_CONDITION,
                    values=ConditionSummaryValues(quantity1=float("nan")),
                )
            ],
        )
        with patch.object(self.summary_service, "build_summary", return_value=invalid):
            with tempfile.TemporaryDirectory() as temp_dir:
                output = Path(temp_dir) / "summary.csv"
                output.write_bytes(b"previous export")
                result = self.csv_service.export_current_summary(
                    ConditionSummaryGrouping(), str(output)
                )
                self.assertFalse(result.success)
                self.assertEqual(result.error_code, ExportErrorCode.UNEXPECTED)
                self.assertEqual(result.format_name, "Summary CSV")
                self.assertEqual(result.page_count, 0)
                self.assertTrue(result.error_message)
                self.assertEqual(output.read_bytes(), b"previous export")


if __name__ == "__main__":
    unittest.main()
