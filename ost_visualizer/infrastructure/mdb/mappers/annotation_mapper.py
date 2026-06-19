from typing import Any, Optional, Tuple
from ....domain.entities.layer import (
    ANNOTATION_LAYER_NAME,
    BidLayers,
    LayerSet,
)


class MdbAnnotationLayerMapper:
    def __init__(self, bid_layers: BidLayers) -> None:
        self._layers = LayerSet(bid_layers)

    def resolve_layer(self, row_layer_uid: Any = None) -> Tuple[Optional[str], bool]:
        return self._layers.resolve_layer_or_default(
            row_layer_uid, ANNOTATION_LAYER_NAME
        ).as_tuple()
