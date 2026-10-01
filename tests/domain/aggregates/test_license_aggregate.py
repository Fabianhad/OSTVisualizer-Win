import unittest
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from unittest.mock import patch
from ost_visualizer.domain.aggregates.license_aggregate import LicenseAggregate
from ost_visualizer.domain.entities.license import License, LicenseValidationResult
from ost_visualizer.domain.services.hardware_identity import (
    HWID_VERSION,
    HardwareIdentitySource,
    MachineIdentity,
    build_hwid,
)

SYSTEM_UUID = uuid.UUID("00112233-4455-6677-8899-AABBCCDDEEFF")
NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)


class _LicenseClockFixture(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch(
                "ost_visualizer.domain.aggregates.license_aggregate.datetime",
                FixedDatetime,
            )
        )
        self.enterContext(
            patch("ost_visualizer.domain.entities.license.datetime", FixedDatetime)
        )


class MemoryLicenseRepository:
    def __init__(self, value=None):
        self.value = value
        self.cleared = False

    def load(self):
        if self.value is None:
            raise FileNotFoundError
        return replace(self.value)

    def save(self, value):
        self.value = replace(value)

    def clear(self):
        self.cleared = True
        self.value = None


class SignatureVerifier:
    def __init__(self, expected_payload):
        self.expected_payload = expected_payload
        self.payloads = []

    def verify_license_payload(self, payload, signature):
        self.payloads.append((dict(payload), signature))
        return payload == self.expected_payload and signature == "signed"


TEST_HWID = "v1:" + "A" * 64


class HwidV1LicenseContractTests(_LicenseClockFixture):
    def setUp(self):
        super().setUp()
        self.identity = MachineIdentity.create(
            HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
            SYSTEM_UUID,
        )
        self.hwid = build_hwid(self.identity)

    def test_local_validation_and_offline_grace_require_canonical_hwid(self):
        now = NOW
        cached = License(
            license_key="LIC-TEST",
            expiry_date=now + timedelta(days=1),
            signature="signed",
            hwid=self.hwid,
            hwid_version=HWID_VERSION,
            last_validated=now,
            signed_expiry_date=(now + timedelta(days=1)).isoformat(),
        )
        expected_payload = {
            "license_key": "LIC-TEST",
            "expiry_date": cached.signed_expiry_date,
            "hwid": self.hwid,
        }
        verifier = SignatureVerifier(expected_payload)
        aggregate = LicenseAggregate(
            MemoryLicenseRepository(cached),
            hwid_provider=lambda: self.hwid,
            signature_verifier=verifier,
        )
        self.assertTrue(aggregate.has_valid_license())
        self.assertTrue(aggregate.can_use_offline_grace())
        self.assertEqual(aggregate.get_signature_payload(), expected_payload)
        self.assertEqual(verifier.payloads, [(expected_payload, "signed")] * 2)

    def test_unsupported_version_cache_is_cleared_before_hwid_comparison(self):
        now = NOW
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
        verifier = SignatureVerifier({})
        aggregate = LicenseAggregate(
            repository,
            hwid_provider=lambda: provider_calls.append(True) or self.hwid,
            signature_verifier=verifier,
        )
        self.assertTrue(aggregate.clear_if_invalid())
        self.assertTrue(repository.cleared)
        self.assertEqual(provider_calls, [])
        self.assertEqual(verifier.payloads, [])
        self.assertIsNone(repository.value)
        self.assertFalse(aggregate.has_license())


class LicenseActivationContractTests(_LicenseClockFixture):
    def test_offline_grace_rejects_future_validation_timestamp(self):
        now = NOW
        cached = License(
            license_key="LIC-test-key",
            expiry_date=now + timedelta(days=30),
            signature="signed",
            hwid=TEST_HWID,
            hwid_version=HWID_VERSION,
            last_validated=now + timedelta(days=30),
            signed_expiry_date=(now + timedelta(days=30)).isoformat(),
        )
        repository = MemoryLicenseRepository(cached)
        verifier = SignatureVerifier(
            {
                "license_key": cached.license_key,
                "expiry_date": cached.signed_expiry_date,
                "hwid": TEST_HWID,
            }
        )
        aggregate = LicenseAggregate(
            repository,
            hwid_provider=lambda: TEST_HWID,
            signature_verifier=verifier,
            offline_grace_hours=72,
        )
        self.assertFalse(aggregate.can_use_offline_grace())
        self.assertEqual(aggregate.validate(), LicenseValidationResult.VALID)
        repository.save(replace(cached, last_validated=now))
        aggregate.load()
        self.assertTrue(aggregate.can_use_offline_grace())

    def test_offline_grace_boundary_is_inclusive_and_future_time_is_rejected(self):
        cached = License(
            "LIC-boundary",
            NOW + timedelta(days=1),
            "signed",
            TEST_HWID,
            HWID_VERSION,
            NOW,
            (NOW + timedelta(days=1)).isoformat(),
        )
        verifier = SignatureVerifier(
            {
                "license_key": cached.license_key,
                "expiry_date": cached.signed_expiry_date,
                "hwid": TEST_HWID,
            }
        )
        repository = MemoryLicenseRepository(cached)
        aggregate = LicenseAggregate(
            repository, lambda: TEST_HWID, verifier, offline_grace_hours=72
        )
        for age, expected in (
            (timedelta(0), True),
            (timedelta(hours=72), True),
            (timedelta(hours=72, microseconds=1), False),
            (timedelta(microseconds=-1), False),
        ):
            with self.subTest(age=age):
                repository.save(replace(cached, last_validated=NOW - age))
                aggregate.load()
                self.assertEqual(aggregate.can_use_offline_grace(), expected)
        self.assertEqual(len(verifier.payloads), 4)

    def test_bad_signature_and_foreign_machine_cannot_use_valid_cached_license(self):
        cached = License(
            "LIC-valid",
            NOW + timedelta(days=1),
            "signed",
            TEST_HWID,
            HWID_VERSION,
            NOW,
            (NOW + timedelta(days=1)).isoformat(),
        )
        verifier = SignatureVerifier(
            {
                "license_key": cached.license_key,
                "expiry_date": cached.signed_expiry_date,
                "hwid": TEST_HWID,
            }
        )
        for candidate, machine, expected in (
            (
                replace(cached, signature="invalid"),
                TEST_HWID,
                LicenseValidationResult.SIGNATURE_INVALID,
            ),
            (cached, "v1:" + "B" * 64, LicenseValidationResult.HWID_MISMATCH),
        ):
            with self.subTest(expected=expected):
                aggregate = LicenseAggregate(
                    MemoryLicenseRepository(candidate), lambda: machine, verifier
                )
                self.assertEqual(aggregate.validate(), expected)
                self.assertFalse(aggregate.has_valid_license())
                self.assertFalse(aggregate.can_use_offline_grace())
