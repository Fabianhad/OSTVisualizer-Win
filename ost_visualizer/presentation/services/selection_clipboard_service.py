from typing import Any, Dict, List, Optional
from ...domain.entities.annotation import BidAnnotation
from ...domain.entities.takeoff import Takeoff


class SelectionClipboardService:
    def __init__(self) -> None:
        self._takeoffs: List[Takeoff] = []
        self._takeoff_extras: Dict[str, Dict[str, Any]] = {}
        self._annotations: List[BidAnnotation] = []
        self._source_bid_uid: Optional[str] = None
        self._source_file_path: Optional[str] = None

    def copy(
        self,
        takeoffs: List[Takeoff],
        annotations: List[BidAnnotation] = None,
        source_bid_uid: Optional[str] = None,
        source_file_path: Optional[str] = None,
        takeoff_extras: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self._source_bid_uid = source_bid_uid
        self._source_file_path = source_file_path
        self._takeoffs = [
            Takeoff(
                uid=t.uid,
                condition_uid=t.condition_uid,
                page_uid=t.page_uid,
                area_uid=t.area_uid,
                position=list(t.position),
                rotation=t.rotation,
                curve=t.curve,
                parent_uid=t.parent_uid,
                is_negative=t.is_negative,
            )
            for t in takeoffs
        ]
        if takeoff_extras:
            self._takeoff_extras = {
                str(uid): dict(extras) for uid, extras in takeoff_extras.items()
            }
        else:
            self._takeoff_extras = {}
        self._annotations = [
            BidAnnotation(
                uid=a.uid,
                annotation_type=a.annotation_type,
                page_uid=a.page_uid,
                layer_uid=a.layer_uid,
                position=list(a.position),
                color=a.color,
                width=a.width,
                properties=dict(a.properties),
                visible=a.visible,
            )
            for a in (annotations or [])
        ]

    def has_content(self) -> bool:
        return bool(self._takeoffs or self._annotations)

    @property
    def items(self) -> List[Takeoff]:
        return self._takeoffs

    @property
    def annotations(self) -> List[BidAnnotation]:
        return self._annotations

    @property
    def source_bid_uid(self) -> Optional[str]:
        return self._source_bid_uid

    @property
    def source_file_path(self) -> Optional[str]:
        return self._source_file_path

    def get_extras(self, takeoff_uid: str) -> Dict[str, Any]:
        return self._takeoff_extras.get(str(takeoff_uid), {})
