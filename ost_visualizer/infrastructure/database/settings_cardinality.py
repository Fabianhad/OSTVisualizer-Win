from .schema_inspector_contract import IDatabaseSchemaInspector
from ...shared.texts import (
    SETTINGS_CARDINALITY_MESSAGE_SETTINGS_HAS_MULTIPLE_ROWS_EXPECTED_AT,
    SETTINGS_CARDINALITY_MESSAGE_THIS_DATABASE_CAN_BE_READ_BUT,
    SETTINGS_CARDINALITY_MESSAGE_THIS_DATABASE_CAN_BE_READ_BUT_2,
)


class GlobalSettingsCardinalityError(RuntimeError):
    """Raised when the database has more than one global Settings record."""


class BidNumberAllocationUnavailableError(RuntimeError):
    """Raised when a readable legacy database cannot allocate durable bid numbers."""


def require_writable_bid_number_allocator(
    schema: IDatabaseSchemaInspector,
) -> None:
    if schema.optional_table_missing("Settings"):
        raise BidNumberAllocationUnavailableError(
            SETTINGS_CARDINALITY_MESSAGE_THIS_DATABASE_CAN_BE_READ_BUT
        )
    if not schema.column_exists("Settings", "NextBidNo"):
        raise BidNumberAllocationUnavailableError(
            SETTINGS_CARDINALITY_MESSAGE_THIS_DATABASE_CAN_BE_READ_BUT_2
        )


def fetch_optional_global_settings_row(
    cursor,
    select_clause: str,
    *,
    table_sql: str = "[Settings]",
):
    cursor.execute(f"SELECT {select_clause} FROM {table_sql}")
    row = cursor.fetchone()
    if row is not None and cursor.fetchone() is not None:
        raise GlobalSettingsCardinalityError(
            SETTINGS_CARDINALITY_MESSAGE_SETTINGS_HAS_MULTIPLE_ROWS_EXPECTED_AT
        )
    return row


def persist_next_bid_number(
    cursor,
    settings_row,
    next_bid_number: int,
    *,
    table_sql: str = "[Settings]",
) -> None:
    if settings_row is None:
        cursor.execute(
            f"INSERT INTO {table_sql} ([NextBidNo]) VALUES (?)",
            next_bid_number,
        )
        return
    cursor.execute(
        f"UPDATE {table_sql} SET [NextBidNo] = ?",
        next_bid_number,
    )


def normalize_next_bid_number(value) -> int:
    parsed = int(value) if value not in (None, "") else 1
    return parsed if parsed != 0 else 1
