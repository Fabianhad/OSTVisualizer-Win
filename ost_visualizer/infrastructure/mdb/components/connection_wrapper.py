import pyodbc


class ConnWrapper:
    def __init__(self, conn: pyodbc.Connection) -> None:
        self._conn = conn
        self._open_cursors: list = []

    def cursor(self, *args, **cursor_options) -> pyodbc.Cursor:
        cur = self._conn.cursor(*args, **cursor_options)
        self._open_cursors.append(cur)
        return cur

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
