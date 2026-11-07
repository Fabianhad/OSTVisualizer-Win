import unittest
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from unittest.mock import patch
from ost_visualizer.domain.aggregates.license_aggregate import LicenseAggregate
from ost_visualizer.domain.entities.license import License, LicenseValidationResult
from ost_visualizer.domain.services.hardware_identity import (
    HWID_VERSION,
    HardwareIdentityError,
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


class _CapturingLogger:
    def __init__(self):
        self.records = []

    def _add(self, level, message, args):
        self.records.append((level, message % args if args else message))

    def error(self, message, *args, **kwargs):
        self._add("error", message, args)

    def warning(self, message, *args, **kwargs):
        self._add("warning", message, args)

    def exception(self, message, *args, **kwargs):
        self._add("exception", message, args)


class _ScriptedRepository:
    def __init__(self, value=None, load_error=None, save_error=None, clear_error=None):
        self.value = value
        self.load_error = load_error
        self.save_error = save_error
        self.clear_error = clear_error
        self.saves = []
        self.clears = 0

    def load(self):
        if self.load_error is not None:
            raise self.load_error
        if self.value is None:
            raise FileNotFoundError
        return replace(self.value)

    def save(self, value):
        if self.save_error is not None:
            raise self.save_error
        self.saves.append(replace(value))
        self.value = replace(value)

    def clear(self):
        self.clears += 1
        if self.clear_error is not None:
            raise self.clear_error
        self.value = None


def _valid_license(**changes):
    values = dict(
        license_key="LIC-1",
        expiry_date=NOW + timedelta(days=5),
        signature="signed",
        hwid=TEST_HWID,
        hwid_version=HWID_VERSION,
        last_validated=NOW,
        signed_expiry_date=(NOW + timedelta(days=5)).isoformat(),
    )
    values.update(changes)
    return License(**values)


def _verifier_for(license_value):
    return SignatureVerifier(
        {
            "license_key": license_value.license_key,
            "expiry_date": license_value.signed_expiry_date,
            "hwid": license_value.hwid or "",
        }
    )


def _aggregate(
    repository,
    license_value=None,
    machine=TEST_HWID,
    verifier=True,
    logger=None,
    **kwargs
):
    if verifier is True:
        verifier = _verifier_for(license_value or _valid_license())
    return LicenseAggregate(
        repository,
        (lambda: machine) if isinstance(machine, str) else machine,
        verifier or None,
        logger=logger,
        **kwargs,
    )


class LicenseAggregateLoadAndCacheTests(_LicenseClockFixture):
    def test_missing_cache_means_no_license_without_logging(self):
        logger = _CapturingLogger()
        aggregate = _aggregate(_ScriptedRepository(), logger=logger)
        self.assertFalse(aggregate.has_license())
        self.assertEqual(logger.records, [])
        self.assertEqual(aggregate.validate(), LicenseValidationResult.NO_LICENSE)

    def test_a_corrupt_cache_is_logged_and_cleared_and_leaves_no_license(self):
        logger = _CapturingLogger()
        repository = _ScriptedRepository(load_error=ValueError("not json"))
        aggregate = _aggregate(repository, logger=logger)
        self.assertFalse(aggregate.has_license())
        self.assertEqual(repository.clears, 1)
        self.assertEqual(
            logger.records, [("error", "not json; clearing license cache")]
        )

    def test_an_unreadable_cache_is_logged_but_not_cleared(self):
        logger = _CapturingLogger()
        repository = _ScriptedRepository(load_error=OSError("locked"))
        aggregate = _aggregate(repository, logger=logger)
        self.assertFalse(aggregate.has_license())
        self.assertEqual(repository.clears, 0)
        self.assertEqual(
            logger.records, [("error", "Error reading license cache: locked")]
        )

    def test_clearing_a_corrupt_cache_tolerates_a_missing_file_and_reports_other_failures(
        self,
    ):
        logger = _CapturingLogger()
        _aggregate(
            _ScriptedRepository(
                load_error=ValueError("bad"), clear_error=FileNotFoundError()
            ),
            logger=logger,
        )
        self.assertEqual(logger.records, [("error", "bad; clearing license cache")])
        logger = _CapturingLogger()
        _aggregate(
            _ScriptedRepository(
                load_error=ValueError("bad"), clear_error=OSError("busy")
            ),
            logger=logger,
        )
        self.assertEqual(
            logger.records,
            [
                ("error", "bad; clearing license cache"),
                ("warning", "Unable to clear license cache: busy"),
            ],
        )

    def test_a_loaded_license_replaces_the_previous_one_and_reload_follows_the_repository(
        self,
    ):
        first = _valid_license(license_key="A")
        repository = _ScriptedRepository(first)
        aggregate = _aggregate(repository)
        self.assertEqual(aggregate.license_key, "A")
        repository.value = _valid_license(license_key="B")
        aggregate.load()
        self.assertEqual(aggregate.license_key, "B")
        repository.value = None
        aggregate.load()
        self.assertIsNone(aggregate.license_key)

    def test_save_writes_the_current_license_and_logs_then_reraises_failures(self):
        repository = _ScriptedRepository(_valid_license())
        aggregate = _aggregate(repository)
        aggregate.save()
        self.assertEqual(repository.saves, [_valid_license()])
        logger = _CapturingLogger()
        failing = _ScriptedRepository(_valid_license(), save_error=OSError("full"))
        aggregate = _aggregate(failing, logger=logger)
        with self.assertRaises(OSError):
            aggregate.save()
        self.assertEqual(logger.records, [("exception", "Error saving license: full")])

    def test_clear_forgets_the_license_and_clears_the_cache(self):
        repository = _ScriptedRepository(_valid_license())
        aggregate = _aggregate(repository)
        aggregate.clear()
        self.assertFalse(aggregate.has_license())
        self.assertEqual(repository.clears, 1)
        self.assertIsNone(repository.value)

    def test_properties_expose_the_cached_fields_and_default_grace_hours_are_used(self):
        cached = _valid_license()
        aggregate = _aggregate(_ScriptedRepository(cached))
        self.assertEqual(
            (
                aggregate.license_key,
                aggregate.expiry_date,
                aggregate.signature,
                aggregate.hwid,
                aggregate.hwid_version,
                aggregate.last_validated,
            ),
            (
                cached.license_key,
                cached.expiry_date,
                "signed",
                TEST_HWID,
                HWID_VERSION,
                NOW,
            ),
        )
        self.assertEqual(aggregate.offline_grace_hours, 72)
        self.assertIs(aggregate.is_expired(), False)
        self.assertIs(aggregate.is_expired(NOW + timedelta(days=6)), True)


class LicenseAggregateValidationOrderTests(_LicenseClockFixture):
    def validate(self, cached, machine=TEST_HWID, verifier=True):
        aggregate = _aggregate(_ScriptedRepository(cached), cached, machine, verifier)
        return aggregate.validate(), aggregate

    def test_each_failure_is_reported_in_priority_order(self):
        cached = _valid_license()
        self.assertEqual(self.validate(None)[0], LicenseValidationResult.NO_LICENSE)
        self.assertEqual(
            self.validate(_valid_license(license_key=""))[0],
            LicenseValidationResult.NO_LICENSE,
        )
        self.assertEqual(
            self.validate(_valid_license(hwid_version="v0"))[0],
            LicenseValidationResult.HWID_VERSION_MISMATCH,
        )
        self.assertEqual(
            self.validate(_valid_license(hwid="short"))[0],
            LicenseValidationResult.HWID_VERSION_MISMATCH,
        )
        self.assertEqual(
            self.validate(_valid_license(hwid=""))[0],
            LicenseValidationResult.HWID_VERSION_MISMATCH,
        )
        self.assertEqual(
            self.validate(_valid_license(expiry_date=NOW - timedelta(seconds=1)))[0],
            LicenseValidationResult.EXPIRED,
        )
        # Expired outranks a bad signature; a bad signature outranks a foreign machine.
        both = _valid_license(expiry_date=NOW - timedelta(days=1), signature="bad")
        self.assertEqual(self.validate(both)[0], LicenseValidationResult.EXPIRED)
        self.assertEqual(
            self.validate(_valid_license(signature="bad"), machine="v1:" + "B" * 64)[0],
            LicenseValidationResult.SIGNATURE_INVALID,
        )
        self.assertEqual(
            self.validate(cached, machine="v1:" + "B" * 64)[0],
            LicenseValidationResult.HWID_MISMATCH,
        )
        self.assertEqual(self.validate(cached)[0], LicenseValidationResult.VALID)

    def test_validation_stops_before_verifying_or_asking_the_machine_when_earlier_checks_fail(
        self,
    ):
        calls = []
        verifier = SignatureVerifier({})
        aggregate = _aggregate(
            _ScriptedRepository(_valid_license(expiry_date=NOW - timedelta(days=1))),
            machine=lambda: calls.append(True) or TEST_HWID,
            verifier=verifier,
        )
        self.assertEqual(aggregate.validate(), LicenseValidationResult.EXPIRED)
        self.assertEqual((verifier.payloads, calls), ([], []))

    def test_without_a_signature_verifier_a_cached_license_is_never_valid(self):
        logger = _CapturingLogger()
        aggregate = _aggregate(
            _ScriptedRepository(_valid_license()), verifier=None, logger=logger
        )
        self.assertEqual(
            aggregate.validate(), LicenseValidationResult.SIGNATURE_INVALID
        )
        self.assertFalse(aggregate.has_valid_license())
        self.assertFalse(aggregate.can_use_offline_grace())
        self.assertEqual(
            {message for _, message in logger.records},
            {"No license signature verifier configured"},
        )
        self.assertEqual({level for level, _ in logger.records}, {"warning"})

    def test_the_machine_hwid_must_be_the_same_canonical_value(self):
        # (name kept for ledger stability) Despite the name this pins that a CACHED
        # hwid that is not canonical (lower-case digits or a wrong length) is a
        # HWID_VERSION_MISMATCH even when the machine reports the very same text.
        for stored, machine in (
            ("v1:" + "a" * 64, "v1:" + "a" * 64),
            ("v1:" + "A" * 63, "v1:" + "A" * 63),
        ):
            cached = _valid_license(hwid=stored)
            aggregate = _aggregate(_ScriptedRepository(cached), cached, machine)
            with self.subTest(stored=stored):
                self.assertEqual(
                    aggregate.validate(), LicenseValidationResult.HWID_VERSION_MISMATCH
                )
        self.assertEqual(
            _aggregate(_ScriptedRepository(_valid_license())).has_valid_license(), True
        )

    def test_the_signature_payload_uses_empty_strings_for_missing_fields(self):
        aggregate = _aggregate(_ScriptedRepository(None))
        self.assertEqual(
            aggregate.get_signature_payload(),
            {"license_key": "", "expiry_date": "", "hwid": ""},
        )
        cached = _valid_license()
        payload = _aggregate(
            _ScriptedRepository(cached), cached
        ).get_signature_payload()
        self.assertEqual(
            payload,
            {
                "license_key": "LIC-1",
                "expiry_date": cached.signed_expiry_date,
                "hwid": TEST_HWID,
            },
        )


class LicenseAggregateOfflineGraceTests(_LicenseClockFixture):
    def grace(self, **changes):
        cached = _valid_license(**changes)
        aggregate = _aggregate(_ScriptedRepository(cached), cached)
        return aggregate.can_use_offline_grace()

    def test_every_precondition_of_the_grace_period_is_checked(self):
        self.assertIs(self.grace(), True)
        self.assertIs(
            _aggregate(_ScriptedRepository(None)).can_use_offline_grace(), False
        )
        self.assertIs(self.grace(hwid_version="v0"), False)
        self.assertIs(self.grace(hwid="short"), False)
        self.assertIs(self.grace(expiry_date=NOW - timedelta(seconds=1)), False)
        self.assertIs(self.grace(last_validated=None), False)
        cached = _valid_license()
        mismatch = _aggregate(
            _ScriptedRepository(cached), cached, machine="v1:" + "B" * 64
        )
        self.assertIs(mismatch.can_use_offline_grace(), False)
        invalid_signature = _aggregate(
            _ScriptedRepository(_valid_license(signature="bad")), cached
        )
        self.assertIs(invalid_signature.can_use_offline_grace(), False)

    def test_naive_and_foreign_timezone_timestamps_are_compared_as_utc(self):
        naive = (NOW - timedelta(hours=10)).replace(tzinfo=None)
        self.assertIs(self.grace(last_validated=naive), True)
        east = timezone(timedelta(hours=9))
        local = (NOW - timedelta(hours=70)).astimezone(east)
        self.assertIs(self.grace(last_validated=local), True)
        too_old = (NOW - timedelta(hours=73)).astimezone(east)
        self.assertIs(self.grace(last_validated=too_old), False)
        wrong_if_naive_local = (
            (NOW + timedelta(hours=1)).astimezone(east).replace(tzinfo=None)
        )
        self.assertIs(self.grace(last_validated=wrong_if_naive_local), False)

    def test_the_grace_window_follows_the_configured_hours(self):
        cached = _valid_license(last_validated=NOW - timedelta(hours=5))
        for hours, expected in ((4, False), (5, True), (6, True), (0, False)):
            aggregate = _aggregate(
                _ScriptedRepository(cached), cached, offline_grace_hours=hours
            )
            with self.subTest(hours=hours):
                self.assertIs(aggregate.can_use_offline_grace(), expected)

    def test_normalizing_datetimes(self):
        normalize = LicenseAggregate._normalize_datetime
        self.assertIsNone(normalize(None))
        self.assertEqual(
            normalize(datetime(2026, 1, 1)), datetime(2026, 1, 1, tzinfo=timezone.utc)
        )
        east = timezone(timedelta(hours=2))
        self.assertEqual(
            normalize(datetime(2026, 1, 1, 12, tzinfo=east)),
            datetime(2026, 1, 1, 10, tzinfo=timezone.utc),
        )


class LicenseAggregateUpdateTests(_LicenseClockFixture):
    def new_values(self, **changes):
        values = dict(
            license_key="LIC-NEW",
            expiry_date=NOW + timedelta(days=30),
            signature="signed",
            hwid=TEST_HWID,
            hwid_version=HWID_VERSION,
            signed_expiry_date=(NOW + timedelta(days=30)).isoformat(),
        )
        values.update(changes)
        return values

    def verifier(self, values):
        return SignatureVerifier(
            {
                "license_key": values["license_key"],
                "expiry_date": values["signed_expiry_date"],
                "hwid": values["hwid"],
            }
        )

    def test_a_valid_update_is_saved_reloaded_and_stamped_with_the_current_time(self):
        values = self.new_values()
        repository = _ScriptedRepository()
        aggregate = _aggregate(
            repository, machine=TEST_HWID, verifier=self.verifier(values)
        )
        aggregate.update(**values)
        self.assertEqual(aggregate.license_key, "LIC-NEW")
        self.assertEqual(aggregate.last_validated, NOW)
        self.assertEqual(
            repository.saves,
            [
                License(
                    license_key="LIC-NEW",
                    expiry_date=values["expiry_date"],
                    signature="signed",
                    hwid=TEST_HWID,
                    hwid_version=HWID_VERSION,
                    last_validated=NOW,
                    signed_expiry_date=values["signed_expiry_date"],
                )
            ],
        )
        self.assertTrue(aggregate.has_valid_license())

    def test_non_canonical_hwid_or_version_is_rejected_before_anything_changes(self):
        # Versions on both sides of "v1" ("v0" < "v1" < "v2" < "x") pin that the
        # check is an exact match, not an ordering comparison.
        for changes in (
            dict(hwid="short"),
            dict(hwid_version="v0"),
            dict(hwid_version="v2"),
            dict(hwid_version="x"),
            dict(hwid=TEST_HWID.lower()),
            dict(hwid_version=""),
        ):
            values = self.new_values(**changes)
            previous = _valid_license(license_key="OLD")
            repository = _ScriptedRepository(previous)
            aggregate = _aggregate(repository, previous)
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError) as raised:
                    aggregate.update(**values)
                self.assertEqual(
                    str(raised.exception),
                    "License update does not contain a canonical HWID",
                )
                self.assertEqual(aggregate.license_key, "OLD")
                self.assertEqual(repository.saves, [])

    def test_a_cache_that_fails_validation_after_saving_is_rolled_back_and_the_previous_cache_restored(
        self,
    ):
        values = self.new_values()
        previous = _valid_license(license_key="OLD")
        repository = _ScriptedRepository(previous)
        wrong_verifier = SignatureVerifier({})
        aggregate = _aggregate(repository, machine=TEST_HWID, verifier=wrong_verifier)
        with self.assertRaises(ValueError) as raised:
            aggregate.update(**values)
        self.assertEqual(
            str(raised.exception),
            "Saved license cache failed validation: signature_invalid",
        )
        self.assertEqual(aggregate.license_key, "OLD")
        self.assertEqual(repository.value, previous)
        self.assertEqual(
            [saved.license_key for saved in repository.saves], ["LIC-NEW", "OLD"]
        )

    def test_a_failed_first_activation_clears_the_cache_it_wrote(self):
        values = self.new_values()
        repository = _ScriptedRepository()
        aggregate = _aggregate(
            repository, machine=TEST_HWID, verifier=SignatureVerifier({})
        )
        with self.assertRaises(ValueError):
            aggregate.update(**values)
        self.assertFalse(aggregate.has_license())
        self.assertEqual(repository.clears, 1)
        self.assertIsNone(repository.value)

    def test_a_save_failure_reraises_restores_the_previous_license_and_logs_a_failed_restore(
        self,
    ):
        values = self.new_values()
        previous = _valid_license(license_key="OLD")
        logger = _CapturingLogger()
        repository = _ScriptedRepository(previous, save_error=OSError("disk full"))
        aggregate = _aggregate(
            repository, machine=TEST_HWID, verifier=self.verifier(values), logger=logger
        )
        with self.assertRaises(OSError):
            aggregate.update(**values)
        self.assertEqual(aggregate.license_key, "OLD")
        self.assertEqual(
            logger.records,
            [
                ("exception", "Error saving license: disk full"),
                (
                    "warning",
                    "Unable to restore previous license cache after failed update: disk full",
                ),
            ],
        )

    def test_a_failed_restore_of_an_empty_previous_state_is_also_reported(self):
        values = self.new_values()
        logger = _CapturingLogger()
        repository = _ScriptedRepository(
            save_error=OSError("disk full"), clear_error=OSError("busy")
        )
        aggregate = _aggregate(
            repository, machine=TEST_HWID, verifier=self.verifier(values), logger=logger
        )
        with self.assertRaises(OSError):
            aggregate.update(**values)
        self.assertFalse(aggregate.has_license())
        self.assertIn(
            (
                "warning",
                "Unable to restore previous license cache after failed update: busy",
            ),
            logger.records,
        )


class LicenseAggregateHwidAndSignatureHelperTests(_LicenseClockFixture):
    def test_ensure_hwid_returns_the_machine_hwid_and_pins_it_when_nothing_is_cached(
        self,
    ):
        aggregate = _aggregate(_ScriptedRepository(None))
        self.assertEqual(aggregate.ensure_hwid(), TEST_HWID)
        self.assertEqual(
            (aggregate.hwid, aggregate.hwid_version), (TEST_HWID, HWID_VERSION)
        )

    def test_a_different_machine_hwid_is_a_mismatch_whether_it_sorts_before_or_after_the_cached_one(
        self,
    ):
        low = "v1:" + "A" * 64
        high = "v1:" + "C" * 64
        for cached_hwid, machine in ((low, high), (high, low)):
            cached = _valid_license(hwid=cached_hwid)
            aggregate = _aggregate(_ScriptedRepository(cached), cached, machine=machine)
            with self.subTest(cached=cached_hwid[3:5], machine=machine[3:5]):
                self.assertEqual(
                    aggregate.validate(), LicenseValidationResult.HWID_MISMATCH
                )
                self.assertIs(aggregate.can_use_offline_grace(), False)
                with self.assertRaises(HardwareIdentityError):
                    aggregate.ensure_hwid()
                self.assertEqual(aggregate.hwid, cached_hwid)

    def test_ensure_hwid_accepts_a_matching_cached_hwid_and_rejects_a_different_machine(
        self,
    ):
        cached = _valid_license()
        self.assertEqual(
            _aggregate(_ScriptedRepository(cached), cached).ensure_hwid(), TEST_HWID
        )
        other = "v1:" + "C" * 64
        aggregate = _aggregate(_ScriptedRepository(cached), cached, machine=other)
        with self.assertRaises(HardwareIdentityError) as raised:
            aggregate.ensure_hwid()
        self.assertEqual(
            str(raised.exception), "The machine HWID does not match the cached license"
        )
        self.assertEqual(aggregate.hwid, TEST_HWID)

    def test_a_non_canonical_cached_hwid_is_replaced_by_the_machine_hwid(self):
        cached = _valid_license(hwid="legacy", hwid_version="legacy")
        aggregate = _aggregate(_ScriptedRepository(cached), cached)
        self.assertEqual(aggregate.ensure_hwid(), TEST_HWID)
        self.assertEqual(
            (aggregate.hwid, aggregate.hwid_version), (TEST_HWID, HWID_VERSION)
        )

    def test_an_invalid_provider_value_is_refused_with_a_clear_message(self):
        for bad in ("", "v1:abc", "V1:" + "A" * 64):
            aggregate = _aggregate(
                _ScriptedRepository(None), machine=lambda bad=bad: bad
            )
            for method in (aggregate.require_canonical_hwid, aggregate.ensure_hwid):
                with self.subTest(bad=bad, method=method.__name__):
                    with self.assertRaises(HardwareIdentityError) as raised:
                        method()
                    self.assertEqual(
                        str(raised.exception),
                        "The hardware identity provider returned an invalid HWID",
                    )

    def test_a_provider_returning_none_is_refused_with_the_clear_message(self):
        # is_canonical_hwid is a total boolean predicate (R4 resolution): None and
        # other non-strings are non-canonical instead of leaking re's TypeError.
        aggregate = _aggregate(_ScriptedRepository(None), machine=lambda: None)
        for method in (aggregate.require_canonical_hwid, aggregate.ensure_hwid):
            with self.subTest(method=method.__name__):
                with self.assertRaises(HardwareIdentityError) as raised:
                    method()
                self.assertEqual(
                    str(raised.exception),
                    "The hardware identity provider returned an invalid HWID",
                )

    def test_a_cached_license_with_a_non_string_hwid_is_not_valid_instead_of_raising(
        self,
    ):
        # License.from_dict does not type-check "hwid", so a corrupt cache can hold a
        # truthy non-string (e.g. an int); validation must classify it, not crash.
        for bad in (12345, ["x"], {"a": 1}):
            with self.subTest(bad=bad):
                cached = _valid_license(hwid=bad)
                aggregate = _aggregate(_ScriptedRepository(cached), cached)
                self.assertEqual(
                    aggregate.validate(),
                    LicenseValidationResult.HWID_VERSION_MISMATCH,
                )
                self.assertFalse(aggregate.can_use_offline_grace())
                self.assertFalse(aggregate.has_valid_license())

    def test_response_signatures_need_a_canonical_hwid_and_a_verifier(self):
        cached = _valid_license()
        verifier = SignatureVerifier(
            {"license_key": "LIC-1", "expiry_date": "2099-01-01", "hwid": TEST_HWID}
        )
        aggregate = _aggregate(_ScriptedRepository(None), verifier=verifier)
        self.assertTrue(
            aggregate.verify_response_signature(
                "LIC-1", "2099-01-01", TEST_HWID, "signed"
            )
        )
        self.assertFalse(
            aggregate.verify_response_signature(
                "LIC-1", "2099-01-01", TEST_HWID, "forged"
            )
        )
        self.assertFalse(
            aggregate.verify_response_signature(
                "LIC-2", "2099-01-01", TEST_HWID, "signed"
            )
        )
        calls = len(verifier.payloads)
        self.assertFalse(
            aggregate.verify_response_signature(
                "LIC-1", "2099-01-01", "short", "signed"
            )
        )
        self.assertEqual(len(verifier.payloads), calls)
        logger = _CapturingLogger()
        bare = _aggregate(_ScriptedRepository(None), verifier=None, logger=logger)
        self.assertFalse(
            bare.verify_response_signature("LIC-1", "2099-01-01", TEST_HWID, "signed")
        )
        self.assertEqual(
            logger.records, [("warning", "No license signature verifier configured")]
        )

    def test_clear_if_invalid_clears_only_for_hwid_failures(self):
        cached = _valid_license()
        for machine, cached_license, cleared in (
            ("v1:" + "B" * 64, cached, True),
            (TEST_HWID, _valid_license(hwid_version="v0"), True),
            (TEST_HWID, cached, False),
            (TEST_HWID, _valid_license(expiry_date=NOW - timedelta(days=1)), False),
            (TEST_HWID, _valid_license(signature="bad"), False),
        ):
            logger = _CapturingLogger()
            repository = _ScriptedRepository(cached_license)
            aggregate = _aggregate(repository, cached, machine, logger=logger)
            with self.subTest(machine=machine, license=cached_license.hwid_version):
                self.assertIs(aggregate.clear_if_invalid(), cleared)
                self.assertEqual(aggregate.has_license(), not cleared)
                self.assertEqual(repository.clears, 1 if cleared else 0)
                self.assertEqual(
                    [
                        r
                        for r in logger.records
                        if r[0] == "warning" and "Canonical HWID" in r[1]
                    ],
                    (
                        [
                            (
                                "warning",
                                "Canonical HWID validation failed. Clearing invalid cached license.",
                            )
                        ]
                        if cleared
                        else []
                    ),
                )
        none = _aggregate(_ScriptedRepository(None))
        self.assertIs(none.clear_if_invalid(), False)


class LicenseAggregateReloadAndPersistenceTests(_LicenseClockFixture):
    def test_reloading_after_the_cache_becomes_corrupt_or_unreadable_drops_the_old_license(
        self,
    ):
        for error in (ValueError("corrupt"), OSError("locked"), FileNotFoundError()):
            with self.subTest(error=type(error).__name__):
                repository = _ScriptedRepository(_valid_license())
                aggregate = _aggregate(repository)
                self.assertTrue(aggregate.has_license())
                repository.load_error = error
                aggregate.load()
                self.assertFalse(aggregate.has_license())

    def test_update_adopts_what_the_repository_actually_persisted(self):
        class RoundingRepository(_ScriptedRepository):
            def load(self):
                loaded = super().load()
                return replace(
                    loaded,
                    last_validated=loaded.last_validated.replace(
                        microsecond=0, second=0
                    ),
                )

        values = dict(
            license_key="LIC-NEW",
            expiry_date=NOW + timedelta(days=30),
            signature="signed",
            hwid=TEST_HWID,
            hwid_version=HWID_VERSION,
            signed_expiry_date=(NOW + timedelta(days=30)).isoformat(),
        )
        verifier = SignatureVerifier(
            {
                "license_key": "LIC-NEW",
                "expiry_date": values["signed_expiry_date"],
                "hwid": TEST_HWID,
            }
        )
        later = NOW.replace(second=30)

        class LaterDatetime(FixedDatetime):
            @classmethod
            def now(cls, tz=None):
                return (
                    later.astimezone(tz)
                    if tz is not None
                    else later.replace(tzinfo=None)
                )

        with patch(
            "ost_visualizer.domain.aggregates.license_aggregate.datetime", LaterDatetime
        ):
            aggregate = _aggregate(
                RoundingRepository(), machine=TEST_HWID, verifier=verifier
            )
            aggregate.update(**values)
        self.assertEqual(aggregate.last_validated, later.replace(second=0))

    def test_a_cached_hwid_that_is_missing_is_a_version_mismatch_not_an_error(self):
        for hwid in (None, ""):
            cached = _valid_license(hwid=hwid)
            aggregate = _aggregate(_ScriptedRepository(cached), cached)
            with self.subTest(hwid=hwid):
                self.assertEqual(
                    aggregate.validate(), LicenseValidationResult.HWID_VERSION_MISMATCH
                )
                self.assertIs(aggregate.can_use_offline_grace(), False)

    def test_negative_results_are_real_booleans(self):
        bare = _aggregate(_ScriptedRepository(_valid_license()), verifier=None)
        self.assertIs(bare.has_valid_cached_signature(), False)
        self.assertIs(
            bare.verify_response_signature("LIC-1", "x", TEST_HWID, "signed"), False
        )
        aggregate = _aggregate(_ScriptedRepository(_valid_license()))
        self.assertIs(
            aggregate.verify_response_signature("LIC-1", "x", "short", "signed"), False
        )
        self.assertIs(aggregate.has_valid_license(), True)
        self.assertIs(_aggregate(_ScriptedRepository(None)).has_valid_license(), False)
        self.assertIs(_aggregate(_ScriptedRepository(None)).has_license(), False)
        self.assertIs(aggregate.has_license(), True)
