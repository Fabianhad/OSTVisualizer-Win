from dataclasses import dataclass
from typing import Dict, List, Optional


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
    layer_name_lower = layer_name.lower()
    for uid, layer in layers.items():
        if layer.name.lower() == layer_name_lower:
            return uid
    return None


def is_layer_visible(layers: BidLayers, layer_uid: Optional[str]) -> bool:
    if not layer_uid:
        return True
    layer = layers.get(str(layer_uid))
    if layer is None:
        return True
    return layer.visible
