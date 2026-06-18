from dataclasses import dataclass
from typing import Dict, List, Optional

ANNOTATION_LAYER_NAME = "annotation"
IMAGE_LAYER_NAME = "image"


def normalize_layer_name(name: str) -> str:
    return str(name or "").strip().lower()


def is_annotation_layer_name(name: str) -> bool:
    return normalize_layer_name(name) == ANNOTATION_LAYER_NAME


def is_image_layer_name(name: str) -> bool:
    return normalize_layer_name(name) == IMAGE_LAYER_NAME


@dataclass
class Layer:
    uid: str
    name: str = ""
    visible: bool = True


BidLayers = Dict[str, Layer]


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
