import logging
from pathlib import Path
from typing import Any, Callable, List, Optional
from ..domain.entities.database_descriptor import DatabaseBackend
from ..domain.entities.file_state import FileEntry, normalize_path
from .builders.annotation_view_builder import AnnotationViewBuilder
from .builders.model_builder import ModelBuilder
from .builders.orchestrator_builder import AppOrchestrators, OrchestratorBuilder
from .builders.service_builder import ServiceBuilder
from .builders.use_case_builder import UseCaseBuilder
from .events.app_events import AppEvents
from .interfaces.i_annotation_view_manager import IAnnotationViewManager
from .interfaces.i_api_client_provider import IApiClientProvider
from .interfaces.i_event_bus import IEventBus
from .interfaces.i_infrastructure_service_provider import (
    IInfrastructureServiceProvider,
)
from .interfaces.i_mdb_connection_manager import IMdbConnectionManager
from .interfaces.i_repository_provider import IRepositoryProvider
from .interfaces.i_thread_scene_notifier import IThreadSceneNotifier
from .service_container import ServiceContainer
from .services.project_operations_service import ProjectOperationsService
from .services.project_read_service import ProjectReadService
from .use_cases.project.import_project_files_from_args_use_case import (
    ImportProjectFilesFromArgsUseCase,
)
from ..domain.repositories.i_annotation_view_repository import (
    IAnnotationViewRepository,
)


class AppController:
    def __init__(
        self,
        container: ServiceContainer,
        event_bus: IEventBus,
        logger: logging.Logger,
        orchestrators: AppOrchestrators,
        project_data_service,
        file_loading_service,
        load_files_from_config_use_case,
        working_directory_service,
        file_state_model,
        database_descriptor_registry=None,
        cleanup_hooks: Optional[List[Callable[[], None]]] = None,
    ):
        self.container = container
        self.event_bus = event_bus
        self.logger = logger
        self.orchestrators = orchestrators
        self._project_data_service = project_data_service
        self._file_loading_service = file_loading_service
        self._load_files_from_config_use_case = load_files_from_config_use_case
        self._working_directory_service = working_directory_service
        self._file_state_model = file_state_model
        self._database_descriptor_registry = database_descriptor_registry
        self._cleanup_hooks: List[Callable[[], None]] = list(cleanup_hooks or [])
        self._subscriptions = []
        self._cleaned_up = False

    def get_service(self, name: str) -> Any:
        return self.container.get(name)

    def get_selected_page_uids(self) -> List[str]:
        return self._project_data_service.get_selected_page_uids()

    def unload_file(self, file_path: Optional[str] = None) -> bool:
        if not self._project_data_service.get_current_file_path():
            return False
        target_path = file_path or self._project_data_service.get_current_file_path()
        current_bid_file_path = self._project_data_service.get_current_bid_file_path()
        current_file_path = self._project_data_service.get_current_file_path()
        active_context_path = current_bid_file_path or current_file_path
        active_context_removed = bool(
            target_path and active_context_path
        ) and normalize_path(target_path) == normalize_path(active_context_path)
        try:
            self.orchestrators.visualization.close_realtime_visualization()
            result = self._file_loading_service.unload_file(file_path)
            if result.success:
                self.event_bus.publish(
                    AppEvents.FILE_UNLOADED,
                    file_path=target_path or "",
                    active_context_removed=active_context_removed,
                )
                return True
            self.logger.error("Failed to unload file: %s", result.error_message)
            return False
        except Exception as exc:
            self.logger.exception("Error unloading file: %s", exc)
            return False

    def load_files_from_config(self) -> List[str]:
        try:
            self._auto_discover_databases()
            if self._database_descriptor_registry is not None:
                self._database_descriptor_registry.register_all(
                    entry.descriptor for entry in self._file_state_model.file_entries
                )
            loaded = self._load_files_from_config_use_case.execute()
            capability_service = self.container.get("database_capability_service")
            loaded_set = set(loaded)
            for entry in self._file_state_model.file_entries:
                if entry.runtime_locator not in loaded_set:
                    continue
                capability_service.mark_connected(entry.database_id)
            return loaded
        except Exception as exc:
            self.logger.exception("Error loading files from config: %s", exc)
            return []

    def _auto_discover_databases(self) -> None:
        try:
            self._file_state_model.reload()
            merged = self._working_directory_service.merge_discovered_into_file_state(
                self._file_state_model.file_entries
            )
            if len(merged) != len(self._file_state_model.file_entries):
                self._file_state_model.update_entries(merged)
        except Exception as exc:
            self.logger.warning("Auto-discovery failed: %s", exc)

    def has_any_databases(self) -> bool:
        try:
            return any(
                entry.is_checked
                and (
                    entry.backend == DatabaseBackend.SQL_SERVER
                    or Path(entry.file_path).exists()
                )
                for entry in self._file_state_model.file_entries
            )
        except OSError:
            return False

    def create_new_database(
        self,
        name: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        try:
            db_path = self._working_directory_service.create_database(
                name,
                progress_callback=progress_callback,
            )
            if db_path is None:
                return None
            db_str = str(db_path)
            entry = FileEntry(file_path=db_str, is_checked=True)
            if not self._file_state_model.contains_path(db_str):
                entries = list(self._file_state_model.file_entries)
                entries.append(entry)
                self._file_state_model.update_entries(entries)
            if self._database_descriptor_registry is not None:
                self._database_descriptor_registry.register(entry.descriptor)
            return db_str
        except Exception as exc:
            self.logger.exception("Error creating database: %s", exc)
            return None

    def subscribe_to_event(self, event_name: str, callback) -> None:
        self.event_bus.subscribe(event_name, callback)
        self._subscriptions.append((event_name, callback))

    def cleanup(self) -> None:
        if self._cleaned_up:
            return
        self._cleaned_up = True
        for event_name, callback in self._subscriptions:
            self.event_bus.unsubscribe(event_name, callback)
        self._subscriptions.clear()
        if self.orchestrators is not None:
            self.orchestrators.visualization.cleanup()
            self.orchestrators.license.cleanup()
        for hook in self._cleanup_hooks:
            try:
                hook()
            except Exception:
                self.logger.exception("Cleanup hook failed")
        self._cleanup_hooks.clear()
        self._project_data_service = None
        self._file_loading_service = None
        self._load_files_from_config_use_case = None
        self._working_directory_service = None
        self._file_state_model = None
        self._database_descriptor_registry = None
        self.orchestrators = None
        self.event_bus = None
        if self.container is not None:
            self.container.clear()
        self.container = None


class AppControllerBuilder:
    def __init__(
        self,
        container: ServiceContainer,
        logger: logging.Logger,
        repository_provider: IRepositoryProvider,
        infrastructure_provider: IInfrastructureServiceProvider,
        api_client_provider: IApiClientProvider,
        view_manager_factory: Callable[..., IAnnotationViewManager],
        repository_factory: Callable[[], IAnnotationViewRepository],
        event_bus_factory: Callable[[], IEventBus],
        scene_notifier: IThreadSceneNotifier,
        ost_signaler=None,
    ):
        self.container = container
        self.logger = logger
        self.repository_provider = repository_provider
        self.infrastructure_provider = infrastructure_provider
        self.api_client_provider = api_client_provider
        self.view_manager_factory = view_manager_factory
        self.repository_factory = repository_factory
        self.event_bus_factory = event_bus_factory
        self.scene_notifier = scene_notifier
        self.ost_signaler = ost_signaler

    def build(self) -> AppController:
        event_bus = self.event_bus_factory()
        self.container.register_instance("event_bus", event_bus)
        self.container.register_instance(
            "infrastructure_provider", self.infrastructure_provider
        )
        shared_conn_manager = self.infrastructure_provider.create_connection_manager()
        self.container.register_instance("connection_manager", shared_conn_manager)
        self._setup_models(shared_conn_manager)
        self._setup_use_cases(shared_conn_manager, event_bus)
        license_model = self.container.get("license_model")
        validate_uc = self.container.get("validate_license_use_case")
        activate_uc = self.container.get("activate_license_use_case")
        deactivate_uc = self.container.get("deactivate_license_use_case")
        orchestrators = OrchestratorBuilder(
            self.container,
            event_bus,
            self.logger,
            self.infrastructure_provider,
        ).build(
            license_model=license_model,
            validate_use_case=validate_uc,
            activate_use_case=activate_uc,
            deactivate_use_case=deactivate_uc,
        )
        self._setup_services(event_bus, shared_conn_manager)
        visualization_service = self.container.get("visualization_service")
        orchestrators.visualization.set_visualization_service(visualization_service)
        cleanup_hooks: List[Callable[[], None]] = []
        if shared_conn_manager is not None:
            cleanup_hooks.append(shared_conn_manager.close)
        controller = AppController(
            container=self.container,
            event_bus=event_bus,
            logger=self.logger,
            orchestrators=orchestrators,
            project_data_service=self.container.get("project_data_service"),
            file_loading_service=self.container.get("file_loading_service"),
            load_files_from_config_use_case=self.container.get(
                "load_files_from_config_use_case"
            ),
            working_directory_service=self.container.get("working_directory_service"),
            file_state_model=self.container.get("file_state_model"),
            database_descriptor_registry=(
                self.infrastructure_provider.get_database_descriptor_registry()
            ),
            cleanup_hooks=cleanup_hooks,
        )
        orchestrators.lifecycle.set_app_controller(controller)
        self._setup_event_subscriptions(controller)
        self.container.register_instance("app_controller", controller)
        return controller

    def _setup_models(self, conn_manager: IMdbConnectionManager) -> None:
        ModelBuilder(
            self.container, self.logger, self.repository_provider, conn_manager
        ).build()

    def _setup_use_cases(
        self,
        conn_manager: IMdbConnectionManager,
        event_bus: IEventBus,
    ) -> None:
        mdb_reader = self.infrastructure_provider.get_mdb_reader(
            conn_manager=conn_manager
        )
        self.container.register_instance("mdb_reader", mdb_reader)
        project_read_service = ProjectReadService(
            mdb_reader, self.logger.getChild("ProjectReadService")
        )
        self.container.register_instance("project_read_service", project_read_service)
        mdb_writer = self.infrastructure_provider.get_mdb_writer(
            conn_manager=conn_manager
        )
        self.container.register_instance("mdb_writer", mdb_writer)
        ost_model = self.container.get("ost_model")
        project_data_service = self.container.get("project_data_service")
        file_state_model = self.container.get("file_state_model")
        license_model = self.container.get("license_model")
        UseCaseBuilder(self.container, self.logger, self.api_client_provider).build(
            ost_model=ost_model,
            project_data_service=project_data_service,
            file_state_model=file_state_model,
            mdb_writer=mdb_writer,
            event_bus=event_bus,
            license_model=license_model,
            connection_manager=conn_manager,
        )

    def _setup_services(
        self,
        event_bus: IEventBus,
        connection_manager: IMdbConnectionManager,
    ) -> None:
        project_data_service = self.container.get("project_data_service")
        operations_logger = self.logger.getChild("ProjectOperationsService")
        project_operations_service = ProjectOperationsService(
            project_data_service,
            logger=operations_logger,
        )
        self.container.register_instance(
            "project_operations_service", project_operations_service
        )
        load_file_use_case = self.container.get("load_file_use_case")
        unload_file_use_case = self.container.get("unload_file_use_case")
        load_bid_use_case = self.container.get("load_bid_use_case")
        reload_database_use_case = self.container.get("reload_database_use_case")
        project_operations_service.configure_use_cases(
            load_file_use_case,
            unload_file_use_case.execute,
            load_bid_use_case.execute,
            reload_database_use_case.execute,
        )
        license_api_client = self.container.get("license_api_client")
        ServiceBuilder(
            self.container,
            self.logger,
            self.infrastructure_provider,
            self.scene_notifier,
            self.ost_signaler,
        ).build(
            config_model=self.container.get("config_model"),
            project_data_service=project_data_service,
            project_operations_service=project_operations_service,
            event_bus=event_bus,
            connection_manager=connection_manager,
            license_api_client=license_api_client,
        )
        self.container.register_instance(
            "import_project_files_from_args_use_case",
            ImportProjectFilesFromArgsUseCase(
                import_service=self.container.get("import_service"),
                project_data_service=project_data_service,
                file_state_model=self.container.get("file_state_model"),
                workspace_state_model=self.container.get("workspace_state_model"),
                logger=self.logger.getChild("ImportProjectFilesFromArgs"),
            ),
        )
        AnnotationViewBuilder(
            self.container,
            event_bus=self.container.get("event_bus"),
            view_manager_factory=self.view_manager_factory,
            repository_factory=self.repository_factory,
            logger=self.logger.getChild("AnnotationViewBuilder"),
        ).build()

    def _setup_event_subscriptions(self, controller: AppController) -> None:
        lifecycle_orchestrator = self.container.get("lifecycle_orchestrator")
        callback = lifecycle_orchestrator.handle_license_expired
        controller.subscribe_to_event(AppEvents.LICENSE_EXPIRED, callback)
