import io
import json
import logging
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.dtos.license_activation_identity_dto import (
    LICENSE_ACTIVATION_IDENTITY_VERSION,
    LicenseActivationIdentityDto,
    WindowsJoinType,
)
from ost_visualizer.application.dtos.license_dto import (
    LicenseOperationResultDto,
    LicenseOperationStatus,
)
from ost_visualizer.application.orchestrators.license_orchestrator import (
    LicenseOrchestrator,
)
from ost_visualizer.application.use_cases.license.activate_license_use_case import (
    ActivateLicenseUseCase,
)
from ost_visualizer.application.use_cases.license.utils.license_use_case import (
    ERROR_CONTRACT,
    ERROR_DEVICE_ACTIVATION_INACTIVE,
    ERROR_INVALID_HWID,
    ERROR_INVALID_ACTIVATION_IDENTITY,
    ERROR_LICENSE_NOT_FOUND,
    ERROR_MAX_ACTIVATIONS_REACHED,
    parse_failure_response,
    parse_signed_success_response,
)
from ost_visualizer.domain.entities.license import License, LicenseStatus
from ost_visualizer.domain.services.hardware_identity import (
    HWID_VERSION,
    HardwareIdentityError,
)
from ost_visualizer.infrastructure.external.license_api_client import LicenseApiClient

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


class ImmediateThreadManager:
    def spawn_with_bridge(
        self, operation, callback_bridge, on_main_thread, error_prefix
    ):
        on_main_thread(*operation())

    def cleanup(self):
        pass


class _WireRecorder:
    """Stands in for urllib.request.urlopen: the only network boundary.
    Every request is recorded as (method, url, decoded JSON body); the answer is
    an HTTP 4xx response carrying the supplied JSON body, like the real server.
    """

    def __init__(self, status, body):
        self.requests = []
        self._status = status
        self._body = body

    def __call__(self, request, timeout=None, context=None):
        self.requests.append(
            (request.get_method(), request.full_url, json.loads(request.data))
        )
        raise urllib.error.HTTPError(
            request.full_url,
            self._status,
            "rejected",
            {},
            io.BytesIO(json.dumps(self._body).encode("utf-8")),
        )


_ACTIVATION_IDENTITY = LicenseActivationIdentityDto(
    version=LICENSE_ACTIVATION_IDENTITY_VERSION,
    windows_account=r"EXAMPLE\Estimator",
    computer_name="ESTIMATOR-PC",
    join_type=WindowsJoinType.DOMAIN,
    join_name="EXAMPLE",
)


class LicenseActivationContractTests(unittest.TestCase):
    def test_startup_reactivation_uses_required_activation_identity_payload(self):
        validate = FakeUseCase(
            self._result(
                False,
                LicenseOperationStatus.DEVICE_ACTIVATION_INACTIVE,
                LicenseStatus.INVALID,
                "inactive",
                ERROR_CONTRACT[ERROR_DEVICE_ACTIVATION_INACTIVE],
            )
        )
        client = LicenseApiClient(
            activation_identity_provider=SimpleNamespace(
                get_identity=lambda: _ACTIVATION_IDENTITY
            ),
            base_url="https://license.invalid/api",
        )
        wire = _WireRecorder(
            403,
            {
                "success": False,
                "error": "Maximum activations reached",
                "error_name": ERROR_MAX_ACTIVATIONS_REACHED,
                "error_code": ERROR_CONTRACT[ERROR_MAX_ACTIVATIONS_REACHED],
            },
        )
        model = FakeModel()
        activate = ActivateLicenseUseCase(model, client)
        publisher = FakeEventPublisher()
        orchestrator = self._build_orchestrator(
            validate,
            activate,
            publisher,
            model=model,
        )
        with patch("urllib.request.urlopen", wire):
            orchestrator.initialize()
        # Exactly one POST (a 4xx is not retried), carrying the versioned
        # activation_identity next to the canonical HWID.
        self.assertEqual(
            wire.requests,
            [
                (
                    "POST",
                    "https://license.invalid/api/activate",
                    {
                        "license_key": "LIC-test-key",
                        "hwid": TEST_HWID,
                        "activation_identity": {
                            "version": "v1",
                            "windows_account": r"EXAMPLE\Estimator",
                            "computer_name": "ESTIMATOR-PC",
                            "join_type": "domain",
                            "join_name": "EXAMPLE",
                        },
                    },
                )
            ],
        )
        # The single reactivation attempt is final: the activation-limit answer
        # is published as an invalidation instead of looping back to validate.
        self.assertEqual(validate.calls, [None])
        self.assertEqual(
            publisher.invalidated,
            [
                (
                    "License activation limit reached. This license is active on "
                    "the maximum number of devices.",
                    LicenseStatus.INVALID,
                )
            ],
        )
        self.assertEqual(publisher.activated_calls, 0)
        self.assertEqual(
            orchestrator.get_license_info().status, LicenseStatus.INVALID.value
        )

    def test_startup_validation_failure_without_inactive_device_does_not_reactivate(
        self,
    ):
        # Negative control for the reactivation test: only the dedicated
        # DEVICE_ACTIVATION_INACTIVE status triggers an activation request.
        validate = FakeUseCase(
            self._result(
                False,
                LicenseOperationStatus.FAILED,
                LicenseStatus.INVALID,
                "rejected",
                ERROR_CONTRACT[ERROR_INVALID_HWID],
            )
        )
        client = LicenseApiClient(
            activation_identity_provider=SimpleNamespace(
                get_identity=lambda: _ACTIVATION_IDENTITY
            ),
            base_url="https://license.invalid/api",
        )
        wire = _WireRecorder(403, {})
        model = FakeModel()
        publisher = FakeEventPublisher()
        orchestrator = self._build_orchestrator(
            validate,
            ActivateLicenseUseCase(model, client),
            publisher,
            model=model,
        )
        with patch("urllib.request.urlopen", wire):
            orchestrator.initialize()
        self.assertEqual(wire.requests, [])
        self.assertEqual(validate.calls, [None])
        self.assertEqual(publisher.invalidated, [("rejected", LicenseStatus.INVALID)])

    def _build_orchestrator(
        self,
        validate,
        activate,
        publisher,
        callback_bridge=None,
        model=None,
    ):
        model = model or FakeModel()
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
            callback_bridge=callback_bridge or object(),
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
