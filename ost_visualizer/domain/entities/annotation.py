import math
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Optional, Tuple

ANNOTATION_TYPE_ARROW = "arrow"
ANNOTATION_TYPE_CALLOUT = "callout"
ANNOTATION_TYPE_CLOUD = "cloud"
ANNOTATION_TYPE_DIMENSION = "dimension"
ANNOTATION_TYPE_HIGHLIGHT = "highlight"
ANNOTATION_TYPE_HOTLINK = "hotlink"
ANNOTATION_TYPE_INK = "ink"
ANNOTATION_TYPE_LINE = "line"
ANNOTATION_TYPE_NAMED_VIEW = "namedview"
ANNOTATION_TYPE_OVAL = "oval"
ANNOTATION_TYPE_POLYGON = "polygon"
ANNOTATION_TYPE_RECT = "rect"
ANNOTATION_TYPE_TEXT = "text"


@dataclass
class BidAnnotation:
    LINEAR_TYPES: ClassVar[frozenset] = frozenset(
        {ANNOTATION_TYPE_LINE, ANNOTATION_TYPE_ARROW, ANNOTATION_TYPE_DIMENSION}
    )
    INTERACTIVE_TYPES: ClassVar[frozenset] = frozenset(
        {
            ANNOTATION_TYPE_LINE,
            ANNOTATION_TYPE_ARROW,
            ANNOTATION_TYPE_DIMENSION,
            ANNOTATION_TYPE_RECT,
            ANNOTATION_TYPE_OVAL,
            ANNOTATION_TYPE_HIGHLIGHT,
            ANNOTATION_TYPE_TEXT,
            ANNOTATION_TYPE_POLYGON,
            ANNOTATION_TYPE_CLOUD,
            ANNOTATION_TYPE_INK,
            ANNOTATION_TYPE_NAMED_VIEW,
            ANNOTATION_TYPE_HOTLINK,
            ANNOTATION_TYPE_CALLOUT,
        }
    )
    RESIZABLE_TYPES: ClassVar[frozenset] = frozenset(
        {
            ANNOTATION_TYPE_LINE,
            ANNOTATION_TYPE_ARROW,
            ANNOTATION_TYPE_DIMENSION,
            ANNOTATION_TYPE_RECT,
            ANNOTATION_TYPE_OVAL,
            ANNOTATION_TYPE_HIGHLIGHT,
            ANNOTATION_TYPE_TEXT,
            ANNOTATION_TYPE_POLYGON,
            ANNOTATION_TYPE_CLOUD,
            ANNOTATION_TYPE_NAMED_VIEW,
            ANNOTATION_TYPE_CALLOUT,
        }
    )
    ROTATABLE_TYPES: ClassVar[frozenset] = frozenset(
        {
            ANNOTATION_TYPE_LINE,
            ANNOTATION_TYPE_ARROW,
            ANNOTATION_TYPE_DIMENSION,
            ANNOTATION_TYPE_RECT,
            ANNOTATION_TYPE_OVAL,
            ANNOTATION_TYPE_HIGHLIGHT,
            ANNOTATION_TYPE_TEXT,
            ANNOTATION_TYPE_POLYGON,
            ANNOTATION_TYPE_CLOUD,
            ANNOTATION_TYPE_INK,
            ANNOTATION_TYPE_CALLOUT,
        }
    )
    uid: str
    annotation_type: str
    page_uid: str = ""
    layer_uid: str = ""
    position: List[float] = field(default_factory=list)
    color: str = "#FF0000"
    width: float = 1.0
    properties: Dict[str, Any] = field(default_factory=dict)
    visible: bool = True

    @property
    def is_interactive(self) -> bool:
        return self.annotation_type in self.INTERACTIVE_TYPES

    @property
    def can_resize(self) -> bool:
        return self.annotation_type in self.RESIZABLE_TYPES

    @property
    def can_rotate(self) -> bool:
        return self.annotation_type in self.ROTATABLE_TYPES

    @property
    def is_text(self) -> bool:
        return self.annotation_type == ANNOTATION_TYPE_TEXT

    @property
    def is_cloud(self) -> bool:
        return self.annotation_type == ANNOTATION_TYPE_CLOUD

    @property
    def is_dimension(self) -> bool:
        return self.annotation_type == ANNOTATION_TYPE_DIMENSION

    @property
    def is_namedview(self) -> bool:
        return self.annotation_type == ANNOTATION_TYPE_NAMED_VIEW

    @property
    def is_hotlink(self) -> bool:
        return self.annotation_type == ANNOTATION_TYPE_HOTLINK

    @property
    def is_rect(self) -> bool:
        return self.annotation_type == ANNOTATION_TYPE_RECT

    @property
    def is_oval(self) -> bool:
        return self.annotation_type == ANNOTATION_TYPE_OVAL

    @property
    def is_polygon(self) -> bool:
        return self.annotation_type == ANNOTATION_TYPE_POLYGON

    @property
    def is_ink(self) -> bool:
        return self.annotation_type == ANNOTATION_TYPE_INK

    @property
    def is_highlight(self) -> bool:
        return self.annotation_type == ANNOTATION_TYPE_HIGHLIGHT

    @property
    def hotlink_target_view_uid(self) -> Optional[str]:
        if not self.is_hotlink:
            return None
        val = self.properties.get("BidPageViewUID")
        if val in (None, "", "0"):
            return None
        return str(val)

    @property
    def stored_rotation_rad(self) -> float:
        pos = self.position
        if self.is_ink:
            return pos[0] if len(pos) % 2 == 1 else 0.0
        if self.is_text:
            return pos[4] if len(pos) >= 5 else 0.0
        if len(pos) % 2 == 1:
            return pos[-1]
        return 0.0

    @property
    def has_valid_position(self) -> bool:
        if self.annotation_type in self.LINEAR_TYPES:
            return len(self.position) >= 4
        return len(self.position) >= 2

    def get_line_coords(self) -> Optional[Tuple[float, float, float, float]]:
        if len(self.position) >= 4:
            return (
                self.position[0],
                self.position[1],
                self.position[2],
                self.position[3],
            )
        return None

    def get_bbox_ost(self) -> Optional[Tuple[float, float, float, float]]:
        pos = self.position
        if self.is_text and len(pos) >= 4:
            cx, cy, w, h = pos[0], pos[1], pos[2], pos[3]
            return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
        if self.is_rect or self.is_oval or self.is_highlight or self.is_namedview:
            n = len(pos)
            pairs = n // 2 if n % 2 == 0 else (n - 1) // 2
            if pairs < 2:
                return None
            xs = [pos[i * 2] for i in range(pairs)]
            ys = [pos[i * 2 + 1] for i in range(pairs)]
            return min(xs), min(ys), max(xs), max(ys)
        if self.is_ink:
            start = 1 if len(pos) % 2 == 1 else 0
            coords = pos[start:]
            xs = coords[0::2]
            ys = coords[1::2]
            if len(xs) < 2:
                return None
            return min(xs), min(ys), max(xs), max(ys)
        return None

    def get_oval_geometry_ost(
        self,
    ) -> Optional[Tuple[float, float, float, float, float]]:
        if not self.is_oval or len(self.position) < 4:
            return None
        x1, y1, x2, y2 = self.position[:4]
        rotation = self.stored_rotation_rad
        if not all(math.isfinite(value) for value in (x1, y1, x2, y2, rotation)):
            return None
        cos_r = math.cos(rotation)
        sin_r = math.sin(rotation)
        diagonal_x = x2 - x1
        diagonal_y = y2 - y1
        unrotated_width = diagonal_x * cos_r + diagonal_y * sin_r
        unrotated_height = -diagonal_x * sin_r + diagonal_y * cos_r
        radius_x = abs(unrotated_width) / 2.0
        radius_y = abs(unrotated_height) / 2.0
        if radius_x == 0.0 or radius_y == 0.0:
            return None
        return (
            (x1 + x2) / 2.0,
            (y1 + y2) / 2.0,
            radius_x,
            radius_y,
            rotation,
        )

    def get_text_content(self) -> str:
        return self.properties.get("Text", "")


def int_color_to_hex(color_fill: int) -> str:
    r = color_fill & 0xFF
    g = (color_fill >> 8) & 0xFF
    b = (color_fill >> 16) & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"
