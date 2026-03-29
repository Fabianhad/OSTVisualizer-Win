from dataclasses import dataclass
from typing import Optional


@dataclass
class LicenseViewModelDto:
    has_license: bool
    status: str = "No active license"
    expiry_date: Optional[str] = None
    license_key: Optional[str] = None
    message: Optional[str] = None
