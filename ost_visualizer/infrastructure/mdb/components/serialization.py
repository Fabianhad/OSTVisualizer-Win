from typing import Any, FrozenSet, Iterable, List, Union
from ....domain.utils.position import parse_position
from ...database.annotation_storage import ANNOTATION_TYPE_BY_TABLE

POSITION_TEXT_ENCODING = "latin-1"
TEXT_BLOB_ENCODING = "utf-8"
ANNOTATION_TEXT_ENCODING = "latin-1"
ANNOTATION_TEXT_BLOB_TABLES = frozenset({"BidTexts", "BidCallOuts"})
TEXT_POSITION_TABLES: FrozenSet[str] = frozenset(
    {
        "BidCallOuts",
        "BidComments",
        "BidTexts",
    }
)


def encode_position(
    position: Iterable[float], *, preserve_indices: frozenset[int] = frozenset()
) -> bytes:
    parts = []
    for index, value in enumerate(position):
        if index in preserve_indices:
            parts.append(str(float(value)))
        else:
            rounded = round(float(value), 3)
            parts.append(f"{rounded:.3f}".rstrip("0").rstrip("."))
    return (";".join(parts) + "\n").encode(POSITION_TEXT_ENCODING)


def serialize_position_for_table(
    table: str,
    position: Iterable[float],
    *,
    preserve_indices: frozenset[int] = frozenset(),
) -> Union[bytes, str]:
    if table in ANNOTATION_TYPE_BY_TABLE:
        position = tuple(position)
        preserve_indices = frozenset(range(len(position)))
    position_bytes = encode_position(position, preserve_indices=preserve_indices)
    if table in TEXT_POSITION_TABLES:
        return position_bytes.decode(POSITION_TEXT_ENCODING)
    return position_bytes


def parse_position_storage(value: Any) -> List[float]:
    if not value:
        return []
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode(POSITION_TEXT_ENCODING, errors="replace")
    return parse_position(str(value))


def encode_text_blob(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return value.encode(TEXT_BLOB_ENCODING)
    return value


def decode_text_blob(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode(TEXT_BLOB_ENCODING, errors="replace")
    return str(value)


def encode_annotation_text(value: Any) -> Any:
    if isinstance(value, str):
        return value.encode(ANNOTATION_TEXT_ENCODING)
    return value


def decode_annotation_text(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode(ANNOTATION_TEXT_ENCODING, errors="replace")
    return str(value).replace("\x00", "").replace("\r\n", "\n")


def coerce_binary_column_value(value: Any) -> Any:
    if isinstance(value, str):
        return encode_text_blob(value)
    return value
