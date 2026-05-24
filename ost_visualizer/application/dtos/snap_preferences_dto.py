from dataclasses import dataclass
from typing import Protocol


class SnapPreferenceSource(Protocol):
    snap_to_grid_enabled: bool
    snap_to_grid_threshold_px: int
    snap_to_pdf_lines_enabled: bool
    snap_to_pdf_lines_threshold_px: int
    snap_to_takeoffs_enabled: bool
    snap_to_takeoffs_threshold_px: int
    right_angle_indicator_threshold_px: int


@dataclass(frozen=True)
class SnapPreferencesDto:
    snap_to_grid_enabled: bool
    snap_to_grid_threshold_px: int
    snap_to_pdf_lines_enabled: bool
    snap_to_pdf_lines_threshold_px: int
    snap_to_takeoffs_enabled: bool
    snap_to_takeoffs_threshold_px: int
    right_angle_indicator_threshold_px: int

    @classmethod
    def from_config(cls, config: SnapPreferenceSource) -> "SnapPreferencesDto":
        return cls(
            snap_to_grid_enabled=config.snap_to_grid_enabled,
            snap_to_grid_threshold_px=config.snap_to_grid_threshold_px,
            snap_to_pdf_lines_enabled=config.snap_to_pdf_lines_enabled,
            snap_to_pdf_lines_threshold_px=config.snap_to_pdf_lines_threshold_px,
            snap_to_takeoffs_enabled=config.snap_to_takeoffs_enabled,
            snap_to_takeoffs_threshold_px=config.snap_to_takeoffs_threshold_px,
            right_angle_indicator_threshold_px=(
                config.right_angle_indicator_threshold_px
            ),
        )

    def to_kwargs(self) -> dict[str, bool | int]:
        return {
            "snap_to_grid_enabled": self.snap_to_grid_enabled,
            "snap_to_grid_threshold_px": self.snap_to_grid_threshold_px,
            "snap_to_pdf_lines_enabled": self.snap_to_pdf_lines_enabled,
            "snap_to_pdf_lines_threshold_px": self.snap_to_pdf_lines_threshold_px,
            "snap_to_takeoffs_enabled": self.snap_to_takeoffs_enabled,
            "snap_to_takeoffs_threshold_px": self.snap_to_takeoffs_threshold_px,
            "right_angle_indicator_threshold_px": (
                self.right_angle_indicator_threshold_px
            ),
        }
