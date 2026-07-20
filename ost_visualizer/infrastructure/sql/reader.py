from __future__ import annotations
import logging
from contextlib import contextmanager
from typing import Generator, Optional
import pyodbc
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from ..mdb.mdb_reader import MdbReader
from .connection_manager import SqlConnectionLease, SqlConnectionManager
from .descriptor_connection import SqlDescriptorConnectionFactory
from .errors import SqlErrorCode, SqlErrorDetails, SqlInfrastructureError
from .schema_definition import SQL_SCHEMA_V1
from .schema_inspector import SqlSchemaInspector
from .schema_validator import SqlSchemaValidator
from .write_schema import CurrentSqlWriteSchema
from ..database.schema_inspector_contract import IDatabaseSchemaInspector


class SqlProjectReader(MdbReader):
    def __init__(
        self,
        descriptor_registry: IDatabaseDescriptorRegistry,
        credential_store: ICredentialStore,
        connection_manager: Optional[SqlConnectionManager] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self._descriptor_registry = descriptor_registry
        self._sql_connections = connection_manager or SqlConnectionManager()
        self._request_factory = SqlDescriptorConnectionFactory(
            descriptor_registry, credential_store
        )
        self._inspector = SqlSchemaInspector(self._sql_connections)
        self._validator = SqlSchemaValidator(SQL_SCHEMA_V1.core_schema)
        self._schema_contract = CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)

    @contextmanager
    def _connection(
        self, database_id: str
    ) -> Generator[SqlConnectionLease, None, None]:
        request = self._request_factory.request(database_id, read_only=True)
        with self._sql_connections.connection(request, autocommit=False) as lease:
            completed = False
            try:
                with lease.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL SNAPSHOT")
                    cursor.execute("BEGIN TRANSACTION")
                yield lease
                lease.commit()
                completed = True
            finally:
                if not completed:
                    try:
                        lease.rollback()
                    except pyodbc.Error:
                        pass

    def parse_file(self, database_id: str):
        with self._connection(database_id) as lease:
            return self.parse_file_connection(database_id, lease)

    def parse_file_connection(self, database_id: str, connection):
        report = self._validator.validate(
            self._inspector.inspect_connection(connection)
        )
        if not report.is_valid:
            raise SqlInfrastructureError(
                SqlErrorDetails(
                    SqlErrorCode.SCHEMA_MISMATCH,
                    report.user_message,
                )
            )
        hierarchy = self._parse_hierarchy(connection, database_id)
        cdn_types = self._parse_cdn_types(connection)
        descriptor = self._descriptor_registry.resolve(database_id)
        if descriptor is None:
            raise LookupError("The SQL Server database descriptor is not registered.")
        hierarchy.file_path = descriptor.database_id
        hierarchy.database_name = descriptor.display_name
        hierarchy.display_name = descriptor.display_name
        return hierarchy, cdn_types

    @staticmethod
    def _record_caught_read_error(
        _exc: BaseException, _locator: Optional[str] = None
    ) -> bool:
        """Prevent partial shared-reader results from escaping SQL snapshots."""
        return True

    def _schema(self, connection) -> IDatabaseSchemaInspector:
        del connection
        return self._schema_contract
