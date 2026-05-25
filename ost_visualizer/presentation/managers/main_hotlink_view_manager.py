from typing import Optional
from ...application.interfaces.i_annotation_view_manager import IAnnotationViewManager
from ...domain.entities.identity_refs import BidRef


class QtMainHotlinkViewManager(IAnnotationViewManager):
    def __init__(self, main_window):
        self._main_window = main_window

    def open_view(
        self,
        bid_ref: BidRef,
        target_page_uid: str,
        target_named_view_uid: Optional[str] = None,
    ) -> str:
        self.navigate_to_view(target_page_uid, target_named_view_uid or "")
        return "__main__"

    def navigate_to_view(self, page_uid: str, named_view_uid: str) -> None:
        self._main_window.navigate_to_hotlink_page(page_uid, named_view_uid)

    def bring_to_front(self) -> None:
        self._main_window.raise_()
        self._main_window.activateWindow()

    def is_view_open(self) -> bool:
        return True
