from __future__ import annotations
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sql_server.python.ostv_sql_admin import admin, common, host_state
from tests.sql_server.python.ostv_sql_admin.environment_support import (
    _environment_text as _environment_support__environment_text,
)


@unittest.skipUnless(os.name == "posix", "Ubuntu deployment tooling is POSIX-only")
class SqlAdminCommonTests(unittest.TestCase):
    def test_missing_private_configuration_fails_clearly(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing-state"
            with patch.object(common, "PRIVATE_STATE_ROOT", missing):
                with self.assertRaisesRegex(
                    RuntimeError, "private state root is missing"
                ):
                    common.load_config()

    def test_ownership_mismatch_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "ownership marker does not match"):
            common.require_marker("actual", "expected", "database")

    def test_legacy_config_override_cannot_select_native_deployment(self):
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory) / "state"
            state_root.mkdir(mode=0o700)
            env_path = state_root / ".env"
            env_path.write_text(
                _environment_support__environment_text(state_root), encoding="utf-8"
            )
            env_path.chmod(0o600)
            with (
                patch.object(common, "PRIVATE_STATE_ROOT", state_root),
                patch.dict(
                    os.environ,
                    {"OSTV_SQL_CONFIG": str(state_root / "config/native.env")},
                ),
            ):
                first = common.load_config()
                second = common.load_config()
            self.assertEqual(first, second)
            self.assertEqual(first.container_name, "ostv-sql-test")

    def test_public_sql_sources_must_be_unique_global_ipv4_hosts(self):
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory) / "state"
            state_root.mkdir(mode=0o700)
            text = _environment_support__environment_text(state_root).replace(
                "OSTV_SQL_ALLOWED_SOURCE_CIDR=9.9.9.9/32",
                "OSTV_SQL_ALLOWED_SOURCE_CIDR=9.9.9.0/24",
            )
            env_path = state_root / ".env"
            env_path.write_text(text, encoding="utf-8")
            env_path.chmod(0o600)
            with patch.object(common, "PRIVATE_STATE_ROOT", state_root):
                with self.assertRaisesRegex(
                    RuntimeError, "one or more unique global IPv4 /32"
                ):
                    common.load_environment()
            text = _environment_support__environment_text(state_root).replace(
                "OSTV_SQL_ALLOWED_SOURCE_CIDR=9.9.9.9/32",
                "OSTV_SQL_ALLOWED_SOURCE_CIDR=9.9.9.9/32,8.8.8.8/32",
            )
            env_path.write_text(text, encoding="utf-8")
            with patch.object(common, "PRIVATE_STATE_ROOT", state_root):
                values = common.load_environment()
            self.assertEqual(
                values["OSTV_SQL_ALLOWED_SOURCE_CIDR"],
                "9.9.9.9/32,8.8.8.8/32",
            )

    def test_standard_public_sql_port_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory) / "state"
            state_root.mkdir(mode=0o700)
            text = (
                _environment_support__environment_text(state_root)
                .replace(
                    "OSTV_SQL_HOST_PORT=11433",
                    "OSTV_SQL_HOST_PORT=1433",
                )
                .replace(
                    "OSTV_SQL_PUBLIC_PORT=11433",
                    "OSTV_SQL_PUBLIC_PORT=1433",
                )
            )
            env_path = state_root / ".env"
            env_path.write_text(text, encoding="utf-8")
            env_path.chmod(0o600)
            with patch.object(common, "PRIVATE_STATE_ROOT", state_root):
                values = common.load_environment()
            self.assertEqual(values["OSTV_SQL_HOST_PORT"], "1433")
            self.assertEqual(values["OSTV_SQL_PUBLIC_PORT"], "1433")

    def test_atomic_private_write_removes_temporary_after_success_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory) / "state"
            state_root.mkdir(mode=0o700)
            target = state_root / "value.json"
            with patch.object(common, "PRIVATE_STATE_ROOT", state_root):
                common.atomic_write_private(target, "{}\n")
                self.assertEqual(target.read_text(encoding="utf-8"), "{}\n")
                with patch.object(
                    common.os, "replace", side_effect=OSError("replace failed")
                ):
                    with self.assertRaisesRegex(OSError, "replace failed"):
                        common.atomic_write_private(state_root / "failure.json", "{}\n")
            self.assertEqual(list(state_root.glob(".*.tmp")), [])

    def test_secret_values_are_redacted(self):
        secret = common.ConnectionSecret(
            server="sql.example.internal",
            port=11433,
            database="OSTVisualizer",
            username="OSTV_CLIENT",
            password="unique-test-password",
            encrypt=True,
            trust_server_certificate=False,
            ownership_marker="marker",
        )
        self.assertNotIn(secret.password, repr(secret))
        self.assertEqual(
            common.redact_text(f"failure {secret.password}", (secret.password,)),
            "failure <redacted>",
        )
