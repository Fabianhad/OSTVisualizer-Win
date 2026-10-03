from __future__ import annotations
import contextlib
import io
import json
import os
import tempfile
import unittest
import uuid
from datetime import date, datetime, time
from pathlib import Path
from unittest.mock import patch
from sql_server.python.ostv_sql_admin import admin, common
from tests.sql_server.python.ostv_sql_admin.environment_support import (
    windows_safe_replace,
)

PASSWORD = "unique-admin-secret"


def _config(root: Path) -> common.DeploymentConfig:
    return common.DeploymentConfig(
        server="sql.example.internal",
        port=11433,
        database="OSTVisualizer",
        admin_login="OSTV_PROVISIONER",
        client_login="OSTV_CLIENT",
        edition="Express",
        secrets_directory=root / "secrets" / "container",
        ownership_marker_file=root / "ownership" / "container-marker",
        backup_host_directory=root / "backups",
        backup_sql_directory=Path("/var/opt/mssql/backup"),
        data_sql_directory=Path("/var/opt/mssql/data"),
        container_name="ostv-sql-test",
    )


def _secret(**overrides) -> common.ConnectionSecret:
    values = dict(
        server="sql.example.internal",
        port=11433,
        database="OSTVisualizer",
        username="OSTV_PROVISIONER",
        password=PASSWORD,
        encrypt=True,
        trust_server_certificate=False,
        ownership_marker="marker",
    )
    values.update(overrides)
    return common.ConnectionSecret(**values)


# These cleanup-boundary tests do not touch file permissions or any server, so
# unlike the permission-bit tests in test_common/test_host_state they run on
# every platform.
class SqlAdminCleanupBoundaryTests(unittest.TestCase):
    def test_cleanup_boundary_reports_operation_and_rollback_failures(self):
        operation = RuntimeError("operation")
        cleanup = RuntimeError("cleanup")
        with self.assertRaises(ExceptionGroup) as raised:
            admin._raise_after_cleanup("Provision", operation, (cleanup,))
        self.assertEqual(raised.exception.exceptions, (operation, cleanup))
        self.assertEqual(
            raised.exception.message,
            "Provision and deterministic cleanup both failed.",
        )
        with self.assertRaisesRegex(RuntimeError, "operation") as only_operation:
            admin._raise_after_cleanup("Provision", operation, ())
        self.assertIs(only_operation.exception, operation)

    def test_cleanup_failures_alone_are_reported_without_an_operation_error(self):
        first, second = RuntimeError("first"), RuntimeError("second")
        with self.assertRaises(ExceptionGroup) as raised:
            admin._raise_after_cleanup("Restore", None, (first, second))
        self.assertEqual(raised.exception.message, "Restore cleanup failed.")
        self.assertEqual(raised.exception.exceptions, (first, second))

    def test_successful_operation_and_cleanup_raises_nothing(self):
        self.assertIsNone(admin._raise_after_cleanup("Restore", None, ()))


class SqlAdminHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = _config(self.root)

    def test_generated_passwords_are_long_unique_and_cover_character_groups(self):
        passwords = {admin._password() for _ in range(20)}
        self.assertEqual(len(passwords), 20)
        for password in passwords:
            self.assertTrue(password.startswith("Ov!"))
            self.assertLessEqual(len(password), 128)
            self.assertGreaterEqual(len(password), 90)
            self.assertEqual(len(password), 3 + 96)
            self.assertTrue(any(c.islower() for c in password))
            self.assertTrue(any(c.isupper() for c in password))
            self.assertIn("!", password)
            self.assertNotIn("'", password)
            self.assertNotIn("\x00", password)

    def test_secret_files_live_under_the_configured_secrets_directory(self):
        self.assertEqual(
            admin._secret_path(self.config, "admin"),
            self.root / "secrets" / "container" / "admin.json",
        )

    def test_fingerprint_values_are_type_tagged_so_equal_text_cannot_collide(self):
        fingerprint = admin._fingerprint_value
        self.assertEqual(fingerprint(None), b"N")
        self.assertEqual(fingerprint(b"\x01\x02"), b"B\x01\x02")
        self.assertEqual(fingerprint(1.5), b"F\x3f\xf8\x00\x00\x00\x00\x00\x00")
        self.assertEqual(fingerprint(True), b"T1")
        self.assertEqual(fingerprint(False), b"T0")
        self.assertEqual(fingerprint(7), b"S7")
        self.assertEqual(fingerprint("text"), b"Stext")
        self.assertEqual(fingerprint("é"), b"S\xc3\xa9")
        self.assertEqual(fingerprint(date(2026, 1, 2)), b"D2026-01-02")
        self.assertEqual(
            fingerprint(datetime(2026, 1, 2, 3, 4, 5)), b"D2026-01-02T03:04:05"
        )
        self.assertEqual(fingerprint(time(3, 4, 5)), b"D03:04:05")
        # Integers deliberately share the text tag with strings: both sides of
        # a comparison read the same column type, so only cross-kind values
        # (None, bytes, floats, booleans, temporal values) need distinct tags.
        values = [None, b"1", 1.0, True, "1", date(1, 1, 1)]
        self.assertEqual(len({fingerprint(v) for v in values}), len(values))
        self.assertEqual(fingerprint(1), fingerprint("1"))

    def test_location_always_requires_encryption_and_a_verified_certificate(self):
        location = admin._location(_secret(trust_server_certificate=True), "Other")
        self.assertEqual(location.server, "tcp:sql.example.internal,11433")
        self.assertEqual(location.database, "Other")
        self.assertEqual(location.username, "OSTV_PROVISIONER")
        self.assertEqual(location.authentication_mode.value, "sql_server")
        self.assertTrue(location.encrypt)
        self.assertFalse(location.trust_server_certificate)
        self.assertEqual(location.connection_timeout_seconds, 10)
        self.assertEqual(location.command_timeout_seconds, 600)
        self.assertNotIn(PASSWORD, repr(location))
        self.assertNotIn(PASSWORD, json.dumps(location.to_dict()))

    def test_drain_results_advances_until_no_result_sets_remain(self):
        class Cursor:
            def __init__(self):
                self.remaining = 3
                self.calls = 0

            def nextset(self):
                self.calls += 1
                self.remaining -= 1
                return self.remaining >= 0

        cursor = Cursor()
        admin._drain_results(cursor)
        self.assertEqual(cursor.calls, 4)

    def test_permission_inventory_accepts_only_the_canonical_application_login(self):
        canonical = {
            "server_roles": [],
            "database_roles": ["db_datareader", "db_datawriter"],
            "elevated": (0, 0, 0, 0),
        }
        self.assertIsNone(admin._validate_permission_inventory(canonical))
        reordered = {**canonical, "database_roles": ["db_datawriter", "db_datareader"]}
        self.assertIsNone(admin._validate_permission_inventory(reordered))
        rejected = {
            "sysadmin": ({"server_roles": ["sysadmin"]}, "forbidden server role"),
            "dbcreator": ({"server_roles": ["dbcreator"]}, "forbidden server role"),
            "securityadmin": (
                {"server_roles": ["securityadmin"]},
                "forbidden server role",
            ),
            "serveradmin": ({"server_roles": ["serveradmin"]}, "forbidden server role"),
            "db_owner": (
                {"database_roles": ["db_datareader", "db_datawriter", "db_owner"]},
                "forbidden database role",
            ),
            "db_ddladmin": (
                {"database_roles": ["db_datareader", "db_datawriter", "db_ddladmin"]},
                "forbidden database role",
            ),
            "db_securityadmin": (
                {
                    "database_roles": [
                        "db_datareader",
                        "db_datawriter",
                        "db_securityadmin",
                    ]
                },
                "forbidden database role",
            ),
            "missing writer": ({"database_roles": ["db_datareader"]}, "not canonical"),
            "extra role": (
                {
                    "database_roles": [
                        "db_datareader",
                        "db_datawriter",
                        "db_backupoperator",
                    ]
                },
                "not canonical",
            ),
            "alter database": ({"elevated": (1, 0, 0, 0)}, "forbidden elevated"),
            "control database": ({"elevated": (0, 1, 0, 0)}, "forbidden elevated"),
            "create any database": ({"elevated": (0, 0, 1, 0)}, "forbidden elevated"),
            "alter any login": ({"elevated": [0, 0, 0, 1]}, "forbidden elevated"),
        }
        for label, (changes, message) in rejected.items():
            with self.subTest(label):
                with self.assertRaisesRegex(RuntimeError, message):
                    admin._validate_permission_inventory({**canonical, **changes})

    def test_restore_sources_must_be_bak_files_inside_the_owned_backup_directory(self):
        backups = self.root / "backups"
        (backups / "nightly").mkdir(parents=True)
        good = backups / "nightly" / "Ostv.bak"
        good.write_bytes(b"x")
        upper = backups / "UPPER.BAK"
        upper.write_bytes(b"x")
        resolved, sql_path = admin._resolve_backup_path(self.config, good)
        self.assertEqual(resolved, good.resolve())
        self.assertEqual(
            sql_path, Path("/var/opt/mssql/backup") / "nightly" / "Ostv.bak"
        )
        self.assertEqual(
            admin._resolve_backup_path(self.config, upper)[1],
            Path("/var/opt/mssql/backup") / "UPPER.BAK",
        )
        outside = self.root / "outside.bak"
        outside.write_bytes(b"x")
        wrong_suffix = backups / "notes.txt"
        wrong_suffix.write_bytes(b"x")
        (backups / "folder.bak").mkdir()
        refused = {
            "outside": outside,
            "traversal": backups / ".." / "outside.bak",
            "wrong suffix": wrong_suffix,
            "directory": backups / "folder.bak",
            "missing": backups / "absent.bak",
            "backup root itself": backups,
        }
        for label, path in refused.items():
            with self.subTest(label):
                with self.assertRaisesRegex(
                    RuntimeError, "outside the owned backup directory"
                ):
                    admin._resolve_backup_path(self.config, path)

    def test_error_text_hides_every_readable_stored_password(self):
        secrets_directory = self.root / "secrets" / "container"
        secrets_directory.mkdir(parents=True)
        passwords = {
            "bootstrap": "boot-pw-1",
            "admin": "admin-pw-2",
            "client": "client-pw-3",
        }
        # The admin file is absent and the client file is unreadable: neither
        # password may be consulted, so neither is redacted.
        for role in ("bootstrap", "client"):
            (secrets_directory / f"{role}.json").write_text("{}", encoding="utf-8")

        def fake_read(path):
            if path.name == "client.json":
                raise RuntimeError("unreadable")
            return _secret(password=passwords[path.stem])

        with (
            patch.object(admin, "PRIVATE_STATE_ROOT", self.root),
            patch.object(admin, "read_secret", side_effect=fake_read) as read,
        ):
            message = admin._redacted_error(
                ValueError("login failed for boot-pw-1 and client-pw-3 (admin-pw-2)")
            )
        self.assertEqual(
            message,
            "ValueError: login failed for <redacted> and client-pw-3 (admin-pw-2)",
        )
        self.assertEqual(
            [c.args[0].name for c in read.call_args_list],
            ["bootstrap.json", "client.json"],
        )

    def test_error_text_hides_all_three_passwords_when_every_secret_is_readable(self):
        secrets_directory = self.root / "secrets" / "container"
        secrets_directory.mkdir(parents=True)
        passwords = {
            "bootstrap": "boot-pw-1",
            "admin": "admin-pw-2",
            "client": "client-pw-3",
        }
        for role in passwords:
            (secrets_directory / f"{role}.json").write_text("{}", encoding="utf-8")
        with (
            patch.object(admin, "PRIVATE_STATE_ROOT", self.root),
            patch.object(
                admin,
                "read_secret",
                side_effect=lambda path: _secret(password=passwords[path.stem]),
            ),
        ):
            message = admin._redacted_error(
                ValueError("boot-pw-1 admin-pw-2 client-pw-3")
            )
        self.assertEqual(message, "ValueError: <redacted> <redacted> <redacted>")

    def test_error_text_survives_missing_secret_files(self):
        with patch.object(admin, "PRIVATE_STATE_ROOT", self.root):
            self.assertEqual(
                admin._redacted_error(KeyError("plain")), "KeyError: 'plain'"
            )


class SqlAdminSecretCreationTests(unittest.TestCase):
    """create_secrets/create_recovery_bootstrap with private-file checks bypassed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "state"
        self.root.mkdir()
        self.config = _config(self.root)
        self.admin_private_file = patch.object(admin, "require_private_file")
        for target in (
            windows_safe_replace(),
            patch.object(common, "PRIVATE_STATE_ROOT", self.root),
            patch.object(admin, "PRIVATE_STATE_ROOT", self.root),
            patch.object(common, "require_private_file"),
            self.admin_private_file,
        ):
            started = target.start()
            if target is self.admin_private_file:
                self.admin_private_file = started
            self.addCleanup(target.stop)

    def read(self, role):
        return common.read_secret(self.config.secrets_directory / f"{role}.json")

    def test_first_run_creates_bootstrap_admin_and_client_with_one_marker(self):
        result = admin.create_secrets(self.config)
        self.assertEqual(
            result,
            {
                "status": "ready",
                "created_credentials": ["bootstrap", "admin", "client"],
                "secrets_printed": False,
            },
        )
        marker = self.config.ownership_marker_file.read_text(encoding="utf-8").strip()
        self.assertEqual(str(uuid.UUID(marker)), marker)
        secrets = {role: self.read(role) for role in ("bootstrap", "admin", "client")}
        self.assertEqual(
            {role: (s.username, s.database) for role, s in secrets.items()},
            {
                "bootstrap": ("sa", "master"),
                "admin": ("OSTV_PROVISIONER", "OSTVisualizer"),
                "client": ("OSTV_CLIENT", "OSTVisualizer"),
            },
        )
        for secret in secrets.values():
            self.assertEqual(secret.ownership_marker, marker)
            self.assertEqual(
                (secret.server, secret.port), ("sql.example.internal", 11433)
            )
            self.assertTrue(secret.encrypt)
            self.assertFalse(secret.trust_server_certificate)
            self.assertNotIn(secret.password, json.dumps(result))
        self.assertEqual(len({s.password for s in secrets.values()}), 3)

    def test_the_marker_file_is_checked_only_when_it_already_exists(self):
        admin.create_secrets(self.config)
        self.admin_private_file.assert_not_called()
        admin.create_secrets(self.config)
        self.admin_private_file.assert_called_once_with(
            self.config.ownership_marker_file, label="ownership marker"
        )

    def test_secret_and_marker_directories_are_created_and_restricted_to_the_owner(
        self,
    ):
        # A first run creates everything (its writes repeat the same mkdir/chmod calls),
        # the second run writes nothing, so only create_secrets' own calls remain.
        admin.create_secrets(self.config)
        chmods, makes = [], []
        real_chmod, real_mkdir = os.chmod, Path.mkdir

        def spy_chmod(path, mode, **kwargs):
            chmods.append((Path(path), mode))
            return real_chmod(path, mode, **kwargs)

        def spy_mkdir(self, mode=0o777, parents=False, exist_ok=False):
            makes.append((self, mode, parents, exist_ok))
            return real_mkdir(self, mode=mode, parents=parents, exist_ok=exist_ok)

        with (
            patch.object(os, "chmod", spy_chmod),
            patch.object(Path, "mkdir", spy_mkdir),
        ):
            admin.create_secrets(self.config)
        secrets_directory = self.config.secrets_directory
        marker_directory = self.config.ownership_marker_file.parent
        self.assertEqual(
            makes,
            [
                (secrets_directory, 0o700, True, True),
                (marker_directory, 0o700, True, True),
            ],
        )
        self.assertEqual(
            chmods, [(secrets_directory, 0o700), (marker_directory, 0o700)]
        )

    def test_rerun_keeps_existing_credentials_and_creates_nothing(self):
        admin.create_secrets(self.config)
        before = {role: self.read(role) for role in ("bootstrap", "admin", "client")}
        again = admin.create_secrets(self.config)
        self.assertEqual(again["created_credentials"], [])
        self.assertEqual({role: self.read(role) for role in before}, before)

    def test_bootstrap_is_not_recreated_once_the_admin_exists(self):
        admin.create_secrets(self.config)
        (self.config.secrets_directory / "bootstrap.json").unlink()
        again = admin.create_secrets(self.config)
        self.assertEqual(again["created_credentials"], [])
        self.assertFalse((self.config.secrets_directory / "bootstrap.json").exists())
        (self.config.secrets_directory / "client.json").unlink()
        self.assertEqual(
            admin.create_secrets(self.config)["created_credentials"], ["client"]
        )

    def test_foreign_marker_in_an_existing_secret_is_refused(self):
        admin.create_secrets(self.config)
        foreign = _secret(
            username="OSTV_CLIENT",
            ownership_marker=str(uuid.uuid4()),
            password="foreign-password",
        )
        common.write_secret(self.config.secrets_directory / "client.json", foreign)
        with self.assertRaisesRegex(
            RuntimeError, "different ownership marker"
        ) as raised:
            admin.create_secrets(self.config)
        self.assertNotIn("foreign-password", str(raised.exception))
        self.assertEqual(self.read("client"), foreign)

    def test_invalid_stored_marker_aborts_before_writing_credentials(self):
        self.config.ownership_marker_file.parent.mkdir(parents=True)
        self.config.ownership_marker_file.write_text("not-a-uuid\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            admin.create_secrets(self.config)
        self.assertEqual(list(self.config.secrets_directory.glob("*.json")), [])

    def test_recovery_bootstrap_reuses_the_admin_marker(self):
        result = admin.create_recovery_bootstrap(self.config)
        self.assertEqual(
            result, {"status": "recovery-bootstrap-ready", "secrets_printed": False}
        )
        admin_secret = self.read("admin")
        bootstrap = self.read("bootstrap")
        self.assertEqual(bootstrap.ownership_marker, admin_secret.ownership_marker)
        self.assertEqual((bootstrap.username, bootstrap.database), ("sa", "master"))
        self.assertEqual(
            (bootstrap.server, bootstrap.port, bootstrap.encrypt),
            ("sql.example.internal", 11433, True),
        )
        self.assertIs(bootstrap.trust_server_certificate, False)
        self.assertTrue(bootstrap.password.startswith("Ov!"))
        (self.config.secrets_directory / "bootstrap.json").unlink()
        admin.create_recovery_bootstrap(self.config)
        recreated = self.read("bootstrap")
        self.assertEqual(recreated.ownership_marker, admin_secret.ownership_marker)
        self.assertEqual(
            (recreated.server, recreated.port, recreated.database, recreated.username),
            ("sql.example.internal", 11433, "master", "sa"),
        )
        self.assertIs(recreated.encrypt, True)
        self.assertIs(recreated.trust_server_certificate, False)
        self.assertNotEqual(recreated.password, bootstrap.password)

    def test_recovery_bootstrap_refuses_an_admin_credential_for_another_deployment(
        self,
    ):
        admin.create_secrets(self.config)
        admin_secret = self.read("admin")
        bootstrap_path = self.config.secrets_directory / "bootstrap.json"
        bootstrap_path.unlink()
        common.write_secret(
            self.config.secrets_directory / "admin.json",
            _secret(
                server="other.example.internal",
                ownership_marker=admin_secret.ownership_marker,
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "admin credential does not match"):
            admin.create_recovery_bootstrap(self.config)
        self.assertFalse(bootstrap_path.exists())

    def test_recovery_bootstrap_refuses_a_bootstrap_with_the_wrong_identity(self):
        admin.create_secrets(self.config)
        admin_secret = self.read("admin")
        for label, bad in {
            "user": _secret(
                username="admin",
                database="master",
                ownership_marker=admin_secret.ownership_marker,
            ),
            "database": _secret(
                username="sa",
                database="Other",
                ownership_marker=admin_secret.ownership_marker,
            ),
            "marker": _secret(
                username="sa", database="master", ownership_marker="foreign"
            ),
        }.items():
            with self.subTest(label):
                common.write_secret(
                    self.config.secrets_directory / "bootstrap.json", bad
                )
                with self.assertRaisesRegex(
                    RuntimeError, "recovery bootstrap credential is invalid"
                ):
                    admin.create_recovery_bootstrap(self.config)

    def test_bootstrap_admin_refuses_unsafe_credentials_before_connecting(self):
        admin.create_secrets(self.config)
        admin_secret = self.read("admin")
        path = self.config.secrets_directory / "bootstrap.json"
        cases = {
            "wrong user": (
                _secret(
                    username="admin",
                    database="master",
                    ownership_marker=admin_secret.ownership_marker,
                ),
                "bootstrap credential is invalid",
            ),
            "wrong database": (
                _secret(
                    username="sa",
                    database="Other",
                    ownership_marker=admin_secret.ownership_marker,
                ),
                "bootstrap credential is invalid",
            ),
            "foreign marker": (
                _secret(username="sa", database="master", ownership_marker="foreign"),
                "ownership marker does not match",
            ),
        }
        with patch.object(admin, "connect") as connect:
            for label, (bad, message) in cases.items():
                with self.subTest(label):
                    common.write_secret(path, bad)
                    with self.assertRaisesRegex(RuntimeError, message):
                        admin.bootstrap_admin(self.config)
            connect.assert_not_called()
            self.assertTrue(path.exists())
            common.write_secret(
                self.config.secrets_directory / "admin.json",
                _secret(
                    server="other.example.internal",
                    ownership_marker=admin_secret.ownership_marker,
                ),
            )
            common.write_secret(
                path,
                _secret(
                    username="sa",
                    database="master",
                    ownership_marker=admin_secret.ownership_marker,
                ),
            )
            with self.assertRaisesRegex(
                RuntimeError, "admin credential does not match"
            ):
                admin.bootstrap_admin(self.config)
            connect.assert_not_called()

    def bootstrap(self, *, server_marker="", kind=None, sysadmin=1, verify_marker=""):
        """Run bootstrap_admin against scripted connections; return what it did."""
        admin.create_secrets(self.config)
        admin_secret = self.read("admin")
        bootstrap_path = self.config.secrets_directory / "bootstrap.json"
        connections = []

        def answer(label):
            def reply(sql, parameters):
                if "IS_SRVROLEMEMBER" in sql:
                    return [(sysadmin,)]
                if "class=0 AND name=?" in sql:
                    if parameters == (common.DEPLOYMENT_PROPERTY,):
                        if label == "admin":
                            return [(verify_marker or admin_secret.ownership_marker,)]
                        return [(server_marker,)] if server_marker else []
                    if parameters == (common.DEPLOYMENT_KIND_PROPERTY,):
                        return [(kind or "container:ostv-sql-test",)]
                return []

            return reply

        @contextlib.contextmanager
        def fake_connect(
            secret, *, database=None, app="OSTV SQL Admin", autocommit=True
        ):
            label = "bootstrap" if secret.username == "sa" else "admin"
            connection = _ScriptedConnection(answer(label))
            connections.append((secret, database, app, connection))
            yield connection

        with patch.object(admin, "connect", side_effect=fake_connect):
            try:
                result = admin.bootstrap_admin(self.config)
                error = None
            except RuntimeError as exc:
                result, error = None, exc
        return result, error, connections, admin_secret, bootstrap_path

    def statements(self, connection):
        return [sql for sql, _parameters in connection.executed]

    def test_bootstrap_creates_the_administrator_verifies_it_and_only_then_disables_sa(
        self,
    ):
        result, error, connections, admin_secret, bootstrap_path = self.bootstrap()
        self.assertIsNone(error)
        self.assertEqual(
            result,
            {
                "status": "administrator-configured",
                "sa_disabled": True,
                "administrator_verified": True,
            },
        )
        self.assertEqual(
            [(c[0].username, c[1], c[2]) for c in connections],
            [
                ("sa", "master", "OSTV SQL Bootstrap"),
                ("OSTV_PROVISIONER", "master", "OSTV SQL Admin Verification"),
            ],
        )
        self.assertEqual(connections[1][0].password, admin_secret.password)
        first, second = connections[0][3], connections[1][3]
        login_sql, login_parameters = next(
            (sql, parameters)
            for sql, parameters in first.executed
            if "CREATE LOGIN" in sql
        )
        self.assertEqual(
            login_parameters, (admin_secret.password,) + ("OSTV_PROVISIONER",) * 5
        )
        self.assertNotIn(admin_secret.password, login_sql)
        self.assertIn("ALTER SERVER ROLE [sysadmin] ADD MEMBER", login_sql)
        self.assertIn("CHECK_POLICY=ON", login_sql)
        properties = [
            parameters
            for sql, parameters in first.executed
            if "sp_updateextendedproperty" in sql
        ]
        self.assertEqual(
            [(p[0], p[2]) for p in properties],
            [
                (common.DEPLOYMENT_PROPERTY, admin_secret.ownership_marker),
                (common.DEPLOYMENT_KIND_PROPERTY, "container:ostv-sql-test"),
                (common.BACKUP_PROPERTY, str(self.config.backup_sql_directory)),
            ],
        )
        self.assertNotIn("ALTER LOGIN [sa] DISABLE", " ".join(self.statements(first)))
        self.assertEqual(
            [s for s in self.statements(second) if "DISABLE" in s],
            ["ALTER LOGIN [sa] DISABLE"],
        )
        self.assertLess(
            next(
                i
                for i, s in enumerate(self.statements(second))
                if "IS_SRVROLEMEMBER" in s
            ),
            next(i for i, s in enumerate(self.statements(second)) if "DISABLE" in s),
        )
        self.assertFalse(bootstrap_path.exists())
        self.assertTrue(
            all(c[3].closed_cursors == c[3].opened_cursors for c in connections)
        )

    def test_a_foreign_server_marker_stops_the_bootstrap_before_any_login_change(self):
        result, error, connections, _admin_secret, bootstrap_path = self.bootstrap(
            server_marker=str(uuid.uuid4())
        )
        self.assertRegex(str(error), "server ownership marker does not match")
        self.assertEqual(len(connections), 1)
        self.assertFalse(
            any("LOGIN" in sql for sql in self.statements(connections[0][3]))
        )
        self.assertTrue(bootstrap_path.exists())

    def test_sa_stays_enabled_when_the_verified_server_carries_another_marker(self):
        _result, error, connections, _secret, bootstrap_path = self.bootstrap(
            verify_marker=str(uuid.uuid4())
        )
        self.assertRegex(str(error), "server ownership marker does not match")
        self.assertEqual(len(connections), 2)
        self.assertFalse(
            any("DISABLE" in s for s in self.statements(connections[1][3]))
        )
        self.assertTrue(bootstrap_path.exists())

    def test_sa_stays_enabled_when_the_administrator_cannot_be_verified(self):
        cases = {
            "no sysadmin membership": ({"sysadmin": 0}, "did not receive sysadmin"),
            "NULL sysadmin answer": ({"sysadmin": None}, "did not receive sysadmin"),
            "another container": (
                {"kind": "container:someone-else"},
                "container ownership identity does not match",
            ),
        }
        for label, (changes, message) in cases.items():
            with self.subTest(label):
                _result, error, connections, _secret, bootstrap_path = self.bootstrap(
                    **changes
                )
                self.assertRegex(str(error), message)
                self.assertEqual(len(connections), 2)
                self.assertFalse(
                    any("DISABLE" in s for s in self.statements(connections[1][3]))
                )
                self.assertTrue(bootstrap_path.exists())


class _ScriptedCursor:
    def __init__(self, connection):
        self._connection = connection
        self._rows = []
        connection.opened_cursors += 1

    def execute(self, sql, *parameters):
        self._connection.executed.append((sql, parameters))
        self._rows = list(self._connection.reply(sql, parameters))

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def close(self):
        self._connection.closed_cursors += 1


class _ScriptedConnection:
    def __init__(self, reply):
        self.reply = reply
        self.executed = []
        self.opened_cursors = 0
        self.closed_cursors = 0

    def cursor(self):
        return _ScriptedCursor(self)


class SqlAdminMainTests(unittest.TestCase):
    def run_main(self, argv, **patches):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            for name, value in patches.items():
                stack.enter_context(patch.object(admin, name, **value))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            code = admin.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_successful_commands_print_sorted_json_and_return_zero(self):
        config = object()
        code, out, err = self.run_main(
            ["fingerprint"],
            load_config={"return_value": config},
            database_fingerprint={"return_value": {"b": 1, "a": [2]}},
        )
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, '{\n  "a": [\n    2\n  ],\n  "b": 1\n}\n')

    COMMANDS = {
        "create-secrets": ("create_secrets", (), ()),
        "create-recovery-bootstrap": ("create_recovery_bootstrap", (), ()),
        "bootstrap-admin": ("bootstrap_admin", (), ()),
        "provision": ("provision_database", (), ()),
        "validate-tls-connectivity": ("validate_tls_connectivity", (), ()),
        "restore-verify": ("restore_verify", ("a.bak",), (Path("a.bak"),)),
        "restore-migration": (
            "restore_migration",
            ("a.bak", "marker.txt", "fingerprint.json"),
            (Path("a.bak"), Path("marker.txt"), Path("fingerprint.json")),
        ),
        "fingerprint": ("database_fingerprint", (), ()),
        "repair-permissions": ("repair_permissions", (), ()),
        "rotate-client-password": ("rotate_client_password", (), ()),
        "uninstall-database": ("uninstall_database", (), ()),
        "cleanup-restores": ("cleanup_restore_databases", (), ()),
        "lifecycle-test": ("lifecycle_test", (), ()),
    }

    def test_every_command_runs_exactly_its_own_operation_with_the_configuration(self):
        config = object()
        names = [entry[0] for entry in self.COMMANDS.values()]
        for command, (name, extra, expected) in self.COMMANDS.items():
            with self.subTest(command=command):
                patches = {
                    other: {"side_effect": AssertionError(other)}
                    for other in names
                    if other != name
                }
                patches[name] = {"return_value": {"status": command}}
                patches["load_config"] = {"return_value": config}
                code, out, err = self.run_main([command, *extra], **patches)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(json.loads(out), {"status": command})

    def test_each_command_receives_the_loaded_configuration_and_its_arguments(self):
        config = object()
        for command, (name, extra, expected) in self.COMMANDS.items():
            with self.subTest(command=command):
                with patch.object(admin, name, return_value={}) as target:
                    self.run_main(
                        [command, *extra], load_config={"return_value": config}
                    )
                target.assert_called_once_with(config, *expected)

    def test_backup_reports_the_path_and_restore_commands_receive_paths(self):
        config = object()
        code, out, _ = self.run_main(
            ["backup"],
            load_config={"return_value": config},
            backup_database={"return_value": Path("backups/x.bak")},
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(out),
            {"status": "backup-complete", "path": str(Path("backups/x.bak"))},
        )
        with patch.object(admin, "restore_verify", return_value={"ok": 1}) as restore:
            self.run_main(
                ["restore-verify", "a.bak"], load_config={"return_value": config}
            )
        with patch.object(
            admin, "restore_migration", return_value={"ok": 1}
        ) as migrate:
            self.run_main(
                ["restore-migration", "a.bak", "marker.txt", "fingerprint.json"],
                load_config={"return_value": config},
            )
        self.assertEqual(
            migrate.call_args.args[1:],
            (Path("a.bak"), Path("marker.txt"), Path("fingerprint.json")),
        )

    def test_validate_flag_selects_the_backup_restore_check(self):
        config = object()
        with patch.object(
            admin, "validate_environment", return_value={"ok": 1}
        ) as validate:
            self.run_main(["validate"], load_config={"return_value": config})
            self.run_main(
                ["validate", "--with-backup-restore"],
                load_config={"return_value": config},
            )
        self.assertEqual(
            [c.kwargs for c in validate.call_args_list],
            [{"run_backup": False}, {"run_backup": True}],
        )

    def test_failures_are_redacted_on_stderr_and_nothing_is_printed_to_stdout(self):
        def explode(config):
            raise RuntimeError(f"connection failed with {PASSWORD}")

        code, out, err = self.run_main(
            ["provision"],
            load_config={"return_value": object()},
            provision_database={"side_effect": explode},
            _redacted_error={
                "side_effect": lambda e: common.redact_text(
                    f"{type(e).__name__}: {e}", (PASSWORD,)
                )
            },
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "RuntimeError: connection failed with <redacted>\n")

    def test_configuration_failures_are_reported_through_the_same_redaction(self):
        code, out, err = self.run_main(
            ["lifecycle-test"],
            load_config={"side_effect": RuntimeError("private state root is missing")},
        )
        self.assertEqual(
            (code, out, err),
            (1, "", "RuntimeError: private state root is missing\n"),
        )

    def test_unknown_or_missing_commands_are_rejected_by_the_parser(self):
        for argv in ([], ["drop-everything"], ["restore-verify"]):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        admin.main(argv)
                self.assertEqual(raised.exception.code, 2)
