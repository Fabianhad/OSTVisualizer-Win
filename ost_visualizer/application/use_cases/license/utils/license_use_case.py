from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional, Tuple
from .....config.license_config import MAX_HWID_LENGTH, MAX_LICENSE_KEY_LENGTH
from .....domain.entities.license import LicenseStatus
from .....domain.services.hardware_identity import is_canonical_hwid
from ....dtos.license_dto import LicenseOperationResultDto, LicenseOperationStatus
from .....shared.texts import (
    LICENSE_USE_CASE_MESSAGE_LICENSE_ACTIVATION_LIMIT_REACHED_THIS_LICENSE,
    LICENSE_USE_CASE_MESSAGE_LICENSE_DEACTIVATED_SUCCESSFULLY,
    LICENSE_USE_CASE_MESSAGE_LICENSE_KEY_NOT_FOUND_PLEASE_CHECK,
    LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_REJECTED_THE_WINDOWS,
    LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_REJECTED_THIS_COMPUTER,
    LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_RETURNED_AN_INVALID,
    LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_RETURNED_AN_INVALID_2,
    LICENSE_USE_CASE_MESSAGE_THIS_DEVICE_IS_NOT_CURRENTLY_ACTIVATED,
    LICENSE_USE_CASE_MESSAGE_THIS_LICENSE_HAS_BEEN_REVOKED_PLEASE,
    LICENSE_USE_CASE_MESSAGE_THIS_LICENSE_HAS_EXPIRED_AND_CANNOT,
    LICENSE_USE_CASE_MESSAGE_THIS_LICENSE_KEY_HAS_EXPIRED_PLEASE,
)

LicenseOperation = Literal["activate", "deactivate", "validate"]
ERROR_LICENSE_NOT_FOUND = "LICENSE_NOT_FOUND"
ERROR_LICENSE_EXPIRED = "LICENSE_EXPIRED"
ERROR_LICENSE_REVOKED = "LICENSE_REVOKED"
ERROR_MAX_ACTIVATIONS_REACHED = "MAX_ACTIVATIONS_REACHED"
ERROR_INVALID_HWID = "INVALID_HWID"
ERROR_DEVICE_ACTIVATION_INACTIVE = "DEVICE_ACTIVATION_INACTIVE"
ERROR_INVALID_ACTIVATION_IDENTITY = "INVALID_ACTIVATION_IDENTITY"
ERROR_CONTRACT = {
    ERROR_LICENSE_NOT_FOUND: 1001,
    ERROR_LICENSE_EXPIRED: 1002,
    ERROR_LICENSE_REVOKED: 1003,
    ERROR_MAX_ACTIVATIONS_REACHED: 1005,
    ERROR_INVALID_HWID: 1006,
    ERROR_DEVICE_ACTIVATION_INACTIVE: 1007,
    ERROR_INVALID_ACTIVATION_IDENTITY: 1008,
}


@dataclass(frozen=True)
class SignedLicenseResponse:
    expiry_date_text: str
    expiry_date: datetime
    signature: str


@dataclass(frozen=True)
class LicenseFailureResponse:
    result: LicenseOperationResultDto
    server_message: str
    error_code: Optional[int]


def clean_license_key(license_key: Optional[str]) -> Optional[str]:
    if license_key is None:
        return None
    cleaned = license_key.strip()
    if not cleaned or len(cleaned) > MAX_LICENSE_KEY_LENGTH:
        return None
    return cleaned


def clean_hwid(hwid: Optional[str]) -> Optional[str]:
    if hwid is None:
        return None
    cleaned = hwid.strip()
    if not cleaned or len(cleaned) > MAX_HWID_LENGTH or not is_canonical_hwid(cleaned):
        return None
    return cleaned


def parse_expiry_date(expiry_date_str: Optional[str]) -> Optional[datetime]:
    if not expiry_date_str:
        return None
    try:
        expiry_date = datetime.fromisoformat(expiry_date_str)
    except (TypeError, ValueError):
        return None
    if expiry_date.tzinfo is None:
        expiry_date = expiry_date.replace(tzinfo=timezone.utc)
    return expiry_date


def build_success_result(
    expiry_date: datetime,
    success_message_prefix: str,
) -> LicenseOperationResultDto:
    message = f"{success_message_prefix} until {expiry_date.strftime('%Y-%m-%d')}"
    return LicenseOperationResultDto(
        success=True,
        operation_status=LicenseOperationStatus.SUCCESS,
        license_status=LicenseStatus.VALID,
        message=message,
    )


def map_error(
    error_name: str,
    operation: LicenseOperation = "activate",
) -> Tuple[LicenseOperationStatus, LicenseStatus, str]:
    if error_name == ERROR_LICENSE_NOT_FOUND:
        return (
            LicenseOperationStatus.INVALID_KEY,
            LicenseStatus.INVALID,
            LICENSE_USE_CASE_MESSAGE_LICENSE_KEY_NOT_FOUND_PLEASE_CHECK,
        )
    elif error_name == ERROR_LICENSE_EXPIRED:
        return (
            LicenseOperationStatus.EXPIRED,
            LicenseStatus.EXPIRED if operation == "validate" else LicenseStatus.INVALID,
            (
                LICENSE_USE_CASE_MESSAGE_THIS_LICENSE_KEY_HAS_EXPIRED_PLEASE
                if operation in ("activate", "validate")
                else LICENSE_USE_CASE_MESSAGE_THIS_LICENSE_HAS_EXPIRED_AND_CANNOT
            ),
        )
    elif error_name == ERROR_LICENSE_REVOKED:
        return (
            LicenseOperationStatus.REVOKED,
            LicenseStatus.INVALID,
            LICENSE_USE_CASE_MESSAGE_THIS_LICENSE_HAS_BEEN_REVOKED_PLEASE,
        )
    elif error_name == ERROR_MAX_ACTIVATIONS_REACHED:
        return (
            LicenseOperationStatus.ACTIVATION_LIMIT_REACHED,
            LicenseStatus.INVALID,
            LICENSE_USE_CASE_MESSAGE_LICENSE_ACTIVATION_LIMIT_REACHED_THIS_LICENSE,
        )
    elif error_name == ERROR_DEVICE_ACTIVATION_INACTIVE:
        return (
            LicenseOperationStatus.DEVICE_ACTIVATION_INACTIVE,
            LicenseStatus.INVALID,
            LICENSE_USE_CASE_MESSAGE_THIS_DEVICE_IS_NOT_CURRENTLY_ACTIVATED,
        )
    elif error_name == ERROR_INVALID_HWID:
        return (
            LicenseOperationStatus.FAILED,
            LicenseStatus.INVALID,
            (LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_REJECTED_THIS_COMPUTER),
        )
    elif error_name == ERROR_INVALID_ACTIVATION_IDENTITY:
        return (
            LicenseOperationStatus.FAILED,
            LicenseStatus.INVALID,
            (LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_REJECTED_THE_WINDOWS),
        )
    raise ValueError(f"Unknown license error contract: {error_name}")


def parse_signed_success_response(
    response: dict,
    *,
    success_field: Literal["success", "valid"],
    operation: Literal["activate", "validate"],
) -> tuple[Optional[SignedLicenseResponse], Optional[LicenseOperationResultDto]]:
    marker = response.get(success_field)
    if marker is False:
        return None, None
    if marker is not True:
        return None, create_server_contract_error(operation)
    expiry_date_text = _required_string(response, "expiry_date")
    signature = _required_string(response, "signature")
    if not expiry_date_text or not signature:
        return None, create_server_contract_error(operation)
    expiry_date = parse_expiry_date(expiry_date_text)
    if not expiry_date:
        return None, create_error_result(
            operation_status=LicenseOperationStatus.NETWORK_ERROR,
            message=LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_RETURNED_AN_INVALID_2,
            license_status=_server_error_license_status(operation),
        )
    return (
        SignedLicenseResponse(
            expiry_date_text=expiry_date_text,
            expiry_date=expiry_date,
            signature=signature,
        ),
        None,
    )


def parse_deactivate_success_response(
    response: dict,
) -> tuple[Optional[str], Optional[LicenseOperationResultDto]]:
    marker = response.get("success")
    if marker is False:
        return None, None
    if marker is not True:
        return None, create_server_contract_error("deactivate")
    return (
        _required_string(response, "message")
        or LICENSE_USE_CASE_MESSAGE_LICENSE_DEACTIVATED_SUCCESSFULLY,
        None,
    )


def parse_failure_response(
    response: Optional[dict],
    *,
    operation: LicenseOperation,
    network_message: str,
    network_license_status: LicenseStatus = LicenseStatus.INVALID,
) -> LicenseFailureResponse:
    if response is None:
        return LicenseFailureResponse(
            result=create_error_result(
                operation_status=LicenseOperationStatus.NETWORK_ERROR,
                message=network_message,
                license_status=network_license_status,
            ),
            server_message="Network error",
            error_code=None,
        )
    expected_marker = "valid" if operation == "validate" else "success"
    if response.get(expected_marker) is not False:
        contract_result = create_server_contract_error(operation)
        return LicenseFailureResponse(
            result=contract_result,
            server_message=contract_result.message,
            error_code=None,
        )
    error_name = _required_string(response, "error_name")
    error_code = response.get("error_code")
    if (
        not error_name
        or error_name not in ERROR_CONTRACT
        or type(error_code) is not int
        or ERROR_CONTRACT[error_name] != error_code
    ):
        contract_result = create_server_contract_error(operation)
        return LicenseFailureResponse(
            result=contract_result,
            server_message=contract_result.message,
            error_code=error_code if type(error_code) is int else None,
        )
    server_message = _required_string(response, "error") or (
        f"{operation.capitalize()} failed"
    )
    operation_status, license_status, user_message = map_error(
        error_name, operation=operation
    )
    return LicenseFailureResponse(
        result=create_error_result(
            operation_status=operation_status,
            message=user_message,
            license_status=license_status,
            error_code=error_code,
        ),
        server_message=server_message,
        error_code=error_code,
    )


def create_server_contract_error(
    operation: LicenseOperation,
) -> LicenseOperationResultDto:
    return create_error_result(
        operation_status=LicenseOperationStatus.NETWORK_ERROR,
        message=LICENSE_USE_CASE_MESSAGE_THE_LICENSE_SERVER_RETURNED_AN_INVALID,
        license_status=_server_error_license_status(operation),
    )


def create_error_result(
    operation_status: LicenseOperationStatus,
    message: str,
    license_status: Optional[LicenseStatus] = None,
    error_code: Optional[int] = None,
) -> LicenseOperationResultDto:
    return LicenseOperationResultDto(
        success=False,
        operation_status=operation_status,
        license_status=license_status or LicenseStatus.INVALID,
        message=message,
        error_code=error_code,
    )


def _required_string(response: dict, field_name: str) -> str:
    value = response.get(field_name)
    return value.strip() if isinstance(value, str) else ""


def _server_error_license_status(operation: LicenseOperation) -> LicenseStatus:
    return (
        LicenseStatus.NETWORK_ERROR
        if operation == "validate"
        else LicenseStatus.INVALID
    )
