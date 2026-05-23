from dataclasses import dataclass
from enum import Enum
from typing import Optional
from ...domain.entities.license import LicenseStatus


class LicenseOperationStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    NETWORK_ERROR = "network_error"
    INVALID_KEY = "invalid_key"
    EXPIRED = "expired"
    ACTIVATION_LIMIT_REACHED = "activation_limit_reached"
    REVOKED = "revoked"
    NO_LICENSE = "no_license"


@dataclass
class LicenseOperationResultDto:
    success: bool
    operation_status: LicenseOperationStatus
    message: str
    license_status: Optional[LicenseStatus] = None
    error_code: Optional[int] = None
