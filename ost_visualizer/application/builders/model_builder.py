import logging
from ...domain.aggregates.config_aggregate import ConfigAggregate
from ...domain.aggregates.file_state_aggregate import FileStateAggregate
from ...domain.aggregates.license_aggregate import LicenseAggregate
from ...domain.aggregates.ost_aggregate import OstAggregate
from ...domain.aggregates.workspace_state_aggregate import WorkspaceStateAggregate
from ...domain.services.file_manager_service import FileManager
from ...domain.services.project_data_service import ProjectDataService
from ..interfaces.i_repository_provider import IRepositoryProvider
from ..service_container import ServiceContainer


class ModelBuilder:
    def __init__(
        self,
        container: ServiceContainer,
        logger: logging.Logger,
        repository_provider: IRepositoryProvider,
        conn_manager=None,
    ) -> None:
        self.container = container
        self.logger = logger
        self.repository_provider = repository_provider
        self._conn_manager = conn_manager

    def build(self) -> None:
        ost_logger = self.logger.getChild("OstAggregate")
        config_logger = self.logger.getChild("ConfigAggregate")
        file_state_logger = self.logger.getChild("FileStateAggregate")
        license_logger = self.logger.getChild("LicenseAggregate")
        workspace_state_logger = self.logger.getChild("WorkspaceStateAggregate")
        config_repo = self.repository_provider.get_config_repository()
        project_repo = self.repository_provider.get_project_repository(
            conn_manager=self._conn_manager
        )
        file_state_repo = self.repository_provider.get_file_state_repository()
        workspace_state_repo = self.repository_provider.get_workspace_state_repository()
        license_repo = self.repository_provider.get_license_repository()
        file_manager_logger = ost_logger.getChild("FileManager")
        file_manager = FileManager(
            project_repository=project_repo,
            logger=file_manager_logger,
        )
        ost_model = OstAggregate(file_manager=file_manager, logger=ost_logger)
        self.container.register_instance("ost_model", ost_model)
        self.container.register_instance(
            "config_model", ConfigAggregate(config_repo, logger=config_logger)
        )
        self.container.register_instance(
            "file_state_model",
            FileStateAggregate(file_state_repo, logger=file_state_logger),
        )
        self.container.register_instance(
            "workspace_state_model",
            WorkspaceStateAggregate(
                workspace_state_repo, logger=workspace_state_logger
            ),
        )
        hwid_provider = self.repository_provider.get_hwid_provider()
        signature_verifier = self.repository_provider.get_license_signature_verifier()
        self.container.register_instance(
            "license_model",
            LicenseAggregate(
                license_repo,
                hwid_provider=hwid_provider,
                signature_verifier=signature_verifier,
                logger=license_logger,
            ),
        )
        project_data_logger = self.logger.getChild("ProjectDataService")
        project_data_service = ProjectDataService(ost_model, logger=project_data_logger)
        self.container.register_instance("project_data_service", project_data_service)
