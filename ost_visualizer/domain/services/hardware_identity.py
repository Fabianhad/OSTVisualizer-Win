import hashlib
import re
import uuid
from dataclasses import dataclass
from enum import Enum

HWID_VERSION = "v1"
HWID_DIGEST_LENGTH = 64
HWID_EXTERNAL_LENGTH = len(HWID_VERSION) + 1 + HWID_DIGEST_LENGTH
_HWID_PATTERN = re.compile(rf"{HWID_VERSION}:[0-9A-F]{{{HWID_DIGEST_LENGTH}}}")
_HASH_CONTEXT = "OST_VISUALIZER_HWID"
_GENERIC_UUIDS = {
    uuid.UUID("00000000-0000-0000-0000-000000000000"),
    uuid.UUID("FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF"),
    uuid.UUID("00010203-0405-0607-0809-0A0B0C0D0E0F"),
    uuid.UUID("03000200-0400-0500-0006-000700080009"),
    uuid.UUID("DEADBEEF-DEAD-BEEF-DEAD-BEEFDEADBEEF"),
}


class HardwareIdentityError(RuntimeError):
    """The pinned machine identity could not be established or verified."""


class HardwareIdentitySource(str, Enum):
    SMBIOS_SYSTEM_UUID = "smbios_system_uuid"
    INSTALLATION_UUID = "installation_uuid"


@dataclass(frozen=True)
class MachineIdentity:
    version: str
    source: HardwareIdentitySource
    identifier: str

    def __post_init__(self) -> None:
        if self.version != HWID_VERSION:
            raise ValueError("Invalid machine identity version")
        if not isinstance(self.source, HardwareIdentitySource):
            raise ValueError("Invalid machine identity source")
        if not isinstance(self.identifier, str):
            raise ValueError("Invalid machine identity UUID")
        try:
            identifier = uuid.UUID(self.identifier)
        except ValueError as exc:
            raise ValueError("Invalid machine identity UUID") from exc
        if self.identifier != str(identifier).upper() or not is_usable_identity_uuid(
            identifier
        ):
            raise ValueError("Invalid machine identity UUID")

    @classmethod
    def create(
        cls,
        source: HardwareIdentitySource,
        identifier: uuid.UUID,
    ) -> "MachineIdentity":
        return cls(
            version=HWID_VERSION,
            source=source,
            identifier=str(identifier).upper(),
        )

    @classmethod
    def from_dict(cls, data: dict) -> "MachineIdentity":
        if not isinstance(data, dict):
            raise ValueError("Invalid machine identity: expected JSON object")
        try:
            source = HardwareIdentitySource(data.get("source"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid machine identity source") from exc
        return cls(data.get("version"), source, data.get("identifier"))

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "source": self.source.value,
            "identifier": self.identifier,
        }


def is_usable_identity_uuid(identifier: uuid.UUID) -> bool:
    return identifier not in _GENERIC_UUIDS


def build_hwid(identity: MachineIdentity) -> str:
    material = (
        f"{_HASH_CONTEXT}|{HWID_VERSION}|{identity.source.value}|"
        f"{identity.identifier}"
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest().upper()
    return f"{HWID_VERSION}:{digest}"


def is_canonical_hwid(value: str) -> bool:
    return bool(_HWID_PATTERN.fullmatch(value))
