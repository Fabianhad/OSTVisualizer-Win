import ctypes
import os
import struct
import sys
import unittest
import uuid
from ctypes import wintypes
from ost_visualizer.domain.services.hardware_identity import (
    HardwareIdentityError,
    HardwareIdentitySource,
    MachineIdentity,
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


def _build_raw_table(table, version=(3, 2)):
    return struct.pack("<BBBBI", 0, version[0], version[1], 0, len(table)) + table


def _firmware_kernel32(size_result, read_result=None, last_error=0, raw=b""):
    class FirmwareTableFunction:
        def __init__(self):
            self.argtypes = None
            self.restype = None
            self.calls = 0

        def __call__(self, _provider, _table_id, buffer, buffer_size):
            self.calls += 1
            ctypes.set_last_error(last_error)
            if buffer is None:
                return size_result
            ctypes.memmove(buffer, raw, min(len(raw), buffer_size))
            return read_result

    return type("Kernel32", (), {"GetSystemFirmwareTable": FirmwareTableFunction()})()


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
        self.assertEqual(
            firmware_function.argtypes,
            [wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD],
        )
        self.assertIs(firmware_function.restype, wintypes.UINT)

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
        with self.assertRaisesRegex(
            HardwareIdentityError,
            r"size \(Windows error 5: .+\)",
        ):
            SmbiosSystemUuidReader(kernel32).read_system_uuid()

    def test_reader_reports_missing_error_code_when_size_query_fails(self):
        kernel32 = _firmware_kernel32(size_result=0)
        with self.assertRaisesRegex(
            HardwareIdentityError,
            r"table size \(Windows did not report an error code\)",
        ):
            SmbiosSystemUuidReader(kernel32).read_system_uuid()
        self.assertEqual(kernel32.GetSystemFirmwareTable.calls, 1)

    def test_reader_preserves_windows_error_code_when_table_read_fails(self):
        raw_smbios = _build_raw_smbios(SYSTEM_UUID)
        kernel32 = _firmware_kernel32(
            size_result=len(raw_smbios),
            read_result=0,
            last_error=122,
        )
        with self.assertRaisesRegex(
            HardwareIdentityError,
            r"read the SMBIOS firmware table \(Windows error 122: .+\)",
        ):
            SmbiosSystemUuidReader(kernel32).read_system_uuid()
        self.assertEqual(kernel32.GetSystemFirmwareTable.calls, 2)

    def test_reader_rejects_firmware_table_that_grows_between_calls(self):
        raw_smbios = _build_raw_smbios(SYSTEM_UUID)
        kernel32 = _firmware_kernel32(
            size_result=len(raw_smbios),
            read_result=len(raw_smbios) + 1,
            raw=raw_smbios,
        )
        with self.assertRaisesRegex(
            HardwareIdentityError,
            rf"allocated {len(raw_smbios)} bytes, now requires {len(raw_smbios) + 1}",
        ):
            SmbiosSystemUuidReader(kernel32).read_system_uuid()

    def test_reader_truncates_to_the_byte_count_written_by_windows(self):
        raw_smbios = _build_raw_smbios(SYSTEM_UUID)
        padded_size = len(raw_smbios) + 16
        kernel32 = _firmware_kernel32(
            size_result=padded_size,
            read_result=len(raw_smbios),
            raw=raw_smbios,
        )
        reader = SmbiosSystemUuidReader(kernel32)
        self.assertEqual(reader._read_raw_smbios(), raw_smbios)
        self.assertEqual(reader.read_system_uuid(), SYSTEM_UUID)

    def test_reader_requires_the_windows_firmware_table_api(self):
        with self.assertRaisesRegex(HardwareIdentityError, "API is unavailable"):
            SmbiosSystemUuidReader(type("Kernel32", (), {})())

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

    def test_smbios_uuid_byte_order_switches_exactly_at_version_2_6(self):
        network_order = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
        mixed_order = bytes.fromhex("33221100554477668899AABBCCDDEEFF")
        cases = (
            ((2, 0), network_order),
            ((2, 5), network_order),
            ((2, 6), mixed_order),
            ((2, 7), mixed_order),
            ((3, 0), mixed_order),
            ((3, 2), mixed_order),
        )
        for version, field in cases:
            formatted = bytearray(25)
            formatted[0] = 1
            formatted[1] = len(formatted)
            formatted[8:24] = field
            table = bytes(formatted) + b"\x00\x00" + b"\x7f\x04\xff\xff\x00\x00"
            with self.subTest(version=version):
                self.assertEqual(
                    parse_smbios_system_uuid(_build_raw_table(table, version)),
                    SYSTEM_UUID,
                )

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

    def test_unusable_record_does_not_hide_a_usable_system_uuid(self):
        raw = _build_raw_smbios(
            uuid.UUID(int=0),
            extra_system_uuid=SYSTEM_UUID,
        )
        self.assertEqual(parse_smbios_system_uuid(raw), SYSTEM_UUID)

    def test_other_structures_strings_and_post_end_records_are_skipped(self):
        decoy = bytearray(25)
        decoy[0] = 4
        decoy[1] = len(decoy)
        decoy[8:24] = OTHER_SYSTEM_UUID.bytes_le
        bios = b"\x00\x06\x00\x00\x01\x02" + b"Vendor\x00Version\x00\x00"
        system = bytearray(25)
        system[0] = 1
        system[1] = len(system)
        system[4] = 1
        system[8:24] = SYSTEM_UUID.bytes_le
        system_record = bytes(system) + b"Maker\x00\x00"
        end_of_table = b"\x7f\x04\xff\xff\x00\x00"
        after_end = _build_system_information(OTHER_SYSTEM_UUID, (3, 2))
        table = (
            bios + bytes(decoy) + b"\x00\x00" + system_record + end_of_table + after_end
        )
        self.assertEqual(
            parse_smbios_system_uuid(_build_raw_table(table)),
            SYSTEM_UUID,
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
            (b"", "header is malformed"),
            (b"\x00\x03\x02\x00\x00\x00", "header is malformed"),
            (struct.pack("<BBBBI", 0, 3, 2, 0, 0), "table length is invalid"),
            (
                struct.pack("<BBBBI", 0, 3, 2, 0, 100) + b"\x7f\x04\xff\xff",
                "table length is invalid",
            ),
            (
                struct.pack("<BBBBI", 0, 3, 2, 0, 4) + b"\x01\x03\x00\x00",
                "structure length is invalid",
            ),
            (
                struct.pack("<BBBBI", 0, 3, 2, 0, 8)
                + b"\x01\x19\x00\x00\x00\x00\x00\x00",
                "structure is truncated",
            ),
            (
                _build_raw_table(b"\x00\x04\x01\x02"),
                "string table is unterminated",
            ),
            (
                _build_raw_table(b"\x00\x04\x00\x00\x00\x00" + b"\x01\x02\x03"),
                "structure header is truncated",
            ),
            (
                _build_raw_table(b"\x01\x14" + bytes(18) + b"\x00\x00"),
                "System UUID field is truncated",
            ),
        )
        for raw, message in malformed_tables:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(HardwareIdentityError, message):
                    parse_smbios_system_uuid(raw)

    def test_conflicting_system_information_records_are_rejected(self):
        raw = _build_raw_smbios(SYSTEM_UUID, extra_system_uuid=OTHER_SYSTEM_UUID)
        with self.assertRaisesRegex(HardwareIdentityError, "conflicting"):
            parse_smbios_system_uuid(raw)
