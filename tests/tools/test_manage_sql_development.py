import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import tools.manage_sql_development as sql_development
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


class SqlDevelopmentSetupTests(unittest.TestCase):
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

    def test_secrets_json_is_atomic_exact_and_round_trips(self):
        value = self._secrets("runtime-only-test-value")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sql-development.json"
            write_secrets_atomic(path, value)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload, value.to_dict())
            self.assertEqual(read_secrets(path), value)
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

    def test_existing_login_with_invalid_credential_requires_explicit_rotation(self):
        with self.assertRaisesRegex(RuntimeError, "RotateClientPassword"):
            select_client_password(
                "stale-runtime-secret",
                login_exists=True,
                existing_password_works=False,
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

    def test_teardown_accepts_only_owned_idle_resources(self):
        validate_teardown_inventory(TeardownInventory((CLIENT_DATABASE,), (), (), 0, 0))

    def test_teardown_refuses_unowned_databases_logins_sessions_and_restores(self):
        inventories = (
            TeardownInventory((), ("unmarked",), (), 0, 0),
            TeardownInventory((), (), ("unrelated-login",), 0, 0),
            TeardownInventory((), (), (), 1, 0),
            TeardownInventory((), (), (), 0, 1),
        )
        for inventory in inventories:
            with self.subTest(inventory=inventory):
                with self.assertRaises(RuntimeError):
                    validate_teardown_inventory(inventory)

    @staticmethod
    def _secrets(password: str) -> SqlDevelopmentSecrets:
        return SqlDevelopmentSecrets(
            server=SERVER_HOST,
            port=SERVER_PORT,
            database=CLIENT_DATABASE,
            authentication_mode="sql",
            username=CLIENT_LOGIN,
            password=password,
            credential_target=CLIENT_CREDENTIAL_TARGET,
            encrypt=True,
            trust_server_certificate=False,
            ownership_marker="b264d6f1-c518-4898-9a34-e124159195cb",
        )


if __name__ == "__main__":
    unittest.main()
