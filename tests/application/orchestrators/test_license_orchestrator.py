import logging
import unittest
from unittest.mock import patch
from ost_visualizer.application.dtos.license_dto import (
    LicenseOperationResultDto,
    LicenseOperationStatus,
)
from ost_visualizer.application.orchestrators.license_orchestrator import (
    LicenseOrchestrator,
)
from ost_visualizer.application.orchestrators.license_thread_manager import (
    LicenseThreadManager,
)
from ost_visualizer.application.use_cases.license.utils.license_use_case import (
    ERROR_CONTRACT,
    ERROR_DEVICE_ACTIVATION_INACTIVE,
    ERROR_MAX_ACTIVATIONS_REACHED,
)
from ost_visualizer.domain.entities.license import LicenseStatus
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
        self.offline = False
        self.hwid_error = None

    def has_license(self):
        return bool(self.license_key)

    def can_use_offline_grace(self):
        return self.offline

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
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeScheduler:
    def __init__(self):
        self.task = None
        self.running = False
        self.starts = 0

    def is_running(self):
        return self.running

    def set_task(self, task):
        self.task = task

    def start(self):
        self.starts += 1
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


class QueuedCallbackBridge:
    def __init__(self):
        self.callbacks = []
        self.worker_callbacks = []

    def dispatch(self, callback, payload):
        self.callbacks.append((callback, payload))

    def request_callback(self, callback, success, message):
        self.worker_callbacks.append((callback, success, message))


class RecordingThreadManager(LicenseThreadManager):
    def __init__(self):
        super().__init__(logging.getLogger("test"))
        self.threads = []

    def spawn_with_bridge(self, *args, **kwargs):
        thread = super().spawn_with_bridge(*args, **kwargs)
        self.threads.append(thread)
        return thread

    def drain(self, testcase):
        for thread in self.threads:
            thread.join(timeout=2.0)
            testcase.assertFalse(thread.is_alive(), "license worker did not terminate")


class LicenseActivationContractTests(unittest.TestCase):
    def test_worker_exceptions_report_boolean_failure_and_allow_retry(self):
        for operation in ("activate", "deactivate"):
            with self.subTest(operation=operation):
                failing = FakeUseCase(RuntimeError("server failure"))
                bridge = QueuedCallbackBridge()
                manager = RecordingThreadManager()
                publisher = FakeEventPublisher()
                orchestrator = self._build_orchestrator(
                    failing,
                    failing,
                    publisher,
                    callback_bridge=bridge,
                    thread_manager=manager,
                    deactivate=failing,
                )
                outcomes = []

                def submit():
                    callback = lambda success, message: outcomes.append(
                        (success, message)
                    )
                    if operation == "activate":
                        orchestrator.activate_license_async("LIC-new", callback)
                    else:
                        orchestrator.deactivate_license_async(callback)

                with self.assertLogs("test", level="ERROR"):
                    submit()
                    manager.drain(self)
                self.assertEqual(outcomes, [])
                self.assertEqual(len(bridge.worker_callbacks), 1)
                callback, success, message = bridge.worker_callbacks.pop()
                callback(success, message)
                self.assertEqual(len(outcomes), 1)
                self.assertIs(outcomes[0][0], False)
                self.assertEqual(outcomes[0][1], "Operation failed: server failure")
                self.assertEqual(publisher.activated_calls, 0)
                self.assertEqual(publisher.lost_calls, 0)
                failing.result = self._result(
                    True,
                    LicenseOperationStatus.SUCCESS,
                    (
                        LicenseStatus.VALID
                        if operation == "activate"
                        else LicenseStatus.NO_LICENSE
                    ),
                    "recovered",
                )
                submit()
                manager.drain(self)
                callback, success, message = bridge.worker_callbacks.pop()
                callback(success, message)
                self.assertEqual(outcomes[-1], (True, "recovered"))
                self.assertEqual(len(failing.calls), 2)
                self.assertEqual(
                    publisher.activated_calls, int(operation == "activate")
                )
                self.assertEqual(publisher.lost_calls, int(operation == "deactivate"))

    def test_thread_start_failure_does_not_leave_license_operations_busy(self):
        for operation in ("activate", "deactivate"):
            with self.subTest(operation=operation):
                valid = self._result(
                    True, LicenseOperationStatus.SUCCESS, LicenseStatus.VALID, "done"
                )
                use_case = FakeUseCase(valid)
                bridge = QueuedCallbackBridge()
                manager = RecordingThreadManager()
                orchestrator = self._build_orchestrator(
                    use_case,
                    use_case,
                    FakeEventPublisher(),
                    callback_bridge=bridge,
                    thread_manager=manager,
                    deactivate=use_case,
                )
                outcomes = []

                def submit():
                    callback = lambda *args: outcomes.append(args)
                    if operation == "activate":
                        orchestrator.activate_license_async("LIC-new", callback)
                    else:
                        orchestrator.deactivate_license_async(callback)

                with patch(
                    "threading.Thread.start", side_effect=RuntimeError("cannot start")
                ):
                    with self.assertRaisesRegex(RuntimeError, "cannot start"):
                        submit()
                self.assertEqual(use_case.calls, [])
                self.assertEqual(outcomes, [])
                submit()
                manager.drain(self)
                self.assertEqual(len(bridge.worker_callbacks), 1)
                callback, success, message = bridge.worker_callbacks.pop()
                callback(success, message)
                self.assertEqual(outcomes, [(True, "done")])

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
        orchestrator.initialize()
        self.assertEqual(validate.calls, [None])
        self.assertEqual(activate.calls, ["LIC-test-key"])
        self.assertEqual(publisher.activated_calls, 1)
        self.assertEqual(publisher.invalidated, [])
        self.assertTrue(orchestrator._scheduler.is_running())
        self.assertEqual(orchestrator._scheduler.starts, 1)
        self.assertEqual(orchestrator.get_license_info().status, "valid")

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
        self.assertEqual(validate.calls, [None])
        self.assertEqual(activate.calls, [])
        self.assertEqual(publisher.activated_calls, 0)
        self.assertEqual(
            publisher.invalidated, [("max devices", LicenseStatus.INVALID)]
        )

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
        self.assertEqual(validate.calls, [None])
        self.assertEqual(activate.calls, ["LIC-test-key"])
        self.assertEqual(publisher.activated_calls, 0)
        self.assertEqual(
            publisher.invalidated, [("max devices", LicenseStatus.INVALID)]
        )

    def test_periodic_invalid_result_publishes_on_callback_bridge(self):
        invalid = self._result(
            False,
            LicenseOperationStatus.INVALID_KEY,
            LicenseStatus.INVALID,
            "invalid",
        )
        validate = FakeUseCase(invalid)
        publisher = FakeEventPublisher()
        bridge = QueuedCallbackBridge()
        orchestrator = self._build_orchestrator(
            validate,
            FakeUseCase(invalid),
            publisher,
            callback_bridge=bridge,
        )
        result = orchestrator._perform_periodic_validation()
        self.assertIs(result, invalid)
        self.assertEqual(publisher.invalidated, [])
        self.assertEqual(len(bridge.callbacks), 1)
        callback, payload = bridge.callbacks.pop()
        self.assertEqual(payload, (False, "invalid", LicenseStatus.INVALID))
        callback(payload)
        self.assertEqual(
            publisher.invalidated,
            [("invalid", LicenseStatus.INVALID)],
        )

    def test_periodic_success_publishes_recovery_on_callback_bridge(self):
        valid = self._result(
            True,
            LicenseOperationStatus.SUCCESS,
            LicenseStatus.VALID,
            "valid",
        )
        validate = FakeUseCase(valid)
        publisher = FakeEventPublisher()
        bridge = QueuedCallbackBridge()
        orchestrator = self._build_orchestrator(
            validate,
            FakeUseCase(valid),
            publisher,
            callback_bridge=bridge,
        )
        result = orchestrator._perform_periodic_validation()
        self.assertIs(result, valid)
        self.assertEqual(publisher.activated_calls, 0)
        self.assertEqual(len(bridge.callbacks), 1)
        callback, payload = bridge.callbacks.pop()
        self.assertEqual(payload, (True, "valid", LicenseStatus.VALID))
        callback(payload)
        self.assertEqual(publisher.activated_calls, 1)

    def test_periodic_callback_queued_before_cleanup_is_invalidated(self):
        invalid = self._result(
            False,
            LicenseOperationStatus.INVALID_KEY,
            LicenseStatus.INVALID,
            "invalid",
        )
        publisher = FakeEventPublisher()
        bridge = QueuedCallbackBridge()
        orchestrator = self._build_orchestrator(
            FakeUseCase(invalid),
            FakeUseCase(invalid),
            publisher,
            callback_bridge=bridge,
        )
        orchestrator._perform_periodic_validation()
        self.assertEqual(len(bridge.callbacks), 1)
        orchestrator.cleanup()
        callback, payload = bridge.callbacks.pop()
        callback(payload)
        self.assertEqual(publisher.invalidated, [])

    def test_cleanup_continues_after_scheduler_stop_failure(self):
        invalid = self._result(
            False,
            LicenseOperationStatus.INVALID_KEY,
            LicenseStatus.INVALID,
            "invalid",
        )
        orchestrator = self._build_orchestrator(
            FakeUseCase(invalid),
            FakeUseCase(invalid),
            FakeEventPublisher(),
        )
        calls = []

        class FailingScheduler(FakeScheduler):
            def stop(self):
                calls.append("stop")
                raise RuntimeError("scheduler stop failed")

            def clear_task(self):
                calls.append("clear_task")
                super().clear_task()

        class RecordingThreadManager(ImmediateThreadManager):
            def cleanup(self):
                calls.append("thread_cleanup")

        orchestrator._scheduler = FailingScheduler()
        orchestrator._thread_manager = RecordingThreadManager()
        with self.assertRaisesRegex(RuntimeError, "scheduler stop failed"):
            orchestrator.cleanup()
        self.assertEqual(calls, ["stop", "clear_task", "thread_cleanup"])
        self.assertIsNone(orchestrator._scheduler)
        self.assertIsNone(orchestrator._thread_manager)
        self.assertIsNone(orchestrator._callback_bridge)
        self.assertIsNone(orchestrator._event_publisher)
        orchestrator.cleanup()

    def test_cleanup_reports_failures_from_every_teardown_stage(self):
        invalid = self._result(
            False,
            LicenseOperationStatus.INVALID_KEY,
            LicenseStatus.INVALID,
            "invalid",
        )
        orchestrator = self._build_orchestrator(
            FakeUseCase(invalid),
            FakeUseCase(invalid),
            FakeEventPublisher(),
        )
        calls = []

        class FailingScheduler(FakeScheduler):
            def stop(self):
                calls.append("stop")
                raise RuntimeError("stop failed")

            def clear_task(self):
                calls.append("clear_task")
                raise RuntimeError("clear failed")

        class FailingThreadManager(ImmediateThreadManager):
            def cleanup(self):
                calls.append("thread_cleanup")
                raise RuntimeError("worker failed")

        orchestrator._scheduler = FailingScheduler()
        orchestrator._thread_manager = FailingThreadManager()
        with self.assertRaises(ExceptionGroup) as captured:
            orchestrator.cleanup()
        self.assertEqual(calls, ["stop", "clear_task", "thread_cleanup"])
        self.assertEqual(
            [str(error) for error in captured.exception.exceptions],
            ["stop failed", "clear failed", "worker failed"],
        )
        self.assertIsNone(orchestrator._scheduler)
        self.assertIsNone(orchestrator._thread_manager)
        orchestrator.cleanup()

    def test_startup_hwid_failure_is_explicit_and_skips_server_validation(self):
        invalid = self._result(
            False,
            LicenseOperationStatus.INVALID_KEY,
            LicenseStatus.INVALID,
            "must not run",
        )
        model = FakeModel()
        model.hwid = None
        model.hwid_error = HardwareIdentityError("firmware unavailable")
        validate = FakeUseCase(invalid)
        publisher = FakeEventPublisher()
        orchestrator = self._build_orchestrator(
            validate,
            FakeUseCase(invalid),
            publisher,
            model=model,
        )
        orchestrator.initialize()
        self.assertEqual(validate.calls, [])
        self.assertEqual(orchestrator.get_license_info().status, "hwid_unavailable")
        self.assertIn(
            "hardware identity is unavailable",
            orchestrator.get_view_model().message,
        )
        self.assertFalse(orchestrator.get_view_model().hardware_identity_available)
        self.assertEqual(len(publisher.invalidated), 1)
        self.assertIn("hardware identity is unavailable", publisher.invalidated[0][0])

    def test_startup_populates_hwid_before_license_state_projection(self):
        class PopulatingHwidModel(FakeModel):
            def __init__(self):
                super().__init__()
                self.license_key = None
                self.hwid = None
                self.ensure_calls = 0

            def ensure_hwid(self):
                self.ensure_calls += 1
                self.hwid = TEST_HWID
                return self.hwid

        invalid = self._result(
            False,
            LicenseOperationStatus.INVALID_KEY,
            LicenseStatus.INVALID,
            "must not run",
        )
        model = PopulatingHwidModel()
        validate = FakeUseCase(invalid)
        publisher = FakeEventPublisher()
        orchestrator = self._build_orchestrator(
            validate,
            FakeUseCase(invalid),
            publisher,
            model=model,
        )
        orchestrator.initialize()
        self.assertEqual(model.ensure_calls, 1)
        self.assertEqual(model.hwid, TEST_HWID)
        self.assertEqual(validate.calls, [])
        self.assertEqual(publisher.lost_calls, 1)

    def test_activation_hwid_failure_returns_explicit_message(self):
        invalid = self._result(
            False,
            LicenseOperationStatus.INVALID_KEY,
            LicenseStatus.INVALID,
            "must not run",
        )
        model = FakeModel()
        model.hwid = None
        model.hwid_error = HardwareIdentityError("firmware unavailable")
        activate = FakeUseCase(invalid)
        orchestrator = self._build_orchestrator(
            FakeUseCase(invalid),
            activate,
            FakeEventPublisher(),
            model=model,
        )
        outcomes = []
        orchestrator.activate_license_async(
            "LIC-test-key",
            lambda success, message: outcomes.append((success, message)),
        )
        self.assertEqual(activate.calls, [])
        self.assertEqual(len(outcomes), 1)
        self.assertFalse(outcomes[0][0])
        self.assertIn("hardware identity is unavailable", outcomes[0][1])

    def test_periodic_hwid_failure_marshals_notification_to_callback_bridge(self):
        invalid = self._result(
            False,
            LicenseOperationStatus.INVALID_KEY,
            LicenseStatus.INVALID,
            "must not run",
        )
        model = FakeModel()
        model.hwid_error = HardwareIdentityError("firmware unavailable")
        bridge = QueuedCallbackBridge()
        publisher = FakeEventPublisher()
        validate = FakeUseCase(invalid)
        orchestrator = self._build_orchestrator(
            validate,
            FakeUseCase(invalid),
            publisher,
            callback_bridge=bridge,
            model=model,
        )
        result = orchestrator._perform_periodic_validation()
        self.assertEqual(
            result.operation_status,
            LicenseOperationStatus.HWID_UNAVAILABLE,
        )
        self.assertEqual(validate.calls, [])
        self.assertEqual(publisher.invalidated, [])
        self.assertEqual(len(bridge.callbacks), 1)
        callback, payload = bridge.callbacks.pop()
        self.assertEqual(
            payload, (False, result.message, LicenseStatus.HWID_UNAVAILABLE)
        )
        callback(payload)
        self.assertEqual(
            publisher.invalidated,
            [(result.message, LicenseStatus.HWID_UNAVAILABLE)],
        )

    def test_pending_operation_rejects_overlap_until_main_thread_delivery(self):
        result = self._result(
            True, LicenseOperationStatus.SUCCESS, LicenseStatus.VALID, "done"
        )
        activate = FakeUseCase(result)
        deactivate = FakeUseCase(result)
        bridge = QueuedCallbackBridge()
        manager = RecordingThreadManager()
        publisher = FakeEventPublisher()
        orchestrator = self._build_orchestrator(
            FakeUseCase(result),
            activate,
            publisher,
            callback_bridge=bridge,
            thread_manager=manager,
            deactivate=deactivate,
        )
        outcomes = []
        callback = lambda *args: outcomes.append(args)
        orchestrator.activate_license_async("LIC-first", callback)
        manager.drain(self)
        orchestrator.activate_license_async("LIC-second", callback)
        orchestrator.deactivate_license_async(callback)
        self.assertEqual(activate.calls, ["LIC-first"])
        self.assertEqual(deactivate.calls, [])
        self.assertEqual(
            outcomes, [(False, "Another license operation is in progress")] * 2
        )
        self.assertEqual(publisher.activated_calls, 0)
        self.assertEqual(len(bridge.worker_callbacks), 1)
        completion, success, message = bridge.worker_callbacks.pop()
        completion(success, message)
        self.assertEqual(outcomes[-1], (True, "done"))
        orchestrator.deactivate_license_async(callback)
        manager.drain(self)
        completion, success, message = bridge.worker_callbacks.pop()
        completion(success, message)
        self.assertEqual(deactivate.calls, [None])
        self.assertEqual(publisher.activated_calls, 1)
        self.assertEqual(publisher.lost_calls, 1)

    def test_cleanup_invalidates_queued_activation_and_deactivation_completions(self):
        for operation in ("activate", "deactivate"):
            with self.subTest(operation=operation):
                result = self._result(
                    True, LicenseOperationStatus.SUCCESS, LicenseStatus.VALID, "done"
                )
                use_case = FakeUseCase(result)
                bridge = QueuedCallbackBridge()
                manager = RecordingThreadManager()
                publisher = FakeEventPublisher()
                orchestrator = self._build_orchestrator(
                    use_case,
                    use_case,
                    publisher,
                    callback_bridge=bridge,
                    thread_manager=manager,
                    deactivate=use_case,
                )
                outcomes = []
                if operation == "activate":
                    orchestrator.activate_license_async(
                        "LIC-new", lambda *args: outcomes.append(args)
                    )
                else:
                    orchestrator.deactivate_license_async(
                        lambda *args: outcomes.append(args)
                    )
                manager.drain(self)
                self.assertEqual(len(bridge.worker_callbacks), 1)
                orchestrator.cleanup()
                callback, success, message = bridge.worker_callbacks.pop()
                callback(success, message)
                self.assertEqual(outcomes, [])
                self.assertEqual(publisher.activated_calls, 0)
                self.assertEqual(publisher.lost_calls, 0)

    def test_periodic_no_license_and_closed_states_do_not_contact_server(self):
        model = FakeModel()
        model.license_key = None
        validate = FakeUseCase(RuntimeError("must not run"))
        bridge = QueuedCallbackBridge()
        orchestrator = self._build_orchestrator(
            validate,
            validate,
            FakeEventPublisher(),
            model=model,
            callback_bridge=bridge,
        )
        self.assertIsNone(orchestrator._perform_periodic_validation())
        model.license_key = "LIC-restored"
        orchestrator.cleanup()
        self.assertIsNone(orchestrator._perform_periodic_validation())
        self.assertEqual(validate.calls, [])
        self.assertEqual(bridge.callbacks, [])

    def test_network_failure_preserves_access_only_with_current_offline_grace(self):
        for offline in (True, False):
            with self.subTest(offline=offline):
                model = FakeModel()
                model.offline = offline
                result = self._result(
                    False,
                    LicenseOperationStatus.NETWORK_ERROR,
                    LicenseStatus.NETWORK_ERROR,
                    "unavailable",
                )
                publisher = FakeEventPublisher()
                bridge = QueuedCallbackBridge()
                orchestrator = self._build_orchestrator(
                    FakeUseCase(result),
                    FakeUseCase(result),
                    publisher,
                    model=model,
                    callback_bridge=bridge,
                )
                orchestrator._perform_periodic_validation()
                self.assertEqual(orchestrator.has_valid_license(), offline)
                self.assertEqual(
                    orchestrator.get_license_info().status,
                    "grace" if offline else "network_error",
                )
                callback, payload = bridge.callbacks.pop()
                callback(payload)
                self.assertEqual(publisher.activated_calls, int(offline))
                self.assertEqual(
                    publisher.invalidated,
                    [] if offline else [("unavailable", LicenseStatus.NETWORK_ERROR)],
                )
                model.offline = False
                self.assertFalse(orchestrator.has_valid_license())

    def _build_orchestrator(
        self,
        validate,
        activate,
        publisher,
        callback_bridge=None,
        model=None,
        thread_manager=None,
        deactivate=None,
    ):
        model = model or FakeModel()
        orchestrator = LicenseOrchestrator(
            license_model=model,
            validate_use_case=validate,
            activate_use_case=activate,
            deactivate_use_case=deactivate
            or FakeUseCase(
                LicenseOperationResultDto(
                    success=True,
                    operation_status=LicenseOperationStatus.SUCCESS,
                    license_status=LicenseStatus.NO_LICENSE,
                    message="deactivated",
                )
            ),
            scheduler=FakeScheduler(),
            event_publisher=publisher,
            thread_manager=thread_manager or ImmediateThreadManager(),
            callback_bridge=callback_bridge or QueuedCallbackBridge(),
            logger=logging.getLogger("test"),
        )
        self.addCleanup(orchestrator.cleanup)
        return orchestrator

    @staticmethod
    def _result(success, operation_status, license_status, message, error_code=None):
        return LicenseOperationResultDto(
            success=success,
            operation_status=operation_status,
            license_status=license_status,
            message=message,
            error_code=error_code,
        )
