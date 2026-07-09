from typing import Any, FrozenSet, Iterable, List, Union
from ...parsers.position_parser import parse_position

POSITION_TEXT_ENCODING = "latin-1"
TEXT_BLOB_ENCODING = "utf-8"
ANNOTATION_TEXT_ENCODING = "latin-1"
TEXT_POSITION_TABLES: FrozenSet[str] = frozenset(
    {
        "BidCallOuts",
        "BidComments",
        "BidTexts",
    }
)


def encode_position(position: Iterable[float]) -> bytes:
    parts = []
    for value in position:
        rounded = round(float(value), 3)
        parts.append(f"{rounded:g}")
    return (";".join(parts) + "\n").encode(POSITION_TEXT_ENCODING)


def serialize_position_for_table(
    table: str, position: Iterable[float]
) -> Union[bytes, str]:
    position_bytes = encode_position(position)
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
        return value.encode(ANNOTATION_TEXT_ENCODING, errors="replace")
    return value


def decode_annotation_text(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode(ANNOTATION_TEXT_ENCODING, errors="replace")
    return str(value).replace("\x00", "").replace("\r\n", "\n").strip()


def coerce_binary_column_value(value: Any) -> Any:
    if isinstance(value, str):
        return encode_text_blob(value)
    return value
