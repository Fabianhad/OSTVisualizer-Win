from __future__ import annotations
import contextlib
import dataclasses
import io
import json
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from sql_server.python.ostv_sql_admin import common
from tests.paths import REPO_ROOT
from tests.sql_server.python.ostv_sql_admin.environment_support import (
    POSIX_ROOT_REASON,
    RUNS_AS_POSIX_ROOT,
    _environment_text as _environment_support__environment_text,
    windows_safe_replace,
)

SECRET_PASSWORD = "unique-test-password"


def _secret(**overrides) -> common.ConnectionSecret:
    values = dict(
        server="sql.example.internal",
        port=11433,
        database="OSTVisualizer",
        username="OSTV_CLIENT",
        password=SECRET_PASSWORD,
        encrypt=True,
        trust_server_certificate=False,
        ownership_marker="marker",
    )
    values.update(overrides)
    return common.ConnectionSecret(**values)


def _environment_with(state_root: Path, overrides: dict[str, str | None]) -> str:
    values = dict(
        line.split("=", 1)
        for line in _environment_support__environment_text(state_root).splitlines()
    )
    for key, value in overrides.items():
        if value is None:
            values.pop(key)
        else:
            values[key] = value
    return "".join(f"{key}={value}\n" for key, value in values.items())


@unittest.skipUnless(RUNS_AS_POSIX_ROOT, POSIX_ROOT_REASON)
class SqlAdminCommonTests(unittest.TestCase):
    """Tests that exercise the real 0600/0700 root-owned permission checks.
    They need POSIX file modes and st_uid == 0 (the deployment tooling runs as
    root); Windows reports different mode bits, so they cannot run there. The
    value validation they rely on is covered without the permission checks by
    SqlAdminEnvironmentValidationTests.
    """

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


class SqlAdminCommonSafetyTests(unittest.TestCase):
    """Platform-independent safety contracts (no permission bits, no real SQL)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_root = Path(self.tmp.name) / "state"
        self.state_root.mkdir()
        replace_patch = windows_safe_replace()
        replace_patch.start()
        self.addCleanup(replace_patch.stop)

    def test_missing_private_configuration_fails_clearly(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing-state"
            with patch.object(common, "PRIVATE_STATE_ROOT", missing):
                with self.assertRaisesRegex(
                    RuntimeError, "private state root is missing"
                ):
                    common.load_config()

    def test_missing_private_file_and_outside_paths_are_refused(self):
        with patch.object(common, "PRIVATE_STATE_ROOT", self.state_root):
            with self.assertRaisesRegex(RuntimeError, "credential file is missing"):
                common.require_private_file(self.state_root / "absent.json")
            outside = Path(self.tmp.name) / "elsewhere"
            outside.mkdir()
            with self.assertRaisesRegex(RuntimeError, "must be under"):
                common.require_private_file(outside / "stolen.json")
            with self.assertRaisesRegex(RuntimeError, "must be under"):
                common.atomic_write_private(outside / "planted.json", "{}\n")
            self.assertEqual(list(outside.iterdir()), [])
            with self.assertRaisesRegex(RuntimeError, "missing parent directory"):
                common.atomic_write_private(
                    self.state_root / "not-created" / "x.json", "{}\n"
                )

    def test_ownership_mismatch_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "ownership marker does not match"):
            common.require_marker("actual", "expected", "database")

    def test_matching_marker_passes_and_blank_markers_are_refused(self):
        self.assertIsNone(common.require_marker("same", "same", "server"))
        for actual, expected in (("", ""), ("same", ""), ("", "same")):
            with self.subTest(actual=actual, expected=expected):
                with self.assertRaisesRegex(
                    RuntimeError, "the server ownership marker does not match"
                ):
                    common.require_marker(actual, expected, "server")

    def test_atomic_private_write_removes_temporary_after_success_and_failure(self):
        state_root = self.state_root
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
        self.assertEqual(sorted(p.name for p in state_root.iterdir()), ["value.json"])

    def test_atomic_private_write_does_not_clobber_target_when_write_fails(self):
        target = self.state_root / "value.json"
        with patch.object(common, "PRIVATE_STATE_ROOT", self.state_root):
            common.atomic_write_private(target, "original\n")
            with patch.object(common.os, "fsync", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    common.atomic_write_private(target, "replacement\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "original\n")
        self.assertEqual(list(self.state_root.glob(".*.tmp")), [])

    def test_atomic_private_write_is_exclusive_owner_only_and_durable_before_rename(
        self,
    ):
        target = self.state_root / "value.json"
        events, opened, written, closed = [], [], [], []
        real_open, real_chmod = os.open, os.chmod
        real_fsync, real_replace = os.fsync, os.replace

        def spy_open(path, flags, mode=0o777, **kwargs):
            opened.append(path)
            events.append(
                ("open", Path(path).name, flags & ~getattr(os, "O_BINARY", 0), mode)
            )
            return real_open(path, flags, mode, **kwargs)

        def spy_chmod(path, mode, **kwargs):
            events.append(("chmod", Path(path).name, mode))
            return real_chmod(path, mode, **kwargs)

        def spy_fsync(descriptor):
            events.append(("fsync",))
            written.append(Path(opened[0]).read_bytes())
            return real_fsync(descriptor)

        def spy_close(descriptor):
            # Only record: a stray close of a descriptor the test did not open (a
            # mutant closing stdout) must be reported, never carried out.
            closed.append(descriptor)

        def spy_replace(source, destination, *args, **kwargs):
            events.append(("replace", Path(source).name, Path(destination).name))
            return real_replace(source, destination, *args, **kwargs)

        with (
            patch.object(common, "PRIVATE_STATE_ROOT", self.state_root),
            patch.object(os, "open", spy_open),
            patch.object(os, "chmod", spy_chmod),
            patch.object(os, "fsync", spy_fsync),
            patch.object(os, "replace", spy_replace),
            patch.object(os, "close", spy_close),
        ):
            common.atomic_write_private(target, "{}\n")
        self.assertEqual(written, [b"{}\n"])
        self.assertEqual(closed, [])
        temporary = f".value.json.{os.getpid()}.tmp"
        self.assertEqual(
            events,
            [
                ("chmod", "state", 0o700),
                ("open", temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                ("fsync",),
                ("replace", temporary, "value.json"),
                ("chmod", "value.json", 0o600),
            ],
        )

    def test_atomic_private_write_never_overwrites_a_planted_temporary_file(self):
        target = self.state_root / "value.json"
        planted = self.state_root / f".value.json.{os.getpid()}.tmp"
        planted.write_text("planted by someone else\n", encoding="utf-8")
        with patch.object(common, "PRIVATE_STATE_ROOT", self.state_root):
            with self.assertRaises(FileExistsError):
                common.atomic_write_private(target, "{}\n")
        self.assertFalse(target.exists())
        self.assertEqual(
            planted.read_text(encoding="utf-8"), "planted by someone else\n"
        )

    def test_a_descriptor_that_never_reached_a_stream_is_closed_exactly_once(self):
        target = self.state_root / "value.json"
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

        with (
            patch.object(common, "PRIVATE_STATE_ROOT", self.state_root),
            patch.object(os, "open", spy_open),
            patch.object(os, "close", spy_close),
            patch.object(os, "fdopen", side_effect=OSError("no stream")),
        ):
            with self.assertRaisesRegex(OSError, "no stream"):
                common.atomic_write_private(target, "{}\n")
        self.assertEqual(len(opened), 1)
        self.assertEqual(closed, opened)
        self.assertEqual(list(self.state_root.iterdir()), [])

    def test_a_descriptor_numbered_zero_is_still_closed_when_no_stream_was_created(
        self,
    ):
        closed = []
        with (
            patch.object(common, "PRIVATE_STATE_ROOT", self.state_root),
            patch.object(os, "open", return_value=0),
            patch.object(os, "fdopen", side_effect=OSError("no stream")),
            patch.object(os, "close", side_effect=closed.append),
        ):
            with self.assertRaisesRegex(OSError, "no stream"):
                common.atomic_write_private(self.state_root / "value.json", "{}\n")
        self.assertEqual(closed, [0])

    def test_secret_and_configuration_records_are_immutable(self):
        config = common.DeploymentConfig(
            server="s",
            port=1,
            database="d",
            admin_login="a",
            client_login="c",
            edition="Express",
            secrets_directory=self.state_root,
            ownership_marker_file=self.state_root / "marker",
            backup_host_directory=self.state_root / "backups",
            backup_sql_directory=Path("/var/opt/mssql/backup"),
            data_sql_directory=Path("/var/opt/mssql/data"),
            container_name="n",
        )
        for record, field in ((_secret(), "password"), (config, "database")):
            with self.subTest(type=type(record).__name__):
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    setattr(record, field, "changed")

    def test_repository_root_is_the_checkout_that_holds_the_application(self):
        self.assertTrue(common.REPOSITORY_ROOT.samefile(REPO_ROOT))
        self.assertTrue((common.REPOSITORY_ROOT / "sql_server").is_dir())

    def test_secret_reads_demand_a_private_file_before_touching_its_content(self):
        path = self.state_root / "client.json"
        path.write_text("{}", encoding="utf-8")
        with (
            patch.object(
                common, "require_private_file", side_effect=RuntimeError("not private")
            ) as check,
            patch.object(Path, "read_text") as read,
        ):
            with self.assertRaisesRegex(RuntimeError, "not private"):
                common.read_secret(path)
        check.assert_called_once_with(path)
        read.assert_not_called()

    def test_secret_values_are_redacted(self):
        secret = _secret()
        self.assertNotIn(secret.password, repr(secret))
        self.assertEqual(repr(secret), "ConnectionSecret(<redacted>)")
        self.assertNotIn(secret.password, str(secret))
        self.assertNotIn(secret.password, f"{secret!s} {secret!r} {[secret]}")
        self.assertEqual(
            common.redact_text(f"failure {secret.password}", (secret.password,)),
            "failure <redacted>",
        )

    def test_redaction_replaces_every_occurrence_longest_secret_first(self):
        redact = common.redact_text
        self.assertEqual(
            redact("a abcdef b abc", ("abc", "abcdef")), "a <redacted> b <redacted>"
        )
        self.assertEqual(
            redact("x secret x secret", ("secret",)), "x <redacted> x <redacted>"
        )
        self.assertEqual(redact("nothing here", ("",)), "nothing here")
        self.assertEqual(redact("nothing here", ()), "nothing here")

    def test_password_is_not_part_of_secret_file_errors(self):
        secret = _secret()
        path = self.state_root / "client.json"
        with (
            patch.object(common, "PRIVATE_STATE_ROOT", self.state_root),
            patch.object(common, "require_private_file"),
        ):
            common.write_secret(path, secret)
            self.assertEqual(common.read_secret(path), secret)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(payload),
                {
                    "server",
                    "port",
                    "database",
                    "username",
                    "password",
                    "encrypt",
                    "trust_server_certificate",
                    "ownership_marker",
                },
            )
            self.assertTrue(path.read_text(encoding="utf-8").endswith("}\n"))
            cases = {
                "not json": "{not-json",
                "extra key": json.dumps({**payload, "extra": SECRET_PASSWORD}),
                "missing key": json.dumps(
                    {k: v for k, v in payload.items() if k != "username"}
                ),
                "string port": json.dumps({**payload, "port": "11433"}),
                "bool port": json.dumps({**payload, "port": True}),
                "numeric password": json.dumps({**payload, "password": 12345}),
                "string flag": json.dumps({**payload, "encrypt": "yes"}),
                "string trust flag": json.dumps(
                    {**payload, "trust_server_certificate": "no"}
                ),
                "numeric trust flag": json.dumps(
                    {**payload, "trust_server_certificate": 0}
                ),
                "numeric username": json.dumps({**payload, "username": 7}),
                "list": json.dumps([SECRET_PASSWORD]),
                "list of the expected key names": json.dumps(sorted(payload)),
            }
            for label, text in cases.items():
                with self.subTest(label):
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaises(RuntimeError) as raised:
                        common.read_secret(path)
                    self.assertNotIn(SECRET_PASSWORD, str(raised.exception))
                    self.assertIn("client.json", str(raised.exception))

    def test_verify_secret_matches_requires_exact_encrypted_deployment_identity(self):
        config = common.DeploymentConfig(
            server="sql.example.internal",
            port=11433,
            database="OSTVisualizer",
            admin_login="OSTV_PROVISIONER",
            client_login="OSTV_CLIENT",
            edition="Express",
            secrets_directory=self.state_root,
            ownership_marker_file=self.state_root / "marker",
            backup_host_directory=self.state_root / "backups",
            backup_sql_directory=Path("/var/opt/mssql/backup"),
            data_sql_directory=Path("/var/opt/mssql/data"),
            container_name="ostv-sql-test",
        )
        common.verify_secret_matches(_secret(), config, role="client")
        common.verify_secret_matches(
            _secret(username="OSTV_PROVISIONER"), config, role="admin"
        )
        mismatches = {
            "server": _secret(server="other.example.internal"),
            "port": _secret(port=1433),
            "database": _secret(database="Other"),
            "role user": _secret(username="OSTV_PROVISIONER"),
            "no encryption": _secret(encrypt=False),
            "trusted certificate": _secret(trust_server_certificate=True),
            "no marker": _secret(ownership_marker=""),
        }
        for label, secret in mismatches.items():
            with self.subTest(label):
                with self.assertRaisesRegex(
                    RuntimeError, "client credential does not match"
                ):
                    common.verify_secret_matches(secret, config, role="client")
        with self.assertRaisesRegex(RuntimeError, "admin credential does not match"):
            common.verify_secret_matches(_secret(), config, role="admin")

    def test_quote_identifier_accepts_only_safe_identifiers(self):
        self.assertEqual(common.quote_identifier("OSTVisualizer"), "[OSTVisualizer]")
        self.assertEqual(common.quote_identifier("a" * 128), "[" + "a" * 128 + "]")
        for unsafe in (
            "",
            "1abc",
            "a b",
            "a]b",
            "a;DROP",
            "a-b",
            "é",
            "a" * 129,
            "a\n",
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaisesRegex(RuntimeError, "unsafe SQL identifier"):
                    common.quote_identifier(unsafe)

    def test_brace_escapes_closing_braces_and_rejects_null_bytes(self):
        self.assertEqual(common._brace("p}a;ss"), "{p}}a;ss}")
        self.assertEqual(common._brace(""), "{}")
        with self.assertRaisesRegex(RuntimeError, "null byte"):
            common._brace("bad\x00value")

    def test_shell_callers_can_read_only_non_secret_configuration(self):
        with patch.object(
            common, "load_environment", return_value={"OSTV_SQL_DATABASE": "Db"}
        ) as load:
            self.assertEqual(common.config_value("OSTV_SQL_DATABASE"), "Db")
            load.reset_mock()
            for key in ("OSTV_SA_PASSWORD", "UNKNOWN_KEY", ""):
                with self.subTest(key=key):
                    with self.assertRaisesRegex(
                        RuntimeError, "not available to shell callers"
                    ):
                        common.config_value(key)
            load.assert_not_called()
        self.assertNotIn("OSTV_SA_PASSWORD", common.NON_SECRET_ENVIRONMENT_KEYS)
        self.assertEqual(
            common.NON_SECRET_ENVIRONMENT_KEYS | {"OSTV_SA_PASSWORD"},
            common.ENVIRONMENT_KEYS,
        )

    def test_cli_get_prints_only_public_values_and_reports_errors(self):
        values = {"OSTV_SQL_DATABASE": "Db", "OSTV_SA_PASSWORD": SECRET_PASSWORD}
        with patch.object(common, "load_environment", return_value=values):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = common.main(["get", "OSTV_SQL_DATABASE"])
            self.assertEqual((code, out.getvalue(), err.getvalue()), (0, "Db", ""))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = common.main(["get", "OSTV_SA_PASSWORD"])
            self.assertEqual(code, 1)
            self.assertEqual(out.getvalue(), "")
            self.assertIn("Configuration error:", err.getvalue())
            self.assertNotIn(SECRET_PASSWORD, out.getvalue() + err.getvalue())
        for argv in (["get"], ["validate", "OSTV_SQL_DATABASE"], ["unknown"]):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        common.main(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_cli_validate_loads_the_configuration(self):
        with patch.object(common, "load_config") as load:
            self.assertEqual(common.main(["validate"]), 0)
            load.assert_called_once_with()
        with patch.object(
            common, "load_config", side_effect=RuntimeError("bad configuration")
        ):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(common.main(["validate"]), 1)
            self.assertEqual(err.getvalue(), "Configuration error: bad configuration\n")


def _stat_result(mode: int, uid: int = 0) -> os.stat_result:
    return os.stat_result((mode, 0, 0, 1, uid, 0, 0, 0, 0, 0))


class SqlAdminPrivatePathCheckTests(unittest.TestCase):
    """The 0600/0700 root-owned rules, evaluated on scripted stat results.
    SqlAdminCommonTests exercises the same rules on real files, which needs POSIX
    modes and a root account. Here ``Path.stat`` answers with a scripted
    ``os.stat_result``, so every branch runs on every platform; the path itself is a
    real file or directory under a temporary state root.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_root = Path(self.tmp.name) / "state"
        self.state_root.mkdir()
        self.file = self.state_root / "secret.json"
        self.file.write_text("{}", encoding="utf-8")
        self.directory = self.state_root / "secrets"
        self.directory.mkdir()
        root = patch.object(common, "PRIVATE_STATE_ROOT", self.state_root)
        root.start()
        self.addCleanup(root.stop)

    def scripted(self, result):
        return patch.object(Path, "stat", return_value=result)

    def test_a_regular_file_with_mode_0600_owned_by_root_is_accepted(self):
        with self.scripted(_stat_result(stat.S_IFREG | 0o600)):
            self.assertIsNone(common.require_private_file(self.file))

    def test_every_other_file_mode_is_refused(self):
        for mode in (0o400, 0o440, 0o601, 0o640, 0o644, 0o666, 0o700, 0o000):
            with self.subTest(mode=oct(mode)):
                with self.scripted(_stat_result(stat.S_IFREG | mode)):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "credential file permissions must be 0600: secret.json",
                    ):
                        common.require_private_file(self.file)

    def test_a_file_must_be_regular_and_owned_by_root(self):
        with self.scripted(_stat_result(stat.S_IFDIR | 0o600)):
            with self.assertRaisesRegex(RuntimeError, "must be 0600"):
                common.require_private_file(self.file)
        for uid in (1, 1000):
            with self.subTest(uid=uid):
                with self.scripted(_stat_result(stat.S_IFREG | 0o600, uid)):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "credential file must be owned by root: secret.json",
                    ):
                        common.require_private_file(self.file)

    def test_the_label_names_the_kind_of_file_in_every_message(self):
        with self.scripted(_stat_result(stat.S_IFREG | 0o644)):
            with self.assertRaisesRegex(RuntimeError, "The WireGuard key permissions"):
                common.require_private_file(self.file, label="WireGuard key")
        with self.scripted(_stat_result(stat.S_IFREG | 0o600, 5)):
            with self.assertRaisesRegex(
                RuntimeError, "The WireGuard key must be owned"
            ):
                common.require_private_file(self.file, label="WireGuard key")
        with self.assertRaisesRegex(RuntimeError, "Required WireGuard key is missing"):
            common.require_private_file(
                self.state_root / "absent.json", label="WireGuard key"
            )

    def test_a_symbolic_link_is_refused_before_it_is_examined(self):
        with (
            patch.object(Path, "is_symlink", return_value=True),
            patch.object(Path, "stat") as examine,
        ):
            with self.assertRaisesRegex(RuntimeError, "must not be a symbolic link"):
                common.require_private_file(self.file)
            with self.assertRaisesRegex(RuntimeError, "must not be a symbolic link"):
                common.require_private_directory(self.directory, label="secrets")
        examine.assert_not_called()

    def test_paths_outside_the_private_root_are_refused_before_their_mode_is_read(self):
        outside = Path(self.tmp.name) / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        with patch.object(Path, "stat") as examine:
            with self.assertRaisesRegex(RuntimeError, "must be under"):
                common.require_private_file(outside)
            with self.assertRaisesRegex(RuntimeError, "must be under"):
                common.require_private_directory(outside.parent, label="secrets")
        examine.assert_not_called()

    def test_a_private_directory_must_be_0700_owned_by_root(self):
        with self.scripted(_stat_result(stat.S_IFDIR | 0o700)):
            self.assertIsNone(
                common.require_private_directory(self.directory, label="secrets")
            )
        for mode in (0o500, 0o600, 0o701, 0o750, 0o755, 0o777):
            with self.subTest(mode=oct(mode)):
                with self.scripted(_stat_result(stat.S_IFDIR | mode)):
                    with self.assertRaisesRegex(
                        RuntimeError, "The secrets permissions must be 0700: secrets"
                    ):
                        common.require_private_directory(
                            self.directory, label="secrets"
                        )
        with self.scripted(_stat_result(stat.S_IFREG | 0o700)):
            with self.assertRaisesRegex(RuntimeError, "must be 0700"):
                common.require_private_directory(self.directory, label="secrets")
        with self.scripted(_stat_result(stat.S_IFDIR | 0o700, 1000)):
            with self.assertRaisesRegex(
                RuntimeError, "The secrets must be owned by root: secrets"
            ):
                common.require_private_directory(self.directory, label="secrets")
        with self.assertRaisesRegex(RuntimeError, "Required secrets is missing"):
            common.require_private_directory(
                self.state_root / "absent", label="secrets"
            )

    def test_the_state_root_itself_must_be_a_0700_root_owned_directory(self):
        with self.scripted(_stat_result(stat.S_IFDIR | 0o700)):
            self.assertIsNone(common._require_private_root())
        for mode in (0o500, 0o600, 0o750, 0o755):
            with self.subTest(mode=oct(mode)):
                with self.scripted(_stat_result(stat.S_IFDIR | mode)):
                    with self.assertRaisesRegex(
                        RuntimeError, "must be a mode-0700 directory"
                    ):
                        common._require_private_root()
        with self.scripted(_stat_result(stat.S_IFREG | 0o700)):
            with self.assertRaisesRegex(RuntimeError, "mode-0700 directory"):
                common._require_private_root()
        with self.scripted(_stat_result(stat.S_IFDIR | 0o700, 1000)):
            with self.assertRaisesRegex(RuntimeError, "must be owned by root"):
                common._require_private_root()
        with patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "must not be a symbolic link"):
                common._require_private_root()

    def test_loading_the_environment_checks_the_root_and_the_file_before_reading(self):
        (self.state_root / ".env").write_text(
            _environment_support__environment_text(self.state_root), encoding="utf-8"
        )
        calls = []
        with (
            patch.object(
                common,
                "_require_private_root",
                side_effect=lambda: calls.append("root"),
            ),
            patch.object(
                common,
                "require_private_file",
                side_effect=lambda path, **kwargs: calls.append(("file", path, kwargs)),
            ),
        ):
            common.load_environment()
        self.assertEqual(
            calls,
            [
                "root",
                (
                    "file",
                    self.state_root / ".env",
                    {"label": "deployment configuration"},
                ),
            ],
        )
        for failing in ("_require_private_root", "require_private_file"):
            with self.subTest(failing=failing):
                with (
                    patch.object(common, "_require_private_root"),
                    patch.object(common, "require_private_file"),
                    patch.object(common, failing, side_effect=RuntimeError("refused")),
                    patch.object(common, "_read_env_file") as read,
                ):
                    with self.assertRaisesRegex(RuntimeError, "refused"):
                        common.load_environment()
                read.assert_not_called()


class WindowsSafeReplaceHelperTests(unittest.TestCase):
    """The Windows retry helper may only hide a transient sharing violation.
    Every other error, and a PermissionError that does not go away, must reach the
    test that triggered it, so the helper can never turn a real failure into a pass.
    On POSIX the helper must not retry at all.
    """

    ATTEMPTS = 40 if os.name == "nt" else 1

    def helper_with(self, side_effect):
        with patch.object(os, "replace", side_effect=side_effect) as underlying:
            patcher = windows_safe_replace()
        sleeps = []
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patcher)
        stack.enter_context(
            patch.object(
                time, "sleep", side_effect=lambda seconds: sleeps.append(seconds)
            )
        )
        return underlying, sleeps

    def test_a_transient_permission_error_is_retried_until_the_rename_succeeds(self):
        underlying, sleeps = self.helper_with(
            [PermissionError("busy"), PermissionError("busy"), "done"]
        )
        if os.name == "nt":
            self.assertEqual(os.replace("source", "target"), "done")
            self.assertEqual(underlying.call_count, 3)
            self.assertEqual(sleeps, [0.05, 0.05])
        else:
            with self.assertRaisesRegex(PermissionError, "busy"):
                os.replace("source", "target")
            self.assertEqual(underlying.call_count, 1)
            self.assertEqual(sleeps, [])

    def test_a_permission_error_that_persists_is_raised_after_a_bounded_wait(self):
        failures = [PermissionError(f"locked {number}") for number in range(60)]
        underlying, sleeps = self.helper_with(failures)
        with self.assertRaises(PermissionError) as raised:
            os.replace("source", "target")
        self.assertEqual(underlying.call_count, self.ATTEMPTS)
        self.assertIs(raised.exception, failures[self.ATTEMPTS - 1])
        self.assertEqual(len(sleeps), self.ATTEMPTS - 1)
        self.assertLessEqual(sum(sleeps), 2.0)

    def test_any_other_error_is_raised_immediately_without_a_retry(self):
        for error in (OSError("replace failed"), FileNotFoundError("gone")):
            with self.subTest(error=type(error).__name__):
                underlying, sleeps = self.helper_with([error, "never reached"])
                with self.assertRaises(type(error)) as raised:
                    os.replace("source", "target")
                self.assertIs(raised.exception, error)
                self.assertEqual(underlying.call_count, 1)
                self.assertEqual(sleeps, [])

    def test_arguments_and_the_result_pass_through_unchanged(self):
        underlying, _sleeps = self.helper_with(["renamed"])
        self.assertEqual(
            os.replace("source", "target", src_dir_fd=None, dst_dir_fd=None), "renamed"
        )
        underlying.assert_called_once_with(
            "source", "target", src_dir_fd=None, dst_dir_fd=None
        )


class SqlAdminConnectTests(unittest.TestCase):
    """The ODBC connection builder, with the driver replaced by fakes."""

    def patched_pyodbc(self, drivers=None):
        drivers = [common.EXPECTED_DRIVER] if drivers is None else drivers
        connection = MagicMock()
        connect = patch.object(common.pyodbc, "connect", return_value=connection)
        listing = patch.object(common.pyodbc, "drivers", return_value=drivers)
        self.connect_mock = connect.start()
        listing.start()
        self.addCleanup(connect.stop)
        self.addCleanup(listing.stop)
        return connection

    def test_connection_string_is_always_encrypted_and_certificate_verified(self):
        connection = self.patched_pyodbc()
        secret = _secret(trust_server_certificate=True, encrypt=False)
        with common.connect(secret) as opened:
            self.assertIs(opened, connection)
            connection.close.assert_not_called()
        connection.close.assert_called_once_with()
        self.connect_mock.assert_called_once_with(
            "DRIVER={ODBC Driver 18 for SQL Server};"
            "SERVER={tcp:sql.example.internal,11433};DATABASE={OSTVisualizer};"
            "UID={OSTV_CLIENT};PWD={unique-test-password};Encrypt=yes;"
            "TrustServerCertificate=no;Connection Timeout=10;MARS_Connection=no;"
            "APP={OSTV SQL Admin};",
            autocommit=True,
            timeout=10,
        )

    def test_password_with_connection_string_metacharacters_is_brace_escaped(self):
        self.patched_pyodbc()
        with common.connect(_secret(password="p};Encrypt=no;x}"), database="master"):
            pass
        string = self.connect_mock.call_args.args[0]
        self.assertIn("PWD={p}};Encrypt=no;x}}};", string)
        self.assertIn("DATABASE={master};", string)
        self.assertEqual(string.count("Encrypt=yes"), 1)

    def test_connection_is_closed_when_the_block_fails(self):
        connection = self.patched_pyodbc()
        with self.assertRaisesRegex(ValueError, "boom"):
            with common.connect(_secret(), autocommit=False, app="Custom App"):
                raise ValueError("boom")
        connection.close.assert_called_once_with()
        self.assertEqual(self.connect_mock.call_args.kwargs["autocommit"], False)
        self.assertIn("APP={Custom App};", self.connect_mock.call_args.args[0])

    def test_unsafe_database_identifiers_never_reach_the_driver(self):
        self.patched_pyodbc()
        for database in ("x]; DROP DATABASE y;--", "", "1db"):
            with self.subTest(database=database):
                with self.assertRaisesRegex(
                    RuntimeError, "unsafe SQL database identifier"
                ):
                    with common.connect(_secret(), database=database):
                        self.fail("connection must not open")
        self.connect_mock.assert_not_called()

    def test_null_byte_in_a_credential_is_refused_without_echoing_it(self):
        self.patched_pyodbc()
        with self.assertRaisesRegex(RuntimeError, "null byte") as raised:
            with common.connect(_secret(password="bad\x00pass")):
                self.fail("connection must not open")
        self.assertNotIn("bad", str(raised.exception))
        self.connect_mock.assert_not_called()

    def test_missing_odbc_driver_is_refused_before_connecting(self):
        self.patched_pyodbc(drivers=["Other Driver"])
        with self.assertRaisesRegex(RuntimeError, "ODBC Driver 18"):
            with common.connect(_secret()):
                self.fail("connection must not open")
        self.connect_mock.assert_not_called()

    def test_pooling_is_disabled_so_closed_contexts_close_the_session(self):
        self.assertIs(common.pyodbc.pooling, False)

    def test_scalar_returns_first_column_and_always_closes_the_cursor(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.fetchone.return_value = ("value", "ignored")
        self.assertEqual(common.scalar(connection, "SELECT ?", 5), "value")
        cursor.execute.assert_called_once_with("SELECT ?", 5)
        cursor.close.assert_called_once_with()
        cursor.fetchone.return_value = None
        self.assertIsNone(common.scalar(connection, "SELECT 1"))
        cursor.execute.side_effect = RuntimeError("query failed")
        with self.assertRaisesRegex(RuntimeError, "query failed"):
            common.scalar(connection, "SELECT 2")
        self.assertEqual(cursor.close.call_count, 3)

    def test_marker_helpers_read_the_ownership_properties(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.fetchone.return_value = ("server-marker",)
        self.assertEqual(common.server_marker(connection), "server-marker")
        self.assertEqual(
            cursor.execute.call_args.args[1], "OSTVisualizerUbuntuDeployment"
        )
        cursor.fetchone.return_value = ("db-marker",)
        self.assertEqual(common.database_marker(connection), "db-marker")
        self.assertEqual(
            cursor.execute.call_args.args[1], "OSTVisualizerUbuntuDatabase"
        )
        cursor.fetchone.return_value = None
        self.assertEqual(common.database_marker(connection), "")
        cursor.fetchone.return_value = (None,)
        self.assertEqual(common.server_marker(connection), "")
        for statement in (cursor.execute.call_args.args[0],):
            self.assertIn(
                "FROM sys.extended_properties WHERE class=0 AND name=?", statement
            )

    def test_extended_properties_are_updated_or_added_by_name_with_parameters(self):
        cursor = MagicMock()
        common.set_extended_property(cursor, "Property", "marker-value")
        ((sql, *parameters),) = [call.args for call in cursor.execute.call_args_list]
        self.assertEqual(
            parameters,
            ["Property", "Property", "marker-value", "Property", "marker-value"],
        )
        self.assertEqual(sql.count("?"), 5)
        self.assertNotIn("marker-value", sql)
        self.assertIn("sp_updateextendedproperty", sql)
        self.assertIn("sp_addextendedproperty", sql)
        self.assertLess(sql.index("sp_updateextendedproperty"), sql.index("ELSE"))
        self.assertLess(sql.index("ELSE"), sql.index("sp_addextendedproperty"))
        self.assertIn(
            "IF EXISTS (SELECT 1 FROM sys.extended_properties WHERE class=0", sql
        )

    def test_active_application_sessions_counts_sessions_of_the_named_database(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        for stored, expected in (((3,), 3), ((0,), 0), (None, 0), ((None,), 0)):
            with self.subTest(stored=stored):
                cursor.fetchone.return_value = stored
                self.assertEqual(
                    common.active_application_sessions(connection, "Database"), expected
                )
        sql, database = cursor.execute.call_args.args
        self.assertEqual(database, "Database")
        self.assertIn("database_id=DB_ID(?)", sql)
        self.assertIn("program_name=N'OST Visualizer'", sql)
        self.assertIn("program_name LIKE N'OST Visualizer%'", sql)
        self.assertEqual(sql.count("?"), 1)
        self.assertIsInstance(
            common.active_application_sessions(connection, "Database"), int
        )


class SqlAdminEnvironmentValidationTests(unittest.TestCase):
    """load_environment value rules, with only the permission checks bypassed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_root = Path(self.tmp.name) / "state"
        self.state_root.mkdir()
        for target in (
            patch.object(common, "PRIVATE_STATE_ROOT", self.state_root),
            patch.object(common, "_require_private_root"),
            patch.object(common, "require_private_file"),
        ):
            target.start()
            self.addCleanup(target.stop)

    def write(self, overrides=None, text=None):
        content = (
            text
            if text is not None
            else _environment_with(self.state_root, overrides or {})
        )
        (self.state_root / ".env").write_text(content, encoding="utf-8")

    def test_valid_environment_loads_every_key_and_builds_the_deployment_config(self):
        self.write()
        values = common.load_environment()
        self.assertEqual(set(values), set(common.ENVIRONMENT_KEYS))
        self.assertEqual(len(values), 24)
        config = common.load_config()
        self.assertEqual(config.server, "sql.example.internal")
        self.assertEqual(config.port, 11433)
        self.assertEqual(config.database, "OSTVisualizer")
        self.assertEqual(config.admin_login, "OSTV_PROVISIONER")
        self.assertEqual(config.client_login, "OSTV_CLIENT")
        self.assertEqual(config.edition, "Express")
        self.assertEqual(config.container_name, "ostv-sql-test")
        self.assertEqual(
            config.secrets_directory, self.state_root / "secrets" / "container"
        )
        self.assertEqual(
            config.ownership_marker_file,
            self.state_root / "ownership" / "container-marker",
        )
        self.assertEqual(config.backup_host_directory, self.state_root / "backups")
        self.assertEqual(config.backup_sql_directory, Path("/var/opt/mssql/backup"))
        self.assertEqual(config.data_sql_directory, Path("/var/opt/mssql/data"))

    def test_comments_and_blank_lines_are_ignored(self):
        text = "# deployment\n\n   \n" + _environment_with(self.state_root, {})
        self.write(text=text)
        self.assertEqual(len(common.load_environment()), 24)

    def test_invalid_values_are_rejected_with_specific_messages(self):
        good_digest = "a" * 64
        cases = (
            ("state root", {"OSTV_STATE_ROOT": "/elsewhere"}, "must be exactly"),
            (
                "floating image tag",
                {"OSTV_SQL_IMAGE": "mcr.microsoft.com/mssql/server:latest"},
                "digest-pinned",
            ),
            (
                "foreign image",
                {
                    "OSTV_SQL_IMAGE": f"example.com/mssql/server:2025-CU7-ubuntu-24.04@sha256:{good_digest}"
                },
                "digest-pinned",
            ),
            (
                "old sql version",
                {
                    "OSTV_SQL_IMAGE": f"mcr.microsoft.com/mssql/server:2022-CU7-ubuntu-24.04@sha256:{good_digest}"
                },
                "digest-pinned",
            ),
            (
                "database identifier",
                {"OSTV_SQL_DATABASE": "bad name;"},
                "SQL identifier OSTV_SQL_DATABASE",
            ),
            (
                "admin identifier",
                {"OSTV_SQL_ADMIN_LOGIN": "1admin"},
                "SQL identifier OSTV_SQL_ADMIN_LOGIN",
            ),
            (
                "client identifier",
                {"OSTV_SQL_CLIENT_LOGIN": "a]b"},
                "SQL identifier OSTV_SQL_CLIENT_LOGIN",
            ),
            (
                "container name",
                {"OSTV_CONTAINER_NAME": "-bad"},
                "container name is invalid",
            ),
            (
                "docker network",
                {"OSTV_DOCKER_NETWORK": "bad net"},
                "Docker network name",
            ),
            ("edition", {"OSTV_SQL_EDITION": "Web"}, "edition is invalid"),
            (
                "wireguard interface",
                {"OSTV_WG_INTERFACE": "a" * 16},
                "interface name OSTV_WG_INTERFACE",
            ),
            (
                "public interface",
                {"OSTV_PUBLIC_INTERFACE": "eth 0"},
                "interface name OSTV_PUBLIC_INTERFACE",
            ),
            (
                "certificate name",
                {"OSTV_SQL_CERTIFICATE_NAME": "bad_name"},
                "certificate name",
            ),
            (
                "endpoint",
                {"OSTV_PUBLIC_ENDPOINT": "bad endpoint!"},
                "public WireGuard endpoint",
            ),
            ("host port zero", {"OSTV_SQL_HOST_PORT": "0"}, "port OSTV_SQL_HOST_PORT"),
            ("vpn port high", {"OSTV_SQL_VPN_PORT": "65536"}, "port OSTV_SQL_VPN_PORT"),
            (
                "public port text",
                {"OSTV_SQL_PUBLIC_PORT": "abc"},
                "port OSTV_SQL_PUBLIC_PORT",
            ),
            (
                "listen port negative",
                {"OSTV_WG_LISTEN_PORT": "-1"},
                "port OSTV_WG_LISTEN_PORT",
            ),
            (
                "deployment id",
                {"OSTV_DEPLOYMENT_ID": "not-a-uuid"},
                "invalid UUID, address, or subnet",
            ),
            (
                "wireguard prefix",
                {"OSTV_WG_PREFIX_LENGTH": "99"},
                "invalid UUID, address, or subnet",
            ),
            (
                "docker subnet host bits",
                {"OSTV_DOCKER_SUBNET": "172.29.240.1/24"},
                "invalid UUID, address, or subnet",
            ),
            (
                "private bind address",
                {"OSTV_SQL_PUBLIC_BIND_ADDRESS": "10.0.0.5"},
                "global IPv4 bind address",
            ),
            (
                "ipv6 bind address",
                {"OSTV_SQL_PUBLIC_BIND_ADDRESS": "2001:4860:4860::8888"},
                "global IPv4 bind address",
            ),
            (
                "source network",
                {"OSTV_SQL_ALLOWED_SOURCE_CIDR": "9.9.9.0/24"},
                "unique global IPv4 /32",
            ),
            (
                "private source",
                {"OSTV_SQL_ALLOWED_SOURCE_CIDR": "10.0.0.1/32"},
                "unique global IPv4 /32",
            ),
            (
                "duplicate source",
                {"OSTV_SQL_ALLOWED_SOURCE_CIDR": "9.9.9.9/32,9.9.9.9/32"},
                "unique global IPv4 /32",
            ),
            (
                "ipv6 source",
                {"OSTV_SQL_ALLOWED_SOURCE_CIDR": "2001:4860::1/128"},
                "unique global IPv4 /32",
            ),
            (
                "mixed families",
                {
                    "OSTV_DOCKER_SUBNET": "fd00::/64",
                    "OSTV_SQL_CONTAINER_ADDRESS": "fd00::10",
                },
                "same address family",
            ),
            (
                "wireguard network address",
                {"OSTV_WG_SERVER_ADDRESS": "10.250.240.0"},
                "server address is not usable",
            ),
            (
                "container outside subnet",
                {"OSTV_SQL_CONTAINER_ADDRESS": "172.30.0.10"},
                "not usable in the Docker subnet",
            ),
            (
                "container network address",
                {"OSTV_SQL_CONTAINER_ADDRESS": "172.29.240.0"},
                "not usable in the Docker subnet",
            ),
            (
                "overlapping subnets",
                {
                    "OSTV_DOCKER_SUBNET": "10.250.0.0/16",
                    "OSTV_SQL_CONTAINER_ADDRESS": "10.250.1.10",
                },
                "must not overlap",
            ),
            (
                "placeholder",
                {"OSTV_SQL_DATABASE": "<DATABASE>"},
                "unresolved placeholders",
            ),
            (
                "placeholder with real password",
                {
                    "OSTV_SQL_CERTIFICATE_NAME": "<NAME>",
                    "OSTV_SA_PASSWORD": "Real-Password-1",
                },
                "unresolved placeholders",
            ),
            (
                "unknown placeholder password",
                {"OSTV_SA_PASSWORD": "<OTHER>"},
                "unresolved placeholders",
            ),
            ("extra key", {"OSTV_EXTRA": "1"}, "invalid key set"),
            ("missing key", {"OSTV_SQL_VPN_PORT": None}, "invalid key set"),
            (
                "opening bracket only",
                {"OSTV_SQL_DATABASE": "a<b"},
                "unresolved placeholders",
            ),
            (
                "closing bracket only",
                {"OSTV_SQL_DATABASE": "a>b"},
                "unresolved placeholders",
            ),
            (
                "one valid and one private source",
                {"OSTV_SQL_ALLOWED_SOURCE_CIDR": "9.9.9.9/32,10.0.0.1/32"},
                "unique global IPv4 /32",
            ),
            (
                "global ipv6 network of prefix 32",
                {"OSTV_SQL_ALLOWED_SOURCE_CIDR": "2a00:1450::/32"},
                "unique global IPv4 /32",
            ),
            (
                "source with host bits",
                {"OSTV_SQL_ALLOWED_SOURCE_CIDR": "9.9.9.9/24"},
                "invalid UUID, address, or subnet",
            ),
            (
                "wireguard broadcast address",
                {"OSTV_WG_SERVER_ADDRESS": "10.250.240.255"},
                "server address is not usable",
            ),
            (
                "container broadcast address",
                {"OSTV_SQL_CONTAINER_ADDRESS": "172.29.240.255"},
                "not usable in the Docker subnet",
            ),
            (
                "port above range",
                {"OSTV_WG_LISTEN_PORT": "70000"},
                "port OSTV_WG_LISTEN_PORT",
            ),
            (
                "interface too long",
                {"OSTV_PUBLIC_INTERFACE": "a" * 16},
                "interface name",
            ),
            (
                "empty-looking endpoint",
                {"OSTV_PUBLIC_ENDPOINT": "-bad-"},
                "public WireGuard endpoint",
            ),
        )
        self.write()
        self.assertEqual(
            common.load_environment()["OSTV_SQL_DATABASE"], "OSTVisualizer"
        )
        for label, overrides, message in cases:
            with self.subTest(label):
                self.write(overrides)
                with self.assertRaisesRegex(RuntimeError, message):
                    common.load_environment()

    def test_port_boundaries_one_and_65535_are_accepted(self):
        ports = {
            "OSTV_SQL_HOST_PORT": "1",
            "OSTV_SQL_VPN_PORT": "65535",
            "OSTV_SQL_PUBLIC_PORT": "1",
            "OSTV_WG_LISTEN_PORT": "65535",
        }
        self.write(ports)
        values = common.load_environment()
        self.assertEqual({key: values[key] for key in ports}, ports)
        self.assertEqual(common.load_config().port, 1)

    def test_values_may_contain_equals_signs_only_the_first_one_splits_the_line(self):
        self.write({"OSTV_SA_PASSWORD": "Real=Password=1=="})
        self.assertEqual(
            common.load_environment()["OSTV_SA_PASSWORD"], "Real=Password=1=="
        )

    def test_generated_password_placeholder_and_real_password_are_both_accepted(self):
        self.write({"OSTV_SA_PASSWORD": "<GENERATED_BY_SETUP>"})
        self.assertEqual(
            common.load_environment()["OSTV_SA_PASSWORD"], "<GENERATED_BY_SETUP>"
        )
        self.write({"OSTV_SA_PASSWORD": "Real-Password-1"})
        self.assertEqual(
            common.load_environment()["OSTV_SA_PASSWORD"], "Real-Password-1"
        )

    def test_malformed_environment_lines_are_rejected_without_echoing_them(self):
        base = _environment_with(self.state_root, {})
        cases = {
            "no equals": base + "garbage-line\n",
            "duplicate key": base + "OSTV_SQL_DATABASE=Other\n",
            "empty value": base.replace(
                "OSTV_SQL_EDITION=Express", "OSTV_SQL_EDITION="
            ),
            "space in key": base + "BAD KEY=1\n",
            "empty key": base + "=1\n",
        }
        for label, text in cases.items():
            with self.subTest(label):
                self.write(text=text)
                with self.assertRaisesRegex(RuntimeError, "is malformed"):
                    common.load_environment()

    def test_unreadable_environment_file_is_reported_without_its_content(self):
        (self.state_root / ".env").write_bytes(b"\xff\xfe OSTV_SA_PASSWORD=secret")
        with self.assertRaisesRegex(RuntimeError, "unreadable") as raised:
            common.load_environment()
        self.assertNotIn("secret", str(raised.exception))

    def test_public_sources_accept_several_unique_global_hosts(self):
        self.write({"OSTV_SQL_ALLOWED_SOURCE_CIDR": "9.9.9.9/32,8.8.4.4/32,1.1.1.1/32"})
        self.assertEqual(
            common.load_environment()["OSTV_SQL_ALLOWED_SOURCE_CIDR"],
            "9.9.9.9/32,8.8.4.4/32,1.1.1.1/32",
        )

    def test_standard_public_sql_port_is_supported(self):
        self.write({"OSTV_SQL_HOST_PORT": "1433", "OSTV_SQL_PUBLIC_PORT": "1433"})
        values = common.load_environment()
        self.assertEqual(values["OSTV_SQL_HOST_PORT"], "1433")
        self.assertEqual(values["OSTV_SQL_PUBLIC_PORT"], "1433")
        self.assertEqual(common.load_config().port, 1433)

    def test_legacy_config_override_is_ignored(self):
        self.write()
        override = {"OSTV_SQL_CONFIG": str(self.state_root / "config/native.env")}
        with patch.dict(os.environ, override):
            first = common.load_config()
            second = common.load_config()
        self.assertEqual(first, second)
        self.assertEqual(first.container_name, "ostv-sql-test")
        self.assertEqual(
            first.secrets_directory, self.state_root / "secrets" / "container"
        )
