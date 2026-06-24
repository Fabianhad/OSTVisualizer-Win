import logging
import unittest

from ost_visualizer.application.dtos.license_dto import (
    LicenseOperationResultDto,
    LicenseOperationStatus,
)
from ost_visualizer.application.orchestrators.license_orchestrator import (
    LicenseOrchestrator,
)
from ost_visualizer.application.use_cases.license.deactivate_license_use_case import (
    DeactivateLicenseUseCase,
)
from ost_visualizer.application.use_cases.license.utils.license_use_case import (
    ERROR_CONTRACT,
    ERROR_DEVICE_ACTIVATION_INACTIVE,
    ERROR_LICENSE_NOT_FOUND,
    ERROR_MAX_ACTIVATIONS_REACHED,
    parse_failure_response,
    parse_signed_success_response,
)
from ost_visualizer.domain.entities.license import LicenseStatus


class FakeModel:
    def __init__(self):
        self.license_key = "LIC-test-key"
        self.hwid = "hwid-a"
        self.offline_grace_hours = 72
        self.clear_calls = 0
        self.valid = False

    def has_license(self):
        return bool(self.license_key)

    def can_use_offline_grace(self):
        return False

    def clear_if_invalid(self):
        return False

    def ensure_hwid(self):
        return self.hwid

    def has_valid_license(self):
        return self.valid

    def clear(self):
        self.clear_calls += 1
        self.license_key = None
        self.valid = False


class FakeUseCase:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, license_key=None):
        self.calls.append(license_key)
        return self.result


class FakeScheduler:
    def __init__(self):
        self.task = None
        self.running = False

    def is_running(self):
        return self.running

    def set_task(self, task):
        self.task = task

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def clear_task(self):
        self.task = None


class FakeEventPublisher:
    def __init__(self):
        self.activated_calls = 0
        self.invalidated = []
        self.lost_calls = 0

    def publish_activated(self):
        self.activated_calls += 1

    def publish_invalidated(self, message, status=None):
        self.invalidated.append((message, status))
        return True

    def publish_license_lost(self):
        self.lost_calls += 1

    def reset_failure_state(self):
        pass


class ImmediateThreadManager:
    def spawn_with_bridge(
        self, operation, callback_bridge, on_main_thread, error_prefix
    ):
        on_main_thread(*operation())

    def cleanup(self):
        pass


class FakeApiClient:
    def __init__(self, deactivate_response):
        self.deactivate_response = deactivate_response

    def deactivate(self, license_key, hwid):
        return self.deactivate_response


class LicenseActivationContractTests(unittest.TestCase):
    def test_failure_parser_maps_explicit_inactive_device_contract(self):
        failure = parse_failure_response(
            {
                "valid": False,
                "error": "This device is not currently activated for this license.",
                "error_name": ERROR_DEVICE_ACTIVATION_INACTIVE,
                "error_code": ERROR_CONTRACT[ERROR_DEVICE_ACTIVATION_INACTIVE],
            },
            operation="validate",
            network_message="network",
            network_license_status=LicenseStatus.NETWORK_ERROR,
        )

        self.assertEqual(
            failure.result.operation_status,
            LicenseOperationStatus.DEVICE_ACTIVATION_INACTIVE,
        )
        self.assertEqual(
            failure.error_code, ERROR_CONTRACT[ERROR_DEVICE_ACTIVATION_INACTIVE]
        )

    def test_failure_parser_rejects_numeric_only_legacy_payload(self):
        failure = parse_failure_response(
            {
                "valid": False,
                "error": "Maximum activations reached",
                "error_code": ERROR_CONTRACT[ERROR_MAX_ACTIVATIONS_REACHED],
            },
            operation="validate",
            network_message="network",
            network_license_status=LicenseStatus.NETWORK_ERROR,
        )

        self.assertEqual(
            failure.result.operation_status, LicenseOperationStatus.NETWORK_ERROR
        )
        self.assertEqual(failure.result.license_status, LicenseStatus.NETWORK_ERROR)
        self.assertIn("invalid response", failure.result.message)

    def test_failure_parser_rejects_mismatched_error_name_and_code(self):
        failure = parse_failure_response(
            {
                "success": False,
                "error": "Mismatch",
                "error_name": ERROR_LICENSE_NOT_FOUND,
                "error_code": ERROR_CONTRACT[ERROR_MAX_ACTIVATIONS_REACHED],
            },
            operation="activate",
            network_message="network",
        )

        self.assertEqual(
            failure.result.operation_status, LicenseOperationStatus.NETWORK_ERROR
        )
        self.assertIn("invalid response", failure.result.message)

    def test_signed_success_parser_rejects_unsigned_success_payload(self):
        _response, contract_error = parse_signed_success_response(
            {"valid": True, "expiry_date": "2030-01-01T00:00:00"},
            success_field="valid",
            operation="validate",
        )

        self.assertIsNotNone(contract_error)
        self.assertEqual(
            contract_error.operation_status, LicenseOperationStatus.NETWORK_ERROR
        )

    def test_startup_validation_reactivates_once_for_inactive_device(self):
        validate = FakeUseCase(
            self._result(
                False,
                LicenseOperationStatus.DEVICE_ACTIVATION_INACTIVE,
                LicenseStatus.INVALID,
                "inactive",
                ERROR_CONTRACT[ERROR_DEVICE_ACTIVATION_INACTIVE],
            )
        )
        activate = FakeUseCase(
            self._result(
                True,
                LicenseOperationStatus.SUCCESS,
                LicenseStatus.VALID,
                "activated",
            )
        )
        publisher = FakeEventPublisher()
        orchestrator = self._build_orchestrator(validate, activate, publisher)

        orchestrator.initialize()

        self.assertEqual(validate.calls, [None])
        self.assertEqual(activate.calls, ["LIC-test-key"])
        self.assertEqual(publisher.activated_calls, 1)
        self.assertEqual(publisher.invalidated, [])

    def test_startup_validation_does_not_activate_for_max_device_error(self):
        validate = FakeUseCase(
            self._result(
                False,
                LicenseOperationStatus.ACTIVATION_LIMIT_REACHED,
                LicenseStatus.INVALID,
                "max devices",
                ERROR_CONTRACT[ERROR_MAX_ACTIVATIONS_REACHED],
            )
        )
        activate = FakeUseCase(
            self._result(
                True,
                LicenseOperationStatus.SUCCESS,
                LicenseStatus.VALID,
                "activated",
            )
        )
        publisher = FakeEventPublisher()
        orchestrator = self._build_orchestrator(validate, activate, publisher)

        orchestrator.initialize()

        self.assertEqual(activate.calls, [])
        self.assertEqual(publisher.activated_calls, 0)
        self.assertEqual(publisher.invalidated, [("max devices", LicenseStatus.INVALID)])

    def test_startup_reactivation_surfaces_activation_limit_without_looping(self):
        validate = FakeUseCase(
            self._result(
                False,
                LicenseOperationStatus.DEVICE_ACTIVATION_INACTIVE,
                LicenseStatus.INVALID,
                "inactive",
                ERROR_CONTRACT[ERROR_DEVICE_ACTIVATION_INACTIVE],
            )
        )
        activate = FakeUseCase(
            self._result(
                False,
                LicenseOperationStatus.ACTIVATION_LIMIT_REACHED,
                LicenseStatus.INVALID,
                "max devices",
                ERROR_CONTRACT[ERROR_MAX_ACTIVATIONS_REACHED],
            )
        )
        publisher = FakeEventPublisher()
        orchestrator = self._build_orchestrator(validate, activate, publisher)

        orchestrator.initialize()

        self.assertEqual(activate.calls, ["LIC-test-key"])
        self.assertEqual(publisher.activated_calls, 0)
        self.assertEqual(publisher.invalidated, [("max devices", LicenseStatus.INVALID)])

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

    def _build_orchestrator(self, validate, activate, publisher):
        model = FakeModel()
        return LicenseOrchestrator(
            license_model=model,
            validate_use_case=validate,
            activate_use_case=activate,
            deactivate_use_case=FakeUseCase(
                LicenseOperationResultDto(
                    success=True,
                    operation_status=LicenseOperationStatus.SUCCESS,
                    license_status=LicenseStatus.NO_LICENSE,
                    message="deactivated",
                )
            ),
            scheduler=FakeScheduler(),
            event_publisher=publisher,
            thread_manager=ImmediateThreadManager(),
            callback_bridge=object(),
            logger=logging.getLogger("test"),
        )

    @staticmethod
    def _result(success, operation_status, license_status, message, error_code=None):
        return LicenseOperationResultDto(
            success=success,
            operation_status=operation_status,
            license_status=license_status,
            message=message,
            error_code=error_code,
        )


if __name__ == "__main__":
    unittest.main()
