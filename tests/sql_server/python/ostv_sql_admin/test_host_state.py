from __future__ import annotations
import contextlib
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import call, patch
from sql_server.python.ostv_sql_admin import common, host_state
from tests.sql_server.python.ostv_sql_admin.environment_support import (
    POSIX_ROOT_REASON,
    RUNS_AS_POSIX_ROOT,
    _environment_text as _environment_support__environment_text,
    windows_safe_replace,
)

KEY_A = "A" * 43 + "="
KEY_B = "B" * 43 + "="
KEY_C = "C" * 43 + "="
PASSWORD = "unique-bootstrap-secret"


def _values(state_root: Path, **overrides: str) -> dict[str, str]:
    values = dict(
        line.split("=", 1)
        for line in _environment_support__environment_text(state_root).splitlines()
    )
    values.update(overrides)
    return values


def _secret(**overrides) -> common.ConnectionSecret:
    values = dict(
        server="sql.example.internal",
        port=11433,
        database="OSTVisualizer",
        username="OSTV_CLIENT",
        password="client-test-password",
        encrypt=True,
        trust_server_certificate=False,
        ownership_marker="marker",
    )
    values.update(overrides)
    return common.ConnectionSecret(**values)


@unittest.skipUnless(RUNS_AS_POSIX_ROOT, POSIX_ROOT_REASON)
class SqlAdminHostStateTests(unittest.TestCase):
    """Real 0600/0700 root-owned permission paths; POSIX with st_uid == 0 only.
    The same rollback logic is exercised without the permission checks by
    SqlAdminHostStatePrivateFileTests, which runs on every platform.
    """

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


class SqlAdminHostStatePureTests(unittest.TestCase):
    """Host-state logic with environment, DNS and docker replaced by fakes."""

    def environment_values(self, **overrides):
        return _values(Path("/state"), **overrides)

    def test_public_dns_must_resolve_only_to_the_configured_bind_address(self):
        values = self.environment_values()
        with (
            patch.object(host_state, "load_environment", return_value=values),
            patch.object(
                host_state.socket,
                "getaddrinfo",
                return_value=[(2, 1, 6, "", ("8.8.8.8", 0))],
            ) as lookup,
        ):
            result = host_state.verify_public_dns()
        self.assertEqual(result, {"status": "public-dns-valid", "address": "8.8.8.8"})
        lookup.assert_called_once_with("sql.example.internal", None)
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

    def test_public_dns_with_extra_or_no_addresses_is_refused(self):
        values = self.environment_values()
        duplicated = [(2, 1, 6, "", ("8.8.8.8", 0)), (2, 2, 17, "", ("8.8.8.8", 0))]
        with (
            patch.object(host_state, "load_environment", return_value=values),
            patch.object(host_state.socket, "getaddrinfo", return_value=duplicated),
        ):
            self.assertEqual(host_state.verify_public_dns()["address"], "8.8.8.8")
        extra = duplicated + [(2, 1, 6, "", ("1.2.3.4", 0))]
        with (
            patch.object(host_state, "load_environment", return_value=values),
            patch.object(host_state.socket, "getaddrinfo", return_value=extra),
        ):
            with self.assertRaisesRegex(RuntimeError, "does not resolve exclusively"):
                host_state.verify_public_dns()
        with (
            patch.object(host_state, "load_environment", return_value=values),
            patch.object(
                host_state.socket,
                "getaddrinfo",
                side_effect=host_state.socket.gaierror("no such host"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "name does not resolve"):
                host_state.verify_public_dns()

    def reset_fixture(self):
        secret = _secret(database="master", username="sa", password=PASSWORD)
        admin_secret = _secret(
            username="OSTV_PROVISIONER", password=PASSWORD, database="OSTVisualizer"
        )
        values = {"OSTV_CONTAINER_NAME": "owned", "OSTV_DEPLOYMENT_ID": "deployment"}
        labels = (
            '{"com.ostvisualizer.deployment-id":"deployment",'
            '"com.ostvisualizer.component":"sqlserver"}'
        )
        return secret, admin_secret, values, labels

    def test_sa_reset_does_not_print_or_put_password_in_arguments(self):
        password = PASSWORD
        secret, admin_secret, values, labels = self.reset_fixture()
        output = io.StringIO()
        with (
            patch.object(host_state, "load_environment", return_value=values),
            patch.object(host_state, "read_secret", side_effect=(secret, admin_secret)),
            patch.object(
                host_state,
                "_run_command",
                side_effect=(labels, ""),
            ) as run,
            redirect_stdout(output),
        ):
            result = host_state.reset_sa_password()
            read_calls = host_state.read_secret.call_args_list
        self.assertEqual(
            result, {"status": "sa-password-reset", "secret_printed": False}
        )
        credentials = Path("/home/SQLServer") / "secrets" / "container"
        self.assertEqual(
            [call.args[0] for call in read_calls],
            [credentials / "bootstrap.json", credentials / "admin.json"],
        )
        inspect_call, reset_call = run.call_args_list
        self.assertEqual(
            inspect_call.args[0],
            ("docker", "inspect", "--format", "{{json .Config.Labels}}", "owned"),
        )
        command = reset_call.args[0]
        self.assertNotIn(password, command)
        self.assertEqual(
            command,
            (
                "docker",
                "exec",
                "--user",
                "0:0",
                "--env",
                "MSSQL_SA_PASSWORD",
                "owned",
                "/opt/mssql/bin/mssql-conf",
                "set-sa-password",
            ),
        )
        self.assertEqual(
            reset_call.kwargs["environment"]["MSSQL_SA_PASSWORD"], password
        )
        self.assertEqual(reset_call.kwargs["secrets"], (password,))
        self.assertEqual(
            reset_call.kwargs["environment"]["PATH"], os.environ.get("PATH")
        )
        self.assertNotIn("MSSQL_SA_PASSWORD", os.environ)
        self.assertEqual(output.getvalue(), "")

    def test_sa_reset_refuses_foreign_containers_and_invalid_bootstrap_credentials(
        self,
    ):
        secret, admin_secret, values, labels = self.reset_fixture()
        foreign = labels.replace("deployment", "other-deployment", 1)
        with (
            patch.object(host_state, "load_environment", return_value=values),
            patch.object(host_state, "read_secret") as read,
            patch.object(host_state, "_run_command", return_value=foreign) as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "ownership labels do not match"):
                host_state.reset_sa_password()
        read.assert_not_called()
        self.assertEqual(run.call_count, 1)
        bootstrap_cases = {
            "wrong user": _secret(
                database="master", username="admin", password=PASSWORD
            ),
            "wrong database": _secret(
                database="Other", username="sa", password=PASSWORD
            ),
        }
        for label, bad in bootstrap_cases.items():
            with self.subTest(label):
                with (
                    patch.object(host_state, "load_environment", return_value=values),
                    patch.object(
                        host_state, "read_secret", side_effect=(bad, admin_secret)
                    ),
                    patch.object(
                        host_state, "_run_command", return_value=labels
                    ) as run,
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "bootstrap credential is invalid"
                    ):
                        host_state.reset_sa_password()
                self.assertEqual(run.call_count, 1)
        other_marker = _secret(
            database="OSTVisualizer", ownership_marker="different", password=PASSWORD
        )
        with (
            patch.object(host_state, "load_environment", return_value=values),
            patch.object(host_state, "read_secret", side_effect=(secret, other_marker)),
            patch.object(host_state, "_run_command", return_value=labels) as run,
        ):
            with self.assertRaisesRegex(
                RuntimeError, "ownership marker does not match"
            ):
                host_state.reset_sa_password()
        self.assertEqual(run.call_count, 1)

    def test_container_identity_requires_matching_deployment_labels(self):
        values = {"OSTV_CONTAINER_NAME": "owned", "OSTV_DEPLOYMENT_ID": "deployment"}
        good = {
            "com.ostvisualizer.deployment-id": "deployment",
            "com.ostvisualizer.component": "sqlserver",
        }
        with patch.object(
            host_state, "_run_command", return_value=json.dumps(good)
        ) as run:
            self.assertEqual(
                host_state.require_container_identity(values),
                {"status": "container-identity-valid"},
            )
        self.assertEqual(run.call_args.args[0][-1], "owned")
        for label, output in {
            "other deployment": json.dumps(
                {**good, "com.ostvisualizer.deployment-id": "x"}
            ),
            "other component": json.dumps(
                {**good, "com.ostvisualizer.component": "web"}
            ),
            "no labels": "null",
            "list": "[]",
            "empty": "{}",
        }.items():
            with self.subTest(label):
                with patch.object(host_state, "_run_command", return_value=output):
                    with self.assertRaisesRegex(
                        RuntimeError, "ownership labels do not match"
                    ):
                        host_state.require_container_identity(values)
        with patch.object(host_state, "_run_command", return_value="{not json"):
            with self.assertRaisesRegex(RuntimeError, "invalid ownership label"):
                host_state.require_container_identity(values)

    def test_run_command_redacts_secrets_from_failures_and_strips_output(self):
        completed = subprocess.CompletedProcess(
            ("docker",), 0, stdout=" ok \n", stderr=""
        )
        with patch.object(host_state.subprocess, "run", return_value=completed) as run:
            output = host_state._run_command(
                ("docker", "ps"), environment={"A": "1"}, secrets=(PASSWORD,)
            )
        self.assertEqual(output, "ok")
        self.assertEqual(run.call_args.args[0], ("docker", "ps"))
        self.assertEqual(run.call_args.kwargs["check"], False)
        self.assertEqual(run.call_args.kwargs["env"], {"A": "1"})
        self.assertIs(run.call_args.kwargs["text"], True)
        self.assertEqual(run.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.PIPE)
        failed = subprocess.CompletedProcess(
            ("docker",), 1, stdout="", stderr=f"denied for {PASSWORD}\n"
        )
        with patch.object(host_state.subprocess, "run", return_value=failed):
            with self.assertRaises(RuntimeError) as raised:
                host_state._run_command(("docker", "ps"), secrets=(PASSWORD,))
        self.assertIn("without changing the requested target", str(raised.exception))
        self.assertIn("denied for <redacted>", str(raised.exception))
        self.assertNotIn(PASSWORD, str(raised.exception))

    def test_peer_creation_refuses_bad_names_and_addresses_before_touching_files(self):
        values = self.environment_values()
        key_path = Path("never-read.key")
        cases = (
            ("bad name", "bad name", "10.250.240.2", "peer name is invalid"),
            ("traversal name", "../evil", "10.250.240.2", "peer name is invalid"),
            ("empty name", "", "10.250.240.2", "peer name is invalid"),
            ("not an address", "ok-name", "10.250.240", "peer address is invalid"),
            (
                "outside subnet",
                "ok-name",
                "10.250.241.2",
                "not usable in the private subnet",
            ),
            (
                "server address",
                "ok-name",
                "10.250.240.1",
                "not usable in the private subnet",
            ),
            (
                "network address",
                "ok-name",
                "10.250.240.0",
                "not usable in the private subnet",
            ),
            (
                "broadcast address",
                "ok-name",
                "10.250.240.255",
                "not usable in the private subnet",
            ),
        )
        with (
            patch.object(host_state, "load_environment", return_value=values),
            patch.object(host_state, "require_private_file") as private_file,
        ):
            for label, name, address, message in cases:
                with self.subTest(label):
                    with self.assertRaisesRegex(RuntimeError, message):
                        host_state.create_wireguard_peer(
                            name, address, key_path, key_path
                        )
            private_file.assert_not_called()

    def test_main_prints_json_results_and_reports_host_state_errors(self):
        with patch.object(
            host_state,
            "verify_public_dns",
            return_value={"status": "b", "address": "a"},
        ):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(host_state.main(["verify-public-dns"]), 0)
            self.assertEqual(out.getvalue(), '{"address": "a", "status": "b"}\n')
        for error in (RuntimeError("bad state"), OSError("disk gone")):
            with self.subTest(type(error).__name__):
                with patch.object(host_state, "verify_public_dns", side_effect=error):
                    out, err = io.StringIO(), io.StringIO()
                    with (
                        contextlib.redirect_stdout(out),
                        contextlib.redirect_stderr(err),
                    ):
                        self.assertEqual(host_state.main(["verify-public-dns"]), 1)
                    self.assertEqual(out.getvalue(), "")
                    self.assertEqual(err.getvalue(), f"Host-state error: {error}\n")
        with patch.object(
            host_state, "create_wireguard_peer", return_value={"ok": 1}
        ) as create:
            with contextlib.redirect_stdout(io.StringIO()):
                host_state.main(
                    ["create-wireguard-peer", "n", "10.0.0.2", "a.key", "b.key"]
                )
        create.assert_called_once_with("n", "10.0.0.2", Path("a.key"), Path("b.key"))
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                host_state.main(["format-disk"])
        self.assertEqual(raised.exception.code, 2)


class SqlAdminHostStatePrivateFileTests(unittest.TestCase):
    """Private-file workflows with permission checks bypassed (any platform)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_root = Path(self.tmp.name) / "state"
        for relative in (
            "wireguard/server",
            "wireguard/peers",
            "temporary",
            "secrets/container",
        ):
            (self.state_root / relative).mkdir(parents=True)
        self.values = _values(self.state_root)
        self.require_file = patch.object(host_state, "require_private_file")
        self.require_directory = patch.object(host_state, "require_private_directory")
        for target in (
            windows_safe_replace(),
            patch.object(common, "PRIVATE_STATE_ROOT", self.state_root),
            patch.object(host_state, "PRIVATE_STATE_ROOT", self.state_root),
            patch.object(host_state, "load_environment", return_value=self.values),
            self.require_file,
            self.require_directory,
            patch.object(common, "require_private_file"),
            patch.object(
                host_state,
                "_read_public_wireguard_key",
                host_state._read_wireguard_key,
            ),
        ):
            started = target.start()
            if target is self.require_file:
                self.require_file = started
            elif target is self.require_directory:
                self.require_directory = started
            self.addCleanup(target.stop)

    def write_key(self, relative, key):
        path = self.state_root / relative
        path.write_text(key + "\n", encoding="ascii")
        return path

    def write_peer(self, name, key, address, **extra):
        payload = {"name": name, "public_key": key, "allowed_ip": address, **extra}
        path = self.state_root / "wireguard" / "peers" / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_render_wireguard_config_lists_peers_in_name_order(self):
        self.write_key("wireguard/server/private.key", KEY_A)
        self.write_peer("beta", KEY_C, "10.250.240.3")
        self.write_peer("alpha", KEY_B, "10.250.240.2")
        result = host_state.render_wireguard_config()
        self.assertEqual(result, {"status": "wireguard-rendered", "peer_count": 2})
        rendered = (self.state_root / "wireguard/server/wg-ostv.conf").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            rendered,
            "\n".join(
                (
                    "[Interface]",
                    "Address = 10.250.240.1/24",
                    "ListenPort = 51820",
                    f"PrivateKey = {KEY_A}",
                    "",
                    "# peer: alpha",
                    "[Peer]",
                    f"PublicKey = {KEY_B}",
                    "AllowedIPs = 10.250.240.2/32",
                    "",
                    "# peer: beta",
                    "[Peer]",
                    f"PublicKey = {KEY_C}",
                    "AllowedIPs = 10.250.240.3/32",
                    "",
                )
            ),
        )

    def test_render_wireguard_config_refuses_invalid_peer_records(self):
        self.write_key("wireguard/server/private.key", KEY_A)
        peers = self.state_root / "wireguard" / "peers"
        self.write_peer("alpha", KEY_B, "10.250.240.2")
        invalid = {
            "duplicate address": lambda: self.write_peer("beta", KEY_C, "10.250.240.2"),
            "outside subnet": lambda: self.write_peer("beta", KEY_C, "10.250.241.9"),
            "server address": lambda: self.write_peer("beta", KEY_C, "10.250.240.1"),
            "broadcast address": lambda: self.write_peer(
                "beta", KEY_C, "10.250.240.255"
            ),
            "bad address": lambda: self.write_peer("beta", KEY_C, "nope"),
            "bad key": lambda: self.write_peer("beta", "short", "10.250.240.3"),
            "extra field": lambda: self.write_peer(
                "beta", KEY_C, "10.250.240.3", note="x"
            ),
            "bad name": lambda: self.write_peer("be ta", KEY_C, "10.250.240.3"),
            "name mismatch": lambda: (peers / "beta.json").write_text(
                json.dumps(
                    {"name": "gamma", "public_key": KEY_C, "allowed_ip": "10.250.240.3"}
                ),
                encoding="utf-8",
            ),
            "not json": lambda: (peers / "beta.json").write_text(
                "{nope", encoding="utf-8"
            ),
            "list": lambda: (peers / "beta.json").write_text("[]", encoding="utf-8"),
            "list of the expected field names": lambda: (
                peers / "beta.json"
            ).write_text(
                json.dumps(["name", "public_key", "allowed_ip"]), encoding="utf-8"
            ),
            "numeric name": lambda: (peers / "beta.json").write_text(
                json.dumps(
                    {"name": 5, "public_key": KEY_C, "allowed_ip": "10.250.240.3"}
                ),
                encoding="utf-8",
            ),
            "numeric public key": lambda: (peers / "beta.json").write_text(
                json.dumps(
                    {"name": "beta", "public_key": 7, "allowed_ip": "10.250.240.3"}
                ),
                encoding="utf-8",
            ),
        }
        for label, make in invalid.items():
            with self.subTest(label):
                make()
                with self.assertRaisesRegex(RuntimeError, "WireGuard peer|Invalid"):
                    host_state.render_wireguard_config()
                (peers / "beta.json").unlink(missing_ok=True)
                (peers / "be ta.json").unlink(missing_ok=True)
        self.assertEqual(host_state.render_wireguard_config()["peer_count"], 1)

    def test_render_wireguard_config_refuses_an_invalid_server_key(self):
        self.write_key("wireguard/server/private.key", "not-a-key")
        with self.assertRaisesRegex(RuntimeError, "Invalid WireGuard key file"):
            host_state.render_wireguard_config()
        self.assertFalse((self.state_root / "wireguard/server/wg-ostv.conf").exists())

    def create_peer(self, name="client-one", address="10.250.240.2"):
        private = self.write_key("temporary/private.key", KEY_A)
        public = self.write_key("temporary/public.key", KEY_B)
        self.write_key("wireguard/server/public.key", KEY_C)
        return host_state.create_wireguard_peer(name, address, private, public)

    def test_peer_creation_writes_record_and_client_configuration(self):
        result = self.create_peer()
        config_path = self.state_root / "temporary/wireguard-client-one.conf"
        self.assertEqual(
            result,
            {
                "status": "wireguard-peer-created",
                "client_config": str(config_path),
                "sql_server": "10.250.240.1",
                "sql_port": 11433,
                "certificate_name": "sql.example.internal",
            },
        )
        record = json.loads(
            (self.state_root / "wireguard/peers/client-one.json").read_text("utf-8")
        )
        self.assertEqual(
            record,
            {"name": "client-one", "public_key": KEY_B, "allowed_ip": "10.250.240.2"},
        )
        self.assertEqual(
            config_path.read_text(encoding="utf-8"),
            "\n".join(
                (
                    "[Interface]",
                    f"PrivateKey = {KEY_A}",
                    "Address = 10.250.240.2/32",
                    "",
                    "[Peer]",
                    f"PublicKey = {KEY_C}",
                    "Endpoint = vpn.example.invalid:51820",
                    "AllowedIPs = 10.250.240.1/32",
                    "PersistentKeepalive = 25",
                    "",
                    "# SQL Server: 10.250.240.1,11433",
                    "# Certificate name: sql.example.internal",
                    "",
                )
            ),
        )
        self.assertNotIn(KEY_A, json.dumps(result))

    def test_peer_creation_brackets_ipv6_endpoints(self):
        self.values["OSTV_PUBLIC_ENDPOINT"] = "2001:db8::1"
        self.create_peer()
        text = (self.state_root / "temporary/wireguard-client-one.conf").read_text(
            "utf-8"
        )
        self.assertIn("Endpoint = [2001:db8::1]:51820\n", text)

    def test_peer_creation_refuses_existing_peers_and_authorized_addresses(self):
        self.create_peer()
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            self.create_peer()
        (self.state_root / "wireguard/peers/client-one.json").unlink()
        with self.assertRaisesRegex(RuntimeError, "undelivered client configuration"):
            self.create_peer()
        (self.state_root / "temporary/wireguard-client-one.conf").unlink()
        self.write_peer("other", KEY_C, "10.250.240.2")
        with self.assertRaisesRegex(RuntimeError, "already authorized"):
            self.create_peer()
        self.assertFalse((self.state_root / "wireguard/peers/client-one.json").exists())
        self.assertFalse(
            (self.state_root / "temporary/wireguard-client-one.conf").exists()
        )

    def test_peer_creation_rolls_back_partial_private_files(self):
        self.write_key("temporary/private.key", KEY_A)
        self.write_key("temporary/public.key", KEY_B)
        self.write_key("wireguard/server/public.key", KEY_C)
        original_write = common.atomic_write_private
        calls = []

        def fail_second(path, content):
            calls.append(path.name)
            if len(calls) == 2:
                path.write_text("partial client configuration", encoding="utf-8")
                raise OSError("second write failed")
            original_write(path, content)

        with patch.object(host_state, "atomic_write_private", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "second write failed"):
                host_state.create_wireguard_peer(
                    "client-one",
                    "10.250.240.2",
                    self.state_root / "temporary/private.key",
                    self.state_root / "temporary/public.key",
                )
        self.assertEqual(calls, ["client-one.json", "wireguard-client-one.conf"])
        self.assertFalse((self.state_root / "wireguard/peers/client-one.json").exists())
        self.assertFalse(
            (self.state_root / "temporary/wireguard-client-one.conf").exists()
        )

    def test_peer_creation_rolls_back_the_record_when_the_first_write_fails(self):
        self.write_key("temporary/private.key", KEY_A)
        self.write_key("temporary/public.key", KEY_B)
        self.write_key("wireguard/server/public.key", KEY_C)
        with patch.object(
            host_state,
            "atomic_write_private",
            side_effect=OSError("first write failed"),
        ):
            with self.assertRaisesRegex(OSError, "first write failed"):
                host_state.create_wireguard_peer(
                    "client-one",
                    "10.250.240.2",
                    self.state_root / "temporary/private.key",
                    self.state_root / "temporary/public.key",
                )
        self.assertEqual(list((self.state_root / "wireguard/peers").iterdir()), [])

    def seed_credentials(self, **client_overrides):
        directory = self.state_root / "secrets/container"
        admin = _secret(
            server="old.example.internal",
            username="OSTV_PROVISIONER",
            password="admin-pw",
        )
        client = _secret(
            server="old.example.internal", password="client-pw", **client_overrides
        )
        common.write_secret(directory / "admin.json", admin)
        common.write_secret(directory / "client.json", client)
        return directory, admin, client

    def test_credential_endpoint_sync_updates_server_and_port_idempotently(self):
        directory, admin, client = self.seed_credentials()
        first = host_state.sync_credential_endpoint()
        second = host_state.sync_credential_endpoint()
        self.assertEqual(
            first,
            {
                "status": "credential-endpoint-synchronized",
                "changed": 2,
                "secret_printed": False,
            },
        )
        self.assertEqual(second["changed"], 0)
        for role, before in (("admin", admin), ("client", client)):
            after = common.read_secret(directory / f"{role}.json")
            self.assertEqual(after.server, "sql.example.internal")
            self.assertEqual(after.port, 11433)
            self.assertEqual(after.password, before.password)
            self.assertEqual(after.username, before.username)

    def test_credential_endpoint_sync_rolls_back_when_a_later_write_fails(self):
        directory, admin, client = self.seed_credentials()
        writes = []

        def fail_second(path, secret):
            writes.append(path.name)
            if len(writes) == 2:
                raise OSError("second endpoint write failed")
            common.write_secret(path, secret)

        with patch.object(host_state, "write_secret", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "second endpoint write failed"):
                host_state.sync_credential_endpoint()
        self.assertEqual(common.read_secret(directory / "admin.json"), admin)
        self.assertEqual(common.read_secret(directory / "client.json"), client)

    def test_credential_endpoint_sync_reports_failed_rollbacks_together(self):
        directory, admin, client = self.seed_credentials()
        writes = []

        def always_fail_after_first(path, secret):
            writes.append(path.name)
            if len(writes) == 1:
                common.write_secret(path, secret)
                return
            raise OSError(f"write {len(writes)} failed")

        with patch.object(
            host_state, "write_secret", side_effect=always_fail_after_first
        ):
            with self.assertRaises(ExceptionGroup) as raised:
                host_state.sync_credential_endpoint()
        messages = [str(error) for error in raised.exception.exceptions]
        self.assertEqual(messages, ["write 2 failed", "write 3 failed"])

    def test_credential_endpoint_sync_refuses_mismatched_credentials(self):
        cases = {
            "other database": {"database": "Other"},
            "other user": {"username": "SOMEONE"},
            "no encryption": {"encrypt": False},
            "trusted certificate": {"trust_server_certificate": True},
            "other marker": {"ownership_marker": "different"},
        }
        directory = self.state_root / "secrets/container"
        for label, overrides in cases.items():
            with self.subTest(label):
                self.seed_credentials(**overrides)
                with self.assertRaisesRegex(RuntimeError, "does not match|marker"):
                    host_state.sync_credential_endpoint()
                self.assertEqual(
                    common.read_secret(directory / "client.json").server,
                    "old.example.internal",
                )

    def test_bootstrap_password_sync_writes_the_protected_password_into_the_env_file(
        self,
    ):
        directory = self.state_root / "secrets/container"
        bootstrap = _secret(database="master", username="sa", password="Bootstrap-Pw-1")
        common.write_secret(directory / "bootstrap.json", bootstrap)
        common.write_secret(
            directory / "admin.json", _secret(username="OSTV_PROVISIONER")
        )
        env_path = self.state_root / ".env"
        env_path.write_text(
            _environment_support__environment_text(self.state_root), encoding="utf-8"
        )
        result = host_state.sync_bootstrap_password()
        self.assertEqual(
            result, {"status": "bootstrap-synchronized", "secret_printed": False}
        )
        lines = env_path.read_text(encoding="utf-8").splitlines()
        self.assertIn("OSTV_SA_PASSWORD=Bootstrap-Pw-1", lines)
        self.assertEqual(len(lines), 24)
        self.assertNotIn("Bootstrap-Pw-1", json.dumps(result))
        self.values["OSTV_SA_PASSWORD"] = "Bootstrap-Pw-1"
        self.assertEqual(
            host_state.sync_bootstrap_password()["status"], "bootstrap-synchronized"
        )

    def test_bootstrap_password_sync_refuses_a_disagreeing_password_or_identity(self):
        directory = self.state_root / "secrets/container"
        env_path = self.state_root / ".env"
        env_text = _environment_support__environment_text(self.state_root)
        env_path.write_text(env_text, encoding="utf-8")
        admin = _secret(username="OSTV_PROVISIONER")
        common.write_secret(directory / "admin.json", admin)
        common.write_secret(
            directory / "bootstrap.json",
            _secret(database="master", username="sa", password="Bootstrap-Pw-1"),
        )
        self.values["OSTV_SA_PASSWORD"] = "Different-Pw-2"
        with self.assertRaisesRegex(
            RuntimeError, "disagrees with the private configuration"
        ):
            host_state.sync_bootstrap_password()
        self.assertEqual(env_path.read_text(encoding="utf-8"), env_text)
        self.values["OSTV_SA_PASSWORD"] = "<GENERATED_BY_SETUP>"
        for username, database in (("admin", "master"), ("sa", "OSTVisualizer")):
            common.write_secret(
                directory / "bootstrap.json",
                _secret(
                    database=database, username=username, password="Bootstrap-Pw-1"
                ),
            )
            with self.assertRaisesRegex(
                RuntimeError, "bootstrap credential is invalid"
            ):
                host_state.sync_bootstrap_password()
        common.write_secret(
            directory / "bootstrap.json",
            _secret(
                database="master",
                username="sa",
                password="Bootstrap-Pw-1",
                ownership_marker="foreign",
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "ownership marker does not match"):
            host_state.sync_bootstrap_password()
        self.assertEqual(env_path.read_text(encoding="utf-8"), env_text)
        common.write_secret(
            directory / "bootstrap.json",
            _secret(database="master", username="sa", password="Bootstrap-Pw-1"),
        )
        env_path.write_text(
            env_text.replace("OSTV_SA_PASSWORD=<GENERATED_BY_SETUP>\n", ""),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RuntimeError, "OSTV_SA_PASSWORD is missing"):
            host_state.sync_bootstrap_password()

    def test_peer_creation_removes_a_record_that_exists_when_its_write_still_failed(
        self,
    ):
        self.write_key("temporary/private.key", KEY_A)
        self.write_key("temporary/public.key", KEY_B)
        self.write_key("wireguard/server/public.key", KEY_C)
        original_write = common.atomic_write_private
        calls = []

        def write_then_fail(path, content):
            calls.append(path.name)
            original_write(path, content)
            if len(calls) == 1:
                raise OSError("restricting the record failed")

        with patch.object(
            host_state, "atomic_write_private", side_effect=write_then_fail
        ):
            with self.assertRaisesRegex(OSError, "restricting the record failed"):
                host_state.create_wireguard_peer(
                    "client-one",
                    "10.250.240.2",
                    self.state_root / "temporary/private.key",
                    self.state_root / "temporary/public.key",
                )
        self.assertEqual(calls, ["client-one.json"])
        self.assertEqual(list((self.state_root / "wireguard/peers").iterdir()), [])
        self.assertFalse(
            (self.state_root / "temporary/wireguard-client-one.conf").exists()
        )

    def test_peer_creation_allows_other_peers_and_refuses_an_existing_record_alone(
        self,
    ):
        self.write_peer("other", KEY_C, "10.250.240.3")
        result = self.create_peer()
        self.assertEqual(result["status"], "wireguard-peer-created")
        (self.state_root / "temporary/wireguard-client-one.conf").unlink()
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            self.create_peer()
        self.assertTrue((self.state_root / "wireguard/peers/client-one.json").exists())

    def test_the_private_directories_and_files_that_are_read_are_all_checked(self):
        server = self.state_root / "wireguard/server"
        peers = self.state_root / "wireguard/peers"
        temporary = self.state_root / "temporary"
        self.write_key("wireguard/server/private.key", KEY_A)
        alpha = self.write_peer("alpha", KEY_B, "10.250.240.2")
        host_state.render_wireguard_config()
        self.assertEqual(
            self.require_directory.call_args_list,
            [
                call(server, label="WireGuard server directory"),
                call(peers, label="WireGuard peers directory"),
            ],
        )
        self.assertEqual(
            self.require_file.call_args_list,
            [
                call(server / "private.key", label="WireGuard server private key"),
                call(alpha, label="WireGuard peer record"),
            ],
        )
        self.require_file.reset_mock()
        self.require_directory.reset_mock()
        self.write_key("temporary/private.key", KEY_A)
        self.write_key("temporary/public.key", KEY_B)
        self.write_key("wireguard/server/public.key", KEY_C)
        host_state.create_wireguard_peer(
            "client-one",
            "10.250.240.3",
            temporary / "private.key",
            temporary / "public.key",
        )
        self.assertEqual(
            self.require_file.call_args_list,
            [
                call(
                    temporary / "private.key",
                    label="temporary WireGuard private key",
                ),
                call(temporary / "public.key", label="temporary WireGuard public key"),
                call(alpha, label="WireGuard peer record"),
            ],
        )
        self.assertEqual(
            self.require_directory.call_args_list,
            [
                call(peers, label="WireGuard peers directory"),
                call(temporary, label="private temporary directory"),
            ],
        )

    def test_the_credential_directory_is_checked_before_any_secret_is_read(self):
        self.seed_credentials()
        directory = self.state_root / "secrets/container"
        events = []
        self.require_directory.side_effect = lambda *a, **k: events.append("check")
        original_read = common.read_secret

        def read(path):
            events.append("read")
            return original_read(path)

        with patch.object(host_state, "read_secret", side_effect=read):
            host_state.sync_credential_endpoint()
        self.require_directory.assert_called_once_with(
            directory, label="container credential directory"
        )
        self.assertEqual(events[0], "check")
        self.assertEqual(events.count("read"), 2)

    def malformed_peer_cases(self):
        peers = self.state_root / "wireguard" / "peers"

        def raw(text):
            return lambda: (peers / "beta.json").write_text(text, encoding="utf-8")

        def payload(**fields):
            record = {
                "name": "beta",
                "public_key": KEY_C,
                "allowed_ip": "10.250.240.3",
            }
            record.update(fields)
            return raw(json.dumps(record))

        return {
            "not json": raw("{nope"),
            "list": raw("[]"),
            "list of the expected field names": raw(
                json.dumps(["name", "public_key", "allowed_ip"])
            ),
            "missing field": raw(
                json.dumps({"name": "beta", "public_key": KEY_C}),
            ),
            "extra field": payload(note="x"),
            "numeric name": payload(name=5),
            "name mismatch": payload(name="gamma"),
            "numeric public key": payload(public_key=7),
            "short public key": payload(public_key="short"),
            "bad address": payload(allowed_ip="nope"),
            "address outside the subnet": payload(allowed_ip="10.250.241.9"),
            "server address": payload(allowed_ip="10.250.240.1"),
            "broadcast address": payload(allowed_ip="10.250.240.255"),
            "network address": payload(allowed_ip="10.250.240.0"),
            "address of another peer": payload(allowed_ip="10.250.240.2"),
        }

    def test_peer_creation_fails_loudly_on_a_malformed_existing_record(self):
        self.write_key("wireguard/server/private.key", KEY_A)
        peers = self.state_root / "wireguard" / "peers"
        self.write_peer("alpha", KEY_B, "10.250.240.2")
        for label, make in self.malformed_peer_cases().items():
            with self.subTest(label):
                make()
                malformed = (peers / "beta.json").read_bytes()
                with self.assertRaises(RuntimeError) as render_failure:
                    host_state.render_wireguard_config()
                with self.assertRaises(RuntimeError) as create_failure:
                    self.create_peer("client-one", "10.250.240.9")
                self.assertEqual(
                    str(create_failure.exception), str(render_failure.exception)
                )
                self.assertIn("beta.json", str(create_failure.exception))
                self.assertEqual((peers / "beta.json").read_bytes(), malformed)
                self.assertEqual(
                    sorted(path.name for path in peers.iterdir()),
                    ["alpha.json", "beta.json"],
                )
                self.assertEqual(
                    [path.name for path in (self.state_root / "temporary").iterdir()],
                    ["private.key", "public.key"],
                )
                (peers / "beta.json").unlink()
        self.assertEqual(
            self.create_peer("client-one", "10.250.240.9")["status"],
            "wireguard-peer-created",
        )

    def test_peer_creation_never_replaces_a_malformed_record_of_the_same_name(self):
        peers = self.state_root / "wireguard" / "peers"
        (peers / "client-one.json").write_text("{nope", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            self.create_peer()
        self.assertEqual((peers / "client-one.json").read_text("utf-8"), "{nope")
        self.assertFalse(
            (self.state_root / "temporary/wireguard-client-one.conf").exists()
        )


class SqlAdminPublicKeyFileTests(unittest.TestCase):
    """The WireGuard server public key may be 0600 or 0644, root-owned, never a link."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.key = Path(self.tmp.name) / "public.key"
        self.key.write_text(KEY_C + "\n", encoding="ascii")

    @staticmethod
    def scripted(mode, uid=0):
        return patch.object(
            Path,
            "stat",
            return_value=os.stat_result((mode, 0, 0, 1, uid, 0, 0, 0, 0, 0)),
        )

    def test_both_allowed_modes_return_the_key(self):
        for mode in (0o600, 0o644):
            with self.subTest(mode=oct(mode)):
                with self.scripted(stat.S_IFREG | mode):
                    self.assertEqual(
                        host_state._read_public_wireguard_key(self.key), KEY_C
                    )

    def test_every_other_mode_is_refused(self):
        for mode in (0o400, 0o640, 0o660, 0o666, 0o700, 0o755, 0o000):
            with self.subTest(mode=oct(mode)):
                with self.scripted(stat.S_IFREG | mode):
                    with self.assertRaisesRegex(
                        RuntimeError, "server public key permissions are invalid"
                    ):
                        host_state._read_public_wireguard_key(self.key)
        with self.scripted(stat.S_IFDIR | 0o644):
            with self.assertRaisesRegex(RuntimeError, "permissions are invalid"):
                host_state._read_public_wireguard_key(self.key)

    def test_a_key_not_owned_by_root_is_refused(self):
        for uid in (1, 1000):
            with self.subTest(uid=uid):
                with self.scripted(stat.S_IFREG | 0o644, uid):
                    with self.assertRaisesRegex(
                        RuntimeError, "server public key must be owned by root"
                    ):
                        host_state._read_public_wireguard_key(self.key)

    def test_a_symbolic_link_is_refused_before_it_is_examined(self):
        with (
            patch.object(Path, "is_symlink", return_value=True),
            patch.object(Path, "stat") as examine,
        ):
            with self.assertRaisesRegex(RuntimeError, "must not be a symbolic link"):
                host_state._read_public_wireguard_key(self.key)
        examine.assert_not_called()

    def test_a_malformed_key_is_refused_even_when_the_file_is_private(self):
        self.key.write_text("not-a-key\n", encoding="ascii")
        with self.scripted(stat.S_IFREG | 0o600):
            with self.assertRaisesRegex(RuntimeError, "Invalid WireGuard key file"):
                host_state._read_public_wireguard_key(self.key)


class SqlAdminHostStateCommandTests(unittest.TestCase):
    COMMANDS = {
        "verify-public-dns": "verify_public_dns",
        "sync-credential-endpoint": "sync_credential_endpoint",
        "sync-bootstrap-password": "sync_bootstrap_password",
        "reset-sa-password": "reset_sa_password",
        "require-container-identity": "require_container_identity",
        "render-wireguard": "render_wireguard_config",
    }

    def test_every_command_runs_exactly_its_own_operation_and_prints_its_result(self):
        for command, function in self.COMMANDS.items():
            with self.subTest(command=command):
                others = [
                    patch.object(host_state, name, side_effect=AssertionError(name))
                    for other, name in self.COMMANDS.items()
                    if other != command
                ]
                out = io.StringIO()
                with contextlib.ExitStack() as stack:
                    for patcher in others:
                        stack.enter_context(patcher)
                    target = stack.enter_context(
                        patch.object(
                            host_state, function, return_value={"status": command}
                        )
                    )
                    stack.enter_context(contextlib.redirect_stdout(out))
                    self.assertEqual(host_state.main([command]), 0)
                target.assert_called_once_with()
                self.assertEqual(json.loads(out.getvalue()), {"status": command})

    def test_a_command_is_required(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                host_state.main([])
        self.assertEqual(raised.exception.code, 2)
