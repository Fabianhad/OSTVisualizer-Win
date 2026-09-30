import unittest
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import Mock, patch
import pyodbc
from ost_visualizer.application.interfaces.i_sql_database_creator import (
    SqlDatabaseCreationResult,
    SqlDatabaseRuntimeCredentials,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    validate_sql_database_creation_name,
    validate_sql_database_name,
)
from ost_visualizer.infrastructure.sql.client_provisioning import (
    SqlAuthenticatedClient,
    authenticate_runtime_client,
    provision_runtime_client,
    verify_runtime_client,
)
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from tests.helpers.sql.creation_handoff_support import (
    _CLIENT as _creation_handoff_support__CLIENT,
    _CREATOR as _creation_handoff_support__CREATOR,
    _Connections as _creation_handoff_support__Connections,
    _GUID as _creation_handoff_support__GUID,
    _Lease as _creation_handoff_support__Lease,
    _RUNTIME as _creation_handoff_support__RUNTIME,
    _error as _creation_handoff_support__error,
)


class ClientProvisioningRuntimeProvisioningTests(unittest.TestCase):
    def test_runtime_authentication_error_does_not_expose_driver_credentials(self):
        connections = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        request = SqlConnectionRequest(
            replace(_creation_handoff_support__CREATOR, username="client"),
            _creation_handoff_support__RUNTIME.password,
            database_override="master",
        )
        with patch(
            "ost_visualizer.infrastructure.sql.connection_manager.pyodbc.connect",
            side_effect=pyodbc.Error(
                "28000",
                f"Login failed: PWD={_creation_handoff_support__RUNTIME.password}",
            ),
        ), self.assertRaises(SqlInfrastructureError) as raised:
            authenticate_runtime_client(connections, request)
        self.assertEqual(
            raised.exception.details.code, SqlErrorCode.AUTHENTICATION_FAILED
        )
        self.assertNotIn(
            _creation_handoff_support__RUNTIME.password, str(raised.exception)
        )
        self.assertNotIn(
            _creation_handoff_support__RUNTIME.password, repr(raised.exception)
        )

    def test_login_mapping_is_parameterized_and_transactional(self):
        client = replace(
            _creation_handoff_support__CLIENT, login_name="client];--'name"
        )
        connections = _creation_handoff_support__Connections(
            [(0,), (_creation_handoff_support__GUID,), (client.sid,)]
        )
        provision_runtime_client(
            connections,
            SqlConnectionRequest(
                replace(
                    _creation_handoff_support__CREATOR,
                    database_guid=_creation_handoff_support__GUID,
                )
            ),
            client,
        )
        sql, parameters = connections.leases[0].statements[2]
        self.assertNotIn(client.login_name, sql)
        self.assertEqual(parameters, (client.login_name,))
        self.assertIn("QUOTENAME(@login)", sql)
        self.assertIn("DATABASE_PRINCIPAL_ID(@login) IS NOT NULL", sql)
        self.assertEqual(connections.leases[0].commits, 1)

    def test_missing_database_identity_prevents_any_provisioning(self):
        connections = _creation_handoff_support__Connections([(0,), None])
        with self.assertRaisesRegex(SqlInfrastructureError, "identity changed"):
            provision_runtime_client(
                connections,
                SqlConnectionRequest(_creation_handoff_support__CREATOR),
                _creation_handoff_support__CLIENT,
            )
        self.assertEqual(len(connections.leases[0].statements), 2)
        self.assertEqual(connections.leases[0].rollbacks, 1)

    def test_existing_user_failure_rolls_back_without_demoting_or_remapping(self):
        connections = _creation_handoff_support__Connections(
            [
                (0,),
                (_creation_handoff_support__GUID,),
                _creation_handoff_support__error(),
            ]
        )
        with self.assertRaises(SqlInfrastructureError):
            provision_runtime_client(
                connections,
                SqlConnectionRequest(_creation_handoff_support__CREATOR),
                _creation_handoff_support__CLIENT,
            )
        self.assertEqual(connections.leases[0].rollbacks, 1)
        self.assertEqual(len(connections.leases[0].statements), 3)

    def test_runtime_cannot_be_dbo_owner_or_ddl_admin(self):
        for user, owner, ddl in (("dbo", 0, 0), ("client", 1, 0), ("client", 0, 1)):
            with self.subTest(user=user, owner=owner, ddl=ddl):
                connections = _creation_handoff_support__Connections(
                    [
                        (_creation_handoff_support__GUID,),
                        (_creation_handoff_support__CLIENT.sid, user, owner, ddl),
                    ]
                )
                with self.assertRaisesRegex(
                    SqlInfrastructureError, "without database ownership"
                ):
                    verify_runtime_client(
                        connections,
                        SqlConnectionRequest(_creation_handoff_support__CREATOR),
                        _creation_handoff_support__CLIENT,
                    )

    def test_runtime_cannot_inherit_elevated_server_permissions(self):
        for permissions in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            connections = _creation_handoff_support__Connections(
                [
                    (
                        "client",
                        _creation_handoff_support__CLIENT.sid,
                        "test-server",
                        "S",
                    ),
                    permissions,
                ]
            )
            with self.assertRaisesRegex(
                SqlInfrastructureError, "privileges will not be changed"
            ):
                authenticate_runtime_client(
                    connections,
                    SqlConnectionRequest(_creation_handoff_support__CREATOR),
                )

    def test_group_only_windows_access_has_actionable_precreation_failure(self):
        connections = _creation_handoff_support__Connections(
            [
                (
                    "DOMAIN\\user",
                    _creation_handoff_support__CLIENT.sid,
                    "test-server",
                    None,
                )
            ]
        )
        with self.assertRaisesRegex(
            SqlInfrastructureError, "Group-only Windows access"
        ):
            authenticate_runtime_client(
                connections, SqlConnectionRequest(_creation_handoff_support__CREATOR)
            )
