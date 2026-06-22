from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple

SUMMARY_GROUP_PAGE = "page"
SUMMARY_GROUP_TYPE = "type"
SUMMARY_GROUP_AREA = "area"
SUMMARY_NODE_ROOT = "root"
SUMMARY_NODE_FOLDER = "folder"
SUMMARY_NODE_GROUP = "group"
SUMMARY_NODE_CONDITION = "condition"
SUMMARY_NODE_MULTI_AREA_TOTAL = "multi_area_total"
SUMMARY_NODE_AREA_DETAIL = "area_detail"
SUMMARY_UNASSIGNED_LABEL = "(unassigned)"
SUMMARY_NO_PAGE_LABEL = "Items Without Page"
SUMMARY_MULTI_AREA_TOTAL_LABEL = "Multi-Area Total"
SUMMARY_COLUMN_NUMBER = "number"
SUMMARY_COLUMN_NAME = "name"
SUMMARY_COLUMN_HEIGHT = "height"
SUMMARY_COLUMN_AREA = "area"
SUMMARY_COLUMN_QUANTITY1 = "quantity1"
SUMMARY_COLUMN_UOM1 = "uom1"
SUMMARY_COLUMN_QUANTITY2 = "quantity2"
SUMMARY_COLUMN_UOM2 = "uom2"
SUMMARY_COLUMN_QUANTITY3 = "quantity3"
SUMMARY_COLUMN_UOM3 = "uom3"
SUMMARY_COLUMN_NOTES = "notes"
SUMMARY_QUANTITY_COLUMNS = (
    SUMMARY_COLUMN_QUANTITY1,
    SUMMARY_COLUMN_UOM1,
    SUMMARY_COLUMN_QUANTITY2,
    SUMMARY_COLUMN_UOM2,
    SUMMARY_COLUMN_QUANTITY3,
    SUMMARY_COLUMN_UOM3,
)


@dataclass(frozen=True)
class ConditionSummaryGrouping:
    by_page: bool = False
    by_type: bool = False
    by_area: bool = False

    def active_levels(self) -> Tuple[str, ...]:
        levels = []
        if self.by_page:
            levels.append(SUMMARY_GROUP_PAGE)
        if self.by_type:
            levels.append(SUMMARY_GROUP_TYPE)
        if self.by_area:
            levels.append(SUMMARY_GROUP_AREA)
        return tuple(levels)


@dataclass(frozen=True)
class ConditionSummaryValues:
    number: str = ""
    name: str = ""
    height: str = ""
    area: str = ""
    quantity1: float = 0.0
    uom1: int = 0
    quantity2: float = 0.0
    uom2: int = 0
    quantity3: float = 0.0
    uom3: int = 0
    notes: str = ""


@dataclass
class ConditionSummaryNode:
    kind: str
    label: str = ""
    condition_uid: str = ""
    folder_uid: str = ""
    group_level: str = ""
    values: ConditionSummaryValues = field(default_factory=ConditionSummaryValues)
    children: List["ConditionSummaryNode"] = field(default_factory=list)
    bold_columns: Tuple[str, ...] = ()
    copyable: bool = False
    deletable: bool = False
    color_fill: int = 0
    pattern: int = 0
    layer_visible: bool = True
