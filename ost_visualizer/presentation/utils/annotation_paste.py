from typing import Optional


def annotation_paste_anchor(annotation) -> Optional[tuple]:
    pos = list(annotation.position)
    if annotation.is_ink:
        start = 1 if len(pos) % 2 == 1 else 0
        if len(pos) >= start + 2:
            return float(pos[start]), float(pos[start + 1])
        return None
    if len(pos) >= 2:
        return float(pos[0]), float(pos[1])
    return None


def annotation_paste_source_anchor(annotations: list) -> Optional[tuple]:
    for annotation in annotations:
        anchor = annotation_paste_anchor(annotation)
        if anchor is not None:
            return anchor
    return None


def annotation_paste_translation(
    plan_view, annotations: list
) -> tuple[float, float, Optional[tuple]]:
    step = plan_view.snap_increments if plan_view.snap_increments > 0 else 1.0
    if not plan_view.intelligent_paste_enabled:
        return step, step, None
    source_anchor = annotation_paste_source_anchor(annotations)
    if source_anchor is None:
        return step, step, None
    mouse_anchor = plan_view.current_mouse_ost_position()
    if mouse_anchor is None:
        return 0.0, 0.0, source_anchor
    return (
        mouse_anchor[0] - source_anchor[0],
        mouse_anchor[1] - source_anchor[1],
        source_anchor,
    )


def translate_annotation_position(annotation, dx: float, dy: float) -> list:
    pos = list(annotation.position)
    if annotation.is_text and len(pos) >= 4:
        pos[0] += dx
        pos[1] += dy
    elif annotation.is_ink:
        start = 1 if len(pos) % 2 == 1 else 0
        for i in range(start, len(pos) - 1, 2):
            pos[i] += dx
            pos[i + 1] += dy
    else:
        n = len(pos) // 2
        for i in range(n):
            pos[i * 2] += dx
            pos[i * 2 + 1] += dy
    return pos
