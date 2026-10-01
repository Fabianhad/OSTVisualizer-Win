from dataclasses import dataclass
from typing import Optional
from ...domain.entities.bid import Bid
from ...domain.entities.condition import Condition
from ...domain.entities.condition_folder import BidConditionFolder
from .write_reload_result import WriteReloadResult


@dataclass(frozen=True)
class CreatedConditionProjection:
    previous_bid: Bid
    bid: Bid
    condition: Condition
    folder: Optional[BidConditionFolder]


@dataclass
class CreateConditionResult(WriteReloadResult):
    projection: Optional[CreatedConditionProjection] = None
