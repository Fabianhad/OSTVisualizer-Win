from __future__ import annotations
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from ...application.interfaces.i_database_catalog import DatabaseCatalogError


class SqlErrorCode(str, Enum):
    CONNECTION_FAILED = "connection_failed"
    CERTIFICATE_FAILED = "certificate_failed"
    AUTHENTICATION_FAILED = "authentication_failed"
    DATABASE_MISSING = "database_missing"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT = "timeout"
    SCHEMA_MISMATCH = "schema_mismatch"
    CREDENTIAL_MISSING = "credential_missing"
    LOCKED = "locked"
    SESSION_EXPIRED = "session_expired"
    CONFLICT = "conflict"
    CONSTRAINT_FAILED = "constraint_failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SqlErrorDetails:
    code: SqlErrorCode
    user_message: str
    sql_state: str = ""
    native_code: Optional[int] = None


class SqlInfrastructureError(DatabaseCatalogError):
    def __init__(self, details: SqlErrorDetails) -> None:
        super().__init__(
            details.user_message,
            retryable=details.code
            in {
                SqlErrorCode.CONNECTION_FAILED,
                SqlErrorCode.TIMEOUT,
                SqlErrorCode.UNKNOWN,
            },
            session_expired=details.code == SqlErrorCode.SESSION_EXPIRED,
            credential_required=details.code
            in {
                SqlErrorCode.AUTHENTICATION_FAILED,
                SqlErrorCode.CREDENTIAL_MISSING,
            },
            read_only_required=details.code
            in {
                SqlErrorCode.PERMISSION_DENIED,
                SqlErrorCode.SCHEMA_MISMATCH,
            },
        )
        self.details = details


def sql_schema_mismatch(message: str) -> SqlInfrastructureError:
    return SqlInfrastructureError(
        SqlErrorDetails(SqlErrorCode.SCHEMA_MISMATCH, message)
    )


def classify_pyodbc_error(exc: BaseException) -> SqlErrorDetails:
    args = exc.args
    sql_state = str(args[0]) if args else ""
    text = " ".join(str(value) for value in args[1:]).casefold()
    native_code = _native_code(text)
    fallback = _fallback_messages(text, native_code)
    if sql_state.startswith("23"):
        return SqlErrorDetails(
            SqlErrorCode.CONSTRAINT_FAILED,
            "The requested change violates a SQL data-integrity rule.",
            sql_state,
            native_code,
        )
    if sql_state == "28000" or native_code == 18456:
        return SqlErrorDetails(
            SqlErrorCode.AUTHENTICATION_FAILED,
            "SQL Server rejected the supplied authentication credentials.",
            sql_state,
            native_code,
        )
    if native_code == 4060:
        return _database_missing(sql_state, native_code)
    if native_code in {229, 262, 297}:
        return _permission_denied(sql_state, native_code)
    if sql_state in {"HYT00", "HYT01"}:
        return _timeout(sql_state, native_code)
    if any(_CERTIFICATE_MESSAGE.match(message) for message in fallback):
        return SqlErrorDetails(
            SqlErrorCode.CERTIFICATE_FAILED,
            "SQL Server presented a certificate that Windows does not trust. "
            "OST Visualizer normally trusts the certificate supplied by configured "
            "SQL Server connections; reconnect the database or ask an administrator "
            "to install a trusted certificate.",
            sql_state,
            native_code,
        )
    if any(_DATABASE_MISSING_MESSAGE.match(message) for message in fallback):
        return _database_missing(sql_state, native_code)
    if any(_PERMISSION_DENIED_MESSAGE.match(message) for message in fallback):
        return _permission_denied(sql_state, native_code)
    if any(_TIMEOUT_MESSAGE.match(message) for message in fallback):
        return _timeout(sql_state, native_code)
    if sql_state.startswith("08") or native_code in {53, 64, 233, 10054, 10060}:
        return SqlErrorDetails(
            SqlErrorCode.CONNECTION_FAILED,
            "The SQL Server could not be reached. Check the server name, network, "
            "and SQL Server service.",
            sql_state,
            native_code,
        )
    return SqlErrorDetails(
        SqlErrorCode.UNKNOWN,
        "SQL Server returned an unexpected error.",
        sql_state,
        native_code,
    )


def _database_missing(sql_state: str, native_code: Optional[int]) -> SqlErrorDetails:
    return SqlErrorDetails(
        SqlErrorCode.DATABASE_MISSING,
        "The SQL Server is available, but the selected database is missing "
        "or cannot be opened.",
        sql_state,
        native_code,
    )


def _permission_denied(sql_state: str, native_code: Optional[int]) -> SqlErrorDetails:
    return SqlErrorDetails(
        SqlErrorCode.PERMISSION_DENIED,
        "The SQL login does not have permission to perform this operation.",
        sql_state,
        native_code,
    )


def _timeout(sql_state: str, native_code: Optional[int]) -> SqlErrorDetails:
    return SqlErrorDetails(
        SqlErrorCode.TIMEOUT,
        "The SQL Server connection timed out.",
        sql_state,
        native_code,
    )


_KNOWN_NATIVE_CODES = (18456, 4060, 10060, 10054, 297, 262, 233, 229, 64, 53)
_DIAGNOSTIC_NUMBER = re.compile(
    r"\((\d+)\)(?=\s*(?:\(SQL\w+\)\s*)?(?:;|$))", re.IGNORECASE
)


def _native_code(text: str) -> Optional[int]:
    reported = {int(number) for number in _DIAGNOSTIC_NUMBER.findall(text)}
    if reported:
        for code in _KNOWN_NATIVE_CODES:
            if code in reported:
                return code
        return None
    for code in _KNOWN_NATIVE_CODES:
        if f"({code})" in text or f" {code} " in text:
            return code
    return None


_CERTIFICATE_MESSAGE = re.compile(
    r"(?:(?:ssl|tls)\b[^:]{0,40}:\s*)?(?:(?:the|a)\s+)?certificate\b"
    r"(?: chain\b|[^.]*?(?:not trusted|verify failed))"
)
_DATABASE_MISSING_MESSAGE = re.compile(r"cannot open database\b")
_PERMISSION_DENIED_MESSAGE = re.compile(
    r"the user does not have permission\b"
    r"|(?:the )?[a-z][a-z ]{0,48}? permission (?:was )?denied\b"
)
_TIMEOUT_MESSAGE = re.compile(r"(?:(?:login|query|connection) )?timeout\b")
_RECORD_SEPARATOR = re.compile(r";\s*(?=\[\w{5}\]\s*\[)")
_DRIVER_PREFIX = re.compile(r"(?:\[[^\]]*\]\s*)+")


def _fallback_messages(text: str, native_code: Optional[int]) -> list[str]:
    reported = bool(_reported_numbers(text))
    if not reported and native_code is not None:
        return []
    messages = []
    for record in _RECORD_SEPARATOR.split(text):
        if _reported_numbers(record):
            continue
        messages.append(_DRIVER_PREFIX.sub("", record, count=1).strip())
    return messages


def _reported_numbers(text: str) -> set[int]:
    return {int(number) for number in _DIAGNOSTIC_NUMBER.findall(text)} - {0}
