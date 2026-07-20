from __future__ import annotations
from dataclasses import dataclass
import math


def _round_physical_extent(value: float) -> int:
    return int(math.floor(value + 0.5))


@dataclass(frozen=True)
class RenderSurfaceMetrics:
    logical_width: int
    logical_height: int
    device_pixel_ratio: float
    physical_width: int
    physical_height: int

    @classmethod
    def from_logical_size(
        cls, logical_width: int, logical_height: int, device_pixel_ratio: float
    ) -> RenderSurfaceMetrics:
        logical_width = int(logical_width)
        logical_height = int(logical_height)
        device_pixel_ratio = float(device_pixel_ratio)
        if logical_width < 0 or logical_height < 0:
            raise ValueError("Logical render-surface dimensions cannot be negative")
        if not math.isfinite(device_pixel_ratio) or device_pixel_ratio <= 0.0:
            raise ValueError("Device pixel ratio must be finite and positive")
        return cls(
            logical_width=logical_width,
            logical_height=logical_height,
            device_pixel_ratio=device_pixel_ratio,
            physical_width=_round_physical_extent(logical_width * device_pixel_ratio),
            physical_height=_round_physical_extent(logical_height * device_pixel_ratio),
        )

    @property
    def has_render_target(self) -> bool:
        return self.physical_width > 0 and self.physical_height > 0

    @property
    def physical_size(self) -> tuple[int, int]:
        return self.physical_width, self.physical_height

    def to_physical_point(self, logical_x: float, logical_y: float) -> tuple[int, int]:
        return (
            math.floor(float(logical_x) * self.device_pixel_ratio),
            math.floor(float(logical_y) * self.device_pixel_ratio),
        )
