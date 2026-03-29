from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Optional, Tuple


@dataclass
class BidAnnotation:
    LINEAR_TYPES: ClassVar[frozenset] = frozenset({"line", "arrow"})
    INTERACTIVE_TYPES: ClassVar[frozenset] = frozenset(
        {
            "line",
            "arrow",
            "rect",
            "oval",
            "highlight",
            "text",
            "polygon",
            "cloud",
            "ink",
            "namedview",
            "hotlink",
            "callout",
        }
    )
    RESIZABLE_TYPES: ClassVar[frozenset] = frozenset(
        {
            "line",
            "arrow",
            "rect",
            "oval",
            "highlight",
            "text",
            "polygon",
            "cloud",
            "namedview",
            "callout",
        }
    )
    ROTATABLE_TYPES: ClassVar[frozenset] = frozenset(
        {
            "line",
            "arrow",
            "rect",
            "oval",
            "highlight",
            "text",
            "polygon",
            "cloud",
            "ink",
            "callout",
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
    def is_arrow(self) -> bool:
        return self.annotation_type == "arrow"

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
        return self.annotation_type == "text"

    @property
    def is_cloud(self) -> bool:
        return self.annotation_type == "cloud"

    @property
    def is_line(self) -> bool:
        return self.annotation_type == "line"

    @property
    def is_namedview(self) -> bool:
        return self.annotation_type == "namedview"

    @property
    def is_hotlink(self) -> bool:
        return self.annotation_type == "hotlink"

    @property
    def is_rect(self) -> bool:
        return self.annotation_type == "rect"

    @property
    def is_oval(self) -> bool:
        return self.annotation_type == "oval"

    @property
    def is_polygon(self) -> bool:
        return self.annotation_type == "polygon"

    @property
    def is_ink(self) -> bool:
        return self.annotation_type == "ink"

    @property
    def is_highlight(self) -> bool:
        return self.annotation_type == "highlight"

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

    def get_text_content(self) -> str:
        return self.properties.get("Text", "")


def int_color_to_hex(color_fill: int) -> str:
    r = color_fill & 0xFF
    g = (color_fill >> 8) & 0xFF
    b = (color_fill >> 16) & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"
