from dataclasses import dataclass
from typing import Optional


@dataclass
class BidConditionFolder:
    uid: str
    name: str = ""
    bid_uid: str = ""
    parent_uid: Optional[str] = None
