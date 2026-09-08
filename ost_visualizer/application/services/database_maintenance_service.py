import threading
from dataclasses import dataclass
from ...domain.entities.file_state import normalize_path
from ..events.app_events import AppEvents
from ..interfaces.i_database_maintenance import (
    DatabaseMaintenanceResult,
    IDatabaseMaintenance,
)


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
        return DatabaseMaintenanceTarget(
            locator, self._backend.capture_target(locator), self._loaded_owner(locator)
        )

    def is_target_current(self, target: DatabaseMaintenanceTarget) -> bool:
        return (
            self._loaded_owner(target.locator) is target.loaded_owner
            and self._backend.capture_target(target.locator) == target.source_identity
        )

    def prepare(self, target: DatabaseMaintenanceTarget):
        if not self._operation_lock.acquire(blocking=False):
            raise RuntimeError("Database maintenance is already running.")
        try:
            return self._backend.prepare(target.locator, target.source_identity)
        except BaseException:
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
                False, "The selected database changed; maintenance was cancelled."
            )
            try:
                if self.is_target_current(target):
                    result = prepared.commit()
            except Exception as exc:
                result = DatabaseMaintenanceResult(False, str(exc))
            finally:
                try:
                    prepared.close()
                except Exception as exc:
                    cleanup_error = str(exc)
            if result.success:
                result = self.refresh_loaded_database(target.locator, unload_file)
            if cleanup_error:
                return DatabaseMaintenanceResult(
                    False,
                    f"{result.message} Temporary-file cleanup failed: {cleanup_error}",
                )
            return result
        finally:
            self._operation_lock.release()

    def unavailable_reason(self, locator: str) -> str:
        if not locator:
            return "Select a database first."
        return self._backend.unavailable_reason(locator)

    def compact(self, locator: str) -> DatabaseMaintenanceResult:
        if not self._operation_lock.acquire(blocking=False):
            return DatabaseMaintenanceResult(
                False, "Database maintenance is already running."
            )
        try:
            reason = self.unavailable_reason(locator)
            if reason:
                return DatabaseMaintenanceResult(False, reason)
            return self._backend.compact(locator)
        except Exception as exc:
            return DatabaseMaintenanceResult(
                False, str(exc) or "Database maintenance failed."
            )
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
                        "Compaction completed, but refresh and unload failed. Close and reopen the application before continuing.",
                    )
                return DatabaseMaintenanceResult(
                    False,
                    "Compaction completed, but refresh failed. The database was unloaded; reopen it to retry.",
                )
            self._events.publish(AppEvents.DATABASE_REFRESHED, file_path=locator)
        return DatabaseMaintenanceResult(True, "Compact/Repair completed successfully.")
