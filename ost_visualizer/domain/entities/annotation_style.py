from __future__ import annotations
from dataclasses import dataclass
import re

DEFAULT_ANNOTATION_COLOR = "#ff0000"
DEFAULT_ANNOTATION_LINE_WIDTH = 4.0
MIN_ANNOTATION_LINE_WIDTH = 1.0
MAX_ANNOTATION_LINE_WIDTH = 16.0
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


@dataclass(frozen=True)
class AnnotationStyle:
    color: str = DEFAULT_ANNOTATION_COLOR
    line_width: float = DEFAULT_ANNOTATION_LINE_WIDTH

    def to_dict(self) -> dict:
        return {
            "color": normalize_annotation_color(self.color),
            "line_width": normalize_annotation_line_width(self.line_width),
        }

    @classmethod
    def from_dict(cls, data) -> AnnotationStyle:
        if not isinstance(data, dict):
            return cls()
        return cls(
            color=normalize_annotation_color(data.get("color")),
            line_width=normalize_annotation_line_width(data.get("line_width")),
        )
