import logging
from typing import Optional
from ....domain.aggregates.license_aggregate import LicenseAggregate
from ....domain.repositories.i_license_api_client import ILicenseApiClient
from ....domain.services.hardware_identity import HWID_VERSION
from ...dtos.license_activation_identity_dto import LicenseActivationIdentityError
from ...dtos.license_dto import LicenseOperationResultDto, LicenseOperationStatus
from .utils.license_use_case import (
    build_success_result,
    clean_hwid,
    clean_license_key,
    create_error_result,
    parse_failure_response,
    parse_signed_success_response,
)
from ....shared.texts import (
    ACTIVATE_LICENSE_USE_CASE_MESSAGE_ACTIVATION_SUCCEEDED_BUT_THE_LICENSE_COULD,
    ACTIVATE_LICENSE_USE_CASE_MESSAGE_CANNOT_CONNECT_TO_LICENSE_SERVER_PLEASE,
    ACTIVATE_LICENSE_USE_CASE_MESSAGE_LICENSE_ACTIVATED_VALID_UNTIL,
    ACTIVATE_LICENSE_USE_CASE_MESSAGE_LICENSE_KEY_IS_MISSING_OR_TOO,
    ACTIVATE_LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_RESPONSE_COULD_NOT,
    ACTIVATE_LICENSE_USE_CASE_MESSAGE_UNABLE_TO_DETERMINE_THIS_COMPUTER_S,
    ACTIVATE_LICENSE_USE_CASE_MESSAGE_UNABLE_TO_IDENTIFY_THE_CURRENT_WINDOWS,
)


class ActivateLicenseUseCase:
    def __init__(
        self,
        model: LicenseAggregate,
        api_client: ILicenseApiClient,
        logger: Optional[logging.Logger] = None,
    ):
        self.model = model
        self.api_client = api_client
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, license_key: str) -> LicenseOperationResultDto:
        cleaned_key = clean_license_key(license_key)
        if not cleaned_key:
            return create_error_result(
                operation_status=LicenseOperationStatus.INVALID_KEY,
                message=ACTIVATE_LICENSE_USE_CASE_MESSAGE_LICENSE_KEY_IS_MISSING_OR_TOO,
            )
        hwid = clean_hwid(self.model.hwid)
        if not hwid:
            return create_error_result(
                operation_status=LicenseOperationStatus.FAILED,
                message=ACTIVATE_LICENSE_USE_CASE_MESSAGE_UNABLE_TO_DETERMINE_THIS_COMPUTER_S,
            )
        try:
            success, response = self.api_client.activate(cleaned_key, hwid)
        except LicenseActivationIdentityError as exc:
            self.logger.error("License activation identity unavailable: %s", exc)
            return create_error_result(
                operation_status=LicenseOperationStatus.FAILED,
                message=(
                    ACTIVATE_LICENSE_USE_CASE_MESSAGE_UNABLE_TO_IDENTIFY_THE_CURRENT_WINDOWS
                ),
            )
        if success and response is not None:
            signed_response, contract_error = parse_signed_success_response(
                response, success_field="success", operation="activate"
            )
            if contract_error:
                self.logger.warning("License activation response contract failed")
                return contract_error
            if signed_response is None:
                return self._failure_result(response)
            if not self.model.verify_response_signature(
                cleaned_key,
                signed_response.expiry_date_text,
                hwid,
                signed_response.signature,
            ):
                self.logger.warning(
                    "License activation response signature verification failed"
                )
                return create_error_result(
                    operation_status=LicenseOperationStatus.FAILED,
                    message=ACTIVATE_LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_RESPONSE_COULD_NOT,
                )
            try:
                self.model.update(
                    license_key=cleaned_key,
                    expiry_date=signed_response.expiry_date,
                    signature=signed_response.signature,
                    hwid=hwid,
                    hwid_version=HWID_VERSION,
                    signed_expiry_date=signed_response.expiry_date_text,
                )
            except (OSError, ValueError) as exc:
                self.logger.error(
                    "License activation local verification failed: %s", exc
                )
                return create_error_result(
                    operation_status=LicenseOperationStatus.FAILED,
                    message=(
                        ACTIVATE_LICENSE_USE_CASE_MESSAGE_ACTIVATION_SUCCEEDED_BUT_THE_LICENSE_COULD
                    ),
                )
            return build_success_result(
                expiry_date=signed_response.expiry_date,
                success_message=ACTIVATE_LICENSE_USE_CASE_MESSAGE_LICENSE_ACTIVATED_VALID_UNTIL,
            )
        return self._failure_result(response)

    def _failure_result(self, response: Optional[dict]) -> LicenseOperationResultDto:
        failure = parse_failure_response(
            response,
            operation="activate",
            network_message=(
                ACTIVATE_LICENSE_USE_CASE_MESSAGE_CANNOT_CONNECT_TO_LICENSE_SERVER_PLEASE
            ),
        )
        self.logger.warning(
            "License activation failed: %s (code: %s)",
            failure.server_message,
            failure.error_code,
        )
        return failure.result
