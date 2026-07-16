from dataclasses import dataclass
from ...domain.entities.annotation_caption import AnnotationCaptionId


@dataclass(frozen=True)
class AnnotationCaptionSpec:
    title: str
    measurement_type: int
    prefix: str


ANNOTATION_CAPTION_SPECS = {
    AnnotationCaptionId.LABEL: AnnotationCaptionSpec("Label", 128, ""),
    AnnotationCaptionId.LENGTH: AnnotationCaptionSpec("Length", 2, "L"),
    AnnotationCaptionId.AREA: AnnotationCaptionSpec("Area", 1, "A"),
    AnnotationCaptionId.VOLUME: AnnotationCaptionSpec("Volume", 4, "V"),
    AnnotationCaptionId.DEPTH: AnnotationCaptionSpec("Depth", 8, "D"),
    AnnotationCaptionId.WALL_AREA: AnnotationCaptionSpec("Wall Area", 16, "WA"),
    AnnotationCaptionId.WIDTH: AnnotationCaptionSpec("Width", 32, "W"),
    AnnotationCaptionId.HEIGHT: AnnotationCaptionSpec("Height", 64, "H"),
    AnnotationCaptionId.SLOPE: AnnotationCaptionSpec("Slope", 2048, "Slope"),
}


@dataclass(frozen=True)
class AnnotationCaptionSettingsDto:
    enabled: bool
    selected_ids: tuple[AnnotationCaptionId, ...]


@dataclass(frozen=True)
class ResolvedAnnotationCaptionDto:
    lines: tuple[str, ...] = ()
    label: str = ""
    measurement_types: int = 0
