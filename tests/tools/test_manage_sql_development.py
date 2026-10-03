import contextlib
import dataclasses
import io
import json
import os
import socket
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, call, patch
import tools.manage_sql_development as sql_development
from tests.sql_server.python.ostv_sql_admin.environment_support import (
    windows_safe_replace,
)
from ost_visualizer.infrastructure.sql.client_permissions import (
    SQL_CLIENT_PROTECTED_OSTV_TABLES,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from tools.manage_sql_development import (
    CLIENT_CREDENTIAL_TARGET,
    CLIENT_DATABASE,
    CLIENT_LOGIN,
    SERVER_ENDPOINT,
    SERVER_HOST,
    SERVER_PORT,
    SqlDevelopmentSecrets,
    TeardownInventory,
    generate_client_password,
    read_secrets,
    select_client_password,
    validate_database_ownership,
    validate_teardown_inventory,
    write_secrets_atomic,
)

MARKER = "b264d6f1-c518-4898-9a34-e124159195cb"


def _secrets(password: str, **overrides) -> SqlDevelopmentSecrets:
    values = dict(
        server=SERVER_HOST,
        port=SERVER_PORT,
        database=CLIENT_DATABASE,
        authentication_mode="sql",
        username=CLIENT_LOGIN,
        password=password,
        credential_target=CLIENT_CREDENTIAL_TARGET,
        encrypt=True,
        trust_server_certificate=False,
        ownership_marker=MARKER,
    )
    values.update(overrides)
    return SqlDevelopmentSecrets(**values)


def forbid_real_registry(test):
    """Make any access to the real Windows registry fail the test loudly.
    The teardown and provisioning code deletes and writes machine and user registry
    values; every test here must replace those effects, so a forgotten patch must not
    reach the developer's registry.
    """
    for name in ("OpenKey", "CreateKeyEx", "SetValueEx", "DeleteValue", "QueryValueEx"):
        guard = patch.object(
            sql_development.winreg,
            name,
            side_effect=AssertionError(f"real registry access: winreg.{name}"),
        )
        guard.start()
        test.addCleanup(guard.stop)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []
        self.closed = False

    def execute(self, sql, *params):
        self.connection.executed.append((sql, params))
        self.rows = list(self.connection.handler(sql, params))
        return self

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def close(self):
        self.closed = True


class FakeConnection:
    """Scripted SQL connection; records statements, never reaches a server."""

    def __init__(self, handler=lambda sql, params: ()):
        self.handler = handler
        self.executed = []
        self.cursors = []
        self.closed = False
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        cursor = FakeCursor(self)
        self.cursors.append(cursor)
        return cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True

    def statements(self):
        return [sql for sql, _params in self.executed]


class SqlDevelopmentSetupTests(unittest.TestCase):
    def setUp(self):
        forbid_real_registry(self)
        replace_patch = windows_safe_replace()
        replace_patch.start()
        self.addCleanup(replace_patch.stop)

    def test_development_endpoint_uses_machine_name_and_default_sql_port(self):
        self.assertEqual(SERVER_HOST, socket.gethostname())
        self.assertEqual(SERVER_PORT, 1433)
        self.assertEqual(SERVER_ENDPOINT, f"tcp:{SERVER_HOST}")

    def test_provisioning_refuses_a_different_instance_on_the_default_port(self):
        class _Cursor:
            def execute(self, _sql):
                pass

            def fetchone(self):
                return ("UNRELATED",)

            def close(self):
                pass

        class _Connection:
            def cursor(self):
                return _Cursor()

        with self.assertRaisesRegex(RuntimeError, "OSTVDEV"):
            sql_development.require_owned_sql_instance(_Connection())

    def test_only_the_dedicated_instance_name_is_accepted_case_insensitively(self):
        for name in ("OSTVDEV", "ostvdev", "OstvDev"):
            with self.subTest(name=name):
                connection = FakeConnection(lambda sql, params, n=name: [(n,)])
                self.assertIsNone(
                    sql_development.require_owned_sql_instance(connection)
                )
                self.assertTrue(connection.cursors[0].closed)
        for rows in ([], [(None,)], [("MSSQLSERVER",)], [("OSTVDEV2",)], [("",)]):
            with self.subTest(rows=rows):
                connection = FakeConnection(lambda sql, params, r=rows: r)
                with self.assertRaisesRegex(RuntimeError, "dedicated OSTVDEV"):
                    sql_development.require_owned_sql_instance(connection)
                self.assertTrue(connection.cursors[0].closed)
                self.assertEqual(len(connection.executed), 1)
                self.assertIn(
                    "SERVERPROPERTY('InstanceName')", connection.statements()[0]
                )

    def test_generated_passwords_are_long_random_urlsafe_values(self):
        first = generate_client_password()
        second = generate_client_password()
        self.assertGreaterEqual(len(first), 64)
        self.assertGreaterEqual(len(second), 64)
        self.assertNotEqual(first, second)
        self.assertTrue(
            all(character.isalnum() or character in "-_" for character in first)
        )

    def test_secrets_repr_redacts_connection_password_and_marker(self):
        value = self._secrets("password-must-not-appear")
        rendered = repr(value)
        self.assertNotIn(value.password, rendered)
        self.assertNotIn(value.server, rendered)
        self.assertNotIn(value.ownership_marker, rendered)
        self.assertEqual(
            rendered,
            "SqlDevelopmentSecrets(connection=<redacted>, password=<redacted>, "
            "ownership_marker=<redacted>)",
        )
        self.assertEqual(str(value), rendered)
        self.assertNotIn(value.password, f"{[value]} {value!s}")

    def test_secrets_json_is_atomic_exact_and_round_trips(self):
        value = self._secrets("runtime-only-test-value")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sql-development.json"
            write_secrets_atomic(path, value)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload, value.to_dict())
            self.assertEqual(read_secrets(path), value)
            self.assertEqual(tuple(path.parent.glob(".*.tmp")), ())

    def test_failed_secret_write_keeps_the_previous_file_and_leaves_no_temporary(self):
        original = self._secrets("original-runtime-value")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "sql-development.json"
            write_secrets_atomic(path, original)
            with patch.object(
                sql_development.os, "fsync", side_effect=OSError("disk full")
            ):
                with self.assertRaisesRegex(OSError, "disk full"):
                    write_secrets_atomic(
                        path, self._secrets("replacement-runtime-value")
                    )
            self.assertEqual(read_secrets(path), original)
            self.assertEqual(tuple(path.parent.glob(".*.tmp")), ())
            with patch.object(
                sql_development.os, "replace", side_effect=OSError("locked")
            ):
                with self.assertRaisesRegex(OSError, "locked"):
                    write_secrets_atomic(
                        path, self._secrets("replacement-runtime-value")
                    )
            self.assertEqual(read_secrets(path), original)
            self.assertEqual(tuple(path.parent.glob(".*.tmp")), ())

    def test_secrets_reader_rejects_unknown_fields(self):
        value = self._secrets("runtime-only-test-value")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sql-development.json"
            payload = value.to_dict()
            payload["unexpected"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "invalid shape"):
                read_secrets(path)

    def test_secrets_reader_rejects_coerced_security_values(self):
        value = self._secrets("runtime-only-test-value")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sql-development.json"
            for key, invalid in (
                ("port", str(SERVER_PORT)),
                ("encrypt", "true"),
                ("trust_server_certificate", 0),
                ("password", 123),
            ):
                with self.subTest(key=key):
                    payload = value.to_dict()
                    payload[key] = invalid
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaisesRegex(RuntimeError, "invalid value types"):
                        read_secrets(path)

    def test_missing_or_unreadable_secret_files_never_echo_their_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sql-development.json"
            self.assertIsNone(read_secrets(path))
            for label, data in {
                "not json": b"{not-json runtime-only-test-value",
                "not utf8": b"\xff\xfe runtime-only-test-value",
            }.items():
                with self.subTest(label):
                    path.write_bytes(data)
                    with self.assertRaisesRegex(RuntimeError, "unreadable") as raised:
                        read_secrets(path)
                    self.assertNotIn("runtime-only-test-value", str(raised.exception))
            path.write_text("[1, 2]", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "invalid shape"):
                read_secrets(path)

    def test_secrets_reader_rejects_any_identity_that_weakens_the_connection(self):
        base = self._secrets("runtime-only-test-value").to_dict()
        invalid = {
            "other server": ({"server": "other-host"}, "identity is invalid"),
            "other port": ({"port": 14330}, "identity is invalid"),
            "other database": ({"database": "master"}, "identity is invalid"),
            "windows auth": ({"authentication_mode": "windows"}, "identity is invalid"),
            "other user": ({"username": "sa"}, "identity is invalid"),
            "other target": (
                {"credential_target": "Other/Target"},
                "identity is invalid",
            ),
            "no encryption": ({"encrypt": False}, "identity is invalid"),
            "trusted certificate": (
                {"trust_server_certificate": True},
                "identity is invalid",
            ),
            "empty password": ({"password": ""}, "password is missing"),
            "marker": ({"ownership_marker": "not-a-uuid"}, "marker is invalid"),
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sql-development.json"
            path.write_text(json.dumps(base), encoding="utf-8")
            self.assertEqual(read_secrets(path).username, CLIENT_LOGIN)
            for label, (changes, message) in invalid.items():
                with self.subTest(label):
                    path.write_text(json.dumps({**base, **changes}), encoding="utf-8")
                    with self.assertRaisesRegex(RuntimeError, message) as raised:
                        read_secrets(path)
                    self.assertNotIn("runtime-only-test-value", str(raised.exception))

    def test_idempotent_password_selection_reuses_working_credential(self):
        selection = select_client_password(
            "existing-runtime-secret",
            login_exists=True,
            existing_password_works=True,
            rotate_requested=False,
        )
        self.assertEqual(selection.password, "existing-runtime-secret")
        self.assertFalse(selection.rotate_login)

    def test_rotation_generates_a_new_password_only_when_requested(self):
        with patch(
            "tools.manage_sql_development.generate_client_password",
            return_value="new-runtime-secret",
        ):
            selection = select_client_password(
                "existing-runtime-secret",
                login_exists=True,
                existing_password_works=True,
                rotate_requested=True,
            )
        self.assertEqual(selection.password, "new-runtime-secret")
        self.assertTrue(selection.rotate_login)

    def test_new_login_gets_a_fresh_password_and_rotation_repairs_a_broken_one(self):
        with patch(
            "tools.manage_sql_development.generate_client_password",
            return_value="generated-runtime-secret",
        ) as generate:
            fresh = select_client_password(
                "",
                login_exists=False,
                existing_password_works=False,
                rotate_requested=False,
            )
            repaired = select_client_password(
                "stale",
                login_exists=True,
                existing_password_works=False,
                rotate_requested=True,
            )
        self.assertEqual(
            (fresh.password, fresh.rotate_login), ("generated-runtime-secret", True)
        )
        self.assertEqual(
            (repaired.password, repaired.rotate_login),
            ("generated-runtime-secret", True),
        )
        self.assertEqual(generate.call_count, 2)

    def test_existing_login_with_invalid_credential_requires_explicit_rotation(self):
        with self.assertRaisesRegex(RuntimeError, "RotateClientPassword"):
            select_client_password(
                "stale-runtime-secret",
                login_exists=True,
                existing_password_works=False,
                rotate_requested=False,
            )
        with self.assertRaisesRegex(RuntimeError, "RotateClientPassword"):
            select_client_password(
                "",
                login_exists=True,
                existing_password_works=True,
                rotate_requested=False,
            )

    def test_existing_database_requires_exact_ownership_marker(self):
        validate_database_ownership(
            database_exists=True,
            actual_marker="owned-marker",
            expected_marker="owned-marker",
        )
        for actual in ("", "different-marker"):
            with self.subTest(actual=actual):
                with self.assertRaisesRegex(RuntimeError, "ownership marker"):
                    validate_database_ownership(
                        database_exists=True,
                        actual_marker=actual,
                        expected_marker="owned-marker",
                    )
        with self.assertRaisesRegex(RuntimeError, "ownership marker"):
            validate_database_ownership(
                database_exists=True, actual_marker="", expected_marker=""
            )

    def test_a_missing_database_needs_no_ownership_marker(self):
        validate_database_ownership(
            database_exists=False, actual_marker="", expected_marker="owned-marker"
        )
        validate_database_ownership(
            database_exists=False, actual_marker="other", expected_marker="owned-marker"
        )

    def test_teardown_accepts_only_owned_idle_resources(self):
        validate_teardown_inventory(TeardownInventory((CLIENT_DATABASE,), (), (), 0, 0))

    def test_teardown_refuses_unowned_databases_logins_sessions_and_restores(self):
        inventories = (
            (
                TeardownInventory((), ("unmarked",), (), 0, 0),
                "unmarked or unrelated user database",
            ),
            (
                TeardownInventory((), (), ("unrelated-login",), 0, 0),
                "unrelated server login",
            ),
            (TeardownInventory((), (), (), 1, 0), "active session"),
            (
                TeardownInventory((), (), (), 0, 1),
                "pending disposable database restore",
            ),
        )
        for inventory, message in inventories:
            with self.subTest(inventory=inventory):
                with self.assertRaisesRegex(RuntimeError, message):
                    validate_teardown_inventory(inventory)

    def test_installer_principal_needs_domain_and_user(self):
        with patch.dict(os.environ, {"USERDOMAIN": " CORP ", "USERNAME": " dev "}):
            self.assertEqual(sql_development._installer_principal(), "CORP\\dev")
        for env in (
            {"USERDOMAIN": "", "USERNAME": "dev"},
            {"USERDOMAIN": "CORP", "USERNAME": " "},
        ):
            with self.subTest(env=env):
                with patch.dict(os.environ, env):
                    with self.assertRaisesRegex(RuntimeError, "setup identity"):
                        sql_development._installer_principal()

    def test_windows_connection_is_encrypted_verified_and_integrated(self):
        self.assertEqual(
            sql_development._windows_connection_string(),
            "DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER={{{SERVER_ENDPOINT}}};DATABASE={{master}};"
            "Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=no;"
            "Connection Timeout=10;MARS_Connection=no;"
            "APP=OST Visualizer SQL Development Manager;",
        )
        self.assertIn(
            "DATABASE={OSTV_CLIENT_TEST};",
            sql_development._windows_connection_string(CLIENT_DATABASE),
        )
        with patch.object(sql_development.pyodbc, "connect") as connect:
            result = sql_development._windows_connection()
        connect.assert_called_once_with(
            sql_development._windows_connection_string(), autocommit=True, timeout=10
        )
        self.assertIs(result, connect.return_value)
        location = sql_development._windows_location(CLIENT_DATABASE)
        self.assertEqual(location.server, SERVER_ENDPOINT)
        self.assertEqual(location.database, CLIENT_DATABASE)
        self.assertEqual(location.authentication_mode.value, "windows")
        self.assertTrue(location.encrypt)
        self.assertFalse(location.trust_server_certificate)

    def test_repo_root_must_identify_the_application(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "does not identify OST Visualizer"):
                sql_development._validated_secrets_path(root)
            (root / "ost_visualizer").mkdir()
            self.assertEqual(
                sql_development._validated_secrets_path(root),
                root / ".secrets" / "sql-development.json",
            )

    def test_the_registry_guard_stops_every_unpatched_registry_access(self):
        for label, access in (
            ("exists", sql_development._registry_exists),
            ("value", lambda: sql_development._registry_value("OwnershipMarker")),
            (
                "write",
                lambda: sql_development._write_registry_ownership(MARKER, "CORP\\dev"),
            ),
            ("environment", sql_development._remove_user_environment),
        ):
            with self.subTest(label):
                with self.assertRaisesRegex(AssertionError, "real registry access"):
                    access()

    @staticmethod
    def _secrets(password: str) -> SqlDevelopmentSecrets:
        return _secrets(password)


class SqlDevelopmentFakeServerTests(unittest.TestCase):
    """Server-side helpers against a scripted connection (no SQL, no registry)."""

    def setUp(self):
        forbid_real_registry(self)

    def database_handler(self, databases):
        """databases: {name: marker or None}; answers exists/marker lookups."""

        def handler(sql, params):
            if "DB_ID(?)" in sql:
                return [(1 if params[0] in databases else 0,)]
            if ".sys.extended_properties" in sql:
                inner = sql[sql.index("[") + 1 : sql.index("].sys.extended_properties")]
                name = inner.replace("]]", "]")
                marker = databases.get(name)
                return [(marker,)] if marker else []
            return []

        return handler

    def test_database_marker_is_empty_for_missing_databases_and_quotes_names(self):
        connection = FakeConnection(self.database_handler({"a]b": "marker-1"}))
        self.assertEqual(
            sql_development._database_marker(connection, "a]b"), "marker-1"
        )
        self.assertIn("[a]]b].sys.extended_properties", connection.statements()[1])
        self.assertEqual(
            connection.executed[1][1], (sql_development.DATABASE_MARKER_PROPERTY,)
        )
        missing = FakeConnection(self.database_handler({}))
        self.assertEqual(sql_development._database_marker(missing, "absent"), "")
        self.assertEqual(len(missing.executed), 1)
        unmarked = FakeConnection(self.database_handler({"db": None}))
        self.assertEqual(sql_development._database_marker(unmarked, "db"), "")
        self.assertTrue(all(cursor.closed for cursor in connection.cursors))

    def test_existing_database_without_the_marker_is_never_touched(self):
        for marker in (None, "someone-elses-marker"):
            with self.subTest(marker=marker):
                connection = FakeConnection(
                    self.database_handler({CLIENT_DATABASE: marker})
                )
                with self.assertRaisesRegex(RuntimeError, "ownership marker"):
                    sql_development._ensure_database_container(connection, MARKER)
                self.assertFalse(
                    any("CREATE DATABASE" in sql for sql in connection.statements())
                )

    def test_owned_database_is_reused_and_a_missing_one_is_created_with_the_marker(
        self,
    ):
        owned = FakeConnection(self.database_handler({CLIENT_DATABASE: MARKER}))
        self.assertIs(sql_development._ensure_database_container(owned, MARKER), False)
        self.assertFalse(any("CREATE DATABASE" in sql for sql in owned.statements()))
        fresh = FakeConnection(self.database_handler({}))
        self.assertIs(sql_development._ensure_database_container(fresh, MARKER), True)
        self.assertIn("CREATE DATABASE [OSTV_CLIENT_TEST]", fresh.statements())
        self.assertTrue(all(cursor.closed for cursor in fresh.cursors))
        self.assertTrue(all(cursor.closed for cursor in owned.cursors))
        marker_call = fresh.executed[-1]
        self.assertIn("sp_addextendedproperty", marker_call[0])
        self.assertEqual(
            marker_call[1], (sql_development.DATABASE_MARKER_PROPERTY, MARKER)
        )
        self.assertNotIn(MARKER, marker_call[0])

    def drop(self, connection, name, marker=MARKER):
        sql_development._drop_verified_owned_database(connection, name, marker)

    def test_drop_refuses_databases_outside_the_owned_scope(self):
        for name in ("master", "msdb", "Customer", "ostv_it_lowercase"):
            with self.subTest(name=name):
                connection = FakeConnection(self.database_handler({name: MARKER}))
                with self.assertRaisesRegex(RuntimeError, "outside the owned scope"):
                    self.drop(connection, name)
                self.assertEqual(connection.executed, [])

    def test_drop_requires_the_matching_marker_before_dropping(self):
        for marker in (None, "other-marker"):
            with self.subTest(marker=marker):
                connection = FakeConnection(
                    self.database_handler({CLIENT_DATABASE: marker})
                )
                with self.assertRaisesRegex(RuntimeError, "ownership marker changed"):
                    self.drop(connection, CLIENT_DATABASE)
                self.assertFalse(
                    any("DROP DATABASE" in s for s in connection.statements())
                )
        disposable = FakeConnection(self.database_handler({"OSTV_IT_run1": None}))
        with self.assertRaisesRegex(RuntimeError, "ownership marker changed"):
            self.drop(disposable, "OSTV_IT_run1")
        self.assertFalse(any("DROP DATABASE" in s for s in disposable.statements()))

    def test_drop_removes_only_verified_owned_databases_with_quoted_names(self):
        client = FakeConnection(self.database_handler({CLIENT_DATABASE: MARKER}))
        self.drop(client, CLIENT_DATABASE)
        self.assertEqual(
            client.statements()[-1],
            "ALTER DATABASE [OSTV_CLIENT_TEST] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
            "DROP DATABASE [OSTV_CLIENT_TEST]",
        )
        self.assertTrue(all(cursor.closed for cursor in client.cursors))
        hostile = "OSTV_IT_x]; DROP DATABASE [master"
        disposable = FakeConnection(self.database_handler({hostile: "run-marker"}))
        self.drop(disposable, hostile)
        quoted = "[OSTV_IT_x]]; DROP DATABASE [master]"
        self.assertEqual(
            disposable.statements()[-1],
            f"ALTER DATABASE {quoted} SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
            f"DROP DATABASE {quoted}",
        )

    def inventory_connection(self, **overrides):
        databases = overrides.get(
            "databases",
            {
                CLIENT_DATABASE: MARKER,
                "OSTV_IT_marked": "run-1",
                "OSTV_IT_unmarked": None,
                "Customer": "x",
            },
        )
        logins = overrides.get(
            "logins",
            [
                "CORP\\me",
                "CORP\\installer",
                CLIENT_LOGIN,
                sql_development.INTEGRATION_LOGIN,
                "OSTV_IT_TMP_abc",
                "NT AUTHORITY\\SYSTEM",
                "intruder",
                "another-intruder",
            ],
        )
        base = self.database_handler(databases)

        def handler(sql, params):
            if "database_id>4 ORDER BY" in sql:
                return [(name,) for name in databases]
            if "ORIGINAL_LOGIN()" in sql:
                return [("CORP\\me",)]
            if "sys.server_principals" in sql:
                return [(name,) for name in logins]
            if "dm_exec_sessions" in sql:
                return [(overrides.get("sessions", 0),)]
            if "PendingRestores" in sql:
                return [(overrides.get("restores", 0),)]
            return base(sql, params)

        return FakeConnection(handler)

    def test_teardown_inventory_classifies_databases_logins_and_activity(self):
        connection = self.inventory_connection(sessions=3, restores=2)
        with patch.object(
            sql_development, "_registry_value", return_value="CORP\\installer"
        ):
            inventory = sql_development._collect_teardown_inventory(connection, MARKER)
        self.assertEqual(
            inventory,
            TeardownInventory(
                owned_databases=(CLIENT_DATABASE, "OSTV_IT_marked"),
                unowned_databases=("OSTV_IT_unmarked", "Customer"),
                unexpected_logins=("another-intruder", "intruder"),
                active_sessions=3,
                pending_restores=2,
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "unmarked or unrelated"):
            validate_teardown_inventory(inventory)

    def test_client_database_with_another_marker_is_unowned_in_the_inventory(self):
        connection = self.inventory_connection(
            databases={CLIENT_DATABASE: "other-marker"}, logins=[]
        )
        with patch.object(sql_development, "_registry_value", return_value=""):
            inventory = sql_development._collect_teardown_inventory(connection, MARKER)
        self.assertEqual(inventory.owned_databases, ())
        self.assertEqual(inventory.unowned_databases, (CLIENT_DATABASE,))

    def test_a_blank_environment_marker_never_claims_an_unmarked_client_database(self):
        connection = self.inventory_connection(
            databases={CLIENT_DATABASE: None}, logins=[]
        )
        with patch.object(sql_development, "_registry_value", return_value=""):
            inventory = sql_development._collect_teardown_inventory(connection, "")
        self.assertEqual(inventory.owned_databases, ())
        self.assertEqual(inventory.unowned_databases, (CLIENT_DATABASE,))
        self.assertTrue(all(cursor.closed for cursor in connection.cursors))

    def test_clean_owned_environment_yields_an_inventory_safe_to_remove(self):
        connection = self.inventory_connection(
            databases={CLIENT_DATABASE: MARKER}, logins=[CLIENT_LOGIN, "CORP\\me"]
        )
        with patch.object(
            sql_development, "_registry_value", return_value="CORP\\installer"
        ):
            inventory = sql_development._collect_teardown_inventory(connection, MARKER)
        self.assertEqual(inventory, TeardownInventory((CLIENT_DATABASE,), (), (), 0, 0))
        validate_teardown_inventory(inventory)

    def test_master_object_removal_refuses_unsafe_login_names_before_dropping(self):
        for hostile in (
            "OSTV_IT_TMP_x]; DROP LOGIN [sa",
            "OSTV_IT_TMP_é",
            "OTHER_TMP_x",
            "OSTV_IT_TMP_a b",
        ):
            with self.subTest(hostile=hostile):
                connection = FakeConnection(
                    lambda sql, params, h=hostile: (
                        [(h,)] if "sys.server_principals" in sql else []
                    )
                )
                with self.assertRaisesRegex(RuntimeError, "outside the owned scope"):
                    sql_development._remove_owned_master_objects(connection)
                self.assertFalse(any("DROP" in s for s in connection.statements()))
                self.assertTrue(connection.cursors[0].closed)

    def test_master_object_removal_drops_only_owned_temporary_logins_and_markers(self):
        connection = FakeConnection(
            lambda sql, params: (
                [("OSTV_IT_TMP_one",), ("OSTV_IT_TMP_two",)]
                if "sys.server_principals" in sql
                else []
            )
        )
        sql_development._remove_owned_master_objects(connection)
        self.assertTrue(all(cursor.closed for cursor in connection.cursors))
        statements = connection.statements()
        self.assertEqual(statements[1], "DROP LOGIN [OSTV_IT_TMP_one]")
        self.assertEqual(statements[2], "DROP LOGIN [OSTV_IT_TMP_two]")
        bulk = statements[3]
        self.assertIn(f"DROP LOGIN [{CLIENT_LOGIN}]", bulk)
        self.assertIn(f"DROP LOGIN [{sql_development.INTEGRATION_LOGIN}]", bulk)
        self.assertIn("DROP SCHEMA [ostv_it]", bulk)
        self.assertNotIn("DROP LOGIN [sa]", bulk)
        self.assertNotIn("DROP DATABASE", " ".join(statements))
        marker_calls = [
            e for e in connection.executed if "sp_dropextendedproperty" in e[0]
        ]
        self.assertEqual(
            [params for _sql, params in marker_calls],
            [
                (sql_development.ENVIRONMENT_MARKER_PROPERTY,) * 2,
                ("OSTVisualizerDisposableTestServer",) * 2,
                ("OSTVisualizerDisposableBackupRoot",) * 2,
            ],
        )

    def test_login_password_is_sent_as_a_parameter_never_inside_the_sql_text(self):
        connection = FakeConnection()
        password = "runtime-only-test-value'; DROP LOGIN sa;--"
        sql_development._set_login_password(connection, password)
        ((sql, params),) = connection.executed
        self.assertEqual(params, (password,))
        self.assertNotIn("runtime-only-test-value", sql)
        self.assertIn("QUOTENAME(@secret, NCHAR(39))", sql)
        self.assertTrue(connection.cursors[0].closed)

    def test_client_permission_verification_requires_the_exact_expected_counts(self):
        denials = 3 * len(SQL_CLIENT_PROTECTED_OSTV_TABLES)
        good = FakeConnection(lambda sql, params: [(1, 1, 2, denials)])
        sql_development._verify_client_permissions(good.cursor())
        sql, params = good.executed[-1]
        self.assertEqual(sql.count("?"), len(params))
        self.assertEqual(params.count(CLIENT_LOGIN), 4)
        for wrong in (
            (1, 0, 2, denials),
            (1, 1, 1, denials),
            (1, 1, 2, denials - 1),
            (0, 1, 2, denials),
        ):
            with self.subTest(wrong=wrong):
                connection = FakeConnection(lambda sql, params, w=wrong: [w])
                with self.assertRaisesRegex(RuntimeError, "roles were not applied"):
                    sql_development._verify_client_permissions(connection.cursor())

    def test_marker_resolution_requires_agreement_and_persists_the_result(self):
        other = str(uuid.uuid4())
        existing = _secrets("runtime-only-test-value")
        cases = {
            "all agree": (MARKER, MARKER, existing, MARKER),
            "sql only": (MARKER, "", None, MARKER),
            "registry only": ("", MARKER, None, MARKER),
            "file only": ("", "", existing, MARKER),
        }
        for label, (
            sql_marker,
            registry_marker,
            secrets_value,
            expected,
        ) in cases.items():
            with self.subTest(label):
                connection = object()
                with (
                    patch.object(
                        sql_development, "_server_property", return_value=sql_marker
                    ) as read,
                    patch.object(
                        sql_development, "_registry_value", return_value=registry_marker
                    ) as registry,
                    patch.object(sql_development, "_set_server_property") as persist,
                ):
                    result = sql_development._resolve_ownership_marker(
                        connection, secrets_value
                    )
                read.assert_called_once_with(
                    connection, sql_development.ENVIRONMENT_MARKER_PROPERTY
                )
                registry.assert_called_once_with("OwnershipMarker")
                self.assertEqual(result, expected)
                persist.assert_called_once_with(
                    connection, sql_development.ENVIRONMENT_MARKER_PROPERTY, expected
                )
        with (
            patch.object(sql_development, "_server_property", return_value=""),
            patch.object(sql_development, "_registry_value", return_value=""),
            patch.object(sql_development, "_set_server_property") as persist,
        ):
            generated = sql_development._resolve_ownership_marker(object(), None)
        self.assertEqual(str(uuid.UUID(generated)), generated)
        persist.assert_called_once()
        for label, (sql_marker, registry_marker, secrets_value, message) in {
            "conflict": (MARKER, other, None, "do not agree"),
            "file conflict": (
                MARKER,
                "",
                _secrets("x", ownership_marker=other),
                "do not agree",
            ),
            "not a uuid": ("not-a-uuid", "", None, "marker is invalid"),
        }.items():
            with self.subTest(label):
                with (
                    patch.object(
                        sql_development, "_server_property", return_value=sql_marker
                    ),
                    patch.object(
                        sql_development, "_registry_value", return_value=registry_marker
                    ),
                    patch.object(sql_development, "_set_server_property") as persist,
                ):
                    with self.assertRaisesRegex(RuntimeError, message):
                        sql_development._resolve_ownership_marker(
                            object(), secrets_value
                        )
                persist.assert_not_called()

    def test_blank_client_databases_are_initialized_and_foreign_schemas_are_not(self):
        blank = SimpleNamespace(schema_version=0, tables=frozenset())
        initialized = SimpleNamespace(
            schema_version=1, tables=frozenset({("dbo", "X")})
        )
        foreign = SimpleNamespace(
            schema_version=0, tables=frozenset({("dbo", "Other")})
        )
        location = sql_development._windows_location(CLIENT_DATABASE)

        class Inspector:
            inventories = []

            def inspect(self, _location):
                return Inspector.inventories.pop(0)

        creator = MagicMock()
        validator = MagicMock()
        validator.return_value.validate.return_value.is_valid = True
        with (
            patch.object(sql_development, "SqlSchemaInspector", Inspector),
            patch.object(sql_development, "SqlDatabaseCreator", return_value=creator),
            patch.object(sql_development, "SqlSchemaValidator", validator),
        ):
            Inspector.inventories = [blank, initialized]
            sql_development._ensure_canonical_schema(location)
            creator.initialize_blank_database.assert_called_once_with(
                location,
                application_version="development-setup",
                actor="OST Visualizer SQL development setup",
            )
            self.assertEqual(Inspector.inventories, [])
            creator.reset_mock()
            validator.return_value.validate.return_value.is_valid = False
            Inspector.inventories = [foreign]
            with self.assertRaisesRegex(RuntimeError, "not canonical schema v1"):
                sql_development._ensure_canonical_schema(location)
            creator.initialize_blank_database.assert_not_called()
            creator.reset_mock()
            Inspector.inventories = [
                SimpleNamespace(schema_version=1, tables=frozenset())
            ]
            with self.assertRaisesRegex(RuntimeError, "not canonical schema v1"):
                sql_development._ensure_canonical_schema(location)
            creator.initialize_blank_database.assert_not_called()

    def test_client_permissions_are_committed_only_after_verification(self):
        connection = FakeConnection()
        target = FakeConnection()
        with (
            patch.object(
                sql_development.pyodbc, "connect", return_value=target
            ) as connect,
            patch.object(sql_development, "apply_sql_client_permissions") as apply,
            patch.object(sql_development, "_verify_client_permissions") as verify,
            patch.object(sql_development, "_set_login_password") as set_password,
        ):
            sql_development._configure_client_login_and_permissions(
                connection, "runtime-only-test-value", update_password=False
            )
            set_password.assert_not_called()
            apply.assert_called_once_with(target.cursors[0], CLIENT_LOGIN)
            verify.assert_called_once_with(target.cursors[0])
            self.assertEqual(
                target.statements(),
                [
                    f"IF USER_ID(N'{CLIENT_LOGIN}') IS NULL "
                    f"CREATE USER [{CLIENT_LOGIN}] FOR LOGIN [{CLIENT_LOGIN}]"
                ],
            )
            self.assertTrue(all(cursor.closed for cursor in target.cursors))
            self.assertTrue(all(cursor.closed for cursor in connection.cursors))
            self.assertTrue(target.committed)
            self.assertFalse(target.rolled_back)
            self.assertTrue(target.closed)
            connect.assert_called_once_with(
                sql_development._windows_connection_string(CLIENT_DATABASE),
                autocommit=False,
            )
            sql_development._configure_client_login_and_permissions(
                connection, "runtime-only-test-value", update_password=True
            )
            set_password.assert_called_once_with(connection, "runtime-only-test-value")
        self.assertEqual(
            connection.statements(),
            [
                f"ALTER LOGIN [{CLIENT_LOGIN}] ENABLE; "
                f"ALTER LOGIN [{CLIENT_LOGIN}] WITH DEFAULT_DATABASE=[{CLIENT_DATABASE}]"
            ]
            * 2,
        )

    def test_failed_permission_verification_rolls_back_and_closes_the_database_session(
        self,
    ):
        connection = FakeConnection()
        target = FakeConnection()
        with (
            patch.object(sql_development.pyodbc, "connect", return_value=target),
            patch.object(sql_development, "apply_sql_client_permissions"),
            patch.object(
                sql_development,
                "_verify_client_permissions",
                side_effect=RuntimeError("roles were not applied"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "roles were not applied"):
                sql_development._configure_client_login_and_permissions(
                    connection, "runtime-only-test-value", update_password=False
                )
        self.assertFalse(target.committed)
        self.assertTrue(target.rolled_back)
        self.assertTrue(target.closed)
        self.assertTrue(all(cursor.closed for cursor in target.cursors))

    def test_login_and_property_helpers_bind_their_names_and_close_their_cursors(self):
        connection = FakeConnection(lambda sql, params: [(1,)])
        self.assertIs(sql_development._login_exists(connection, "a]b"), True)
        sql, params = connection.executed[-1]
        self.assertEqual(params, ("a]b",))
        self.assertIn("SUSER_ID(?)", sql)
        missing = FakeConnection(lambda sql, params: [(0,)])
        self.assertIs(sql_development._login_exists(missing, "absent"), False)
        self.assertTrue(connection.cursors[0].closed and missing.cursors[0].closed)
        stored = FakeConnection(lambda sql, params: [("marker-1",)])
        self.assertEqual(
            sql_development._server_property(stored, "Property"), "marker-1"
        )
        sql, params = stored.executed[-1]
        self.assertEqual(params, ("Property",))
        self.assertIn("class=0 AND name=?", sql)
        for rows in ([], [(7,)]):
            empty = FakeConnection(lambda sql, params, r=rows: r)
            self.assertEqual(
                sql_development._server_property(empty, "Property"),
                "" if not rows else "7",
            )
            self.assertTrue(empty.cursors[0].closed)
        writer = FakeConnection()
        sql_development._set_server_property(writer, "Property", "marker-value")
        ((sql, params),) = writer.executed
        self.assertEqual(
            params, ("Property", "Property", "marker-value", "Property", "marker-value")
        )
        self.assertNotIn("marker-value", sql)
        self.assertLess(
            sql.index("sp_updateextendedproperty"), sql.index("sp_addextendedproperty")
        )
        self.assertTrue(writer.cursors[0].closed)

    def test_the_server_marker_must_be_present_and_equal(self):
        def server(marker):
            def handler(sql, params):
                self.assertEqual(params, (sql_development.ENVIRONMENT_MARKER_PROPERTY,))
                return [] if marker is None else [(marker,)]

            return FakeConnection(handler)

        self.assertIsNone(
            sql_development._require_server_marker(server(MARKER), MARKER)
        )
        for actual, expected in (
            (None, MARKER),
            ("", ""),
            ("other", MARKER),
            (MARKER, "other"),
        ):
            with self.subTest(actual=actual, expected=expected):
                with self.assertRaisesRegex(RuntimeError, "server ownership marker"):
                    sql_development._require_server_marker(server(actual), expected)

    def test_a_descriptor_numbered_zero_is_still_closed_when_no_stream_was_created(
        self,
    ):
        closed = []
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sql-development.json"
            with (
                patch.object(os, "open", return_value=0),
                patch.object(os, "fdopen", side_effect=OSError("no stream")),
                patch.object(os, "close", side_effect=closed.append),
            ):
                with self.assertRaisesRegex(OSError, "no stream"):
                    write_secrets_atomic(path, _secrets("runtime-only-test-value"))
        self.assertEqual(closed, [0])


class SqlDevelopmentWorkflowGuardTests(unittest.TestCase):
    """Provision/teardown orchestration with every external effect replaced."""

    def setUp(self):
        forbid_real_registry(self)
        replace_patch = windows_safe_replace()
        replace_patch.start()
        self.addCleanup(replace_patch.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.secrets_path = Path(self.tmp.name) / ".secrets" / "sql-development.json"
        self.connection = FakeConnection()
        self.store = MagicMock()
        self.store.read_password.return_value = ""
        self.calls = {}
        for name, value in {
            "_windows_connection": self.connection,
            "WindowsCredentialStore": self.store,
        }.items():
            target = patch.object(sql_development, name, return_value=value)
            target.start()
            self.addCleanup(target.stop)
        for name, kwargs in {
            "require_owned_sql_instance": {},
            "_registry_exists": {"return_value": False},
            "_resolve_ownership_marker": {"return_value": MARKER},
            "_validate_registry_ownership": {},
            "_login_exists": {"return_value": False},
            "_ensure_database_container": {"return_value": True},
            "_ensure_canonical_schema": {},
            "_write_registry_ownership": {},
            "_installer_principal": {"return_value": "CORP\\dev"},
            "_client_login_accepts": {"return_value": False},
            "_configure_client_login_and_permissions": {},
            "_set_login_password": {},
        }.items():
            target = patch.object(sql_development, name, **kwargs)
            self.calls[name] = target.start()
            self.addCleanup(target.stop)
        inspector = patch.object(sql_development, "SqlSchemaInspector")
        self.inspector = inspector.start()
        self.addCleanup(inspector.stop)
        self.inspector.return_value.inspect.return_value = SimpleNamespace(
            schema_version=1, schema_checksum=sql_development.SQL_SCHEMA_V1.checksum
        )

    def test_unowned_login_blocks_provisioning_before_any_database_change(self):
        self.calls["_login_exists"].return_value = True
        with self.assertRaisesRegex(
            RuntimeError, "login exists without a setup ownership"
        ):
            sql_development._provision(self.secrets_path, False)
        self.calls["_ensure_database_container"].assert_not_called()
        self.calls["_configure_client_login_and_permissions"].assert_not_called()
        self.assertTrue(self.connection.closed)
        self.assertFalse(self.secrets_path.exists())

    def test_unowned_credential_target_blocks_provisioning(self):
        self.store.read_password.return_value = "pre-existing-secret"
        with self.assertRaisesRegex(RuntimeError, "credential target exists without"):
            sql_development._provision(self.secrets_path, False)
        self.calls["_ensure_database_container"].assert_not_called()
        self.store.write_password.assert_not_called()
        self.assertTrue(self.connection.closed)

    def test_first_provision_writes_credential_and_secrets_then_reports_status(self):
        result = sql_development._provision(self.secrets_path, False)
        self.assertEqual(
            result,
            {
                "status": "configured",
                "database_created": True,
                "credential_rotated": True,
                "schema_version": 1,
                "schema_checksum_valid": True,
                "ownership_marker_configured": True,
            },
        )
        written = read_secrets(self.secrets_path)
        self.assertEqual(written.ownership_marker, MARKER)
        self.assertEqual(self.store.write_password.call_count, 1)
        target, login, password = self.store.write_password.call_args.args
        self.assertEqual((target, login), (CLIENT_CREDENTIAL_TARGET, CLIENT_LOGIN))
        self.assertEqual(written.password, password)
        self.assertNotIn(password, json.dumps(result))
        self.calls["_configure_client_login_and_permissions"].assert_called_once_with(
            self.connection, password, update_password=True
        )
        self.assertTrue(self.connection.closed)

    def test_failed_credential_store_write_restores_the_previous_login_password(self):
        write_secrets_atomic(self.secrets_path, _secrets("previous-runtime-value"))
        self.calls["_login_exists"].return_value = True
        self.calls["_client_login_accepts"].return_value = True
        self.store.write_password.side_effect = OSError("credential store unavailable")
        with self.assertRaisesRegex(OSError, "credential store unavailable"):
            sql_development._provision(self.secrets_path, True)
        self.calls["_set_login_password"].assert_called_once_with(
            self.connection, "previous-runtime-value"
        )
        self.assertEqual(
            read_secrets(self.secrets_path).password, "previous-runtime-value"
        )
        self.assertTrue(self.connection.closed)

    def test_failed_credential_store_write_on_a_new_login_does_not_reset_passwords(
        self,
    ):
        self.store.write_password.side_effect = OSError("credential store unavailable")
        with self.assertRaises(OSError):
            sql_development._provision(self.secrets_path, False)
        self.calls["_set_login_password"].assert_not_called()
        self.assertFalse(self.secrets_path.exists())

    def test_complete_teardown_refuses_a_changed_marker_before_deleting_anything(self):
        stored = _secrets("runtime-only-test-value")
        self.secrets_path.parent.mkdir(parents=True)
        write_secrets_atomic(self.secrets_path, stored)
        changed = _secrets(
            "runtime-only-test-value", ownership_marker=str(uuid.uuid4())
        )
        with (
            patch.object(
                sql_development, "_required_owned_secrets", return_value=stored
            ),
            patch.object(sql_development, "read_secrets", return_value=changed),
            patch.object(sql_development, "_remove_user_environment") as environment,
        ):
            with self.assertRaisesRegex(RuntimeError, "marker changed during teardown"):
                sql_development._complete_teardown(self.secrets_path)
        self.store.delete_password.assert_not_called()
        environment.assert_not_called()
        self.assertTrue(self.secrets_path.exists())

    def test_complete_teardown_removes_credentials_environment_and_secrets_file(self):
        stored = _secrets("runtime-only-test-value")
        self.secrets_path.parent.mkdir(parents=True)
        write_secrets_atomic(self.secrets_path, stored)
        with (
            patch.object(
                sql_development, "_required_owned_secrets", return_value=stored
            ),
            patch.object(sql_development, "_remove_user_environment") as environment,
        ):
            result = sql_development._complete_teardown(self.secrets_path)
        self.assertEqual(result, {"status": "completed", "credentials_removed": True})
        self.assertEqual(
            [c.args[0] for c in self.store.delete_password.call_args_list],
            [CLIENT_CREDENTIAL_TARGET, sql_development.INTEGRATION_CREDENTIAL_TARGET],
        )
        environment.assert_called_once_with()
        self.assertFalse(self.secrets_path.exists())

    def test_required_owned_secrets_demand_a_file_and_an_agreeing_registry_marker(self):
        with self.assertRaisesRegex(RuntimeError, "secrets file is missing"):
            sql_development._required_owned_secrets(self.secrets_path)
        write_secrets_atomic(self.secrets_path, _secrets("runtime-only-test-value"))
        for registry_marker in ("", str(uuid.uuid4())):
            with self.subTest(registry_marker=registry_marker):
                with patch.object(
                    sql_development, "_registry_value", return_value=registry_marker
                ):
                    with self.assertRaisesRegex(RuntimeError, "markers do not agree"):
                        sql_development._required_owned_secrets(self.secrets_path)
        with patch.object(sql_development, "_registry_value", return_value=MARKER):
            stored = sql_development._required_owned_secrets(self.secrets_path)
        self.assertEqual(stored.ownership_marker, MARKER)
        self.calls["_validate_registry_ownership"].assert_called_with(MARKER)

    def test_teardown_commands_verify_marker_and_inventory_before_dropping(self):
        stored = _secrets("runtime-only-test-value")
        unsafe = TeardownInventory((CLIENT_DATABASE,), ("Customer",), (), 0, 0)
        with (
            patch.object(
                sql_development, "_required_owned_secrets", return_value=stored
            ),
            patch.object(sql_development, "_require_server_marker") as marker,
            patch.object(
                sql_development, "_collect_teardown_inventory", return_value=unsafe
            ),
            patch.object(sql_development, "_drop_verified_owned_database") as drop,
            patch.object(sql_development, "_remove_owned_master_objects") as remove,
        ):
            with self.assertRaisesRegex(RuntimeError, "unmarked or unrelated"):
                sql_development._prepare_teardown(self.secrets_path)
            marker.assert_called_once_with(self.connection, MARKER)
            with self.assertRaisesRegex(RuntimeError, "unmarked or unrelated"):
                sql_development._verify_teardown(self.secrets_path)
        self.assertEqual(marker.call_count, 2)
        drop.assert_not_called()
        remove.assert_not_called()
        self.assertTrue(self.connection.closed)

    def test_prepare_teardown_drops_each_owned_database_then_master_objects(self):
        stored = _secrets("runtime-only-test-value")
        safe = TeardownInventory((CLIENT_DATABASE, "OSTV_IT_run"), (), (), 0, 0)
        order = []
        with (
            patch.object(
                sql_development, "_required_owned_secrets", return_value=stored
            ),
            patch.object(sql_development, "_require_server_marker"),
            patch.object(
                sql_development, "_collect_teardown_inventory", return_value=safe
            ),
            patch.object(
                sql_development,
                "_drop_verified_owned_database",
                side_effect=lambda c, name, marker: order.append(
                    ("drop", name, marker)
                ),
            ),
            patch.object(
                sql_development,
                "_remove_owned_master_objects",
                side_effect=lambda c: order.append(("master",)),
            ),
        ):
            result = sql_development._prepare_teardown(self.secrets_path)
            verified = sql_development._verify_teardown(self.secrets_path)
        self.assertEqual(result, {"status": "prepared", "sql_resources_removed": True})
        self.assertEqual(
            order,
            [
                ("drop", CLIENT_DATABASE, MARKER),
                ("drop", "OSTV_IT_run", MARKER),
                ("master",),
            ],
        )
        self.assertEqual(
            verified,
            {
                "status": "verified",
                "owned_database_count": 2,
                "safe_for_instance_removal": True,
            },
        )

    def run_main(self, argv):
        out = io.StringIO()
        with (
            patch.object(sys, "argv", ["manage_sql_development.py", *argv]),
            contextlib.redirect_stdout(out),
        ):
            code = sql_development.main()
        return code, out.getvalue()

    def test_main_routes_each_action_and_prints_sorted_json(self):
        repo = Path(self.tmp.name) / "repo"
        (repo / "ost_visualizer").mkdir(parents=True)
        secrets_path = repo.resolve() / ".secrets" / "sql-development.json"
        routes = {
            "--provision": "_provision",
            "--verify-teardown": "_verify_teardown",
            "--prepare-teardown": "_prepare_teardown",
            "--complete-teardown": "_complete_teardown",
        }
        for flag, name in routes.items():
            with self.subTest(flag=flag):
                with patch.object(
                    sql_development, name, return_value={"b": 1, "a": 2}
                ) as route:
                    code, output = self.run_main([flag, "--repo-root", str(repo)])
                self.assertEqual((code, output), (0, '{"a": 2, "b": 1}\n'))
                if flag == "--provision":
                    route.assert_called_once_with(secrets_path, False)
                else:
                    route.assert_called_once_with(secrets_path)
        with patch.object(sql_development, "_provision", return_value={}) as route:
            self.run_main(
                ["--provision", "--rotate-client-password", "--repo-root", str(repo)]
            )
        route.assert_called_once_with(secrets_path, True)

    def test_main_requires_exactly_one_action_and_a_valid_repo_root(self):
        repo = Path(self.tmp.name) / "repo"
        repo.mkdir()
        for argv in (
            [],
            ["--provision"],
            ["--provision", "--verify-teardown", "--repo-root", str(repo)],
            ["--repo-root", str(repo)],
            ["--rotate-client-password", "--repo-root", str(repo)],
        ):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        self.run_main(argv)
                self.assertEqual(raised.exception.code, 2)
        with patch.object(sql_development, "_provision") as route:
            with self.assertRaisesRegex(ValueError, "does not identify OST Visualizer"):
                self.run_main(["--provision", "--repo-root", str(repo)])
        route.assert_not_called()

    def provision_with(
        self,
        *,
        store_password="",
        registry=False,
        secrets_password=None,
        login_exists=False,
        accepts=False,
        rotate=False,
    ):
        if secrets_password is not None:
            write_secrets_atomic(self.secrets_path, _secrets(secrets_password))
        self.store.read_password.return_value = store_password
        self.calls["_registry_exists"].return_value = registry
        self.calls["_login_exists"].return_value = login_exists
        self.calls["_client_login_accepts"].return_value = accepts
        return sql_development._provision(self.secrets_path, rotate)

    def test_provisioning_runs_its_steps_in_order_with_the_right_arguments(self):
        parent = MagicMock()
        for name, mock in self.calls.items():
            parent.attach_mock(mock, name)
        self.provision_with()
        password = self.store.write_password.call_args.args[2]
        self.assertEqual(
            parent.mock_calls,
            [
                call.require_owned_sql_instance(self.connection),
                call._registry_exists(),
                call._resolve_ownership_marker(self.connection, None),
                call._validate_registry_ownership(MARKER),
                call._login_exists(self.connection, CLIENT_LOGIN),
                call._ensure_database_container(self.connection, MARKER),
                call._ensure_canonical_schema(
                    sql_development._windows_location(CLIENT_DATABASE)
                ),
                call._installer_principal(),
                call._write_registry_ownership(MARKER, "CORP\\dev"),
                call._configure_client_login_and_permissions(
                    self.connection, password, update_password=True
                ),
            ],
        )
        self.assertEqual(self.store.mock_calls[-1][0], "write_password")
        self.assertEqual(
            self.inspector.return_value.inspect.call_args.args,
            (sql_development._windows_location(CLIENT_DATABASE),),
        )

    def test_either_a_registry_key_or_a_secrets_file_proves_ownership_of_a_login(self):
        with self.assertRaisesRegex(RuntimeError, "RotateClientPassword"):
            self.provision_with(registry=True, login_exists=True)
        self.calls["_configure_client_login_and_permissions"].assert_not_called()
        write_secrets_atomic(self.secrets_path, _secrets("stored-in-the-file"))
        self.calls["_client_login_accepts"].return_value = True
        self.calls["_login_exists"].return_value = True
        result = sql_development._provision(self.secrets_path, False)
        self.assertIs(result["credential_rotated"], False)
        self.calls["_configure_client_login_and_permissions"].assert_called_once_with(
            self.connection, "stored-in-the-file", update_password=False
        )
        self.store.write_password.assert_called_once_with(
            CLIENT_CREDENTIAL_TARGET, CLIENT_LOGIN, "stored-in-the-file"
        )

    def test_an_existing_credential_target_is_acceptable_once_ownership_is_recorded(
        self,
    ):
        self.provision_with(store_password="from-the-store", registry=True)
        self.calls["_client_login_accepts"].assert_called_once_with("from-the-store")

    def test_the_credential_store_password_wins_over_the_secrets_file(self):
        self.provision_with(
            store_password="from-the-store",
            secrets_password="from-the-file",
            login_exists=True,
            accepts=True,
        )
        self.calls["_client_login_accepts"].assert_called_once_with("from-the-store")
        self.calls["_configure_client_login_and_permissions"].assert_called_once_with(
            self.connection, "from-the-store", update_password=False
        )

    def test_the_secrets_file_password_is_used_when_the_store_has_none(self):
        self.provision_with(
            secrets_password="from-the-file", login_exists=True, accepts=True
        )
        self.calls["_client_login_accepts"].assert_called_once_with("from-the-file")

    def test_no_stored_password_means_the_server_is_never_probed(self):
        self.provision_with()
        self.calls["_client_login_accepts"].assert_not_called()

    def test_a_stored_password_the_server_rejects_needs_explicit_rotation(self):
        with self.assertRaisesRegex(RuntimeError, "RotateClientPassword"):
            self.provision_with(
                secrets_password="stale", login_exists=True, accepts=False
            )
        self.calls["_configure_client_login_and_permissions"].assert_not_called()
        self.store.write_password.assert_not_called()
        self.assertTrue(self.connection.closed)
        self.assertEqual(read_secrets(self.secrets_path).password, "stale")

    def test_the_previous_login_password_is_restored_only_when_it_was_replaced(self):
        self.store.write_password.side_effect = OSError("store unavailable")
        scenarios = {
            "login kept its working password": dict(
                secrets_password="previous", login_exists=True, accepts=True
            ),
            "rotation without a previous password": dict(
                registry=True, login_exists=True, rotate=True
            ),
            "login did not exist before": dict(
                secrets_password="previous", login_exists=False, rotate=True
            ),
        }
        for label, arguments in scenarios.items():
            with self.subTest(label):
                self.secrets_path.unlink(missing_ok=True)
                self.calls["_set_login_password"].reset_mock()
                with self.assertRaisesRegex(OSError, "store unavailable"):
                    self.provision_with(**arguments)
                self.calls["_set_login_password"].assert_not_called()
        self.secrets_path.unlink(missing_ok=True)
        self.calls["_set_login_password"].reset_mock()
        with self.assertRaisesRegex(OSError, "store unavailable"):
            self.provision_with(
                secrets_password="previous",
                login_exists=True,
                accepts=True,
                rotate=True,
            )
        self.calls["_set_login_password"].assert_called_once_with(
            self.connection, "previous"
        )

    def test_a_non_canonical_schema_stops_provisioning_before_any_ownership_is_recorded(
        self,
    ):
        self.calls["_ensure_canonical_schema"].side_effect = RuntimeError(
            "not canonical"
        )
        with self.assertRaisesRegex(RuntimeError, "not canonical"):
            self.provision_with()
        self.calls["_write_registry_ownership"].assert_not_called()
        self.calls["_configure_client_login_and_permissions"].assert_not_called()
        self.store.write_password.assert_not_called()
        self.assertTrue(self.connection.closed)

    def test_teardown_checks_the_instance_marker_and_inventory_and_closes_the_connection(
        self,
    ):
        stored = _secrets("runtime-only-test-value")
        safe = TeardownInventory((CLIENT_DATABASE,), (), (), 0, 0)
        for function in (
            sql_development._prepare_teardown,
            sql_development._verify_teardown,
        ):
            with self.subTest(function=function.__name__):
                self.connection.closed = False
                self.calls["require_owned_sql_instance"].reset_mock()
                with (
                    patch.object(
                        sql_development, "_required_owned_secrets", return_value=stored
                    ),
                    patch.object(sql_development, "_require_server_marker") as marker,
                    patch.object(
                        sql_development,
                        "_collect_teardown_inventory",
                        return_value=safe,
                    ) as collect,
                    patch.object(sql_development, "_drop_verified_owned_database"),
                    patch.object(sql_development, "_remove_owned_master_objects"),
                ):
                    function(self.secrets_path)
                self.calls["require_owned_sql_instance"].assert_called_once_with(
                    self.connection
                )
                marker.assert_called_once_with(self.connection, MARKER)
                collect.assert_called_once_with(self.connection, MARKER)
                self.assertTrue(self.connection.closed)

    def test_a_vanished_secrets_file_counts_as_a_changed_marker_during_teardown(self):
        stored = _secrets("runtime-only-test-value")
        write_secrets_atomic(self.secrets_path, stored)
        with (
            patch.object(
                sql_development, "_required_owned_secrets", return_value=stored
            ),
            patch.object(sql_development, "read_secrets", return_value=None),
            patch.object(sql_development, "_remove_user_environment") as environment,
        ):
            with self.assertRaisesRegex(RuntimeError, "marker changed during teardown"):
                sql_development._complete_teardown(self.secrets_path)
        self.store.delete_password.assert_not_called()
        environment.assert_not_called()
        self.assertTrue(self.secrets_path.exists())


class FakeRegistry:
    """In-memory stand-in for winreg: one machine key and the user's Environment key."""

    HKEY_LOCAL_MACHINE = "HKLM"
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = "KEY_SET_VALUE"
    REG_SZ = "REG_SZ"

    class _Key:
        def __init__(self, root, values):
            self.root = root
            self.values = values

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def __init__(self, machine=None, environment=None):
        self.machine = machine
        self.environment = {} if environment is None else environment
        self.operations = []

    def OpenKey(self, root, path, reserved=0, access=0):
        self.operations.append(("open", root, path, reserved, access))
        if root == self.HKEY_LOCAL_MACHINE:
            if path != sql_development.REGISTRY_PATH or self.machine is None:
                raise FileNotFoundError(path)
            return self._Key(root, self.machine)
        if root == self.HKEY_CURRENT_USER and path == "Environment":
            return self._Key(root, self.environment)
        raise FileNotFoundError(path)

    def CreateKeyEx(self, root, path, reserved, access):
        self.operations.append(("create", root, path, reserved, access))
        assert root == self.HKEY_LOCAL_MACHINE, root
        assert path == sql_development.REGISTRY_PATH, path
        if self.machine is None:
            self.machine = {}
        return self._Key(root, self.machine)

    def QueryValueEx(self, key, name):
        self.operations.append(("query", key.root, name))
        if name not in key.values:
            raise FileNotFoundError(name)
        return key.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.operations.append(("set", key.root, name, reserved, kind))
        key.values[name] = value

    def DeleteValue(self, key, name):
        self.operations.append(("delete", key.root, name))
        if name not in key.values:
            raise FileNotFoundError(name)
        del key.values[name]


def _owned_machine_values(**overrides):
    values = {
        "OwnershipMarker": MARKER,
        "InstanceName": "OSTVDEV",
        "DatabaseName": CLIENT_DATABASE,
        "ClientLogin": CLIENT_LOGIN,
        "ClientCredentialTarget": CLIENT_CREDENTIAL_TARGET,
        "IntegrationCredentialTarget": sql_development.INTEGRATION_CREDENTIAL_TARGET,
        "InstallerPrincipal": "CORP\\dev",
    }
    values.update(overrides)
    return values


class SqlDevelopmentRegistryTests(unittest.TestCase):
    """The registry helpers against an in-memory winreg (the real one is never opened)."""

    def use(self, **kwargs):
        registry = FakeRegistry(**kwargs)
        patcher = patch.object(sql_development, "winreg", registry)
        patcher.start()
        self.addCleanup(patcher.stop)
        return registry

    def test_the_ownership_key_exists_only_when_the_machine_key_is_there(self):
        self.use()
        self.assertIs(sql_development._registry_exists(), False)
        self.use(machine={})
        self.assertIs(sql_development._registry_exists(), True)

    def test_values_are_read_as_text_and_missing_ones_as_empty(self):
        self.use(machine={"OwnershipMarker": MARKER, "Count": 7})
        self.assertEqual(sql_development._registry_value("OwnershipMarker"), MARKER)
        self.assertEqual(sql_development._registry_value("Count"), "7")
        self.assertEqual(sql_development._registry_value("Absent"), "")
        self.use()
        self.assertEqual(sql_development._registry_value("OwnershipMarker"), "")

    def test_ownership_is_written_to_the_machine_key_only_with_exactly_seven_values(
        self,
    ):
        registry = self.use()
        sql_development._write_registry_ownership(MARKER, "CORP\\dev")
        self.assertEqual(registry.machine, _owned_machine_values())
        self.assertEqual(registry.environment, {})
        self.assertEqual(
            registry.operations[0],
            ("create", "HKLM", sql_development.REGISTRY_PATH, 0, "KEY_SET_VALUE"),
        )
        sets = [op for op in registry.operations if op[0] == "set"]
        self.assertEqual(len(sets), 7)
        self.assertTrue(
            all(op[1:2] == ("HKLM",) and op[3:] == (0, "REG_SZ") for op in sets)
        )

    def test_a_missing_registry_record_is_not_validated_and_never_created(self):
        registry = self.use()
        self.assertIsNone(sql_development._validate_registry_ownership(MARKER))
        self.assertEqual([op[0] for op in registry.operations], ["open"])
        self.assertIsNone(registry.machine)

    def test_a_complete_matching_record_is_accepted(self):
        self.use(machine=_owned_machine_values())
        self.assertIsNone(sql_development._validate_registry_ownership(MARKER))

    def test_every_value_of_an_existing_record_must_match(self):
        for name in (
            "OwnershipMarker",
            "InstanceName",
            "DatabaseName",
            "ClientLogin",
            "ClientCredentialTarget",
            "IntegrationCredentialTarget",
        ):
            with self.subTest(name=name):
                self.use(machine=_owned_machine_values(**{name: "something-else"}))
                with self.assertRaisesRegex(
                    RuntimeError, "registry ownership is invalid"
                ):
                    sql_development._validate_registry_ownership(MARKER)
                values = _owned_machine_values()
                del values[name]
                self.use(machine=values)
                with self.assertRaisesRegex(
                    RuntimeError, "registry ownership is invalid"
                ):
                    sql_development._validate_registry_ownership(MARKER)
        self.use(machine=_owned_machine_values(InstallerPrincipal="anybody"))
        self.assertIsNone(sql_development._validate_registry_ownership(MARKER))

    def test_the_user_environment_loses_only_the_eight_test_variables(self):
        owned = (
            "OSTV_SQL_TEST_SERVER",
            "OSTV_SQL_TEST_AUTH",
            "OSTV_SQL_TEST_USER",
            "OSTV_SQL_TEST_SERVER_MARKER",
            "OSTV_SQL_TEST_CREDENTIAL_TARGET",
            "OSTV_SQL_INTEGRATION",
            "OSTV_SQL_DESTRUCTIVE_TESTS",
            "OSTV_SQL_TEST_PASSWORD",
        )
        registry = self.use(
            machine=_owned_machine_values(),
            environment={
                **{name: "x" for name in owned[:6]},
                "PATH": "keep",
                "TEMP": "keep",
            },
        )
        sql_development._remove_user_environment()
        self.assertEqual(registry.environment, {"PATH": "keep", "TEMP": "keep"})
        self.assertEqual(registry.machine, _owned_machine_values())
        deletes = [op[2] for op in registry.operations if op[0] == "delete"]
        self.assertEqual(deletes, list(owned))
        self.assertEqual(
            registry.operations[0], ("open", "HKCU", "Environment", 0, "KEY_SET_VALUE")
        )
        self.assertTrue(all(op[1] == "HKCU" for op in registry.operations))


class SqlDevelopmentPrimitiveTests(unittest.TestCase):
    def setUp(self):
        replace_patch = windows_safe_replace()
        replace_patch.start()
        self.addCleanup(replace_patch.stop)

    def test_generated_passwords_are_exactly_48_random_bytes_long_in_base64(self):
        self.assertEqual(len(generate_client_password()), 64)

    def test_secret_records_are_immutable(self):
        for value in (
            _secrets("runtime-only-test-value"),
            sql_development.PasswordSelection("password", True),
            TeardownInventory((), (), (), 0, 0),
        ):
            with self.subTest(type=type(value).__name__):
                field = next(iter(value.__dataclass_fields__))
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    setattr(value, field, "changed")

    def test_the_secrets_file_ends_with_a_newline_and_nested_directories_are_created(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "one" / "two" / "sql-development.json"
            write_secrets_atomic(path, _secrets("runtime-only-test-value"))
            self.assertTrue(path.read_text(encoding="utf-8").endswith("}\n"))

    def test_a_secrets_file_is_created_exclusively_owner_only_and_durable_before_rename(
        self,
    ):
        events, opened, written, closed = [], [], [], []
        real_open, real_fsync, real_replace = os.open, os.fsync, os.replace

        def spy_open(path, flags, mode=0o777, **kwargs):
            opened.append(path)
            events.append(
                ("open", Path(path).name[:1], flags & ~getattr(os, "O_BINARY", 0), mode)
            )
            return real_open(path, flags, mode, **kwargs)

        def spy_fsync(descriptor):
            events.append(("fsync",))
            written.append(Path(opened[0]).read_bytes())
            return real_fsync(descriptor)

        def spy_replace(source, destination, *args, **kwargs):
            events.append(("replace", Path(destination).name))
            return real_replace(source, destination, *args, **kwargs)

        def spy_close(descriptor):
            closed.append(descriptor)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sql-development.json"
            with (
                patch.object(os, "open", spy_open),
                patch.object(os, "fsync", spy_fsync),
                patch.object(os, "replace", spy_replace),
                patch.object(os, "close", spy_close),
            ):
                write_secrets_atomic(path, _secrets("runtime-only-test-value"))
        self.assertEqual(
            events,
            [
                ("open", ".", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                ("fsync",),
                ("replace", "sql-development.json"),
            ],
        )
        self.assertEqual(len(written), 1)
        self.assertTrue(written[0].endswith(b"}\n"))
        self.assertEqual(closed, [])

    def test_a_descriptor_that_never_reached_a_stream_is_closed_exactly_once(self):
        real_open, real_close = os.open, os.close
        opened, closed = [], []

        def spy_open(path, flags, mode=0o777, **kwargs):
            descriptor = real_open(path, flags, mode, **kwargs)
            opened.append(descriptor)
            return descriptor

        def spy_close(descriptor):
            closed.append(descriptor)
            if descriptor in opened:
                return real_close(descriptor)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sql-development.json"
            with (
                patch.object(os, "open", spy_open),
                patch.object(os, "close", spy_close),
                patch.object(os, "fdopen", side_effect=OSError("no stream")),
            ):
                with self.assertRaisesRegex(OSError, "no stream"):
                    write_secrets_atomic(path, _secrets("runtime-only-test-value"))
            self.assertEqual(list(Path(temporary).iterdir()), [])
        self.assertEqual(len(opened), 1)
        self.assertEqual(closed, opened)

    def test_a_list_holding_exactly_the_secret_key_names_is_an_invalid_shape(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sql-development.json"
            path.write_text(
                json.dumps(sorted(sql_development._SECRET_KEYS)), encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "invalid shape"):
                read_secrets(path)


class SqlDevelopmentClientLoginProbeTests(unittest.TestCase):
    def probe(self, outcome):
        seen = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def execute(self, sql):
                seen.append(sql)

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
                seen.append((request, autocommit))
                if isinstance(outcome, Exception):
                    raise outcome
                return Lease()

        with patch.object(sql_development, "SqlConnectionManager", Manager):
            return sql_development._client_login_accepts("candidate-password"), seen

    def test_the_candidate_password_is_accepted_only_by_a_real_select_one(self):
        accepted, seen = self.probe(1)
        self.assertIs(accepted, True)
        request, autocommit = seen[0]
        self.assertTrue(autocommit)
        self.assertEqual(request.password, "candidate-password")
        self.assertTrue(request.read_only)
        location = request.location
        self.assertEqual(
            (location.server, location.database, location.username),
            (SERVER_ENDPOINT, CLIENT_DATABASE, CLIENT_LOGIN),
        )
        self.assertEqual(location.authentication_mode.value, "sql_server")
        self.assertTrue(location.encrypt)
        self.assertFalse(location.trust_server_certificate)
        self.assertEqual(seen[1], "SELECT 1")
        self.assertIs(self.probe(0)[0], False)

    def test_connection_failures_mean_the_password_does_not_work(self):
        for error in (
            OSError("down"),
            RuntimeError("login failed"),
            ValueError("bad"),
            SqlInfrastructureError(
                SqlErrorDetails(SqlErrorCode.CONNECTION_FAILED, "login failed")
            ),
        ):
            with self.subTest(error=type(error).__name__):
                self.assertIs(self.probe(error)[0], False)


if __name__ == "__main__":
    unittest.main()
