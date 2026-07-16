from dataclasses import dataclass

Point2D = tuple[float, float]


@dataclass(frozen=True)
class ElevationCallout:
    x: float
    y: float
    lines: tuple[str, ...]
