from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class FontDefinition:
    """Serializable font attributes supported by OST project columns."""

    family: str
    style_name: str
    point_size: int
    weight: int
    italic: bool
    underline: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "style_name": self.style_name,
            "point_size": self.point_size,
            "weight": self.weight,
            "italic": self.italic,
            "underline": self.underline,
        }

    @classmethod
    def from_dict(cls, data: Any) -> FontDefinition:
        """Parse structurally; ConfigAggregate owns semantic validation."""
        if not isinstance(data, Mapping):
            return cls("", "", 0, 0, False, False)
        return cls(
            family=data.get("family"),  # type: ignore[arg-type]
            style_name=data.get("style_name"),  # type: ignore[arg-type]
            point_size=data.get("point_size"),  # type: ignore[arg-type]
            weight=data.get("weight"),  # type: ignore[arg-type]
            italic=data.get("italic"),  # type: ignore[arg-type]
            underline=data.get("underline"),  # type: ignore[arg-type]
        )
