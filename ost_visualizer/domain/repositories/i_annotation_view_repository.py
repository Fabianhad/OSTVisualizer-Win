from typing import Optional, Protocol, runtime_checkable
from ..entities.annotation_view import AnnotationView
from ..entities.identity_refs import BidRef


@runtime_checkable
class IAnnotationViewRepository(Protocol):
    def get_active_view(self) -> Optional[AnnotationView]: ...
    def create_view(
        self,
        bid_ref: BidRef,
        target_page_uid: str,
        target_named_view_uid: Optional[str] = None,
    ) -> AnnotationView: ...
    def update_view(self, view: AnnotationView) -> None: ...
