from dataclasses import dataclass


@dataclass(frozen=True)
class ConditionTakeoffReassignment:
    condition_uid: str
    page_uid: str
    takeoff_uids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.condition_uid or not self.page_uid or not self.takeoff_uids:
            raise ValueError("Condition reassignment requires a Page and Takeoffs.")
        if any(not uid for uid in self.takeoff_uids) or len(
            set(self.takeoff_uids)
        ) != len(self.takeoff_uids):
            raise ValueError(
                "Condition reassignment requires distinct Takeoff identities."
            )
