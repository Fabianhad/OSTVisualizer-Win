from dataclasses import dataclass


@dataclass(frozen=True)
class PdfPageInfoDto:
    status: str = "unavailable"
    page_count: int = 0
    effective_width_pts: float = 0.0
    effective_height_pts: float = 0.0
    media_width_pts: float = 0.0
    media_height_pts: float = 0.0
    crop_width_pts: float = 0.0
    crop_height_pts: float = 0.0
    intrinsic_rotation: int = 0


@dataclass(frozen=True)
class PdfTextRunDto:
    text: str
    left: float
    top: float
    right: float
    bottom: float


@dataclass(frozen=True)
class PdfVectorSegmentDto:
    x1: float
    y1: float
    x2: float
    y2: float
