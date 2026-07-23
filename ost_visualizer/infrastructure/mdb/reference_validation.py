UID_NULL_VALUES = frozenset({"", "0", "NULL"})


def is_present_uid(value: str) -> bool:
    return value not in UID_NULL_VALUES
