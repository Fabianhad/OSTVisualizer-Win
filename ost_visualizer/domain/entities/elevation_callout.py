from dataclasses import dataclass

Point2D = tuple[float, float]


@dataclass(frozen=True)
class ElevationCalloutSettings:
    include_condition: bool = True
    include_top: bool = True
    include_bottom: bool = True
    include_cubic_yards: bool = True

    @property
    def has_content(self) -> bool:
        return (
            self.include_condition
            or self.include_top
            or self.include_bottom
            or self.include_cubic_yards
        )


DEFAULT_ELEVATION_CALLOUT_SETTINGS = ElevationCalloutSettings()


@dataclass(frozen=True)
class ElevationCallout:
    x: float
    y: float
    lines: tuple[str, ...]
