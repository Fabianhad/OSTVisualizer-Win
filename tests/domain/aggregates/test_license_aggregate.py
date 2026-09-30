import unittest
import uuid
from datetime import datetime, timedelta, timezone
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
from types import SimpleNamespace
from ost_visualizer.domain.services.hardware_identity import (
    HWID_VERSION,
    HardwareIdentityError,
)

SYSTEM_UUID = uuid.UUID("00112233-4455-6677-8899-AABBCCDDEEFF")


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


TEST_HWID = "v1:" + "A" * 64


class HwidV1LicenseContractTests(unittest.TestCase):
    def setUp(self):
        self.identity = MachineIdentity.create(
            HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
            SYSTEM_UUID,
        )
        self.hwid = build_hwid(self.identity)

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


class LicenseActivationContractTests(unittest.TestCase):
    def test_offline_grace_rejects_future_validation_timestamp(self):
        now = datetime.now(timezone.utc)
        cached = License(
            license_key="LIC-test-key",
            expiry_date=now + timedelta(days=30),
            signature="signed",
            hwid=TEST_HWID,
            hwid_version=HWID_VERSION,
            last_validated=now + timedelta(days=30),
            signed_expiry_date=(now + timedelta(days=30)).isoformat(),
        )
        repository = SimpleNamespace(
            load=lambda: cached,
            save=lambda _license: None,
            clear=lambda: None,
        )
        verifier = SimpleNamespace(
            verify_license_payload=lambda _payload, _signature: True
        )
        aggregate = LicenseAggregate(
            repository,
            hwid_provider=lambda: TEST_HWID,
            signature_verifier=verifier,
            offline_grace_hours=72,
        )
        self.assertFalse(aggregate.can_use_offline_grace())
