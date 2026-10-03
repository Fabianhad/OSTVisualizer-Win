"""The guarded SQL integration provisioner, with every external effect replaced.
Nothing here reaches a SQL Server, the Windows registry, the credential store or the
network: ``pyodbc.connect`` is patched, ``winreg`` is replaced by a recorder, the
credential store is a stand-in and the backup root lives in a temporary ``ProgramData``.
The T-SQL is NOT executed (no server is available); the stored-procedure tests read the
generated text and pin the structure of the guards that protect destructive statements.
"""

import contextlib
import io
import json
import os
import re
import secrets
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch
from tools import manage_sql_development
from tools import provision_sql_integration as provision

PASSWORD = "stored-executor-password"
PROCEDURES = {
    "CreateDatabase": provision._create_database_procedure,
    "DropDatabase": provision._drop_database_procedure,
    "RestoreDatabase": provision._restore_database_procedure,
    "ValidateRestoredDatabase": provision._validate_restored_database_procedure,
}
# The named parameters the integration harness passes to each procedure
# (tests/helpers/sql/integration_support.py and test_environment_acceptance.py).
HARNESS_PARAMETERS = {
    "CreateDatabase": ("@DatabaseName", "@RunMarker", "@ExpectedServerMarker"),
    "DropDatabase": ("@DatabaseName", "@RunMarker", "@ExpectedServerMarker"),
    "RestoreDatabase": (
        "@DatabaseName",
        "@RunMarker",
        "@BackupPath",
        "@ExpectedServerMarker",
    ),
    "ValidateRestoredDatabase": (
        "@DatabaseName",
        "@RunMarker",
        "@ExpectedServerMarker",
    ),
}


def _thrown_codes(text):
    return [int(code) for code in re.findall(r"THROW (\d+),", text)]


class _Cursor:
    def __init__(self, connection):
        self._connection = connection
        self.closed = False

    def execute(self, sql, *parameters):
        self._connection.executed.append((sql, parameters))
        self._connection.pending = list(self._connection.handler(sql, parameters))

    def fetchone(self):
        pending = self._connection.pending
        return pending.pop(0) if pending else None

    def close(self):
        self.closed = True


class _Connection:
    def __init__(self, handler=lambda sql, parameters: ()):
        self.handler = handler
        self.executed = []
        self.pending = []
        self.cursors = []
        self.closed = False

    def cursor(self):
        cursor = _Cursor(self)
        self.cursors.append(cursor)
        return cursor

    def close(self):
        self.closed = True

    def statements(self):
        return [sql for sql, _parameters in self.executed]


class ProcedureGuardTextTests(unittest.TestCase):
    def test_each_procedure_is_declared_with_the_parameters_the_harness_passes(self):
        for name, build in PROCEDURES.items():
            with self.subTest(procedure=name):
                text = build()
                header = re.search(
                    rf"CREATE OR ALTER PROCEDURE \[ostv_it\]\.\[{name}\]\s*(.*?)\bAS\b",
                    text,
                    re.DOTALL,
                )
                self.assertIsNotNone(header)
                declared = tuple(re.findall(r"@\w+", header.group(1)))
                self.assertEqual(declared, HARNESS_PARAMETERS[name])

    def test_the_server_marker_guard_is_the_first_statement_of_every_procedure(self):
        for name, build in PROCEDURES.items():
            with self.subTest(procedure=name):
                text = build()
                body = text[text.index("BEGIN") :]
                first_throw = body.index("THROW")
                self.assertLess(body.index("SET NOCOUNT ON;"), first_throw)
                self.assertRegex(
                    body[:first_throw],
                    r"name=N'OSTVisualizerDisposableTestServer'\s+\);\s+"
                    r"IF @ServerMarker IS NULL OR @ExpectedServerMarker IS NULL\s+"
                    r"OR @ServerMarker COLLATE Latin1_General_100_BIN2\s+"
                    r"<> @ExpectedServerMarker COLLATE Latin1_General_100_BIN2\s+$",
                )

    def test_every_guard_precedes_the_first_statement_that_changes_the_server(self):
        for name, build in PROCEDURES.items():
            with self.subTest(procedure=name):
                text = build()
                last_guard = max(
                    match.start() for match in re.finditer(r"THROW \d+,", text)
                )
                self.assertLess(last_guard, text.index("EXEC (@Sql)"))

    def test_error_numbers_are_unique_across_all_four_procedures(self):
        codes = [
            code for build in PROCEDURES.values() for code in _thrown_codes(build())
        ]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(
            {name: _thrown_codes(build()) for name, build in PROCEDURES.items()},
            {
                "CreateDatabase": [51000, 51003, 51001, 51002],
                "DropDatabase": [51010, 51013, 51011, 51012],
                "RestoreDatabase": [51019, 51023, 51020, 51021, 51022, 51024],
                "ValidateRestoredDatabase": [51030, 51033, 51031, 51032, 51034],
            },
        )

    def test_database_names_are_limited_to_the_binary_collated_disposable_pattern(self):
        for name, build in PROCEDURES.items():
            with self.subTest(procedure=name):
                text = build()
                self.assertIn(
                    "@DatabaseName COLLATE Latin1_General_100_BIN2 NOT LIKE "
                    "N'OSTV_IT[_]%'",
                    text,
                )
                self.assertIn("LEN(@DatabaseName) <= LEN(N'OSTV_IT_')", text)
                self.assertIn(
                    "@DatabaseName COLLATE Latin1_General_100_BIN2 LIKE "
                    "N'%[^A-Za-z0-9_]%'",
                    text,
                )

    def test_dynamic_statements_only_embed_database_names_through_quotename(self):
        for name, build in PROCEDURES.items():
            with self.subTest(procedure=name):
                text = build()
                self.assertNotRegex(text, r"\+\s*@DatabaseName\b")
                self.assertNotRegex(text, r"\+\s*@RunMarker\b")
                self.assertNotRegex(text, r"\+\s*@BackupPath\b")
                self.assertNotRegex(text, r"@Sql\s*=\s*@")
                for statement in re.findall(r"QUOTENAME\(([^)]*)\)", text):
                    self.assertIn(
                        statement, {"@DatabaseName", "@BackupPath, ''''"}, statement
                    )

    def test_a_database_is_dropped_only_after_its_run_marker_is_proven(self):
        text = provision._drop_database_procedure()
        self.assertEqual(text.count("DROP DATABASE"), 1)
        self.assertLess(text.index("THROW 51012"), text.index("DROP DATABASE"))
        self.assertLess(
            text.index("DB_ID(@DatabaseName) IS NULL RETURN"), text.index("N'USE '")
        )
        self.assertRegex(
            text,
            r"IF @ActualMarker IS NULL OR @ActualMarker COLLATE Latin1_General_100_BIN2"
            r"\s+<> @RunMarker COLLATE Latin1_General_100_BIN2\s+"
            r"THROW 51012,",
        )
        self.assertIn("SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE", text)
        self.assertRegex(
            text,
            r"DELETE FROM \[ostv_it\]\.\[PendingRestores\]\s+"
            r"WHERE \[DatabaseName\]=@DatabaseName\s+"
            r"AND \[RunMarker\] COLLATE Latin1_General_100_BIN2",
        )

    def test_a_restore_is_verified_against_the_dedicated_backup_root_only(self):
        text = provision._restore_database_procedure()
        self.assertEqual(text.count("RESTORE VERIFYONLY"), 1)
        self.assertNotIn("RESTORE DATABASE", text)
        self.assertLess(text.index("THROW 51020"), text.index("RESTORE VERIFYONLY"))
        self.assertLess(text.index("THROW 51022"), text.index("RESTORE VERIFYONLY"))
        self.assertLess(text.index("THROW 51024"), text.index("RESTORE VERIFYONLY"))
        self.assertIn("OSTVisualizerDisposableBackupRoot", text)
        self.assertIn("LEFT(@BackupPath, LEN(@BackupRoot)) <> @BackupRoot", text)
        self.assertIn("@BackupPath LIKE N'%..%'", text)
        self.assertIn("IF @BackupRoot IS NULL", text)
        self.assertLess(
            text.index("SET @BackupRoot += N'\\'"),
            text.index("LEFT(@BackupPath, LEN(@BackupRoot)) <> @BackupRoot"),
        )
        self.assertIn("WITH CHECKSUM", text)
        self.assertLess(
            text.index("RESTORE VERIFYONLY"),
            text.index("INSERT INTO [ostv_it].[PendingRestores]"),
        )

    def test_restore_validation_requires_the_pending_request_and_the_run_marker(self):
        text = provision._validate_restored_database_procedure()
        self.assertLess(text.index("THROW 51032"), text.index("SET MULTI_USER"))
        self.assertLess(text.index("THROW 51034"), text.index("SET MULTI_USER"))
        self.assertLess(
            text.index("SET MULTI_USER"),
            text.index("DELETE FROM [ostv_it].[PendingRestores]"),
        )
        self.assertIn("[RunMarker] COLLATE Latin1_General_100_BIN2", text)

    def test_created_databases_carry_the_run_marker_and_change_tracking(self):
        text = provision._create_database_procedure()
        self.assertLess(text.index("THROW 51002"), text.index("CREATE DATABASE"))
        self.assertLess(
            text.index("CREATE DATABASE"), text.index("CHANGE_TRACKING = ON")
        )
        self.assertLess(
            text.index("CHANGE_TRACKING = ON"), text.index("sp_addextendedproperty")
        )
        self.assertIn(
            f"@name=N''{manage_sql_development.DISPOSABLE_MARKER_PROPERTY}''", text
        )
        self.assertEqual(
            manage_sql_development.DISPOSABLE_MARKER_PROPERTY,
            "OSTVisualizerDisposableTestRun",
        )
        self.assertIn("@value=@Marker", text)
        self.assertIn("@Marker=@RunMarker", text)
        self.assertIn("LEN(@RunMarker)>128", text)


class ProvisionConstantsTests(unittest.TestCase):
    def test_names_agree_with_the_development_manager_that_tears_them_down(self):
        self.assertEqual(provision._LOGIN, manage_sql_development.INTEGRATION_LOGIN)
        self.assertEqual(
            provision._CREDENTIAL_TARGET,
            manage_sql_development.INTEGRATION_CREDENTIAL_TARGET,
        )
        self.assertEqual(
            provision._SERVER_MARKER_PROPERTY, "OSTVisualizerDisposableTestServer"
        )
        self.assertEqual(
            provision._BACKUP_ROOT_PROPERTY, "OSTVisualizerDisposableBackupRoot"
        )
        source = Path(manage_sql_development.__file__).read_text(encoding="utf-8")
        removed = source[source.index("def _remove_owned_master_objects") :]
        for property_name in (
            provision._SERVER_MARKER_PROPERTY,
            provision._BACKUP_ROOT_PROPERTY,
        ):
            self.assertIn(f'"{property_name}"', removed)
        self.assertEqual(provision._SERVER, "tcp:localhost")


class ValidatedBackupRootTests(unittest.TestCase):
    def setUp(self):
        self.program_data = tempfile.TemporaryDirectory()
        self.addCleanup(self.program_data.cleanup)
        environment = patch.dict(os.environ, {"ProgramData": self.program_data.name})
        environment.start()
        self.addCleanup(environment.stop)
        self.expected = Path(self.program_data.name) / "OSTVisualizer"
        self.expected = self.expected / "SqlIntegrationBackups"

    def test_only_the_dedicated_directory_is_accepted_and_it_is_created(self):
        self.assertFalse(self.expected.exists())
        result = provision._validated_backup_root(str(self.expected))
        self.assertEqual(Path(result), self.expected.resolve())
        self.assertTrue(self.expected.is_dir())
        self.assertEqual(provision._validated_backup_root(result), result)

    def test_any_other_directory_is_refused_without_being_created(self):
        elsewhere = Path(self.program_data.name) / "Elsewhere"
        candidates = (
            elsewhere,
            self.expected.parent,
            self.expected / "child",
            self.expected / ".." / "Other",
            Path(self.program_data.name),
        )
        for candidate in candidates:
            with self.subTest(candidate=str(candidate)):
                with self.assertRaisesRegex(ValueError, "dedicated path"):
                    provision._validated_backup_root(str(candidate))
        self.assertFalse(elsewhere.exists())
        self.assertFalse(self.expected.exists())


class ServerMarkerTests(unittest.TestCase):
    def test_an_existing_marker_is_reused_and_a_new_one_is_a_random_uuid(self):
        existing = _Connection(lambda sql, parameters: [("marker-1",)])
        self.assertEqual(provision._server_marker(existing), "marker-1")
        ((sql, parameters),) = existing.executed
        self.assertIn("class=0 AND name=?", sql)
        self.assertEqual(parameters, ("OSTVisualizerDisposableTestServer",))
        self.assertTrue(existing.cursors[0].closed)
        fresh = _Connection()
        first = provision._server_marker(fresh)
        second = provision._server_marker(fresh)
        self.assertEqual(str(uuid.UUID(first)), first)
        self.assertNotEqual(first, second)
        self.assertTrue(all(cursor.closed for cursor in fresh.cursors))

    def test_the_cursor_is_closed_when_the_query_fails(self):
        class Failing(_Connection):
            def cursor(self):
                cursor = super().cursor()
                cursor.execute = MagicMock(side_effect=RuntimeError("boom"))
                return cursor

        connection = Failing()
        with self.assertRaisesRegex(RuntimeError, "boom"):
            provision._server_marker(connection)
        self.assertTrue(connection.cursors[0].closed)


class ConfigureServerTests(unittest.TestCase):
    def configure(self, update_executor_password=True):
        connection = _Connection()
        provision._configure_server(
            connection,
            "server-marker",
            r"C:\ProgramData\OSTVisualizer\SqlIntegrationBackups",
            "executor-secret-value",
            "master-key-secret-value",
            update_executor_password=update_executor_password,
        )
        return connection

    def test_secrets_are_sent_only_as_parameters_never_inside_the_sql_text(self):
        connection = self.configure()
        for sql in connection.statements():
            self.assertNotIn("executor-secret-value", sql)
            self.assertNotIn("master-key-secret-value", sql)
            self.assertNotIn("server-marker", sql)
        by_secret = {
            parameters[0]: sql
            for sql, parameters in connection.executed
            if len(parameters) == 1
        }
        self.assertIn("CREATE LOGIN", by_secret["executor-secret-value"])
        self.assertIn(
            "QUOTENAME(@secret, NCHAR(39))", by_secret["executor-secret-value"]
        )
        self.assertIn(
            "CREATE MASTER KEY ENCRYPTION", by_secret["master-key-secret-value"]
        )
        self.assertTrue(all(cursor.closed for cursor in connection.cursors))

    def test_an_unchanged_executor_password_is_never_sent_again(self):
        connection = self.configure(update_executor_password=False)
        statements = " ".join(connection.statements())
        self.assertNotIn("CREATE LOGIN [OSTV_IT_EXECUTOR]", statements)
        self.assertNotIn("ALTER LOGIN", statements)
        self.assertNotIn(
            "executor-secret-value",
            [value for _sql, parameters in connection.executed for value in parameters],
        )
        self.assertIn("CREATE USER [OSTV_IT_EXECUTOR]", statements)

    def test_markers_and_backup_root_are_stored_as_server_extended_properties(self):
        connection = self.configure()
        properties = [
            parameters
            for sql, parameters in connection.executed
            if "sp_updateextendedproperty" in sql
        ]
        self.assertEqual(
            properties,
            [
                ("OSTVisualizerDisposableTestServer",) * 2
                + ("server-marker",)
                + ("OSTVisualizerDisposableTestServer", "server-marker"),
                ("OSTVisualizerDisposableBackupRoot",) * 2
                + (r"C:\ProgramData\OSTVisualizer\SqlIntegrationBackups",)
                + (
                    "OSTVisualizerDisposableBackupRoot",
                    r"C:\ProgramData\OSTVisualizer\SqlIntegrationBackups",
                ),
            ],
        )

    def test_the_executor_may_only_execute_the_four_signed_procedures(self):
        statements = self.configure().statements()
        joined = " ".join(statements)
        for forbidden in (
            "sysadmin",
            "ALTER SERVER ROLE",
            "ADD MEMBER",
            "sp_addsrvrolemember",
            "sp_addrolemember",
            "db_owner",
            "CONTROL",
        ):
            self.assertNotIn(forbidden, joined)
        grants = re.findall(r"GRANT ([^;]+?) TO \[(\w+)\]", joined)
        self.assertEqual(
            sorted(grants),
            sorted(
                [
                    (f"EXECUTE ON OBJECT::[ostv_it].[{name}]", "OSTV_IT_EXECUTOR")
                    for name in PROCEDURES
                ]
                + [
                    (privilege, "OSTV_IT_ProvisioningCertificateLogin")
                    for privilege in (
                        "CREATE ANY DATABASE",
                        "ALTER ANY DATABASE",
                        "CONNECT ANY DATABASE",
                    )
                ]
            ),
        )
        self.assertEqual(
            re.findall(r"REVOKE ([^;]+?) FROM \[(\w+)\]", joined),
            [("EXECUTE ON SCHEMA::[ostv_it]", "OSTV_IT_EXECUTOR")],
        )
        executor = [s for s in statements if "GRANT EXECUTE ON OBJECT" in s]
        self.assertEqual(len(executor), 1)
        self.assertLess(
            executor[0].index("REVOKE EXECUTE ON SCHEMA"),
            executor[0].index("GRANT EXECUTE"),
        )

    def test_the_executor_login_is_policy_checked_and_enabled(self):
        statements = self.configure().statements()
        (login,) = [s for s in statements if "CREATE LOGIN [OSTV_IT_EXECUTOR]" in s]
        self.assertIn("CHECK_POLICY=ON", login)
        self.assertIn("CHECK_EXPIRATION=OFF", login)
        self.assertIn("DEFAULT_DATABASE=[master]", login)
        self.assertIn("ALTER LOGIN [OSTV_IT_EXECUTOR] WITH PASSWORD=", login)
        self.assertTrue(
            login.rstrip().endswith("ALTER LOGIN [OSTV_IT_EXECUTOR] ENABLE;")
        )

    def test_procedures_are_created_then_signed_then_granted_in_that_order(self):
        statements = self.configure().statements()

        def positions(fragment):
            found = [i for i, sql in enumerate(statements) if fragment in sql]
            self.assertTrue(found, fragment)
            return found

        def position(fragment):
            found = positions(fragment)
            self.assertEqual(len(found), 1, fragment)
            return found[0]

        created = [
            position(f"CREATE OR ALTER PROCEDURE [ostv_it].[{name}]")
            for name in PROCEDURES
        ]
        signed = [
            position(f"ADD SIGNATURE TO OBJECT::[ostv_it].[{name}]")
            for name in PROCEDURES
        ]
        self.assertEqual(created, sorted(created))
        self.assertEqual(signed, sorted(signed))
        self.assertLess(max(created), min(signed))
        self.assertLess(position("sp_configure N'show advanced options'"), min(created))
        self.assertLess(position("CREATE SCHEMA [ostv_it]"), min(created))
        self.assertLess(
            position("CREATE TABLE [ostv_it].[PendingRestores]"), min(created)
        )
        self.assertLess(min(positions("sp_updateextendedproperty")), min(created))
        self.assertLess(position("CREATE CERTIFICATE"), min(signed))
        self.assertLess(
            max(signed), position("GRANT EXECUTE ON OBJECT::[ostv_it].[CreateDatabase]")
        )
        for sql in statements:
            if "ADD SIGNATURE" in sql:
                self.assertIn("BY CERTIFICATE [OSTV_IT_ProvisioningCertificate]", sql)

    def test_contained_database_authentication_is_disabled(self):
        first = self.configure().statements()[0]
        self.assertIn("contained database authentication', 0", first)
        self.assertIn("show advanced options', 1", first)


class UserEnvironmentTests(unittest.TestCase):
    def run_with_recorder(self, missing=()):
        calls = []

        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        def open_key(root, path, reserved, access):
            calls.append(("open", root, path, reserved, access))
            return Key()

        def set_value(key, name, reserved, kind, value):
            self.assertEqual(reserved, 0)
            calls.append(("set", name, kind, value))

        def delete_value(key, name):
            calls.append(("delete", name))
            if name in missing:
                raise FileNotFoundError(name)

        fake = SimpleNamespace(
            HKEY_CURRENT_USER="HKCU",
            HKEY_LOCAL_MACHINE="HKLM",
            KEY_SET_VALUE="SET",
            REG_SZ="SZ",
            OpenKey=open_key,
            SetValueEx=set_value,
            DeleteValue=delete_value,
        )
        with patch.object(provision, "winreg", fake):
            provision._set_user_environment("the-marker")
        return calls

    def test_only_the_current_users_environment_gets_the_five_connection_values(self):
        calls = self.run_with_recorder()
        self.assertEqual(calls[0], ("open", "HKCU", "Environment", 0, "SET"))
        self.assertEqual(
            [call for call in calls if call[0] == "set"],
            [
                ("set", "OSTV_SQL_TEST_SERVER", "SZ", "tcp:localhost"),
                ("set", "OSTV_SQL_TEST_AUTH", "SZ", "sql"),
                ("set", "OSTV_SQL_TEST_USER", "SZ", "OSTV_IT_EXECUTOR"),
                ("set", "OSTV_SQL_TEST_SERVER_MARKER", "SZ", "the-marker"),
                (
                    "set",
                    "OSTV_SQL_TEST_CREDENTIAL_TARGET",
                    "SZ",
                    "OSTVisualizer/Integration/OSTVDEV/Executor",
                ),
            ],
        )
        self.assertEqual(len([call for call in calls if call[0] == "open"]), 1)

    def test_a_stored_password_and_opt_in_switches_are_removed_even_when_absent(self):
        removed = [
            call[1]
            for call in self.run_with_recorder(missing=("OSTV_SQL_TEST_PASSWORD",))
            if call[0] == "delete"
        ]
        self.assertEqual(
            removed,
            [
                "OSTV_SQL_INTEGRATION",
                "OSTV_SQL_DESTRUCTIVE_TESTS",
                "OSTV_SQL_TEST_PASSWORD",
            ],
        )


class ExecutorLoginProbeTests(unittest.TestCase):
    def probe(self, outcome):
        requests = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def execute(self, sql):
                requests.append(("execute", sql))

            def fetchone(self):
                return (outcome,)

        class Lease:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def cursor(self):
                return Cursor()

        class Manager:
            def connection(self, request, *, autocommit):
                requests.append(("connection", request, autocommit))
                if isinstance(outcome, Exception):
                    raise outcome
                return Lease()

        with patch.object(provision, "SqlConnectionManager", Manager):
            return provision._executor_login_accepts("candidate"), requests

    def test_the_stored_password_is_accepted_only_by_a_real_select_one(self):
        accepted, requests = self.probe(1)
        self.assertTrue(accepted)
        _tag, request, autocommit = requests[0]
        self.assertTrue(autocommit)
        self.assertEqual(request.password, "candidate")
        self.assertTrue(request.read_only)
        location = request.location
        self.assertEqual(
            (location.server, location.database, location.username),
            ("tcp:localhost", "master", "OSTV_IT_EXECUTOR"),
        )
        self.assertEqual(location.authentication_mode.value, "sql_server")
        self.assertTrue(location.encrypt)
        self.assertFalse(location.trust_server_certificate)
        self.assertEqual(location.connection_timeout_seconds, 5)
        self.assertEqual(requests[1], ("execute", "SELECT 1"))
        self.assertIs(self.probe(0)[0], False)

    def test_connection_failures_mean_the_password_is_not_reusable(self):
        for error in (OSError("down"), RuntimeError("login failed"), ValueError("bad")):
            with self.subTest(error=type(error).__name__):
                self.assertIs(self.probe(error)[0], False)


class ServerIdentityTests(unittest.TestCase):
    def test_version_and_edition_are_returned_as_text_and_the_cursor_is_closed(self):
        connection = _Connection(lambda sql, parameters: [(17, "Developer Edition")])
        self.assertEqual(
            provision._server_identity(connection), ("17", "Developer Edition")
        )
        self.assertIn("SERVERPROPERTY('ProductVersion')", connection.statements()[0])
        self.assertIn("SERVERPROPERTY('Edition')", connection.statements()[0])
        self.assertTrue(connection.cursors[0].closed)


class ProvisionMainTests(unittest.TestCase):
    def setUp(self):
        self.program_data = tempfile.TemporaryDirectory()
        self.addCleanup(self.program_data.cleanup)
        self.backup_root = str(
            Path(self.program_data.name) / "OSTVisualizer" / "SqlIntegrationBackups"
        )
        self.connection = _Connection()
        self.store = MagicMock()
        self.store.read_password.return_value = ""
        self.events = []
        patches = {
            "pyodbc.connect": patch.object(
                provision.pyodbc, "connect", return_value=self.connection
            ),
            "store": patch.object(
                provision, "WindowsCredentialStore", return_value=self.store
            ),
            "require": patch.object(provision, "require_owned_sql_instance"),
            "marker": patch.object(provision, "_server_marker", return_value="marker"),
            "configure": patch.object(provision, "_configure_server"),
            "environment": patch.object(provision, "_set_user_environment"),
            "identity": patch.object(
                provision, "_server_identity", return_value=("17.0", "Developer")
            ),
            "accepts": patch.object(
                provision, "_executor_login_accepts", return_value=False
            ),
            "tokens": patch.object(
                provision.secrets,
                "token_urlsafe",
                side_effect=lambda _n: f"generated-{len(self.events)}-{uuid.uuid4().hex}",
            ),
        }
        self.mocks = {}
        for name, target in patches.items():
            self.mocks[name] = target.start()
            self.addCleanup(target.stop)
        environment = patch.dict(os.environ, {"ProgramData": self.program_data.name})
        environment.start()
        self.addCleanup(environment.stop)
        self.mocks["configure"].side_effect = lambda *a, **k: self.events.append(
            "configure"
        )
        self.store.write_password.side_effect = lambda *a: self.events.append("store")
        self.mocks["environment"].side_effect = lambda *a: self.events.append(
            "environment"
        )

    def run_main(self, backup_root=None):
        out = io.StringIO()
        argv = [
            "provision_sql_integration.py",
            "--backup-root",
            backup_root or self.backup_root,
        ]
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(out):
            code = provision.main()
        return code, out.getvalue()

    def test_a_fresh_environment_generates_a_password_and_stores_it_after_configuring(
        self,
    ):
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(self.events, ["configure", "store", "environment"])
        self.assertEqual(self.mocks["tokens"].call_args_list, [call(48), call(48)])
        args, kwargs = self.mocks["configure"].call_args
        connection, marker, backup_root, executor_password, master_password = args
        self.assertIs(connection, self.connection)
        self.assertEqual(marker, "marker")
        self.assertEqual(Path(backup_root), Path(self.backup_root).resolve())
        self.assertNotEqual(executor_password, master_password)
        self.assertEqual(kwargs, {"update_executor_password": True})
        self.store.write_password.assert_called_once_with(
            "OSTVisualizer/Integration/OSTVDEV/Executor",
            "OSTV_IT_EXECUTOR",
            executor_password,
        )
        self.mocks["environment"].assert_called_once_with("marker")
        self.mocks["require"].assert_called_once_with(self.connection)
        payload = json.loads(output)
        self.assertEqual(output, json.dumps(payload, sort_keys=True) + "\n")
        self.assertEqual(
            payload,
            {
                "status": "configured",
                "instance": "OSTVDEV",
                "port": 1433,
                "version": "17.0",
                "edition": "Developer",
                "credential_target_configured": True,
                "credential_rotated": True,
                "server_marker_configured": True,
            },
        )
        self.assertNotIn(executor_password, output)
        self.assertNotIn(master_password, output)
        self.assertTrue(self.connection.closed)

    def test_the_connection_is_integrated_encrypted_and_verified(self):
        self.run_main()
        self.mocks["pyodbc.connect"].assert_called_once_with(
            "DRIVER={ODBC Driver 18 for SQL Server};"
            "SERVER={tcp:localhost};DATABASE={master};Trusted_Connection=yes;"
            "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=10;"
            "MARS_Connection=no;APP=OST Visualizer SQL Integration Provisioner;",
            autocommit=True,
            timeout=10,
        )

    def test_a_working_stored_password_is_reused_without_rewriting_anything(self):
        self.store.read_password.return_value = PASSWORD
        self.mocks["accepts"].return_value = True
        _code, output = self.run_main()
        self.mocks["accepts"].assert_called_once_with(PASSWORD)
        args, kwargs = self.mocks["configure"].call_args
        self.assertEqual(args[3], PASSWORD)
        self.assertEqual(kwargs, {"update_executor_password": False})
        self.store.write_password.assert_not_called()
        self.assertEqual(self.events, ["configure", "environment"])
        self.assertIs(json.loads(output)["credential_rotated"], False)
        self.assertNotIn(PASSWORD, output)

    def test_a_stored_password_the_server_rejects_is_replaced(self):
        self.store.read_password.return_value = PASSWORD
        self.mocks["accepts"].return_value = False
        self.run_main()
        args, kwargs = self.mocks["configure"].call_args
        self.assertNotEqual(args[3], PASSWORD)
        self.assertEqual(kwargs, {"update_executor_password": True})
        self.store.write_password.assert_called_once_with(
            "OSTVisualizer/Integration/OSTVDEV/Executor", "OSTV_IT_EXECUTOR", args[3]
        )

    def test_an_empty_stored_password_is_never_probed_against_the_server(self):
        self.store.read_password.return_value = None
        self.run_main()
        self.mocks["accepts"].assert_not_called()

    def test_a_failed_configuration_stores_nothing_and_still_closes_the_connection(
        self,
    ):
        self.mocks["configure"].side_effect = RuntimeError("guard refused")
        with self.assertRaisesRegex(RuntimeError, "guard refused"):
            self.run_main()
        self.store.write_password.assert_not_called()
        self.mocks["environment"].assert_not_called()
        self.assertTrue(self.connection.closed)

    def test_a_foreign_instance_is_refused_before_any_server_change(self):
        self.mocks["require"].side_effect = RuntimeError("not the dedicated instance")
        with self.assertRaisesRegex(RuntimeError, "dedicated instance"):
            self.run_main()
        self.mocks["marker"].assert_not_called()
        self.mocks["configure"].assert_not_called()
        self.assertTrue(self.connection.closed)

    def test_a_failed_credential_store_write_leaves_the_user_environment_alone(self):
        self.store.write_password.side_effect = OSError("credential store unavailable")
        with self.assertRaisesRegex(OSError, "credential store unavailable"):
            self.run_main()
        self.mocks["environment"].assert_not_called()
        self.assertTrue(self.connection.closed)

    def test_a_backup_root_outside_the_dedicated_path_stops_before_the_store_is_read(
        self,
    ):
        with self.assertRaisesRegex(ValueError, "dedicated path"):
            self.run_main(backup_root=str(Path(self.program_data.name) / "Elsewhere"))
        self.store.read_password.assert_not_called()
        self.mocks["pyodbc.connect"].assert_not_called()

    def test_the_backup_root_argument_is_required(self):
        with patch.object(sys, "argv", ["provision_sql_integration.py"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    provision.main()
        self.assertEqual(raised.exception.code, 2)
        self.mocks["pyodbc.connect"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
