import logging
import unittest
from ost_visualizer.application.use_cases.license.deactivate_license_use_case import (
    DeactivateLicenseUseCase,
)
from ost_visualizer.application.dtos.license_dto import LicenseOperationStatus
from ost_visualizer.application.use_cases.license.utils.license_use_case import (
    ERROR_CONTRACT,
    ERROR_LICENSE_EXPIRED,
)
from ost_visualizer.domain.entities.license import License, LicenseStatus
from ost_visualizer.domain.services.hardware_identity import (
    HWID_VERSION,
    HardwareIdentityError,
)

TEST_HWID = "v1:" + "A" * 64
QUIET_LOGGER = logging.getLogger("test.deactivate_license")
QUIET_LOGGER.addHandler(logging.NullHandler())
QUIET_LOGGER.propagate = False


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
        self.deactivate_calls = []

    def deactivate(self, license_key, hwid):
        self.deactivate_calls.append((license_key, hwid))
        return self.deactivate_response


class LicenseActivationContractTests(unittest.TestCase):
    def _use_case(self, model, deactivate_response):
        api_client = FakeApiClient(deactivate_response)
        use_case = DeactivateLicenseUseCase(
            model=model,
            api_client=api_client,
            logger=QUIET_LOGGER,
        )
        return use_case, api_client

    def test_deactivate_clears_cache_on_already_inactive_success(self):
        model = FakeModel()
        use_case, api_client = self._use_case(
            model,
            (
                True,
                {
                    "success": True,
                    "message": "Device activation is already inactive.",
                },
            ),
        )
        result = use_case.execute()
        self.assertTrue(result.success)
        self.assertEqual(result.operation_status, LicenseOperationStatus.SUCCESS)
        self.assertEqual(result.message, "Device activation is already inactive.")
        self.assertEqual(model.clear_calls, 1)
        self.assertIsNone(model.license_key)
        self.assertEqual(result.license_status, LicenseStatus.NO_LICENSE)
        self.assertEqual(api_client.deactivate_calls, [("LIC-test-key", TEST_HWID)])

    def test_deactivate_failure_responses_keep_cached_license(self):
        responses = {
            "server_failure": (
                False,
                {
                    "success": False,
                    "error": "License expired",
                    "error_name": ERROR_LICENSE_EXPIRED,
                    "error_code": ERROR_CONTRACT[ERROR_LICENSE_EXPIRED],
                },
            ),
            "network_error": (False, None),
            "unmarked_success": (True, {"message": "done"}),
        }
        for label, response in responses.items():
            with self.subTest(label=label):
                model = FakeModel()
                use_case, _api_client = self._use_case(model, response)
                result = use_case.execute()
                self.assertFalse(result.success)
                self.assertEqual(model.clear_calls, 0)
                self.assertEqual(model.license_key, "LIC-test-key")
        model = FakeModel()
        use_case, _api_client = self._use_case(model, responses["server_failure"])
        result = use_case.execute()
        self.assertEqual(result.operation_status, LicenseOperationStatus.EXPIRED)
        self.assertEqual(result.error_code, ERROR_CONTRACT[ERROR_LICENSE_EXPIRED])
        self.assertIn("cannot be deactivated", result.message)
        model = FakeModel()
        use_case, _api_client = self._use_case(model, responses["network_error"])
        result = use_case.execute()
        self.assertEqual(result.operation_status, LicenseOperationStatus.NETWORK_ERROR)

    def test_deactivate_without_license_or_with_unusable_cache_skips_server(self):
        model = FakeModel()
        model.license_key = None
        use_case, api_client = self._use_case(model, (True, {"success": True}))
        result = use_case.execute()
        self.assertTrue(result.success)
        self.assertEqual(result.operation_status, LicenseOperationStatus.NO_LICENSE)
        self.assertEqual(api_client.deactivate_calls, [])
        self.assertEqual(model.clear_calls, 0)
        model = FakeModel()
        model.hwid = "not-a-canonical-hwid"
        use_case, api_client = self._use_case(model, (True, {"success": True}))
        result = use_case.execute()
        self.assertFalse(result.success)
        self.assertEqual(result.operation_status, LicenseOperationStatus.FAILED)
        self.assertEqual(result.license_status, LicenseStatus.INVALID)
        self.assertEqual(api_client.deactivate_calls, [])
        self.assertEqual(model.clear_calls, 0)
