import ctypes
import struct
import uuid
from ctypes import wintypes
from typing import Optional
from ...domain.services.hardware_identity import (
    HardwareIdentityError,
    is_usable_identity_uuid,
)

_RAW_SMBIOS_PROVIDER = int.from_bytes(b"RSMB", byteorder="big")
_RAW_SMBIOS_HEADER_SIZE = 8
_SMBIOS_STRUCTURE_HEADER_SIZE = 4
_SYSTEM_INFORMATION_TYPE = 1
_END_OF_TABLE_TYPE = 127
_SYSTEM_UUID_OFFSET = 8
_SYSTEM_UUID_LENGTH = 16


class SmbiosSystemUuidReader:
    def __init__(self, kernel32=None) -> None:
        self._api = (
            ctypes.WinDLL("kernel32", use_last_error=True)
            if kernel32 is None
            else kernel32
        )
        self._configure_api()

    def read_system_uuid(self) -> Optional[uuid.UUID]:
        raw_smbios = self._read_raw_smbios()
        return parse_smbios_system_uuid(raw_smbios)

    def _configure_api(self) -> None:
        try:
            function = self._api.GetSystemFirmwareTable
            function.argtypes = [
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
            ]
            function.restype = wintypes.UINT
        except AttributeError as exc:
            raise HardwareIdentityError(
                "The Windows SMBIOS firmware API is unavailable"
            ) from exc

    def _read_raw_smbios(self) -> bytes:
        ctypes.set_last_error(0)
        size = self._api.GetSystemFirmwareTable(
            _RAW_SMBIOS_PROVIDER,
            0,
            None,
            0,
        )
        if not size:
            raise _firmware_api_error("Unable to query the SMBIOS firmware table size")
        buffer = ctypes.create_string_buffer(size)
        ctypes.set_last_error(0)
        written = self._api.GetSystemFirmwareTable(
            _RAW_SMBIOS_PROVIDER,
            0,
            buffer,
            size,
        )
        if not written:
            raise _firmware_api_error("Unable to read the SMBIOS firmware table")
        if written > size:
            raise HardwareIdentityError(
                "The SMBIOS firmware table grew while it was being read "
                f"(allocated {size} bytes, now requires {written})"
            )
        return buffer.raw[:written]


def _firmware_api_error(message: str) -> HardwareIdentityError:
    error_code = ctypes.get_last_error()
    if not error_code:
        return HardwareIdentityError(
            f"{message} (Windows did not report an error code)"
        )
    error_text = ctypes.FormatError(error_code).strip()
    return HardwareIdentityError(
        f"{message} (Windows error {error_code}: {error_text})"
    )


def parse_smbios_system_uuid(raw_smbios: bytes) -> Optional[uuid.UUID]:
    if len(raw_smbios) < _RAW_SMBIOS_HEADER_SIZE:
        raise HardwareIdentityError("The SMBIOS firmware table header is malformed")
    major, minor, table_length = _parse_raw_header(raw_smbios)
    table_end = _RAW_SMBIOS_HEADER_SIZE + table_length
    if table_length <= 0 or table_end > len(raw_smbios):
        raise HardwareIdentityError("The SMBIOS firmware table length is invalid")
    table = raw_smbios[_RAW_SMBIOS_HEADER_SIZE:table_end]
    identifiers = _collect_system_uuids(table, major, minor)
    if not identifiers:
        return None
    if len(identifiers) != 1:
        raise HardwareIdentityError(
            "The SMBIOS firmware table contains conflicting System UUIDs"
        )
    return next(iter(identifiers))


def _parse_raw_header(raw_smbios: bytes) -> tuple[int, int, int]:
    _calling_method, major, minor, _revision, table_length = struct.unpack_from(
        "<BBBBI",
        raw_smbios,
        0,
    )
    return major, minor, table_length


def _collect_system_uuids(
    table: bytes,
    major: int,
    minor: int,
) -> set[uuid.UUID]:
    identifiers = set()
    offset = 0
    while offset < len(table):
        if offset + _SMBIOS_STRUCTURE_HEADER_SIZE > len(table):
            raise HardwareIdentityError("An SMBIOS structure header is truncated")
        structure_type = table[offset]
        structure_length = table[offset + 1]
        if structure_length < _SMBIOS_STRUCTURE_HEADER_SIZE:
            raise HardwareIdentityError("An SMBIOS structure length is invalid")
        formatted_end = offset + structure_length
        if formatted_end > len(table):
            raise HardwareIdentityError("An SMBIOS structure is truncated")
        strings_end = table.find(b"\x00\x00", formatted_end)
        if strings_end < 0:
            raise HardwareIdentityError("An SMBIOS string table is unterminated")
        if structure_type == _SYSTEM_INFORMATION_TYPE:
            identifier = _parse_system_information_uuid(
                table[offset:formatted_end],
                major,
                minor,
            )
            if identifier is not None:
                identifiers.add(identifier)
        offset = strings_end + 2
        if structure_type == _END_OF_TABLE_TYPE:
            break
    return identifiers


def _parse_system_information_uuid(
    structure: bytes,
    major: int,
    minor: int,
) -> Optional[uuid.UUID]:
    uuid_end = _SYSTEM_UUID_OFFSET + _SYSTEM_UUID_LENGTH
    if len(structure) < uuid_end:
        raise HardwareIdentityError("The SMBIOS System UUID field is truncated")
    raw_uuid = structure[_SYSTEM_UUID_OFFSET:uuid_end]
    identifier = (
        uuid.UUID(bytes_le=raw_uuid)
        if (major, minor) >= (2, 6)
        else uuid.UUID(bytes=raw_uuid)
    )
    return identifier if is_usable_identity_uuid(identifier) else None
