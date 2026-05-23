import logging
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Set
from ....domain.dtos.raw_bid_data_dto import RawBidData
from ..ost_schema import BID_SECTIONS, BID_TAIL_SECTIONS, GLOBAL_SECTIONS, PAGE_SECTIONS
from ..ost_schema import singular as _singular

logger = logging.getLogger(__name__)
_GLOBAL_ZERO_UID_FIELDS: Set[str] = {
    "EstimatorUID",
    "PrManagerUID",
    "JobSiteManagerUID",
    "BidProjectUID",
    "ParentBidUID",
    "OrigBidProjectUID",
    "OrigParentBidUID",
    "SourceBidUID",
    "OCRUID",
    "CoverSheetSelItemUID",
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
    "MasterPageUID",
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
            raw_data = self._parse_ost_xml(ost_file_path)
            return self._mdb_writer.import_ost_data(
                target_db_path, raw_data, self._transform, target_project_uid
            )
        except Exception:
            logger.exception("Failed to import OST file %s", ost_file_path)
            return False

    def _transform(
        self,
        raw_data: RawBidData,
        max_uid: int,
        cdn_uid_map: Dict[str, str],
        job_status_uid_map: Dict[str, str],
    ) -> RawBidData:
        uid_map = self._build_uid_map(raw_data, max_uid)
        return self._remap_data(raw_data, uid_map, cdn_uid_map, job_status_uid_map)

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

    def _remap_uid_value(
        self,
        field: str,
        value: str,
        uid_map: Dict[str, str],
        cdn_uid_map: Dict[str, str],
        job_status_uid_map: Dict[str, str],
    ) -> str:
        if not value:
            return value
        if value == "0":
            return "NULL" if field.endswith("UID") else value
        if field == "CdnTypeUID":
            return cdn_uid_map.get(value, value)
        if field == "JobStatusUID":
            return job_status_uid_map.get(value, "NULL")
        if field in _GLOBAL_ZERO_UID_FIELDS:
            return "NULL"
        if field in _BID_INTERNAL_UID_FIELDS:
            return uid_map.get(value, value)
        return value

    def _remap_row(
        self,
        row: Dict[str, str],
        uid_map: Dict[str, str],
        cdn_uid_map: Dict[str, str],
        job_status_uid_map: Dict[str, str],
    ) -> Dict[str, str]:
        return {
            field: self._remap_uid_value(
                field, value, uid_map, cdn_uid_map, job_status_uid_map
            )
            for field, value in row.items()
        }

    def _remap_data(
        self,
        raw_data: RawBidData,
        uid_map: Dict[str, str],
        cdn_uid_map: Dict[str, str],
        job_status_uid_map: Dict[str, str],
    ) -> RawBidData:
        remapped_bid_row = self._remap_row(
            raw_data.bid_row, uid_map, cdn_uid_map, job_status_uid_map
        )
        remapped_bid_tables = {
            table: [
                self._remap_row(r, uid_map, cdn_uid_map, job_status_uid_map)
                for r in rows
            ]
            for table, rows in raw_data.bid_tables.items()
        }
        remapped_page_tables = {
            table: [
                self._remap_row(r, uid_map, cdn_uid_map, job_status_uid_map)
                for r in rows
            ]
            for table, rows in raw_data.page_tables.items()
        }
        return RawBidData(
            bid_row=remapped_bid_row,
            bid_tables=remapped_bid_tables,
            page_tables=remapped_page_tables,
        )

    def _parse_ost_xml(self, ost_path: str) -> RawBidData:
        tree = ET.parse(ost_path)
        root = tree.getroot()
        bid_elem = root.find("Bid")
        if bid_elem is None:
            raise ValueError("No Bid element found in OST file")
        bid_row = dict(bid_elem.attrib)
        bid_tables: Dict[str, List] = {}
        page_tables: Dict[str, List] = {}
        global_tables: Dict[str, List] = {}
        for section in BID_SECTIONS:
            rows: List[Dict[str, str]] = []
            container = bid_elem.find(section)
            if container is not None:
                singular = _singular(section)
                for child in container:
                    if child.tag == singular:
                        rows.append(dict(child.attrib))
            bid_tables[section] = rows
        pages_container = bid_elem.find("BidPages")
        bid_pages: List[Dict[str, str]] = []
        if pages_container is not None:
            for page_elem in pages_container:
                if page_elem.tag != "BidPage":
                    continue
                bid_pages.append(dict(page_elem.attrib))
                for section in PAGE_SECTIONS:
                    container = page_elem.find(section)
                    if container is not None:
                        singular = _singular(section)
                        for child in container:
                            if child.tag == singular:
                                page_tables.setdefault(section, []).append(
                                    dict(child.attrib)
                                )
        bid_tables["BidPages"] = bid_pages
        for section in BID_TAIL_SECTIONS:
            rows = []
            container = bid_elem.find(section)
            if container is not None:
                singular = _singular(section)
                for child in container:
                    if child.tag == singular:
                        rows.append(dict(child.attrib))
            bid_tables[section] = rows
        for section in GLOBAL_SECTIONS:
            rows = []
            container = root.find(section)
            if container is not None:
                singular = _singular(section)
                for child in container:
                    if child.tag == singular:
                        rows.append(dict(child.attrib))
            global_tables[section] = rows
        return RawBidData(
            bid_row=bid_row,
            bid_tables=bid_tables,
            page_tables=page_tables,
            global_tables=global_tables,
        )
