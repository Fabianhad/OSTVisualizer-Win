from typing import Optional
from PySide6 import QtCore


def encode_byte_array(value: QtCore.QByteArray) -> Optional[str]:
    if value is None or value.isEmpty():
        return None
    return bytes(value.toBase64()).decode("ascii")


def decode_byte_array(value: Optional[str]) -> QtCore.QByteArray:
    if not value or not isinstance(value, str):
        return QtCore.QByteArray()
    if not value.isascii():
        return QtCore.QByteArray()
    return QtCore.QByteArray.fromBase64(value.encode("ascii"))
