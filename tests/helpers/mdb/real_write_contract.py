"""sqlite stand-in that runs the production MdbWriter column contract.
The shared sqlite helpers in ``tests.helpers.mdb.operations`` skip the declared
required columns and the operation labels of ``_execute_insert_values`` and
``_execute_update_values``. ``RealContractOps`` delegates to the real MdbWriter
implementations instead, so a wrong required column, a missing optional-column
report or a wrong operation label becomes observable.
"""

import sqlite3
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from tests.helpers.mdb.operations import (
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteMdbOps,
    _SqliteSchema,
)


class RealContractSchema(_SqliteSchema):
    """sqlite schema that records skipped optional writes like the real one."""

    def __init__(self, connection):
        super().__init__(connection)
        self.skips = []

    def require_table(self, table):
        if self.optional_table_missing(table):
            raise RuntimeError(f"Missing table {table}")

    def log_optional_write_skip(self, table, column, operation):
        self.skips.append((table, column, operation))


class ListParamCursor(_SqliteCursorWrapper):
    """pyodbc accepts one list of parameters; the sqlite wrapper takes varargs."""

    def execute(self, query, *params):
        if len(params) == 1 and isinstance(params[0], (list, tuple)):
            params = tuple(params[0])
        return super().execute(query, *params)


class ListParamConnection(_SqliteConnectionWrapper):
    def cursor(self):
        return ListParamCursor(self._connection)


class RealContractOps(_SqliteMdbOps):
    _require_write_columns = MdbWriter._require_write_columns
    _filter_existing_write_values = MdbWriter._filter_existing_write_values
    _execute_insert_values = MdbWriter._execute_insert_values
    _execute_update_values = MdbWriter._execute_update_values

    def __init__(self, connection):
        super().__init__(connection)
        self._schema_ref = RealContractSchema(connection)

    def _connection(self, _db_path):
        return ListParamConnection(self._connection_ref)

    @property
    def skips(self):
        return self._schema_ref.skips


def contract_db(*ddl):
    conn = sqlite3.connect(":memory:")
    for statement in ddl:
        conn.execute(statement)
    return conn
