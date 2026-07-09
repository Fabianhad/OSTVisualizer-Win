from __future__ import annotations
import re
from dataclasses import dataclass

DEFAULT_ANNOTATION_COLOR = "#ff0000"
DEFAULT_ANNOTATION_LINE_WIDTH = 4.0
DEFAULT_TEXT_FONT_NAME = "Arial"
DEFAULT_TEXT_FONT_SIZE = 12
DEFAULT_TEXT_ALIGN = 0
MIN_ANNOTATION_LINE_WIDTH = 1.0
MAX_ANNOTATION_LINE_WIDTH = 16.0
MIN_TEXT_FONT_SIZE = 1
MAX_TEXT_FONT_SIZE = 144
_HEX_COLOR_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


def normalize_annotation_color(value, default: str = DEFAULT_ANNOTATION_COLOR) -> str:
    if not isinstance(value, str):
        return default
    text = value.strip()
    if not _HEX_COLOR_RE.match(text):
        return default
    if not text.startswith("#"):
        text = f"#{text}"
    return text.lower()


def normalize_annotation_line_width(
    value, default: float = DEFAULT_ANNOTATION_LINE_WIDTH
) -> float:
    try:
        width = float(value)
    except (TypeError, ValueError):
        width = float(default)
    return max(MIN_ANNOTATION_LINE_WIDTH, min(MAX_ANNOTATION_LINE_WIDTH, width))


def normalize_text_font_name(value, default: str = DEFAULT_TEXT_FONT_NAME) -> str:
    if not isinstance(value, str):
        return default
    text = value.strip()
    return text or default


def normalize_text_font_size(value, default: int = DEFAULT_TEXT_FONT_SIZE) -> int:
    try:
        size = int(round(float(value)))
    except (TypeError, ValueError):
        size = int(default)
    return max(MIN_TEXT_FONT_SIZE, min(MAX_TEXT_FONT_SIZE, size))


def normalize_text_align(value, default: int = DEFAULT_TEXT_ALIGN) -> int:
    try:
        align = int(value)
    except (TypeError, ValueError):
        align = int(default)
    return align if align in (0, 1, 2) else int(default)


@dataclass(frozen=True)
class AnnotationStyle:
    color: str = DEFAULT_ANNOTATION_COLOR
    line_width: float = DEFAULT_ANNOTATION_LINE_WIDTH
    font_name: str = DEFAULT_TEXT_FONT_NAME
    font_size: int = DEFAULT_TEXT_FONT_SIZE
    font_bold: bool = False
    font_italic: bool = False
    font_underline: bool = False
    text_align: int = DEFAULT_TEXT_ALIGN

    def to_dict(self) -> dict:
        return {
            "color": normalize_annotation_color(self.color),
            "line_width": normalize_annotation_line_width(self.line_width),
            "font_name": normalize_text_font_name(self.font_name),
            "font_size": normalize_text_font_size(self.font_size),
            "font_bold": bool(self.font_bold),
            "font_italic": bool(self.font_italic),
            "font_underline": bool(self.font_underline),
            "text_align": normalize_text_align(self.text_align),
        }

    @classmethod
    def from_dict(cls, data) -> AnnotationStyle:
        if not isinstance(data, dict):
            return cls()
        return cls(
            color=normalize_annotation_color(data.get("color")),
            line_width=normalize_annotation_line_width(data.get("line_width")),
            font_name=normalize_text_font_name(data.get("font_name")),
            font_size=normalize_text_font_size(data.get("font_size")),
            font_bold=bool(data.get("font_bold", False)),
            font_italic=bool(data.get("font_italic", False)),
            font_underline=bool(data.get("font_underline", False)),
            text_align=normalize_text_align(data.get("text_align")),
        )
