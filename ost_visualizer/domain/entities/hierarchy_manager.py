from typing import Optional
from .hierarchy import Hierarchy
from .hierarchy_data import HierarchyBidInfo, HierarchyData
from .identity_refs import BidRef


class HierarchyManager:
    def __init__(self) -> None:
        self.hierarchy = Hierarchy()

    @property
    def data(self) -> HierarchyData:
        return self.hierarchy.data

    def set_hierarchy(self, data: HierarchyData) -> None:
        self.hierarchy.set(data)

    def clear(self) -> None:
        self.hierarchy.set(HierarchyData())

    def find_bid_info(self, bid_ref: BidRef) -> Optional[HierarchyBidInfo]:
        return self.hierarchy.find_bid_info(bid_ref)

    def bid_exists(self, bid_ref: BidRef) -> bool:
        return self.hierarchy.bid_exists(bid_ref)

    def page_exists(self, page_uid: str) -> bool:
        return self.hierarchy.page_exists(page_uid)
