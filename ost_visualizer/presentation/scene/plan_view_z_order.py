from ..utils.image_show_mode import SHOW_BOTH

PAGE_CANVAS_Z = -1.0
PAGE_IMAGE_Z = 0.0
OVERLAY_MOVE_BASE_Z = 0.05
PAGE_VISIBLE_FRAME_Z = 0.35
FOREGROUND_OVERLAY_Z = 0.36
OVERLAY_MOVE_FOREGROUND_Z = 0.38
PAPER_HIGHLIGHT_Z = 0.4
TAKEOFF_BODY_Z = 0.5
PDF_TEXT_SELECTION_Z = 0.75
ANNOTATION_BODY_Z = 2.0
DIMENSION_LABEL_Z = 3.0
NAMED_VIEW_LABEL_BACKGROUND_Z = 3.0
NAMED_VIEW_LABEL_Z = 4.0
TAKEOFF_LABEL_Z = 20.0
AI_PREVIEW_Z = 30.0
TAKEOFF_DRAW_ORDER_STEP = 0.0000001
TAKEOFF_PREVIEW_DRAW_INDEX = 1_000_000


def takeoff_z_value(base_z: float, draw_index: int) -> float:
    return base_z + (draw_index * TAKEOFF_DRAW_ORDER_STEP)


TAKEOFF_PREVIEW_BODY_Z = takeoff_z_value(TAKEOFF_BODY_Z, TAKEOFF_PREVIEW_DRAW_INDEX)
TAKEOFF_PREVIEW_OUTLINE_Z = takeoff_z_value(
    TAKEOFF_BODY_Z, TAKEOFF_PREVIEW_DRAW_INDEX + 1
)
TAKEOFF_PREVIEW_INDICATOR_Z = takeoff_z_value(
    TAKEOFF_BODY_Z, TAKEOFF_PREVIEW_DRAW_INDEX + 2
)


def overlay_visual_z(
    show_mode: int,
    *,
    primary_z: float,
    foreground_z: float,
) -> float:
    return foreground_z if show_mode == SHOW_BOTH else primary_z
