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


class SummaryCsvDropElevationTests(unittest.TestCase):
    NAME_CELL = 5

    def setUp(self):
        self.summary_service = ConditionSummaryService()
        self.folders = {
            "level": BidConditionFolder(uid="level", name="Level @T 9' 0\""),
        }
        self.conditions = {
            "c1": self._condition("c1", 1, "Wall @T 5' 0\""),
            "c2": self._condition("c2", 2, "Wall @B 2&apos; 0&quot;"),
            "c3": self._condition("c3", 3, "Slab @T 1' 0\""),
            "c4": self._condition("c4", 4, "Plain"),
            "c5": self._condition("c5", 5, "Meeting @T later"),
        }
        self.pages = [Page(uid="p1", name="Page 1", sequence=1)]
        self.areas = [
            BidArea(uid="a1", bid_uid="bid", parent_uid="", name="Area", sequence=1)
        ]
        self.takeoffs = [
            Takeoff(uid=f"t{index}", condition_uid=uid, page_uid="p1", area_uid="a1")
            for index, uid in enumerate(self.conditions, start=1)
        ]
        self.project_data = _ProjectData(
            self.conditions, self.folders, self.takeoffs, self.pages
        )
        self.csv_service = SummaryCsvExportService(
            self.project_data, _ProjectRead(self.areas), self.summary_service
        )
        self.original = {
            uid: (condition.name, condition.z_value, condition.is_top)
            for uid, condition in self.conditions.items()
        }

    @staticmethod
    def _condition(uid, ref_no, name):
        return Condition(
            uid=uid,
            name=name,
            condition_type=Condition.TYPE_COUNT,
            cdn_type_uid="type",
            cdn_type_name="Type",
            folder_uid="level",
            uom1=UOM_EACH,
            calc_type1=CALC_COUNT,
            uom2=UOM_SQUARE_FEET,
            uom3=UOM_CUBIC_YARDS,
            ref_no=ref_no,
            z_value=60.0,
            is_top=True,
        )

    def _write(self, grouping, **options):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "summary.csv"
            result = self.csv_service.export_current_summary(
                grouping, str(output), **options
            )
            with output.open(encoding="utf-8", newline="") as handle:
                return result, list(csv.reader(handle))

    def _names(self, rows):
        return [row[self.NAME_CELL] for row in rows]

    def test_default_keeps_every_name_exactly_as_stored(self):
        result, rows = self._write(ConditionSummaryGrouping())
        self.assertTrue(result.success)
        self.assertEqual(
            sorted(self._names(rows)),
            sorted(condition.name for condition in self.conditions.values()),
        )
        self.assertEqual(result.elevation_name_collisions, ())

    def test_option_off_explicitly_matches_the_default(self):
        _, default_rows = self._write(ConditionSummaryGrouping())
        _, off_rows = self._write(
            ConditionSummaryGrouping(), strip_condition_elevations=False
        )
        self.assertEqual(default_rows, off_rows)

    def test_option_on_writes_names_without_elevations(self):
        result, rows = self._write(
            ConditionSummaryGrouping(), strip_condition_elevations=True
        )
        self.assertTrue(result.success)
        self.assertEqual(
            sorted(self._names(rows)),
            ["Meeting @T later", "Plain", "Slab", "Wall", "Wall"],
        )

    def test_every_other_cell_is_unchanged_by_the_option(self):
        _, off_rows = self._write(ConditionSummaryGrouping())
        _, on_rows = self._write(
            ConditionSummaryGrouping(), strip_condition_elevations=True
        )
        self.assertEqual(len(on_rows), len(off_rows))
        for off, on in zip(off_rows, on_rows):
            without_name_off = off[: self.NAME_CELL] + off[self.NAME_CELL + 1 :]
            without_name_on = on[: self.NAME_CELL] + on[self.NAME_CELL + 1 :]
            self.assertEqual(without_name_on, without_name_off)

    def test_folder_names_keep_their_text_even_when_it_looks_like_an_elevation(self):
        _, rows = self._write(
            ConditionSummaryGrouping(), strip_condition_elevations=True
        )
        self.assertTrue(all(row[0] == "Level @T 9' 0\"" for row in rows))

    def test_every_grouping_strips_every_row_kind(self):
        for grouping in (
            ConditionSummaryGrouping(),
            ConditionSummaryGrouping(by_type=True),
            ConditionSummaryGrouping(by_page=True),
            ConditionSummaryGrouping(by_area=True),
            ConditionSummaryGrouping(by_page=True, by_area=True),
            ConditionSummaryGrouping(by_type=True, by_page=True, by_area=True),
        ):
            with self.subTest(grouping=grouping):
                _, rows = self._write(grouping, strip_condition_elevations=True)
                for name in self._names(rows):
                    self.assertNotIn(" @B", name)
                    self.assertNotIn("&apos;", name)
                    self.assertNotIn(" @T 5", name)

    def test_colliding_conditions_stay_separate_rows_and_are_reported(self):
        result, rows = self._write(
            ConditionSummaryGrouping(), strip_condition_elevations=True
        )
        walls = [row for row in rows if row[self.NAME_CELL] == "Wall"]
        self.assertEqual(len(walls), 2)
        self.assertEqual({row[4] for row in walls}, {"1", "2"})
        self.assertEqual(result.elevation_name_collisions, (("Wall", 2),))

    def test_no_collision_is_reported_when_names_stay_distinct(self):
        del self.conditions["c2"]
        self.takeoffs[:] = [t for t in self.takeoffs if t.condition_uid != "c2"]
        result, _rows = self._write(
            ConditionSummaryGrouping(), strip_condition_elevations=True
        )
        self.assertEqual(result.elevation_name_collisions, ())

    def test_collisions_are_not_reported_when_the_option_is_off(self):
        result, _rows = self._write(ConditionSummaryGrouping())
        self.assertEqual(result.elevation_name_collisions, ())

    def test_conditions_without_takeoffs_do_not_cause_collisions(self):
        self.conditions["unused"] = self._condition("unused", 9, "Slab @B 3' 0\"")
        result, _rows = self._write(
            ConditionSummaryGrouping(), strip_condition_elevations=True
        )
        self.assertEqual(result.elevation_name_collisions, (("Wall", 2),))

    def test_source_conditions_and_the_summary_tree_are_never_modified(self):
        root = self.csv_service.build_current_summary(ConditionSummaryGrouping())
        before = repr(root)
        self.csv_service.to_csv_rows(
            root, ConditionSummaryGrouping(), strip_condition_elevations=True
        )
        self.csv_service.to_csv_text(
            root, ConditionSummaryGrouping(), strip_condition_elevations=True
        )
        self._write(ConditionSummaryGrouping(), strip_condition_elevations=True)
        self.assertEqual(repr(root), before)
        self.assertEqual(
            {uid: (c.name, c.z_value, c.is_top) for uid, c in self.conditions.items()},
            self.original,
        )

    def test_only_condition_nodes_count_and_each_condition_counts_once(self):
        def values(name):
            return ConditionSummaryValues(name=name)

        root = ConditionSummaryNode(
            kind=SUMMARY_NODE_ROOT,
            values=values("Wall @B 1' 0\""),
            children=[
                ConditionSummaryNode(
                    kind=SUMMARY_NODE_FOLDER,
                    label="F",
                    values=values("Wall @T 2' 0\""),
                    children=[
                        ConditionSummaryNode(
                            kind=SUMMARY_NODE_CONDITION,
                            condition_uid="c1",
                            values=values("Wall @T 5' 0\""),
                        ),
                        ConditionSummaryNode(
                            kind=SUMMARY_NODE_CONDITION,
                            condition_uid="c1",
                            values=values("Wall @T 5' 0\""),
                        ),
                    ],
                )
            ],
        )
        self.assertEqual(
            SummaryCsvExportService._condition_names(root), ["Wall @T 5' 0\""]
        )

    def test_no_data_result_carries_no_collisions(self):
        self.takeoffs[:] = []
        result, _rows = (
            self.csv_service.export_current_summary(
                ConditionSummaryGrouping(),
                str(Path(tempfile.gettempdir()) / "ost-no-data.csv"),
                strip_condition_elevations=True,
            ),
            None,
        )
        self.assertFalse(result.success)
        self.assertEqual(result.elevation_name_collisions, ())


if __name__ == "__main__":
    unittest.main()
