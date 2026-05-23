from __future__ import annotations
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class Config:
    DEFAULT_COLOR_MODE: ClassVar[str] = "Solid"
    color_mode: str = DEFAULT_COLOR_MODE
    grayscale_enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "color_mode": self.color_mode,
            "grayscale_enabled": self.grayscale_enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Config:
        config = cls()
        if not data:
            return config
        if "color_mode" in data:
            config.color_mode = str(data["color_mode"])
        if "grayscale_enabled" in data:
            config.grayscale_enabled = bool(data["grayscale_enabled"])
        return config
