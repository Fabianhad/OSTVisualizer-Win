from __future__ import annotations
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
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    CREDENTIAL_MISSING = "credential_missing"
    LOCKED = "locked"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SqlErrorDetails:
    code: SqlErrorCode
    user_message: str
    sql_state: str = ""
    native_code: Optional[int] = None


class SqlInfrastructureError(DatabaseCatalogError):
    def __init__(self, details: SqlErrorDetails) -> None:
        super().__init__(details.user_message)
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
    if "certificate" in text and (
        "not trusted" in text
        or "certificate chain" in text
        or "certificate verify failed" in text
    ):
        return SqlErrorDetails(
            SqlErrorCode.CERTIFICATE_FAILED,
            "SQL Server presented a certificate that Windows does not trust. "
            "OST Visualizer normally trusts the certificate supplied by configured "
            "SQL Server connections; reconnect the database or ask an administrator "
            "to install a trusted certificate.",
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
    if native_code == 4060 or "cannot open database" in text:
        return SqlErrorDetails(
            SqlErrorCode.DATABASE_MISSING,
            "The SQL Server is available, but the selected database is missing "
            "or cannot be opened.",
            sql_state,
            native_code,
        )
    if native_code in {229, 262, 297} or "permission" in text:
        return SqlErrorDetails(
            SqlErrorCode.PERMISSION_DENIED,
            "The SQL login does not have permission to perform this operation.",
            sql_state,
            native_code,
        )
    if sql_state in {"HYT00", "HYT01"} or "timeout" in text:
        return SqlErrorDetails(
            SqlErrorCode.TIMEOUT,
            "The SQL Server connection timed out.",
            sql_state,
            native_code,
        )
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


def _native_code(text: str) -> Optional[int]:
    for code in (18456, 4060, 10060, 10054, 297, 262, 233, 229, 64, 53):
        if f"({code})" in text or f" {code} " in text:
            return code
    return None
