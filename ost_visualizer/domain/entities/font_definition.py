from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class FontDefinition:
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
        if not isinstance(data, Mapping):
            return cls("", "", 0, 0, False, False)
        return cls(
            family=data.get("family"),
            style_name=data.get("style_name"),
            point_size=data.get("point_size"),
            weight=data.get("weight"),
            italic=data.get("italic"),
            underline=data.get("underline"),
        )
