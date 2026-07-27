from collections.abc import Mapping
from ...application.dtos.insert_annotation_spec_dto import InsertAnnotationSpec
from ...domain.entities.annotation import (
    ANNOTATION_TYPE_ARROW,
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_HIGHLIGHT,
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_LINE,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
)
from ...domain.entities.annotation_style import (
    AnnotationStyle,
    normalize_annotation_color,
    normalize_annotation_line_width,
    normalize_text_align,
    normalize_text_font_name,
    normalize_text_font_size,
)
from .plan_tool_registry import PLAN_ANNOTATION_TOOL_SPECS

DIMENSION_ANNOTATION_WIDTH = 1.0
HOTLINK_DEFAULT_COLOR = "#ff0000"
NAMED_VIEW_DEFAULT_COLOR = "#008000"
PLACEABLE_ANNOTATION_TYPES = frozenset(
    spec.annotation_type
    for spec in PLAN_ANNOTATION_TOOL_SPECS
    if spec.annotation_type is not None
)
_STYLE_KEYS = tuple(sorted(PLACEABLE_ANNOTATION_TYPES))


def _default_style_for_tool(annotation_type: str) -> AnnotationStyle:
    if annotation_type == ANNOTATION_TYPE_NAMED_VIEW:
        return AnnotationStyle(color=NAMED_VIEW_DEFAULT_COLOR)
    if annotation_type == ANNOTATION_TYPE_HOTLINK:
        return AnnotationStyle(color=HOTLINK_DEFAULT_COLOR)
    return AnnotationStyle()


_ANNOTATION_STYLES: dict[str, AnnotationStyle] = {
    annotation_type: _default_style_for_tool(annotation_type)
    for annotation_type in _STYLE_KEYS
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
    font_name=None,
    font_size=None,
    font_bold=None,
    font_italic=None,
    font_underline=None,
    text_align=None,
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
            and key
            not in (
                ANNOTATION_TYPE_DIMENSION,
                ANNOTATION_TYPE_TEXT,
                ANNOTATION_TYPE_HIGHLIGHT,
                ANNOTATION_TYPE_HOTLINK,
                ANNOTATION_TYPE_NAMED_VIEW,
            )
            else current.line_width
        ),
        font_name=(
            normalize_text_font_name(font_name, current.font_name)
            if font_name is not None
            else current.font_name
        ),
        font_size=(
            normalize_text_font_size(font_size, current.font_size)
            if font_size is not None
            else current.font_size
        ),
        font_bold=bool(font_bold) if font_bold is not None else current.font_bold,
        font_italic=(
            bool(font_italic) if font_italic is not None else current.font_italic
        ),
        font_underline=(
            bool(font_underline)
            if font_underline is not None
            else current.font_underline
        ),
        text_align=(
            normalize_text_align(text_align, current.text_align)
            if text_align is not None
            else current.text_align
        ),
    )
    _ANNOTATION_STYLES[key] = next_style
    return next_style


def set_annotation_styles_by_tool(
    styles: Mapping[str, AnnotationStyle | Mapping[str, object]],
) -> dict[str, AnnotationStyle]:
    next_styles = {key: _default_style_for_tool(key) for key in _STYLE_KEYS}
    for annotation_type, raw_style in styles.items():
        key = str(annotation_type or "").strip().lower()
        if key not in PLACEABLE_ANNOTATION_TYPES:
            continue
        if isinstance(raw_style, AnnotationStyle):
            next_styles[key] = raw_style
        else:
            next_styles[key] = AnnotationStyle.from_dict(raw_style)
    _ANNOTATION_STYLES.clear()
    _ANNOTATION_STYLES.update(next_styles)
    return get_annotation_styles_by_tool()


def dimension_annotation_properties() -> dict:
    style = _style_for(ANNOTATION_TYPE_DIMENSION)
    font_color = normalize_annotation_color(style.color)
    return {
        "BidTakeoffFromUID": "",
        "BidTakeoffToUID": "",
        "FontName": style.font_name,
        "FontColor": font_color,
        "FontSize": style.font_size,
        "FontBold": style.font_bold,
        "FontItalic": style.font_italic,
        "FontUnderline": style.font_underline,
    }


def _annotation_color_int(color: str) -> int:
    text = normalize_annotation_color(color).lstrip("#")
    red = int(text[0:2], 16)
    green = int(text[2:4], 16)
    blue = int(text[4:6], 16)
    return red | (green << 8) | (blue << 16)


def text_annotation_properties() -> dict:
    style = _style_for(ANNOTATION_TYPE_TEXT)
    return {
        "Text": "",
        "FontName": style.font_name,
        "FontColor": _annotation_color_int(style.color),
        "FontSize": style.font_size,
        "FontBold": style.font_bold,
        "FontItalic": style.font_italic,
        "FontUnderline": style.font_underline,
        "TextAlign": style.text_align,
    }


def annotation_default_style(annotation_type: str) -> tuple[str, float]:
    key = _normalize_annotation_type(annotation_type)
    style = _style_for(key)
    if key == ANNOTATION_TYPE_DIMENSION:
        return style.color, DIMENSION_ANNOTATION_WIDTH
    if key in (ANNOTATION_TYPE_TEXT, ANNOTATION_TYPE_HIGHLIGHT):
        return style.color, 0.0
    if key in (ANNOTATION_TYPE_HOTLINK, ANNOTATION_TYPE_NAMED_VIEW):
        return style.color, 2.0
    return style.color, style.line_width


def annotation_default_properties(annotation_type: str) -> dict:
    key = _normalize_annotation_type(annotation_type)
    if key == ANNOTATION_TYPE_DIMENSION:
        return dimension_annotation_properties()
    if key in (ANNOTATION_TYPE_LINE, ANNOTATION_TYPE_ARROW):
        return {
            "BidTakeoffFromUID": "",
            "BidTakeoffToUID": "",
        }
    if key == ANNOTATION_TYPE_TEXT:
        return text_annotation_properties()
    if key == ANNOTATION_TYPE_NAMED_VIEW:
        return {"Text": ""}
    if key == ANNOTATION_TYPE_HOTLINK:
        return {"BidPageViewUID": ""}
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
