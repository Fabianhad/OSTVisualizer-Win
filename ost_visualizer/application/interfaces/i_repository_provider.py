from typing import Callable, Optional, Protocol
from .i_mdb_connection_manager import IMdbConnectionManager
from ...domain.repositories.i_config_repository import IConfigRepository
from ...domain.repositories.i_file_state_repository import IFileStateRepository
from ...domain.repositories.i_license_repository import ILicenseRepository
from ...domain.repositories.i_license_signature_verifier import (
    ILicenseSignatureVerifier,
)
from ...domain.repositories.i_project_repository import IProjectRepository
from ...domain.repositories.i_workspace_state_repository import (
    IWorkspaceStateRepository,
)


class IRepositoryProvider(Protocol):
    def get_config_repository(self) -> IConfigRepository: ...
    def get_file_state_repository(self) -> IFileStateRepository: ...
    def get_workspace_state_repository(self) -> IWorkspaceStateRepository: ...
    def get_license_repository(self) -> ILicenseRepository: ...
    def get_license_signature_verifier(self) -> ILicenseSignatureVerifier: ...
    def get_project_repository(
        self, conn_manager: Optional[IMdbConnectionManager] = None
    ) -> IProjectRepository: ...
    def get_hwid_provider(self) -> Callable[[], str]: ...
