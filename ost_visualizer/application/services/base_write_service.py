import logging
from typing import Callable, Optional
from ..dtos.collaboration_dtos import (
    DatabaseMutationRequest,
    DatabaseMutationResult,
    ResourceRef,
)
from ..events.app_events import AppEvents
from ..interfaces.i_database_mutation_executor import (
    IDatabaseMutationExecutor,
    IMutationRecorder,
)
from ..interfaces.i_database_session_registry import IDatabaseSessionRegistry
from .database_concurrency_token_service import DatabaseConcurrencyTokenService
from .database_capability_service import DatabaseCapabilityService


class BaseWriteService:
    def __init__(
        self,
        reload_database: Callable[[str], bool],
        event_bus,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._reload_database = reload_database
        self._event_bus = event_bus
        self.logger = logger or logging.getLogger(__name__)

    def reload_and_notify(self, file_path: str) -> bool:
        if not self.reload_database(file_path):
            return False
        self.notify_database_refreshed(file_path)
        return True

    def reload_database(self, file_path: str) -> bool:
        try:
            return self._reload_database(file_path)
        except Exception:
            self.logger.warning("Failed to reload database", exc_info=True)
            return False

    def notify_database_refreshed(self, file_path: str) -> None:
        self._event_bus.publish(AppEvents.DATABASE_REFRESHED, file_path=file_path)


class DatabaseMutationWriteService(BaseWriteService):
    def __init__(
        self,
        reload_database: Callable[[str], bool],
        event_bus,
        mutation_executor: IDatabaseMutationExecutor,
        session_registry: IDatabaseSessionRegistry,
        concurrency_tokens: DatabaseConcurrencyTokenService,
        database_capability_service: DatabaseCapabilityService,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        super().__init__(reload_database, event_bus, logger)
        self._mutation_executor = mutation_executor
        self._session_registry = session_registry
        self._concurrency_tokens = concurrency_tokens
        self._database_capability_service = database_capability_service

    def _execute_database_mutation(
        self,
        database_id: str,
        resources: tuple[ResourceRef, ...],
        operation: Callable[[IMutationRecorder], object],
        *,
        block_bid_child_locks: bool = False,
        block_bid_active_editors: bool = False,
    ) -> DatabaseMutationResult:
        if not self._database_capability_service.is_editable(database_id):
            self.logger.warning(
                "Database mutation rejected because editing is unavailable."
            )
            return DatabaseMutationResult(success=False)
        for resource in resources:
            if not self._database_capability_service.is_editable(database_id, resource):
                self.logger.warning(
                    "Database mutation rejected because its resource is unavailable."
                )
                return DatabaseMutationResult(success=False)
        session_id = self._session_registry.get(database_id)
        self._concurrency_tokens.ensure_resources_loaded(database_id, resources)
        expected_versions = self._concurrency_tokens.expected_versions(
            database_id, resources
        )
        result = self._mutation_executor.execute(
            DatabaseMutationRequest(
                database_id=database_id,
                session_id=session_id,
                resources=resources,
                expected_versions=expected_versions,
                required_lock_tokens=self._session_registry.lock_tokens(
                    database_id, resources
                ),
                block_bid_child_locks=block_bid_child_locks,
                block_bid_active_editors=block_bid_active_editors,
            ),
            operation,
        )
        if result.success:
            self._concurrency_tokens.apply_result(
                database_id, result.resulting_versions
            )
        if result.conflict is not None:
            self._event_bus.publish(
                AppEvents.SYNCHRONIZATION_CONFLICT,
                database_id=database_id,
                resource_type=result.conflict.resource.resource_type,
                resource_id=result.conflict.resource.resource_id,
                bid_uid=str(result.conflict.resource.bid_uid or ""),
                message=result.conflict.reason,
                blocks_database=False,
            )
        return result
