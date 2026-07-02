from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence, Set, Tuple

from ...domain.dtos.raw_bid_data_dto import RawBidData, RawTable
from .reference_validation import is_present_uid
from .schema_contract import (
    BID_SECTIONS,
    BID_TAIL_SECTIONS,
    GLOBAL_SECTIONS,
    PAGE_SECTIONS,
)


@dataclass(frozen=True)
class RawBidRelationship:
    child_table: str
    child_column: str
    parent_table: str
    parent_column: str = "UID"


@dataclass(frozen=True)
class RawBidIntegrityIssue:
    table: str
    row_uid: str
    column: str
    missing_uid: str
    parent_table: str

    def format(self) -> str:
        row_uid = self.row_uid or "<no UID>"
        return (
            f"{self.table}.UID={row_uid} {self.column}={self.missing_uid} "
            f"missing {self.parent_table}.UID"
        )


RAW_BID_RELATIONSHIPS: Tuple[RawBidRelationship, ...] = (
    RawBidRelationship("BidPlanRooms", "BidUID", "Bids"),
    RawBidRelationship("BidAreas", "BidUID", "Bids"),
    RawBidRelationship("BidAreas", "ParentUID", "BidAreas"),
    RawBidRelationship("BidTypAreas", "BidUID", "Bids"),
    RawBidRelationship("BidConditionFolders", "BidUID", "Bids"),
    RawBidRelationship("BidConditionFolders", "ParentUID", "BidConditionFolders"),
    RawBidRelationship("BidPageFolders", "BidUID", "Bids"),
    RawBidRelationship("BidPageFolders", "ParentUID", "BidPageFolders"),
    RawBidRelationship("BidSettings", "BidUID", "Bids"),
    RawBidRelationship("BidSettings", "BidPageSelectedUID", "BidPages"),
    RawBidRelationship("BidEmployees", "BidUID", "Bids"),
    RawBidRelationship("BidEmployees", "EmployeeUID", "Employees"),
    RawBidRelationship("BidEmployees", "PayClassUID", "PayClasses"),
    RawBidRelationship("BidLayers", "BidUID", "Bids"),
    RawBidRelationship("BidTypAreaCounts", "BidAreaUID", "BidAreas"),
    RawBidRelationship("BidTypAreaCounts", "BidTypAreaUID", "BidTypAreas"),
    RawBidRelationship("BidConditions", "BidUID", "Bids"),
    RawBidRelationship("BidConditions", "BidConditionFolderUID", "BidConditionFolders"),
    RawBidRelationship("BidConditions", "BidLayerUID", "BidLayers"),
    RawBidRelationship("BidConditions", "CdnTypeUID", "CdnTypes"),
    RawBidRelationship("BidConditionUser", "BidUID", "Bids"),
    RawBidRelationship("BidZones", "BidUID", "Bids"),
    RawBidRelationship("BidZones", "BidLayerUID", "BidLayers"),
    RawBidRelationship("BidTypGroupViews", "BidUID", "Bids"),
    RawBidRelationship("BidTypGroupViews", "BidPageUID", "BidPages"),
    RawBidRelationship("BidTypGroupViews", "BidConditionUID", "BidConditions"),
    RawBidRelationship("BidPages", "BidUID", "Bids"),
    RawBidRelationship("BidPages", "BidPageFolderUID", "BidPageFolders"),
    RawBidRelationship("BidPages", "MasterPageUID", "BidPages"),
    RawBidRelationship("BidTakeoffs", "BidUID", "Bids"),
    RawBidRelationship("BidTakeoffs", "BidPageUID", "BidPages"),
    RawBidRelationship("BidTakeoffs", "BidConditionUID", "BidConditions"),
    RawBidRelationship("BidTakeoffs", "BidZoneUID", "BidZones"),
    RawBidRelationship("BidTakeoffs", "BidAreaUID", "BidAreas"),
    RawBidRelationship("BidTakeoffs", "BidTypAreaUID", "BidTypAreas"),
    RawBidRelationship("BidTakeoffs", "ParentUID", "BidTakeoffs"),
    RawBidRelationship("BidTakeoffs", "TypGroupTakeoffUID", "BidTakeoffs"),
    RawBidRelationship("BidTakeoffs", "TypPageTakeoffUID", "BidTakeoffs"),
    RawBidRelationship("BidTakeoffs", "TypGroupMarkerUID", "BidTakeoffs"),
    RawBidRelationship("BidHighlights", "BidUID", "Bids"),
    RawBidRelationship("BidHighlights", "BidPageUID", "BidPages"),
    RawBidRelationship("BidHighlights", "BidLayerUID", "BidLayers"),
    RawBidRelationship("BidTexts", "BidUID", "Bids"),
    RawBidRelationship("BidTexts", "BidPageUID", "BidPages"),
    RawBidRelationship("BidTexts", "BidLayerUID", "BidLayers"),
    RawBidRelationship("BidDimensions", "BidUID", "Bids"),
    RawBidRelationship("BidDimensions", "BidPageUID", "BidPages"),
    RawBidRelationship("BidDimensions", "BidTakeoffFromUID", "BidTakeoffs"),
    RawBidRelationship("BidDimensions", "BidTakeoffToUID", "BidTakeoffs"),
    RawBidRelationship("BidArrows", "BidUID", "Bids"),
    RawBidRelationship("BidArrows", "BidPageUID", "BidPages"),
    RawBidRelationship("BidArrows", "BidTakeoffFromUID", "BidTakeoffs"),
    RawBidRelationship("BidArrows", "BidTakeoffToUID", "BidTakeoffs"),
    RawBidRelationship("BidALines", "BidUID", "Bids"),
    RawBidRelationship("BidALines", "BidPageUID", "BidPages"),
    RawBidRelationship("BidALines", "BidTakeoffFromUID", "BidTakeoffs"),
    RawBidRelationship("BidALines", "BidTakeoffToUID", "BidTakeoffs"),
    RawBidRelationship("BidCallOuts", "BidUID", "Bids"),
    RawBidRelationship("BidCallOuts", "BidPageUID", "BidPages"),
    RawBidRelationship("BidCallOuts", "BidLayerUID", "BidLayers"),
    RawBidRelationship("BidAnnotationRects", "BidUID", "Bids"),
    RawBidRelationship("BidAnnotationRects", "BidPageUID", "BidPages"),
    RawBidRelationship("BidAnnotationRects", "BidLayerUID", "BidLayers"),
    RawBidRelationship("BidAnnotationOvals", "BidUID", "Bids"),
    RawBidRelationship("BidAnnotationOvals", "BidPageUID", "BidPages"),
    RawBidRelationship("BidAnnotationOvals", "BidLayerUID", "BidLayers"),
    RawBidRelationship("BidAnnotationPolygons", "BidUID", "Bids"),
    RawBidRelationship("BidAnnotationPolygons", "BidPageUID", "BidPages"),
    RawBidRelationship("BidAnnotationPolygons", "BidLayerUID", "BidLayers"),
    RawBidRelationship("BidAnnotationClouds", "BidUID", "Bids"),
    RawBidRelationship("BidAnnotationClouds", "BidPageUID", "BidPages"),
    RawBidRelationship("BidAnnotationClouds", "BidLayerUID", "BidLayers"),
    RawBidRelationship("BidAnnoInk", "BidUID", "Bids"),
    RawBidRelationship("BidAnnoInk", "BidPageUID", "BidPages"),
    RawBidRelationship("BidLegends", "BidUID", "Bids"),
    RawBidRelationship("BidLegends", "BidPageUID", "BidPages"),
    RawBidRelationship("BidPageSettings", "BidPageUID", "BidPages"),
    RawBidRelationship("BidPageSettings", "BidAreaUID", "BidAreas"),
    RawBidRelationship("BidPageSettings", "BidTypAreaUID", "BidTypAreas"),
    RawBidRelationship("BidAreaTranslations", "BidPageUID", "BidPages"),
    RawBidRelationship("BidAreaTranslations", "MasterAreaUID", "BidAreas"),
    RawBidRelationship("BidAreaTranslations", "TranslateAreaUID", "BidAreas"),
    RawBidRelationship("BidMarkedPages", "BidPageUID", "BidPages"),
    RawBidRelationship("BidComments", "BidUID", "Bids"),
    RawBidRelationship("BidComments", "BidPageUID", "BidPages"),
    RawBidRelationship("BidComments", "BidLayerUID", "BidLayers"),
    RawBidRelationship("BidComments", "ParentCommentUID", "BidComments"),
    RawBidRelationship("BidNamedViews", "BidUID", "Bids"),
    RawBidRelationship("BidNamedViews", "BidPageUID", "BidPages"),
    RawBidRelationship("BidHotLinks", "BidUID", "Bids"),
    RawBidRelationship("BidHotLinks", "BidPageUID", "BidPages"),
    RawBidRelationship("BidHotLinks", "BidPageViewUID", "BidNamedViews"),
    RawBidRelationship("BidHotLinks", "BidLayerUID", "BidLayers"),
    RawBidRelationship("Employees", "PayClassUID", "PayClasses"),
    RawBidRelationship("Employees", "AccessLevelUID", "AccessLevels"),
)

_RAW_TABLES = (
    ("Bids",)
    + tuple(BID_SECTIONS)
    + ("BidPages",)
    + tuple(BID_TAIL_SECTIONS)
    + tuple(PAGE_SECTIONS)
    + tuple(GLOBAL_SECTIONS)
)
_RAW_TABLE_SET = set(_RAW_TABLES)
_GLOBAL_TABLE_SET = set(GLOBAL_SECTIONS)
_CLEARABLE_EXPORT_REFERENCES = {("BidSettings", "BidPageSelectedUID")}


def clone_raw_bid_data(raw_data: RawBidData) -> RawBidData:
    return RawBidData(
        bid_row=dict(raw_data.bid_row),
        bid_tables={
            table: [dict(row) for row in rows]
            for table, rows in raw_data.bid_tables.items()
        },
        page_tables={
            table: [dict(row) for row in rows]
            for table, rows in raw_data.page_tables.items()
        },
        global_tables={
            table: [dict(row) for row in rows]
            for table, rows in raw_data.global_tables.items()
        },
    )


def raw_bid_table_rows(raw_data: RawBidData) -> Dict[str, RawTable]:
    rows: Dict[str, RawTable] = {table: [] for table in _RAW_TABLES}
    if raw_data.bid_row:
        rows["Bids"] = [raw_data.bid_row]
    for source in (raw_data.bid_tables, raw_data.page_tables, raw_data.global_tables):
        for table, table_rows in source.items():
            rows.setdefault(table, [])
            rows[table].extend(table_rows)
    return rows


def _present_uids(rows: Iterable[Mapping[str, str]], column: str) -> Set[str]:
    return {
        str(row.get(column, ""))
        for row in rows
        if is_present_uid(str(row.get(column, "")))
    }


def validate_raw_bid_integrity(
    raw_data: RawBidData,
    relationships: Sequence[RawBidRelationship] = RAW_BID_RELATIONSHIPS,
) -> List[RawBidIntegrityIssue]:
    rows_by_table = raw_bid_table_rows(raw_data)
    parent_uid_cache: Dict[Tuple[str, str], Set[str]] = {}
    issues: List[RawBidIntegrityIssue] = []
    for relationship in relationships:
        child_rows = rows_by_table.get(relationship.child_table, [])
        if not child_rows:
            continue
        key = (relationship.parent_table, relationship.parent_column)
        if key not in parent_uid_cache:
            parent_uid_cache[key] = _present_uids(
                rows_by_table.get(relationship.parent_table, []),
                relationship.parent_column,
            )
        valid_parent_uids = parent_uid_cache[key]
        for row in child_rows:
            if relationship.child_column not in row:
                continue
            value = str(row.get(relationship.child_column, ""))
            if not is_present_uid(value) or value in valid_parent_uids:
                continue
            issues.append(
                RawBidIntegrityIssue(
                    table=relationship.child_table,
                    row_uid=str(row.get("UID", "")),
                    column=relationship.child_column,
                    missing_uid=value,
                    parent_table=relationship.parent_table,
                )
            )
    return issues


def format_integrity_issues(
    issues: Sequence[RawBidIntegrityIssue],
    *,
    limit: int = 10,
) -> str:
    preview = "; ".join(issue.format() for issue in issues[:limit])
    if len(issues) > limit:
        preview += f"; +{len(issues) - limit} more"
    return preview


def prepare_raw_bid_data_for_export(raw_data: RawBidData) -> RawBidData:
    prepared = clone_raw_bid_data(raw_data)
    _clear_missing_export_references(prepared)
    while _prune_export_orphans(prepared):
        _clear_missing_export_references(prepared)
    return prepared


def _clear_missing_export_references(raw_data: RawBidData) -> None:
    rows_by_table = raw_bid_table_rows(raw_data)
    page_uids = _present_uids(rows_by_table.get("BidPages", []), "UID")
    for row in raw_data.bid_tables.get("BidSettings", []):
        selected_uid = str(row.get("BidPageSelectedUID", ""))
        if is_present_uid(selected_uid) and selected_uid not in page_uids:
            row["BidPageSelectedUID"] = "0"


def _prune_export_orphans(raw_data: RawBidData) -> bool:
    rows_by_table = raw_bid_table_rows(raw_data)
    parent_uid_cache = {
        (relationship.parent_table, relationship.parent_column): _present_uids(
            rows_by_table.get(relationship.parent_table, []),
            relationship.parent_column,
        )
        for relationship in RAW_BID_RELATIONSHIPS
    }
    pruned_any = False
    for table, rows in list(raw_data.bid_tables.items()):
        pruned_rows = _prune_rows(table, rows, parent_uid_cache)
        if len(pruned_rows) != len(rows):
            raw_data.bid_tables[table] = pruned_rows
            pruned_any = True
    for table, rows in list(raw_data.page_tables.items()):
        pruned_rows = _prune_rows(table, rows, parent_uid_cache)
        if len(pruned_rows) != len(rows):
            raw_data.page_tables[table] = pruned_rows
            pruned_any = True
    return pruned_any


def _prune_rows(
    table: str,
    rows: RawTable,
    parent_uid_cache: Mapping[Tuple[str, str], Set[str]],
) -> RawTable:
    if table not in _RAW_TABLE_SET or table in _GLOBAL_TABLE_SET:
        return rows
    table_relationships = [
        relationship
        for relationship in RAW_BID_RELATIONSHIPS
        if relationship.child_table == table
        and relationship.parent_table not in _GLOBAL_TABLE_SET
        and (relationship.child_table, relationship.child_column)
        not in _CLEARABLE_EXPORT_REFERENCES
    ]
    if not table_relationships:
        return rows
    kept: RawTable = []
    for row in rows:
        keep = True
        for relationship in table_relationships:
            value = str(row.get(relationship.child_column, ""))
            if not is_present_uid(value):
                continue
            valid_parent_uids = parent_uid_cache.get(
                (relationship.parent_table, relationship.parent_column),
                set(),
            )
            if value not in valid_parent_uids:
                keep = False
                break
        if keep:
            kept.append(row)
    return kept
