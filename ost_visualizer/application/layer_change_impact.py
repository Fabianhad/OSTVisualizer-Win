from dataclasses import replace
from collections.abc import Sequence
from ..domain.entities.layer import (
    ANNOTATION_LAYER_NAME,
    COMMENTS_LAYER_NAME,
    IMAGE_LAYER_NAME,
    BidLayer,
    normalize_layer_name,
)


def layer_rename_preserves_rendering(
    before: Sequence[BidLayer], after: Sequence[BidLayer]
) -> bool:
    previous = {layer.uid: layer for layer in before}
    current = {layer.uid: layer for layer in after}
    if not previous or previous.keys() != current.keys():
        return False
    if len(previous) != len(before) or len(current) != len(after):
        return False
    roles = {ANNOTATION_LAYER_NAME, COMMENTS_LAYER_NAME, IMAGE_LAYER_NAME}
    renamed = False
    for uid, old in previous.items():
        new = current[uid]
        if replace(old, name=new.name) != new:
            return False
        if old.name != new.name:
            renamed = True
            if (
                normalize_layer_name(old.name) in roles
                or normalize_layer_name(new.name) in roles
            ):
                return False
    return renamed
