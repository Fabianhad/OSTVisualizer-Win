from dataclasses import dataclass
from typing import List

UNASSIGNED_AREA_UID = "0"


def normalize_area_uid(area_uid) -> str:
    uid = str(area_uid or "").strip()
    return uid or UNASSIGNED_AREA_UID


def is_unassigned_area_uid(area_uid) -> bool:
    return normalize_area_uid(area_uid) == UNASSIGNED_AREA_UID


def area_group_uid(area_uid) -> str:
    uid = normalize_area_uid(area_uid)
    return "" if uid == UNASSIGNED_AREA_UID else uid


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
