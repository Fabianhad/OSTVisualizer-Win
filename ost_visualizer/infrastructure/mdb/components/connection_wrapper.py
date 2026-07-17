import pyodbc


class _CursorLease:
    def __init__(self, owner: "ConnWrapper", cursor: pyodbc.Cursor) -> None:
        self._owner = owner
        self._cursor = cursor
        self._closed = False

    def __enter__(self) -> "_CursorLease":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()

    def execute(self, *args, **kwargs) -> "_CursorLease":
        self._cursor.execute(*args, **kwargs)
        return self

    def columns(self, *args, **kwargs) -> "_CursorLease":
        self._cursor.columns(*args, **kwargs)
        return self

    def tables(self, *args, **kwargs) -> "_CursorLease":
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
    def connection(self):
        return self._owner

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self):
        return self._cursor.rowcount


class ConnWrapper:
    def __init__(self, conn: pyodbc.Connection) -> None:
        self._conn = conn
        self._open_cursors: list[_CursorLease] = []

    def cursor(self, *args, **cursor_options) -> _CursorLease:
        cursor = _CursorLease(self, self._conn.cursor(*args, **cursor_options))
        self._open_cursors.append(cursor)
        return cursor

    def _unregister_cursor(self, cursor: _CursorLease) -> None:
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
