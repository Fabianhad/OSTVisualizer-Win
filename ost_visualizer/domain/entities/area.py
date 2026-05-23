from dataclasses import dataclass
from typing import List


@dataclass
class BidArea:
    uid: str
    bid_uid: str
    parent_uid: str
    name: str
    sequence: int
    guid: str = ""


@dataclass
class BidAreaChangeset:
    new: List[BidArea]
    updated: List[BidArea]
    deleted_uids: List[str]
