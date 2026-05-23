import logging
from typing import Optional
from ....domain.aggregates.license_aggregate import LicenseAggregate
from ....domain.entities.license import LicenseStatus
from ....domain.repositories.i_license_api_client import ILicenseApiClient
from ...dtos.license_dto import LicenseOperationResultDto, LicenseOperationStatus
from .utils.license_use_case import (
    clean_hwid,
    clean_license_key,
    parse_deactivate_success_response,
    parse_failure_response,
)


class DeactivateLicenseUseCase:
    def __init__(
        self,
        model: LicenseAggregate,
        api_client: ILicenseApiClient,
        logger: Optional[logging.Logger] = None,
    ):
        self.model = model
        self.api_client = api_client
        self.logger = logger or logging.getLogger(__name__)

    def execute(self) -> LicenseOperationResultDto:
        if not self.model.has_license():
            return LicenseOperationResultDto(
                success=True,
                operation_status=LicenseOperationStatus.NO_LICENSE,
                license_status=LicenseStatus.NO_LICENSE,
                message="No active license to deactivate.",
            )
        license_key = clean_license_key(self.model.license_key)
        hwid = clean_hwid(self.model.hwid or self.model.ensure_hwid())
        if not license_key or not hwid:
            return LicenseOperationResultDto(
                success=False,
                operation_status=LicenseOperationStatus.FAILED,
                license_status=LicenseStatus.INVALID,
                message="Stored license data is invalid. Please contact support.",
            )
        success, response = self.api_client.deactivate(license_key, hwid)
        if success and response is not None:
            message, contract_error = parse_deactivate_success_response(response)
            if contract_error:
                self.logger.warning("License deactivation response contract failed")
                return contract_error
            if message is not None:
                self.model.clear()
                return LicenseOperationResultDto(
                    success=True,
                    operation_status=LicenseOperationStatus.SUCCESS,
                    license_status=LicenseStatus.NO_LICENSE,
                    message=message,
                )
            return self._failure_result(response)
        return self._failure_result(response)

    def _failure_result(self, response: Optional[dict]) -> LicenseOperationResultDto:
        failure = parse_failure_response(
            response,
            operation="deactivate",
            network_message=(
                "Cannot contact the license server.\n\n"
                "Please check your internet connection and try again."
            ),
        )
        if response is None:
            self.logger.error("License deactivation failed due to network error")
        else:
            self.logger.warning(
                "License deactivation failed: %s (code: %s)",
                failure.server_message,
                failure.error_code,
            )
        return failure.result
