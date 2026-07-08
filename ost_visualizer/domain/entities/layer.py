from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

ANNOTATION_LAYER_NAME = "annotation"
IMAGE_LAYER_NAME = "image"
COMMENTS_LAYER_NAME = "comments"


def normalize_layer_name(name: str) -> str:
    return str(name or "").strip().lower()


def is_comments_layer_name(name: str) -> bool:
    return normalize_layer_name(name) == COMMENTS_LAYER_NAME


@dataclass
class Layer:
    uid: str
    name: str = ""
    visible: bool = True


BidLayers = Dict[str, Layer]


@dataclass(frozen=True)
class LayerVisibility:
    uid: Optional[str]
    visible: bool

    def as_tuple(self) -> Tuple[Optional[str], bool]:
        return self.uid, self.visible


class LayerSet:
    def __init__(self, layers: BidLayers) -> None:
        self._layers = layers

    def uid_by_name(self, layer_name: str) -> Optional[str]:
        return get_layer_uid_by_name(self._layers, layer_name)

    def is_visible(self, layer_uid: Optional[str]) -> bool:
        return is_layer_visible(self._layers, layer_uid)

    def resolve_layer(self, layer_uid: Optional[str]) -> LayerVisibility:
        if layer_uid is None:
            return LayerVisibility(None, True)
        normalized_uid = str(layer_uid)
        return LayerVisibility(normalized_uid, self.is_visible(normalized_uid))

    def resolve_layer_or_default(
        self, layer_uid: Optional[str], default_layer_name: str
    ) -> LayerVisibility:
        if layer_uid is not None:
            return self.resolve_layer(str(layer_uid))
        default_uid = self.uid_by_name(default_layer_name)
        return LayerVisibility(default_uid, self.is_visible(default_uid))

    def annotation_layer_uid(self) -> Optional[str]:
        return self.uid_by_name(ANNOTATION_LAYER_NAME)

    def annotation_layer_visible(self) -> bool:
        return self.is_visible(self.annotation_layer_uid())


@dataclass
class BidLayer:
    uid: str
    bid_uid: str
    name: str
    show: bool
    sequence: int
    is_template: bool = False
    is_locked: bool = False


def merge_layers_for_bid(layers: List[BidLayer]) -> List[BidLayer]:
    merged: Dict[str, BidLayer] = {}
    for layer in sorted(layers, key=lambda l: (not l.is_template, l.sequence)):
        merged[layer.name.lower()] = layer
    return sorted(merged.values(), key=lambda l: l.sequence)


def get_layer_uid_by_name(layers: BidLayers, layer_name: str) -> Optional[str]:
    layer_name_lower = normalize_layer_name(layer_name)
    for uid, layer in layers.items():
        if normalize_layer_name(layer.name) == layer_name_lower:
            return uid
    return None


def is_layer_visible(layers: BidLayers, layer_uid: Optional[str]) -> bool:
    if not layer_uid:
        return True
    layer = layers.get(str(layer_uid))
    if layer is None:
        return True
    return layer.visible
