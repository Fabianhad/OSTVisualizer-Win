from dataclasses import dataclass
from typing import Optional


@dataclass
class HotlinkDto:
    uid: str
    bid_page_uid: str
    target_view_uid: Optional[str]
    center_x: float
    center_y: float
    radius: float
