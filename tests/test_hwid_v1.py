import ctypes
import inspect
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import pywintypes
from ost_visualizer.application.use_cases.license.activate_license_use_case import (
    ActivateLicenseUseCase,
)
from ost_visualizer.application.use_cases.license.validate_license_use_case import (
    ValidateLicenseUseCase,
)
from ost_visualizer.application.use_cases.license.utils.license_use_case import (
    ERROR_CONTRACT,
    ERROR_INVALID_HWID,
)
from ost_visualizer.application.dtos.license_dto import LicenseOperationStatus
from ost_visualizer.domain.aggregates.license_aggregate import LicenseAggregate
from ost_visualizer.domain.entities.license import License, LicenseStatus
from ost_visualizer.domain.services.hardware_identity import (
    HWID_VERSION,
    HardwareIdentityError,
    HardwareIdentitySource,
    MachineIdentity,
    build_hwid,
    is_canonical_hwid,
)
from ost_visualizer.infrastructure.app_paths import get_machine_app_data_dir
from ost_visualizer.infrastructure.external.license_api_client import LicenseApiClient
from ost_visualizer.infrastructure.hardware import hwid_generator, smbios_system_uuid
from ost_visualizer.infrastructure.hardware.hwid_generator import HWIDGenerator
from ost_visualizer.infrastructure.hardware.smbios_system_uuid import (
    SmbiosSystemUuidReader,
    parse_smbios_system_uuid,
)
from ost_visualizer.infrastructure.persistence.repositories.json_license_repository import (
    JsonLicenseRepository,
)

SYSTEM_UUID = uuid.UUID("00112233-4455-6677-8899-AABBCCDDEEFF")
OTHER_SYSTEM_UUID = uuid.UUID("10213243-5465-7687-98A9-BACBDCEDFE0F")
INSTALLATION_UUID = uuid.UUID("AABBCCDD-EEFF-4011-9234-56789ABCDEF0")


class FixedSystemUuidReader:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def read_system_uuid(self):
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class MemoryLicenseRepository:
    def __init__(self, value=None):
        self.value = value
        self.cleared = False

    def load(self):
        if self.value is None:
            raise FileNotFoundError
        return self.value

    def save(self, value):
        self.value = value

    def clear(self):
        self.cleared = True
        self.value = None


class AcceptingSignatureVerifier:
    def __init__(self):
        self.payloads = []

    def verify_license_payload(self, payload, signature):
        self.payloads.append((payload, signature))
        return True


class RecordingLicenseApi:
    def __init__(self):
        self.calls = []

    def activate(self, license_key, hwid):
        self.calls.append(("activate", license_key, hwid))
        return True, {
            "success": True,
            "expiry_date": "2099-01-01T00:00:00+00:00",
            "signature": "signed",
        }

    def validate(self, license_key, hwid):
        self.calls.append(("validate", license_key, hwid))
        return True, {
            "valid": True,
            "expiry_date": "2099-01-01T00:00:00+00:00",
            "signature": "signed",
        }


class RejectingHardwareIdApi:
    def __init__(self):
        self.calls = []

    def activate(self, license_key, hwid):
        self.calls.append((license_key, hwid))
        return False, {
            "success": False,
            "error": "HWID too long",
            "error_name": ERROR_INVALID_HWID,
            "error_code": ERROR_CONTRACT[ERROR_INVALID_HWID],
        }

    def validate(self, license_key, hwid):
        self.calls.append((license_key, hwid))
        return False, {
            "valid": False,
            "error": "HWID too long",
            "error_name": ERROR_INVALID_HWID,
            "error_code": ERROR_CONTRACT[ERROR_INVALID_HWID],
        }


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

    def test_hwid_formula_is_canonical_full_sha256(self):
        identity = MachineIdentity.create(
            HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
            SYSTEM_UUID,
        )
        hwid = build_hwid(identity)
        self.assertEqual(
            hwid,
            "v1:B216EAC22D5562B0F8448312C46EE0C55E5F8AB6EF7BB1D8F799C020761525AD",
        )
        self.assertTrue(is_canonical_hwid(hwid))
        self.assertFalse(is_canonical_hwid(hwid.lower()))
        self.assertFalse(is_canonical_hwid("A" * 16))

    def test_machine_identity_rejects_noncanonical_contract_values(self):
        for identity_args in (
            (
                "unsupported",
                HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
                str(SYSTEM_UUID).upper(),
            ),
            (HWID_VERSION, "unknown_source", str(SYSTEM_UUID).upper()),
            (
                HWID_VERSION,
                HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
                str(SYSTEM_UUID).lower(),
            ),
        ):
            with self.subTest(identity_args=identity_args):
                with self.assertRaises(ValueError):
                    MachineIdentity(*identity_args)

    def test_smbios_identity_is_stable_across_application_restarts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            identity_path = Path(temp_dir) / "hardware_identity_v1.json"
            first = HWIDGenerator(
                identity_path=identity_path,
                system_uuid_reader=FixedSystemUuidReader(SYSTEM_UUID),
            ).get_hwid()
            second = HWIDGenerator(
                identity_path=identity_path,
                system_uuid_reader=FixedSystemUuidReader(SYSTEM_UUID),
            ).get_hwid()
        self.assertEqual(first, second)

    def test_default_identity_path_uses_canonical_v1_filename(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "ost_visualizer.infrastructure.hardware.hwid_generator."
            "get_machine_app_data_dir",
            return_value=Path(temp_dir),
        ):
            HWIDGenerator(
                system_uuid_reader=FixedSystemUuidReader(SYSTEM_UUID)
            ).get_hwid()
            self.assertTrue((Path(temp_dir) / "hardware_identity_v1.json").is_file())

    def test_unrelated_machine_and_session_changes_do_not_affect_hwid(self):
        scenarios = (
            "elevation",
            "windows_user",
            "wmic_feature_removal",
            "network_adapter",
            "disk_or_drive_letter",
            "gpu_or_ram",
            "dock_or_undock",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            identity_path = Path(temp_dir) / "hardware_identity_v1.json"
            baseline = HWIDGenerator(
                identity_path=identity_path,
                system_uuid_reader=FixedSystemUuidReader(SYSTEM_UUID),
            ).get_hwid()
            for scenario in scenarios:
                with self.subTest(scenario=scenario), patch.dict(
                    os.environ,
                    {
                        "USERNAME": f"user-for-{scenario}",
                        "USERPROFILE": f"C:\\Users\\{scenario}",
                        "OST_TEST_MACHINE_CHANGE": scenario,
                    },
                ), patch.object(
                    subprocess,
                    "run",
                    side_effect=AssertionError("WMIC must not be called"),
                ):
                    observed = HWIDGenerator(
                        identity_path=identity_path,
                        system_uuid_reader=FixedSystemUuidReader(SYSTEM_UUID),
                    ).get_hwid()
                    self.assertEqual(observed, baseline)

    def test_generator_has_only_canonical_identity_sources(self):
        production_source = (
            inspect.getsource(hwid_generator) + inspect.getsource(smbios_system_uuid)
        ).lower()
        for forbidden in (
            "wmic",
            "baseboard",
            "serialnumber",
            "install_id.txt",
            "path.home",
            "mac_address",
            "disk",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, production_source)

    def test_first_transient_smbios_failure_does_not_create_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            identity_path = Path(temp_dir) / "hardware_identity_v1.json"
            generator = HWIDGenerator(
                identity_path=identity_path,
                system_uuid_reader=FixedSystemUuidReader(
                    HardwareIdentityError("temporary firmware failure")
                ),
                identity_factory=lambda: INSTALLATION_UUID,
            )
            with self.assertRaises(HardwareIdentityError):
                generator.get_hwid()
            self.assertFalse(identity_path.exists())

    def test_pinned_smbios_failure_does_not_change_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            identity_path = Path(temp_dir) / "hardware_identity_v1.json"
            baseline = HWIDGenerator(
                identity_path=identity_path,
                system_uuid_reader=FixedSystemUuidReader(SYSTEM_UUID),
            ).get_hwid()
            persisted_before = identity_path.read_bytes()
            unavailable = HWIDGenerator(
                identity_path=identity_path,
                system_uuid_reader=FixedSystemUuidReader(
                    HardwareIdentityError("temporary firmware failure")
                ),
                identity_factory=lambda: OTHER_SYSTEM_UUID,
            )
            with self.assertRaises(HardwareIdentityError):
                unavailable.get_hwid()
            self.assertEqual(identity_path.read_bytes(), persisted_before)
            recovered = HWIDGenerator(
                identity_path=identity_path,
                system_uuid_reader=FixedSystemUuidReader(SYSTEM_UUID),
            ).get_hwid()
            self.assertEqual(recovered, baseline)

    def test_changed_pinned_smbios_uuid_is_an_explicit_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            identity_path = Path(temp_dir) / "hardware_identity_v1.json"
            HWIDGenerator(
                identity_path=identity_path,
                system_uuid_reader=FixedSystemUuidReader(SYSTEM_UUID),
            ).get_hwid()
            with self.assertRaisesRegex(HardwareIdentityError, "does not match"):
                HWIDGenerator(
                    identity_path=identity_path,
                    system_uuid_reader=FixedSystemUuidReader(OTHER_SYSTEM_UUID),
                ).get_hwid()

    def test_fallback_is_created_once_and_never_switches_to_smbios(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            identity_path = Path(temp_dir) / "hardware_identity_v1.json"
            first = HWIDGenerator(
                identity_path=identity_path,
                system_uuid_reader=FixedSystemUuidReader(None),
                identity_factory=lambda: INSTALLATION_UUID,
            ).get_hwid()
            later_reader = FixedSystemUuidReader(SYSTEM_UUID)
            second = HWIDGenerator(
                identity_path=identity_path,
                system_uuid_reader=later_reader,
                identity_factory=lambda: OTHER_SYSTEM_UUID,
            ).get_hwid()
            persisted = json.loads(identity_path.read_text(encoding="utf-8"))
        self.assertEqual(first, second)
        self.assertEqual(later_reader.calls, 0)
        self.assertEqual(persisted["version"], HWID_VERSION)
        self.assertEqual(
            persisted["source"],
            HardwareIdentitySource.INSTALLATION_UUID.value,
        )
        self.assertEqual(persisted["identifier"], str(INSTALLATION_UUID).upper())

    def test_fallback_storage_read_failure_never_regenerates_identity(self):
        factory_calls = []

        class FailingRepository:
            def load(self):
                raise OSError("temporary read failure")

            def create_if_absent(self, identity):
                raise AssertionError("identity must not be rewritten")

        generator = HWIDGenerator(
            identity_repository=FailingRepository(),
            system_uuid_reader=FixedSystemUuidReader(None),
            identity_factory=lambda: factory_calls.append(True) or INSTALLATION_UUID,
        )
        with self.assertRaises(HardwareIdentityError):
            generator.get_hwid()
        self.assertEqual(factory_calls, [])

    def test_missing_pinned_fallback_record_is_not_regenerated(self):
        factory_calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            identity_path = Path(temp_dir) / "hardware_identity_v1.json"
            HWIDGenerator(
                identity_path=identity_path,
                system_uuid_reader=FixedSystemUuidReader(None),
                identity_factory=lambda: INSTALLATION_UUID,
            ).get_hwid()
            identity_path.unlink()
            with self.assertRaises(HardwareIdentityError):
                HWIDGenerator(
                    identity_path=identity_path,
                    system_uuid_reader=FixedSystemUuidReader(None),
                    identity_factory=lambda: factory_calls.append(True)
                    or OTHER_SYSTEM_UUID,
                ).get_hwid()
        self.assertEqual(factory_calls, [])

    def test_corrupt_identity_record_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            identity_path = Path(temp_dir) / "hardware_identity_v1.json"
            identity_path.write_text("{not-json", encoding="utf-8")
            generator = HWIDGenerator(
                identity_path=identity_path,
                system_uuid_reader=FixedSystemUuidReader(SYSTEM_UUID),
            )
            with self.assertRaisesRegex(HardwareIdentityError, "invalid"):
                generator.get_hwid()
            self.assertEqual(identity_path.read_text(encoding="utf-8"), "{not-json")
            self.assertFalse(
                identity_path.with_name(
                    "hardware_identity_v1.json.initialized"
                ).exists()
            )

    def test_existing_identity_without_marker_is_loaded_and_marked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            identity_path = Path(temp_dir) / "hardware_identity_v1.json"
            identity = MachineIdentity.create(
                HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
                SYSTEM_UUID,
            )
            identity_path.write_text(
                json.dumps(identity.to_dict()),
                encoding="utf-8",
            )
            hwid = HWIDGenerator(
                identity_path=identity_path,
                system_uuid_reader=FixedSystemUuidReader(SYSTEM_UUID),
            ).get_hwid()
            marker_path = identity_path.with_name(
                "hardware_identity_v1.json.initialized"
            )
            self.assertEqual(hwid, build_hwid(identity))
            self.assertTrue(marker_path.exists())

    def test_machine_identity_write_permission_failure_is_explicit(self):
        class PermissionDeniedRepository:
            def load(self):
                return None

            def create_if_absent(self, _identity):
                raise PermissionError("machine identity directory is read-only")

        generator = HWIDGenerator(
            identity_repository=PermissionDeniedRepository(),
            system_uuid_reader=FixedSystemUuidReader(SYSTEM_UUID),
        )
        with self.assertRaises(HardwareIdentityError) as raised:
            generator.get_hwid()
        self.assertIsInstance(raised.exception.__cause__, PermissionError)

    def test_concurrent_fallback_startup_persists_one_atomic_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            identity_path = Path(temp_dir) / "hardware_identity_v1.json"

            def generate(_index):
                return HWIDGenerator(
                    identity_path=identity_path,
                    system_uuid_reader=FixedSystemUuidReader(None),
                ).get_hwid()

            with ThreadPoolExecutor(max_workers=16) as executor:
                values = tuple(executor.map(generate, range(64)))
            persisted = json.loads(identity_path.read_text(encoding="utf-8"))
            temp_files = tuple(identity_path.parent.glob(".*.tmp"))
        self.assertEqual(len(set(values)), 1)
        self.assertEqual(persisted["version"], HWID_VERSION)
        self.assertEqual(
            persisted["source"],
            HardwareIdentitySource.INSTALLATION_UUID.value,
        )
        self.assertEqual(temp_files, ())

    def test_concurrent_process_startup_observes_one_fallback_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            identity_path = Path(temp_dir) / "hardware_identity_v1.json"
            with ProcessPoolExecutor(max_workers=8) as executor:
                values = tuple(
                    executor.map(
                        _generate_fallback_in_process,
                        (str(identity_path),) * 24,
                    )
                )
            persisted = json.loads(identity_path.read_text(encoding="utf-8"))
        self.assertEqual(len(set(values)), 1)
        self.assertEqual(persisted["version"], HWID_VERSION)
        self.assertEqual(
            persisted["source"],
            HardwareIdentitySource.INSTALLATION_UUID.value,
        )

    def test_machine_data_path_uses_programdata_known_folder(self):
        with patch(
            "win32com.shell.shell.SHGetKnownFolderPath",
            return_value=r"C:\ProgramData",
        ):
            path = get_machine_app_data_dir()
        self.assertEqual(path, Path(r"C:\ProgramData\OST Visualizer"))

    def test_machine_data_path_failure_has_no_user_scoped_fallback(self):
        with patch(
            "win32com.shell.shell.SHGetKnownFolderPath",
            side_effect=pywintypes.com_error(-1, "unavailable", None, None),
        ):
            with self.assertRaisesRegex(OSError, "machine data directory"):
                get_machine_app_data_dir()

    def test_unsupported_per_user_install_id_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            unsupported_install_id = (
                root / "user" / ".ost_visualizer" / "install_id.txt"
            )
            unsupported_install_id.parent.mkdir(parents=True)
            unsupported_install_id.write_text("IGNORED-A", encoding="utf-8")
            identity_path = root / "machine" / "hardware_identity_v1.json"
            first = HWIDGenerator(
                identity_path=identity_path,
                system_uuid_reader=FixedSystemUuidReader(None),
                identity_factory=lambda: INSTALLATION_UUID,
            ).get_hwid()
            unsupported_install_id.write_text("IGNORED-B", encoding="utf-8")
            second = HWIDGenerator(
                identity_path=identity_path,
                system_uuid_reader=FixedSystemUuidReader(SYSTEM_UUID),
            ).get_hwid()
        self.assertEqual(first, second)


class HwidV1LicenseContractTests(unittest.TestCase):
    def setUp(self):
        self.identity = MachineIdentity.create(
            HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
            SYSTEM_UUID,
        )
        self.hwid = build_hwid(self.identity)

    def test_activation_validation_and_signatures_use_exact_canonical_hwid(self):
        repository = MemoryLicenseRepository()
        verifier = AcceptingSignatureVerifier()
        aggregate = LicenseAggregate(
            repository,
            hwid_provider=lambda: self.hwid,
            signature_verifier=verifier,
        )
        aggregate.ensure_hwid()
        api = RecordingLicenseApi()
        activation = ActivateLicenseUseCase(aggregate, api).execute("LIC-TEST")
        validation = ValidateLicenseUseCase(aggregate, api).execute()
        self.assertTrue(activation.success)
        self.assertTrue(validation.success)
        self.assertEqual(
            api.calls,
            [
                ("activate", "LIC-TEST", self.hwid),
                ("validate", "LIC-TEST", self.hwid),
            ],
        )
        self.assertEqual(aggregate.hwid, self.hwid)
        self.assertEqual(aggregate.hwid_version, HWID_VERSION)
        self.assertTrue(
            all(
                payload["hwid"] == self.hwid
                for payload, _signature in verifier.payloads
            )
        )

    def test_valid_generated_hwid_rejected_by_server_is_not_reported_unavailable(self):
        aggregate = LicenseAggregate(
            MemoryLicenseRepository(),
            hwid_provider=lambda: self.hwid,
            signature_verifier=AcceptingSignatureVerifier(),
        )
        aggregate.ensure_hwid()
        api = RejectingHardwareIdApi()
        result = ActivateLicenseUseCase(aggregate, api).execute("LIC-TEST")
        self.assertFalse(result.success)
        self.assertEqual(result.operation_status, LicenseOperationStatus.FAILED)
        self.assertEqual(result.license_status, LicenseStatus.INVALID)
        self.assertIn("license server rejected", result.message)
        self.assertNotIn("Unable to determine", result.message)
        self.assertEqual(api.calls, [("LIC-TEST", self.hwid)])

    def test_validation_logs_server_hwid_rejection_reason(self):
        cached = License(
            license_key="LIC-TEST",
            hwid=self.hwid,
            hwid_version=HWID_VERSION,
        )
        aggregate = LicenseAggregate(
            MemoryLicenseRepository(cached),
            hwid_provider=lambda: self.hwid,
            signature_verifier=AcceptingSignatureVerifier(),
        )
        api = RejectingHardwareIdApi()
        use_case = ValidateLicenseUseCase(aggregate, api)
        with self.assertLogs(use_case.logger, level="WARNING") as captured:
            result = use_case.execute()
        self.assertFalse(result.success)
        self.assertIn("license server rejected", result.message)
        self.assertTrue(any("HWID too long" in line for line in captured.output))

    def test_local_validation_and_offline_grace_require_canonical_hwid(self):
        now = datetime.now(timezone.utc)
        cached = License(
            license_key="LIC-TEST",
            expiry_date=now + timedelta(days=1),
            signature="signed",
            hwid=self.hwid,
            hwid_version=HWID_VERSION,
            last_validated=now,
            signed_expiry_date="2099-01-01T00:00:00+00:00",
        )
        aggregate = LicenseAggregate(
            MemoryLicenseRepository(cached),
            hwid_provider=lambda: self.hwid,
            signature_verifier=AcceptingSignatureVerifier(),
        )
        self.assertTrue(aggregate.has_valid_license())
        self.assertTrue(aggregate.can_use_offline_grace())
        self.assertEqual(
            aggregate.get_signature_payload()["hwid"],
            self.hwid,
        )

    def test_cache_without_hwid_version_is_cleared_on_load(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "license_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "license_key": "LIC-UNVERSIONED",
                        "expiry_date": "2099-01-01T00:00:00+00:00",
                        "signature": "unversioned-signature",
                        "hwid": "0123456789ABCDEF",
                        "last_validated": "2026-01-01T00:00:00+00:00",
                        "signed_expiry_date": "2099-01-01T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            aggregate = LicenseAggregate(
                JsonLicenseRepository(cache_path),
                hwid_provider=lambda: self.hwid,
                signature_verifier=AcceptingSignatureVerifier(),
            )
            self.assertFalse(aggregate.has_license())
            self.assertFalse(cache_path.exists())

    def test_unsupported_version_cache_is_cleared_before_hwid_comparison(self):
        now = datetime.now(timezone.utc)
        cached = License(
            license_key="LIC-UNSUPPORTED",
            expiry_date=now + timedelta(days=1),
            signature="unsupported-signature",
            hwid="0123456789ABCDEF",
            hwid_version="unsupported",
            last_validated=now,
            signed_expiry_date="2099-01-01T00:00:00+00:00",
        )
        repository = MemoryLicenseRepository(cached)
        provider_calls = []
        aggregate = LicenseAggregate(
            repository,
            hwid_provider=lambda: provider_calls.append(True) or self.hwid,
            signature_verifier=AcceptingSignatureVerifier(),
        )
        self.assertTrue(aggregate.clear_if_invalid())
        self.assertTrue(repository.cleared)
        self.assertEqual(provider_calls, [])

    def test_api_payload_keeps_one_self_versioned_hwid_field(self):
        client = LicenseApiClient()
        with patch.object(client, "_post", return_value=(False, None)) as post:
            client.activate("LIC-TEST", self.hwid)
        post.assert_called_once_with(
            "activate",
            {"license_key": "LIC-TEST", "hwid": self.hwid},
        )


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


def _generate_fallback_in_process(identity_path):
    return HWIDGenerator(
        identity_path=Path(identity_path),
        system_uuid_reader=FixedSystemUuidReader(None),
    ).get_hwid()


if __name__ == "__main__":
    unittest.main()
