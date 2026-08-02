from pathlib import Path
from typing import Optional
from ..application.app_controller import AppControllerBuilder
from ..application.services.database_capability_service import (
    DatabaseCapabilityService,
)
from ..application.services.database_session_registry import DatabaseSessionRegistry
from ..application.services.local_draft_registry import LocalDraftRegistry
from ..application.services.pending_mutation_registry import PendingMutationRegistry
from ..application.services.conflict_resolution_service import (
    ConflictResolutionService,
)
from ..application.services.database_concurrency_token_service import (
    DatabaseConcurrencyTokenService,
)
from ..application.services.remote_change_reconciliation_service import (
    RemoteChangeReconciliationService,
)
from ..application.services.sql_collaboration_coordinator import (
    SqlCollaborationCoordinator,
)
from ..application.service_container import ServiceContainer
from ..infrastructure.app_paths import get_app_data_dir
from ..infrastructure.events.event_bus import EventBus
from ..infrastructure.database.descriptor_registry import DatabaseDescriptorRegistry
from ..infrastructure.logging.logger_factory import LoggerFactory
from ..infrastructure.sql.credential_store import WindowsCredentialStore
from ..infrastructure.sql.collaboration_store import SqlCollaborationStore
from ..infrastructure.sql.connection_manager import SqlConnectionManager
from ..infrastructure.sql.remote_change_reader import SqlRemoteChangeReader
from ..infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ..infrastructure.database.entity_version_reader import (
    DatabaseEntityVersionReader,
)
from ..infrastructure.persistence.repositories.memory_annotation_view_repository import (
    MemoryAnnotationViewRepository,
)
from ..infrastructure.persistence.repositories.json_pending_sql_operation_repository import (
    JsonPendingSqlOperationRepository,
)
from ..infrastructure.providers import (
    ApiClientProvider,
    InfrastructureServiceProvider,
    RepositoryProvider,
)
from ..presentation.managers.annotation_view_manager import QtAnnotationViewManager
from ..presentation.managers.main_hotlink_view_manager import QtMainHotlinkViewManager
from ..presentation.managers.view_window_manager import QtViewWindowManager
from ..presentation.services.qt_scene_notifier import QtSceneNotifier
from ..presentation.utils.qt_callback_bridge import OstSignaler, QtCallbackBridge
from ..presentation.utils.qt_message_notifier import QtMessageNotifier
from ..presentation.utils.qt_window_icon_provider import QtWindowIconProvider


def configure_application(log_dir: Optional[Path] = None) -> ServiceContainer:
    container = ServiceContainer()
    if log_dir is None:
        log_dir = get_app_data_dir()
    LoggerFactory.configure(log_dir)
    logger = LoggerFactory.get_logger("ost_visualizer")
    container.register_instance("logger", logger)
    descriptor_registry = DatabaseDescriptorRegistry()
    credential_store = WindowsCredentialStore()
    session_registry = DatabaseSessionRegistry()
    local_drafts = LocalDraftRegistry()
    pending_mutations = PendingMutationRegistry()
    conflict_resolution = ConflictResolutionService()
    sql_connections = SqlConnectionManager()
    concurrency_tokens = DatabaseConcurrencyTokenService(
        DatabaseEntityVersionReader(
            descriptor_registry, credential_store, sql_connections
        ),
        local_drafts,
    )
    container.register_instance("database_session_registry", session_registry)
    container.register_instance("database_concurrency_tokens", concurrency_tokens)
    container.register_instance("local_draft_registry", local_drafts)
    container.register_instance("pending_mutation_registry", pending_mutations)
    icon_provider = QtWindowIconProvider()
    message_notifier = QtMessageNotifier(icon_provider=icon_provider)
    infrastructure_provider = InfrastructureServiceProvider(
        logger,
        callback_bridge_factory=QtCallbackBridge,
        icon_provider=icon_provider,
        message_notifier=message_notifier,
        descriptor_registry=descriptor_registry,
        credential_store=credential_store,
        database_session_registry=session_registry,
    )
    database_capability_service = DatabaseCapabilityService(
        descriptor_registry,
        infrastructure_provider.get_database_permission_probe(),
    )
    container.register_instance(
        "database_capability_service", database_capability_service
    )
    repository_provider = RepositoryProvider(
        logger,
        descriptor_registry=descriptor_registry,
        project_reader_factory=infrastructure_provider.get_mdb_reader,
    )
    api_client_provider = ApiClientProvider(logger)

    def event_bus_factory():
        return EventBus()

    def view_manager_factory(
        event_bus,
        repository,
        project_data_service,
        config_model,
        parent_window,
        logger,
        icon_provider,
        view_kind="annotation",
        write_service=None,
        annotation_write_service=None,
        saved_window_state_provider=None,
    ):
        coord_factory = infrastructure_provider.get_coordinate_transformer_factory()
        color_service = infrastructure_provider.get_color_service()
        resolved_view_kind = str(view_kind).lower()
        if resolved_view_kind == "main":
            return QtMainHotlinkViewManager(parent_window)
        manager_cls = (
            QtAnnotationViewManager
            if resolved_view_kind == "annotation"
            else QtViewWindowManager
        )
        return manager_cls(
            event_bus=event_bus,
            icon_provider=icon_provider,
            repository=repository,
            project_data=project_data_service,
            config_model=config_model,
            coord_factory=coord_factory,
            color_service=color_service,
            infrastructure_provider=infrastructure_provider,
            write_service=write_service,
            annotation_write_service=annotation_write_service,
            saved_window_state_provider=saved_window_state_provider,
            parent_window=parent_window,
            logger=logger,
        )

    def repository_factory():
        return MemoryAnnotationViewRepository()

    scene_notifier = QtSceneNotifier()
    ost_signaler = OstSignaler()
    AppControllerBuilder(
        container=container,
        logger=logger,
        repository_provider=repository_provider,
        infrastructure_provider=infrastructure_provider,
        api_client_provider=api_client_provider,
        view_manager_factory=view_manager_factory,
        repository_factory=repository_factory,
        event_bus_factory=event_bus_factory,
        scene_notifier=scene_notifier,
        ost_signaler=ost_signaler,
    ).build()
    event_bus = container.get("event_bus")
    reconciliation = RemoteChangeReconciliationService(
        container.get("project_data_service"),
        event_bus,
        concurrency_tokens,
        local_drafts,
        conflict_resolution,
    )
    remote_change_reader = SqlRemoteChangeReader(
        descriptor_registry, credential_store, sql_connections
    )
    collaboration = SqlCollaborationCoordinator(
        descriptor_registry=descriptor_registry,
        store=SqlCollaborationStore(
            descriptor_registry,
            credential_store,
            remote_change_reader,
            sql_connections,
        ),
        remote_reader=remote_change_reader,
        dispatcher=QtCallbackBridge(),
        reconciliation=reconciliation,
        capability_service=database_capability_service,
        session_registry=session_registry,
        concurrency_tokens=concurrency_tokens,
        local_drafts=local_drafts,
        event_bus=event_bus,
        supported_schema_version=SQL_SCHEMA_V1.version,
        pending_mutations=pending_mutations,
        operation_journal=JsonPendingSqlOperationRepository(logger=logger),
    )
    container.register_instance("sql_collaboration_coordinator", collaboration)
    return container
