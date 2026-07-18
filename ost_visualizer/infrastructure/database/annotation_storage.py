from types import MappingProxyType
from ...domain.entities.annotation import (
    ANNOTATION_TYPE_ARROW,
    ANNOTATION_TYPE_CALLOUT,
    ANNOTATION_TYPE_CLOUD,
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_HIGHLIGHT,
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_INK,
    ANNOTATION_TYPE_LINE,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_OVAL,
    ANNOTATION_TYPE_POLYGON,
    ANNOTATION_TYPE_RECT,
    ANNOTATION_TYPE_TEXT,
)

ANNOTATION_TABLE_BY_TYPE = MappingProxyType(
    {
        ANNOTATION_TYPE_LINE: "BidALines",
        ANNOTATION_TYPE_ARROW: "BidArrows",
        ANNOTATION_TYPE_DIMENSION: "BidDimensions",
        ANNOTATION_TYPE_CLOUD: "BidAnnotationClouds",
        ANNOTATION_TYPE_POLYGON: "BidAnnotationPolygons",
        ANNOTATION_TYPE_RECT: "BidAnnotationRects",
        ANNOTATION_TYPE_OVAL: "BidAnnotationOvals",
        ANNOTATION_TYPE_INK: "BidAnnoInk",
        ANNOTATION_TYPE_TEXT: "BidTexts",
        ANNOTATION_TYPE_HIGHLIGHT: "BidHighlights",
        ANNOTATION_TYPE_NAMED_VIEW: "BidNamedViews",
        ANNOTATION_TYPE_HOTLINK: "BidHotLinks",
        ANNOTATION_TYPE_CALLOUT: "BidCallOuts",
    }
)
ANNOTATION_TYPE_BY_TABLE = MappingProxyType(
    {
        table: annotation_type
        for annotation_type, table in ANNOTATION_TABLE_BY_TYPE.items()
    }
)
