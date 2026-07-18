from __future__ import annotations
import pyodbc
from typing import Protocol


class _CursorOwner(Protocol):
    def _unregister_cursor(self, cursor: "CursorLease") -> None: ...
class CursorLease:
    def __init__(self, owner: _CursorOwner, cursor: pyodbc.Cursor) -> None:
        self._owner = owner
        self._cursor = cursor
        self._closed = False

    def __enter__(self) -> "CursorLease":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()

    def execute(self, *args, **kwargs) -> "CursorLease":
        self._cursor.execute(*args, **kwargs)
        return self

    def columns(self, *args, **kwargs) -> "CursorLease":
        self._cursor.columns(*args, **kwargs)
        return self

    def tables(self, *args, **kwargs) -> "CursorLease":
        self._cursor.tables(*args, **kwargs)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._cursor.close()
        finally:
            self._owner._unregister_cursor(self)

    @property
    def connection(self) -> _CursorOwner:
        return self._owner

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self):
        return self._cursor.rowcount


class ConnectionWrapper:
    def __init__(self, connection, *, accepts_cursor_options: bool = True) -> None:
        self._conn = connection
        self._accepts_cursor_options = accepts_cursor_options
        self._open_cursors: list[CursorLease] = []

    def cursor(self, *args, **cursor_options) -> CursorLease:
        if not self._accepts_cursor_options and (args or cursor_options):
            raise TypeError("This database cursor does not accept cursor options")
        raw_cursor = (
            self._conn.cursor(*args, **cursor_options)
            if self._accepts_cursor_options
            else self._conn.cursor()
        )
        cursor = CursorLease(self, raw_cursor)
        self._open_cursors.append(cursor)
        return cursor

    def _unregister_cursor(self, cursor: CursorLease) -> None:
        if cursor in self._open_cursors:
            self._open_cursors.remove(cursor)

    def close_cursors(self) -> None:
        for cursor in list(self._open_cursors):
            try:
                cursor.close()
            except pyodbc.Error:
                pass
        self._open_cursors.clear()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def getinfo(self, info_type: int):
        return self._conn.getinfo(info_type)
