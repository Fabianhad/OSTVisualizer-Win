import logging
import uuid
from pathlib import Path
from typing import Callable, Optional, Protocol
from ...domain.services.hardware_identity import (
    HardwareIdentityError,
    HardwareIdentitySource,
    MachineIdentity,
    build_hwid,
)
from ..app_paths import get_machine_app_data_dir
from ..persistence.repositories.json_machine_identity_repository import (
    JsonMachineIdentityRepository,
)
from .smbios_system_uuid import SmbiosSystemUuidReader

_MACHINE_IDENTITY_FILENAME = "hardware_identity_v1.json"


class ISystemUuidReader(Protocol):
    def read_system_uuid(self) -> Optional[uuid.UUID]: ...
class IMachineIdentityRepository(Protocol):
    def load(self) -> Optional[MachineIdentity]: ...
    def create_if_absent(self, identity: MachineIdentity) -> MachineIdentity: ...
class HWIDGenerator:
    def __init__(
        self,
        identity_path: Optional[Path] = None,
        system_uuid_reader: Optional[ISystemUuidReader] = None,
        identity_factory: Callable[[], uuid.UUID] = uuid.uuid4,
        identity_repository: Optional[IMachineIdentityRepository] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if identity_path is not None and identity_repository is not None:
            raise ValueError(
                "Specify either an identity path or an identity repository, not both"
            )
        self._identity_path = identity_path
        self._system_uuid_reader = system_uuid_reader
        self._identity_factory = identity_factory
        self._identity_repository = identity_repository
        self._cached_hwid: Optional[str] = None
        self._logger = logger or logging.getLogger(__name__)

    def get_hwid(self) -> str:
        if self._cached_hwid is not None:
            return self._cached_hwid
        try:
            repository = self._get_repository()
            identity = repository.load()
            if identity is None:
                candidate = self._create_identity()
                identity = repository.create_if_absent(candidate)
                if identity != candidate:
                    self._verify_pinned_identity(identity)
            else:
                self._verify_pinned_identity(identity)
            self._cached_hwid = build_hwid(identity)
            return self._cached_hwid
        except HardwareIdentityError:
            raise
        except (OSError, ValueError) as exc:
            raise HardwareIdentityError(
                "The pinned machine identity is unavailable or invalid"
            ) from exc

    def _create_identity(self) -> MachineIdentity:
        system_uuid = self._get_system_uuid_reader().read_system_uuid()
        if system_uuid is not None:
            return MachineIdentity.create(
                HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
                system_uuid,
            )
        installation_uuid = self._identity_factory()
        return MachineIdentity.create(
            HardwareIdentitySource.INSTALLATION_UUID,
            installation_uuid,
        )

    def _verify_pinned_identity(self, identity: MachineIdentity) -> None:
        if identity.source == HardwareIdentitySource.INSTALLATION_UUID:
            return
        observed_uuid = self._get_system_uuid_reader().read_system_uuid()
        if observed_uuid is None:
            raise HardwareIdentityError(
                "The pinned SMBIOS System UUID is temporarily unavailable"
            )
        if str(observed_uuid).upper() != identity.identifier:
            raise HardwareIdentityError(
                "The SMBIOS System UUID does not match the pinned machine identity"
            )

    def _get_repository(self) -> IMachineIdentityRepository:
        if self._identity_repository is None:
            identity_path = self._identity_path
            if identity_path is None:
                identity_path = get_machine_app_data_dir() / _MACHINE_IDENTITY_FILENAME
            self._identity_repository = JsonMachineIdentityRepository(
                identity_path,
                logger=self._logger.getChild("MachineIdentityRepository"),
            )
        return self._identity_repository

    def _get_system_uuid_reader(self) -> ISystemUuidReader:
        if self._system_uuid_reader is None:
            self._system_uuid_reader = SmbiosSystemUuidReader()
        return self._system_uuid_reader
