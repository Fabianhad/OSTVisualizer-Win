from collections.abc import Mapping
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
_STYLE_KEYS = tuple(sorted(PLACEABLE_ANNOTATION_TYPES))
_ANNOTATION_STYLES: dict[str, AnnotationStyle] = {
    annotation_type: AnnotationStyle() for annotation_type in _STYLE_KEYS
}


def _normalize_annotation_type(annotation_type: str) -> str:
    text = str(annotation_type or "").strip().lower()
    if text not in PLACEABLE_ANNOTATION_TYPES:
        raise ValueError(f"Unknown annotation tool type: {annotation_type!r}")
    return text


def _style_for(annotation_type: str) -> AnnotationStyle:
    key = _normalize_annotation_type(annotation_type)
    return _ANNOTATION_STYLES[key]


def get_annotation_style_for_tool(annotation_type: str) -> AnnotationStyle:
    return _style_for(annotation_type)


def get_annotation_styles_by_tool() -> dict[str, AnnotationStyle]:
    return {key: _style_for(key) for key in _STYLE_KEYS}


def set_annotation_style_for_tool(
    annotation_type: str,
    color=None,
    line_width=None,
) -> AnnotationStyle:
    key = _normalize_annotation_type(annotation_type)
    current = _style_for(key)
    next_style = AnnotationStyle(
        color=(
            normalize_annotation_color(color, current.color)
            if color is not None
            else current.color
        ),
        line_width=(
            normalize_annotation_line_width(line_width, current.line_width)
            if line_width is not None
            else current.line_width
        ),
    )
    _ANNOTATION_STYLES[key] = next_style
    return next_style


def set_annotation_styles_by_tool(
    styles: Mapping[str, AnnotationStyle | Mapping[str, object]],
) -> dict[str, AnnotationStyle]:
    next_styles = {key: AnnotationStyle() for key in _STYLE_KEYS}
    for annotation_type, raw_style in styles.items():
        key = _normalize_annotation_type(annotation_type)
        if isinstance(raw_style, AnnotationStyle):
            next_styles[key] = raw_style
        else:
            next_styles[key] = AnnotationStyle.from_dict(raw_style)
    _ANNOTATION_STYLES.clear()
    _ANNOTATION_STYLES.update(next_styles)
    return get_annotation_styles_by_tool()


def dimension_annotation_properties() -> dict:
    font_color = normalize_annotation_color(_style_for("dimension").color)
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


def _annotation_color_int(color: str) -> int:
    text = normalize_annotation_color(color).lstrip("#")
    red = int(text[0:2], 16)
    green = int(text[2:4], 16)
    blue = int(text[4:6], 16)
    return red | (green << 8) | (blue << 16)


def text_annotation_properties() -> dict:
    return {
        "Text": "",
        "FontName": "Arial",
        "FontColor": _annotation_color_int(_style_for("text").color),
        "FontSize": 12,
        "FontBold": False,
        "FontItalic": False,
        "FontUnderline": False,
        "TextAlign": 0,
    }


def annotation_default_style(annotation_type: str) -> tuple[str, float]:
    key = _normalize_annotation_type(annotation_type)
    style = _style_for(key)
    if key == "dimension":
        return style.color, DIMENSION_ANNOTATION_WIDTH
    return style.color, style.line_width


def annotation_default_properties(annotation_type: str) -> dict:
    key = _normalize_annotation_type(annotation_type)
    if key == "dimension":
        return dimension_annotation_properties()
    if key in ("line", "arrow"):
        return {
            "BidTakeoffFromUID": "",
            "BidTakeoffToUID": "",
        }
    if key == "text":
        return text_annotation_properties()
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
