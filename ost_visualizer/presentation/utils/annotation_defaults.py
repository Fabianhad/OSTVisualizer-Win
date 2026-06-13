from ...application.dtos.insert_annotation_spec_dto import InsertAnnotationSpec
from ...domain.entities.annotation_style import (
    AnnotationStyle,
    normalize_annotation_color,
    normalize_annotation_line_width,
)
from .plan_tool_registry import PLAN_ANNOTATION_TOOL_SPECS

DIMENSION_ANNOTATION_WIDTH = 1.0
PLACEABLE_ANNOTATION_TYPES = frozenset(
    spec.annotation_type
    for spec in PLAN_ANNOTATION_TOOL_SPECS
    if spec.annotation_type is not None
)
_CURRENT_ANNOTATION_STYLE = AnnotationStyle()


def get_annotation_style() -> AnnotationStyle:
    return _CURRENT_ANNOTATION_STYLE


def set_annotation_style(color=None, line_width=None) -> AnnotationStyle:
    global _CURRENT_ANNOTATION_STYLE
    current = _CURRENT_ANNOTATION_STYLE
    next_color = (
        normalize_annotation_color(color, current.color)
        if color is not None
        else current.color
    )
    next_width = (
        normalize_annotation_line_width(line_width, current.line_width)
        if line_width is not None
        else current.line_width
    )
    _CURRENT_ANNOTATION_STYLE = AnnotationStyle(next_color, next_width)
    return _CURRENT_ANNOTATION_STYLE


def dimension_annotation_properties() -> dict:
    font_color = normalize_annotation_color(get_annotation_style().color)
    return {
        "BidTakeoffFromUID": "",
        "BidTakeoffToUID": "",
        "FontName": "Arial",
        "FontColor": font_color,
        "FontSize": 10,
        "FontBold": False,
        "FontItalic": False,
        "FontUnderline": False,
    }


def annotation_default_style(annotation_type: str) -> tuple[str, float]:
    style = get_annotation_style()
    if annotation_type == "dimension":
        return style.color, DIMENSION_ANNOTATION_WIDTH
    return style.color, style.line_width


def annotation_default_properties(annotation_type: str) -> dict:
    if annotation_type == "dimension":
        return dimension_annotation_properties()
    if annotation_type in ("line", "arrow"):
        return {
            "BidTakeoffFromUID": "",
            "BidTakeoffToUID": "",
        }
    return {}


def build_placed_annotation_spec(
    annotation_type: str, page_uid: str, position: list
) -> InsertAnnotationSpec | None:
    if annotation_type not in PLACEABLE_ANNOTATION_TYPES:
        return None
    color, width = annotation_default_style(annotation_type)
    return InsertAnnotationSpec(
        page_uid=page_uid,
        annotation_type=annotation_type,
        position=list(position),
        color=color,
        width=width,
        properties=annotation_default_properties(annotation_type),
    )
