from dataclasses import dataclass, field
from typing import Optional
from .hierarchy_data import HierarchyBidInfo, HierarchyData
from .identity_refs import BidRef


@dataclass
class Hierarchy:
    data: HierarchyData = field(default_factory=HierarchyData)

    def set(self, hierarchy: HierarchyData) -> None:
        self.data = hierarchy if hierarchy is not None else HierarchyData()

    def find_bid_info(self, bid_ref: BidRef) -> Optional[HierarchyBidInfo]:
        return self.data.find_bid_info(bid_ref)

    def bid_exists(self, bid_ref: BidRef) -> bool:
        return self.data.bid_exists(bid_ref)

    def page_exists(self, page_uid: str) -> bool:
        return self.data.page_exists(page_uid)
