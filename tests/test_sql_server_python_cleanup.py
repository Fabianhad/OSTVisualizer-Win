from __future__ import annotations
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SQL_SERVER_ROOT = REPOSITORY_ROOT / "sql_server"
sys.path.insert(0, str(SQL_SERVER_ROOT / "python"))
from ostv_sql_admin import admin, common, host_state  # noqa: E402


def _environment_text(state_root: Path) -> str:
    values = {
        "OSTV_STATE_ROOT": str(state_root),
        "OSTV_SQL_IMAGE": (
            "mcr.microsoft.com/mssql/server:2025-CU7-ubuntu-24.04@sha256:" + "a" * 64
        ),
        "OSTV_CONTAINER_NAME": "ostv-sql-test",
        "OSTV_DEPLOYMENT_ID": "00000000-0000-4000-8000-000000000001",
        "OSTV_SQL_EDITION": "Express",
        "OSTV_SA_PASSWORD": "<GENERATED_BY_SETUP>",
        "OSTV_SQL_DATABASE": "OSTVisualizer",
        "OSTV_SQL_ADMIN_LOGIN": "OSTV_PROVISIONER",
        "OSTV_SQL_CLIENT_LOGIN": "OSTV_CLIENT",
        "OSTV_SQL_HOST_PORT": "11433",
        "OSTV_SQL_VPN_PORT": "11433",
        "OSTV_SQL_PUBLIC_BIND_ADDRESS": "8.8.8.8",
        "OSTV_SQL_PUBLIC_PORT": "11433",
        "OSTV_SQL_ALLOWED_SOURCE_CIDR": "9.9.9.9/32",
        "OSTV_SQL_CERTIFICATE_NAME": "sql.example.internal",
        "OSTV_WG_INTERFACE": "wg-ostv",
        "OSTV_WG_SERVER_ADDRESS": "10.250.240.1",
        "OSTV_WG_PREFIX_LENGTH": "24",
        "OSTV_WG_LISTEN_PORT": "51820",
        "OSTV_PUBLIC_INTERFACE": "eth0",
        "OSTV_PUBLIC_ENDPOINT": "vpn.example.invalid",
        "OSTV_DOCKER_NETWORK": "ostv_sql_private",
        "OSTV_DOCKER_SUBNET": "172.29.240.0/24",
        "OSTV_SQL_CONTAINER_ADDRESS": "172.29.240.10",
    }
    return "".join(f"{key}={value}\n" for key, value in values.items())


@unittest.skipUnless(os.name == "posix", "Ubuntu deployment tooling is POSIX-only")
class SqlServerPythonCleanupTests(unittest.TestCase):
    def test_old_repository_directory_name_is_absent(self):
        obsolete = "/client/" + "SQL" + "Server"
        matches = []
        for path in SQL_SERVER_ROOT.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeError:
                    continue
                if obsolete in text:
                    matches.append(str(path))
        self.assertEqual(matches, [])

    def test_private_state_has_no_environment_or_repository_fallback(self):
        common_source = (SQL_SERVER_ROOT / "python/ostv_sql_admin/common.py").read_text(
            encoding="utf-8"
        )
        shell_source = (SQL_SERVER_ROOT / "lib/common.sh").read_text(encoding="utf-8")
        self.assertIn('PRIVATE_STATE_ROOT = Path("/home/SQLServer")', common_source)
        self.assertNotIn("OSTV_SQL_CONFIG", common_source + shell_source)
        self.assertNotIn("OSTV_SQL_STATE_ROOT:-", shell_source)
        self.assertNotIn("native-rollback", common_source)

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
            env_path.write_text(_environment_text(state_root), encoding="utf-8")
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

    def test_public_sql_source_must_be_one_global_ipv4_host(self):
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory) / "state"
            state_root.mkdir(mode=0o700)
            text = _environment_text(state_root).replace(
                "OSTV_SQL_ALLOWED_SOURCE_CIDR=9.9.9.9/32",
                "OSTV_SQL_ALLOWED_SOURCE_CIDR=9.9.9.0/24",
            )
            env_path = state_root / ".env"
            env_path.write_text(text, encoding="utf-8")
            env_path.chmod(0o600)
            with patch.object(common, "PRIVATE_STATE_ROOT", state_root):
                with self.assertRaisesRegex(RuntimeError, "one global IPv4 /32"):
                    common.load_environment()

    def test_standard_public_sql_port_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory) / "state"
            state_root.mkdir(mode=0o700)
            text = (
                _environment_text(state_root)
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

    def test_public_sql_firewall_is_destination_scoped(self):
        firewall = (SQL_SERVER_ROOT / "configure_firewall.sh").read_text(
            encoding="utf-8"
        )
        compose = (SQL_SERVER_ROOT / "templates/docker-compose.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("--ctorigdst", firewall)
        self.assertIn("--ctorigdstport", firewall)
        self.assertIn("OSTV_SQL_ALLOWED_SOURCE_CIDR", firewall)
        self.assertIn("readonly managed_chain=OSTV-SQL", firewall)
        self.assertIn(
            "${OSTV_SQL_PUBLIC_BIND_ADDRESS}:${OSTV_SQL_PUBLIC_PORT}:1433", compose
        )
        self.assertNotIn(
            'ufw deny in on "$public_interface" proto tcp to any port 1433', firewall
        )

    def test_public_dns_must_resolve_only_to_the_configured_bind_address(self):
        values = dict(
            line.split("=", 1)
            for line in _environment_text(Path("/state")).splitlines()
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
                for line in _environment_text(state_root)
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

    def test_tls_deployment_uses_certbot_and_has_a_scoped_renewal_hook(self):
        deployment = (SQL_SERVER_ROOT / "deploy_tls.sh").read_text(encoding="utf-8")
        hook = (SQL_SERVER_ROOT / "templates/certbot-deploy-hook.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("/etc/letsencrypt/live/$certificate_name", deployment)
        self.assertIn("openssl verify", deployment)
        self.assertIn("require_container_identity", deployment)
        self.assertIn("RENEWED_LINEAGE", hook)
        self.assertNotIn("genpkey", deployment)
        self.assertNotIn("TrustServerCertificate=yes", deployment + hook)

    def test_shell_and_python_use_one_canonical_configuration(self):
        shell_files = list(SQL_SERVER_ROOT.glob("*.sh")) + [
            SQL_SERVER_ROOT / "lib/common.sh"
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in shell_files)
        self.assertNotIn("config/container.env", combined)
        self.assertNotIn('sed -n "s/^${key}=', combined)
        self.assertIn("ostv_sql_admin.common get", combined)
        self.assertFalse(
            any("<<'PY'" in path.read_text(encoding="utf-8") for path in shell_files)
        )

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

    def test_cleanup_boundary_reports_operation_and_rollback_failures(self):
        operation = RuntimeError("operation")
        cleanup = RuntimeError("cleanup")
        with self.assertRaises(ExceptionGroup) as raised:
            admin._raise_after_cleanup("Provision", operation, (cleanup,))
        self.assertEqual(raised.exception.exceptions, (operation, cleanup))
        with self.assertRaisesRegex(RuntimeError, "operation"):
            admin._raise_after_cleanup("Provision", operation, ())

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
                for line in _environment_text(state_root).splitlines()
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

    def test_backups_and_unrelated_docker_resources_have_no_cleanup_target(self):
        shell_files = list(SQL_SERVER_ROOT.glob("*.sh")) + [
            SQL_SERVER_ROOT / "lib/common.sh"
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in shell_files)
        for forbidden in (
            "docker system prune",
            "docker container prune",
            "docker rm",
            "docker network rm",
        ):
            self.assertNotIn(forbidden, combined)
        self.assertNotIn("backups -delete", combined)
        uninstall = (SQL_SERVER_ROOT / "uninstall.sh").read_text(encoding="utf-8")
        self.assertLess(
            uninstall.index("require_container_identity"),
            uninstall.index("compose down"),
        )


if __name__ == "__main__":
    unittest.main()
