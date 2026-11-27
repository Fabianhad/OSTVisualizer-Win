import ctypes
import logging
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
import win32com.client
import win32con
import win32file
from ...application.interfaces.i_database_maintenance import DatabaseMaintenanceResult
from ...shared.texts import (
    DATABASE_MAINTENANCE_LOG_COULD_NOT_RESTORE_THE_ORIGINAL_DATABASE,
    DATABASE_MAINTENANCE_LOG_MAINTENANCE_CLEANUP_FAILED_AFTER_THE_INTERRUPT,
    DATABASE_MAINTENANCE_MESSAGE_ACCESS_REPORTED_REPAIR_ERRORS_THE_ORIGINAL,
    DATABASE_MAINTENANCE_MESSAGE_CLOSE_ON_SCREEN_TAKEOFF_BEFORE_DATABASE,
    DATABASE_MAINTENANCE_MESSAGE_COMPACTED_DATABASE_VALIDATION_FAILED_THE_ORIGINA,
    DATABASE_MAINTENANCE_MESSAGE_COMPACT_REPAIR_COMPLETED_SUCCESSFULLY,
    DATABASE_MAINTENANCE_MESSAGE_COM_COULD_NOT_BE_INITIALISED_HRESULT,
    DATABASE_MAINTENANCE_MESSAGE_MAINTENANCE_WAS_INTERRUPTED_BY_ON_SCREEN,
    DATABASE_MAINTENANCE_MESSAGE_REPLACEMENT_RECOVERY_FAILED_THE_ORIGINAL_DATABAS,
    DATABASE_MAINTENANCE_MESSAGE_SELECT_AN_EXISTING_MICROSOFT_ACCESS_MDB,
    DATABASE_MAINTENANCE_MESSAGE_THE_SELECTED_DATABASE_CHANGED_START_MAINTENANCE,
    DATABASE_MAINTENANCE_MESSAGE_THE_SOURCE_CHANGED_DURING_REPLACEMENT_ITS,
    DATABASE_MAINTENANCE_MESSAGE_THE_SOURCE_CHANGED_DURING_REPLACEMENT_RECOVERY,
    DATABASE_MAINTENANCE_MESSAGE_THE_SOURCE_DATABASE_CHANGED_DURING_MAINTENANCE,
    DATABASE_MAINTENANCE_MESSAGE_THIS_MAINTENANCE_RESULT_IS_NO_LONGER,
)

_LOGGER = logging.getLogger(__name__)
_COINIT_APARTMENTTHREADED = 0x2
_S_OK = 0
_S_FALSE = 1
_RPC_E_CHANGED_MODE = -2147417850
_ole32_dll = None


def _ole32():
    global _ole32_dll
    if _ole32_dll is None:
        ole32 = ctypes.WinDLL("ole32")
        ole32.CoInitializeEx.argtypes = [wintypes.LPVOID, wintypes.DWORD]
        ole32.CoInitializeEx.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = []
        ole32.CoUninitialize.restype = None
        _ole32_dll = ole32
    return _ole32_dll


@contextmanager
def _com_initialized():
    ole32 = _ole32()
    result = ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    if result not in (_S_OK, _S_FALSE, _RPC_E_CHANGED_MODE):
        raise OSError(
            DATABASE_MAINTENANCE_MESSAGE_COM_COULD_NOT_BE_INITIALISED_HRESULT.format(
                hresult=result & 4294967295
            )
        )
    try:
        yield
    finally:
        if result in (_S_OK, _S_FALSE):
            ole32.CoUninitialize()


def _replace_file(source: Path, destination: Path, backup: Path) -> None:
    replace = ctypes.WinDLL("kernel32", use_last_error=True).ReplaceFileW
    replace.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    replace.restype = wintypes.BOOL
    if not replace(str(source), str(destination), str(backup), 0, None, None):
        raise ctypes.WinError(ctypes.get_last_error())


def _signature(path: Path) -> tuple:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _cleanup_after_interrupt(cleanup, interrupt: BaseException) -> None:
    try:
        cleanup()
    except Exception:
        _LOGGER.exception(
            DATABASE_MAINTENANCE_LOG_MAINTENANCE_CLEANUP_FAILED_AFTER_THE_INTERRUPT.format(
                error_type=type(interrupt).__name__
            )
        )


def _table_counts(engine, path: Path) -> dict[str, int | None]:
    database = engine.OpenDatabase(str(path), True, True)
    try:
        counts = {}
        for table in database.TableDefs:
            name = table.Name
            if name.startswith("MSys") and name != "MSysCompactError":
                continue
            if table.Attributes & 0x60000000:
                counts[name] = None
                continue
            escaped = name.replace("]", "]]")
            rows = database.OpenRecordset(f"SELECT COUNT(*) FROM [{escaped}]", 4)
            try:
                count = int(rows.Fields(0).Value)
            finally:
                rows.Close()
            if name == "MSysCompactError":
                if count:
                    raise RuntimeError(
                        DATABASE_MAINTENANCE_MESSAGE_ACCESS_REPORTED_REPAIR_ERRORS_THE_ORIGINAL
                    )
                continue
            counts[name] = count
        return counts
    finally:
        database.Close()


class MdbDatabaseMaintenance:
    def __init__(self, connections):
        self._connections = connections

    def unavailable_reason(self, locator: str) -> str:
        if self._connections.is_write_blocked():
            return DATABASE_MAINTENANCE_MESSAGE_CLOSE_ON_SCREEN_TAKEOFF_BEFORE_DATABASE
        if not Path(locator).is_file() or Path(locator).suffix.lower() != ".mdb":
            return DATABASE_MAINTENANCE_MESSAGE_SELECT_AN_EXISTING_MICROSOFT_ACCESS_MDB
        return ""

    def capture_target(self, locator: str):
        source = Path(locator).absolute()
        file_identity = _signature(source)[:2]
        lease = self._connections.maintenance(str(source))
        lease.__enter__()
        try:
            identity = _signature(source)
            if identity[:2] != file_identity:
                raise RuntimeError(
                    DATABASE_MAINTENANCE_MESSAGE_THE_SELECTED_DATABASE_CHANGED_START_MAINTENANCE
                )
            return _MdbMaintenanceTarget(source, identity, lease)
        except Exception:
            lease.__exit__(None, None, None)
            raise
        except BaseException as interrupt:
            _cleanup_after_interrupt(
                lambda: lease.__exit__(None, None, None), interrupt
            )
            raise

    def is_target_current(self, locator: str, identity: object) -> bool:
        return (
            isinstance(identity, _MdbMaintenanceTarget)
            and identity.active
            and os.path.normcase(os.path.abspath(locator))
            == os.path.normcase(str(identity.source))
            and _signature(identity.source) == identity.signature
        )

    def release_target(self, locator: str, identity: object) -> None:
        identity.close()

    def compact(self, locator: str) -> DatabaseMaintenanceResult:
        prepared = self.prepare(locator, self.capture_target(locator))
        try:
            return prepared.commit()
        finally:
            pending = sys.exc_info()[1]
            if pending is None or isinstance(pending, Exception):
                prepared.close()
            else:
                _cleanup_after_interrupt(prepared.close, pending)

    def prepare(self, locator: str, identity: object):
        prepared = _PreparedMdbMaintenance(
            identity.source, identity.signature, identity, self._connections
        )
        try:
            if not self.is_target_current(locator, identity):
                raise RuntimeError(
                    DATABASE_MAINTENANCE_MESSAGE_THE_SELECTED_DATABASE_CHANGED_START_MAINTENANCE
                )
            with _com_initialized():
                prepared.build()
            return prepared
        except Exception:
            prepared.close()
            raise
        except BaseException as interrupt:
            _cleanup_after_interrupt(prepared.close, interrupt)
            raise


class _MdbMaintenanceTarget:
    def __init__(self, source, signature, lease):
        self.source = source
        self.signature = signature
        self._lease = lease

    @property
    def active(self) -> bool:
        return self._lease is not None

    def close(self) -> None:
        if self._lease is not None:
            self._lease.__exit__(None, None, None)
            self._lease = None


class _PreparedMdbMaintenance:
    def __init__(self, source, identity, lease, connections):
        self.source = source
        self.identity = identity
        self._lease = lease
        self._connections = connections
        self._work = None
        self._preserve_recovery = False
        self._swap_in_progress = False
        self._committed = False

    def build(self) -> None:
        engine = win32com.client.Dispatch("DAO.DBEngine.120")
        expected = _table_counts(engine, self.source)
        self._work = Path(
            tempfile.mkdtemp(prefix=".ost-compact-", dir=self.source.parent)
        )
        destination = self._work / self.source.name
        engine.CompactDatabase(str(self.source), str(destination))
        if _table_counts(engine, destination) != expected:
            raise RuntimeError(
                DATABASE_MAINTENANCE_MESSAGE_COMPACTED_DATABASE_VALIDATION_FAILED_THE_ORIGINA
            )
        with destination.open("rb+") as compacted:
            os.fsync(compacted.fileno())

    def commit(self) -> DatabaseMaintenanceResult:
        if self._lease is None or not self._lease.active or self._committed:
            raise RuntimeError(
                DATABASE_MAINTENANCE_MESSAGE_THIS_MAINTENANCE_RESULT_IS_NO_LONGER
            )
        if self._connections.is_write_blocked():
            raise RuntimeError(
                DATABASE_MAINTENANCE_MESSAGE_MAINTENANCE_WAS_INTERRUPTED_BY_ON_SCREEN
            )
        handle = win32file.CreateFile(
            str(self.source),
            win32con.GENERIC_READ,
            win32con.FILE_SHARE_READ | win32con.FILE_SHARE_DELETE,
            None,
            win32con.OPEN_EXISTING,
            win32con.FILE_ATTRIBUTE_NORMAL,
            None,
        )
        try:
            if _signature(self.source) != self.identity:
                raise RuntimeError(
                    DATABASE_MAINTENANCE_MESSAGE_THE_SOURCE_DATABASE_CHANGED_DURING_MAINTENANCE
                )
        finally:
            handle.Close()
        destination = self._work / self.source.name
        backup = self._work / "original.backup"
        self._swap_in_progress = True
        try:
            _replace_file(self.source, destination, backup)
            if _signature(backup) != self.identity:
                self._preserve_recovery = True
                try:
                    _replace_file(self.source, backup, self._work / "rejected.compact")
                except Exception as exc:
                    raise RuntimeError(
                        DATABASE_MAINTENANCE_MESSAGE_THE_SOURCE_CHANGED_DURING_REPLACEMENT_RECOVERY.format(
                            work=self._work
                        )
                    ) from exc
                self._preserve_recovery = False
                raise RuntimeError(
                    DATABASE_MAINTENANCE_MESSAGE_THE_SOURCE_CHANGED_DURING_REPLACEMENT_ITS
                )
        except BaseException as failure:
            self._recover_swap(backup, failure)
            raise
        self._swap_in_progress = False
        self._committed = True
        return DatabaseMaintenanceResult(
            True, DATABASE_MAINTENANCE_MESSAGE_COMPACT_REPAIR_COMPLETED_SUCCESSFULLY
        )

    def _recover_swap(self, backup: Path, failure: BaseException) -> None:
        if not backup.exists():
            self._swap_in_progress = False
            return
        preserved_before = self._preserve_recovery
        self._preserve_recovery = True
        if self.source.exists():
            return
        try:
            os.rename(backup, self.source)
        except Exception as exc:
            if isinstance(failure, Exception):
                if not isinstance(exc, OSError):
                    raise
                raise RuntimeError(
                    DATABASE_MAINTENANCE_MESSAGE_REPLACEMENT_RECOVERY_FAILED_THE_ORIGINAL_DATABAS.format(
                        backup=backup
                    )
                ) from exc
            _LOGGER.exception(
                DATABASE_MAINTENANCE_LOG_COULD_NOT_RESTORE_THE_ORIGINAL_DATABASE.format(
                    error_type=type(failure).__name__, backup=backup
                )
            )
            return
        self._preserve_recovery = preserved_before
        self._swap_in_progress = False

    def close(self) -> None:
        try:
            if self._work is not None and not (
                self._preserve_recovery or self._swap_in_progress
            ):
                shutil.rmtree(self._work)
                self._work = None
        except Exception:
            self._release_lease()
            raise
        except BaseException as interrupt:
            _cleanup_after_interrupt(self._release_lease, interrupt)
            raise
        self._release_lease()

    def _release_lease(self) -> None:
        if self._lease is not None:
            self._lease.close()
            self._lease = None
