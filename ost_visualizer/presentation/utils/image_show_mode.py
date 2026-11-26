from ..texts import (
    IMAGE_SHOW_MODE_ITEM_BOTH,
    IMAGE_SHOW_MODE_ITEM_ORIGINAL,
    IMAGE_SHOW_MODE_ITEM_OVERLAY,
)

SHOW_ORIGINAL = 0
SHOW_OVERLAY = 1
SHOW_BOTH = 2
SHOW_LABELS = {
    SHOW_ORIGINAL: IMAGE_SHOW_MODE_ITEM_ORIGINAL,
    SHOW_OVERLAY: IMAGE_SHOW_MODE_ITEM_OVERLAY,
    SHOW_BOTH: IMAGE_SHOW_MODE_ITEM_BOTH,
}


def mode_to_flags(mode: int) -> tuple[bool, bool]:
    show_original = mode in (SHOW_ORIGINAL, SHOW_BOTH)
    show_overlay = mode in (SHOW_OVERLAY, SHOW_BOTH)
    return show_original, show_overlay


def flags_to_mode(show_original: bool, show_overlay: bool) -> int:
    if show_original and show_overlay:
        return SHOW_BOTH
    if show_overlay:
        return SHOW_OVERLAY
    return SHOW_ORIGINAL


def resolve_toggled_mode(current_mode: int, target: str, checked: bool) -> int:
    show_original, show_overlay = mode_to_flags(current_mode)
    if target == "original":
        show_original = checked
    elif target == "overlay":
        show_overlay = checked
    if not show_original and not show_overlay:
        return SHOW_OVERLAY if target == "original" else SHOW_ORIGINAL
    return flags_to_mode(show_original, show_overlay)
