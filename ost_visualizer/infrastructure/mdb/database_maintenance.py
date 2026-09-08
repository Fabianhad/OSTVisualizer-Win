import os
import ctypes
from ctypes import wintypes
from pathlib import Path
import tempfile
import shutil
import pythoncom
import win32com.client
import win32con
import win32file
from ...application.interfaces.i_database_maintenance import DatabaseMaintenanceResult


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
                        "Access reported repair errors; the original database was not replaced."
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
            return "Close On-Screen Takeoff before database maintenance."
        if not Path(locator).is_file() or Path(locator).suffix.lower() != ".mdb":
            return "Select an existing Microsoft Access MDB database."
        return ""

    def capture_target(self, locator: str) -> tuple:
        return _signature(Path(locator))

    def compact(self, locator: str) -> DatabaseMaintenanceResult:
        prepared = self.prepare(locator, self.capture_target(locator))
        try:
            return prepared.commit()
        finally:
            prepared.close()

    def prepare(self, locator: str, identity: object):
        source = Path(locator).absolute()
        lease = self._connections.maintenance(str(source))
        lease.__enter__()
        prepared = _PreparedMdbMaintenance(source, identity, lease, self._connections)
        try:
            if _signature(source) != identity:
                raise RuntimeError(
                    "The selected database changed; start maintenance again."
                )
            pythoncom.CoInitialize()
            try:
                prepared.build()
            finally:
                pythoncom.CoUninitialize()
            return prepared
        except BaseException:
            prepared.close()
            raise


class _PreparedMdbMaintenance:
    def __init__(self, source, identity, lease, connections):
        self.source = source
        self.identity = identity
        self._lease = lease
        self._connections = connections
        self._work = None
        self._preserve_recovery = False
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
                "Compacted database validation failed; the original was not replaced."
            )
        with destination.open("rb+") as compacted:
            os.fsync(compacted.fileno())

    def commit(self) -> DatabaseMaintenanceResult:
        if self._lease is None or self._committed:
            raise RuntimeError("This maintenance result is no longer pending.")
        if self._connections.is_write_blocked():
            raise RuntimeError(
                "Maintenance was interrupted by On-Screen Takeoff; the original was not replaced."
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
                    "The source database changed during maintenance; it was not replaced."
                )
        finally:
            handle.Close()
        destination = self._work / self.source.name
        backup = self._work / "original.backup"
        try:
            _replace_file(self.source, destination, backup)
            if _signature(backup) != self.identity:
                self._preserve_recovery = True
                try:
                    _replace_file(self.source, backup, self._work / "rejected.compact")
                except Exception as exc:
                    raise RuntimeError(
                        f"The source changed during replacement. Recovery files are preserved at {self._work}."
                    ) from exc
                self._preserve_recovery = False
                raise RuntimeError(
                    "The source changed during replacement; its newer contents were restored."
                )
        except Exception:
            if backup.exists():
                if not self.source.exists():
                    try:
                        os.rename(backup, self.source)
                    except OSError as exc:
                        self._preserve_recovery = True
                        raise RuntimeError(
                            f"Replacement recovery failed. The original database is preserved at {backup}."
                        ) from exc
                else:
                    self._preserve_recovery = True
            raise
        self._committed = True
        return DatabaseMaintenanceResult(True, "Compact/Repair completed successfully.")

    def close(self) -> None:
        try:
            if self._work is not None and not self._preserve_recovery:
                shutil.rmtree(self._work)
                self._work = None
        finally:
            if self._lease is not None:
                self._lease.__exit__(None, None, None)
                self._lease = None
