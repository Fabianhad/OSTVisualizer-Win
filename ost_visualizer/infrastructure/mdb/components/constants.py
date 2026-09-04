from typing import List, Set
from ..schema_contract import BID_SECTIONS

COVER_SHEET_PAGE_SELECTION_TYPE = 1


def hex_to_color_int(color: str) -> int:
    color = color.lstrip("#")
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)
    return r | (g << 8) | (b << 16)


NUMERIC_TYPE_SUBSTRINGS = (
    "int",
    "long",
    "short",
    "double",
    "float",
    "real",
    "bit",
    "byte",
    "counter",
    "currency",
    "single",
    "numeric",
    "decimal",
)
BID_TABLES_WRITE_ORDER: List[str] = (
    [t for t in BID_SECTIONS if t not in {"BidSettings", "BidTypGroupViews"}]
    + ["BidPages"]
    + ["BidSettings", "BidTypGroupViews"]
    + ["BidNamedViews", "BidHotLinks"]
)
HANDLED_SEPARATELY: Set[str] = {
    "BidTypGroupViews",
    "BidSettings",
    "BidTakeoffTotals",
    "OCRProps",
    "BidConditions",
    "BidConditionFolders",
    "BidLayers",
    "BidAreas",
    "BidZones",
    "BidPageFolders",
    "BidNamedViews",
}
LEGACY_BID_TABLES_COPIED_BY_DUPLICATION = (
    "AffectDPCTypGroupViews",
    "BidLaborCostCodeTotals",
    "BidTypicalGroupTotals",
    "Boost",
    "DPCCalcFilter",
    "BidLaborActivity",
    "BidLaborCostCodes",
    "BidDPCSubscribers",
    "BidNotes",
    "BidTimeCardStates",
)
TAKEOFF_REFERENCE_TABLES = (
    "BidDimensions",
    "BidALines",
    "BidArrows",
)
PAGE_ANNOTATION_TABLES = (
    "BidDimensions",
    "BidALines",
    "BidArrows",
    "BidHighlights",
    "BidTexts",
    "BidCallOuts",
    "BidAnnotationRects",
    "BidAnnotationOvals",
    "BidAnnotationPolygons",
    "BidAnnotationClouds",
    "BidAnnoInk",
    "BidLegends",
    "BidComments",
)
PAGE_AUXILIARY_CHILD_TABLES = (
    "BidPageSettings",
    "BidAreaTranslations",
    "BidMarkedPages",
    "BidPercents",
    "BidTakeoffTotals",
    "BidLaborCostCodeTotals",
    "BidTypicalGroupTotals",
    "BidTypGroupViews",
    "Boost",
    "DPCCalcFilter",
)
PAGE_DELETE_CHILD_TABLES = PAGE_ANNOTATION_TABLES + PAGE_AUXILIARY_CHILD_TABLES
PAGE_CONTENT_TABLES = (
    ("BidTakeoffs",)
    + PAGE_ANNOTATION_TABLES
    + (
        "BidNamedViews",
        "BidHotLinks",
    )
)
PAGE_DELETE_CONFIRMATION_TABLES = tuple(
    table for table in PAGE_CONTENT_TABLES if table != "BidLegends"
)
LAYER_REFERENCE_TABLES = (
    "BidConditions",
    "BidZones",
    "BidComments",
    "BidAnnotationClouds",
    "BidAnnotationOvals",
    "BidAnnotationPolygons",
    "BidAnnotationRects",
    "BidTexts",
    "BidHighlights",
    "BidHotLinks",
    "BidCallOuts",
)
