from dataclasses import dataclass, field
from typing import Dict, List

RawRow = Dict[str, str]
RawTable = List[RawRow]


@dataclass
class RawBidData:
    bid_row: RawRow = field(default_factory=dict)
    bid_tables: Dict[str, RawTable] = field(default_factory=dict)
    page_tables: Dict[str, RawTable] = field(default_factory=dict)
    global_tables: Dict[str, RawTable] = field(default_factory=dict)
