import ctypes
import os
import struct
import sys
import unittest
import uuid
from ost_visualizer.domain.services.hardware_identity import (
    HWID_VERSION,
    HardwareIdentityError,
    HardwareIdentitySource,
    MachineIdentity,
    build_hwid,
    is_canonical_hwid,
)
from ost_visualizer.infrastructure.hardware.smbios_system_uuid import (
    SmbiosSystemUuidReader,
    parse_smbios_system_uuid,
)

SYSTEM_UUID = uuid.UUID("00112233-4455-6677-8899-AABBCCDDEEFF")
OTHER_SYSTEM_UUID = uuid.UUID("10213243-5465-7687-98A9-BACBDCEDFE0F")


def _build_raw_smbios(
    system_uuid,
    version=(3, 2),
    extra_system_uuid=None,
):
    structures = []
    if system_uuid is not None:
        structures.append(_build_system_information(system_uuid, version))
    if extra_system_uuid is not None:
        structures.append(_build_system_information(extra_system_uuid, version))
    structures.append(b"\x7f\x04\xff\xff\x00\x00")
    table = b"".join(structures)
    return struct.pack("<BBBBI", 0, version[0], version[1], 0, len(table)) + table


def _build_system_information(identifier, version):
    formatted = bytearray(25)
    formatted[0] = 1
    formatted[1] = len(formatted)
    raw_uuid = identifier.bytes_le if version >= (2, 6) else identifier.bytes
    formatted[8:24] = raw_uuid
    return bytes(formatted) + b"\x00\x00"


class HwidV1Tests(unittest.TestCase):
    def test_reader_uses_windows_firmware_table_api(self):
        raw_smbios = _build_raw_smbios(SYSTEM_UUID)

        class FirmwareTableFunction:
            def __init__(self):
                self.argtypes = None
                self.restype = None
                self.calls = []

            def __call__(self, provider, table_id, buffer, buffer_size):
                self.calls.append((provider, table_id, buffer_size))
                if buffer is None:
                    return len(raw_smbios)
                ctypes.memmove(buffer, raw_smbios, len(raw_smbios))
                return len(raw_smbios)

        firmware_function = FirmwareTableFunction()
        kernel32 = type(
            "Kernel32",
            (),
            {"GetSystemFirmwareTable": firmware_function},
        )()
        observed = SmbiosSystemUuidReader(kernel32).read_system_uuid()
        self.assertEqual(observed, SYSTEM_UUID)
        self.assertEqual(len(firmware_function.calls), 2)
        self.assertTrue(
            all(
                call[0] == int.from_bytes(b"RSMB", byteorder="big")
                for call in firmware_function.calls
            )
        )
        self.assertEqual(firmware_function.calls[0][1:], (0, 0))
        self.assertEqual(firmware_function.calls[1][1:], (0, len(raw_smbios)))

    def test_reader_preserves_windows_error_code_when_size_query_fails(self):
        class FirmwareTableFunction:
            def __init__(self):
                self.argtypes = None
                self.restype = None

            def __call__(self, _provider, _table_id, _buffer, _buffer_size):
                ctypes.set_last_error(5)
                return 0

        kernel32 = type(
            "Kernel32",
            (),
            {"GetSystemFirmwareTable": FirmwareTableFunction()},
        )()
        with self.assertRaisesRegex(HardwareIdentityError, "Windows error 5"):
            SmbiosSystemUuidReader(kernel32).read_system_uuid()

    @unittest.skipUnless(
        sys.platform == "win32"
        and os.environ.get("OSTV_RUN_WINDOWS_FIRMWARE_INTEGRATION") == "1",
        "set OSTV_RUN_WINDOWS_FIRMWARE_INTEGRATION=1 for the live firmware API test",
    )
    def test_live_windows_firmware_api_returns_valid_system_uuid(self):
        reader = SmbiosSystemUuidReader()
        raw_smbios = reader._read_raw_smbios()
        self.assertGreaterEqual(len(raw_smbios), 8)
        identifier = parse_smbios_system_uuid(raw_smbios)
        self.assertIsInstance(identifier, uuid.UUID)
        self.assertEqual(reader.read_system_uuid(), identifier)

    def test_smbios_uuid_is_parsed_with_canonical_byte_order(self):
        raw = _build_raw_smbios(SYSTEM_UUID, version=(3, 2))
        parsed = parse_smbios_system_uuid(raw)
        self.assertEqual(parsed, SYSTEM_UUID)
        identity = MachineIdentity.create(
            HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
            parsed,
        )
        self.assertEqual(identity.identifier, str(SYSTEM_UUID).upper())

    def test_pre_2_6_smbios_uuid_uses_network_byte_order(self):
        raw = _build_raw_smbios(SYSTEM_UUID, version=(2, 5))
        self.assertEqual(parse_smbios_system_uuid(raw), SYSTEM_UUID)

    def test_unusable_smbios_uuids_are_rejected(self):
        unusable = (
            uuid.UUID(int=0),
            uuid.UUID(int=(1 << 128) - 1),
            uuid.UUID("00010203-0405-0607-0809-0A0B0C0D0E0F"),
            uuid.UUID("03000200-0400-0500-0006-000700080009"),
            uuid.UUID("DEADBEEF-DEAD-BEEF-DEAD-BEEFDEADBEEF"),
        )
        for identifier in unusable:
            with self.subTest(identifier=identifier):
                self.assertIsNone(
                    parse_smbios_system_uuid(_build_raw_smbios(identifier))
                )

    def test_legitimate_non_rfc_and_sparse_vendor_uuids_are_accepted(self):
        identifiers = (
            uuid.UUID("12345678-1234-0000-0011-223344556677"),
            uuid.UUID("00000000-0000-0000-0000-000000000001"),
            uuid.UUID("00112233-4455-6677-C899-AABBCCDDEEFF"),
        )
        for identifier in identifiers:
            with self.subTest(identifier=identifier):
                self.assertEqual(
                    parse_smbios_system_uuid(_build_raw_smbios(identifier)),
                    identifier,
                )

    def test_missing_system_information_record_returns_no_uuid(self):
        self.assertIsNone(parse_smbios_system_uuid(_build_raw_smbios(None)))

    def test_duplicate_identical_system_information_records_are_accepted(self):
        raw = _build_raw_smbios(SYSTEM_UUID, extra_system_uuid=SYSTEM_UUID)
        self.assertEqual(parse_smbios_system_uuid(raw), SYSTEM_UUID)

    def test_malformed_smbios_is_an_explicit_failure(self):
        malformed_tables = (
            b"",
            struct.pack("<BBBBI", 0, 3, 2, 0, 0),
            struct.pack("<BBBBI", 0, 3, 2, 0, 4) + b"\x01\x03\x00\x00",
            struct.pack("<BBBBI", 0, 3, 2, 0, 8) + b"\x01\x19\x00\x00\x00\x00\x00\x00",
        )
        for raw in malformed_tables:
            with self.subTest(raw=raw):
                with self.assertRaises(HardwareIdentityError):
                    parse_smbios_system_uuid(raw)

    def test_conflicting_system_information_records_are_rejected(self):
        raw = _build_raw_smbios(SYSTEM_UUID, extra_system_uuid=OTHER_SYSTEM_UUID)
        with self.assertRaisesRegex(HardwareIdentityError, "conflicting"):
            parse_smbios_system_uuid(raw)
