import json
import tempfile
import unittest
import uuid
from pathlib import Path
from ost_visualizer.application.dtos.license_activation_identity_dto import (
    LICENSE_ACTIVATION_IDENTITY_VERSION,
    LicenseActivationIdentityDto,
    LicenseActivationIdentityError,
    WindowsJoinType,
)
from ost_visualizer.application.dtos.license_dto import LicenseOperationStatus
from ost_visualizer.application.use_cases.license.activate_license_use_case import (
    ActivateLicenseUseCase,
)
from ost_visualizer.application.use_cases.license.utils.license_use_case import (
    ERROR_CONTRACT,
    ERROR_INVALID_HWID,
)
from ost_visualizer.application.use_cases.license.validate_license_use_case import (
    ValidateLicenseUseCase,
)
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
from ost_visualizer.infrastructure.persistence.repositories.json_license_repository import (
    JsonLicenseRepository,
)

SYSTEM_UUID = uuid.UUID("00112233-4455-6677-8899-AABBCCDDEEFF")
# sha256("OST_VISUALIZER_HWID|v1|smbios_system_uuid|<UUID upper>") per AGENTS.md,
# computed independently of build_hwid so the contract is pinned, not echoed.
EXPECTED_HWID = "v1:B216EAC22D5562B0F8448312C46EE0C55E5F8AB6EF7BB1D8F799C020761525AD"


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


class UnavailableActivationIdentityApi:
    def activate(self, _license_key, _hwid):
        raise LicenseActivationIdentityError("Windows account query failed")


class HwidV1LicenseContractTests(unittest.TestCase):
    def setUp(self):
        self.identity = MachineIdentity.create(
            HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
            SYSTEM_UUID,
        )
        self.hwid = build_hwid(self.identity)

    def test_machine_identity_builds_pinned_v1_hwid(self):
        self.assertEqual(self.hwid, EXPECTED_HWID)
        self.assertTrue(is_canonical_hwid(self.hwid))
        self.assertEqual(len(self.hwid), len("v1:") + 64)
        installation = MachineIdentity.create(
            HardwareIdentitySource.INSTALLATION_UUID, SYSTEM_UUID
        )
        # The pinned source is part of the hashed material.
        self.assertNotEqual(build_hwid(installation), EXPECTED_HWID)
        for malformed in (
            EXPECTED_HWID.lower(),
            EXPECTED_HWID[3:],
            EXPECTED_HWID + "0",
            "v2:" + EXPECTED_HWID[3:],
        ):
            self.assertFalse(is_canonical_hwid(malformed), malformed)

    def test_activation_validation_and_signatures_use_exact_canonical_hwid(self):
        repository = MemoryLicenseRepository()
        verifier = AcceptingSignatureVerifier()
        aggregate = LicenseAggregate(
            repository,
            hwid_provider=lambda: self.hwid,
            signature_verifier=verifier,
        )
        self.assertEqual(aggregate.ensure_hwid(), EXPECTED_HWID)
        api = RecordingLicenseApi()
        activation = ActivateLicenseUseCase(aggregate, api).execute("LIC-TEST")
        validation = ValidateLicenseUseCase(aggregate, api).execute()
        self.assertTrue(activation.success)
        self.assertTrue(validation.success)
        self.assertEqual(
            api.calls,
            [
                ("activate", "LIC-TEST", EXPECTED_HWID),
                ("validate", "LIC-TEST", EXPECTED_HWID),
            ],
        )
        self.assertEqual(aggregate.hwid, EXPECTED_HWID)
        self.assertEqual(aggregate.hwid_version, "v1")
        expected_signature_payload = {
            "license_key": "LIC-TEST",
            "expiry_date": "2099-01-01T00:00:00+00:00",
            "hwid": EXPECTED_HWID,
        }
        # Per operation: the signed server response, then the re-verification of
        # the freshly saved cache; both over the same canonical payload.
        self.assertEqual(
            verifier.payloads,
            [(expected_signature_payload, "signed")] * 4,
        )
        persisted = repository.value
        self.assertEqual(persisted.license_key, "LIC-TEST")
        self.assertEqual(persisted.hwid, EXPECTED_HWID)
        self.assertEqual(persisted.hwid_version, "v1")
        self.assertEqual(persisted.signed_expiry_date, "2099-01-01T00:00:00+00:00")

    def test_valid_generated_hwid_rejected_by_server_is_not_reported_unavailable(self):
        repository = MemoryLicenseRepository()
        aggregate = LicenseAggregate(
            repository,
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
        self.assertEqual(api.calls, [("LIC-TEST", EXPECTED_HWID)])
        self.assertIsNone(repository.value)
        self.assertFalse(aggregate.has_license())

    def test_activation_identity_failure_is_distinct_from_hwid_failure(self):
        repository = MemoryLicenseRepository()
        aggregate = LicenseAggregate(
            repository,
            hwid_provider=lambda: self.hwid,
            signature_verifier=AcceptingSignatureVerifier(),
        )
        aggregate.ensure_hwid()
        use_case = ActivateLicenseUseCase(
            aggregate,
            UnavailableActivationIdentityApi(),
        )
        with self.assertLogs(use_case.logger, level="ERROR") as captured:
            result = use_case.execute("LIC-TEST")
        self.assertFalse(result.success)
        self.assertIn("Windows user and computer", result.message)
        self.assertNotIn("hardware ID", result.message)
        self.assertTrue(
            any("Windows account query failed" in line for line in captured.output)
        )
        self.assertEqual(result.operation_status, LicenseOperationStatus.FAILED)
        self.assertIsNone(repository.value)

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
        self.assertEqual(api.calls, [("LIC-TEST", EXPECTED_HWID)])
        self.assertTrue(any("HWID too long" in line for line in captured.output))

    def test_cache_without_hwid_version_is_cleared_on_load(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "license_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "license_key": "LIC-UNVERSIONED",
                        "expiry_date": "2099-01-01T00:00:00+00:00",
                        "signature": "unversioned-signature",
                        "hwid": self.hwid,
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

    def test_cache_with_current_hwid_version_is_retained_on_load(self):
        # Positive control for the unversioned-cache test: the identical file
        # plus the explicit HWID version is accepted and left on disk.
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "license_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "license_key": "LIC-VERSIONED",
                        "expiry_date": "2099-01-01T00:00:00+00:00",
                        "signature": "versioned-signature",
                        "hwid": self.hwid,
                        "hwid_version": HWID_VERSION,
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
            self.assertTrue(aggregate.has_license())
            self.assertEqual(aggregate.hwid, EXPECTED_HWID)
            self.assertTrue(aggregate.has_valid_license())
            self.assertTrue(cache_path.exists())
