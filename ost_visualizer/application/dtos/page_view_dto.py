from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from ...domain.entities.annotation import BidAnnotation
from ...domain.entities.condition import Condition
from ...domain.entities.identity_refs import BidRef
from ...domain.entities.named_view import NamedView
from ...domain.entities.page import Page
from ...domain.entities.takeoff import Takeoff


@dataclass
class PageViewDto:
    page: Optional[Page]
    takeoffs: List[Takeoff] = field(default_factory=list)
    conditions: Dict[str, Condition] = field(default_factory=dict)
    color_map: Dict[str, Any] = field(default_factory=dict)
    bid_ref: Optional[BidRef] = None
    annotations: List[BidAnnotation] = field(default_factory=list)
    ordered_pages: List[Page] = field(default_factory=list)
    named_view: Optional[NamedView] = None
    page_area_selections: Dict[str, Optional[str]] = field(default_factory=dict)
    hidden_layer_uids: Set[str] = field(default_factory=set)
    annotation_layer_uid: Optional[str] = None

    def is_layer_visible(self, layer_uid: Optional[str]) -> bool:
        layer_key = str(layer_uid or "")
        if not layer_key:
            return True
        return all(
            str(hidden_uid) != layer_key for hidden_uid in self.hidden_layer_uids
        )
