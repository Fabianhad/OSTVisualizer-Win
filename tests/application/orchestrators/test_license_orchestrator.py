import logging
import threading
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


class _LoggerSpy:
    def __init__(self):
        self.records = []

    def warning(self, message, *args):
        self.records.append(("warning", message % args))

    def error(self, message, *args):
        self.records.append(("error", message % args))


class _SpyingModel(FakeModel):
    def __init__(self):
        super().__init__()
        self.calls = []

    def clear_if_invalid(self):
        self.calls.append("clear_if_invalid")
        return False

    def ensure_hwid(self):
        self.calls.append("ensure_hwid")
        return super().ensure_hwid()


class _SpyingThreadManager:
    def __init__(self):
        self.prefixes = []

    def spawn_with_bridge(
        self, operation, callback_bridge, on_main_thread, error_prefix
    ):
        self.prefixes.append(error_prefix)
        on_main_thread(*operation())

    def cleanup(self):
        pass


OK = LicenseOperationStatus.SUCCESS


class LicenseOrchestratorStateTests(unittest.TestCase):
    _build_orchestrator = LicenseActivationContractTests._build_orchestrator
    _result = staticmethod(LicenseActivationContractTests._result)

    def build(self, validate_result=None, activate_result=None, model=None, **kwargs):
        validate = FakeUseCase(
            validate_result or self._result(True, OK, LicenseStatus.VALID, "ok")
        )
        activate = FakeUseCase(
            activate_result or self._result(True, OK, LicenseStatus.VALID, "activated")
        )
        publisher = FakeEventPublisher()
        orchestrator = self._build_orchestrator(
            validate, activate, publisher, model=model, **kwargs
        )
        return orchestrator, validate, activate, publisher

    # --- initialize -------------------------------------------------------
    def test_initialize_wires_the_periodic_task_validates_the_cache_and_starts_once(
        self,
    ):
        model = _SpyingModel()
        model.offline = True
        orchestrator, validate, _activate, publisher = self.build(model=model)
        orchestrator.initialize()
        scheduler = orchestrator._scheduler
        self.assertEqual(
            scheduler.task.__func__, LicenseOrchestrator._perform_periodic_validation
        )
        self.assertEqual(scheduler.starts, 1)
        self.assertEqual(model.calls[:2], ["clear_if_invalid", "ensure_hwid"])
        # Cached license inside the offline grace: shown as GRACE immediately, then validated.
        self.assertEqual(publisher.activated_calls, 2)
        self.assertEqual(validate.calls, [None])
        self.assertEqual(orchestrator.get_license_info().status, "valid")
        orchestrator.initialize()
        self.assertEqual(scheduler.starts, 1)
        self.assertEqual(validate.calls, [None])

    def test_initialize_publishes_grace_before_the_server_answers(self):
        model = FakeModel()
        model.offline = True
        bridge = QueuedCallbackBridge()
        manager = RecordingThreadManager()
        self.addCleanup(manager.cleanup)
        orchestrator, validate, _a, publisher = self.build(
            model=model, thread_manager=manager, callback_bridge=bridge
        )
        orchestrator.initialize()
        manager.drain(self)
        self.assertEqual(publisher.activated_calls, 1)
        self.assertEqual(orchestrator._current_license_status, LicenseStatus.VALID)

    def test_initialize_without_a_license_reports_it_lost_without_validating(self):
        model = FakeModel()
        model.license_key = None
        orchestrator, validate, _a, publisher = self.build(model=model)
        orchestrator._current_license_status = LicenseStatus.VALID
        orchestrator.initialize()
        self.assertIsNone(orchestrator._current_license_status)
        self.assertEqual(
            (publisher.lost_calls, publisher.activated_calls, validate.calls),
            (1, 0, []),
        )
        self.assertEqual(orchestrator._scheduler.starts, 1)
        self.assertEqual(orchestrator.get_license_info().status, "no_license")

    def test_initialize_with_a_license_outside_grace_validates_without_pretending_grace(
        self,
    ):
        model = FakeModel()
        model.offline = False
        orchestrator, validate, _a, publisher = self.build(
            validate_result=self._result(
                False,
                LicenseOperationStatus.NETWORK_ERROR,
                LicenseStatus.NETWORK_ERROR,
                "down",
            ),
            model=model,
        )
        orchestrator.initialize()
        self.assertEqual(validate.calls, [None])
        self.assertEqual(publisher.activated_calls, 0)
        self.assertEqual(publisher.invalidated, [("down", LicenseStatus.NETWORK_ERROR)])
        self.assertEqual(
            orchestrator._current_license_status, LicenseStatus.NETWORK_ERROR
        )

    def test_initialize_hardware_identity_failure_still_starts_the_scheduler_and_skips_the_server(
        self,
    ):
        model = FakeModel()
        model.hwid_error = HardwareIdentityError("firmware unavailable")
        logger = _LoggerSpy()
        orchestrator, validate, _a, publisher = self.build(model=model)
        orchestrator._logger = logger
        orchestrator.initialize()
        expected = (
            "This computer's hardware identity is unavailable. "
            "Restart Windows and try again; if the problem continues, contact support."
        )
        self.assertEqual(
            orchestrator._current_license_status, LicenseStatus.HWID_UNAVAILABLE
        )
        self.assertEqual(orchestrator._status_message, expected)
        self.assertEqual(
            publisher.invalidated, [(expected, LicenseStatus.HWID_UNAVAILABLE)]
        )
        self.assertEqual(validate.calls, [])
        self.assertEqual(orchestrator._scheduler.starts, 1)
        self.assertEqual(
            logger.records,
            [("error", "Hardware identity validation failed: firmware unavailable")],
        )
        view = orchestrator.get_view_model()
        self.assertIs(view.hardware_identity_available, False)
        self.assertEqual(view.message, expected)

    # --- operations ---------------------------------------------------------
    def test_activation_applies_the_result_in_the_worker_and_reports_on_the_main_thread(
        self,
    ):
        manager = _SpyingThreadManager()
        orchestrator, _v, activate, publisher = self.build(thread_manager=manager)
        outcomes = []
        orchestrator.activate_license_async(
            "KEY", lambda ok, msg: outcomes.append((ok, msg))
        )
        self.assertEqual(manager.prefixes, ["activation"])
        self.assertEqual(activate.calls, ["KEY"])
        self.assertEqual(outcomes, [(True, "activated")])
        self.assertEqual(publisher.activated_calls, 1)
        self.assertEqual(orchestrator._current_license_status, LicenseStatus.VALID)
        self.assertIs(orchestrator._operation_in_progress, False)

    def test_a_refused_activation_changes_no_status_and_publishes_nothing(self):
        failed = self._result(
            False,
            LicenseOperationStatus.NETWORK_ERROR,
            LicenseStatus.INVALID,
            "bad key",
        )
        orchestrator, _v, _a, publisher = self.build(activate_result=failed)
        outcomes = []
        orchestrator.activate_license_async(
            "KEY", lambda ok, msg: outcomes.append((ok, msg))
        )
        self.assertEqual(outcomes, [(False, "bad key")])
        self.assertEqual(publisher.activated_calls, 0)
        self.assertIsNone(orchestrator._current_license_status)
        self.assertIs(orchestrator._operation_in_progress, False)

    def test_deactivation_applies_success_or_no_license_and_reports_the_loss(self):
        manager = _SpyingThreadManager()
        for status, success, applied in (
            (OK, True, True),
            (LicenseOperationStatus.NO_LICENSE, False, True),
        ):
            with self.subTest(status=status):
                result = self._result(success, status, LicenseStatus.NO_LICENSE, "done")
                orchestrator, _v, _a, publisher = self.build(thread_manager=manager)
                orchestrator._deactivate_use_case = FakeUseCase(result)
                orchestrator._current_license_status = LicenseStatus.VALID
                outcomes = []
                orchestrator.deactivate_license_async(
                    lambda ok, msg: outcomes.append((ok, msg))
                )
                self.assertEqual(outcomes, [(success, "done")])
                self.assertEqual(publisher.lost_calls, int(success))
                self.assertEqual(
                    orchestrator._current_license_status, LicenseStatus.NO_LICENSE
                )
        self.assertEqual(manager.prefixes, ["deactivation", "deactivation"])

    def test_a_failed_deactivation_leaves_the_license_state_alone(self):
        manager = _SpyingThreadManager()
        result = self._result(
            False,
            LicenseOperationStatus.NETWORK_ERROR,
            LicenseStatus.NETWORK_ERROR,
            "offline",
        )
        orchestrator, _v, _a, publisher = self.build(thread_manager=manager)
        orchestrator._deactivate_use_case = FakeUseCase(result)
        orchestrator._current_license_status = LicenseStatus.VALID
        outcomes = []
        orchestrator.deactivate_license_async(
            lambda ok, msg: outcomes.append((ok, msg))
        )
        self.assertEqual(outcomes, [(False, "offline")])
        self.assertEqual(
            (publisher.lost_calls, orchestrator._current_license_status),
            (0, LicenseStatus.VALID),
        )

    def test_overlap_refusal_message_is_exact_for_activation_and_deactivation(self):
        orchestrator, _v, activate, _p = self.build()
        orchestrator._operation_in_progress = True
        seen = []
        orchestrator.activate_license_async("K", lambda ok, msg: seen.append((ok, msg)))
        orchestrator.deactivate_license_async(lambda ok, msg: seen.append((ok, msg)))
        self.assertEqual(
            seen, [(False, "Another license operation is in progress")] * 2
        )
        self.assertEqual(activate.calls, [])

    # --- status projection --------------------------------------------------
    def test_apply_result_maps_each_outcome_to_a_license_status_and_message(self):
        orchestrator, *_ = self.build()
        cases = (
            (
                self._result(True, OK, LicenseStatus.VALID, "m"),
                LicenseStatus.VALID,
                None,
            ),
            (
                self._result(
                    False,
                    LicenseOperationStatus.HWID_UNAVAILABLE,
                    LicenseStatus.HWID_UNAVAILABLE,
                    "no hw",
                ),
                LicenseStatus.HWID_UNAVAILABLE,
                "no hw",
            ),
            (
                self._result(False, LicenseOperationStatus.NO_LICENSE, None, "none"),
                None,
                None,
            ),
            (self._result(True, OK, None, "ok"), LicenseStatus.VALID, None),
            (
                self._result(False, LicenseOperationStatus.NETWORK_ERROR, None, "x"),
                LicenseStatus.INVALID,
                None,
            ),
            (
                self._result(
                    False,
                    LicenseOperationStatus.NETWORK_ERROR,
                    LicenseStatus.EXPIRED,
                    "old",
                ),
                LicenseStatus.EXPIRED,
                None,
            ),
        )
        for result, status, message in cases:
            with self.subTest(result=result):
                orchestrator._current_license_status = LicenseStatus.GRACE
                orchestrator._apply_result(result)
                self.assertEqual(orchestrator._current_license_status, status)
                self.assertEqual(orchestrator._status_message, message)

    def test_network_error_inside_grace_logs_the_grace_hours_and_shows_grace(self):
        model = FakeModel()
        model.offline = True
        model.offline_grace_hours = 48
        logger = _LoggerSpy()
        orchestrator, *_ = self.build(model=model)
        orchestrator._logger = logger
        orchestrator._apply_result(
            self._result(
                False,
                LicenseOperationStatus.NETWORK_ERROR,
                LicenseStatus.NETWORK_ERROR,
                "down",
            )
        )
        self.assertEqual(orchestrator._current_license_status, LicenseStatus.GRACE)
        self.assertEqual(
            logger.records,
            [
                (
                    "warning",
                    "License server unavailable; using cached license within 48-hour offline grace",
                )
            ],
        )
        model.offline = False
        logger.records.clear()
        orchestrator._apply_result(
            self._result(
                False,
                LicenseOperationStatus.NETWORK_ERROR,
                LicenseStatus.NETWORK_ERROR,
                "down",
            )
        )
        self.assertEqual(
            orchestrator._current_license_status, LicenseStatus.NETWORK_ERROR
        )
        self.assertEqual(logger.records, [])

    def test_validity_follows_the_model_for_valid_and_grace_and_is_false_otherwise(
        self,
    ):
        model = FakeModel()
        orchestrator, *_ = self.build(model=model)
        for status, valid, offline, expected in (
            (LicenseStatus.VALID, True, False, True),
            (LicenseStatus.VALID, False, True, False),
            (LicenseStatus.GRACE, False, True, True),
            (LicenseStatus.GRACE, True, False, False),
            (LicenseStatus.INVALID, True, True, False),
            (None, True, True, False),
        ):
            with self.subTest(status=status, valid=valid, offline=offline):
                model.valid, model.offline = valid, offline
                orchestrator._current_license_status = status
                self.assertIs(orchestrator.has_valid_license(), expected)

    def test_license_info_and_view_model_expose_the_expiry_key_and_status_text(self):
        from datetime import datetime, timezone

        model = FakeModel()
        model.expiry_date = datetime(2030, 1, 2, tzinfo=timezone.utc)
        model.valid = True
        orchestrator, *_ = self.build(model=model)
        orchestrator._current_license_status = LicenseStatus.VALID
        orchestrator._status_message = "note"
        info = orchestrator.get_license_info()
        self.assertEqual(
            (info.has_license, info.status, info.expiry_date, info.license_key),
            (True, "valid", "2030-01-02T00:00:00+00:00", "LIC-test-key"),
        )
        view = orchestrator.get_view_model()
        self.assertEqual(
            (
                view.has_license,
                view.status,
                view.expiry_date,
                view.license_key,
                view.message,
                view.hardware_identity_available,
            ),
            (True, "valid", "2030-01-02T00:00:00+00:00", "LIC-test-key", "note", True),
        )
        model.expiry_date = None
        orchestrator._current_license_status = None
        self.assertEqual(
            (
                orchestrator.get_license_info().expiry_date,
                orchestrator.get_license_info().status,
            ),
            (None, "no_license"),
        )

    # --- notifications ------------------------------------------------------
    def test_validation_outcomes_publish_activation_or_invalidation_by_status(self):
        for success, status, valid, activated, invalidated in (
            (True, LicenseStatus.VALID, False, 1, False),
            (False, LicenseStatus.NETWORK_ERROR, True, 1, False),
            (False, LicenseStatus.NETWORK_ERROR, False, 0, True),
            (False, LicenseStatus.INVALID, True, 0, True),
            (False, LicenseStatus.EXPIRED, False, 0, True),
            (False, LicenseStatus.HWID_UNAVAILABLE, False, 0, True),
            (False, LicenseStatus.NO_LICENSE, False, 0, False),
            (False, LicenseStatus.GRACE, False, 0, False),
            (False, None, False, 0, False),
        ):
            with self.subTest(success=success, status=status, valid=valid):
                model = FakeModel()
                model.valid = valid
                orchestrator, _v, _a, publisher = self.build(model=model)
                orchestrator._current_license_status = LicenseStatus.VALID
                orchestrator._publish_validation_outcome(success, "msg", status)
                self.assertEqual(publisher.activated_calls, activated)
                self.assertEqual(bool(publisher.invalidated), invalidated)
                if invalidated:
                    self.assertEqual(publisher.invalidated, [("msg", status)])

    def test_nothing_is_published_after_cleanup(self):
        orchestrator, _v, _a, publisher = self.build()
        orchestrator._publish_validation_outcome(True, "m", LicenseStatus.VALID)
        self.assertEqual(publisher.activated_calls, 1)
        publisher_ref = publisher
        orchestrator._closed = True
        orchestrator._publish_validation_outcome(True, "m", LicenseStatus.VALID)
        orchestrator._publish_periodic_validation_outcome(
            (False, "m", LicenseStatus.INVALID)
        )
        self.assertEqual(
            (publisher_ref.activated_calls, publisher_ref.invalidated), (1, [])
        )
        self.assertIsNone(orchestrator._perform_periodic_validation())

    def test_cleanup_failures_are_grouped_with_the_fixed_message_and_cleanup_is_idempotent(
        self,
    ):
        class Failing(FakeScheduler):
            def stop(self):
                raise RuntimeError("stop")

            def clear_task(self):
                raise ValueError("clear")

        orchestrator, *_ = self.build()
        orchestrator._scheduler = Failing()
        with self.assertRaises(ExceptionGroup) as raised:
            orchestrator.cleanup()
        self.assertEqual(
            raised.exception.message, "License orchestrator cleanup failed"
        )
        self.assertEqual(
            [type(e) for e in raised.exception.exceptions], [RuntimeError, ValueError]
        )
        orchestrator.cleanup()
        for attribute in (
            "_callback_bridge",
            "_event_publisher",
            "_scheduler",
            "_thread_manager",
        ):
            self.assertIsNone(getattr(orchestrator, attribute))


class _PendingThreadManager:
    def __init__(self):
        self.pending = []
        self.prefixes = []

    def spawn_with_bridge(
        self, operation, callback_bridge, on_main_thread, error_prefix
    ):
        self.prefixes.append(error_prefix)
        self.pending.append((operation, on_main_thread))

    def cleanup(self):
        pass


class LicenseOrchestratorAsyncOrderingTests(unittest.TestCase):
    _build_orchestrator = LicenseActivationContractTests._build_orchestrator
    _result = staticmethod(LicenseActivationContractTests._result)

    def build(self, **kwargs):
        validate = FakeUseCase(self._result(True, OK, LicenseStatus.VALID, "ok"))
        activate = FakeUseCase(self._result(True, OK, LicenseStatus.VALID, "activated"))
        publisher = FakeEventPublisher()
        orchestrator = self._build_orchestrator(validate, activate, publisher, **kwargs)
        return orchestrator, validate, publisher

    def test_a_cached_license_inside_the_offline_grace_is_shown_as_grace_until_the_server_answers(
        self,
    ):
        model = _SpyingModel()
        model.offline = True
        manager = _PendingThreadManager()
        orchestrator, validate, publisher = self.build(
            model=model, thread_manager=manager
        )
        orchestrator.initialize()
        self.assertEqual(manager.prefixes, ["startup license validation"])
        self.assertEqual(orchestrator._current_license_status, LicenseStatus.GRACE)
        self.assertEqual(publisher.activated_calls, 1)
        self.assertEqual(validate.calls, [])
        self.assertEqual(model.calls.count("ensure_hwid"), 2)
        operation, on_main = manager.pending[0]
        on_main(*operation())
        self.assertEqual(orchestrator._current_license_status, LicenseStatus.VALID)

    def test_startup_validation_checks_the_hardware_identity_then_reports_the_outcome_to_its_callback(
        self,
    ):
        model = _SpyingModel()
        manager = _SpyingThreadManager()
        orchestrator, validate, publisher = self.build(
            model=model, thread_manager=manager
        )
        seen = []
        orchestrator._startup_validate_license_async(
            lambda ok, message: seen.append((ok, message))
        )
        self.assertEqual(model.calls, ["ensure_hwid"])
        self.assertEqual(seen, [(True, "ok")])
        self.assertEqual(publisher.activated_calls, 1)
        model.hwid_error = HardwareIdentityError("gone")
        with self.assertRaises(HardwareIdentityError):
            orchestrator._startup_validate_license_async(
                lambda *_: seen.append("never")
            )
        self.assertEqual(len(seen), 1)

    def test_a_pending_deactivation_blocks_other_operations_until_its_main_thread_delivery(
        self,
    ):
        manager = _PendingThreadManager()
        orchestrator, _v, _p = self.build(thread_manager=manager)
        first, second, third = [], [], []
        orchestrator.deactivate_license_async(lambda ok, msg: first.append((ok, msg)))
        self.assertIs(orchestrator._operation_in_progress, True)
        orchestrator.deactivate_license_async(lambda ok, msg: second.append((ok, msg)))
        orchestrator.activate_license_async(
            "K", lambda ok, msg: third.append((ok, msg))
        )
        self.assertEqual(second, [(False, "Another license operation is in progress")])
        self.assertEqual(third, [(False, "Another license operation is in progress")])
        operation, on_main = manager.pending[0]
        on_main(*operation())
        self.assertEqual(first, [(True, "deactivated")])
        self.assertIs(orchestrator._operation_in_progress, False)

    def test_periodic_validation_returns_the_server_result_and_applies_a_hardware_failure(
        self,
    ):
        model = FakeModel()
        orchestrator, validate, _p = self.build(model=model)
        result = validate.result
        self.assertIs(orchestrator._perform_periodic_validation(), result)
        model.hwid_error = HardwareIdentityError("firmware")
        logger = _LoggerSpy()
        orchestrator._logger = logger
        failure = orchestrator._perform_periodic_validation()
        self.assertEqual(
            logger.records, [("error", "Hardware identity validation failed: firmware")]
        )
        self.assertEqual(failure.license_status, LicenseStatus.HWID_UNAVAILABLE)
        self.assertEqual(
            orchestrator._current_license_status, LicenseStatus.HWID_UNAVAILABLE
        )
        self.assertEqual(orchestrator._status_message, failure.message)
        self.assertEqual(validate.calls, [None])


class LicenseOrchestratorOperationProtocolTests(unittest.TestCase):
    _build_orchestrator = LicenseActivationContractTests._build_orchestrator
    _result = staticmethod(LicenseActivationContractTests._result)

    def test_a_hardware_identity_failure_does_not_leave_license_operations_busy(self):
        success = self._result(True, OK, LicenseStatus.VALID, "activated")
        model = FakeModel()
        model.hwid_error = HardwareIdentityError("firmware unavailable")
        activate = FakeUseCase(success)
        orchestrator = self._build_orchestrator(
            FakeUseCase(success), activate, FakeEventPublisher(), model=model
        )
        outcomes = []
        orchestrator.activate_license_async(
            "KEY", lambda ok, message: outcomes.append((ok, message))
        )
        self.assertEqual(
            outcomes,
            [
                (
                    False,
                    "This computer's hardware identity is unavailable. "
                    "Restart Windows and try again; if the problem continues, contact support.",
                )
            ],
        )
        self.assertEqual(activate.calls, [])
        self.assertIs(orchestrator._operation_in_progress, False)
        model.hwid_error = None
        orchestrator.activate_license_async(
            "KEY", lambda ok, message: outcomes.append((ok, message))
        )
        self.assertEqual(outcomes[1:], [(True, "activated")])
        self.assertEqual(activate.calls, ["KEY"])
        self.assertEqual(orchestrator._current_license_status, LicenseStatus.VALID)

    def test_the_result_of_an_operation_is_applied_by_the_worker_before_the_main_thread_is_told(
        self,
    ):
        for operation, status in (
            ("activate", LicenseStatus.VALID),
            ("deactivate", LicenseStatus.NO_LICENSE),
        ):
            with self.subTest(operation=operation):
                result = self._result(True, OK, status, "done")
                use_case = FakeUseCase(result)
                bridge, manager, publisher = (
                    QueuedCallbackBridge(),
                    RecordingThreadManager(),
                    FakeEventPublisher(),
                )
                orchestrator = self._build_orchestrator(
                    use_case,
                    use_case,
                    publisher,
                    callback_bridge=bridge,
                    thread_manager=manager,
                    deactivate=use_case,
                )
                self.addCleanup(manager.cleanup)
                appliers = []
                real_apply = orchestrator._apply_result

                def recording_apply(applied, real_apply=real_apply, appliers=appliers):
                    appliers.append(threading.get_ident())
                    real_apply(applied)

                orchestrator._apply_result = recording_apply
                outcomes = []
                callback = lambda ok, message: outcomes.append((ok, message))
                if operation == "activate":
                    orchestrator.activate_license_async("KEY", callback)
                else:
                    orchestrator._current_license_status = LicenseStatus.VALID
                    orchestrator.deactivate_license_async(callback)
                manager.drain(self)
                self.assertEqual(outcomes, [])
                self.assertEqual(
                    (publisher.activated_calls, publisher.lost_calls), (0, 0)
                )
                self.assertEqual(orchestrator._current_license_status, status)
                self.assertEqual(len(appliers), 1)
                self.assertNotEqual(appliers[0], threading.get_ident())
                delivered, ok, message = bridge.worker_callbacks.pop()
                delivered(ok, message)
                self.assertEqual(outcomes, [(True, "done")])
                self.assertEqual(len(appliers), 1)


class LicenseOrchestratorReactivationGuardTests(unittest.TestCase):
    _build_orchestrator = LicenseActivationContractTests._build_orchestrator
    _result = staticmethod(LicenseActivationContractTests._result)

    def test_an_inactive_device_without_a_cached_key_is_not_reactivated(self):
        inactive = self._result(
            False,
            LicenseOperationStatus.DEVICE_ACTIVATION_INACTIVE,
            LicenseStatus.INVALID,
            "inactive",
        )
        model = FakeModel()
        model.license_key = None
        activate = FakeUseCase(self._result(True, OK, LicenseStatus.VALID, "activated"))
        orchestrator = self._build_orchestrator(
            FakeUseCase(inactive), activate, FakeEventPublisher(), model=model
        )
        self.assertIs(
            orchestrator._reactivate_once_if_device_activation_inactive(inactive),
            inactive,
        )
        self.assertEqual(activate.calls, [])
        model.license_key = "LIC"
        self.assertEqual(
            orchestrator._reactivate_once_if_device_activation_inactive(
                inactive
            ).message,
            "activated",
        )
        self.assertEqual(activate.calls, ["LIC"])
        ok = self._result(True, OK, LicenseStatus.VALID, "fine")
        self.assertIs(
            orchestrator._reactivate_once_if_device_activation_inactive(ok), ok
        )
        self.assertEqual(activate.calls, ["LIC"])


class _ArgumentRecordingThreadManager:
    def __init__(self):
        self.calls = []

    def spawn_with_bridge(
        self, operation, callback_bridge, on_main_thread, error_prefix
    ):
        self.calls.append((error_prefix, callback_bridge))

    def cleanup(self):
        pass


class LicenseOrchestratorFailurePolicyTests(unittest.TestCase):
    _build_orchestrator = LicenseActivationContractTests._build_orchestrator
    _result = staticmethod(LicenseActivationContractTests._result)

    class _BrokenModel(FakeModel):
        def ensure_hwid(self):
            raise RuntimeError("registry corrupt")

        def require_canonical_hwid(self):
            raise RuntimeError("registry corrupt")

    def _build(self, model, bridge=None, thread_manager=None):
        validate = FakeUseCase(self._result(True, OK, LicenseStatus.VALID, "ok"))
        activate = FakeUseCase(self._result(True, OK, LicenseStatus.VALID, "activated"))
        publisher = FakeEventPublisher()
        orchestrator = self._build_orchestrator(
            validate,
            activate,
            publisher,
            model=model,
            callback_bridge=bridge,
            thread_manager=thread_manager,
        )
        return orchestrator, validate, activate, publisher

    def test_an_unexpected_model_failure_during_initialize_is_not_reported_as_a_hardware_failure(
        self,
    ):
        orchestrator, validate, _activate, publisher = self._build(self._BrokenModel())
        with self.assertRaisesRegex(RuntimeError, "^registry corrupt$"):
            orchestrator.initialize()
        self.assertEqual(orchestrator._scheduler.starts, 0)
        self.assertEqual(validate.calls, [])
        self.assertEqual(
            (publisher.invalidated, publisher.lost_calls, publisher.activated_calls),
            ([], 0, 0),
        )
        self.assertIsNone(orchestrator._current_license_status)
        self.assertIsNone(orchestrator._status_message)

    def test_an_unexpected_model_failure_before_an_activation_is_not_reported_as_a_hardware_failure(
        self,
    ):
        orchestrator, _validate, activate, publisher = self._build(self._BrokenModel())
        outcomes = []
        with self.assertRaisesRegex(RuntimeError, "^registry corrupt$"):
            orchestrator.activate_license_async(
                "KEY", lambda ok, message: outcomes.append((ok, message))
            )
        self.assertEqual(outcomes, [])
        self.assertEqual(activate.calls, [])
        self.assertEqual(publisher.invalidated, [])
        self.assertIsNone(orchestrator._current_license_status)
        self.assertIs(orchestrator._operation_in_progress, False)

    def test_an_unexpected_model_failure_during_periodic_validation_is_not_reported_as_a_hardware_failure(
        self,
    ):
        bridge = QueuedCallbackBridge()
        orchestrator, validate, _activate, publisher = self._build(
            self._BrokenModel(), bridge=bridge
        )
        with self.assertRaisesRegex(RuntimeError, "^registry corrupt$"):
            orchestrator._perform_periodic_validation()
        self.assertEqual(validate.calls, [])
        self.assertEqual(bridge.callbacks, [])
        self.assertEqual(publisher.invalidated, [])
        self.assertIsNone(orchestrator._current_license_status)

    def test_a_periodic_validation_that_outlives_cleanup_returns_its_result_without_publishing(
        self,
    ):
        invalid = self._result(
            False,
            LicenseOperationStatus.INVALID_KEY,
            LicenseStatus.INVALID,
            "invalid",
        )

        class ValidationThatRacesCleanup(FakeUseCase):
            orchestrator = None

            def execute(self, license_key=None):
                self.orchestrator.cleanup()
                return super().execute(license_key)

        validate = ValidationThatRacesCleanup(invalid)
        publisher = FakeEventPublisher()
        bridge = QueuedCallbackBridge()
        orchestrator = self._build_orchestrator(
            validate, FakeUseCase(invalid), publisher, callback_bridge=bridge
        )
        validate.orchestrator = orchestrator
        self.assertIs(orchestrator._perform_periodic_validation(), invalid)
        self.assertEqual(validate.calls, [None])
        self.assertIsNone(orchestrator._callback_bridge)
        self.assertEqual(bridge.callbacks, [])
        self.assertEqual(publisher.invalidated, [])

    def test_a_hardware_failure_found_by_a_periodic_validation_that_outlives_cleanup_is_returned_without_publishing(
        self,
    ):
        bridge = QueuedCallbackBridge()
        holder = []

        class ModelThatRacesCleanup(FakeModel):
            def require_canonical_hwid(self):
                holder[0].cleanup()
                raise HardwareIdentityError("firmware unavailable")

        invalid = self._result(
            False,
            LicenseOperationStatus.INVALID_KEY,
            LicenseStatus.INVALID,
            "must not run",
        )
        validate = FakeUseCase(invalid)
        publisher = FakeEventPublisher()
        orchestrator = self._build_orchestrator(
            validate,
            FakeUseCase(invalid),
            publisher,
            model=ModelThatRacesCleanup(),
            callback_bridge=bridge,
        )
        holder.append(orchestrator)
        with self.assertLogs("test", level="ERROR"):
            result = orchestrator._perform_periodic_validation()
        self.assertEqual(
            result.operation_status, LicenseOperationStatus.HWID_UNAVAILABLE
        )
        self.assertEqual(result.license_status, LicenseStatus.HWID_UNAVAILABLE)
        self.assertEqual(validate.calls, [])
        self.assertIsNone(orchestrator._callback_bridge)
        self.assertEqual(bridge.callbacks, [])
        self.assertEqual(publisher.invalidated, [])

    def test_every_asynchronous_operation_hands_the_orchestrators_callback_bridge_to_the_thread_manager(
        self,
    ):
        for operation, expected_prefix in (
            ("initialize", "startup license validation"),
            ("activate", "activation"),
            ("deactivate", "deactivation"),
        ):
            with self.subTest(operation=operation):
                bridge = QueuedCallbackBridge()
                manager = _ArgumentRecordingThreadManager()
                orchestrator, *_ = self._build(
                    FakeModel(), bridge=bridge, thread_manager=manager
                )
                if operation == "initialize":
                    orchestrator.initialize()
                elif operation == "activate":
                    orchestrator.activate_license_async("KEY", lambda *_args: None)
                else:
                    orchestrator.deactivate_license_async(lambda *_args: None)
                self.assertEqual(len(manager.calls), 1)
                prefix, handed_bridge = manager.calls[0]
                self.assertEqual(prefix, expected_prefix)
                self.assertIs(handed_bridge, bridge)


class _ObservingPublisher:
    """Publisher stand-in that records, in one shared log, what a synchronous subscriber would see at publish time."""

    def __init__(self, log):
        self.log = log
        self.orchestrator = None

    def _view(self):
        return self.orchestrator.has_valid_license()

    def publish_activated(self):
        self.log.append(("activated", self._view()))

    def publish_license_lost(self):
        self.log.append(("lost", self._view()))

    def publish_invalidated(self, message, status=None):
        view = self.orchestrator.get_view_model()
        self.log.append(
            (
                "invalidated",
                self._view(),
                view.hardware_identity_available,
                view.message == message,
            )
        )
        return True


class LicenseOrchestratorPublishOrderingTests(unittest.TestCase):
    """EventBus.publish and the completion callbacks run synchronously, so the order of state changes, publications
    and callbacks inside the orchestrator is observable to subscribers and to callbacks that start the next operation.
    """

    _result = staticmethod(LicenseActivationContractTests._result)

    def _build(self, model=None, thread_manager=None, deactivate_result=None):
        log = []
        publisher = _ObservingPublisher(log)
        ok = self._result(True, OK, LicenseStatus.VALID, "activated")
        gone = deactivate_result or self._result(
            True, OK, LicenseStatus.NO_LICENSE, "deactivated"
        )
        orchestrator = LicenseOrchestrator(
            license_model=model or FakeModel(),
            validate_use_case=FakeUseCase(
                self._result(True, OK, LicenseStatus.VALID, "ok")
            ),
            activate_use_case=FakeUseCase(ok),
            deactivate_use_case=FakeUseCase(gone),
            scheduler=FakeScheduler(),
            event_publisher=publisher,
            thread_manager=thread_manager or ImmediateThreadManager(),
            callback_bridge=QueuedCallbackBridge(),
            logger=logging.getLogger("test"),
        )
        publisher.orchestrator = orchestrator
        self.addCleanup(orchestrator.cleanup)
        return orchestrator, log

    def test_a_completion_callback_may_start_the_next_operation(self):
        for first in ("activate", "deactivate"):
            with self.subTest(first=first):
                orchestrator, _log = self._build()
                inner = []

                def record(success, message):
                    inner.append((success, message))

                def start_the_other(_success, _message):
                    if first == "activate":
                        orchestrator.deactivate_license_async(record)
                    else:
                        orchestrator.activate_license_async("KEY", record)

                if first == "activate":
                    orchestrator.activate_license_async("KEY", start_the_other)
                    expected = (True, "deactivated")
                else:
                    orchestrator.deactivate_license_async(start_the_other)
                    expected = (True, "activated")
                self.assertEqual(inner, [expected])
                self.assertIs(orchestrator._operation_in_progress, False)

    def test_the_outcome_is_published_before_the_completion_callback_runs(self):
        for operation, event in (("activate", "activated"), ("deactivate", "lost")):
            with self.subTest(operation=operation):
                orchestrator, log = self._build()
                callback = lambda success, message: log.append(("callback", success))
                if operation == "activate":
                    orchestrator.activate_license_async("KEY", callback)
                else:
                    orchestrator.deactivate_license_async(callback)
                self.assertEqual([entry[0] for entry in log], [event, "callback"])

    def test_a_failed_operation_publishes_nothing_before_its_callback(self):
        orchestrator, log = self._build(
            deactivate_result=self._result(
                False, LicenseOperationStatus.NETWORK_ERROR, None, "offline"
            )
        )
        orchestrator.deactivate_license_async(
            lambda success, message: log.append(("callback", success, message))
        )
        self.assertEqual(log, [("callback", False, "offline")])

    def test_initialize_shows_grace_to_subscribers_before_the_server_has_answered(self):
        model = FakeModel()
        model.offline = True
        model.valid = True
        manager = _PendingThreadManager()
        orchestrator, log = self._build(model=model, thread_manager=manager)
        orchestrator.initialize()
        self.assertEqual(log, [("activated", True)])
        self.assertEqual(orchestrator._current_license_status, LicenseStatus.GRACE)
        self.assertEqual(len(manager.pending), 1)
        operation, on_main = manager.pending[0]
        on_main(*operation())
        self.assertEqual(orchestrator._current_license_status, LicenseStatus.VALID)
        self.assertEqual(log, [("activated", True), ("activated", True)])

    def test_initialize_without_a_license_clears_a_stale_status_before_reporting_the_loss(
        self,
    ):
        model = FakeModel()
        model.license_key = None
        model.valid = True
        orchestrator, log = self._build(model=model)
        orchestrator._current_license_status = LicenseStatus.VALID
        orchestrator.initialize()
        self.assertEqual(log, [("lost", False)])
        self.assertIsNone(orchestrator._current_license_status)

    def test_a_hardware_failure_updates_the_state_before_the_invalidation_is_published(
        self,
    ):
        for operation in ("initialize", "activate"):
            with self.subTest(operation=operation):
                model = FakeModel()
                model.valid = True
                model.hwid_error = HardwareIdentityError("firmware unavailable")
                orchestrator, log = self._build(model=model)
                orchestrator._current_license_status = LicenseStatus.VALID
                with self.assertLogs("test", level="ERROR"):
                    if operation == "initialize":
                        orchestrator.initialize()
                    else:
                        orchestrator.activate_license_async(
                            "KEY", lambda success, message: None
                        )
                self.assertEqual(log, [("invalidated", False, False, True)])
                self.assertEqual(
                    orchestrator._current_license_status, LicenseStatus.HWID_UNAVAILABLE
                )


class LicenseOrchestratorStartupCallbackOrderingTests(unittest.TestCase):
    def test_the_startup_validation_callback_runs_after_the_outcome_is_published(self):
        log = []
        publisher = _ObservingPublisher(log)
        orchestrator = LicenseOrchestrator(
            license_model=FakeModel(),
            validate_use_case=FakeUseCase(
                LicenseOperationResultDto(
                    success=True,
                    operation_status=OK,
                    license_status=LicenseStatus.VALID,
                    message="ok",
                )
            ),
            activate_use_case=FakeUseCase(None),
            deactivate_use_case=FakeUseCase(None),
            scheduler=FakeScheduler(),
            event_publisher=publisher,
            thread_manager=ImmediateThreadManager(),
            callback_bridge=QueuedCallbackBridge(),
            logger=logging.getLogger("test"),
        )
        publisher.orchestrator = orchestrator
        self.addCleanup(orchestrator.cleanup)
        orchestrator._current_license_status = LicenseStatus.VALID
        orchestrator._model.valid = True
        orchestrator._startup_validate_license_async(
            lambda success, message: log.append(("callback", success, message))
        )
        self.assertEqual(log, [("activated", True), ("callback", True, "ok")])


class LicenseOrchestratorInterruptPolicyTests(unittest.TestCase):
    """Interrupt policy (KeyboardInterrupt or SystemExit): reset or release what the operation held, log any secondary
    error and re-raise the ORIGINAL interrupt; never swallow it, never let a cleanup error replace it. Ordinary
    exceptions keep their existing handling (see LicenseOrchestratorFailurePolicyTests).
    """

    INTERRUPTS = (KeyboardInterrupt, SystemExit)
    _build_orchestrator = LicenseActivationContractTests._build_orchestrator
    _result = staticmethod(LicenseActivationContractTests._result)

    class _SpawnInterruptedOnce(ImmediateThreadManager):
        def __init__(self, interrupt):
            self.interrupt = interrupt
            self.spawns = 0

        def spawn_with_bridge(
            self, operation, callback_bridge, on_main_thread, error_prefix
        ):
            self.spawns += 1
            if self.spawns == 1:
                raise self.interrupt
            super().spawn_with_bridge(
                operation, callback_bridge, on_main_thread, error_prefix
            )

    def _orchestrator(self, **kwargs):
        valid = self._result(True, OK, LicenseStatus.VALID, "done")
        use_case = FakeUseCase(valid)
        orchestrator = self._build_orchestrator(
            use_case,
            use_case,
            FakeEventPublisher(),
            deactivate=use_case,
            **kwargs,
        )
        return orchestrator, use_case

    def test_an_interrupt_while_starting_an_operation_does_not_leave_license_operations_busy(
        self,
    ):
        for kind in self.INTERRUPTS:
            for operation in ("activate", "deactivate"):
                with self.subTest(interrupt=kind.__name__, operation=operation):
                    interrupt = kind("spawn interrupted")
                    manager = self._SpawnInterruptedOnce(interrupt)
                    orchestrator, use_case = self._orchestrator(thread_manager=manager)
                    outcomes = []

                    def submit():
                        callback = lambda success, message: outcomes.append(
                            (success, message)
                        )
                        if operation == "activate":
                            orchestrator.activate_license_async("KEY", callback)
                        else:
                            orchestrator.deactivate_license_async(callback)

                    with self.assertRaises(kind) as raised:
                        submit()
                    self.assertIs(raised.exception, interrupt)
                    self.assertIs(orchestrator._operation_in_progress, False)
                    self.assertEqual(outcomes, [])
                    submit()
                    self.assertEqual(outcomes, [(True, "done")])
                    self.assertEqual(manager.spawns, 2)
                    self.assertEqual(len(use_case.calls), 1)

    def _failing_cleanup_orchestrator(self, calls, stop=None, clear=None, workers=None):
        orchestrator, _use_case = self._orchestrator()

        def step(name, error):
            def run():
                calls.append(name)
                if error is not None:
                    raise error

            return run

        scheduler = FakeScheduler()
        scheduler.stop = step("stop", stop)
        scheduler.clear_task = step("clear_task", clear)
        manager = ImmediateThreadManager()
        manager.cleanup = step("thread_cleanup", workers)
        orchestrator._scheduler = scheduler
        orchestrator._thread_manager = manager
        return orchestrator

    def _assert_released_and_retry_is_a_noop(self, orchestrator, calls):
        for attribute in (
            "_callback_bridge",
            "_event_publisher",
            "_scheduler",
            "_thread_manager",
        ):
            self.assertIsNone(getattr(orchestrator, attribute))
        self.assertIs(orchestrator._closed, True)
        before = list(calls)
        orchestrator.cleanup()
        self.assertEqual(calls, before)

    def test_an_interrupt_in_any_cleanup_stage_still_runs_the_other_stages_and_releases_every_reference(
        self,
    ):
        for kind in self.INTERRUPTS:
            for stage in ("stop", "clear", "workers"):
                with self.subTest(interrupt=kind.__name__, stage=stage):
                    calls = []
                    interrupt = kind(f"{stage} interrupted")
                    orchestrator = self._failing_cleanup_orchestrator(
                        calls,
                        stop=interrupt if stage == "stop" else None,
                        clear=interrupt if stage == "clear" else None,
                        workers=interrupt if stage == "workers" else None,
                    )
                    with self.assertNoLogs("test"):
                        with self.assertRaises(kind) as raised:
                            orchestrator.cleanup()
                    self.assertIs(raised.exception, interrupt)
                    self.assertEqual(calls, ["stop", "clear_task", "thread_cleanup"])
                    self._assert_released_and_retry_is_a_noop(orchestrator, calls)

    def test_ordinary_cleanup_errors_around_an_interrupt_are_logged_and_never_replace_it(
        self,
    ):
        calls = []
        interrupt = KeyboardInterrupt("original")
        orchestrator = self._failing_cleanup_orchestrator(
            calls,
            stop=RuntimeError("stop failed"),
            clear=interrupt,
            workers=ValueError("workers failed"),
        )
        with self.assertLogs("test", level="ERROR") as logs:
            with self.assertRaises(KeyboardInterrupt) as raised:
                orchestrator.cleanup()
        self.assertIs(raised.exception, interrupt)
        self.assertEqual(calls, ["stop", "clear_task", "thread_cleanup"])
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Error in license orchestrator cleanup;"
                " the original KeyboardInterrupt is re-raised: stop failed",
                "Error in license orchestrator cleanup;"
                " the original KeyboardInterrupt is re-raised: workers failed",
            ],
        )
        self.assertEqual(
            [type(record.exc_info[1]) for record in logs.records],
            [RuntimeError, ValueError],
        )
        self._assert_released_and_retry_is_a_noop(orchestrator, calls)

    def test_a_second_interrupt_during_cleanup_is_logged_and_the_first_one_is_re_raised(
        self,
    ):
        for stage, label in (
            ("clear", "scheduler clear_task"),
            ("workers", "thread manager cleanup"),
        ):
            with self.subTest(stage=stage):
                calls = []
                first = KeyboardInterrupt("first")
                second = SystemExit(2)
                orchestrator = self._failing_cleanup_orchestrator(
                    calls,
                    stop=first,
                    clear=second if stage == "clear" else None,
                    workers=second if stage == "workers" else None,
                )
                with self.assertLogs("test", level="ERROR") as logs:
                    with self.assertRaises(KeyboardInterrupt) as raised:
                        orchestrator.cleanup()
                self.assertIs(raised.exception, first)
                self.assertEqual(calls, ["stop", "clear_task", "thread_cleanup"])
                self.assertEqual(
                    [record.getMessage() for record in logs.records],
                    [
                        f"SystemExit during license orchestrator cleanup ({label})"
                        " after KeyboardInterrupt;"
                        " the original KeyboardInterrupt is re-raised"
                    ],
                )
                self.assertIs(logs.records[0].exc_info[1], second)
                self._assert_released_and_retry_is_a_noop(orchestrator, calls)

    def test_without_an_interrupt_cleanup_errors_are_still_raised_and_not_logged(self):
        calls = []
        orchestrator = self._failing_cleanup_orchestrator(
            calls, stop=RuntimeError("stop failed"), workers=ValueError("workers")
        )
        with self.assertNoLogs("test"):
            with self.assertRaises(ExceptionGroup) as raised:
                orchestrator.cleanup()
        self.assertEqual(
            [str(error) for error in raised.exception.exceptions],
            ["stop failed", "workers"],
        )
        self.assertEqual(calls, ["stop", "clear_task", "thread_cleanup"])
