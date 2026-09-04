from typing import Sequence


class BidSettingsCardinalityError(RuntimeError):
    """Raised when a bid has more than one settings record."""


def fetch_optional_bid_settings_row(cursor, bid_uid, columns: Sequence[str]):
    selected_columns = ", ".join(f"[{column}]" for column in columns)
    cursor.execute(
        f"SELECT {selected_columns} FROM [BidSettings] WHERE [BidUID]=?",
        bid_uid,
    )
    row = cursor.fetchone()
    if row is not None and cursor.fetchone() is not None:
        raise BidSettingsCardinalityError(
            f"BidSettings has multiple rows for Bids.UID={bid_uid}; "
            "expected at most one."
        )
    return row
