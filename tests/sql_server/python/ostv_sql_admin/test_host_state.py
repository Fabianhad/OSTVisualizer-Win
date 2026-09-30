from __future__ import annotations
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from sql_server.python.ostv_sql_admin import admin, common, host_state
from tests.sql_server.python.ostv_sql_admin.environment_support import (
    _environment_text as _environment_support__environment_text,
)


@unittest.skipUnless(os.name == "posix", "Ubuntu deployment tooling is POSIX-only")
class SqlAdminHostStateTests(unittest.TestCase):
    def test_public_dns_must_resolve_only_to_the_configured_bind_address(self):
        values = dict(
            line.split("=", 1)
            for line in _environment_support__environment_text(
                Path("/state")
            ).splitlines()
        )
        with (
            patch.object(host_state, "load_environment", return_value=values),
            patch.object(
                host_state.socket,
                "getaddrinfo",
                return_value=[(2, 1, 6, "", ("8.8.8.8", 0))],
            ),
        ):
            result = host_state.verify_public_dns()
        self.assertEqual(result["status"], "public-dns-valid")
        with (
            patch.object(host_state, "load_environment", return_value=values),
            patch.object(
                host_state.socket,
                "getaddrinfo",
                return_value=[(2, 1, 6, "", ("9.9.9.9", 0))],
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "does not resolve exclusively"):
                host_state.verify_public_dns()

    def test_credential_endpoint_sync_is_idempotent_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory) / "state"
            credentials = state_root / "secrets/container"
            credentials.mkdir(parents=True, mode=0o700)
            original = {
                "admin": common.ConnectionSecret(
                    server="old.example.internal",
                    port=11433,
                    database="OSTVisualizer",
                    username="OSTV_PROVISIONER",
                    password="admin-test-password",
                    encrypt=True,
                    trust_server_certificate=False,
                    ownership_marker="marker",
                ),
                "client": common.ConnectionSecret(
                    server="old.example.internal",
                    port=11433,
                    database="OSTVisualizer",
                    username="OSTV_CLIENT",
                    password="client-test-password",
                    encrypt=True,
                    trust_server_certificate=False,
                    ownership_marker="marker",
                ),
            }
            values = dict(
                line.split("=", 1)
                for line in _environment_support__environment_text(state_root)
                .replace("OSTV_SQL_HOST_PORT=11433", "OSTV_SQL_HOST_PORT=1433")
                .splitlines()
            )
            with (
                patch.object(common, "PRIVATE_STATE_ROOT", state_root),
                patch.object(host_state, "PRIVATE_STATE_ROOT", state_root),
            ):
                for role, secret in original.items():
                    common.write_secret(credentials / f"{role}.json", secret)
                writes = 0

                def fail_second(path: Path, secret: common.ConnectionSecret) -> None:
                    nonlocal writes
                    writes += 1
                    if writes == 2:
                        raise OSError("second endpoint write failed")
                    common.write_secret(path, secret)

                with (
                    patch.object(host_state, "load_environment", return_value=values),
                    patch.object(host_state, "write_secret", side_effect=fail_second),
                ):
                    with self.assertRaisesRegex(
                        OSError, "second endpoint write failed"
                    ):
                        host_state.sync_credential_endpoint()
                for role, secret in original.items():
                    self.assertEqual(
                        common.read_secret(credentials / f"{role}.json"), secret
                    )
                with patch.object(host_state, "load_environment", return_value=values):
                    first = host_state.sync_credential_endpoint()
                    second = host_state.sync_credential_endpoint()
                self.assertEqual(first["changed"], 2)
                self.assertEqual(second["changed"], 0)
                for role in original:
                    self.assertEqual(
                        common.read_secret(credentials / f"{role}.json").port, 1433
                    )

    def test_peer_creation_rolls_back_partial_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory) / "state"
            for relative in (
                "wireguard/server",
                "wireguard/peers",
                "temporary",
            ):
                (state_root / relative).mkdir(parents=True, mode=0o700)
            private_key = state_root / "temporary/private.key"
            public_key = state_root / "temporary/public.key"
            server_public = state_root / "wireguard/server/public.key"
            key = "A" * 43 + "="
            for path in (private_key, public_key, server_public):
                path.write_text(key + "\n", encoding="ascii")
                path.chmod(0o600)
            values = dict(
                line.split("=", 1)
                for line in _environment_support__environment_text(
                    state_root
                ).splitlines()
            )
            original_write = common.atomic_write_private
            calls = 0

            def fail_second(path: Path, content: str) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("second write failed")
                original_write(path, content)

            with (
                patch.object(common, "PRIVATE_STATE_ROOT", state_root),
                patch.object(host_state, "PRIVATE_STATE_ROOT", state_root),
                patch.object(host_state, "load_environment", return_value=values),
                patch.object(
                    host_state, "atomic_write_private", side_effect=fail_second
                ),
            ):
                with self.assertRaisesRegex(OSError, "second write failed"):
                    host_state.create_wireguard_peer(
                        "client-one", "10.250.240.2", private_key, public_key
                    )
            self.assertFalse((state_root / "wireguard/peers/client-one.json").exists())
            self.assertFalse(
                (state_root / "temporary/wireguard-client-one.conf").exists()
            )

    def test_sa_reset_does_not_print_or_put_password_in_arguments(self):
        password = "unique-bootstrap-secret"
        secret = common.ConnectionSecret(
            server="sql.example.internal",
            port=11433,
            database="master",
            username="sa",
            password=password,
            encrypt=True,
            trust_server_certificate=False,
            ownership_marker="marker",
        )
        admin_secret = common.ConnectionSecret(
            server=secret.server,
            port=secret.port,
            database="OSTVisualizer",
            username="OSTV_PROVISIONER",
            password=secret.password,
            encrypt=secret.encrypt,
            trust_server_certificate=secret.trust_server_certificate,
            ownership_marker=secret.ownership_marker,
        )
        output = io.StringIO()
        with (
            patch.object(
                host_state,
                "load_environment",
                return_value={
                    "OSTV_CONTAINER_NAME": "owned",
                    "OSTV_DEPLOYMENT_ID": "deployment",
                },
            ),
            patch.object(host_state, "read_secret", side_effect=(secret, admin_secret)),
            patch.object(
                host_state,
                "_run_command",
                side_effect=(
                    '{"com.ostvisualizer.deployment-id":"deployment",'
                    '"com.ostvisualizer.component":"sqlserver"}',
                    "",
                ),
            ) as run,
            redirect_stdout(output),
        ):
            host_state.reset_sa_password()
        command = run.call_args_list[1].args[0]
        self.assertNotIn(password, command)
        self.assertEqual(
            run.call_args_list[1].kwargs["environment"]["MSSQL_SA_PASSWORD"],
            password,
        )
        self.assertEqual(output.getvalue(), "")
