from enum import IntEnum


class RenderPriority(IntEnum):
    REQUIRED_PAGE = 0
    VISIBLE_FRAME = 1
    PDF_TEXT = 2
    OPTIONAL_BASE = 3
    NEARBY_PREFETCH = 4
