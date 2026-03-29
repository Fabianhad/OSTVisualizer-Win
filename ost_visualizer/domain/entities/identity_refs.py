from dataclasses import dataclass


@dataclass(frozen=True)
class BidRef:
    file_path: str
    bid_uid: str
