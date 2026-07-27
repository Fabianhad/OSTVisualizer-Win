import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from ...config.license_config import LICENSE_OFFLINE_GRACE_HOURS
from ..entities.license import License, LicenseValidationResult
from ..repositories.i_license_repository import ILicenseRepository
from ..repositories.i_license_signature_verifier import ILicenseSignatureVerifier


class LicenseAggregate:
    def __init__(
        self,
        repository: ILicenseRepository,
        hwid_provider: Callable[[], str],
        signature_verifier: Optional[ILicenseSignatureVerifier] = None,
        offline_grace_hours: int = LICENSE_OFFLINE_GRACE_HOURS,
        logger: Optional[logging.Logger] = None,
    ):
        self.logger = logger or logging.getLogger(__name__)
        self.repository = repository
        self.hwid_provider = hwid_provider
        self.signature_verifier = signature_verifier
        self.offline_grace_hours = offline_grace_hours
        self._license = License()
        self.load()

    def load(self) -> None:
        try:
            license_data = self.repository.load()
            self._license = license_data
        except FileNotFoundError:
            self._license = License()
        except ValueError as exc:
            self.logger.error("%s; clearing license cache", exc)
            self._license = License()
            self._safe_clear()
        except OSError as exc:
            self.logger.error("Error reading license cache: %s", exc)
            self._license = License()

    def save(self) -> None:
        try:
            self.repository.save(self._license)
        except OSError as exc:
            self.logger.exception("Error saving license: %s", exc)
            raise

    def clear(self) -> None:
        self._license = License()
        self._safe_clear()

    def update(
        self,
        license_key: str,
        expiry_date: datetime,
        signature: Optional[str],
        hwid: str,
        signed_expiry_date: str,
    ) -> None:
        previous_license = self._license
        self._license = License(
            license_key=license_key,
            expiry_date=expiry_date,
            signature=signature,
            hwid=hwid,
            last_validated=datetime.now(timezone.utc),
            signed_expiry_date=signed_expiry_date,
        )
        try:
            self.save()
            self.load()
            validation_result = self.validate()
            if validation_result != LicenseValidationResult.VALID:
                raise ValueError(
                    "Saved license cache failed validation: "
                    f"{validation_result.name.lower()}"
                )
        except (OSError, ValueError):
            self._license = previous_license
            self._restore_previous_cache(previous_license)
            raise

    @property
    def license_key(self) -> Optional[str]:
        return self._license.license_key

    @property
    def expiry_date(self) -> Optional[datetime]:
        return self._license.expiry_date

    @property
    def signature(self) -> Optional[str]:
        return self._license.signature

    @property
    def hwid(self) -> Optional[str]:
        return self._license.hwid

    def ensure_hwid(self) -> Optional[str]:
        if self._license.hwid:
            return self._license.hwid
        hwid = self.hwid_provider()
        self._license.hwid = hwid
        return hwid

    @property
    def last_validated(self) -> Optional[datetime]:
        return self._license.last_validated

    def has_license(self) -> bool:
        return bool(self._license.license_key)

    def is_expired(self, reference_time: Optional[datetime] = None) -> bool:
        return self._license.is_expired(reference_time)

    def validate(self) -> LicenseValidationResult:
        if not self.has_license():
            return LicenseValidationResult.NO_LICENSE
        if self.is_expired():
            return LicenseValidationResult.EXPIRED
        if not self.has_valid_cached_signature():
            return LicenseValidationResult.SIGNATURE_INVALID
        if not self._matches_current_hwid():
            return LicenseValidationResult.HWID_MISMATCH
        return LicenseValidationResult.VALID

    def has_valid_license(self) -> bool:
        return self.validate() == LicenseValidationResult.VALID

    def can_use_offline_grace(self) -> bool:
        if not self.has_license():
            return False
        if self.is_expired():
            return False
        if not self.has_valid_cached_signature():
            return False
        if not self._matches_current_hwid():
            return False
        if not self._license.last_validated:
            return False
        last_validated = self._normalize_datetime(self._license.last_validated)
        if last_validated is None:
            return False
        age = datetime.now(timezone.utc) - last_validated
        return timedelta(0) <= age <= timedelta(hours=self.offline_grace_hours)

    def has_valid_cached_signature(self) -> bool:
        if not self.signature_verifier:
            self.logger.warning("No license signature verifier configured")
            return False
        return self.signature_verifier.verify_license_payload(
            self.get_signature_payload(),
            self._license.signature,
        )

    def verify_response_signature(
        self,
        license_key: str,
        expiry_date: str,
        hwid: str,
        signature: Optional[str],
    ) -> bool:
        if not self.signature_verifier:
            self.logger.warning("No license signature verifier configured")
            return False
        return self.signature_verifier.verify_license_payload(
            {
                "license_key": license_key,
                "expiry_date": expiry_date,
                "hwid": hwid,
            },
            signature,
        )

    def get_signature_payload(self) -> dict:
        return {
            "license_key": self._license.license_key or "",
            "expiry_date": self._license.signed_expiry_date or "",
            "hwid": self._license.hwid or "",
        }

    def clear_if_invalid(self) -> bool:
        result = self.validate()
        if result == LicenseValidationResult.HWID_MISMATCH:
            self.logger.warning(
                "HWID mismatch detected. Clearing invalid cached license."
            )
            self.clear()
            return True
        return False

    def _safe_clear(self) -> None:
        try:
            self.repository.clear()
        except FileNotFoundError:
            pass
        except OSError as exc:
            self.logger.warning("Unable to clear license cache: %s", exc)

    def _restore_previous_cache(self, previous_license: License) -> None:
        try:
            if previous_license.license_key:
                self.repository.save(previous_license)
            else:
                self.repository.clear()
        except OSError as exc:
            self.logger.warning(
                "Unable to restore previous license cache after failed update: %s",
                exc,
            )

    def _matches_current_hwid(self) -> bool:
        stored_hwid = self._license.hwid
        return bool(stored_hwid) and stored_hwid == self.hwid_provider()

    @staticmethod
    def _normalize_datetime(value: datetime) -> Optional[datetime]:
        if not value:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
