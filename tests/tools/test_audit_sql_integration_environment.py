"""The SQL integration environment auditor, with the ODBC driver replaced by fakes.
Nothing here connects to a server: ``pyodbc.connect`` is patched for every test, the
backup directory is a temporary ``ProgramData`` tree and the query result is scripted.
The T-SQL itself is NOT verified here (no server); these tests pin the Python side of
the auditor: the connection it asks for, how each result column is named, which values
make the exit code non-zero, and that nothing is leaked or left open.
"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import audit_sql_integration_environment as audit

# Written independently of the auditor: the healthy state of the guarded environment,
# keyed by the name the auditor prints, in the order of the SELECT list.
HEALTHY_COUNTS = (
    ("test_databases", 0),
    ("temporary_logins", 0),
    ("active_application_sessions", 0),
    ("active_application_cursors", 0),
    ("server_markers", 1),
    ("guarded_procedures", 4),
    ("signed_guarded_procedures", 4),
    ("pending_restores", 0),
    ("executor_logins", 1),
    ("provisioning_certificates", 1),
    ("provisioning_certificate_logins", 1),
    ("executor_schema_execute_grants", 0),
    ("executor_object_execute_grants", 4),
    ("execute_as_modules", 0),
    ("persistent_client_databases", 1),
    ("persistent_client_markers", 1),
    ("persistent_client_logins", 1),
    ("active_client_collaboration_sessions", 0),
    ("client_presence_rows", 0),
    ("client_lock_rows", 0),
)
# One fragment of the SELECT text that identifies each column, in select order. The
# test below proves the fragments occur in this order, which ties the positional row
# indexes used by the auditor to the columns the SQL really returns.
SELECT_ORDER = (
    ("version", "SERVERPROPERTY('ProductVersion')"),
    ("edition", "SERVERPROPERTY('Edition')"),
    ("test_databases", "FROM sys.databases WHERE name COLLATE Latin1_General_100_BIN2"),
    ("temporary_logins", "LIKE N'OSTV_IT_TMP[_]%'"),
    ("active_application_sessions", "FROM sys.dm_exec_sessions WHERE"),
    ("active_application_cursors", "sys.dm_exec_cursors(0)"),
    ("server_markers", "AND name=N'OSTVisualizerDisposableTestServer'"),
    ("guarded_procedures", "FROM sys.procedures p JOIN sys.schemas s ON"),
    ("signed_guarded_procedures", "sys.crypt_properties"),
    ("pending_restores", "FROM [ostv_it].[PendingRestores]"),
    ("executor_logins", "WHERE name=N'OSTV_IT_EXECUTOR'"),
    ("provisioning_certificates", "SELECT COUNT(*) FROM sys.certificates"),
    ("provisioning_certificate_logins", "name=N'OSTV_IT_ProvisioningCertificateLogin'"),
    ("executor_schema_execute_grants", "dp.class=3"),
    ("executor_object_execute_grants", "dp.class=1"),
    ("execute_as_modules", "m.execute_as_principal_id IS NOT NULL"),
    ("persistent_client_databases", "WHERE name=N'OSTV_CLIENT_TEST'"),
    ("persistent_client_markers", "OSTVisualizerSqlDevelopmentDatabase"),
    ("persistent_client_logins", "name=N'OSTV_CLIENT_TEST_USER'"),
    ("active_client_collaboration_sessions", "[ostv].[Sessions]"),
    ("client_presence_rows", "[ostv].[Presence]"),
    ("client_lock_rows", "[ostv].[Locks]"),
)


class _Cursor:
    def __init__(self, owner):
        self._owner = owner
        self.closed = False

    def execute(self, sql, *parameters):
        self._owner.executed.append((sql, parameters))
        if self._owner.execute_error is not None:
            raise self._owner.execute_error

    def fetchone(self):
        return self._owner.row

    def close(self):
        self.closed = True


class _Connection:
    def __init__(self, row, execute_error=None):
        self.row = row
        self.execute_error = execute_error
        self.executed = []
        self.cursors = []
        self.closed = False

    def cursor(self):
        cursor = _Cursor(self)
        self.cursors.append(cursor)
        return cursor

    def close(self):
        self.closed = True


def _row(counts=None, version="17.0.1000.7", edition="Developer Edition"):
    values = dict(HEALTHY_COUNTS)
    values.update(counts or {})
    return (version, edition, *(values[name] for name, _expected in HEALTHY_COUNTS))


class AuditSqlIntegrationEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.program_data = tempfile.TemporaryDirectory()
        self.addCleanup(self.program_data.cleanup)
        self.backups = Path(self.program_data.name) / "OSTVisualizer"
        self.backups = self.backups / "SqlIntegrationBackups"
        self.backups.mkdir(parents=True)

    def run_audit(self, row=None, execute_error=None):
        connection = _Connection(_row() if row is None else row, execute_error)
        out = io.StringIO()
        self.error_output = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patch.dict(os.environ, {"ProgramData": self.program_data.name})
            )
            connect = stack.enter_context(
                patch.object(audit.pyodbc, "connect", return_value=connection)
            )
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(self.error_output))
            try:
                code = audit.main()
            except Exception as error:
                code = error
        return code, out.getvalue(), connection, connect

    def test_healthy_environment_exits_zero_and_prints_every_count_once(self):
        code, output, connection, _connect = self.run_audit()
        self.assertEqual(code, 0)
        self.assertEqual(output, json.dumps(json.loads(output), sort_keys=True) + "\n")
        expected = {name: value for name, value in HEALTHY_COUNTS}
        expected.update(
            version="17.0.1000.7", edition="Developer Edition", backup_files=0
        )
        self.assertEqual(json.loads(output), expected)
        self.assertTrue(connection.closed)

    def test_each_result_column_is_reported_under_its_own_name(self):
        distinct = {
            name: 100 + index for index, (name, _x) in enumerate(HEALTHY_COUNTS)
        }
        _code, output, _connection, _connect = self.run_audit(_row(distinct))
        printed = json.loads(output)
        for name, value in distinct.items():
            with self.subTest(name=name):
                self.assertEqual(printed[name], value)
        self.assertEqual(printed["version"], "17.0.1000.7")
        self.assertEqual(printed["edition"], "Developer Edition")

    def test_the_select_list_returns_the_columns_in_the_order_the_auditor_reads(self):
        _code, _output, connection, _connect = self.run_audit()
        ((sql, parameters),) = connection.executed
        self.assertEqual(parameters, ())
        positions = []
        for name, fragment in SELECT_ORDER:
            with self.subTest(name=name):
                self.assertIn(fragment, sql)
                positions.append(sql.index(fragment))
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(len(SELECT_ORDER), 2 + len(HEALTHY_COUNTS))

    def test_every_deviation_from_the_healthy_state_fails_the_audit(self):
        for name, healthy in HEALTHY_COUNTS:
            for deviation in (healthy + 1, healthy - 1):
                if deviation < 0:
                    continue
                with self.subTest(name=name, value=deviation):
                    code, output, connection, _connect = self.run_audit(
                        _row({name: deviation})
                    )
                    self.assertEqual(code, 1)
                    self.assertEqual(json.loads(output)[name], deviation)
                    self.assertTrue(connection.closed)

    def test_leftover_backup_files_fail_the_audit_but_directories_are_not_counted(self):
        (self.backups / "OSTV_IT_run.bak").write_bytes(b"x")
        (self.backups / "second.bak").write_bytes(b"x")
        (self.backups / "nested").mkdir()
        code, output, _connection, _connect = self.run_audit()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)["backup_files"], 2)

    def test_the_connection_is_integrated_encrypted_verified_and_bounded(self):
        _code, _output, _connection, connect = self.run_audit()
        connect.assert_called_once_with(
            "DRIVER={ODBC Driver 18 for SQL Server};"
            "SERVER={tcp:localhost};DATABASE={master};Trusted_Connection=yes;"
            "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=10;"
            "MARS_Connection=no;APP=OSTV SQL Integration Auditor;",
            autocommit=True,
            timeout=10,
        )

    def test_a_failing_query_closes_the_cursor_and_the_connection_and_prints_nothing(
        self,
    ):
        error = RuntimeError("query failed")
        code, output, connection, _connect = self.run_audit(execute_error=error)
        self.assertIs(code, error)
        self.assertEqual(output, "")
        self.assertTrue(connection.closed)
        self.assertEqual([cursor.closed for cursor in connection.cursors], [True])

    def test_a_missing_backup_directory_fails_with_a_clear_message_and_is_not_created(
        self,
    ):
        self.backups.rmdir()
        code, output, connection, _connect = self.run_audit()
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        message = self.error_output.getvalue()
        self.assertEqual(message.count("\n"), 1)
        self.assertIn(str(self.backups), message)
        self.assertIn("backup directory", message)
        self.assertIn("setup-sql-development.ps1", message)
        self.assertNotIn("Traceback", message)
        self.assertFalse(self.backups.exists())
        self.assertTrue(connection.closed)

    def test_a_backup_path_that_is_a_file_fails_with_the_same_clear_message(self):
        self.backups.rmdir()
        self.backups.write_bytes(b"not a directory")
        code, output, _connection, _connect = self.run_audit()
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertIn(str(self.backups), self.error_output.getvalue())
        self.assertEqual(self.backups.read_bytes(), b"not a directory")

    def test_a_healthy_audit_writes_nothing_to_the_error_stream(self):
        code, _output, _connection, _connect = self.run_audit()
        self.assertEqual(code, 0)
        self.assertEqual(self.error_output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
