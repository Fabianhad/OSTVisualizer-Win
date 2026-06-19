from typing import Any, Optional, Tuple

from ....domain.entities.layer import (
    ANNOTATION_LAYER_NAME,
    BidLayers,
    get_layer_uid_by_name,
    is_layer_visible,
)


class MdbAnnotationLayerMapper:
    def __init__(self, bid_layers: BidLayers) -> None:
        self._bid_layers = bid_layers
        self._annotation_layer_uid = get_layer_uid_by_name(
            bid_layers, ANNOTATION_LAYER_NAME
        )
        self._annotation_layer_visible = is_layer_visible(
            bid_layers, self._annotation_layer_uid
        )

    def resolve_layer(self, row_layer_uid: Any = None) -> Tuple[Optional[str], bool]:
        if row_layer_uid is not None:
            layer_uid = str(row_layer_uid)
            return layer_uid, is_layer_visible(self._bid_layers, layer_uid)
        return self._annotation_layer_uid, self._annotation_layer_visible
