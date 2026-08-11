import math

INTERACTIVE_PDF_RENDER_SCALE = 3.0
RASTER_NATIVE_RENDER_SCALE = 1.0
CONSTRAINED_RENDER_SCALE_FLOOR = 0.1
ZOOM_PDF_RENDER_SCALE_MIN = 1.0
RENDER_SCALE_DECIMAL_PLACES = 3
RENDER_FRAME_COORD_DECIMAL_PLACES = 3


def baseline_render_scale(*, is_pdf: bool) -> float:
    return INTERACTIVE_PDF_RENDER_SCALE if is_pdf else RASTER_NATIVE_RENDER_SCALE


def quantize_constrained_render_scale(render_scale: float) -> float:
    return max(
        CONSTRAINED_RENDER_SCALE_FLOOR,
        round(float(render_scale), RENDER_SCALE_DECIMAL_PLACES),
    )


def truncate_constrained_render_scale(render_scale: float) -> float:
    multiplier = 10**RENDER_SCALE_DECIMAL_PLACES
    constrained = max(CONSTRAINED_RENDER_SCALE_FLOOR, float(render_scale))
    return math.floor(constrained * multiplier) / multiplier


def align_rendered_frame_origin(value: float, render_scale: float) -> float:
    if render_scale <= 0.0:
        return value
    return math.floor(value * render_scale + 0.5) / render_scale


def quantize_render_frame_coordinate(value: float) -> float:
    return round(float(value), RENDER_FRAME_COORD_DECIMAL_PLACES)
