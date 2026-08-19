import logging
import os
from pathlib import Path
from typing import Optional
from ....domain.services.hardware_identity import MachineIdentity
from .json_repository_base import JsonRepositoryBase


class JsonMachineIdentityRepository(JsonRepositoryBase):
    def __init__(
        self,
        identity_path: Path,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        super().__init__(identity_path, "machine identity", logger)
        self._initialized_marker_path = identity_path.with_name(
            f"{identity_path.name}.initialized"
        )

    def load(self) -> Optional[MachineIdentity]:
        try:
            identity = MachineIdentity.from_dict(self._load_json())
        except FileNotFoundError:
            if self._has_initialized_marker():
                raise OSError("The pinned machine identity record is missing")
            return None
        self._ensure_initialized_marker()
        return identity

    def create_if_absent(self, identity: MachineIdentity) -> MachineIdentity:
        if self._save_json_if_absent(identity.to_dict()):
            self._ensure_initialized_marker()
            return identity
        persisted = self.load()
        if persisted is None:
            raise OSError("Machine identity disappeared during initialization")
        return persisted

    def _ensure_initialized_marker(self) -> None:
        try:
            with self._initialized_marker_path.open("x", encoding="ascii") as handle:
                handle.write("initialized\n")
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            pass

    def _has_initialized_marker(self) -> bool:
        try:
            with self._initialized_marker_path.open("r", encoding="ascii"):
                return True
        except FileNotFoundError:
            return False
