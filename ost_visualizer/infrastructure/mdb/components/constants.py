from typing import List, Set
from ..ost_schema import BID_SECTIONS


def encode_position(position: List[float]) -> bytes:
    parts = []
    for v in position:
        rounded = round(v, 3)
        parts.append(f"{rounded:g}")
    return (";".join(parts) + "\n").encode("latin-1")


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
    [t for t in BID_SECTIONS if t != "BidSettings"]
    + ["BidPages"]
    + ["BidSettings"]
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
