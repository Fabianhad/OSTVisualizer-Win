from typing import Any, Dict, Optional, Protocol, Tuple, runtime_checkable


@runtime_checkable
class ILicenseApiClient(Protocol):
    def validate(
        self, license_key: str, hwid: Optional[str]
    ) -> Tuple[bool, Optional[Dict[str, Any]]]: ...
    def activate(
        self, license_key: str, hwid: Optional[str]
    ) -> Tuple[bool, Optional[Dict[str, Any]]]: ...
    def deactivate(
        self, license_key: str, hwid: Optional[str]
    ) -> Tuple[bool, Optional[Dict[str, Any]]]: ...
    def check_version(self) -> Tuple[bool, Optional[Dict[str, Any]]]: ...
