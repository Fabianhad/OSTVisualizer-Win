from typing import List, Tuple

BID_SECTIONS: List[str] = [
    "BidPlanRooms",
    "BidAreas",
    "BidTypAreas",
    "BidConditionFolders",
    "BidPageFolders",
    "BidSettings",
    "BidEmployees",
    "BidLayers",
    "BidTypAreaCounts",
    "BidConditions",
    "UserMasterConditions",
    "BidConditionUser",
    "BidZones",
    "BidTypGroupViews",
    "OCRProps",
]
PAGE_SECTIONS: List[str] = [
    "BidTakeoffs",
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
    "BidLegends",
    "BidPageSettings",
    "BidAreaTranslations",
    "BidMarkedPages",
    "BidComments",
]
BID_TAIL_SECTIONS: List[str] = ["BidNamedViews", "BidHotLinks"]
GLOBAL_SECTIONS: List[str] = [
    "Employees",
    "PayClasses",
    "AccessLevels",
    "CdnTypes",
    "JobStatuses",
]
RAW_BID_TABLES: List[str] = BID_SECTIONS + ["BidPages"] + BID_TAIL_SECTIONS
RAW_GLOBAL_TABLES: List[str] = [
    "Employees",
    "PayClasses",
    "AccessLevels",
    "CdnTypes",
    "JobStatuses",
]
_SINGULAR_OVERRIDES = {
    "JobStatuses": "JobStatuse",
    "PayClasses": "PayClass",
}
DEFAULT_LAYER_ROWS: Tuple[Tuple[str, bool, bool, int], ...] = (
    ("Default", True, True, 2),
    ("Annotation", True, True, 1),
    ("Image", True, True, 0),
    ("Comments", True, True, 3),
)
# OST XML uses this spelling while the Access and SQL schemas use CopyTimeStamp.
DATABASE_TO_OST_XML_COLUMN = {
    "CopyTimeStamp": "CopyTimestamp",
}
OST_XML_TO_DATABASE_COLUMN = {
    xml_name: database_name
    for database_name, xml_name in DATABASE_TO_OST_XML_COLUMN.items()
}


def singular(table_name: str) -> str:
    if table_name in _SINGULAR_OVERRIDES:
        return _SINGULAR_OVERRIDES[table_name]
    if table_name.endswith("s"):
        return table_name[:-1]
    return table_name
