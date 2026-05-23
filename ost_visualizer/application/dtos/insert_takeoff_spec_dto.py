from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class InsertTakeoffSpec:
    condition_uid: str
    page_uid: str
    area_uid: Optional[str]
    position: List[float]
    parent_uid: Optional[str] = None
    curve: int = -1
    rotation: float = 0.0
    is_negative: bool = False
    raw_extras: Dict[str, Any] = field(default_factory=dict)
    source_bid_uid: Optional[str] = None
