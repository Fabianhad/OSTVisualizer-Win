import logging
import threading
from dataclasses import dataclass
from ...domain.entities.file_state import normalize_path
from ..events.app_events import AppEvents
from ..utils.failure_messages import maintenance_failure_message
from ..interfaces.i_database_maintenance import (
    DatabaseMaintenanceResult,
    IDatabaseMaintenance,
)
from ...shared.texts import (
    DATABASE_MAINTENANCE_SERVICE_MESSAGE_COMPACTION_COMPLETED_BUT_RELOAD_AND_UNLOAD,
    DATABASE_MAINTENANCE_SERVICE_MESSAGE_COMPACTION_COMPLETED_BUT_THE_RELOAD_FAILED,
    DATABASE_MAINTENANCE_SERVICE_MESSAGE_COMPACT_REPAIR_COMPLETED_SUCCESSFULLY,
    DATABASE_MAINTENANCE_SERVICE_MESSAGE_SELECT_A_DATABASE_FIRST,
    DATABASE_MAINTENANCE_SERVICE_MESSAGE_DATABASE_MAINTENANCE_IS_ALREADY_RUNNING,
    DATABASE_MAINTENANCE_SERVICE_MESSAGE_TEMPORARY_FILE_CLEANUP_FAILED,
    DATABASE_MAINTENANCE_SERVICE_MESSAGE_THE_SELECTED_DATABASE_CHANGED_MAINTENANCE_WAS,
    DATABASE_MAINTENANCE_SERVICE_MESSAGE_THE_SELECTED_DATABASE_CHANGED_START_MAINTENANCE,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatabaseMaintenanceTarget:
    locator: str
    source_identity: object
    loaded_owner: object


class DatabaseMaintenanceService:
    def __init__(self, backend: IDatabaseMaintenance, file_loading_service, event_bus):
        self._backend = backend
        self._files = file_loading_service
        self._events = event_bus
        self._operation_lock = threading.Lock()

    def _loaded_owner(self, locator):
        return next(
            (
                entry
                for entry in self._files.data_service.get_hierarchy().loaded_files
                if normalize_path(entry.file_path) == normalize_path(locator)
            ),
            None,
        )

    def capture_target(self, locator: str) -> DatabaseMaintenanceTarget:
        owner = self._loaded_owner(locator)
        return DatabaseMaintenanceTarget(
            locator, self._backend.capture_target(locator), owner
        )

    def release_target(self, target: DatabaseMaintenanceTarget) -> None:
        self._backend.release_target(target.locator, target.source_identity)

    def is_target_current(self, target: DatabaseMaintenanceTarget) -> bool:
        return self._loaded_owner(
            target.locator
        ) is target.loaded_owner and self._backend.is_target_current(
            target.locator, target.source_identity
        )

    def prepare(self, target: DatabaseMaintenanceTarget):
        if not self._operation_lock.acquire(blocking=False):
            raise RuntimeError(
                DATABASE_MAINTENANCE_SERVICE_MESSAGE_DATABASE_MAINTENANCE_IS_ALREADY_RUNNING
            )
        try:
            if not self.is_target_current(target):
                raise RuntimeError(
                    DATABASE_MAINTENANCE_SERVICE_MESSAGE_THE_SELECTED_DATABASE_CHANGED_START_MAINTENANCE
                )
            return self._backend.prepare(target.locator, target.source_identity)
        except BaseException:
            try:
                self.release_target(target)
            finally:
                self._operation_lock.release()
            raise

    def discard(self, prepared) -> None:
        try:
            prepared.close()
        finally:
            self._operation_lock.release()

    def finish(self, target, prepared, unload_file) -> DatabaseMaintenanceResult:
        try:
            cleanup_error = None
            result = DatabaseMaintenanceResult(
                False,
                DATABASE_MAINTENANCE_SERVICE_MESSAGE_THE_SELECTED_DATABASE_CHANGED_MAINTENANCE_WAS,
            )
            try:
                if self.is_target_current(target):
                    result = prepared.commit()
            except Exception as exc:
                logger.warning(
                    "Database maintenance commit failed: %s", exc, exc_info=exc
                )
                result = DatabaseMaintenanceResult(
                    False, maintenance_failure_message(exc)
                )
            finally:
                try:
                    prepared.close()
                except Exception as exc:
                    logger.warning(
                        "Database maintenance cleanup failed: %s", exc, exc_info=exc
                    )
                    cleanup_error = str(exc)
            if result.success:
                result = self.refresh_loaded_database(target.locator, unload_file)
            if cleanup_error:
                return DatabaseMaintenanceResult(
                    False,
                    DATABASE_MAINTENANCE_SERVICE_MESSAGE_TEMPORARY_FILE_CLEANUP_FAILED.format(
                        message=result.message
                    ),
                )
            return result
        finally:
            self._operation_lock.release()

    def unavailable_reason(self, locator: str) -> str:
        if not locator:
            return DATABASE_MAINTENANCE_SERVICE_MESSAGE_SELECT_A_DATABASE_FIRST
        return self._backend.unavailable_reason(locator)

    def compact(self, locator: str) -> DatabaseMaintenanceResult:
        if not self._operation_lock.acquire(blocking=False):
            return DatabaseMaintenanceResult(
                False,
                DATABASE_MAINTENANCE_SERVICE_MESSAGE_DATABASE_MAINTENANCE_IS_ALREADY_RUNNING,
            )
        try:
            reason = self.unavailable_reason(locator)
            if reason:
                return DatabaseMaintenanceResult(False, reason)
            return self._backend.compact(locator)
        except Exception as exc:
            logger.warning("Database compaction failed: %s", exc, exc_info=exc)
            return DatabaseMaintenanceResult(False, maintenance_failure_message(exc))
        finally:
            self._operation_lock.release()

    def refresh_loaded_database(
        self, locator: str, unload_file
    ) -> DatabaseMaintenanceResult:
        owner = self._loaded_owner(locator)
        if owner is not None:
            locator = owner.file_path
            try:
                success = self._files.reload_database(locator).success
            except Exception:
                success = False
            if not success:
                if not unload_file(locator):
                    return DatabaseMaintenanceResult(
                        False,
                        DATABASE_MAINTENANCE_SERVICE_MESSAGE_COMPACTION_COMPLETED_BUT_RELOAD_AND_UNLOAD,
                    )
                return DatabaseMaintenanceResult(
                    False,
                    DATABASE_MAINTENANCE_SERVICE_MESSAGE_COMPACTION_COMPLETED_BUT_THE_RELOAD_FAILED,
                )
            self._events.publish(AppEvents.DATABASE_REFRESHED, file_path=locator)
        return DatabaseMaintenanceResult(
            True,
            DATABASE_MAINTENANCE_SERVICE_MESSAGE_COMPACT_REPAIR_COMPLETED_SUCCESSFULLY,
        )
