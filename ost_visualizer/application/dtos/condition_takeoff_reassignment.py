from dataclasses import dataclass
from ...shared.texts import (
    CONDITION_TAKEOFF_REASSIGNMENT_MESSAGE_CONDITION_REASSIGNMENT_REQUIRES_A_PAGE_AND,
    CONDITION_TAKEOFF_REASSIGNMENT_MESSAGE_CONDITION_REASSIGNMENT_REQUIRES_DISTINCT_TAKEOFF,
)


@dataclass(frozen=True)
class ConditionTakeoffReassignment:
    condition_uid: str
    page_uid: str
    takeoff_uids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.condition_uid or not self.page_uid or not self.takeoff_uids:
            raise ValueError(
                CONDITION_TAKEOFF_REASSIGNMENT_MESSAGE_CONDITION_REASSIGNMENT_REQUIRES_A_PAGE_AND
            )
        if any(not uid for uid in self.takeoff_uids) or len(
            set(self.takeoff_uids)
        ) != len(self.takeoff_uids):
            raise ValueError(
                CONDITION_TAKEOFF_REASSIGNMENT_MESSAGE_CONDITION_REASSIGNMENT_REQUIRES_DISTINCT_TAKEOFF
            )
