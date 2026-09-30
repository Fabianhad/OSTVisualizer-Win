import logging
import unittest
from ost_visualizer.application.use_cases.license.deactivate_license_use_case import (
    DeactivateLicenseUseCase,
)
from ost_visualizer.domain.entities.license import License, LicenseStatus
from ost_visualizer.domain.services.hardware_identity import (
    HWID_VERSION,
    HardwareIdentityError,
)

TEST_HWID = "v1:" + "A" * 64


class FakeModel:
    def __init__(self):
        self.license_key = "LIC-test-key"
        self.hwid = TEST_HWID
        self.hwid_version = HWID_VERSION
        self.expiry_date = None
        self.offline_grace_hours = 72
        self.clear_calls = 0
        self.valid = False
        self.hwid_error = None

    def has_license(self):
        return bool(self.license_key)

    def can_use_offline_grace(self):
        return False

    def clear_if_invalid(self):
        return False

    def ensure_hwid(self):
        if self.hwid_error is not None:
            raise self.hwid_error
        return self.hwid

    def require_canonical_hwid(self):
        if self.hwid_error is not None:
            raise self.hwid_error
        return self.hwid

    def has_valid_license(self):
        return self.valid

    def clear(self):
        self.clear_calls += 1
        self.license_key = None
        self.valid = False


class FakeApiClient:
    def __init__(self, deactivate_response):
        self.deactivate_response = deactivate_response

    def deactivate(self, license_key, hwid):
        return self.deactivate_response


class LicenseActivationContractTests(unittest.TestCase):
    def test_deactivate_clears_cache_on_already_inactive_success(self):
        model = FakeModel()
        use_case = DeactivateLicenseUseCase(
            model=model,
            api_client=FakeApiClient(
                (
                    True,
                    {
                        "success": True,
                        "message": "Device activation is already inactive.",
                    },
                )
            ),
            logger=logging.getLogger("test"),
        )
        result = use_case.execute()
        self.assertTrue(result.success)
        self.assertEqual(model.clear_calls, 1)
        self.assertEqual(result.license_status, LicenseStatus.NO_LICENSE)
