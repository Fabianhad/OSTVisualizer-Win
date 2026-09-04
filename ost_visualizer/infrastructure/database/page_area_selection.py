from collections.abc import Mapping
from typing import TypeVar

_PageSettingRow = TypeVar("_PageSettingRow", bound=Mapping[str, object])


def _integer_or_zero(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def canonicalize_page_area_settings(
    rows: list[_PageSettingRow],
) -> list[_PageSettingRow]:
    inactive_rows: list[_PageSettingRow] = []
    selected_by_page: dict[str, _PageSettingRow] = {}
    for row in rows:
        selected_value = _integer_or_zero(row.get("BidAreaSelected"))
        if selected_value <= 0:
            inactive_rows.append(row)
            continue
        page_uid = str(row.get("BidPageUID") or "")
        current = selected_by_page.get(page_uid)
        if current is None:
            selected_by_page[page_uid] = row
            continue
        current_rank = (
            _integer_or_zero(current.get("BidAreaSelected")),
            _integer_or_zero(current.get("UID")),
        )
        row_rank = (selected_value, _integer_or_zero(row.get("UID")))
        if row_rank >= current_rank:
            selected_by_page[page_uid] = row
    return inactive_rows + list(selected_by_page.values())
