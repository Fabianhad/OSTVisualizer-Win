import os
import threading
from contextlib import contextmanager
from typing import Dict, Generator
import pyodbc
from ...application.interfaces.i_mdb_connection_manager import (
    DatabaseConnectionUnavailableError,
)
from ..database.connection_wrapper import ConnectionWrapper

ACCESS_CLIENT_TASK_EXHAUSTED_MESSAGE = (
    "Microsoft Access cannot open another database connection in this OST "
    "Visualizer session. Save any work in other applications, restart OST "
    "Visualizer, and try again."
)


class WriteBlockedError(Exception):
    """Raised when an MDB write is attempted while writes are blocked."""


class MdbConnectionManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._read_conns: Dict[str, pyodbc.Connection] = {}
        self._write_conns: Dict[str, pyodbc.Connection] = {}
        self._path_locks = {}
        self._active_leases: Dict[str, tuple[bool, int]] = {}
        self._unhealthy_connection_ids: set[int] = set()
        self._writer_read_paths: set[str] = set()
        self._write_blocked = False
        self._maintenance_paths: set[str] = set()

    @contextmanager
    def maintenance(self, db_path: str):
        key = os.path.normcase(os.path.abspath(db_path))
        with self._lock:
            if self._write_blocked:
                raise WriteBlockedError(
                    "Close On-Screen Takeoff before database maintenance."
                )
            if key in self._maintenance_paths or any(
                os.path.normcase(path) == key for path in self._active_leases
            ):
                raise RuntimeError(
                    "The database has active operations; try again when they finish."
                )
            self._maintenance_paths.add(key)
            paths = {db_path} | {
                path
                for path in set(self._read_conns) | set(self._write_conns)
                if os.path.normcase(path) == key
            }
        try:
            for path in paths:
                self.close_database(path)
            yield
        finally:
            with self._lock:
                self._maintenance_paths.remove(key)

    def set_write_blocked(self, blocked: bool) -> None:
        with self._lock:
            self._write_blocked = blocked
        if blocked:
            self.close_write_connections()

    def is_write_blocked(self) -> bool:
        with self._lock:
            return self._write_blocked

    @contextmanager
    def connection(
        self, db_path: str, autocommit: bool = True
    ) -> Generator[ConnectionWrapper, None, None]:
        abs_path = os.path.normcase(os.path.abspath(db_path))
        path_lock = self._get_path_lock(abs_path)
        with path_lock:
            with self._lock:
                if os.path.normcase(abs_path) in self._maintenance_paths:
                    raise RuntimeError(
                        "The database is temporarily closed for maintenance."
                    )
                if not autocommit and self._write_blocked:
                    raise WriteBlockedError(
                        "Database writes are blocked while OST is active"
                    )
                active_lease = self._active_leases.get(abs_path)
                if active_lease is not None and active_lease[0] != autocommit:
                    raise RuntimeError(
                        "Nested MDB connection leases must use the same mode"
                    )
                borrowed_write_connection = False
                prefer_writer = autocommit and abs_path in self._writer_read_paths
                if prefer_writer:
                    pool = self._write_conns
                    conn = self._write_conns.get(abs_path)
                    borrowed_write_connection = conn is not None
                    if conn is None:
                        self._close_single(self._read_conns, abs_path)
                        self._writer_read_paths.discard(abs_path)
                        pool = self._read_conns
                else:
                    pool = self._read_conns if autocommit else self._write_conns
                    conn = pool.get(abs_path)
                    if autocommit and conn is None:
                        conn = self._write_conns.get(abs_path)
                        if conn is not None:
                            pool = self._write_conns
                            borrowed_write_connection = True
                if conn is not None and id(conn) in self._unhealthy_connection_ids:
                    self._close_single(pool, abs_path)
                    conn = None
                    if borrowed_write_connection:
                        self._close_single(self._read_conns, abs_path)
                        self._writer_read_paths.discard(abs_path)
                        pool = self._read_conns
                    borrowed_write_connection = False
                if conn is not None:
                    try:
                        conn.cursor().close()
                    except pyodbc.Error:
                        self._unhealthy_connection_ids.add(id(conn))
                        self._close_single(pool, abs_path)
                        conn = None
                        if borrowed_write_connection:
                            self._close_single(self._read_conns, abs_path)
                            self._writer_read_paths.discard(abs_path)
                            pool = self._read_conns
                        borrowed_write_connection = False
                if conn is None:
                    conn_str = (
                        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
                        f"DBQ={abs_path};"
                    )
                    try:
                        conn = pyodbc.connect(conn_str, autocommit=autocommit)
                    except pyodbc.OperationalError as exc:
                        if self._is_client_task_exhaustion(exc):
                            raise DatabaseConnectionUnavailableError(
                                ACCESS_CLIENT_TASK_EXHAUSTED_MESSAGE
                            ) from exc
                        raise
                    pool[abs_path] = conn
                lease_depth = active_lease[1] + 1 if active_lease is not None else 1
                self._active_leases[abs_path] = (autocommit, lease_depth)
            wrapper = ConnectionWrapper(conn)
            cursor_cleanup_errors = []
            try:
                try:
                    yield wrapper
                finally:
                    cursor_cleanup_errors = wrapper.close_cursors()
                    if borrowed_write_connection:
                        conn.rollback()
            except pyodbc.Error as operation_error:
                should_replace = self._connection_requires_replacement(
                    conn,
                    operation_error,
                )
                if should_replace:
                    with self._lock:
                        _active_mode, active_depth = self._active_leases[abs_path]
                        if active_depth == 1:
                            self._unhealthy_connection_ids.add(id(conn))
                            try:
                                self._close_single(pool, abs_path)
                            except pyodbc.Error as close_error:
                                operation_error.add_note(
                                    "The invalid MDB connection could not be closed: "
                                    f"{close_error}"
                                )
                raise
            finally:
                if cursor_cleanup_errors:
                    with self._lock:
                        self._unhealthy_connection_ids.add(id(conn))
                        try:
                            self._close_single(pool, abs_path)
                        except pyodbc.Error as close_error:
                            cursor_cleanup_errors[0].add_note(
                                "The MDB connection with an unclosed cursor could "
                                f"not be closed: {close_error}"
                            )
                with self._lock:
                    active_mode, depth = self._active_leases[abs_path]
                    depth -= 1
                    if depth:
                        self._active_leases[abs_path] = (active_mode, depth)
                    else:
                        self._active_leases.pop(abs_path)

    def use_committed_writer_for_reads(self, db_path: str) -> None:
        abs_path = os.path.normcase(os.path.abspath(db_path))
        path_lock = self._get_path_lock(abs_path)
        with path_lock:
            with self._lock:
                if abs_path in self._active_leases:
                    return
                self._writer_read_paths.add(abs_path)

    def close_write_connections(self) -> None:
        with self._lock:
            paths = list(self._write_conns)
        errors = []
        for abs_path in paths:
            try:
                self._close_path_connection(self._write_conns, abs_path)
            except pyodbc.Error as exc:
                errors.append(exc)
        self._raise_close_errors(errors)

    def close_database(self, db_path: str) -> None:
        abs_path = os.path.normcase(os.path.abspath(db_path))
        path_lock = self._get_path_lock(abs_path)
        with path_lock:
            with self._lock:
                errors = []
                for pool in (self._read_conns, self._write_conns):
                    try:
                        self._close_single(pool, abs_path)
                    except pyodbc.Error as exc:
                        errors.append(exc)
                self._writer_read_paths.discard(abs_path)
                self._raise_close_errors(errors)

    def close(self) -> None:
        with self._lock:
            paths = set(self._read_conns) | set(self._write_conns)
        errors = []
        for abs_path in paths:
            try:
                self.close_database(abs_path)
            except (pyodbc.Error, ExceptionGroup) as exc:
                errors.append(exc)
        self._raise_close_errors(errors)
        with self._lock:
            self._path_locks.clear()
            self._unhealthy_connection_ids.clear()
            self._writer_read_paths.clear()

    def _get_path_lock(self, abs_path: str):
        with self._lock:
            return self._path_locks.setdefault(abs_path, threading.RLock())

    def _close_path_connection(self, pool: dict, abs_path: str) -> None:
        path_lock = self._get_path_lock(abs_path)
        with path_lock:
            with self._lock:
                self._close_single(pool, abs_path)

    def _close_single(self, pool: dict, abs_path: str) -> None:
        conn = pool.get(abs_path)
        if conn is not None:
            conn.close()
            if pool.get(abs_path) is conn:
                pool.pop(abs_path)
            self._unhealthy_connection_ids.discard(id(conn))

    @staticmethod
    def _raise_close_errors(errors: list[BaseException]) -> None:
        if not errors:
            return
        if len(errors) == 1:
            raise errors[0]
        raise ExceptionGroup("Failed to close MDB connections", errors)

    @staticmethod
    def _is_client_task_exhaustion(exc: pyodbc.OperationalError) -> bool:
        messages = [str(arg) for arg in exc.args]
        messages.append(str(exc))
        combined = " ".join(messages).casefold()
        return "08004" in combined and (
            "-1036" in combined or "too many client tasks" in combined
        )

    @staticmethod
    def _connection_requires_replacement(conn, exc: pyodbc.Error) -> bool:
        if any(str(arg).strip().upper().startswith("08") for arg in exc.args):
            return True
        try:
            cursor = conn.cursor()
            cursor.close()
        except pyodbc.Error:
            return True
        return False
