from abc import ABC, abstractmethod
from typing import Optional
from ...domain.entities.identity_refs import BidRef
from ..dtos.detached_view_navigation import (
    DetachedViewNavigationSource,
)


class IAnnotationViewManager(ABC):
    @abstractmethod
    def open_view(
        self,
        bid_ref: BidRef,
        target_page_uid: str,
        target_named_view_uid: Optional[str] = None,
        *,
        navigation_source: DetachedViewNavigationSource,
    ) -> str: ...
    @abstractmethod
    def navigate_to_view(self, page_uid: str, named_view_uid: str) -> None: ...
    @abstractmethod
    def bring_to_front(self) -> None: ...
    @abstractmethod
    def is_view_open(self) -> bool: ...
