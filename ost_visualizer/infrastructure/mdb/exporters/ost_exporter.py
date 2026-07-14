import logging
from collections import defaultdict
from typing import Dict, List, Tuple
from xml.etree.ElementTree import Element, SubElement
from ....application.dtos.export_dto import ExportErrorCode, ExportResultDto
from ....application.interfaces.i_uom_service import IUOMService
from ....domain.dtos.raw_bid_data_dto import RawBidData
from ....domain.entities.area import UNASSIGNED_AREA_UID
from ....domain.entities.condition import Condition
from ....domain.utils.position import parse_position
from ...parsers.ost_serializer import serialize_value
from ..raw_bid_integrity import (
    format_integrity_issues,
    prepare_raw_bid_data_for_export,
    validate_raw_bid_integrity,
)
from ..reference_validation import (
    collect_present_uids,
    filter_hotlink_rows,
    filter_page_referenced_rows,
)
from ..schema_contract import BID_SECTIONS as _BID_SECTIONS
from ..schema_contract import BID_TAIL_SECTIONS as _BID_TAIL_SECTIONS
from ..schema_contract import GLOBAL_SECTIONS as _GLOBAL_SECTIONS
from ..schema_contract import PAGE_SECTIONS as _PAGE_SECTIONS
from ..schema_contract import singular as _singular

logger = logging.getLogger(__name__)
_PRIORITY_ATTRS = [
    "UID",
    "BidUID",
    "BidPageUID",
    "BidConditionUID",
    "BidLayerUID",
    "BidZoneUID",
    "BidAreaUID",
    "BidTypAreaUID",
    "AreaUID",
    "TypAreaUID",
    "ParentUID",
    "CdnTypeUID",
]
_BID_CONDITION_ATTR_ORDER = [
    "UID",
    "BidUID",
    "BidConditionFolderUID",
    "BidLayerUID",
    "CdnTypeUID",
    "ExternalID",
    "GUID",
    "RefNo",
    "Name",
    "Notes",
    "Type",
    "Shape",
    "Pattern",
    "ColorLine",
    "ColorFill",
    "Width",
    "Height",
    "Spacing",
    "Thickness",
    "Rise",
    "Run",
    "Depth",
    "UOM1",
    "UOM2",
    "UOM3",
    "RoundUp",
    "Backout",
    "DropRun",
    "DropValue",
    "Grid",
    "GridSize1",
    "GridSize2",
    "Gap",
    "Connect",
    "ConnectTolerance",
    "Trim",
    "Curve",
    "SnapToGrid",
    "SnapToLinear",
    "SnapToLinearTolerance",
    "ManualLength",
    "MatAmount",
    "LabAmount",
    "SubAmount",
    "DirectQuantity1",
    "DirectQuantity2",
    "DirectQuantity3",
    "FontName",
    "FontSize",
    "FontBold",
    "FontItalic",
    "DisplayDimension",
    "RoundQuantity",
    "Quantity1",
    "Quantity2",
    "Quantity3",
    "IsTemplate",
    "ExcelCell1",
    "ExcelCell2",
    "ExcelCell3",
    "IsCurvedSegment",
    "OpenExternalID",
    "DisplayGridWhileDrawing",
    "TypGroupUID",
    "ShowTakeoff",
    "DisplaySize",
    "DisplayName",
]
_BID_PAGE_ATTR_ORDER = [
    "UID",
    "BidUID",
    "BidPageFolderUID",
    "Name",
    "ImagePath",
    "OverlayImagePath",
    "Show",
    "RasterDrawMethod",
    "ScaleStyle",
    "IsCustomScale",
    "ScaleFactor1",
    "ScaleFactor2",
    "Scale",
    "Width",
    "Height",
    "ZoomFac",
    "CurrentX",
    "CurrentY",
    "FlipX",
    "FlipY",
    "Rotation",
    "DeskewRotation",
    "OverlayOffsetX",
    "OverlayOffsetY",
    "OverlayRotation",
    "MultiPageCount",
    "Index1",
    "Sequence",
    "Invert",
    "Bitonal",
    "DigitizerNX1",
    "DigitizerNY1",
    "DigitizerNX2",
    "DigitizerNY2",
    "DigitizerWidth",
    "DigitizerHeight",
    "DigitizerResX",
    "DigitizerResY",
    "WasSent",
    "MasterPageUID",
    "TypicalPageRepeats",
    "GUID",
    "OverlayRect",
    "OverlayResized",
    "DeskewRotationOverlay",
    "ZoomFlag",
    "SheetNo",
    "OCRState",
    "OCRUID",
]
_BID_LAYER_ATTR_ORDER = [
    "UID",
    "BidUID",
    "IsTemplate",
    "Name",
    "Show",
    "IsLocked",
    "Sequence",
]
_CDN_TYPE_ATTR_ORDER = ["UID", "Name", "ExpandState"]
_EMPLOYEE_ATTR_ORDER = [
    "UID",
    "PayClassUID",
    "AccessLevelUID",
    "EmployeeNo",
    "FirstName",
    "LastName",
    "EnableLogin",
    "LoginName",
    "Password",
    "Address1",
    "Address2",
    "City",
    "State",
    "Zip",
    "HomePhone",
    "MobilePhone",
    "EMail",
]
_PAY_CLASS_ATTR_ORDER = ["UID", "Name"]
_ACCESS_LEVEL_ATTR_ORDER = ["UID", "Description", "Privileges"]
_BID_SETTING_ATTR_ORDER = [
    "UID",
    "BidUID",
    "BidPageSelectedUID",
    "STSGUID",
    "STSServerName",
    "STSClientName",
]
_BID_CONDITION_FOLDER_ATTR_ORDER = [
    "UID",
    "BidUID",
    "ParentUID",
    "Name",
    "Description",
    "ExpandState",
]
_BID_AREA_ATTR_ORDER = [
    "UID",
    "BidUID",
    "ParentUID",
    "Name",
    "Sequence",
    "WasSent",
    "GUID",
]
_BID_PAGE_FOLDER_ATTR_ORDER = [
    "UID",
    "BidUID",
    "ParentUID",
    "Name",
    "Description",
    "WasSent",
    "GUID",
    "ExpandState",
]
_BID_ZONE_ATTR_ORDER = [
    "UID",
    "BidUID",
    "BidLayerUID",
    "ExternalID",
    "Name",
    "Notes",
    "Pattern",
    "ColorLine",
    "ColorFill",
    "Spacing",
    "IsNegativeValues",
    "Sequence",
    "GUID",
]
_BID_DIMENSION_ATTR_ORDER = [
    "UID",
    "BidUID",
    "BidPageUID",
    "BidTakeoffFromUID",
    "BidTakeoffToUID",
    "Position",
    "FontName",
    "FontColor",
    "FontSize",
    "FontBold",
    "FontItalic",
    "FontUnderline",
]
_BID_NAMED_VIEW_ATTR_ORDER = [
    "UID",
    "BidUID",
    "BidPageUID",
    "Name",
    "Position",
]
_BID_HOT_LINK_ATTR_ORDER = [
    "UID",
    "BidUID",
    "BidPageUID",
    "BidPageViewUID",
    "BidLayerUID",
    "Color",
    "Position",
]
_BID_ALINE_ATTR_ORDER = [
    "UID",
    "BidUID",
    "BidPageUID",
    "BidTakeoffFromUID",
    "BidTakeoffToUID",
    "Position",
    "Color",
    "Width",
]
_BID_LEGEND_ATTR_ORDER = [
    "UID",
    "BidUID",
    "BidPageUID",
    "Position",
    "Rotation",
    "FontName",
    "FontColor",
    "FontSize",
    "FontBold",
    "FontItalic",
    "FontUnderline",
    "IsShowTotals",
    "MoveToCorner",
]
_BID_TAKEOFF_ATTR_ORDER = [
    "UID",
    "BidUID",
    "BidConditionUID",
    "BidZoneUID",
    "BidPageUID",
    "BidAreaUID",
    "BidTypAreaUID",
    "ParentUID",
    "No",
    "Quantity",
    "Count",
    "Rotation",
    "Position",
    "GridOffsetX",
    "GridOffsetY",
    "GridRotation",
    "IsNegativeQuantity",
    "FontName",
    "FontColor",
    "FontSize",
    "FontBold",
    "FontItalic",
    "FontUnderline",
    "TypGroupTakeoffUID",
    "TypPageTakeoffUID",
    "TakeoffModified",
    "TypGroupUID",
    "TypGroupMarkerUID",
    "FlipX",
    "FlipY",
    "GUID",
    "NameFontName",
    "NameFontColor",
    "NameFontSize",
    "NameFontBold",
    "NameFontItalic",
    "NameFontUnderline",
    "Curve",
]
_BID_ATTR_ORDER = [
    "UID",
    "BidProjectUID",
    "ParentBidUID",
    "OrigBidProjectUID",
    "OrigParentBidUID",
    "JobStatusUID",
    "EstimatorUID",
    "PrManagerUID",
    "JobSiteManagerUID",
    "SourceBidUID",
    "ExternalID",
    "QuickBidDB",
    "BidNo",
    "BidType",
    "JobID",
    "JobName",
    "ImageFolder",
    "Notes",
    "IsAccepted",
    "RecalcNeeded",
    "CreateDateTime",
    "ModDateTime",
    "PriceUsing",
    "PriceUsingDatabase",
    "PriceUsingWorksheet",
    "TakeoffIncrements",
    "HoursPerDay",
    "MeasureBase",
    "WeekStartDay",
    "QuantitiesInLegend",
    "JobSendRec",
    "ScaleStyle",
    "IsCustomScale",
    "ScaleFactor1",
    "ScaleFactor2",
    "PageScale",
    "PageWidth",
    "PageHeight",
    "LastReceiveDateTime",
    "LastSendDateTime",
    "DeliverEntireBid",
    "EstimatedDays",
    "Percent",
    "ProjectOver",
    "DPCMode",
    "IsDPCUpdated",
    "IgnoreBidAreas",
    "SendImageFiles",
    "HasSTSClash",
    "SRPending",
    "IsUnlocked",
    "FullBidSent",
    "TypicalType",
    "GUID",
    "BidDate",
    "CopyFromBidNO",
    "CopyTimestamp",
    "CoverSheetSelItemType",
    "CoverSheetSelItemUID",
    "LegendFlags",
    "IsCalculatedForSlope",
    "IsCalculatedForLaborCostCodeTotals",
]
_ZERO_DEFAULT_FIELDS = {
    "AreaUID",
    "TypAreaUID",
    "ParentUID",
    "BidProjectUID",
    "ParentBidUID",
    "OrigBidProjectUID",
    "OrigParentBidUID",
    "EstimatorUID",
    "PrManagerUID",
    "JobSiteManagerUID",
    "ExternalID",
    "OpenExternalID",
    "TypGroupUID",
    "BidZoneUID",
    "BidAreaUID",
    "BidTypAreaUID",
    "TypGroupTakeoffUID",
    "TypPageTakeoffUID",
    "TypGroupMarkerUID",
    "BidTakeoffFromUID",
    "BidTakeoffToUID",
    "MasterPageUID",
    "BidPageFolderUID",
    "BidConditionFolderUID",
    "CdnTypeUID",
    "BidLayerUID",
    "BidPageUID",
    "BidConditionUID",
    "BidUID",
    "JobStatusUID",
    "PayClassUID",
    "AccessLevelUID",
    "CoverSheetSelItemUID",
    "BidPageSelectedUID",
    "OCRUID",
    "OCRState",
}
_STRING_FIELDS = {
    "SourceBidUID",
    "QuickBidDB",
    "PriceUsingDatabase",
    "PriceUsingWorksheet",
    "STSServerName",
    "STSClientName",
    "ImageFolder",
    "ImagePath",
    "OverlayImagePath",
    "SheetNo",
    "Notes",
    "Name",
    "Description",
    "JobID",
    "JobName",
    "ExcelCell1",
    "ExcelCell2",
    "ExcelCell3",
    "FontName",
    "NameFontName",
    "GUID",
    "STSGUID",
    "OverlayRect",
    "OverlayResized",
    "Position",
    "BFperLF",
    "ALState",
}
_OMIT_IF_EMPTY_FIELDS = {
    "BFperLF",
    "ALState",
}
_OMIT_IF_EMPTY_BY_ELEMENT = {
    "BidNamedView": frozenset({"Color", "Origin"}),
}
_XML_NEWLINE = "\r\n"
_ALWAYS_SELF_CLOSE_CHILD = frozenset({"BidAreas", "BidTypAreas", "BidTypAreaCounts"})
_SELF_CLOSING_BID_SECTIONS = frozenset(
    {
        "BidPlanRooms",
        "UserMasterConditions",
        "BidConditionUser",
    }
)
_SELF_CLOSING_PAGE_SECTIONS = frozenset(
    {
        "BidHighlights",
        "BidTexts",
        "BidDimensions",
        "BidArrows",
        "BidALines",
        "BidCallOuts",
        "BidAnnotationRects",
        "BidAnnotationOvals",
        "BidAnnotationPolygons",
        "BidAnnotationClouds",
        "BidAnnoInk",
    }
)
_COLUMN_NAME_MAP = {
    "CopyTimeStamp": "CopyTimestamp",
}
_ATTR_ORDER_MAP: Dict[str, List[str]] = {
    "BidCondition": _BID_CONDITION_ATTR_ORDER,
    "BidPage": _BID_PAGE_ATTR_ORDER,
    "BidTakeoff": _BID_TAKEOFF_ATTR_ORDER,
    "Bid": _BID_ATTR_ORDER,
    "BidLayer": _BID_LAYER_ATTR_ORDER,
    "CdnType": _CDN_TYPE_ATTR_ORDER,
    "Employee": _EMPLOYEE_ATTR_ORDER,
    "PayClass": _PAY_CLASS_ATTR_ORDER,
    "AccessLevel": _ACCESS_LEVEL_ATTR_ORDER,
    "BidSetting": _BID_SETTING_ATTR_ORDER,
    "BidConditionFolder": _BID_CONDITION_FOLDER_ATTR_ORDER,
    "BidArea": _BID_AREA_ATTR_ORDER,
    "BidPageFolder": _BID_PAGE_FOLDER_ATTR_ORDER,
    "BidZone": _BID_ZONE_ATTR_ORDER,
    "BidLegend": _BID_LEGEND_ATTR_ORDER,
    "BidNamedView": _BID_NAMED_VIEW_ATTR_ORDER,
    "BidHotLink": _BID_HOT_LINK_ATTR_ORDER,
    "BidDimension": _BID_DIMENSION_ATTR_ORDER,
    "BidALine": _BID_ALINE_ATTR_ORDER,
}


def _sort_attrs(attrs: Dict[str, str], element_type: str = "") -> Dict[str, str]:
    attr_order = _ATTR_ORDER_MAP.get(element_type, _PRIORITY_ATTRS)
    seen: set = set()
    ordered: Dict[str, str] = {}
    for key in attr_order:
        if key in attrs:
            ordered[key] = attrs[key]
            seen.add(key)
    for key in sorted(attrs):
        if key not in seen:
            ordered[key] = attrs[key]
    return ordered


def _normalize_nulls(row: Dict[str, str]) -> Dict[str, str]:
    result = {}
    for key, value in row.items():
        if value in ("NULL", None):
            result[key] = "0" if key in _ZERO_DEFAULT_FIELDS else ""
        elif value == "" and key in _ZERO_DEFAULT_FIELDS:
            result[key] = "0"
        else:
            result[key] = value
    return result


def _normalize_table_rows(tables: Dict[str, List]) -> Dict[str, List]:
    result = {}
    for table_name, rows in tables.items():
        if isinstance(rows, list):
            result[table_name] = [_normalize_nulls(row) for row in rows]
        else:
            result[table_name] = rows
    return result


def _filter_empty_attrs(row: Dict[str, str], element_type: str = "") -> Dict[str, str]:
    element_omit_fields = _OMIT_IF_EMPTY_BY_ELEMENT.get(element_type, frozenset())
    return {
        key: value
        for key, value in row.items()
        if not (
            key in _OMIT_IF_EMPTY_FIELDS.union(element_omit_fields)
            and value in ("", "NULL")
        )
    }


def _normalize_column_names(row: Dict[str, str]) -> Dict[str, str]:
    result = {}
    for key, value in row.items():
        normalized_key = _COLUMN_NAME_MAP.get(key, key)
        result[normalized_key] = value
    return result


def _build_section(
    parent: Element,
    table_name: str,
    rows: List[Dict[str, str]],
    self_closing: bool = False,
) -> Element:
    container = SubElement(parent, table_name)
    item_tag = _singular(table_name)
    for row in rows:
        filtered_row = _filter_empty_attrs(row, item_tag)
        sorted_row = _sort_attrs(filtered_row, element_type=item_tag)
        SubElement(container, item_tag, sorted_row)
    if table_name in _ALWAYS_SELF_CLOSE_CHILD:
        SubElement(container, table_name)
    return container


def _group_by_key(
    rows: List[Dict[str, str]], key: str
) -> Dict[str, List[Dict[str, str]]]:
    grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row.get(key, "")].append(row)
    return grouped


def _escape_xml_attr(text: str) -> str:
    if not text:
        return text
    text = text.replace("&", "&amp;")
    text = text.replace("'", "&apos;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    text = text.replace("\r", "&#xd;")
    text = text.replace("\n", "&#xa;")
    return text


def _write_element(file_obj, elem: Element) -> None:
    attrs = []
    for key, value in elem.attrib.items():
        escaped_value = _escape_xml_attr(str(value))
        attrs.append(f'{key}="{escaped_value}"')
    attr_str = " " + " ".join(attrs) if attrs else ""
    children = list(elem)
    text = elem.text or ""
    if not children and not text.strip():
        file_obj.write(f"<{elem.tag}{attr_str}/>{_XML_NEWLINE}")
    elif not children:
        escaped_text = _escape_xml_attr(text)
        file_obj.write(
            f"<{elem.tag}{attr_str}>{escaped_text}</{elem.tag}>{_XML_NEWLINE}"
        )
    else:
        file_obj.write(f"<{elem.tag}{attr_str}>{_XML_NEWLINE}")
        for child in children:
            _write_element(file_obj, child)
        file_obj.write(f"</{elem.tag}>{_XML_NEWLINE}")


class OstExporter:
    def __init__(self, uom_service: IUOMService):
        self._uom_service = uom_service

    def export(
        self,
        raw_data: RawBidData,
        output_path: str,
        on_progress=None,
    ) -> ExportResultDto:
        try:
            raw_data = prepare_raw_bid_data_for_export(raw_data)
            integrity_issues = validate_raw_bid_integrity(raw_data)
            if integrity_issues:
                return ExportResultDto(
                    success=False,
                    format_name="OST",
                    error_message=(
                        "Cannot export OST because database references are invalid: "
                        f"{format_integrity_issues(integrity_issues)}"
                    ),
                    error_code=ExportErrorCode.UNEXPECTED,
                )
            root = Element("XML_ROOT")
            SubElement(root, "OST", Version="3.2.0")
            bid_row = _normalize_column_names(_normalize_nulls(raw_data.bid_row))
            bid_tables = _normalize_table_rows(raw_data.bid_tables)
            page_tables = _normalize_table_rows(raw_data.page_tables)
            global_tables = _normalize_table_rows(raw_data.global_tables)
            if "ExternalID" not in bid_row or not bid_row["ExternalID"]:
                bid_row["ExternalID"] = "0"
            sorted_bid_row = _sort_attrs(bid_row, element_type="Bid")
            bid_elem = SubElement(root, "Bid", sorted_bid_row)
            self._build_bid_sections(bid_elem, bid_tables, page_tables)
            self._build_pages_section(bid_elem, bid_tables, page_tables)
            self._build_tail_sections(bid_elem, bid_tables)
            self._build_global_sections(root, bid_tables, global_tables, bid_row)
            if on_progress:
                on_progress(1, 1, "Writing OST")
            with open(output_path, "w", encoding="utf-8", newline="") as f:
                _write_element(f, root)
            return ExportResultDto(success=True, format_name="OST")
        except Exception as exc:
            logger.exception("Failed to export OST file to %s", output_path)
            return ExportResultDto(
                success=False,
                format_name="OST",
                error_message=str(exc),
                error_code=ExportErrorCode.UNEXPECTED,
            )

    def _build_bid_sections(
        self,
        bid_elem: Element,
        bid_tables: Dict[str, List],
        page_tables: Dict[str, List],
    ) -> None:
        for table_name in _BID_SECTIONS:
            rows = bid_tables.get(table_name, [])
            if table_name == "BidEmployees" and not rows:
                continue
            sorted_rows = self._sort_rows(table_name, rows)
            self_closing = table_name in _SELF_CLOSING_BID_SECTIONS
            if table_name == "BidConditions":
                self._build_conditions_section(
                    bid_elem, sorted_rows, bid_tables, page_tables
                )
            else:
                _build_section(bid_elem, table_name, sorted_rows, self_closing)

    def _sort_rows(
        self, table_name: str, rows: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        if not rows:
            return rows
        rows_copy = list(rows)
        if table_name == "BidLayers":
            rows_copy.sort(key=lambda x: int(x.get("Sequence", 0)))
        elif table_name == "BidAreas":
            rows_copy.sort(key=lambda x: int(x.get("Sequence", 0)), reverse=True)
        elif table_name == "BidPageFolders":
            rows_copy.sort(key=lambda x: int(x.get("UID", 0)), reverse=True)
        elif table_name == "BidConditions":
            rows_copy.sort(key=lambda x: int(x.get("UID", 0)))
        elif table_name in (
            "BidTakeoffs",
            "BidHighlights",
            "BidALines",
            "BidArrows",
            "BidTexts",
            "BidCallOuts",
            "BidDimensions",
            "BidAnnotationRects",
            "BidAnnotationOvals",
            "BidAnnotationPolygons",
            "BidAnnotationClouds",
            "BidAnnoInk",
            "BidLegends",
            "BidComments",
        ):
            rows_copy.sort(key=lambda x: int(x.get("UID", 0)), reverse=True)
        elif table_name == "BidPages":
            rows_copy.sort(key=lambda x: int(x.get("Sequence", 0)))
        elif table_name in ("BidNamedViews", "BidHotLinks"):
            rows_copy.sort(key=lambda x: int(x.get("UID", 0)), reverse=True)
        return rows_copy

    def _build_conditions_section(
        self,
        bid_elem: Element,
        condition_rows: List[Dict[str, str]],
        bid_tables: Dict[str, List],
        page_tables: Dict[str, List],
    ) -> None:
        container = SubElement(bid_elem, "BidConditions")
        all_takeoffs = page_tables.get("BidTakeoffs", [])
        takeoffs_by_condition: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        takeoffs_by_parent: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        for _t in all_takeoffs:
            takeoffs_by_condition[_t.get("BidConditionUID", "")].append(_t)
            takeoffs_by_parent[_t.get("ParentUID", "")].append(_t)
        condition_props = {}
        for cdn_row in condition_rows:
            cdn_uid = cdn_row.get("UID", "")
            condition_props[cdn_uid] = {
                "type": int(cdn_row.get("Type", "0") or "0"),
                "width": float(cdn_row.get("Width", "0") or "0"),
                "depth": float(cdn_row.get("Depth", "0") or "0"),
                "rise": float(cdn_row.get("Rise", "0") or "0"),
                "run": float(cdn_row.get("Run", "0") or "0"),
                "grid_size1": float(cdn_row.get("GridSize1", "0") or "0"),
                "grid_size2": float(cdn_row.get("GridSize2", "0") or "0"),
                "gap": float(cdn_row.get("Gap", "0") or "0"),
                "round_quantity": str(cdn_row.get("RoundQuantity", "0") or "0")
                in ("1", "True", "true"),
                "round_up": float(cdn_row.get("RoundUp", "0") or "0"),
            }
        area_condition_uid = 1
        for cdn_row in condition_rows:
            if "ExternalID" not in cdn_row or not cdn_row["ExternalID"]:
                cdn_row["ExternalID"] = "0"
            filtered_cdn = _filter_empty_attrs(cdn_row, "BidCondition")
            sorted_cdn = _sort_attrs(filtered_cdn, element_type="BidCondition")
            cdn_elem = SubElement(container, "BidCondition", sorted_cdn)
            cdn_uid = cdn_row.get("UID", "")
            _props = condition_props[cdn_uid]
            condition_type = _props["type"]
            width = _props["width"]
            depth = _props["depth"]
            rise = _props["rise"]
            run = _props["run"]
            grid_size1 = _props["grid_size1"]
            grid_size2 = _props["grid_size2"]
            gap = _props["gap"]
            round_quantity = _props["round_quantity"]
            round_up = _props["round_up"]
            calc_type1 = int(cdn_row.get("Quantity1", "0") or "0")
            calc_type2 = int(cdn_row.get("Quantity2", "0") or "0")
            calc_type3 = int(cdn_row.get("Quantity3", "0") or "0")
            uom1 = int(cdn_row.get("UOM1", "0") or "0")
            uom2 = int(cdn_row.get("UOM2", "0") or "0")
            uom3 = int(cdn_row.get("UOM3", "0") or "0")
            height = float(cdn_row.get("Height", "0") or "0")
            thickness = float(cdn_row.get("Thickness", "0") or "0")
            condition_takeoffs = takeoffs_by_condition.get(cdn_uid, [])
            area_container = SubElement(cdn_elem, "BidAreaConditions")
            area_totals: Dict[Tuple[str, str], List[float]] = {}
            if condition_takeoffs:
                if condition_type == Condition.TYPE_AREA:
                    main_takeoffs = [
                        t
                        for t in condition_takeoffs
                        if (t.get("ParentUID", "0") or "0") == "0"
                    ]
                    for takeoff in main_takeoffs:
                        area_key = (
                            takeoff.get("BidAreaUID", UNASSIGNED_AREA_UID)
                            or UNASSIGNED_AREA_UID,
                            takeoff.get("BidTypAreaUID", UNASSIGNED_AREA_UID)
                            or UNASSIGNED_AREA_UID,
                        )
                        position = parse_position(takeoff.get("Position", ""))
                        takeoff_uid = takeoff.get("UID", "")
                        children = takeoffs_by_parent.get(takeoff_uid, [])
                        hole_positions = []
                        att_footprint = 0.0
                        att_perimeter = 0.0
                        for child in children:
                            child_cdn_uid = child.get("BidConditionUID", "")
                            if child_cdn_uid == cdn_uid:
                                child_pos = parse_position(child.get("Position", ""))
                                if child_pos:
                                    hole_positions.append(child_pos)
                            child_props = condition_props.get(child_cdn_uid, {})
                            if child_props.get("type") == Condition.TYPE_ATTACHMENT:
                                w = child_props.get("width", 0.0)
                                d = child_props.get("depth", 0.0)
                                att_footprint += w * d
                                att_perimeter += 2.0 * (w + d)
                        q1, q2, q3 = self._uom_service.calculate_condition_quantities(
                            condition_type=condition_type,
                            calc_type1=calc_type1,
                            calc_type2=calc_type2,
                            calc_type3=calc_type3,
                            uom1=uom1,
                            uom2=uom2,
                            uom3=uom3,
                            width=width,
                            height=height,
                            depth=depth,
                            thickness=thickness,
                            position=position,
                            hole_positions=hole_positions if hole_positions else None,
                            attachment_footprint=att_footprint,
                            attachment_perimeter=att_perimeter,
                            rise=rise,
                            run=run,
                            grid_size1=grid_size1,
                            grid_size2=grid_size2,
                            gap=gap,
                            round_quantity=round_quantity,
                            round_up=round_up,
                        )
                        if area_key not in area_totals:
                            area_totals[area_key] = [0.0, 0.0, 0.0]
                        area_totals[area_key][0] += q1
                        area_totals[area_key][1] += q2
                        area_totals[area_key][2] += q3
                else:
                    for takeoff in condition_takeoffs:
                        area_key = (
                            takeoff.get("BidAreaUID", UNASSIGNED_AREA_UID)
                            or UNASSIGNED_AREA_UID,
                            takeoff.get("BidTypAreaUID", UNASSIGNED_AREA_UID)
                            or UNASSIGNED_AREA_UID,
                        )
                        position = parse_position(takeoff.get("Position", ""))
                        q1, q2, q3 = self._uom_service.calculate_condition_quantities(
                            condition_type=condition_type,
                            calc_type1=calc_type1,
                            calc_type2=calc_type2,
                            calc_type3=calc_type3,
                            uom1=uom1,
                            uom2=uom2,
                            uom3=uom3,
                            width=width,
                            height=height,
                            depth=depth,
                            thickness=thickness,
                            position=position,
                            rise=rise,
                            run=run,
                            grid_size1=grid_size1,
                            grid_size2=grid_size2,
                            gap=gap,
                            curve=int(takeoff.get("Curve", "-1") or "-1"),
                            round_quantity=round_quantity,
                            round_up=round_up,
                        )
                        if area_key not in area_totals:
                            area_totals[area_key] = [0.0, 0.0, 0.0]
                        area_totals[area_key][0] += q1
                        area_totals[area_key][1] += q2
                        area_totals[area_key][2] += q3
            if not area_totals:
                area_totals[("0", "0")] = [0.0, 0.0, 0.0]
            for (area_uid, typ_area_uid), totals in area_totals.items():
                area_condition = {
                    "UID": str(area_condition_uid),
                    "BidConditionUID": cdn_uid,
                    "AreaUID": area_uid,
                    "TypAreaUID": typ_area_uid,
                    "Quantity1": serialize_value(totals[0]),
                    "Quantity2": serialize_value(totals[1]),
                    "Quantity3": serialize_value(totals[2]),
                }
                sorted_area = _sort_attrs(
                    area_condition, element_type="BidAreaCondition"
                )
                SubElement(area_container, "BidAreaCondition", sorted_area)
                area_condition_uid += 1

    def _build_pages_section(
        self,
        bid_elem: Element,
        bid_tables: Dict[str, List],
        page_tables: Dict[str, List],
    ) -> None:
        pages_container = SubElement(bid_elem, "BidPages")
        page_rows = bid_tables.get("BidPages", [])
        if not page_rows:
            page_rows = page_tables.get("BidPages", [])
        page_rows = sorted(page_rows, key=lambda x: int(x.get("Sequence", 0)))
        grouped_page_data: Dict[str, Dict[str, List]] = {}
        for table_name in _PAGE_SECTIONS:
            rows = page_tables.get(table_name, [])
            by_page = _group_by_key(rows, "BidPageUID")
            for page_uid, page_rows_for_table in by_page.items():
                grouped_page_data.setdefault(page_uid, {})[table_name] = (
                    self._sort_rows(table_name, page_rows_for_table)
                )
        for page_row in page_rows:
            filtered_page = _filter_empty_attrs(page_row, "BidPage")
            sorted_page = _sort_attrs(filtered_page, element_type="BidPage")
            page_uid = page_row.get("UID", "")
            page_elem = SubElement(pages_container, "BidPage", sorted_page)
            page_data = grouped_page_data.get(page_uid, {})
            for table_name in _PAGE_SECTIONS:
                rows = page_data.get(table_name, [])
                self_closing = table_name in _SELF_CLOSING_PAGE_SECTIONS
                _build_section(page_elem, table_name, rows, self_closing)

    def _build_tail_sections(
        self, bid_elem: Element, bid_tables: Dict[str, List]
    ) -> None:
        valid_page_uids = collect_present_uids(bid_tables.get("BidPages", []))
        named_view_rows = filter_page_referenced_rows(
            bid_tables.get("BidNamedViews", []),
            valid_page_uids,
        )
        valid_named_view_uids = collect_present_uids(named_view_rows)
        for table_name in _BID_TAIL_SECTIONS:
            if table_name == "BidNamedViews":
                rows = named_view_rows
            elif table_name == "BidHotLinks":
                rows = filter_hotlink_rows(
                    bid_tables.get(table_name, []),
                    valid_page_uids,
                    valid_named_view_uids,
                )
            else:
                rows = bid_tables.get(table_name, [])
            sorted_rows = self._sort_rows(table_name, rows)
            _build_section(bid_elem, table_name, sorted_rows, self_closing=True)

    def _build_global_sections(
        self,
        root: Element,
        bid_tables: Dict[str, List],
        global_tables: Dict[str, List],
        bid_row: Dict[str, str],
    ) -> None:
        job_status_uid = bid_row.get("JobStatusUID", "")
        condition_rows = bid_tables.get("BidConditions", [])
        bid_employee_rows = bid_tables.get("BidEmployees", [])
        used_cdn_types = {
            c.get("CdnTypeUID") for c in condition_rows if c.get("CdnTypeUID")
        }
        used_employee_uids = {
            uid
            for uid in (
                bid_row.get("EstimatorUID", ""),
                bid_row.get("PrManagerUID", ""),
                bid_row.get("JobSiteManagerUID", ""),
            )
            if uid and uid != "0"
        }
        used_employee_uids.update(
            row.get("EmployeeUID", "")
            for row in bid_employee_rows
            if row.get("EmployeeUID") and row.get("EmployeeUID") != "0"
        )
        employee_rows = [
            row
            for row in global_tables.get("Employees", [])
            if row.get("UID") in used_employee_uids
        ]
        used_pay_class_uids = {
            row.get("PayClassUID", "")
            for row in employee_rows + bid_employee_rows
            if row.get("PayClassUID") and row.get("PayClassUID") != "0"
        }
        used_access_level_uids = {
            row.get("AccessLevelUID", "")
            for row in employee_rows
            if row.get("AccessLevelUID") and row.get("AccessLevelUID") != "0"
        }
        for table_name in _GLOBAL_SECTIONS:
            rows = global_tables.get(table_name, [])
            if table_name == "Employees":
                rows = employee_rows
            elif table_name == "PayClasses":
                rows = [r for r in rows if r.get("UID") in used_pay_class_uids]
            elif table_name == "AccessLevels":
                rows = [r for r in rows if r.get("UID") in used_access_level_uids]
            elif table_name == "CdnTypes":
                rows = [r for r in rows if r.get("UID") in used_cdn_types]
            elif table_name == "JobStatuses":
                rows = [r for r in rows if r.get("UID") == job_status_uid]
            if rows or table_name == "AccessLevels":
                _build_section(root, table_name, rows)
