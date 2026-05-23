import uuid
from typing import Optional
from ....domain.entities.annotation_view import AnnotationView
from ....domain.entities.identity_refs import BidRef
from ....domain.repositories.i_annotation_view_repository import (
    IAnnotationViewRepository,
)


class MemoryAnnotationViewRepository(IAnnotationViewRepository):
    def __init__(self):
        self._active_view: Optional[AnnotationView] = None

    def get_active_view(self) -> Optional[AnnotationView]:
        return self._active_view

    def create_view(
        self,
        bid_ref: BidRef,
        target_page_uid: str,
        target_named_view_uid: Optional[str] = None,
    ) -> AnnotationView:
        view = AnnotationView(
            uid=f"annotation_view_{uuid.uuid4().hex[:8]}",
            bid_uid=bid_ref.bid_uid,
            target_page_uid=target_page_uid,
            target_named_view_uid=target_named_view_uid,
            file_path=bid_ref.file_path,
        )
        self._active_view = view
        return view

    def update_view(self, view: AnnotationView) -> None:
        if self._active_view and self._active_view.uid == view.uid:
            self._active_view = view
