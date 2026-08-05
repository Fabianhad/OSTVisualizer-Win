import os
import threading
from contextlib import contextmanager
from typing import Dict, Generator
import pyodbc
from ..database.connection_wrapper import ConnectionWrapper


class WriteBlockedError(Exception):
    pass


class MdbConnectionManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._read_conns: Dict[str, pyodbc.Connection] = {}
        self._write_conns: Dict[str, pyodbc.Connection] = {}
        self._path_locks = {}
        self._active_leases: Dict[str, tuple[bool, int]] = {}
        self._write_blocked = False

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
        abs_path = os.path.abspath(db_path)
        path_lock = self._get_path_lock(abs_path)
        with path_lock:
            with self._lock:
                if not autocommit and self._write_blocked:
                    raise WriteBlockedError(
                        "Database writes are blocked while OST is active"
                    )
                active_lease = self._active_leases.get(abs_path)
                if active_lease is not None and active_lease[0] != autocommit:
                    raise RuntimeError(
                        "Nested MDB connection leases must use the same mode"
                    )
                pool = self._read_conns if autocommit else self._write_conns
                borrowed_write_connection = False
                conn = pool.get(abs_path)
                if autocommit and conn is None:
                    conn = self._write_conns.get(abs_path)
                    if conn is not None:
                        pool = self._write_conns
                        borrowed_write_connection = True
                if conn is not None:
                    try:
                        conn.cursor().close()
                    except pyodbc.Error:
                        self._close_single(pool, abs_path)
                        conn = None
                        if borrowed_write_connection:
                            pool = self._read_conns
                        borrowed_write_connection = False
                if conn is None:
                    conn_str = (
                        "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
                        f"DBQ={abs_path};"
                    )
                    conn = pyodbc.connect(conn_str, autocommit=autocommit)
                    pool[abs_path] = conn
                lease_depth = active_lease[1] + 1 if active_lease is not None else 1
                self._active_leases[abs_path] = (autocommit, lease_depth)
            wrapper = ConnectionWrapper(conn)
            try:
                try:
                    yield wrapper
                finally:
                    wrapper.close_cursors()
                    if borrowed_write_connection:
                        conn.rollback()
            except pyodbc.Error:
                with self._lock:
                    _active_mode, active_depth = self._active_leases[abs_path]
                    if active_depth == 1:
                        self._close_single(pool, abs_path)
                raise
            finally:
                with self._lock:
                    active_mode, depth = self._active_leases[abs_path]
                    depth -= 1
                    if depth:
                        self._active_leases[abs_path] = (active_mode, depth)
                    else:
                        self._active_leases.pop(abs_path)

    def close_write_connections(self) -> None:
        with self._lock:
            paths = list(self._write_conns)
        for abs_path in paths:
            self._close_path_connection(self._write_conns, abs_path)

    def close_read(self, db_path: str) -> None:
        abs_path = os.path.abspath(db_path)
        self._close_path_connection(self._read_conns, abs_path)

    def close_database(self, db_path: str) -> None:
        abs_path = os.path.abspath(db_path)
        path_lock = self._get_path_lock(abs_path)
        with path_lock:
            with self._lock:
                self._close_single(self._read_conns, abs_path)
                self._close_single(self._write_conns, abs_path)

    def close(self) -> None:
        with self._lock:
            paths = set(self._read_conns) | set(self._write_conns)
        for abs_path in paths:
            self.close_database(abs_path)
        with self._lock:
            self._path_locks.clear()

    def _get_path_lock(self, abs_path: str):
        with self._lock:
            return self._path_locks.setdefault(abs_path, threading.RLock())

    def _close_path_connection(self, pool: dict, abs_path: str) -> None:
        path_lock = self._get_path_lock(abs_path)
        with path_lock:
            with self._lock:
                self._close_single(pool, abs_path)

    @staticmethod
    def _close_single(pool: dict, abs_path: str) -> None:
        conn = pool.pop(abs_path, None)
        if conn is not None:
            try:
                conn.close()
            except pyodbc.Error:
                pass
