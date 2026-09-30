import contextlib
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.sql.client_permissions import (
    SQL_CLIENT_DATABASE_ROLES,
    SQL_CLIENT_DIRECT_WRITE_TABLES,
    _sql_integer_values_match,
    apply_sql_client_permissions,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from ost_visualizer.infrastructure.sql.permissions import SqlDatabasePermissionProbe
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from tests.helpers.sql.cleanup_support import (
    _CredentialStore as _cleanup_support__CredentialStore,
)


class PermissionsSqlCleanupTests(unittest.TestCase):
    def test_sql_edit_probe_requires_built_in_roles_and_collaboration_permissions(
        self,
    ):
        class _PermissionCursor:
            def __init__(
                self,
                role_result,
                metadata_result,
                collaboration_result=(
                    len(SQL_CLIENT_DIRECT_WRITE_TABLES),
                    0,
                    0,
                ),
                marker_result=(1, 1, 0, 0, 1),
            ):
                self._role_result = role_result
                self._metadata_result = metadata_result
                self._collaboration_result = collaboration_result
                self._marker_result = marker_result
                self._last_sql = ""

            def execute(self, sql, *_params):
                self._last_sql = sql
                return self

            def fetchone(self):
                if "ostv_permission_snapshot" in self._last_sql:
                    return (
                        *self._role_result,
                        *self._metadata_result,
                        *self._collaboration_result,
                        *self._marker_result,
                    )
                if "IS_ROLEMEMBER" in self._last_sql:
                    return self._role_result
                if "s.[name]=N'ostv'" in self._last_sql:
                    return self._collaboration_result
                if "VIEW CHANGE TRACKING" in self._last_sql:
                    return self._marker_result
                return self._metadata_result

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return None

        class _PermissionManager:
            def __init__(
                self,
                role_result,
                metadata_result,
                collaboration_result=(
                    len(SQL_CLIENT_DIRECT_WRITE_TABLES),
                    0,
                    0,
                ),
                marker_result=(1, 1, 0, 0, 1),
            ):
                self._cursor = _PermissionCursor(
                    role_result,
                    metadata_result,
                    collaboration_result,
                    marker_result,
                )

            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield SimpleNamespace(cursor=lambda: self._cursor)

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        current = (
            SQL_SCHEMA_V1.version,
            SQL_SCHEMA_V1.checksum,
            "READ_WRITE",
            "ost_visualizer_only",
            "disabled",
            None,
            1,
            1,
            1,
            1,
        )
        complete = SqlDatabasePermissionProbe(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_PermissionManager((1, 1, 1, 1, 1), current),
        )
        self.assertTrue(complete.can_edit(descriptor.database_id))
        for roles in (
            (0, 1, 1, 1, 1),
            (1, 0, 1, 1, 1),
            (1, 1, 1, 1, 0),
        ):
            with self.subTest(roles=roles):
                missing_role = SqlDatabasePermissionProbe(
                    registry,
                    _cleanup_support__CredentialStore(),
                    connection_manager=_PermissionManager(roles, current),
                )
                self.assertFalse(missing_role.can_edit(descriptor.database_id))
        malformed_role = SqlDatabasePermissionProbe(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_PermissionManager((1, 1, object(), 1, 1), current),
        )
        self.assertFalse(malformed_role.can_edit(descriptor.database_id))
        denied_change_log = SqlDatabasePermissionProbe(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_PermissionManager(
                (1, 1, 1, 1, 1),
                current,
                (len(SQL_CLIENT_DIRECT_WRITE_TABLES), 1, 0),
            ),
        )
        self.assertFalse(denied_change_log.can_edit(descriptor.database_id))
        writable_schema_ledger = SqlDatabasePermissionProbe(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_PermissionManager(
                (1, 1, 1, 1, 1),
                current,
                (len(SQL_CLIENT_DIRECT_WRITE_TABLES), 0, 1),
            ),
        )
        self.assertFalse(writable_schema_ledger.can_edit(descriptor.database_id))
        missing_marker_permission = SqlDatabasePermissionProbe(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_PermissionManager(
                (1, 1, 1, 1, 1),
                current,
                marker_result=(1, 1, 0, 0, 0),
            ),
        )
        self.assertFalse(missing_marker_permission.can_edit(descriptor.database_id))
        disabled_change_tracking = SqlDatabasePermissionProbe(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_PermissionManager(
                (1, 1, 1, 1, 1),
                current[:6] + (0, 0, 1, 1),
            ),
        )
        self.assertFalse(disabled_change_tracking.can_edit(descriptor.database_id))
        read_only_database = SqlDatabasePermissionProbe(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_PermissionManager(
                (1, 1, 1, 1, 1),
                (
                    SQL_SCHEMA_V1.version,
                    SQL_SCHEMA_V1.checksum,
                    "READ_ONLY",
                ),
            ),
        )
        self.assertFalse(read_only_database.can_edit(descriptor.database_id))

    def test_sql_edit_probe_treats_connection_failure_as_read_only(self):
        class _UnavailableConnection:
            def __enter__(self):
                raise SqlInfrastructureError(
                    SqlErrorDetails(
                        SqlErrorCode.CONNECTION_FAILED,
                        "The SQL Server is unavailable.",
                    )
                )

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

        class _UnavailableManager:
            def connection(self, _request, *, autocommit=False):
                del autocommit
                return _UnavailableConnection()

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        probe = SqlDatabasePermissionProbe(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_UnavailableManager(),
        )
        self.assertFalse(probe.can_edit(descriptor.database_id))
