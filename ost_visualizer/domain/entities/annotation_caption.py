from enum import Enum


class AnnotationCaptionId(str, Enum):
    LABEL = "label"
    LENGTH = "length"
    AREA = "area"
    VOLUME = "volume"
    DEPTH = "depth"
    WALL_AREA = "wall_area"
    WIDTH = "width"
    HEIGHT = "height"
    SLOPE = "slope"


ANNOTATION_CAPTION_ORDER = tuple(AnnotationCaptionId)
SUPPORTED_ANNOTATION_CAPTION_IDS = tuple(
    caption_id.value for caption_id in ANNOTATION_CAPTION_ORDER
)
DEFAULT_ANNOTATION_CAPTION_IDS: tuple[str, ...] = ()
