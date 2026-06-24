import logging
import os
import threading
from contextlib import contextmanager
from typing import Dict, Generator
import pyodbc

logger = logging.getLogger(__name__)


class WriteBlockedError(Exception):
    pass


class MdbConnectionManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._read_conns: Dict[str, pyodbc.Connection] = {}
        self._write_conns: Dict[str, pyodbc.Connection] = {}
        self._write_blocked = False

    def set_write_blocked(self, blocked: bool) -> None:
        self._write_blocked = blocked
        if blocked:
            self.close_write_connections()

    def is_write_blocked(self) -> bool:
        return self._write_blocked

    @contextmanager
    def connection(
        self, db_path: str, autocommit: bool = True
    ) -> Generator[pyodbc.Connection, None, None]:
        if not autocommit and self._write_blocked:
            raise WriteBlockedError("Database writes are blocked while OST is active")
        abs_path = os.path.abspath(db_path)
        pool = self._read_conns if autocommit else self._write_conns
        with self._lock:
            conn = pool.get(abs_path)
            if conn is not None:
                try:
                    conn.cursor().close()
                except pyodbc.Error:
                    self._close_single(pool, abs_path)
                    conn = None
            if conn is None:
                conn_str = (
                    "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
                    f"DBQ={abs_path};"
                )
                conn = pyodbc.connect(conn_str, autocommit=autocommit)
                pool[abs_path] = conn
        try:
            yield conn
        except pyodbc.Error:
            with self._lock:
                self._close_single(pool, abs_path)
            raise

    def close_write_connections(self) -> None:
        with self._lock:
            for conn in self._write_conns.values():
                try:
                    conn.close()
                except pyodbc.Error:
                    pass
            self._write_conns.clear()

    def close_read(self, db_path: str) -> None:
        abs_path = os.path.abspath(db_path)
        with self._lock:
            self._close_single(self._read_conns, abs_path)

    def close(self) -> None:
        with self._lock:
            for pool in (self._read_conns, self._write_conns):
                for conn in pool.values():
                    try:
                        conn.close()
                    except pyodbc.Error:
                        pass
                pool.clear()

    @staticmethod
    def _close_single(pool: dict, abs_path: str) -> None:
        conn = pool.pop(abs_path, None)
        if conn is not None:
            try:
                conn.close()
            except pyodbc.Error:
                pass
