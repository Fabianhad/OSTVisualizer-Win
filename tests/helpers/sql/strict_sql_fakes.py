"""Strict pyodbc / SQL Server stand-ins for the SQL infrastructure tests.
The permissive per-test fakes accept statements that a real server rejects.
This module models the pyodbc and T-SQL behaviours that production SQL code
must respect, without needing a live server:
* ``SET NOCOUNT ON`` is session scoped: once a batch ran it, ``cursor.rowcount``
  is ``-1`` for every later statement on that connection (and ``-1`` for any
  SELECT), so code that trusts ``rowcount`` is exposed.
* A closed cursor or closed connection raises ``pyodbc.ProgrammingError``.
* The number of ``?`` markers must equal the supplied parameters
  (``ProgrammingError``), and a request carries at most 2100 parameters
  (SQLSTATE 07002).
* Result sets are consumed in order: fetching from a statement without a
  result set raises ``ProgrammingError``; later sets are only reachable via
  ``nextset()``; a further statement on another cursor while rows of an earlier
  one are still unfetched raises ``Connection is busy`` (``MARS_Connection=no``).
* ``ALTER/CREATE DATABASE`` only run on an autocommit connection outside an
  explicit transaction (error 226); ``sp_getapplock ... N'Transaction'`` needs
  an open transaction; ``SET TRANSACTION ISOLATION LEVEL SNAPSHOT`` cannot be
  applied to a transaction that already accessed data (error 3951) and needs
  snapshot isolation enabled on the database (error 3952).
* Transaction-owned application locks are released at commit or rollback and
  conflict between connections (``sp_getapplock`` returns -1 on timeout).
* Application-lock acquisition order is recorded per connection:
  ``ApplockTable.order_inversions()`` lists every resource pair that two
  transactions requested in opposite orders (the classic two-lock deadlock).
* ``CHANGETABLE(CHANGES t, last_sync_version)`` with a ``last_sync_version`` below
  ``CHANGE_TRACKING_MIN_VALID_VERSION`` raises the SQL Server error instead of
  returning rows (set ``server.change_tracking_minimum`` to the version source).
* Every statement is routed through explicit rules: an unscripted statement
  raises ``StrictSqlViolation`` (whitelisting), and every table or INSERT column
  it names must exist in the canonical v1 catalog (``42S02`` / ``42S22``).
Limits: this is still a model, not SQL Server. It never executes T-SQL; the
rules decide what each recognised statement returns. It proves that production
code respects pyodbc/T-SQL protocol rules, not that the SQL text is correct.
"""

from __future__ import annotations
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Optional
from unittest.mock import patch
import pyodbc

MAX_PARAMETERS = 2100
# The DatabaseMetadata identity predicate written out literally (an oracle that
# does not import the production constant): exactly one OST Visualizer row, and
# that row is the metadata of THIS database incarnation.
EXPECTED_DATABASE_METADATA_PREDICATE = (
    "m.[Product]=N'OST Visualizer' AND "
    "(SELECT COUNT_BIG(*) FROM [ostv].[DatabaseMetadata] metadata_count "
    "WHERE metadata_count.[Product]=N'OST Visualizer')=1 AND "
    "m.[DatabaseGuid]=(SELECT database_guid FROM sys.database_recovery_status "
    "WHERE database_id=DB_ID())"
)
CONNECT_PATCH_TARGET = (
    "ost_visualizer.infrastructure.sql.connection_manager.pyodbc.connect"
)


class StrictSqlViolation(AssertionError):
    """The code under test broke a rule the strict fake enforces."""

    pass


def sql_server_error(
    state: str, message: str, native: Optional[int] = None, api: str = "SQLExecDirectW"
) -> pyodbc.Error:
    """Build a pyodbc.Error shaped like the ODBC Driver 18 diagnostics."""
    suffix = f" ({native})" if native is not None else ""
    text = (
        f"[{state}] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]"
        f"{message}{suffix} ({api})"
    )
    return pyodbc.Error(state, text)


def count_parameter_markers(sql: str) -> int:
    """Count ``?`` markers outside literals, comments and bracketed names."""
    count = 0
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if char == "'":
            index += 1
            while index < length:
                if sql[index] == "'":
                    if index + 1 < length and sql[index + 1] == "'":
                        index += 2
                        continue
                    break
                index += 1
        elif char == "[":
            index += 1
            while index < length and sql[index] != "]":
                index += 1
        elif sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            index = length if end < 0 else end + 1
        elif sql.startswith("--", index):
            end = sql.find("\n", index)
            index = length if end < 0 else end
        elif char == "?":
            count += 1
        index += 1
    return count


def flatten_parameters(args: tuple) -> tuple:
    """pyodbc accepts ``execute(sql, a, b)`` and ``execute(sql, [a, b])``."""
    if len(args) == 1 and isinstance(args[0], (list, tuple)):
        return tuple(args[0])
    return tuple(args)


def nocount_after(sql: str, current: bool) -> bool:
    state = current
    for match in re.finditer(r"SET\s+NOCOUNT\s+(ON|OFF)\b", sql, re.IGNORECASE):
        state = match.group(1).upper() == "ON"
    return state


_DML_STATEMENT = re.compile(r"(INSERT|UPDATE|DELETE|MERGE)\b", re.IGNORECASE)


def count_dml_result_sets(sql: str, nocount: bool) -> int:
    """Count-only result sets a batch produces while ``SET NOCOUNT`` is OFF.
    With NOCOUNT OFF every INSERT/UPDATE/DELETE/MERGE sends a rows-affected result
    that pyodbc exposes as a result set WITHOUT a cursor description: ``fetch*``
    raises ``ProgrammingError`` until ``nextset()`` has skipped it. A statement
    with an ``OUTPUT`` clause that is not ``OUTPUT ... INTO @table`` returns its
    rows first and is not counted. Approximation: statements are split at ``;``
    (the production batches contain no ';' inside literals) and every count is
    placed before the batch's real result sets. Opt-in per server
    (``StrictSqlServer.model_result_counts``)."""
    state = nocount
    count = 0
    for statement in sql.split(";"):
        text = statement.strip()
        toggle = re.match(r"SET\s+NOCOUNT\s+(ON|OFF)\b", text, re.IGNORECASE)
        if toggle:
            state = toggle.group(1).upper() == "ON"
            continue
        if state or _DML_STATEMENT.match(text) is None:
            continue
        returns_rows = re.search(r"\bOUTPUT\b", text, re.IGNORECASE) and not re.search(
            r"\bINTO\s+@", text, re.IGNORECASE
        )
        if not returns_rows:
            count += 1
    return count


_TABLE_REFERENCE = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO|MERGE)\s+\[(?P<schema>dbo|ostv)\]\.\[(?P<table>\w+)\]"
    r"|\b(?:FROM|JOIN|UPDATE|INTO|MERGE)\s+\[(?P<bare>\w+)\](?!\.)",
    re.IGNORECASE,
)
_INSERT_COLUMNS = re.compile(
    r"INSERT\s+INTO\s+\[(?P<schema>dbo|ostv)\]\.\[(?P<table>\w+)\]\s*\((?P<columns>[^)]*)\)",
    re.IGNORECASE,
)


def canonical_catalog() -> dict[tuple[str, str], frozenset[str]]:
    from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1

    catalog: dict[tuple[str, str], frozenset[str]] = {}
    for table in SQL_SCHEMA_V1.core_schema.tables:
        catalog[("dbo", table.name)] = frozenset(c.name for c in table.columns)
    for table in SQL_SCHEMA_V1.tables:
        catalog[(table.schema, table.name)] = frozenset(c.name for c in table.columns)
    return catalog


def catalog_error(sql: str, catalog: dict) -> Optional[pyodbc.Error]:
    """Return the error SQL Server raises for unknown tables or INSERT columns.
    Identifier comparison is case-insensitive (default collation)."""
    known_tables = {(s.casefold(), t.casefold()) for s, t in catalog}
    for match in _TABLE_REFERENCE.finditer(sql):
        schema = match.group("schema") or "dbo"
        table = match.group("table") or match.group("bare")
        if (schema.casefold(), table.casefold()) not in known_tables:
            return sql_server_error(
                "42S02", f"Invalid object name '{schema}.{table}'.", 208
            )
    columns_by_table = {
        (s.casefold(), t.casefold()): {c.casefold() for c in columns}
        for (s, t), columns in catalog.items()
    }
    for match in _INSERT_COLUMNS.finditer(sql):
        key = (match.group("schema").casefold(), match.group("table").casefold())
        known = columns_by_table.get(key)
        if known is None:
            continue
        for name in re.findall(r"\[(\w+)\]", match.group("columns")):
            if name.casefold() not in known:
                return sql_server_error("42S22", f"Invalid column name '{name}'.", 207)
    return None


@dataclass
class Reply:
    """What a recognised statement returns: result sets and/or an affected count."""

    result_sets: tuple = ()
    affected: int = -1
    columns: Optional[tuple] = None

    @staticmethod
    def rows(*rows, columns=None) -> "Reply":
        return Reply((tuple(rows),), columns=columns)

    @staticmethod
    def sets(*sets, columns=None) -> "Reply":
        return Reply(tuple(tuple(rows) for rows in sets), columns=columns)

    @staticmethod
    def dml(affected: int) -> "Reply":
        return Reply((), affected)


@dataclass
class Call:
    sql: str
    params: tuple
    connection: "StrictRawConnection"
    cursor: "StrictRawCursor"
    server: "StrictSqlServer"

    def json(self, index: int = 0):
        return json.loads(self.params[index])


Matcher = Callable[[str], bool]


def _matcher(pattern) -> Matcher:
    if callable(pattern):
        return pattern
    if isinstance(pattern, re.Pattern):
        return lambda sql: pattern.search(sql) is not None
    return lambda sql: pattern in sql


class StrictRawCursor:
    """Stands in for ``pyodbc.Cursor``."""

    def __init__(self, connection: "StrictRawConnection") -> None:
        self._connection = connection
        self.closed = False
        self.closed_explicitly = False
        self.timeout = 0
        self._sets: list[tuple] = []
        self._columns: Optional[tuple] = None
        self._position = 0
        self._set_index = 0
        self._rowcount = -1
        self.executed: list[tuple[str, tuple]] = []

    # -- pyodbc surface -------------------------------------------------
    def execute(self, sql, *args):
        self._require_open()
        server = self._connection.server
        params = flatten_parameters(args)
        markers = count_parameter_markers(sql)
        if markers != len(params):
            raise pyodbc.ProgrammingError(
                f"The SQL contains {markers} parameter markers, but "
                f"{len(params)} parameters were supplied",
                "HY000",
            )
        if len(params) > MAX_PARAMETERS:
            raise sql_server_error(
                "07002",
                "The incoming request has too many parameters. The server "
                f"supports a maximum of {MAX_PARAMETERS} parameters. Reduce the "
                "number of parameters and resend the request.",
                8003,
            )
        self._connection.raise_if_busy(self)
        self._connection.check_protocol(sql)
        problem = catalog_error(sql, server.catalog)
        if problem is not None and server.enforce_catalog:
            self._connection.log("execute", sql)
            raise problem
        self._connection.log("execute", sql)
        server.check_change_tracking(sql, params)
        self.executed.append((sql, params))
        self._reset_results()
        reply = server.dispatch(Call(sql, params, self._connection, self, server))
        self._connection.note_statement(sql)
        was_nocount = self._connection.nocount
        nocount = nocount_after(sql, self._connection.nocount)
        self._connection.nocount = nocount
        self._sets = [tuple(rows) for rows in reply.result_sets]
        if server.model_result_counts:
            leading = count_dml_result_sets(sql, was_nocount)
            self._sets = [None] * leading + self._sets
        self._columns = reply.columns
        self._position = 0
        self._set_index = 0
        self._rowcount = -1 if nocount or self._sets else reply.affected
        return self

    def fetchone(self):
        self._require_results()
        rows = self._sets[self._set_index]
        if self._position >= len(rows):
            return None
        row = rows[self._position]
        self._position += 1
        return row

    def fetchall(self):
        self._require_results()
        rows = self._sets[self._set_index]
        remaining = list(rows[self._position :])
        self._position = len(rows)
        return remaining

    def fetchmany(self, size=1):
        self._require_results()
        rows = self._sets[self._set_index]
        chunk = list(rows[self._position : self._position + size])
        self._position += len(chunk)
        return chunk

    def nextset(self):
        self._require_open()
        if self._set_index + 1 < len(self._sets):
            self._set_index += 1
            self._position = 0
            return True
        self._sets = []
        return False

    @property
    def rowcount(self):
        self._require_open()
        return self._rowcount

    @property
    def description(self):
        if not self._sets or self._sets[self._set_index] is None:
            return None
        width = (
            len(self._sets[self._set_index][0]) if self._sets[self._set_index] else 0
        )
        names = self._columns or tuple(f"c{i}" for i in range(width))
        return tuple((name, None, None, None, None, None, True) for name in names)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.closed_explicitly = True
        self._connection.log("cursor_close", "")
        self._connection.server.consume_fault("cursor_close")

    # -- helpers --------------------------------------------------------
    @property
    def has_unfetched_rows(self) -> bool:
        if self.closed or not self._sets:
            return False
        current = self._sets[self._set_index]
        if current is not None and self._position < len(current):
            return True
        return any(rows for rows in self._sets[self._set_index + 1 :] if rows)

    def _reset_results(self):
        self._sets = []
        self._columns = None

    def _require_open(self):
        if self.closed:
            raise pyodbc.ProgrammingError("Attempt to use a closed cursor.")
        if self._connection.closed:
            raise pyodbc.ProgrammingError("Attempt to use a closed connection.")

    def _require_results(self):
        self._require_open()
        if not self._sets or self._sets[self._set_index] is None:
            raise pyodbc.ProgrammingError("No results.  Previous SQL was not a query.")


class StrictRawConnection:
    """Stands in for ``pyodbc.Connection``."""

    def __init__(
        self, server: "StrictSqlServer", number: int, autocommit: bool
    ) -> None:
        self.server = server
        self.number = number
        self.autocommit = autocommit
        self.closed = False
        self.timeout = 0
        self.cursors: list[StrictRawCursor] = []
        self.nocount = False
        self.explicit_transaction = False
        self.transaction_has_data = False
        self.isolation = "READ COMMITTED"
        self.snapshot_violation = False
        self.commits = 0
        self.rollbacks = 0
        self.events: list[tuple[str, str]] = []

    def log(self, kind: str, detail: str) -> None:
        entry = (kind, detail)
        self.events.append(entry)
        self.server.events.append((self.number, kind, detail))

    def cursor(self):
        if self.closed:
            raise pyodbc.ProgrammingError("Attempt to use a closed connection.")
        cursor = StrictRawCursor(self)
        self.cursors.append(cursor)
        self.log("cursor_open", "")
        return cursor

    def commit(self):
        self._finish("commit")

    def rollback(self):
        self._finish("rollback")

    def getinfo(self, _info_type):
        return 0

    def close(self):
        if self.closed:
            return
        self.log("close", "")
        self.closed = True
        self.server.applocks.release(self)
        self.server.consume_fault("close")

    # -- protocol rules -------------------------------------------------
    @property
    def in_transaction(self) -> bool:
        if self.explicit_transaction:
            return True
        return (not self.autocommit) and self.transaction_has_data

    def raise_if_busy(self, executing: StrictRawCursor) -> None:
        for other in self.cursors:
            if other is not executing and other.has_unfetched_rows:
                raise sql_server_error(
                    "HY000", "Connection is busy with results for another command", 0
                )

    def check_protocol(self, sql: str) -> None:
        stripped = sql.lstrip().upper()
        without_literals = re.sub(r"'(?:[^']|'')*'", "''", sql)
        database_ddl = re.search(
            r"\b(ALTER|CREATE)\s+DATABASE\b", without_literals, re.IGNORECASE
        )
        if database_ddl:
            if not self.autocommit or self.explicit_transaction:
                raise sql_server_error(
                    "25000",
                    f"{database_ddl.group(1).upper()} DATABASE statement not allowed "
                    "within multi-statement transaction.",
                    226,
                )
        if re.search(r"@LockOwner\s*=\s*N'Transaction'", sql, re.IGNORECASE):
            if self.autocommit and not self.explicit_transaction:
                raise StrictSqlViolation(
                    "sp_getapplock with @LockOwner=N'Transaction' needs an open "
                    "transaction but the connection is in autocommit mode"
                )
        if self.snapshot_violation and not re.match(r"(SET|BEGIN)\b", stripped):
            raise sql_server_error(
                "42000",
                "Transaction failed because the statement was run under snapshot "
                "isolation but the transaction did not start in snapshot isolation. "
                "You cannot change the isolation level of the transaction to "
                "snapshot after the transaction has started unless the transaction "
                "was originally started under snapshot isolation level.",
                3951,
            )
        if self.isolation == "SNAPSHOT" and not self.server.snapshot_enabled:
            if not re.match(r"(SET|BEGIN)\b", stripped):
                raise sql_server_error(
                    "42000",
                    "Snapshot isolation transaction failed accessing database "
                    "because snapshot isolation is not allowed in this database.",
                    3952,
                )

    @staticmethod
    def _accesses_data(sql: str) -> bool:
        without_literals = re.sub(r"'(?:[^']|'')*'", "''", sql)
        return not re.fullmatch(
            r"\s*(?:SET\s+[^;]*;?\s*|BEGIN\s+TRAN(?:SACTION)?\s*;?\s*)+",
            without_literals,
            re.IGNORECASE,
        )

    def note_statement(self, sql: str) -> None:
        stripped = sql.lstrip().upper()
        if stripped.startswith("SET TRANSACTION ISOLATION LEVEL SNAPSHOT"):
            if self.explicit_transaction or self.transaction_has_data:
                self.snapshot_violation = True
            self.isolation = "SNAPSHOT"
            return
        if re.match(r"SET\s+TRANSACTION\s+ISOLATION\s+LEVEL", stripped):
            self.isolation = "READ COMMITTED"
            return
        if re.match(r"BEGIN\s+TRAN", stripped):
            self.explicit_transaction = True
            return
        if not self.autocommit and self._accesses_data(sql):
            self.transaction_has_data = True

    def _finish(self, kind: str) -> None:
        if self.closed:
            raise pyodbc.ProgrammingError("Attempt to use a closed connection.")
        self.log(kind, "")
        fault = self.server.consume_fault(kind)
        if kind == "commit":
            self.commits += 1
        else:
            self.rollbacks += 1
        if fault is not None and fault.get("committed", False):
            self._end_transaction()
            raise fault["error"]
        if fault is not None:
            raise fault["error"]
        self._end_transaction()

    def _end_transaction(self) -> None:
        self.explicit_transaction = False
        self.transaction_has_data = False
        self.snapshot_violation = False
        self.server.applocks.release(self)


class ApplockTable:
    """Transaction-owned ``sp_getapplock`` bookkeeping shared by connections."""

    def __init__(self) -> None:
        self.held: dict[str, list[tuple[StrictRawConnection, str]]] = {}
        self.log: list[tuple[int, str, str, int]] = []

    def acquire(self, connection: StrictRawConnection, resource: str, mode: str) -> int:
        holders = self.held.setdefault(resource, [])
        for owner, held_mode in holders:
            if owner is connection:
                continue
            if mode == "Exclusive" or held_mode == "Exclusive":
                self.log.append((connection.number, resource, mode, -1))
                return -1
        if not any(owner is connection for owner, _held in holders):
            holders.append((connection, mode))
        self.log.append((connection.number, resource, mode, 0))
        return 0

    def release(self, connection: StrictRawConnection) -> None:
        for resource in list(self.held):
            self.held[resource] = [
                item for item in self.held[resource] if item[0] is not connection
            ]
            if not self.held[resource]:
                del self.held[resource]

    def holders(self, resource: str) -> list[int]:
        return [owner.number for owner, _mode in self.held.get(resource, [])]

    def acquisition_orders(self) -> dict[int, list[str]]:
        """Per connection, the resources it requested, in first-request order.
        A refused request (-1) counts: on a real server it is a blocked wait
        while the transaction still holds every earlier lock."""
        orders: dict[int, list[str]] = {}
        for number, resource, _mode, _code in self.log:
            sequence = orders.setdefault(number, [])
            if resource not in sequence:
                sequence.append(resource)
        return orders

    def order_inversions(self) -> list[tuple[str, str, int, int]]:
        """Resource pairs two connections requested in opposite orders.
        Each item is ``(first, second, connection_a, connection_b)``: connection
        ``a`` requested ``first`` before ``second`` and ``b`` the other way
        round. Two transactions holding one lock each while waiting for the
        other's is the deadlock this exposes."""
        orders = self.acquisition_orders()
        found: list[tuple[str, str, int, int]] = []
        numbers = sorted(orders)
        for a_index, a in enumerate(numbers):
            for b in numbers[a_index + 1 :]:
                a_order, b_order = orders[a], orders[b]
                common = [item for item in a_order if item in b_order]
                for index, first in enumerate(common):
                    for second in common[index + 1 :]:
                        if b_order.index(first) > b_order.index(second):
                            found.append((first, second, a, b))
        return found


class StrictSqlServer:
    """Routes statements through explicit rules; owns connections and faults."""

    def __init__(self, *, enforce_catalog: bool = True, snapshot_enabled: bool = True):
        self.rules: list[tuple[Matcher, Callable[[Call], Optional[Reply]]]] = []
        self.connections: list[StrictRawConnection] = []
        self.connect_calls: list[dict] = []
        self.events: list[tuple[int, str, str]] = []
        self.applocks = ApplockTable()
        self.catalog = canonical_catalog()
        self.enforce_catalog = enforce_catalog
        self.snapshot_enabled = snapshot_enabled
        self._faults: dict[str, list[dict]] = {}
        self.connect_error: Optional[BaseException] = None
        # Source of CHANGE_TRACKING_MIN_VALID_VERSION for the CHANGETABLE rule;
        # None leaves CHANGETABLE unchecked (legacy tests that never poll).
        self.change_tracking_minimum: Optional[Callable[[], int]] = None
        # Opt-in protocol rule (see count_dml_result_sets): batches that leave
        # SET NOCOUNT OFF produce count-only result sets in front of their rows.
        self.model_result_counts = False

    # -- scripting ------------------------------------------------------
    def on(self, pattern, responder) -> "StrictSqlServer":
        """Register a rule; the first matching rule answers the statement."""
        if not callable(responder):
            reply = responder
            responder = lambda _call, _reply=reply: _reply  # noqa: E731
        self.rules.append((_matcher(pattern), responder))
        return self

    def fail(
        self,
        kind: str,
        error: BaseException,
        *,
        committed: bool = False,
        skip: int = 0,
    ):
        """Inject a failure for a ``commit``/``rollback``/``close``/``cursor_close``.
        ``skip`` lets that many earlier occurrences succeed first. ``committed``
        models a commit the server applied although the client saw an error
        (uncertain commit)."""
        self._faults.setdefault(kind, []).append(
            {"error": error, "committed": committed, "skip": skip}
        )

    def consume_fault(self, kind: str):
        queue = self._faults.get(kind)
        if not queue:
            return None
        fault = queue[0]
        if fault["skip"] > 0:
            fault["skip"] -= 1
            return None
        queue.pop(0)
        if kind in {"close", "cursor_close"}:
            raise fault["error"]
        return fault

    def check_change_tracking(self, sql: str, params: tuple) -> None:
        """Reject ``CHANGETABLE(CHANGES t, v)`` when ``v`` < the minimum valid version.
        SQL Server raises an error for a ``last_sync_version`` older than
        ``CHANGE_TRACKING_MIN_VALID_VERSION`` (the change history it would need was
        cleaned up); ``NULL`` is the only value that means "no checkpoint".
        Native number 22002 is quoted from memory of the SQL Server error list: no
        live server is available to confirm it, only the raise-instead-of-rows
        behaviour is modelled."""
        if self.change_tracking_minimum is None:
            return
        match = re.search(
            r"CHANGETABLE\s*\(\s*CHANGES\s+[^,]+,\s*(\?|NULL|-?\d+)\s*\)",
            sql,
            re.IGNORECASE,
        )
        if match is None:
            return
        token = match.group(1)
        if token.upper() == "NULL":
            return
        if token == "?":
            value = params[count_parameter_markers(sql[: match.start(1)])]
        else:
            value = int(token)
        if value is None:
            return
        minimum = int(self.change_tracking_minimum())
        if int(value) < minimum:
            raise sql_server_error(
                "42000",
                "Change tracking information for table is not available. The "
                f"minimum valid version is {minimum}, last synchronized version "
                f"is {int(value)}. Reinitialize the dataset.",
                22002,
            )

    def dispatch(self, call: Call) -> Reply:
        for matches, responder in self.rules:
            if matches(call.sql):
                outcome = responder(call) if callable(responder) else responder
                if outcome is None:
                    return Reply()
                if not isinstance(outcome, Reply):
                    raise StrictSqlViolation(
                        f"rule returned {type(outcome).__name__}, expected Reply"
                    )
                return outcome
        raise StrictSqlViolation(f"unscripted SQL statement: {call.sql[:240]!r}")

    # -- pyodbc.connect replacement ------------------------------------
    def connect(self, connection_string, *, autocommit=False, timeout=0):
        self.connect_calls.append(
            {
                "connection_string": connection_string,
                "autocommit": autocommit,
                "timeout": timeout,
            }
        )
        if self.connect_error is not None:
            raise self.connect_error
        connection = StrictRawConnection(self, len(self.connections) + 1, autocommit)
        self.connections.append(connection)
        return connection

    @contextmanager
    def patched(self):
        with patch(CONNECT_PATCH_TARGET, side_effect=self.connect):
            yield self

    def manager(self):
        from ost_visualizer.infrastructure.sql.connection_manager import (
            SqlConnectionManager,
        )

        return SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])

    # -- assertions -----------------------------------------------------
    def statements(self, connection: Optional[int] = None) -> list[str]:
        return [
            detail
            for number, kind, detail in self.events
            if kind == "execute" and (connection is None or number == connection)
        ]

    def event_kinds(self, connection: int) -> list[str]:
        return [kind for number, kind, _ in self.events if number == connection]

    def assert_everything_closed(self) -> None:
        for connection in self.connections:
            if not connection.closed:
                raise StrictSqlViolation(f"connection {connection.number} left open")
            for cursor in connection.cursors:
                if not cursor.closed:
                    raise StrictSqlViolation(
                        f"cursor on connection {connection.number} left open"
                    )


# -- reusable rules ------------------------------------------------------
def snapshot_transaction_rules(server: StrictSqlServer) -> StrictSqlServer:
    server.on("SET TRANSACTION ISOLATION LEVEL SNAPSHOT", Reply())
    server.on(re.compile(r"^\s*BEGIN TRANSACTION\s*$"), Reply())
    return server


def applock_rules(server: StrictSqlServer) -> StrictSqlServer:
    """Model the three production application-lock batches."""

    def single(call: Call):
        resource = call.params[0]
        mode = re.search(r"@LockMode=N'(\w+)'", call.sql).group(1)
        return Reply.rows((server.applocks.acquire(call.connection, resource, mode),))

    def batch(call: Call):
        results = []
        for item in call.json(0):
            code = server.applocks.acquire(
                call.connection, item["resource"], item["mode"]
            )
            results.append((item["ordinal"], code))
            if code < 0:
                break
        return Reply.rows(*results)

    server.on(lambda sql: "DECLARE @RequestedLocks TABLE" in sql, batch)
    server.on(
        lambda sql: "EXEC @result=sys.sp_getapplock" in sql
        and "@LockOwner=N'Transaction'" in sql
        and "@Result" not in sql,
        single,
    )
    return server


def collaboration_lock_batch_rule(server: StrictSqlServer) -> StrictSqlServer:
    """Model ``SqlCollaborationStore.acquire_locks``' single edit-lock batch.
    Takes the transaction application locks in payload order (as the real
    ``WHILE`` loop does) and answers the status/ordinal/token rows."""

    def acquire(call: Call):
        granted = []
        for item in call.json(0):
            resource = f"OSTV:{item['resource_type']}:{item['resource_id']}"
            code = server.applocks.acquire(call.connection, resource, "Exclusive")
            if code < 0:
                return Reply.rows((-1, -1, None, None))
            granted.append(item)
        return Reply.rows(
            *((0, item["ordinal"], None, item["lock_token"]) for item in granted)
        )

    server.on("DECLARE @Requested TABLE", acquire)
    return server


# -- proxy for the legacy canned fakes -----------------------------------
class StrictCursorProxy:
    """Adds the protocol rules above to an existing canned cursor fake."""

    def __init__(self, lease: "StrictLeaseProxy", inner, exit_hook=None) -> None:
        self._lease = lease
        self._inner = inner
        self._exit_hook = exit_hook
        self.closed = False

    def _require_open(self):
        if self.closed:
            raise pyodbc.ProgrammingError("Attempt to use a closed cursor.")
        if self._lease.closed:
            raise pyodbc.ProgrammingError("Attempt to use a closed connection.")

    def execute(self, sql, *args):
        self._require_open()
        params = flatten_parameters(args)
        markers = count_parameter_markers(sql)
        if markers != len(params):
            raise pyodbc.ProgrammingError(
                f"The SQL contains {markers} parameter markers, but "
                f"{len(params)} parameters were supplied",
                "HY000",
            )
        if len(params) > MAX_PARAMETERS:
            raise sql_server_error(
                "07002", "The incoming request has too many parameters.", 8003
            )
        problem = catalog_error(sql, self._lease.catalog)
        if problem is not None:
            raise problem
        if re.search(
            r"\b(ALTER|CREATE)\s+DATABASE\b",
            re.sub(r"'(?:[^']|'')*'", "''", sql),
            re.IGNORECASE,
        ):
            if not self._lease.autocommit:
                raise sql_server_error(
                    "25000", "DATABASE statement not allowed within a transaction.", 226
                )
        if re.search(r"@LockOwner\s*=\s*N'Transaction'", sql, re.IGNORECASE):
            if self._lease.autocommit:
                raise StrictSqlViolation(
                    "transaction-owned application lock requested in autocommit mode"
                )
        self._lease.events.append(("execute", sql))
        self._lease.nocount = nocount_after(sql, self._lease.nocount)
        result = self._inner.execute(sql, *args)
        return self if result is self._inner or result is None else result

    def fetchone(self):
        self._require_open()
        return self._inner.fetchone()

    def fetchall(self):
        self._require_open()
        return self._inner.fetchall()

    def nextset(self):
        self._require_open()
        return self._inner.nextset()

    @property
    def rowcount(self):
        self._require_open()
        if self._lease.nocount:
            return -1
        return self._inner.rowcount

    @property
    def description(self):
        self._require_open()
        return self._inner.description

    def close(self):
        if self.closed:
            return
        self.closed = True
        self._lease.events.append(("cursor_close", ""))
        if self._exit_hook is not None:
            self._exit_hook()
            return
        close = getattr(self._inner, "close", None)
        if close is not None:
            close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False

    def __getattr__(self, name):
        return getattr(self._inner, name)


class StrictLeaseProxy:
    """Wraps a canned lease so cursors it hands out are protocol-checked."""

    def __init__(self, inner, *, autocommit: bool = False) -> None:
        self._inner = inner
        self.autocommit = autocommit
        self.closed = False
        self.nocount = False
        self.events: list[tuple[str, str]] = []
        self.cursor_proxies: list[StrictCursorProxy] = []
        self.catalog = canonical_catalog()

    def cursor(self):
        if self.closed:
            raise pyodbc.ProgrammingError("Attempt to use a closed connection.")
        raw = self._inner.cursor()
        exit_hook = None
        if not hasattr(raw, "execute") and hasattr(raw, "__enter__"):
            # a context-manager style stub: the cursor is what it yields
            context = raw
            raw = context.__enter__()
            exit_hook = lambda: context.__exit__(None, None, None)  # noqa: E731
        proxy = StrictCursorProxy(self, raw, exit_hook)
        self.cursor_proxies.append(proxy)
        return proxy

    def commit(self):
        self.events.append(("commit", ""))
        return self._inner.commit()

    def rollback(self):
        self.events.append(("rollback", ""))
        return self._inner.rollback()

    def close(self):
        self.closed = True

    def assert_cursors_closed(self) -> None:
        for proxy in self.cursor_proxies:
            if not proxy.closed:
                raise StrictSqlViolation("a cursor was left open")

    def __getattr__(self, name):
        return getattr(self._inner, name)


def strict_cursor(inner_cursor, *, autocommit: bool = False) -> StrictCursorProxy:
    """Protocol-check a stand-alone canned cursor (no connection around it)."""
    return StrictCursorProxy(
        StrictLeaseProxy(object(), autocommit=autocommit), inner_cursor
    )


@contextmanager
def strict_connection(inner_lease, *, autocommit: bool = False):
    lease = StrictLeaseProxy(inner_lease, autocommit=autocommit)
    try:
        yield lease
    finally:
        lease.close()


def strict_manager(inner_manager):
    """Wrap a canned ``connection()`` manager so every lease is protocol-checked."""

    class _Manager:
        def __init__(self) -> None:
            self.inner = inner_manager
            self.leases: list[StrictLeaseProxy] = []

        def __getattr__(self, name):
            return getattr(self.inner, name)

        @contextmanager
        def connection(self, request, *, autocommit=False):
            with self.inner.connection(request, autocommit=autocommit) as lease:
                proxy = StrictLeaseProxy(lease, autocommit=autocommit)
                self.leases.append(proxy)
                try:
                    yield proxy
                finally:
                    proxy.close()

    return _Manager()


# -- Bid lock rows for the writer's lock-validation batch -------------------
_BID_LOCK_BRANCH = re.compile(
    r"UNION ALL SELECT -1, N'bid_locked'.*?(?=\) SELECT TOP \(1\))", re.DOTALL
)


class BidLockState:
    """Bids.JobStatusUID and JobStatuses.Locked rows for the lock-validation batch.
    The writer's ``bid_locked`` Violations branch is NOT scripted by the test: the
    branch text is cut out of the statement the writer really sent and run on
    sqlite over tables built from this state and the statement's own
    @MutationResources payload, so the production predicate (join type, NULL
    handling, resource-type exemption, exemption flag) decides the answer.
    Limits: sqlite is not T-SQL (no bit type, no UPDLOCK, no READ COMMITTED
    blocking, no applock interplay); the translation only strips ``[dbo].``, the
    ``N`` string prefix and the ``@`` of the table variable. It checks the predicate's logic, not that SQL Server
    accepts the text. A statement without the branch yields no violation, so
    removing the check from the writer is observable."""

    def __init__(self) -> None:
        self.bid_status: dict[int, Optional[int]] = {}
        self.job_statuses: dict[int, Optional[int]] = {}

    def set_status(self, uid: int, locked: Optional[int]) -> "BidLockState":
        """A JobStatuses row; ``locked`` is the bit (0/1) or None for SQL NULL."""
        if locked not in (None, 0, 1):
            raise ValueError("JobStatuses.Locked is a nullable bit")
        self.job_statuses[int(uid)] = locked
        return self

    def set_bid(self, bid_uid: int, job_status_uid: Optional[int]) -> "BidLockState":
        """A Bids row; ``job_status_uid`` None is NULL, a UID with no JobStatuses
        row is a dangling reference."""
        self.bid_status[int(bid_uid)] = job_status_uid
        return self

    def violation_rows(self, call: Call) -> tuple:
        """Rows the ``bid_locked`` branch contributes to the Violations CTE, shaped
        like the final SELECT (Kind, Owner, ExpectedOrdinal, ActualToken)."""
        import sqlite3

        match = _BID_LOCK_BRANCH.search(call.sql)
        if match is None:
            return ()
        branch = match.group(0)
        markers = count_parameter_markers(branch)
        first = count_parameter_markers(call.sql[: match.start()])
        branch_params = tuple(call.params[first : first + markers])
        sqlite_sql = re.sub(r"\[dbo\]\.\[(\w+)\]", r"\1", branch)
        sqlite_sql = sqlite_sql.replace("N'", "'").replace(
            "@MutationResources", "MutationResources"
        )
        sqlite_sql = "SELECT " + sqlite_sql[len("UNION ALL SELECT ") :]
        database = sqlite3.connect(":memory:")
        try:
            database.execute("CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER)")
            database.execute("CREATE TABLE JobStatuses (UID INTEGER, Locked INTEGER)")
            database.execute(
                "CREATE TABLE MutationResources (Ordinal INTEGER, ResourceType TEXT, "
                "ResourceId TEXT, BidUID INTEGER)"
            )
            database.executemany(
                "INSERT INTO Bids VALUES (?, ?)", sorted(self.bid_status.items())
            )
            database.executemany(
                "INSERT INTO JobStatuses VALUES (?, ?)",
                sorted(self.job_statuses.items()),
            )
            database.executemany(
                "INSERT INTO MutationResources VALUES (?, ?, ?, ?)",
                [
                    (
                        item["ordinal"],
                        item["resource_type"],
                        item["resource_id"],
                        item["bid_uid"],
                    )
                    for item in call.json(0)
                ],
            )
            selected = database.execute(sqlite_sql, branch_params).fetchall()
        finally:
            database.close()
        return tuple((row[1], None, None, None) for row in selected)

    def validation_cursor(self) -> "_BidLockValidationCursor":
        """A cursor for ``SqlProjectWriter._validate_mutation_locks`` alone: it
        answers the lock-validation batch with this state's ``bid_locked`` rows and
        nothing else (every other Violations branch is out of scope here)."""
        return _BidLockValidationCursor(self)


class _BidLockValidationCursor:
    def __init__(self, state: BidLockState) -> None:
        self._state = state
        self._rows: tuple = ()
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, *args):
        params = flatten_parameters(args)
        if count_parameter_markers(sql) != len(params):
            raise pyodbc.ProgrammingError(
                "The SQL parameter markers do not match the parameters", "HY000"
            )
        self.executed.append((sql, params))
        call = Call(sql, params, None, None, None)  # type: ignore[arg-type]
        self._rows = self._state.violation_rows(call)
        return self

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass
