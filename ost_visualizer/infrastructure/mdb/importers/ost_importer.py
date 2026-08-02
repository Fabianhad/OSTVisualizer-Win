import logging
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Set
from ....application.dtos.collaboration_dtos import (
    ChangeOperation,
    ResourceRef,
)
from ....domain.dtos.raw_bid_data_dto import RawBidData
from ..raw_bid_integrity import (
    clear_missing_annotation_takeoff_references,
    clear_missing_selected_page_references,
    format_integrity_issues,
    resolve_takeoff_graph,
    validate_raw_bid_integrity,
)
from ..schema_contract import (
    BID_SECTIONS,
    BID_TAIL_SECTIONS,
    OST_XML_TO_DATABASE_COLUMN,
    GLOBAL_SECTIONS,
    PAGE_SECTIONS,
)
from ..schema_contract import singular as _singular

logger = logging.getLogger(__name__)
_GLOBAL_ZERO_UID_FIELDS: Set[str] = {
    "BidProjectUID",
    "ParentBidUID",
    "OrigBidProjectUID",
    "OrigParentBidUID",
    "SourceBidUID",
    "OCRUID",
    "CoverSheetSelItemUID",
}
_EMPLOYEE_UID_FIELDS: Set[str] = {
    "EstimatorUID",
    "PrManagerUID",
    "JobSiteManagerUID",
    "EmployeeUID",
}
_BID_INTERNAL_UID_FIELDS: Set[str] = {
    "UID",
    "BidUID",
    "BidPageUID",
    "BidConditionUID",
    "BidLayerUID",
    "BidZoneUID",
    "BidAreaUID",
    "BidTypAreaUID",
    "ParentUID",
    "ParentCommentUID",
    "MasterPageUID",
    "MasterAreaUID",
    "TranslateAreaUID",
    "BidConditionFolderUID",
    "BidPageFolderUID",
    "BidTakeoffFromUID",
    "BidTakeoffToUID",
    "BidPageViewUID",
    "TypGroupTakeoffUID",
    "TypPageTakeoffUID",
    "TypGroupMarkerUID",
    "TypGroupUID",
    "BidPageSelectedUID",
}


def _matches_section_child(section: str, tag: str) -> bool:
    if tag == _singular(section):
        return True
    return bool(section.endswith("s") and tag == section[:-1])


def _database_row(attributes) -> Dict[str, str]:
    return {
        OST_XML_TO_DATABASE_COLUMN.get(column, column): value
        for column, value in attributes.items()
    }


class OstImporter:
    def __init__(self, mdb_writer) -> None:
        self._mdb_writer = mdb_writer

    def import_ost(
        self,
        ost_file_path: str,
        target_db_path: str,
        target_project_uid: Optional[str] = None,
    ) -> bool:
        try:
            raw_data = self._validated_raw_data(ost_file_path)
            return bool(
                self._mdb_writer.import_ost_data(
                    target_db_path, raw_data, self._transform, target_project_uid
                )
            )
        except Exception:
            logger.exception("Failed to import OST file %s", ost_file_path)
            return False

    def import_ost_mutation(
        self,
        ost_file_path: str,
        target_db_path: str,
        target_project_uid: Optional[str],
        recorder,
    ) -> dict[str, object]:
        raw_data = self._validated_raw_data(ost_file_path)
        value = self._mdb_writer.import_ost_data(
            target_db_path,
            raw_data,
            self._transform,
            target_project_uid,
        )
        if not isinstance(value, dict):
            raise RuntimeError(
                "The SQL import writer did not return authoritative identities."
            )
        bid_map = value.get("bid_uids")
        if not isinstance(bid_map, dict) or len(bid_map) != 1:
            raise RuntimeError(
                "The SQL import writer did not return exactly one imported bid."
            )
        bid_uid = str(next(iter(bid_map.values())))
        bid_value = int(bid_uid)
        project_collection = ResourceRef("project_bids", target_project_uid or "orphan")
        recorder.record(ResourceRef("bid", bid_uid, bid_value), ChangeOperation.CREATE)
        recorder.record(project_collection, ChangeOperation.UPDATE)
        for resource_type in (
            "conditions_collection",
            "areas_collection",
            "pages_collection",
            "layers_collection",
            "takeoffs_collection",
            "annotations_collection",
        ):
            recorder.record(
                ResourceRef(resource_type, bid_uid, bid_value),
                ChangeOperation.BULK_REFRESH,
            )
        recorder.record(
            ResourceRef("cover_sheet", bid_uid, bid_value),
            ChangeOperation.BULK_REFRESH,
        )
        for table_name, resource_type in (
            ("CdnTypes", "condition_types_collection"),
            ("JobStatuses", "job_statuses_collection"),
            ("Employees", "employees_collection"),
            ("PayClasses", "pay_classes_collection"),
        ):
            if raw_data.global_tables.get(table_name):
                recorder.record(
                    ResourceRef(resource_type, "database"),
                    ChangeOperation.BULK_REFRESH,
                )
        return value

    def _validated_raw_data(self, ost_file_path: str) -> RawBidData:
        raw_data = self._parse_ost_xml(ost_file_path)
        takeoff_graph = resolve_takeoff_graph(raw_data)
        if takeoff_graph.fatal_issues:
            raise ValueError(
                "The imported takeoff graph is invalid: "
                + format_integrity_issues(takeoff_graph.fatal_issues)
            )
        if takeoff_graph.skipped_count:
            descendant_diagnostic = (
                "; skipped dependent descendants: "
                + format_integrity_issues(takeoff_graph.dependent_descendants)
                if takeoff_graph.dependent_descendants
                else ""
            )
            logger.warning(
                "Skipping %d invalid takeoff(s) during OST import; "
                "missing-parent roots: %s%s",
                takeoff_graph.skipped_count,
                format_integrity_issues(takeoff_graph.missing_parent_roots),
                descendant_diagnostic,
            )
        cleared_selected_pages = clear_missing_selected_page_references(raw_data)
        if cleared_selected_pages:
            logger.warning(
                "Cleared %d missing selected-page reference(s) during OST "
                "import: %s",
                len(cleared_selected_pages),
                format_integrity_issues(cleared_selected_pages),
            )
        cleared_annotation_refs = clear_missing_annotation_takeoff_references(raw_data)
        if cleared_annotation_refs:
            logger.warning(
                "Cleared %d missing annotation takeoff attachment reference(s) "
                "during OST import: %s",
                len(cleared_annotation_refs),
                format_integrity_issues(cleared_annotation_refs),
            )
        if not self._validate_page_references(raw_data):
            raise ValueError("The imported project contains invalid references.")
        return raw_data

    def _transform(
        self,
        raw_data: RawBidData,
        max_uid: int,
        cdn_uid_map: Dict[str, str],
        job_status_uid_map: Dict[str, str],
        employee_uid_map: Dict[str, str],
        pay_class_uid_map: Dict[str, str],
    ) -> RawBidData:
        uid_map = self._build_uid_map(raw_data, max_uid)
        page_uid_map = self._build_page_uid_map(raw_data, uid_map)
        return self._remap_data(
            raw_data,
            uid_map,
            page_uid_map,
            cdn_uid_map,
            job_status_uid_map,
            employee_uid_map,
            pay_class_uid_map,
        )

    def _build_uid_map(self, raw_data: RawBidData, max_uid: int) -> Dict[str, str]:
        uid_map: Dict[str, str] = {}
        next_uid = max_uid + 1

        def assign(uid_val: str) -> None:
            nonlocal next_uid
            if uid_val and uid_val != "0" and uid_val not in uid_map:
                uid_map[uid_val] = str(next_uid)
                next_uid += 1

        assign(raw_data.bid_row.get("UID", ""))
        for rows in raw_data.bid_tables.values():
            for row in rows:
                assign(row.get("UID", ""))
        for rows in raw_data.page_tables.values():
            for row in rows:
                assign(row.get("UID", ""))
        return uid_map

    def _build_page_uid_map(
        self, raw_data: RawBidData, uid_map: Dict[str, str]
    ) -> Dict[str, str]:
        page_uid_map: Dict[str, str] = {}
        for page_row in raw_data.bid_tables.get("BidPages", []):
            source_uid = (page_row.get("UID") or "").strip()
            if not source_uid or source_uid == "0":
                continue
            mapped_uid = uid_map.get(source_uid)
            if mapped_uid:
                page_uid_map[source_uid] = mapped_uid
        return page_uid_map

    def _remap_uid_value(
        self,
        field: str,
        value: str,
        uid_map: Dict[str, str],
        page_uid_map: Dict[str, str],
        cdn_uid_map: Dict[str, str],
        job_status_uid_map: Dict[str, str],
        employee_uid_map: Dict[str, str],
        pay_class_uid_map: Dict[str, str],
    ) -> str:
        if field == "BidPageSelectedUID":
            source_uid = (value or "").strip()
            if not source_uid or source_uid == "0":
                return "NULL"
            return page_uid_map.get(source_uid, "NULL")
        if not value:
            return value
        if value == "0":
            return "NULL" if field.endswith("UID") else value
        if field == "CdnTypeUID":
            return cdn_uid_map.get(value, value)
        if field == "JobStatusUID":
            return job_status_uid_map.get(value, "NULL")
        if field in _EMPLOYEE_UID_FIELDS:
            return employee_uid_map.get(value, "NULL")
        if field == "PayClassUID":
            return pay_class_uid_map.get(value, "NULL")
        if field in _GLOBAL_ZERO_UID_FIELDS:
            return "NULL"
        if field in _BID_INTERNAL_UID_FIELDS:
            return uid_map.get(value, value)
        return value

    def _remap_row(
        self,
        row: Dict[str, str],
        uid_map: Dict[str, str],
        page_uid_map: Dict[str, str],
        cdn_uid_map: Dict[str, str],
        job_status_uid_map: Dict[str, str],
        employee_uid_map: Dict[str, str],
        pay_class_uid_map: Dict[str, str],
    ) -> Dict[str, str]:
        return {
            field: self._remap_uid_value(
                field,
                value,
                uid_map,
                page_uid_map,
                cdn_uid_map,
                job_status_uid_map,
                employee_uid_map,
                pay_class_uid_map,
            )
            for field, value in row.items()
        }

    def _remap_data(
        self,
        raw_data: RawBidData,
        uid_map: Dict[str, str],
        page_uid_map: Dict[str, str],
        cdn_uid_map: Dict[str, str],
        job_status_uid_map: Dict[str, str],
        employee_uid_map: Dict[str, str],
        pay_class_uid_map: Dict[str, str],
    ) -> RawBidData:
        remapped_bid_row = self._remap_row(
            raw_data.bid_row,
            uid_map,
            page_uid_map,
            cdn_uid_map,
            job_status_uid_map,
            employee_uid_map,
            pay_class_uid_map,
        )
        remapped_bid_tables = {
            table: [
                self._remap_row(
                    r,
                    uid_map,
                    page_uid_map,
                    cdn_uid_map,
                    job_status_uid_map,
                    employee_uid_map,
                    pay_class_uid_map,
                )
                for r in rows
            ]
            for table, rows in raw_data.bid_tables.items()
        }
        remapped_page_tables = {
            table: [
                self._remap_row(
                    r,
                    uid_map,
                    page_uid_map,
                    cdn_uid_map,
                    job_status_uid_map,
                    employee_uid_map,
                    pay_class_uid_map,
                )
                for r in rows
            ]
            for table, rows in raw_data.page_tables.items()
        }
        remapped_page_tables["BidPageSettings"] = self._canonicalize_page_area_settings(
            remapped_page_tables.get("BidPageSettings", [])
        )
        return RawBidData(
            bid_row=remapped_bid_row,
            bid_tables=remapped_bid_tables,
            page_tables=remapped_page_tables,
        )

    def _validate_page_references(self, raw_data: RawBidData) -> bool:
        invalid_refs = validate_raw_bid_integrity(raw_data)
        if invalid_refs:
            logger.error(
                "Rejecting OST import because it contains invalid database "
                "references: %s",
                format_integrity_issues(invalid_refs),
            )
            return False
        return True

    def _canonicalize_page_area_settings(
        self, rows: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        if not rows:
            return rows
        unselected_rows: List[Dict[str, str]] = []
        selected_by_page: Dict[str, Dict[str, str]] = {}
        for row in rows:
            page_uid = row.get("BidPageUID", "")
            try:
                selected_value = int(row.get("BidAreaSelected", "0") or "0")
            except ValueError:
                selected_value = 0
            if selected_value <= 0:
                unselected_rows.append(row)
                continue
            current = selected_by_page.get(page_uid)
            if current is None:
                selected_by_page[page_uid] = row
                continue
            try:
                current_selected = int(current.get("BidAreaSelected", "0") or "0")
            except ValueError:
                current_selected = 0
            try:
                current_uid = int(current.get("UID", "0") or "0")
            except ValueError:
                current_uid = 0
            try:
                row_uid = int(row.get("UID", "0") or "0")
            except ValueError:
                row_uid = 0
            if (selected_value, row_uid) >= (current_selected, current_uid):
                selected_by_page[page_uid] = row
        return unselected_rows + list(selected_by_page.values())

    def _parse_ost_xml(self, ost_path: str) -> RawBidData:
        tree = ET.parse(ost_path)
        root = tree.getroot()
        bid_elem = root.find("Bid")
        if bid_elem is None:
            raise ValueError("No Bid element found in OST file")
        bid_row = _database_row(bid_elem.attrib)
        bid_tables: Dict[str, List] = {}
        page_tables: Dict[str, List] = {}
        global_tables: Dict[str, List] = {}
        for section in BID_SECTIONS:
            rows: List[Dict[str, str]] = []
            container = bid_elem.find(section)
            if container is not None:
                for child in container:
                    if _matches_section_child(section, child.tag):
                        rows.append(_database_row(child.attrib))
            bid_tables[section] = rows
        pages_container = bid_elem.find("BidPages")
        bid_pages: List[Dict[str, str]] = []
        if pages_container is not None:
            for page_elem in pages_container:
                if page_elem.tag != "BidPage":
                    continue
                bid_pages.append(_database_row(page_elem.attrib))
                for section in PAGE_SECTIONS:
                    container = page_elem.find(section)
                    if container is not None:
                        for child in container:
                            if _matches_section_child(section, child.tag):
                                page_tables.setdefault(section, []).append(
                                    _database_row(child.attrib)
                                )
        bid_tables["BidPages"] = bid_pages
        for section in BID_TAIL_SECTIONS:
            rows = []
            container = bid_elem.find(section)
            if container is not None:
                for child in container:
                    if _matches_section_child(section, child.tag):
                        rows.append(_database_row(child.attrib))
            bid_tables[section] = rows
        for section in GLOBAL_SECTIONS:
            rows = []
            container = root.find(section)
            if container is not None:
                for child in container:
                    if _matches_section_child(section, child.tag):
                        rows.append(_database_row(child.attrib))
            global_tables[section] = rows
        return RawBidData(
            bid_row=bid_row,
            bid_tables=bid_tables,
            page_tables=page_tables,
            global_tables=global_tables,
        )
