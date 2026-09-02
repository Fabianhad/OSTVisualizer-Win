import logging
from typing import Any, Callable, Optional
from ...domain.aggregates.license_aggregate import LicenseAggregate
from ...domain.entities.license import LicenseStatus
from ...domain.entities.license_info import LicenseInfo
from ...domain.services.hardware_identity import HardwareIdentityError
from ..dtos.license_dto import LicenseOperationResultDto, LicenseOperationStatus
from ..dtos.license_view_model_dto import LicenseViewModelDto
from ..interfaces.i_license_validation_scheduler import ILicenseValidationScheduler
from ..interfaces.i_thread_callback_bridge import IThreadCallbackBridge
from ..use_cases.license.activate_license_use_case import ActivateLicenseUseCase
from ..use_cases.license.deactivate_license_use_case import DeactivateLicenseUseCase
from ..use_cases.license.validate_license_use_case import ValidateLicenseUseCase
from .license_event_publisher import LicenseEventPublisher
from .license_thread_manager import LicenseThreadManager


class LicenseOrchestrator:
    def __init__(
        self,
        license_model: LicenseAggregate,
        validate_use_case: ValidateLicenseUseCase,
        activate_use_case: ActivateLicenseUseCase,
        deactivate_use_case: DeactivateLicenseUseCase,
        scheduler: ILicenseValidationScheduler,
        event_publisher: LicenseEventPublisher,
        thread_manager: LicenseThreadManager,
        callback_bridge: IThreadCallbackBridge,
        logger: logging.Logger,
    ) -> None:
        self._model = license_model
        self._validate_use_case = validate_use_case
        self._activate_use_case = activate_use_case
        self._deactivate_use_case = deactivate_use_case
        self._scheduler = scheduler
        self._event_publisher = event_publisher
        self._thread_manager = thread_manager
        self._callback_bridge = callback_bridge
        self._logger = logger
        self._current_license_status: Optional[LicenseStatus] = None
        self._status_message: Optional[str] = None
        self._operation_in_progress: bool = False
        self._closed = False

    def initialize(self) -> None:
        if self._scheduler.is_running():
            return
        self._scheduler.set_task(self._perform_periodic_validation)
        try:
            self._model.clear_if_invalid()
            self._ensure_hwid()
        except HardwareIdentityError as exc:
            self._handle_hwid_failure(exc)
            self._scheduler.start()
            return
        if self._model.has_license():
            if self._model.can_use_offline_grace():
                self._current_license_status = LicenseStatus.GRACE
                self._event_publisher.publish_activated()
            self._startup_validate_license_async(lambda _success, _msg: None)
        else:
            self._current_license_status = None
            self._event_publisher.publish_license_lost()
        self._scheduler.start()

    def cleanup(self) -> None:
        if self._closed:
            return
        self._closed = True
        errors = []
        cleanup_steps = (
            self._scheduler.stop,
            self._scheduler.clear_task,
            self._thread_manager.cleanup,
        )
        for cleanup in cleanup_steps:
            try:
                cleanup()
            except Exception as exc:
                errors.append(exc)
        self._callback_bridge = None
        self._event_publisher = None
        self._scheduler = None
        self._thread_manager = None
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise ExceptionGroup("License orchestrator cleanup failed", errors)

    def activate_license_async(
        self, license_key: str, callback: Callable[[bool, str], None]
    ) -> None:
        if self._operation_in_progress:
            callback(False, "Another license operation is in progress")
            return
        try:
            self._ensure_hwid()
        except HardwareIdentityError as exc:
            callback(False, self._handle_hwid_failure(exc))
            return
        self._operation_in_progress = True

        def operation() -> tuple[bool, str, Any]:
            result = self._activate_use_case.execute(license_key)
            if result.success:
                self._apply_result(result)
            return result.success, result.message, result.success

        def on_main(_s: bool, message: str, activation_success: bool) -> None:
            self._operation_in_progress = False
            if activation_success:
                self._event_publisher.publish_activated()
            callback(activation_success, message)

        self._thread_manager.spawn_with_bridge(
            operation=operation,
            callback_bridge=self._callback_bridge,
            on_main_thread=on_main,
            error_prefix="activation",
        )

    def deactivate_license_async(self, callback: Callable[[bool, str], None]) -> None:
        if self._operation_in_progress:
            callback(False, "Another license operation is in progress")
            return
        self._operation_in_progress = True

        def operation() -> tuple[bool, str, bool]:
            result = self._deactivate_use_case.execute()
            if (
                result.success
                or result.operation_status == LicenseOperationStatus.NO_LICENSE
            ):
                self._apply_result(result)
            return result.success, result.message, result.success

        def on_main(_s: bool, message: str, deactivation_success: bool) -> None:
            self._operation_in_progress = False
            if deactivation_success:
                self._event_publisher.publish_license_lost()
            callback(deactivation_success, message)

        self._thread_manager.spawn_with_bridge(
            operation=operation,
            callback_bridge=self._callback_bridge,
            on_main_thread=on_main,
            error_prefix="deactivation",
        )

    def _startup_validate_license_async(
        self, callback: Callable[[bool, str], None]
    ) -> None:
        self._ensure_hwid()

        def operation() -> tuple[bool, str, Optional[LicenseStatus]]:
            result = self._validate_use_case.execute()
            result = self._reactivate_once_if_device_activation_inactive(result)
            self._apply_result(result)
            return result.success, result.message, result.license_status

        def on_main(
            _s: bool, message: str, license_status: Optional[LicenseStatus]
        ) -> None:
            self._publish_validation_outcome(_s, message, license_status)
            callback(_s, message)

        self._thread_manager.spawn_with_bridge(
            operation=operation,
            callback_bridge=self._callback_bridge,
            on_main_thread=on_main,
            error_prefix="startup license validation",
        )

    def _reactivate_once_if_device_activation_inactive(
        self, result: LicenseOperationResultDto
    ) -> LicenseOperationResultDto:
        if result.operation_status != LicenseOperationStatus.DEVICE_ACTIVATION_INACTIVE:
            return result
        license_key = self._model.license_key
        if not license_key:
            return result
        return self._activate_use_case.execute(license_key)

    def has_valid_license(self) -> bool:
        if self._current_license_status == LicenseStatus.VALID:
            return self._model.has_valid_license()
        if self._current_license_status == LicenseStatus.GRACE:
            return self._model.can_use_offline_grace()
        return False

    def get_license_info(self) -> LicenseInfo:
        return LicenseInfo(
            has_license=self.has_valid_license(),
            status=(
                self._current_license_status.value
                if self._current_license_status
                else "no_license"
            ),
            expiry_date=(
                self._model.expiry_date.isoformat() if self._model.expiry_date else None
            ),
            license_key=self._model.license_key,
        )

    def get_view_model(self) -> LicenseViewModelDto:
        info = self.get_license_info()
        return LicenseViewModelDto(
            has_license=info.has_license,
            status=info.status or "No active license",
            expiry_date=info.expiry_date,
            license_key=info.license_key,
            message=self._status_message,
            hardware_identity_available=(
                self._current_license_status != LicenseStatus.HWID_UNAVAILABLE
            ),
        )

    def _ensure_hwid(self) -> None:
        self._model.ensure_hwid()

    def _perform_periodic_validation(self) -> Optional[LicenseOperationResultDto]:
        if self._closed:
            return None
        if not self._model.has_license():
            return None
        try:
            self._model.require_canonical_hwid()
        except HardwareIdentityError as exc:
            message = self._hardware_identity_failure_message(exc)
            result = LicenseOperationResultDto(
                success=False,
                operation_status=LicenseOperationStatus.HWID_UNAVAILABLE,
                license_status=LicenseStatus.HWID_UNAVAILABLE,
                message=message,
            )
            self._apply_result(result)
            callback_bridge = self._callback_bridge
            if callback_bridge is not None:
                callback_bridge.dispatch(
                    self._publish_periodic_validation_outcome,
                    (result.success, result.message, result.license_status),
                )
            return result
        result = self._validate_use_case.execute()
        self._apply_result(result)
        callback_bridge = self._callback_bridge
        if callback_bridge is not None:
            callback_bridge.dispatch(
                self._publish_periodic_validation_outcome,
                (result.success, result.message, result.license_status),
            )
        return result

    def _publish_periodic_validation_outcome(
        self, outcome: tuple[bool, str, Optional[LicenseStatus]]
    ) -> None:
        if self._closed:
            return
        success, message, license_status = outcome
        self._publish_validation_outcome(success, message, license_status)

    def _publish_validation_outcome(
        self,
        success: bool,
        message: str,
        license_status: Optional[LicenseStatus],
    ) -> None:
        if self._closed:
            return
        if success or (
            license_status == LicenseStatus.NETWORK_ERROR and self.has_valid_license()
        ):
            self._event_publisher.publish_activated()
        elif license_status in (
            LicenseStatus.INVALID,
            LicenseStatus.EXPIRED,
            LicenseStatus.NETWORK_ERROR,
            LicenseStatus.HWID_UNAVAILABLE,
        ):
            self._event_publisher.publish_invalidated(message, license_status)

    def _apply_result(self, result: LicenseOperationResultDto) -> None:
        self._status_message = (
            result.message
            if result.license_status == LicenseStatus.HWID_UNAVAILABLE
            else None
        )
        if result.license_status:
            if (
                result.license_status == LicenseStatus.NETWORK_ERROR
                and self._model.can_use_offline_grace()
            ):
                self._logger.warning(
                    "License server unavailable; using cached license within %s-hour offline grace",
                    self._model.offline_grace_hours,
                )
                self._current_license_status = LicenseStatus.GRACE
            else:
                self._current_license_status = result.license_status
        elif result.operation_status == LicenseOperationStatus.NO_LICENSE:
            self._current_license_status = None
        elif result.operation_status == LicenseOperationStatus.SUCCESS:
            self._current_license_status = LicenseStatus.VALID
        else:
            self._current_license_status = LicenseStatus.INVALID

    def _handle_hwid_failure(self, exc: HardwareIdentityError) -> str:
        message = self._hardware_identity_failure_message(exc)
        self._current_license_status = LicenseStatus.HWID_UNAVAILABLE
        self._status_message = message
        self._event_publisher.publish_invalidated(
            message,
            LicenseStatus.HWID_UNAVAILABLE,
        )
        return message

    def _hardware_identity_failure_message(self, exc: HardwareIdentityError) -> str:
        message = (
            "This computer's hardware identity is unavailable. "
            "Restart Windows and try again; if the problem continues, contact support."
        )
        self._logger.error("Hardware identity validation failed: %s", exc)
        return message
