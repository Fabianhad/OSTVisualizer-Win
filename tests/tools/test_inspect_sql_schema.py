import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from ost_visualizer.domain.entities.database_descriptor import (
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.sql.errors import sql_schema_mismatch
from ost_visualizer.infrastructure.sql.schema_inspector import (
    SqlColumnInventory,
    SqlModuleInventory,
    SqlSchemaInventory,
)
from tests.infrastructure.sql.test_schema_validator import _canonical_inventory
from tests.paths import REPO_ROOT
from tools import inspect_sql_schema as tool

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PASSWORD = "env-only-test-password"


class InspectSqlSchemaDatabaseDescriptorTests(unittest.TestCase):
    def test_schema_inspection_tool_uses_canonical_certificate_default(self):
        root = REPO_ROOT
        tool_source = (root / "tools/inspect_sql_schema.py").read_text(encoding="utf-8")
        self.assertIn("SqlServerDatabaseLocation(", tool_source)
        self.assertNotIn("--trust-server-certificate", tool_source)
        self.assertNotIn("trust_server_certificate=", tool_source)


class InspectSqlSchemaScriptTests(unittest.TestCase):
    def test_the_script_finds_the_application_when_run_from_another_directory(self):
        # Runs only --help: argument parsing, no SQL driver call and no network.
        environment = {
            key: value for key, value in os.environ.items() if key != "PYTHONPATH"
        }
        with tempfile.TemporaryDirectory() as elsewhere:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "inspect_sql_schema.py"),
                    "--help",
                ],
                cwd=elsewhere,
                env=environment,
                capture_output=True,
                text=True,
                timeout=120,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--sql-auth", completed.stdout)
        self.assertIn("OSTV_SQL_PASSWORD", completed.stdout)
        self.assertNotIn("--password", completed.stdout)


class FakeInspector:
    """Stands in for SqlSchemaInspector; records the request, opens no connection."""

    calls = []
    inventory = None
    error = None

    def inspect(self, location, password=""):
        FakeInspector.calls.append((location, password))
        if FakeInspector.error is not None:
            raise FakeInspector.error
        return FakeInspector.inventory


def _inventory():
    return SqlSchemaInventory(
        database_guid="guid-1",
        schema_version=0,
        schema_checksum="",
        tables=frozenset(
            {("ostv", "B"), ("dbo", "A")}
            | {("dbo", f"T{number}") for number in range(8)}
        ),
        columns=(
            SqlColumnInventory("dbo", "A", "Id", "int", 4, 0, False, True, False),
        ),
        foreign_keys=(),
        indexes=(),
        views=(SqlModuleInventory("dbo", "V"),),
        triggers=(),
        procedures=(),
        functions=(),
    )


class InspectSqlSchemaMainTests(unittest.TestCase):
    def setUp(self):
        FakeInspector.calls = []
        FakeInspector.inventory = _inventory()
        FakeInspector.error = None

    def run_tool(self, argv, environment=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patch.object(sys, "argv", ["inspect_sql_schema.py", *argv])
            )
            stack.enter_context(patch.dict(os.environ))
            os.environ.pop("OSTV_SQL_PASSWORD", None)
            os.environ.update(environment or {})
            stack.enter_context(patch.object(tool, "SqlSchemaInspector", FakeInspector))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            code = tool.main()
        return code, out.getvalue(), err.getvalue()

    def test_windows_authentication_builds_the_canonical_location(self):
        code, out, err = self.run_tool(["--server", "srv", "--database", "db"])
        self.assertEqual((code, err), (0, ""))
        ((location, password),) = FakeInspector.calls
        self.assertEqual(
            location,
            SqlServerDatabaseLocation(
                server="srv",
                database="db",
                authentication_mode=SqlAuthenticationMode.WINDOWS,
                username="",
                connection_timeout_seconds=10,
            ),
        )
        self.assertEqual(password, "")
        self.assertTrue(location.encrypt)

    def test_sql_authentication_reads_the_password_only_from_the_environment(self):
        code, out, err = self.run_tool(
            [
                "--server",
                "srv",
                "--database",
                "db",
                "--sql-auth",
                "--username",
                "reader",
                "--connection-timeout",
                "7",
            ],
            {"OSTV_SQL_PASSWORD": PASSWORD},
        )
        self.assertEqual(code, 0)
        ((location, password),) = FakeInspector.calls
        self.assertEqual(password, PASSWORD)
        self.assertEqual(location.authentication_mode, SqlAuthenticationMode.SQL_SERVER)
        self.assertEqual(location.username, "reader")
        self.assertEqual(location.connection_timeout_seconds, 7)
        self.assertNotIn(PASSWORD, out + err + repr(location))

    def test_sql_authentication_requires_username_and_environment_password(self):
        base = ["--server", "srv", "--database", "db", "--sql-auth"]
        code, out, err = self.run_tool(base, {"OSTV_SQL_PASSWORD": PASSWORD})
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, "--username is required with --sql-auth.\n")
        code, out, err = self.run_tool(base + ["--username", "reader"])
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, "OSTV_SQL_PASSWORD is required with --sql-auth.\n")
        self.assertEqual(FakeInspector.calls, [])

    def test_passwords_and_certificate_trust_cannot_be_given_on_the_command_line(self):
        for extra in (
            ["--password", PASSWORD],
            ["--trust-server-certificate"],
            ["--trust-server-certificate", "true"],
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(SystemExit) as raised:
                    self.run_tool(["--server", "srv", "--database", "db", *extra])
                self.assertEqual(raised.exception.code, 2)
        self.assertEqual(FakeInspector.calls, [])

    def test_inspection_errors_print_only_the_message_and_exit_nonzero(self):
        FakeInspector.error = sql_schema_mismatch("Schema is not readable")
        code, out, err = self.run_tool(
            ["--server", "srv", "--database", "db", "--sql-auth", "--username", "u"],
            {"OSTV_SQL_PASSWORD": PASSWORD},
        )
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, "Schema is not readable\n")
        self.assertNotIn(PASSWORD, err)

    def test_inventory_is_printed_as_sorted_sanitized_json(self):
        code, out, err = self.run_tool(
            ["--server", "srv", "--database", "db", "--sql-auth", "--username", "u"],
            {"OSTV_SQL_PASSWORD": PASSWORD},
        )
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn(PASSWORD, out)
        self.assertEqual(
            out, json.dumps(json.loads(out), indent=2, sort_keys=True) + "\n"
        )
        payload = json.loads(out)
        self.assertEqual(
            set(payload),
            {
                "database_guid",
                "schema_version",
                "is_valid",
                "problems",
                "tables",
                "columns",
                "foreign_keys",
                "indexes",
                "views",
                "triggers",
                "procedures",
                "functions",
            },
        )
        self.assertEqual(payload["database_guid"], "guid-1")
        self.assertIs(payload["is_valid"], False)
        self.assertEqual(payload["problems"], ["ostv.DatabaseMetadata.SchemaVersion"])
        self.assertEqual(
            payload["tables"],
            [{"name": "A", "schema": "dbo"}]
            + [{"name": f"T{number}", "schema": "dbo"} for number in range(8)]
            + [{"name": "B", "schema": "ostv"}],
        )
        self.assertEqual(payload["columns"][0]["column_name"], "Id")
        self.assertEqual(payload["views"], [{"name": "V", "schema_name": "dbo"}])

    def test_a_canonical_inventory_is_reported_valid_with_every_collection_printed(
        self,
    ):
        inventory = _canonical_inventory()
        FakeInspector.inventory = inventory
        code, out, err = self.run_tool(
            ["--server", "srv", "--database", "db", "--sql-auth", "--username", "u"],
            {"OSTV_SQL_PASSWORD": PASSWORD},
        )
        self.assertEqual((code, err), (0, ""))
        payload = json.loads(out)
        self.assertIs(payload["is_valid"], True)
        self.assertEqual(payload["problems"], [])
        self.assertEqual(payload["schema_version"], inventory.schema_version)
        self.assertEqual(payload["database_guid"], inventory.database_guid)
        self.assertEqual(len(payload["tables"]), len(inventory.tables))
        for key in (
            "columns",
            "foreign_keys",
            "indexes",
            "views",
            "triggers",
            "procedures",
            "functions",
        ):
            with self.subTest(collection=key):
                self.assertEqual(len(payload[key]), len(getattr(inventory, key)))
        self.assertGreater(len(payload["columns"]), 100)
        self.assertNotIn(PASSWORD, out)

    def test_a_non_numeric_connection_timeout_is_rejected_by_the_parser(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_tool(
                ["--server", "srv", "--database", "db", "--connection-timeout", "soon"]
            )
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(FakeInspector.calls, [])

    def test_server_and_database_are_required_and_nothing_is_inspected_without_them(
        self,
    ):
        for argv in ([], ["--server", "srv"], ["--database", "db"]):
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit) as raised:
                    self.run_tool(argv)
                self.assertEqual(raised.exception.code, 2)
        self.assertEqual(FakeInspector.calls, [])


if __name__ == "__main__":
    unittest.main()
