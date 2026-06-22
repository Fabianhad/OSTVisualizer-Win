from __future__ import annotations
import csv
import io
from dataclasses import dataclass
from typing import Callable, List, Sequence, Tuple
from ...domain.entities.file_extensions import CSV_EXTENSION
from ...domain.services.project_data_service import ProjectDataService
from ...domain.services.uom_service import get_uom_label
from ..dtos.condition_summary_dtos import (
    SUMMARY_GROUP_AREA,
    SUMMARY_GROUP_PAGE,
    SUMMARY_GROUP_TYPE,
    SUMMARY_NODE_AREA_DETAIL,
    SUMMARY_NODE_CONDITION,
    SUMMARY_NODE_FOLDER,
    SUMMARY_NODE_GROUP,
    SUMMARY_NODE_MULTI_AREA_TOTAL,
    ConditionSummaryGrouping,
    ConditionSummaryNode,
    ConditionSummaryValues,
)
from ..dtos.export_dto import ExportErrorCode, ExportResultDto
from ..utils.quantity_display import format_quantity_number
from .project_read_service import ProjectReadService
from ..use_cases.project.condition_summary_service import ConditionSummaryService


@dataclass(frozen=True)
class _ExportRow:
    folder_path: Tuple[str, ...]
    page: str
    type_name: str
    area: str
    values: ConditionSummaryValues
    sequence: int


class SummaryCsvExportService:
    FORMAT_NAME = "Summary CSV"

    def __init__(
        self,
        project_data_service: ProjectDataService,
        project_read_service: ProjectReadService,
        summary_service: ConditionSummaryService | None = None,
    ) -> None:
        self._project_data = project_data_service
        self._project_read = project_read_service
        self._summary_service = summary_service or ConditionSummaryService()

    def default_filename(self) -> str:
        bid = self._project_data.get_current_bid()
        bid_name = (bid.name if bid else "") or "Bid"
        return f"{bid_name} Summary{CSV_EXTENSION}"

    def export_current_summary(
        self, grouping: ConditionSummaryGrouping, filename: str
    ) -> ExportResultDto:
        root = self.build_current_summary(grouping)
        if root is None or not root.children:
            return ExportResultDto(
                success=False,
                format_name=self.FORMAT_NAME,
                error_message="No summary rows are available to export.",
                error_code=ExportErrorCode.NO_DATA,
            )
        try:
            csv_text = self.to_csv_text(root, grouping)
            if not csv_text:
                return ExportResultDto(
                    success=False,
                    format_name=self.FORMAT_NAME,
                    error_message="No summary rows are available to export.",
                    error_code=ExportErrorCode.NO_DATA,
                )
            with open(filename, "w", encoding="utf-8", newline="") as handle:
                handle.write(csv_text)
            return ExportResultDto(
                success=True, page_count=1, format_name=self.FORMAT_NAME
            )
        except OSError as exc:
            return ExportResultDto(
                success=False,
                format_name=self.FORMAT_NAME,
                error_message=str(exc),
                error_code=ExportErrorCode.WRITE_FAILED,
            )
        except Exception as exc:
            return ExportResultDto(
                success=False,
                format_name=self.FORMAT_NAME,
                error_message=str(exc),
                error_code=ExportErrorCode.UNEXPECTED,
            )

    def build_current_summary(
        self, grouping: ConditionSummaryGrouping
    ) -> ConditionSummaryNode | None:
        bid_ref = self._project_data.get_current_bid_ref()
        if not bid_ref:
            return None
        bid = self._project_data.get_bid(bid_ref)
        project_name = (bid.name or "") if bid else ""
        metric = bool(bid.measure_base) if bid else False
        areas = self._project_read.get_bid_areas(bid_ref.file_path, bid_ref.bid_uid)
        return self._summary_service.build_summary(
            conditions=self._project_data.get_bid_conditions(),
            folders=self._project_data.get_bid_condition_folders(),
            takeoffs=self._project_data.get_all_takeoffs(),
            pages=self._project_data.get_all_pages(),
            areas=areas,
            project_name=project_name,
            grouping=grouping,
            metric=metric,
        )

    def to_csv_text(
        self, root: ConditionSummaryNode, grouping: ConditionSummaryGrouping
    ) -> str:
        rows = self.to_csv_rows(root, grouping)
        if not rows:
            return ""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n", quoting=csv.QUOTE_ALL)
        writer.writerows(rows)
        return buffer.getvalue()

    def to_csv_rows(
        self, root: ConditionSummaryNode, grouping: ConditionSummaryGrouping
    ) -> List[List[str]]:
        export_rows: List[_ExportRow] = []
        self._collect_rows(root, (), {}, export_rows)
        export_rows = self._sort_rows(export_rows, grouping)
        return [self._format_row(row, grouping) for row in export_rows]

    def _collect_rows(
        self,
        node: ConditionSummaryNode,
        folder_path: Tuple[str, ...],
        groups: dict[str, str],
        rows: List[_ExportRow],
    ) -> None:
        if node.kind == SUMMARY_NODE_FOLDER:
            folder_path = (*folder_path, node.label)
        elif node.kind == SUMMARY_NODE_GROUP:
            groups = dict(groups)
            groups[node.group_level] = node.label
        elif node.kind in (
            SUMMARY_NODE_CONDITION,
            SUMMARY_NODE_MULTI_AREA_TOTAL,
            SUMMARY_NODE_AREA_DETAIL,
        ):
            values = node.values
            type_name = groups.get(SUMMARY_GROUP_TYPE) or values.type_name
            area = groups.get(SUMMARY_GROUP_AREA) or values.area
            rows.append(
                _ExportRow(
                    folder_path=folder_path,
                    page=groups.get(SUMMARY_GROUP_PAGE, ""),
                    type_name=type_name,
                    area=area,
                    values=values,
                    sequence=len(rows),
                )
            )
        for child in node.children:
            self._collect_rows(child, folder_path, groups, rows)

    def _sort_rows(
        self, rows: Sequence[_ExportRow], grouping: ConditionSummaryGrouping
    ) -> List[_ExportRow]:
        if not rows:
            return []
        page_order = self._encounter_order(rows, lambda row: row.page)
        area_order = self._encounter_order(rows, lambda row: row.area)

        def natural(row: _ExportRow) -> Tuple:
            return (row.sequence,)

        def type_key(row: _ExportRow) -> Tuple:
            return (row.type_name.lower(), row.type_name)

        def page_key(row: _ExportRow) -> Tuple:
            return (page_order[row.page], row.page.lower(), row.page)

        def area_key(row: _ExportRow) -> Tuple:
            return (area_order[row.area], row.area.lower(), row.area)

        if grouping.by_page and grouping.by_area:
            return sorted(
                rows, key=lambda row: (page_key(row), area_key(row), natural(row))
            )
        if grouping.by_page and grouping.by_type:
            return sorted(
                rows, key=lambda row: (type_key(row), page_key(row), natural(row))
            )
        if grouping.by_page:
            return sorted(rows, key=lambda row: (page_key(row), natural(row)))
        if grouping.by_type and grouping.by_area:
            return sorted(
                rows, key=lambda row: (type_key(row), area_key(row), natural(row))
            )
        if grouping.by_type:
            return sorted(rows, key=lambda row: (type_key(row), natural(row)))
        if grouping.by_area:
            return sorted(rows, key=lambda row: (area_key(row), natural(row)))
        return list(rows)

    @staticmethod
    def _encounter_order(
        rows: Sequence[_ExportRow], value_for_row: Callable[[_ExportRow], str]
    ) -> dict[str, int]:
        order: dict[str, int] = {}
        for row in rows:
            value = value_for_row(row)
            if value not in order:
                order[value] = len(order)
        return order

    def _format_row(
        self, row: _ExportRow, grouping: ConditionSummaryGrouping
    ) -> List[str]:
        values = row.values
        first_folder = row.folder_path[0] if row.folder_path else ""
        remaining_folders = " / ".join(row.folder_path[1:])
        cells = [
            first_folder,
            row.page if grouping.by_page else "",
            remaining_folders,
            row.type_name,
            values.number,
            values.name,
            self._format_height(values.height_inches),
        ]
        if self._include_area_column(grouping):
            cells.append(row.area)
        cells.extend(
            [
                self._format_quantity(values.quantity1, values.uom1),
                get_uom_label(values.uom1),
                self._format_quantity(values.quantity2, values.uom2),
                get_uom_label(values.uom2),
                self._format_quantity(values.quantity3, values.uom3),
                get_uom_label(values.uom3),
                values.notes,
            ]
        )
        return cells

    @staticmethod
    def _include_area_column(grouping: ConditionSummaryGrouping) -> bool:
        return (not grouping.by_area) or grouping.by_page

    @staticmethod
    def _format_height(value: float) -> str:
        if abs(value) < 0.000005:
            return "0"
        return f"{value:.5f}"

    @staticmethod
    def _format_quantity(value: float, uom_code: int) -> str:
        return format_quantity_number(value, uom_code, zero_text="0")
