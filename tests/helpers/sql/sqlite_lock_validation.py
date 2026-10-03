"""SQLite evaluation of the SQL writer's lock-validation and operation-prepare SQL.
``strict_sql_fakes`` models pyodbc protocol rules but never executes T-SQL, so a
fake that answers the writer's lock-validation batch with a scripted row proves
only the Python mapping of the returned row. This module runs the SQL the writer
REALLY sent against rows described by a ``LockDatabase``: the ``Violations`` CTE of
``SqlProjectWriter._validate_mutation_locks`` (item/bid/child owner, active
editor, token, rowversion and bid_locked branches, their priorities and every
bound parameter) and the marker/session-liveness SELECT of ``_prepare_mutation``.
What is real: the statement text and the parameter binding order the writer sent
(a swapped or missing parameter changes the answer), the three-valued NULL logic,
JOIN/LEFT JOIN semantics, UNION ALL and ORDER BY of the production predicates.
What is not: sqlite is not T-SQL. The translation only strips table hints, the
``N`` string prefix, the ``@`` of table variables, ``CONVERT`` casts and ``TOP``;
``SYSUTCDATETIME()``/``DATEADD`` are replaced by Python functions bound to ONE
injectable server clock (``LockDatabase.now``, never the client clock);
text columns use BINARY (case-sensitive) comparison, the STRICTEST collation: a statement
that is correct here is correct under SQL Server's default case-insensitive collation too
and does not rely on it;
there is no locking, snapshot isolation, rowversion generation, or datetime2
precision. Anything the translator cannot handle raises ``LockSqlTranslationError``
(fail closed) so a rewritten production statement cannot pass silently. It proves
the predicate logic, never that SQL Server accepts the text (UNVERIFIED against a
live server).
"""

from __future__ import annotations
import json
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
_CTE = re.compile(r"WITH Violations AS \(.*?\) SELECT TOP \(1\)[^;]*$", re.DOTALL)


class LockSqlTranslationError(AssertionError):
    """The writer's statement no longer has the shape this evaluator understands."""

    pass


def _stamp(value: datetime) -> str:
    return value.strftime(_FORMAT)[:-3]


def _dateadd(unit, amount, stamp):
    if str(unit).lower() != "second":
        raise LockSqlTranslationError(f"unsupported DATEADD unit {unit!r}")
    if stamp is None:
        return None
    moment = datetime.strptime(stamp, _FORMAT)
    return _stamp(moment + timedelta(seconds=int(amount)))


class LockDatabase:
    """Rows of ostv.Sessions/Locks/Presence/EntityVersions/ChangeTransactions and
    dbo.Bids/JobStatuses at one injected server instant."""

    # Every column the sqlite tables define: a test checks they all exist in the
    # canonical schema, so the evaluation cannot pass on a column SQL Server lacks.
    COLUMNS = {
        ("ostv", "Sessions"): (
            "SessionId",
            "DisplayName",
            "DisconnectedAt",
            "LastHeartbeatAt",
        ),
        ("ostv", "Locks"): (
            "ResourceType",
            "ResourceId",
            "BidUID",
            "OwnerSessionId",
            "LockToken",
            "ExpiresAt",
        ),
        ("ostv", "Presence"): ("SessionId", "BidUID", "ActivityMode"),
        ("ostv", "EntityVersions"): ("ResourceType", "ResourceId", "Token"),
        ("ostv", "ChangeTransactions"): (
            "TransactionId",
            "OperationType",
            "RequestHash",
            "ResultFormatVersion",
            "ResultPayload",
        ),
        ("dbo", "Bids"): ("UID", "JobStatusUID"),
        ("dbo", "JobStatuses"): ("UID", "Locked"),
    }

    def __init__(self, now: Optional[datetime] = None) -> None:
        self.now = now or datetime(2026, 1, 1, 12, 0, 0)
        self.sessions: list[tuple] = []
        self.locks: list[tuple] = []
        self.presence: list[tuple] = []
        self.versions: list[tuple] = []
        self.transactions: list[tuple] = []
        self.bids: list[tuple] = []
        self.statuses: list[tuple] = []

    def at(self, seconds: float) -> str:
        """Server-time stamp ``seconds`` after (positive) or before (negative) now."""
        return _stamp(self.now + timedelta(seconds=seconds))

    def add_session(
        self,
        session_id: str,
        display_name: str,
        *,
        heartbeat_age: float = 0,
        disconnected: bool = False,
    ) -> "LockDatabase":
        self.sessions.append(
            (
                session_id,
                display_name,
                self.at(0) if disconnected else None,
                self.at(-heartbeat_age),
            )
        )
        return self

    def add_lock(
        self,
        resource_type: str,
        resource_id: str,
        owner: str,
        token: str,
        *,
        bid_uid: Optional[int] = None,
        expires_in: float = 60,
    ) -> "LockDatabase":
        self.locks.append(
            (
                resource_type,
                resource_id,
                bid_uid,
                owner,
                token.upper(),
                self.at(expires_in),
            )
        )
        return self

    def add_presence(
        self, session_id: str, bid_uid: Optional[int], mode: str
    ) -> "LockDatabase":
        self.presence.append((session_id, bid_uid, mode))
        return self

    def add_version(
        self, resource_type: str, resource_id: str, token: bytes
    ) -> "LockDatabase":
        self.versions.append((resource_type, resource_id, token))
        return self

    def add_marker(
        self,
        operation_id: str,
        operation_type: str,
        request_hash: str,
        format_version: int,
        payload: str,
    ) -> "LockDatabase":
        self.transactions.append(
            (operation_id, operation_type, request_hash, format_version, payload)
        )
        return self

    def set_bid(self, bid_uid: int, job_status_uid: Optional[int]) -> "LockDatabase":
        self.bids.append((bid_uid, job_status_uid))
        return self

    def set_status(self, uid: int, locked: Optional[int]) -> "LockDatabase":
        if locked not in (None, 0, 1):
            raise ValueError("JobStatuses.Locked is a nullable bit")
        self.statuses.append((uid, locked))
        return self

    def _connect(self) -> sqlite3.Connection:
        database = sqlite3.connect(":memory:")
        database.create_function("SYSUTCDATETIME", 0, lambda: self.at(0))
        database.create_function("DATEADD", 3, _dateadd)
        database.create_function("HEXBLOB", 1, lambda text: bytes.fromhex(text))
        database.execute("ATTACH DATABASE ':memory:' AS ostv")
        database.execute("ATTACH DATABASE ':memory:' AS dbo")
        nocase = "TEXT"
        database.execute(
            "CREATE TABLE ostv.Sessions (SessionId TEXT, "
            "DisplayName TEXT, DisconnectedAt TEXT, LastHeartbeatAt TEXT)"
        )
        database.execute(
            f"CREATE TABLE ostv.Locks (ResourceType {nocase}, ResourceId {nocase}, "
            f"BidUID INTEGER, OwnerSessionId {nocase}, LockToken {nocase}, "
            "ExpiresAt TEXT)"
        )
        database.execute(
            f"CREATE TABLE ostv.Presence (SessionId {nocase}, BidUID INTEGER, "
            "ActivityMode TEXT)"
        )
        database.execute(
            f"CREATE TABLE ostv.EntityVersions (ResourceType {nocase}, "
            f"ResourceId {nocase}, Token BLOB)"
        )
        database.execute(
            f"CREATE TABLE ostv.ChangeTransactions (TransactionId {nocase}, "
            "OperationType TEXT, RequestHash TEXT, ResultFormatVersion INTEGER, "
            "ResultPayload TEXT)"
        )
        database.execute("CREATE TABLE dbo.Bids (UID INTEGER, JobStatusUID INTEGER)")
        database.execute("CREATE TABLE dbo.JobStatuses (UID INTEGER, Locked INTEGER)")
        database.executemany(
            "INSERT INTO ostv.Sessions VALUES (?,?,?,?)", self.sessions
        )
        database.executemany("INSERT INTO ostv.Locks VALUES (?,?,?,?,?,?)", self.locks)
        database.executemany("INSERT INTO ostv.Presence VALUES (?,?,?)", self.presence)
        database.executemany(
            "INSERT INTO ostv.EntityVersions VALUES (?,?,?)", self.versions
        )
        database.executemany(
            "INSERT INTO ostv.ChangeTransactions VALUES (?,?,?,?,?)", self.transactions
        )
        database.executemany("INSERT INTO dbo.Bids VALUES (?,?)", self.bids)
        database.executemany("INSERT INTO dbo.JobStatuses VALUES (?,?)", self.statuses)
        return database

    @staticmethod
    def _common(sql: str) -> str:
        sql = re.sub(r"\s+WITH \(UPDLOCK, HOLDLOCK\)", "", sql)
        sql = sql.replace("N'", "'")
        sql = sql.replace("DATEADD(second,", "DATEADD('second',")
        sql = sql.replace("CONVERT(varbinary(8), NULL)", "NULL")
        sql = re.sub(
            r"LOWER\(CONVERT\(nvarchar\(36\), (\w+\.\[\w+\])\)\)", r"LOWER(\1)", sql
        )
        sql = re.sub(
            r"CONVERT\(nvarchar\(128\), (\w+\.\[\w+\])\)", r"CAST(\1 AS TEXT)", sql
        )
        for table in ("MutationResources", "RequiredTokens", "ExpectedVersions"):
            sql = sql.replace("@" + table, table)
        return sql

    def violation(self, sql: str, params: tuple) -> Optional[tuple]:
        """The single row (Kind, Owner, ExpectedOrdinal, ActualToken) the writer's
        validation statement returns for these rows, or None. The statement is run
        in two parts: its preamble (the three table variables filled from the three
        OPENJSON parameters) and its Violations CTE; both come from the text the
        writer really sent."""
        match = _CTE.search(sql)
        if match is None:
            raise LockSqlTranslationError("no Violations CTE in the statement")
        preamble = sql[: match.start()]
        preamble_markers = _count(preamble)
        cte = match.group(0)
        cte = cte.replace("SELECT TOP (1) ", "SELECT ")
        cte = cte.rstrip() + " LIMIT 1"
        translated = self._common(cte)
        for leftover in ("CONVERT(", "@", "TOP ", "UPDLOCK"):
            if leftover in translated:
                raise LockSqlTranslationError(f"untranslated {leftover!r}")
        cte_params = tuple(
            params[preamble_markers : preamble_markers + _count(match.group(0))]
        )
        database = self._connect()
        try:
            self._run_preamble(database, preamble, tuple(params[:preamble_markers]))
            return database.execute(translated, cte_params).fetchone()
        finally:
            database.close()

    _DECLARE = re.compile(r"^DECLARE @(\w+) TABLE \((.*)\)$", re.DOTALL)
    _INSERT = re.compile(r"^INSERT INTO @(\w+) (SELECT .*)$", re.DOTALL)
    _OPENJSON_WITH = re.compile(
        r"FROM OPENJSON\(\?\) WITH \((?P<spec>.*)\)$", re.DOTALL
    )
    _SPEC = re.compile(r"\[(\w+)\] \w+(?:\(\d+\))? '(\$\.\w+)'")

    def _run_preamble(self, database, preamble: str, params: tuple) -> None:
        remaining = list(params)
        for raw in preamble.split(";"):
            statement = raw.strip()
            if not statement or statement == "SET NOCOUNT ON":
                continue
            declare = self._DECLARE.match(statement)
            if declare is not None:
                columns = re.sub(r"nvarchar\(\d+\)", "TEXT", declare.group(2))
                columns = re.sub(r"varbinary\(\d+\)", "BLOB", columns)
                columns = re.sub(r"\bint\b", "INTEGER", columns)
                database.execute(f"CREATE TEMP TABLE {declare.group(1)} ({columns})")
                continue
            insert = self._INSERT.match(statement)
            if insert is None:
                raise LockSqlTranslationError(
                    f"unrecognised preamble: {statement[:60]}"
                )
            body = insert.group(2)
            with_clause = self._OPENJSON_WITH.search(body)
            if with_clause is not None:
                fields = self._SPEC.findall(with_clause.group("spec"))
                if not fields:
                    raise LockSqlTranslationError("OPENJSON WITH without columns")
                source = ", ".join(
                    f"json_extract(value, '{path}') AS [{name}]"
                    for name, path in fields
                )
                body = (
                    body[: with_clause.start()]
                    + f"FROM (SELECT {source} FROM json_each(?))"
                )
            else:
                body = body.replace("OPENJSON(?)", "json_each(?)")
            body = body.replace(
                "CONVERT(varbinary(8), [ExpectedTokenHex], 2)",
                "HEXBLOB([ExpectedTokenHex])",
            )
            if "OPENJSON" in body or "CONVERT(" in body:
                raise LockSqlTranslationError(f"untranslated preamble: {body[:60]}")
            if not remaining:
                raise LockSqlTranslationError("preamble has more parameters than bound")
            database.execute(
                f"INSERT INTO {insert.group(1)} {body}", (remaining.pop(0),)
            )
        if remaining:
            raise LockSqlTranslationError(
                "preamble consumed fewer parameters than bound"
            )

    def operation_context(self, sql: str, params: tuple, lock_result: int) -> tuple:
        """The row of the prepare batch: (lock result, marker columns..., 1/0 session
        alive) from the SELECT of ``_prepare_mutation``."""
        start = sql.index("SELECT @LockResult")
        head = sql[:start]
        skipped = _count(head)
        select = sql[start:].replace("@LockResult", str(int(lock_result)), 1)
        select = select.replace(
            "(VALUES (1)) seed([Value])", "(SELECT 1 AS [Value]) seed"
        )
        translated = self._common(select)
        if "@" in translated or "VALUES" in translated:
            raise LockSqlTranslationError("untranslated prepare statement")
        database = self._connect()
        try:
            return database.execute(translated, tuple(params[skipped:])).fetchone()
        finally:
            database.close()


def _count(sql: str) -> int:
    from tests.helpers.sql.strict_sql_fakes import count_parameter_markers

    return count_parameter_markers(sql)
