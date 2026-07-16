from typing import Optional, Protocol


class ILicenseSignatureVerifier(Protocol):
    def verify_license_payload(
        self,
        payload: dict,
        signature: Optional[str],
    ) -> bool: ...
