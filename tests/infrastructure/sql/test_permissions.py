from tests.helpers.sql.strict_sql_fakes import (
    StrictLeaseProxy,
    strict_cursor,
    strict_manager,
)
import contextlib
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    COLLABORATION_RESOURCE_CATALOG_CHECKSUM,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlAuthenticationMode,
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
                yield StrictLeaseProxy(
                    SimpleNamespace(cursor=lambda: self._cursor), autocommit=autocommit
                )

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
                current[:2] + ("READ_ONLY",) + current[3:],
            ),
        )
        self.assertFalse(read_only_database.can_edit(descriptor.database_id))
        stale_checksum = SqlDatabasePermissionProbe(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_PermissionManager(
                (1, 1, 1, 1, 1),
                (current[0], "0" * 64) + current[2:],
            ),
        )
        self.assertFalse(stale_checksum.can_edit(descriptor.database_id))
        unvalidated_mixed_writer = SqlDatabasePermissionProbe(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_PermissionManager(
                (1, 1, 1, 1, 1),
                current[:3] + ("mixed_application", "disabled") + current[5:],
            ),
        )
        self.assertFalse(unvalidated_mixed_writer.can_edit(descriptor.database_id))
        validated_mixed_writer = SqlDatabasePermissionProbe(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_PermissionManager(
                (1, 1, 1, 1, 1),
                current[:3]
                + (
                    "mixed_application",
                    "validated",
                    COLLABORATION_RESOURCE_CATALOG_CHECKSUM,
                )
                + current[6:],
            ),
        )
        self.assertTrue(validated_mixed_writer.can_edit(descriptor.database_id))
        incomplete_snapshot = SqlDatabasePermissionProbe(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_PermissionManager(
                (1, 1, 1, 1, 1),
                current[:5],
            ),
        )
        self.assertFalse(incomplete_snapshot.can_edit(descriptor.database_id))

    def test_sql_edit_probe_opens_read_only_autocommit_connection_for_descriptor(
        self,
    ):
        captured = []

        class _Cursor:
            def execute(self, sql, *_params):
                captured.append(sql)
                return self

            def fetchone(self):
                return (
                    1, 1, 1, 1, 1,
                    SQL_SCHEMA_V1.version,
                    SQL_SCHEMA_V1.checksum,
                    "READ_WRITE",
                    "ost_visualizer_only",
                    "disabled",
                    None,
                    1, 1, 1, 1,
                    len(SQL_CLIENT_DIRECT_WRITE_TABLES), 0, 0,
                    1, 1, 0, 0, 1,
                )  # fmt: skip

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return None

        class _Manager:
            requests = []
            autocommit_values = []

            @contextlib.contextmanager
            def connection(self, request, *, autocommit=False):
                self.requests.append(request)
                self.autocommit_values.append(autocommit)
                yield StrictLeaseProxy(
                    SimpleNamespace(cursor=_Cursor), autocommit=autocommit
                )

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        manager = _Manager()
        probe = SqlDatabasePermissionProbe(
            registry, _cleanup_support__CredentialStore(), connection_manager=manager
        )
        self.assertTrue(probe.can_edit(descriptor.database_id))
        self.assertEqual(len(manager.requests), 1)
        self.assertEqual(manager.requests[0].location, descriptor.sql_location)
        self.assertTrue(manager.requests[0].read_only)
        self.assertEqual(manager.autocommit_values, [True])
        self.assertEqual(len(captured), 1)
        self.assertIn("ostv_permission_snapshot", captured[0])

    def test_unknown_descriptor_and_missing_sql_password_are_read_only(self):
        class _NeverConnects:
            def connection(self, _request, *, autocommit=False):
                raise AssertionError("must not connect without a usable request")

        registry = DatabaseDescriptorRegistry()
        sql_auth = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(
                server="localhost",
                database="OSTV_TEST",
                authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                username="test-user",
            ),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(sql_auth)
        probe = SqlDatabasePermissionProbe(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_NeverConnects(),
        )
        self.assertFalse(probe.can_edit("not-a-registered-database"))
        self.assertFalse(probe.can_edit(sql_auth.database_id))

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


class PermissionsProbeContractTests(unittest.TestCase):
    """Survivors of the second-pass mutation sweep over permissions.py."""

    def _registry(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        return registry, descriptor

    def test_probe_owns_a_real_connection_manager_unless_one_is_injected(self):
        from ost_visualizer.infrastructure.sql.connection_manager import (
            SqlConnectionManager,
        )

        registry, _descriptor = self._registry()
        probe = SqlDatabasePermissionProbe(
            registry, _cleanup_support__CredentialStore()
        )
        self.assertIsInstance(probe._connections, SqlConnectionManager)
        injected = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        probe = SqlDatabasePermissionProbe(
            registry, _cleanup_support__CredentialStore(), connection_manager=injected
        )
        self.assertIs(probe._connections, injected)

    def test_can_edit_answers_with_real_booleans_for_grant_and_refusal(self):
        class _Manager:
            def __init__(self, error):
                self.error = error

            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                if self.error is not None:
                    raise self.error
                snapshot = _CanonicalCursor()
                yield StrictLeaseProxy(
                    SimpleNamespace(cursor=lambda: snapshot), autocommit=autocommit
                )

        registry, descriptor = self._registry()
        granted = SqlDatabasePermissionProbe(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_Manager(None),
        )
        self.assertIs(granted.can_edit(descriptor.database_id), True)
        refused = SqlDatabasePermissionProbe(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_Manager(
                SqlInfrastructureError(
                    SqlErrorDetails(SqlErrorCode.CONNECTION_FAILED, "unreachable")
                )
            ),
        )
        self.assertIs(refused.can_edit(descriptor.database_id), False)

    def test_only_infrastructure_failures_are_read_only_other_errors_propagate(self):
        class _Manager:
            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                raise RuntimeError("programming error must not be hidden")
                yield

        registry, descriptor = self._registry()
        probe = SqlDatabasePermissionProbe(
            registry, _cleanup_support__CredentialStore(), connection_manager=_Manager()
        )
        with self.assertRaisesRegex(RuntimeError, "must not be hidden"):
            probe.can_edit(descriptor.database_id)


class _CanonicalCursor:
    def execute(self, _sql, *_params):
        return self

    @staticmethod
    def fetchone():
        return (
            1, 1, 1, 1, 1,
            SQL_SCHEMA_V1.version,
            SQL_SCHEMA_V1.checksum,
            "READ_WRITE",
            "ost_visualizer_only",
            "disabled",
            None,
            1, 1, 1, 1,
            len(SQL_CLIENT_DIRECT_WRITE_TABLES), 0, 0,
            1, 1, 0, 0, 1,
        )  # fmt: skip

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None
