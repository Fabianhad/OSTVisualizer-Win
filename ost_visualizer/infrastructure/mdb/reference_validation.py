from typing import Dict, Iterable, List, Set

UID_NULL_VALUES = (None, "", "0", "NULL")


def is_present_uid(value: str) -> bool:
    return value not in UID_NULL_VALUES


def collect_present_uids(rows: Iterable[Dict[str, str]]) -> Set[str]:
    return {row.get("UID", "") for row in rows if is_present_uid(row.get("UID", ""))}


def row_has_valid_page_reference(
    row: Dict[str, str], valid_page_uids: Set[str]
) -> bool:
    page_uid = row.get("BidPageUID", "")
    return not is_present_uid(page_uid) or page_uid in valid_page_uids


def row_has_valid_named_view_reference(
    row: Dict[str, str], valid_named_view_uids: Set[str]
) -> bool:
    named_view_uid = row.get("BidPageViewUID", "")
    return not is_present_uid(named_view_uid) or named_view_uid in valid_named_view_uids


def filter_page_referenced_rows(
    rows: List[Dict[str, str]], valid_page_uids: Set[str]
) -> List[Dict[str, str]]:
    return [row for row in rows if row_has_valid_page_reference(row, valid_page_uids)]


def filter_hotlink_rows(
    rows: List[Dict[str, str]],
    valid_page_uids: Set[str],
    valid_named_view_uids: Set[str],
) -> List[Dict[str, str]]:
    page_valid_rows = filter_page_referenced_rows(rows, valid_page_uids)
    return [
        row
        for row in page_valid_rows
        if row_has_valid_named_view_reference(row, valid_named_view_uids)
    ]
