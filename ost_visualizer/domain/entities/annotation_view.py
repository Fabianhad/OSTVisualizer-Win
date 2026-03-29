from dataclasses import dataclass
from typing import Optional
from .identity_refs import BidRef


@dataclass
class AnnotationView:
    uid: str
    bid_uid: str
    target_page_uid: str
    target_named_view_uid: Optional[str] = None
    file_path: Optional[str] = None

    def update_view_target(
        self, page_uid: str, named_view_uid: Optional[str] = None
    ) -> None:
        self.target_page_uid = page_uid
        self.target_named_view_uid = named_view_uid

    @property
    def bid_ref(self) -> Optional[BidRef]:
        if not self.bid_uid or not self.file_path:
            return None
        return BidRef(file_path=self.file_path, bid_uid=self.bid_uid)
