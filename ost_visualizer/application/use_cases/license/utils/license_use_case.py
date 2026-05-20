from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional, Tuple
from .....config.license_config import MAX_HWID_LENGTH, MAX_LICENSE_KEY_LENGTH
from .....domain.entities.license import LicenseStatus
from ....dtos.license_dto import LicenseOperationResultDto, LicenseOperationStatus

LicenseOperation = Literal["activate", "deactivate", "validate"]


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
    if not cleaned or len(cleaned) > MAX_HWID_LENGTH:
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
    error_code: Optional[int],
    error_message: str,
    operation: LicenseOperation = "activate",
) -> Tuple[LicenseOperationStatus, LicenseStatus, str]:
    default_status = LicenseOperationStatus.FAILED
    default_license_status = LicenseStatus.INVALID
    default_message = f"{operation.capitalize()} failed. {error_message}"
    if error_code == 1001:
        return (
            LicenseOperationStatus.INVALID_KEY,
            LicenseStatus.INVALID,
            "License key not found. Please check the key and try again, or contact support.",
        )
    elif error_code == 1002:
        return (
            LicenseOperationStatus.EXPIRED,
            LicenseStatus.EXPIRED if operation == "validate" else LicenseStatus.INVALID,
            (
                "This license key has expired. Please contact support to renew your license."
                if operation in ("activate", "validate")
                else "This license has expired and cannot be deactivated. Please contact support for assistance."
            ),
        )
    elif error_code == 1003:
        return (
            LicenseOperationStatus.REVOKED,
            LicenseStatus.INVALID,
            "This license has been revoked. Please contact support for more information.",
        )
    elif error_code == 1005:
        return (
            LicenseOperationStatus.ACTIVATION_LIMIT_REACHED,
            LicenseStatus.INVALID,
            "License activation limit reached. This license is active on the maximum number of devices.",
        )
    return (default_status, default_license_status, default_message)


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
            message="The license server returned an invalid expiry date.",
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
        _required_string(response, "message") or "License deactivated successfully.",
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
    error_code = response.get("error_code")
    server_message = _required_string(response, "error") or (
        f"{operation.capitalize()} failed"
    )
    operation_status, license_status, user_message = map_error(
        error_code, server_message, operation=operation
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
        message="The license server returned an invalid response. Please contact support.",
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
