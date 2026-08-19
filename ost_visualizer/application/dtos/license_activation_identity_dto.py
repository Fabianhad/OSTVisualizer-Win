from dataclasses import dataclass
from enum import Enum

LICENSE_ACTIVATION_IDENTITY_VERSION = "v1"
LICENSE_ACTIVATION_IDENTITY_PAYLOAD_FIELD = "activation_identity"
_MAX_WINDOWS_ACCOUNT_LENGTH = 512
_MAX_COMPUTER_NAME_LENGTH = 255
_MAX_JOIN_NAME_LENGTH = 255


class LicenseActivationIdentityError(RuntimeError):
    """The current Windows activation identity could not be obtained."""


class WindowsJoinType(str, Enum):
    UNJOINED = "unjoined"
    WORKGROUP = "workgroup"
    DOMAIN = "domain"


@dataclass(frozen=True)
class LicenseActivationIdentityDto:
    version: str
    windows_account: str
    computer_name: str
    join_type: WindowsJoinType
    join_name: str

    def __post_init__(self) -> None:
        if self.version != LICENSE_ACTIVATION_IDENTITY_VERSION:
            raise ValueError("Invalid license activation identity version")
        _validate_required_value(
            self.windows_account,
            _MAX_WINDOWS_ACCOUNT_LENGTH,
            "Windows account",
        )
        _validate_required_value(
            self.computer_name,
            _MAX_COMPUTER_NAME_LENGTH,
            "computer name",
        )
        if not isinstance(self.join_type, WindowsJoinType):
            raise ValueError("Invalid Windows join type")
        if self.join_type == WindowsJoinType.UNJOINED:
            if self.join_name:
                raise ValueError("An unjoined computer cannot have a join name")
        else:
            _validate_required_value(
                self.join_name,
                _MAX_JOIN_NAME_LENGTH,
                "Windows join name",
            )

    def to_payload(self) -> dict[str, str]:
        return {
            "version": self.version,
            "windows_account": self.windows_account,
            "computer_name": self.computer_name,
            "join_type": self.join_type.value,
            "join_name": self.join_name,
        }


def _validate_required_value(value: str, maximum_length: int, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"Invalid {label}")
    if len(value) > maximum_length or any(ord(character) < 32 for character in value):
        raise ValueError(f"Invalid {label}")
