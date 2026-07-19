from __future__ import annotations
import logging
from contextlib import contextmanager
from typing import Generator, Optional
from ...application.interfaces.i_credential_store import ICredentialStore
from ...application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from ..mdb.mdb_reader import MdbReader
from .connection_manager import SqlConnectionLease, SqlConnectionManager
from .descriptor_connection import SqlDescriptorConnectionFactory
from .errors import SqlErrorCode, SqlErrorDetails, SqlInfrastructureError
from .schema_definition import LATEST_SQL_SCHEMA
from .schema_inspector import SqlSchemaInspector
from .schema_validator import SqlSchemaValidator


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
        self._validator = SqlSchemaValidator(LATEST_SQL_SCHEMA.core_schema)

    @contextmanager
    def _connection(
        self, database_id: str
    ) -> Generator[SqlConnectionLease, None, None]:
        request = self._request_factory.request(database_id, read_only=True)
        with self._sql_connections.connection(request, autocommit=True) as lease:
            yield lease

    def parse_file(self, database_id: str):
        request = self._request_factory.request(database_id, read_only=True)
        report = self._validator.validate(self._inspector.inspect_request(request))
        if not report.is_read_compatible:
            raise SqlInfrastructureError(
                SqlErrorDetails(
                    SqlErrorCode.SCHEMA_MISMATCH,
                    report.user_message,
                )
            )
        hierarchy, cdn_types = MdbReader.parse_file(self, database_id)
        descriptor = self._descriptor_registry.resolve(database_id)
        if descriptor is None:
            raise LookupError("The SQL Server database descriptor is not registered.")
        hierarchy.file_path = descriptor.database_id
        hierarchy.database_name = descriptor.display_name
        hierarchy.display_name = descriptor.display_name
        return hierarchy, cdn_types
