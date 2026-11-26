import logging
from typing import Optional
from ....domain.aggregates.license_aggregate import LicenseAggregate
from ....domain.entities.license import LicenseStatus
from ....domain.repositories.i_license_api_client import ILicenseApiClient
from ....domain.services.hardware_identity import HWID_VERSION
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
    VALIDATE_LICENSE_USE_CASE_MESSAGE_CANNOT_CONNECT_TO_LICENSE_SERVER_YOUR,
    VALIDATE_LICENSE_USE_CASE_MESSAGE_LICENSE_VALID,
    VALIDATE_LICENSE_USE_CASE_MESSAGE_NO_LICENSE_KEY_PROVIDED,
    VALIDATE_LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_RESPONSE_COULD_NOT,
    VALIDATE_LICENSE_USE_CASE_MESSAGE_THE_LICENSE_WAS_ACCEPTED_BY_THE,
    VALIDATE_LICENSE_USE_CASE_MESSAGE_UNABLE_TO_DETERMINE_THIS_COMPUTER_S,
)


class ValidateLicenseUseCase:
    def __init__(
        self,
        model: LicenseAggregate,
        api_client: ILicenseApiClient,
        logger: Optional[logging.Logger] = None,
    ):
        self.model = model
        self.api_client = api_client
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, license_key: Optional[str] = None) -> LicenseOperationResultDto:
        key_to_use = clean_license_key(license_key or self.model.license_key)
        if not key_to_use:
            return LicenseOperationResultDto(
                success=False,
                operation_status=LicenseOperationStatus.NO_LICENSE,
                license_status=None,
                message=VALIDATE_LICENSE_USE_CASE_MESSAGE_NO_LICENSE_KEY_PROVIDED,
            )
        hwid = clean_hwid(self.model.hwid)
        if not hwid:
            return create_error_result(
                operation_status=LicenseOperationStatus.FAILED,
                message=VALIDATE_LICENSE_USE_CASE_MESSAGE_UNABLE_TO_DETERMINE_THIS_COMPUTER_S,
            )
        success, response = self.api_client.validate(key_to_use, hwid)
        if success and response is not None:
            signed_response, contract_error = parse_signed_success_response(
                response, success_field="valid", operation="validate"
            )
            if contract_error:
                self.logger.warning("License validation response contract failed")
                return contract_error
            if signed_response is None:
                return self._failure_result(response)
            if not self.model.verify_response_signature(
                key_to_use,
                signed_response.expiry_date_text,
                hwid,
                signed_response.signature,
            ):
                self.logger.warning(
                    "License validation response signature verification failed"
                )
                return create_error_result(
                    operation_status=LicenseOperationStatus.FAILED,
                    message=VALIDATE_LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_RESPONSE_COULD_NOT,
                )
            try:
                self.model.update(
                    license_key=key_to_use,
                    expiry_date=signed_response.expiry_date,
                    signature=signed_response.signature,
                    hwid=hwid,
                    hwid_version=HWID_VERSION,
                    signed_expiry_date=signed_response.expiry_date_text,
                )
            except (OSError, ValueError) as exc:
                self.logger.error(
                    "License validation local verification failed: %s", exc
                )
                return create_error_result(
                    operation_status=LicenseOperationStatus.FAILED,
                    message=(
                        VALIDATE_LICENSE_USE_CASE_MESSAGE_THE_LICENSE_WAS_ACCEPTED_BY_THE
                    ),
                )
            return build_success_result(
                expiry_date=signed_response.expiry_date,
                success_message_prefix=VALIDATE_LICENSE_USE_CASE_MESSAGE_LICENSE_VALID,
            )
        return self._failure_result(response)

    def _failure_result(self, response: Optional[dict]) -> LicenseOperationResultDto:
        failure = parse_failure_response(
            response,
            operation="validate",
            network_message=(
                VALIDATE_LICENSE_USE_CASE_MESSAGE_CANNOT_CONNECT_TO_LICENSE_SERVER_YOUR
            ),
            network_license_status=LicenseStatus.NETWORK_ERROR,
        )
        if response is not None:
            self.logger.warning(
                "License validation failed: %s (code: %s)",
                failure.server_message,
                failure.error_code,
            )
        return failure.result
