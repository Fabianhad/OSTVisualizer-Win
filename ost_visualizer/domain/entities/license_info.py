from dataclasses import dataclass
from typing import Optional


@dataclass
class LicenseInfo:
    has_license: bool
    status: str
    expiry_date: Optional[str] = None
    license_key: Optional[str] = None
