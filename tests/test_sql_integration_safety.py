import os
import unittest
from unittest.mock import MagicMock, patch
from ost_visualizer.domain.entities.database_descriptor import (
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
)
from tests.sql_integration_support import (
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
        with self.assertRaises(RuntimeError):
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
            with self.assertRaises(RuntimeError):
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
            with self.assertRaises(RuntimeError):
                database.drop()
        database.connections.connection.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()
