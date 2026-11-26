from dataclasses import dataclass
from typing import Optional
from ...shared.texts import LICENSE_VIEW_MODEL_DTO_LABEL_NO_ACTIVE_LICENSE


@dataclass
class LicenseViewModelDto:
    has_license: bool
    status: str = LICENSE_VIEW_MODEL_DTO_LABEL_NO_ACTIVE_LICENSE
    expiry_date: Optional[str] = None
    license_key: Optional[str] = None
    message: Optional[str] = None
    hardware_identity_available: bool = True
