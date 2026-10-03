import contextlib
import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from ost_visualizer.domain.entities.database_descriptor import (
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
)
import tests.helpers.sql.integration_support as integration_support
import tests.integration.sql.test_collaboration_acceptance as collaboration_integration
from tests.helpers.sql.integration_support import (
    DisposableSqlConfiguration,
    DisposableSqlDatabase,
    _require_test_database_name,
)


class DisposableSqlConfigurationSafetyTests(unittest.TestCase):
    def test_general_opt_in_does_not_authorize_destructive_sql_tests(self):
        environment = {
            "OSTV_SQL_INTEGRATION": "1",
            "OSTV_SQL_TEST_SERVER": "tcp:localhost",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(unittest.SkipTest) as skipped:
                DisposableSqlConfiguration.from_environment()
        self.assertIn("destructive", str(skipped.exception).casefold())

    def test_nonlocal_server_is_never_accepted_by_the_local_harness(self):
        environment = {
            "OSTV_SQL_INTEGRATION": "1",
            "OSTV_SQL_DESTRUCTIVE_TESTS": "1",
            "OSTV_SQL_TEST_SERVER": "tcp:shared-server,1433",
            "OSTV_SQL_TEST_SERVER_MARKER": "test-marker",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(unittest.SkipTest) as skipped:
                DisposableSqlConfiguration.from_environment()
        self.assertIn("local", str(skipped.exception).casefold())

    def test_local_harness_accepts_an_explicit_nondefault_fixed_port(self):
        environment = {
            "OSTV_SQL_INTEGRATION": "1",
            "OSTV_SQL_DESTRUCTIVE_TESTS": "1",
            "OSTV_SQL_TEST_SERVER": "tcp:localhost,51433",
            "OSTV_SQL_TEST_SERVER_MARKER": "test-marker",
        }
        with patch.dict(os.environ, environment, clear=True):
            configuration = DisposableSqlConfiguration.from_environment()
        self.assertEqual(configuration.location.server, "tcp:localhost,51433")

    def test_local_harness_rejects_invalid_tcp_ports(self):
        for server in ("tcp:localhost,0", "tcp:localhost,65536", "localhost,bad"):
            environment = {
                "OSTV_SQL_INTEGRATION": "1",
                "OSTV_SQL_DESTRUCTIVE_TESTS": "1",
                "OSTV_SQL_TEST_SERVER": server,
                "OSTV_SQL_TEST_SERVER_MARKER": "test-marker",
            }
            with (
                self.subTest(server=server),
                patch.dict(os.environ, environment, clear=True),
            ):
                with self.assertRaises(unittest.SkipTest):
                    DisposableSqlConfiguration.from_environment()

    def test_database_name_guard_accepts_only_the_disposable_prefix(self):
        _require_test_database_name("OSTV_IT_20260718_abc123")
        for unsafe_name in (
            "production",
            "OSTV_IT_",
            "OSTV_IT_safe;DROP DATABASE production",
            "ostv_it_case_changed",
        ):
            with self.subTest(unsafe_name=unsafe_name):
                with self.assertRaises(RuntimeError):
                    _require_test_database_name(unsafe_name)

    def test_configuration_repr_redacts_all_connection_identity(self):
        environment = {
            "OSTV_SQL_INTEGRATION": "1",
            "OSTV_SQL_DESTRUCTIVE_TESTS": "1",
            "OSTV_SQL_TEST_SERVER": "tcp:localhost",
            "OSTV_SQL_TEST_SERVER_MARKER": "marker-must-not-appear",
        }
        with patch.dict(os.environ, environment, clear=True):
            configuration = DisposableSqlConfiguration.from_environment()
        rendered = repr(configuration)
        self.assertNotIn("localhost", rendered)
        self.assertNotIn("marker-must-not-appear", rendered)

    def test_cleanup_refuses_unsafe_name_before_any_sql_connection(self):
        database = self._database()
        database.database_name = "production"
        database.connections = MagicMock()
        with self.assertRaisesRegex(RuntimeError, "outside the OSTV_IT_ test scope"):
            database.drop()
        database.connections.connection.assert_not_called()

    def test_cleanup_stops_before_ddl_when_server_marker_is_invalid(self):
        database = self._database()
        database.connections = MagicMock()
        with patch.object(
            database,
            "_verify_server_marker",
            side_effect=RuntimeError("invalid server marker"),
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid server marker"):
                database.drop()
        database.connections.connection.assert_not_called()

    def test_cleanup_stops_before_ddl_when_database_marker_is_invalid(self):
        database = self._database()
        database.connections = MagicMock()
        with (
            patch.object(database, "_verify_server_marker"),
            patch.object(database, "_database_exists", return_value=True),
            patch.object(
                database,
                "_verify_database_marker",
                side_effect=RuntimeError("invalid database marker"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid database marker"):
                database.drop()
        database.connections.connection.assert_not_called()

    def test_client_factory_drops_login_when_database_user_setup_fails(self):
        disposable = self._database()
        database = MagicMock()
        database.location = disposable.location
        configuration = DisposableSqlConfiguration(
            disposable.location,
            "admin-password",
            "server-marker",
        )
        admin = MagicMock()
        admin_cursor = (
            admin.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        )
        with (
            patch(
                "tests.integration.sql.test_collaboration_acceptance.SqlConnectionManager",
                return_value=admin,
            ),
            patch(
                "tests.integration.sql.test_collaboration_acceptance."
                "apply_sql_client_permissions",
                side_effect=RuntimeError("permission setup failed"),
            ),
            self.assertRaisesRegex(RuntimeError, "permission setup failed"),
        ):
            collaboration_integration.SqlCollaborationIntegrationTests._create_test_client(
                database,
                configuration,
                "SETUP_FAILURE",
            )
        executed_sql = [call.args[0] for call in admin_cursor.execute.call_args_list]
        self.assertTrue(
            any(statement.startswith("DROP LOGIN") for statement in executed_sql)
        )

    @staticmethod
    def _database() -> DisposableSqlDatabase:
        location = SqlServerDatabaseLocation(
            server="tcp:localhost",
            database="master",
            authentication_mode=SqlAuthenticationMode.WINDOWS,
            encrypt=True,
            trust_server_certificate=False,
        )
        return DisposableSqlDatabase(
            DisposableSqlConfiguration(location, "", "server-marker")
        )


class FakeCursor:
    def __init__(self, owner):
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, sql, *params):
        self.owner.executed.append((sql, params))
        self.owner.current = list(self.owner.rows(sql, params))

    def fetchone(self):
        return self.owner.current.pop(0) if self.owner.current else None


class FakeLease:
    def __init__(self, owner):
        self.owner = owner
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return FakeCursor(self.owner)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakeConnections:
    """SqlConnectionManager replacement: records requests and statements only."""

    def __init__(self, rows=lambda sql, params: ()):
        self.rows = rows
        self.requests = []
        self.executed = []
        self.current = []
        self.leases = []

    @contextlib.contextmanager
    def connection(self, request, autocommit=False):
        self.requests.append((request, autocommit))
        lease = FakeLease(self)
        self.leases.append(lease)
        yield lease


SERVER_MARKER = "server-marker"


def _marker_rows(server=SERVER_MARKER, run=None, exists=True):
    def rows(sql, params):
        if "extended_properties" in sql:
            if params[0] == "OSTVisualizerDisposableTestServer":
                return [] if server is None else [(server,)]
            return [] if run is None else [(run,)]
        if "DB_ID" in sql:
            return [(7 if exists else None,)]
        return []

    return rows


class DisposableSqlConfigurationEnvironmentTests(unittest.TestCase):
    BASE = {
        "OSTV_SQL_INTEGRATION": "1",
        "OSTV_SQL_DESTRUCTIVE_TESTS": "1",
        "OSTV_SQL_TEST_SERVER": "tcp:localhost",
        "OSTV_SQL_TEST_SERVER_MARKER": "test-marker",
    }

    def configuration(self, **changes):
        environment = {**self.BASE, **changes}
        environment = {k: v for k, v in environment.items() if v is not None}
        with patch.dict(os.environ, environment, clear=True):
            return DisposableSqlConfiguration.from_environment()

    def skip_message(self, **changes):
        with self.assertRaises(unittest.SkipTest) as skipped:
            self.configuration(**changes)
        return str(skipped.exception)

    def test_every_missing_opt_in_skips_with_a_specific_reason(self):
        self.assertIn(
            "OSTV_SQL_INTEGRATION=1", self.skip_message(OSTV_SQL_INTEGRATION=None)
        )
        self.assertIn(
            "OSTV_SQL_INTEGRATION=1", self.skip_message(OSTV_SQL_INTEGRATION="0")
        )
        self.assertIn(
            "OSTV_SQL_DESTRUCTIVE_TESTS=1",
            self.skip_message(OSTV_SQL_DESTRUCTIVE_TESTS=None),
        )
        self.assertIn(
            "OSTV_SQL_DESTRUCTIVE_TESTS=1",
            self.skip_message(OSTV_SQL_DESTRUCTIVE_TESTS="true"),
        )
        self.assertIn(
            "OSTV_SQL_TEST_SERVER is not configured",
            self.skip_message(OSTV_SQL_TEST_SERVER="  "),
        )
        self.assertIn(
            "OSTV_SQL_TEST_SERVER_MARKER is not configured",
            self.skip_message(OSTV_SQL_TEST_SERVER_MARKER=" "),
        )
        self.assertIn(
            "must be 'windows' or 'sql'",
            self.skip_message(OSTV_SQL_TEST_AUTH="kerberos"),
        )

    def test_windows_authentication_builds_an_encrypted_verified_master_location(self):
        configuration = self.configuration()
        location = configuration.location
        self.assertEqual(location.server, "tcp:localhost")
        self.assertEqual(location.database, "master")
        self.assertEqual(location.authentication_mode, SqlAuthenticationMode.WINDOWS)
        self.assertEqual(location.username, "")
        self.assertTrue(location.encrypt)
        self.assertFalse(location.trust_server_certificate)
        self.assertEqual(configuration.password, "")
        self.assertEqual(configuration.server_marker, "test-marker")

    def test_sql_authentication_needs_a_user_and_a_stored_credential(self):
        sql_auth = {"OSTV_SQL_TEST_AUTH": "SQL"}
        self.assertIn(
            "requires OSTV_SQL_TEST_USER",
            self.skip_message(**sql_auth, OSTV_SQL_TEST_USER="tester"),
        )
        store = MagicMock()
        store.return_value.read_password.return_value = "stored-test-password"
        with patch.object(integration_support, "WindowsCredentialStore", store):
            self.assertIn(
                "requires OSTV_SQL_TEST_USER",
                self.skip_message(**sql_auth, OSTV_SQL_TEST_CREDENTIAL_TARGET="target"),
            )
            configuration = self.configuration(
                **sql_auth,
                OSTV_SQL_TEST_USER=" tester ",
                OSTV_SQL_TEST_CREDENTIAL_TARGET="target",
            )
        store.return_value.read_password.assert_called_with("target")
        self.assertEqual(configuration.password, "stored-test-password")
        self.assertEqual(configuration.location.username, "tester")
        self.assertEqual(
            configuration.location.authentication_mode, SqlAuthenticationMode.SQL_SERVER
        )
        self.assertNotIn("stored-test-password", repr(configuration))
        with patch.object(integration_support, "WindowsCredentialStore", store):
            store.return_value.read_password.return_value = None
            self.assertIn(
                "requires OSTV_SQL_TEST_USER",
                self.skip_message(
                    **sql_auth,
                    OSTV_SQL_TEST_USER="tester",
                    OSTV_SQL_TEST_CREDENTIAL_TARGET="target",
                ),
            )

    def test_only_explicit_localhost_targets_are_accepted(self):
        accepted = (
            "localhost",
            "tcp:localhost",
            "TCP:LocalHost,1433",
            "127.0.0.1",
            "tcp:127.0.0.1,51433",
            "tcp:localhost,65535",
            "  tcp:localhost,1  ",
        )
        for server in accepted:
            with self.subTest(accepted=server):
                self.assertEqual(
                    self.configuration(OSTV_SQL_TEST_SERVER=server).location.server,
                    server.strip(),
                )
        rejected = (
            "tcp:shared-server",
            "tcp:localhost.example.com",
            "tcp:127.0.0.1.example.com",
            "evil.localhost",
            "tcp:localhost,",
            "tcp:localhost,1433,2",
            "tcp:localhost\\SQLEXPRESS",
            "tcp:[::1]",
            "tcp:10.0.0.5",
            "tcp:0.0.0.0",
            "np:\\\\.\\pipe\\sql\\query",
            "tcp:localhost,123456",
            "tcp:localhost,0",
            "tcp:localhost,65536",
        )
        for server in rejected:
            with self.subTest(rejected=server):
                with self.assertRaises(unittest.SkipTest):
                    self.configuration(OSTV_SQL_TEST_SERVER=server)

    def test_configuration_repr_is_exactly_redacted(self):
        configuration = self.configuration()
        self.assertEqual(
            repr(configuration),
            "DisposableSqlConfiguration(location=<redacted>, "
            "password=<redacted>, server_marker=<redacted>)",
        )
        self.assertEqual(str(configuration), repr(configuration))


class DisposableSqlDatabaseContractTests(unittest.TestCase):
    def database(self, rows=None, **kwargs):
        location = SqlServerDatabaseLocation(
            server="tcp:localhost",
            database="master",
            authentication_mode=SqlAuthenticationMode.WINDOWS,
            encrypt=True,
            trust_server_certificate=False,
        )
        database = DisposableSqlDatabase(
            DisposableSqlConfiguration(location, "admin-password", SERVER_MARKER),
            **kwargs,
        )
        database.connections = FakeConnections(
            rows if rows is not None else _marker_rows(run=database.run_marker)
        )
        return database

    def test_generated_names_are_unique_safe_and_bounded(self):
        names = {self.database().database_name for _ in range(5)}
        self.assertEqual(len(names), 5)
        for name in names:
            _require_test_database_name(name)
            self.assertTrue(name.startswith("OSTV_IT_"))
            self.assertLessEqual(len(name), 128)

    def test_run_markers_are_random_per_database(self):
        first, second = self.database(), self.database()
        self.assertRegex(first.run_marker, r"^[0-9a-f]{32}$")
        self.assertNotEqual(first.run_marker, second.run_marker)
        self.assertTrue(first.database_name.endswith(first.run_marker[:12]))

    def test_database_name_guard_rejects_other_unsafe_shapes(self):
        for unsafe in (
            "OSTV_IT_a b",
            "OSTV_IT_a-b",
            "OSTV_IT_é",
            "OSTV_IT_a\n",
            "OSTV_IT_" + "a" * 121,
            "master",
            "",
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaisesRegex(
                    RuntimeError, "outside the OSTV_IT_ test scope"
                ):
                    _require_test_database_name(unsafe)
        _require_test_database_name("OSTV_IT_" + "a" * 120)

    def test_server_marker_must_match_before_any_database_is_created(self):
        for rows in (_marker_rows(server=None), _marker_rows(server="another-server")):
            with self.subTest(rows=rows):
                database = self.database(rows)
                with self.assertRaisesRegex(RuntimeError, "server marker is invalid"):
                    database._create_database()
                self.assertFalse(
                    any(
                        "CreateDatabase" in sql
                        for sql, _ in database.connections.executed
                    )
                )

    def test_create_refuses_unsafe_names_before_any_sql_connection(self):
        database = self.database()
        database.database_name = "production"
        with self.assertRaisesRegex(RuntimeError, "outside the OSTV_IT_ test scope"):
            database._create_database()
        self.assertEqual(database.connections.requests, [])

    def test_create_uses_the_stored_procedure_with_parameters_only(self):
        database = self.database()
        database._create_database()
        create = database.connections.executed[-1]
        self.assertEqual(
            create[0],
            "EXEC [ostv_it].[CreateDatabase] @DatabaseName=?, @RunMarker=?, "
            "@ExpectedServerMarker=?",
        )
        self.assertEqual(
            create[1], (database.database_name, database.run_marker, SERVER_MARKER)
        )
        self.assertFalse(
            any(
                "CREATE DATABASE" in sql.upper().replace("[OSTV_IT]", "")
                for sql, _ in database.connections.executed
            )
        )
        for request, autocommit in database.connections.requests:
            self.assertEqual(request.database_override, "master")
            self.assertTrue(autocommit)
        self.assertTrue(database.connections.requests[0][0].read_only)
        self.assertFalse(database.connections.requests[-1][0].read_only)

    def test_server_marker_query_is_parameterized_and_read_only(self):
        database = self.database()
        database._verify_server_marker()
        sql, params = database.connections.executed[0]
        self.assertEqual(params, ("OSTVisualizerDisposableTestServer",))
        self.assertNotIn("OSTVisualizerDisposableTestServer", sql)
        ((request, _autocommit),) = database.connections.requests
        self.assertTrue(request.read_only)
        self.assertEqual(request.password, "admin-password")

    def test_database_marker_must_match_this_runs_marker(self):
        for rows in (_marker_rows(run=None), _marker_rows(run="someone-elses-run")):
            with self.subTest(rows=rows):
                database = self.database(rows)
                with self.assertRaisesRegex(RuntimeError, "database marker is invalid"):
                    database._verify_database_marker()
        database = self.database()
        database._verify_database_marker()
        request, _ = database.connections.requests[0]
        self.assertEqual(request.location.database, database.database_name)
        self.assertTrue(request.read_only)

    def test_drop_skips_missing_databases_without_verifying_or_dropping(self):
        database = self.database(_marker_rows(exists=False))
        database.drop()
        statements = [sql for sql, _ in database.connections.executed]
        self.assertEqual(len(statements), 2)
        self.assertFalse(any("DropDatabase" in sql for sql in statements))

    def test_drop_uses_the_stored_procedure_after_both_markers_verify(self):
        database = self.database()
        database.drop()
        statements = database.connections.executed
        self.assertEqual(
            [
                ("extended_properties" in s, p[0] if p else "")
                for s, p in statements[:1]
            ],
            [(True, "OSTVisualizerDisposableTestServer")],
        )
        drop_sql, drop_params = statements[-1]
        self.assertEqual(
            drop_sql,
            "EXEC [ostv_it].[DropDatabase] @DatabaseName=?, @RunMarker=?, "
            "@ExpectedServerMarker=?",
        )
        self.assertEqual(
            drop_params, (database.database_name, database.run_marker, SERVER_MARKER)
        )
        self.assertFalse(any("DROP DATABASE" in s.upper() for s, _ in statements))

    def test_drop_refuses_a_database_owned_by_another_run(self):
        database = self.database(_marker_rows(run="another-run"))
        with self.assertRaisesRegex(RuntimeError, "database marker is invalid"):
            database.drop()
        self.assertFalse(
            any("DropDatabase" in sql for sql, _ in database.connections.executed)
        )

    def test_failed_setup_drops_the_database_only_when_ownership_was_proven(self):
        database = self.database(initialize_schema=True)
        with (
            patch.object(database, "_create_database"),
            patch.object(database, "_verify_server_marker"),
            patch.object(database, "_verify_database_marker"),
            patch.object(integration_support, "SqlDatabaseCreator") as creator,
            patch.object(database, "drop") as drop,
        ):
            creator.return_value.initialize_blank_database.side_effect = RuntimeError(
                "schema failed"
            )
            with self.assertRaisesRegex(RuntimeError, "schema failed"):
                database.__enter__()
        drop.assert_called_once_with()
        unproven = self.database()
        with (
            patch.object(unproven, "_create_database"),
            patch.object(unproven, "_verify_server_marker"),
            patch.object(
                unproven,
                "_verify_database_marker",
                side_effect=RuntimeError("invalid database marker"),
            ),
            patch.object(unproven, "drop") as unproven_drop,
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid database marker"):
                unproven.__enter__()
        unproven_drop.assert_not_called()

    def test_failed_setup_drops_a_proven_database_for_any_exception_type(self):
        # A setup failure that is not one of the anticipated infrastructure
        # errors (or a KeyboardInterrupt) must still not leak a proven database.
        for error in (
            TypeError("unexpected"),
            KeyError("unexpected"),
            KeyboardInterrupt(),
        ):
            with self.subTest(error=type(error).__name__):
                database = self.database()
                with (
                    patch.object(database, "_create_database"),
                    patch.object(database, "_verify_server_marker"),
                    patch.object(database, "_verify_database_marker"),
                    patch.object(integration_support, "SqlDatabaseCreator") as creator,
                    patch.object(database, "drop") as drop,
                ):
                    creator.return_value.initialize_blank_database.side_effect = error
                    with self.assertRaises(type(error)):
                        database.__enter__()
                drop.assert_called_once_with()

    def test_client_factory_verifies_the_server_marker_before_creating_a_login(self):
        database = MagicMock()
        database._verify_server_marker.side_effect = RuntimeError(
            "invalid server marker"
        )
        configuration = self.database().configuration
        admin = MagicMock()
        with (
            patch(
                "tests.integration.sql.test_collaboration_acceptance.SqlConnectionManager",
                return_value=admin,
            ),
            self.assertRaisesRegex(RuntimeError, "invalid server marker"),
        ):
            collaboration_integration.SqlCollaborationIntegrationTests._create_test_client(
                database, configuration, "NO_MARKER"
            )
        admin.connection.assert_not_called()

    def test_context_exit_always_drops_and_never_swallows_errors(self):
        database = self.database()
        with patch.object(database, "drop") as drop:
            self.assertIs(database.__exit__(None, None, None), False)
            self.assertIs(
                database.__exit__(ValueError, ValueError("body failed"), None), False
            )
        self.assertEqual(drop.call_count, 2)

    def test_blank_schema_uses_the_admin_password_and_records_the_location(self):
        database = self.database()
        created = SimpleNamespace(location="initialized-location")
        with (
            patch.object(database, "_create_database"),
            patch.object(database, "_verify_server_marker"),
            patch.object(database, "_verify_database_marker"),
            patch.object(database, "_create_test_roles") as roles,
            patch.object(integration_support, "SqlDatabaseCreator") as creator,
        ):
            creator.return_value.initialize_blank_database.return_value = created
            self.assertIs(database.__enter__(), database)
        creator.return_value.initialize_blank_database.assert_called_once_with(
            replace(database.configuration.location, database=database.database_name),
            "admin-password",
            application_version="integration-test",
            actor="OST Visualizer integration test",
        )
        self.assertEqual(database.location, "initialized-location")
        roles.assert_called_once_with()

    def test_test_roles_are_created_only_after_marker_checks_and_committed(self):
        database = self.database()
        database.location = database.configuration.location
        database._create_test_roles()
        statements = [sql for sql, _ in database.connections.executed]
        self.assertIn("extended_properties", statements[0])
        self.assertIn("extended_properties", statements[1])
        self.assertTrue(any("CREATE ROLE [ostv_it_reader]" in s for s in statements))
        self.assertTrue(database.connections.leases[-1].committed)
        self.assertFalse(database.connections.leases[-1].rolled_back)
        failing = self.database(_marker_rows(run="another-run"))
        with self.assertRaisesRegex(RuntimeError, "database marker is invalid"):
            failing._create_test_roles()
        self.assertFalse(
            any("CREATE ROLE" in s for s, _ in failing.connections.executed)
        )

    def test_failed_role_creation_rolls_back(self):
        database = self.database()
        database.location = database.configuration.location

        def rows(sql, params):
            if "CREATE ROLE" in sql:
                raise RuntimeError("role creation failed")
            return _marker_rows(run=database.run_marker)(sql, params)

        database.connections.rows = rows
        with self.assertRaisesRegex(RuntimeError, "role creation failed"):
            database._create_test_roles()
        lease = database.connections.leases[-1]
        self.assertTrue(lease.rolled_back)
        self.assertFalse(lease.committed)


if __name__ == "__main__":
    unittest.main()
