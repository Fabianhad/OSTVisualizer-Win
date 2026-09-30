import inspect
import json
import os
import subprocess
import tempfile
import unittest
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.domain.services.hardware_identity import (
    HWID_VERSION,
    HardwareIdentityError,
    HardwareIdentitySource,
    MachineIdentity,
    build_hwid,
    is_canonical_hwid,
)
from ost_visualizer.infrastructure.hardware import hwid_generator, smbios_system_uuid
from ost_visualizer.infrastructure.hardware.hwid_generator import HWIDGenerator

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


def _generate_fallback_in_process(identity_path):
    return HWIDGenerator(
        identity_path=Path(identity_path),
        system_uuid_reader=FixedSystemUuidReader(None),
    ).get_hwid()


class HwidV1Tests(unittest.TestCase):
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
