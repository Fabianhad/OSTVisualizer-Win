from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Optional


class LicenseStatus(Enum):
    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"
    NO_LICENSE = "no_license"
    NETWORK_ERROR = "network_error"
    GRACE = "grace"
    HWID_UNAVAILABLE = "hwid_unavailable"


class LicenseValidationResult(Enum):
    VALID = auto()
    NO_LICENSE = auto()
    EXPIRED = auto()
    HWID_MISMATCH = auto()
    HWID_VERSION_MISMATCH = auto()
    SIGNATURE_INVALID = auto()


@dataclass
class License:
    license_key: Optional[str] = None
    expiry_date: Optional[datetime] = None
    signature: Optional[str] = None
    hwid: Optional[str] = None
    hwid_version: Optional[str] = None
    last_validated: Optional[datetime] = None
    signed_expiry_date: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "license_key": self.license_key,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "signature": self.signature,
            "hwid": self.hwid,
            "hwid_version": self.hwid_version,
            "last_validated": (
                self.last_validated.isoformat() if self.last_validated else None
            ),
            "signed_expiry_date": self.signed_expiry_date,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> License:
        if not data:
            return cls()
        if not isinstance(data, dict):
            raise ValueError("Invalid license cache: expected JSON object")
        cls._require_current_cache_fields(data)
        expiry_date = cls._parse_iso_datetime(data.get("expiry_date"))
        last_validated = cls._parse_iso_datetime(data.get("last_validated"))
        if expiry_date is None:
            raise ValueError("Invalid license cache: invalid expiry_date")
        if last_validated is None:
            raise ValueError("Invalid license cache: invalid last_validated")
        return cls(
            license_key=data.get("license_key"),
            expiry_date=expiry_date,
            signature=data.get("signature"),
            hwid=data.get("hwid"),
            hwid_version=data.get("hwid_version"),
            last_validated=last_validated,
            signed_expiry_date=data.get("signed_expiry_date"),
        )

    @staticmethod
    def _require_current_cache_fields(data: dict) -> None:
        required_fields = (
            "license_key",
            "expiry_date",
            "signature",
            "hwid",
            "hwid_version",
            "last_validated",
            "signed_expiry_date",
        )
        missing_fields = [
            field for field in required_fields if not str(data.get(field) or "").strip()
        ]
        if missing_fields:
            raise ValueError(
                "Invalid license cache: missing required fields "
                + ", ".join(missing_fields)
            )

    @staticmethod
    def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    def is_expired(self, reference_time: Optional[datetime] = None) -> bool:
        if not self.expiry_date:
            return True
        reference = reference_time or datetime.now(timezone.utc)
        expiry = self.expiry_date
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        return reference > expiry
