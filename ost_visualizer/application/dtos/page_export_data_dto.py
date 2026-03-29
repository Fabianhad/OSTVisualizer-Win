from dataclasses import dataclass, field
from typing import Dict, List
from ...domain.entities.condition import Condition
from ...domain.entities.page import Page
from ...domain.entities.takeoff import Takeoff


@dataclass
class PageExportData:
    page: Page
    bid_takeoffs: List[Takeoff] = field(default_factory=list)
    bid_conditions: Dict[str, Condition] = field(default_factory=dict)
