import logging
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import Mock, patch
from ost_visualizer.infrastructure.mdb import database_creator
from ost_visualizer.infrastructure.mdb.schema_contract import DEFAULT_LAYER_ROWS


class DatabaseCreatorPersistenceTests(unittest.TestCase):
    def test_database_creator_closes_cursor_and_connection_on_schema_failure(self):
        class FakeCursor:
            def __init__(self):
                self.closed = False

            def execute(self, _sql):
                raise RuntimeError("ddl failed")

            def close(self):
                self.closed = True

        class FakeConnection:
            def __init__(self):
                self.cursor_instance = FakeCursor()
                self.rolled_back = False
                self.closed = False

            def cursor(self):
                return self.cursor_instance

            def rollback(self):
                self.rolled_back = True

            def close(self):
                self.closed = True

        fake_connection = FakeConnection()
        original_connect = database_creator.pyodbc.connect

        def connect(_connection_string, autocommit=False):
            self.assertFalse(autocommit)
            return fake_connection

        database_creator.pyodbc.connect = connect
        try:
            creator = database_creator.DatabaseCreator()
            with self.assertRaisesRegex(RuntimeError, "ddl failed"):
                creator._create_schema("test.mdb")
        finally:
            database_creator.pyodbc.connect = original_connect
        self.assertTrue(fake_connection.cursor_instance.closed)
        self.assertTrue(fake_connection.rolled_back)
        self.assertTrue(fake_connection.closed)

    def test_database_creator_preserves_schema_error_across_cleanup_failures(self):
        class FakeCursor:
            def execute(self, _sql):
                raise RuntimeError("ddl failed")

            def close(self):
                raise RuntimeError("cursor close failed")

        class FakeConnection:
            def __init__(self):
                self.closed = False

            def cursor(self):
                return FakeCursor()

            def rollback(self):
                raise RuntimeError("rollback failed")

            def close(self):
                self.closed = True

        fake_connection = FakeConnection()
        original_connect = database_creator.pyodbc.connect

        def connect(_connection_string, autocommit=False):
            self.assertFalse(autocommit)
            return fake_connection

        database_creator.pyodbc.connect = connect
        try:
            creator = database_creator.DatabaseCreator(
                logging.getLogger("test.database_creator.cleanup")
            )
            with self.assertLogs(creator._logger, level="ERROR"):
                with self.assertRaisesRegex(RuntimeError, "ddl failed"):
                    creator._create_schema("test.mdb")
        finally:
            database_creator.pyodbc.connect = original_connect
        self.assertTrue(fake_connection.closed)

    def test_database_creator_closes_connection_before_raising_cleanup_error(self):
        class FakeCursor:
            def execute(self, _sql):
                pass

            def close(self):
                raise RuntimeError("cursor close failed")

        class FakeConnection:
            def __init__(self):
                self.closed = False

            def cursor(self):
                return FakeCursor()

            def commit(self):
                pass

            def rollback(self):
                raise AssertionError("successful schema should not roll back")

            def close(self):
                self.closed = True

        fake_connection = FakeConnection()
        original_connect = database_creator.pyodbc.connect

        def connect(_connection_string, autocommit=False):
            self.assertFalse(autocommit)
            return fake_connection

        database_creator.pyodbc.connect = connect
        try:
            creator = database_creator.DatabaseCreator(
                logging.getLogger("test.database_creator.success_cleanup")
            )
            with self.assertLogs(creator._logger, level="ERROR"):
                with self.assertRaisesRegex(RuntimeError, "cursor close failed"):
                    creator._create_schema("test.mdb")
        finally:
            database_creator.pyodbc.connect = original_connect
        self.assertTrue(fake_connection.closed)

    def test_database_creator_preserves_metadata_error_when_dao_close_fails(self):
        class FakeDatabase:
            def TableDefs(self, _table_name):
                raise RuntimeError("metadata failed")

            def Close(self):
                raise RuntimeError("DAO close failed")

        engine = SimpleNamespace(OpenDatabase=lambda _path: FakeDatabase())
        creator = database_creator.DatabaseCreator(
            logging.getLogger("test.database_creator.dao_cleanup")
        )
        with patch("win32com.client.Dispatch", return_value=engine):
            with self.assertLogs(creator._logger, level="ERROR"):
                with self.assertRaisesRegex(RuntimeError, "metadata failed"):
                    creator._apply_reference_schema_metadata("test.mdb")

    def test_database_creator_uses_unique_argument_based_vbs_scripts(self):
        commands = []
        scripts = []

        def run(command, **_call_options):
            commands.append(command)
            script_path = Path(command[2])
            scripts.append((script_path, script_path.read_text(encoding="utf-8")))
            Path(command[3]).touch()
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp_dir:
            first_path = Path(tmp_dir) / "first;database.mdb"
            second_path = Path(tmp_dir) / "second.mdb"
            with patch.object(database_creator.subprocess, "run", side_effect=run):
                creator = database_creator.DatabaseCreator()
                creator._create_blank_mdb(first_path)
                creator._create_blank_mdb(second_path)
        self.assertNotEqual(commands[0][2], commands[1][2])
        self.assertEqual(commands[0][3], str(first_path))
        self.assertEqual(commands[1][3], str(second_path))
        for script_path, script in scripts:
            self.assertFalse(script_path.exists())
            self.assertIn("WScript.Arguments(0)", script)
            self.assertNotIn(str(first_path), script)
            self.assertNotIn(str(second_path), script)

    def test_database_creator_blank_mdb_failures_raise_and_remove_script(self):
        scripts = []

        def failing_run(command, **_call_options):
            scripts.append(Path(command[2]))
            return subprocess.CompletedProcess(command, 1, "", "provider missing")

        def silent_run(command, **_call_options):
            scripts.append(Path(command[2]))
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "blank.mdb"
            creator = database_creator.DatabaseCreator()
            with patch.object(
                database_creator.subprocess, "run", side_effect=failing_run
            ):
                with self.assertRaisesRegex(
                    RuntimeError, r"VBScript failed \(rc=1\): provider missing"
                ):
                    creator._create_blank_mdb(db_path)
            with patch.object(
                database_creator.subprocess, "run", side_effect=silent_run
            ):
                with self.assertRaisesRegex(RuntimeError, "MDB file was not created"):
                    creator._create_blank_mdb(db_path)
        self.assertEqual(len(scripts), 2)
        for script_path in scripts:
            self.assertFalse(script_path.exists())

    def test_database_creator_create_database_removes_partial_file_on_failure(self):
        class FailingCreator(database_creator.DatabaseCreator):
            def _create_blank_mdb(self, db_path):
                Path(db_path).touch()

            def _create_schema(
                self, db_path, progress_callback=None, *, seed_name=None
            ):
                raise RuntimeError("schema failed")

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "partial.mdb"
            creator = FailingCreator(logging.getLogger("test.database_creator.partial"))
            with self.assertLogs(creator._logger, level="ERROR"):
                self.assertFalse(creator.create_database(db_path, "Created"))
            self.assertFalse(db_path.exists())
            db_path.write_bytes(b"existing")
            self.assertFalse(creator.create_database(db_path, "Created"))
            self.assertEqual(db_path.read_bytes(), b"existing")

    def test_database_creator_reports_major_progress_stages(self):
        class FakeDatabaseCreator(database_creator.DatabaseCreator):
            def _create_blank_mdb(self, db_path):
                Path(db_path).touch()

            def _create_schema(
                self,
                db_path,
                progress_callback=None,
                *,
                seed_name=None,
            ):
                if seed_name != "Created":
                    raise AssertionError("database name was not forwarded to seeding")
                self._report_progress(progress_callback, "schema tables")
                self._report_progress(progress_callback, "schema field metadata")
                self._report_progress(progress_callback, "schema indexes")
                self._report_progress(progress_callback, "schema relationships")
                self._report_progress(progress_callback, "default data")

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "created.mdb"
            reports = []
            creator = FakeDatabaseCreator()
            self.assertTrue(
                creator.create_database(
                    db_path,
                    "Created",
                    progress_callback=reports.append,
                )
            )
        self.assertEqual(
            reports,
            [
                "database file",
                "schema tables",
                "schema field metadata",
                "schema indexes",
                "schema relationships",
                "default data",
                "finalizing",
            ],
        )

    def test_database_creator_schema_emits_every_stage_in_order_around_commits(self):
        events = []
        connection = Mock()
        connection.commit.side_effect = lambda: events.append("commit")
        engine = Mock()
        creator = database_creator.DatabaseCreator()
        with (
            patch.object(database_creator.pyodbc, "connect", return_value=connection),
            patch("win32com.client.Dispatch", return_value=engine),
        ):
            creator._create_schema(
                "test.mdb",
                progress_callback=events.append,
                seed_name="Created",
            )
        self.assertEqual(
            events,
            [
                "schema tables",
                "commit",
                "schema field metadata",
                "schema indexes",
                "schema relationships",
                "default data",
                "commit",
            ],
        )
        connection.rollback.assert_not_called()
        connection.close.assert_called_once()
        executed = [
            call.args[0]
            for call in connection.cursor.return_value.execute.call_args_list
        ]
        table_count = len(database_creator._TABLE_DDL)
        self.assertEqual(executed[:table_count], list(database_creator._TABLE_DDL))
        self.assertIn("INSERT INTO [Settings]", executed[table_count])

    def test_database_creator_reuses_one_odbc_connection_for_schema_and_seed(self):
        events = []
        connection = Mock()
        connection.cursor.return_value = Mock()
        connection.commit.side_effect = lambda: events.append("commit")
        creator = database_creator.DatabaseCreator()
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "created.mdb"

            def create_blank(path):
                Path(path).touch()

            with (
                patch.object(
                    creator,
                    "_create_blank_mdb",
                    side_effect=create_blank,
                ),
                patch.object(
                    creator,
                    "_apply_reference_schema_metadata",
                    side_effect=lambda *_args, **_kwargs: events.append("metadata"),
                ),
                patch.object(
                    database_creator.pyodbc,
                    "connect",
                    return_value=connection,
                ) as connect,
            ):
                self.assertTrue(creator.create_database(db_path, "Created"))
        connect.assert_called_once()
        connection.close.assert_called_once()
        connection.rollback.assert_not_called()
        self.assertEqual(events, ["commit", "metadata", "commit"])

    def test_database_creator_seeds_default_layers_from_schema_contract(self):
        class FakeCursor:
            def __init__(self):
                self.calls = []

            def execute(self, sql, *params):
                self.calls.append((sql, params))

            def close(self):
                pass

        class FakeConnection:
            def __init__(self):
                self.cursor_instance = FakeCursor()
                self.committed = False
                self.closed = False

            def cursor(self):
                return self.cursor_instance

            def commit(self):
                self.committed = True

            def rollback(self):
                raise AssertionError("seed data should not roll back")

            def close(self):
                self.closed = True

        fake_connection = FakeConnection()
        original_connect = database_creator.pyodbc.connect

        def connect(_connection_string, autocommit=False):
            self.assertFalse(autocommit)
            return fake_connection

        database_creator.pyodbc.connect = connect
        try:
            creator = database_creator.DatabaseCreator()
            creator._insert_seed_data("test.mdb", "Created")
        finally:
            database_creator.pyodbc.connect = original_connect
        layer_params = [
            params
            for sql, params in fake_connection.cursor_instance.calls
            if "INSERT INTO [BidLayers]" in sql
        ]
        self.assertEqual(
            layer_params,
            [
                (name, -1 if show else 0, -1 if locked else 0, sequence)
                for name, show, locked, sequence in DEFAULT_LAYER_ROWS
            ],
        )
        settings_params = [
            params
            for sql, params in fake_connection.cursor_instance.calls
            if "INSERT INTO [Settings]" in sql
        ]
        self.assertEqual(len(settings_params), 1)
        self.assertEqual(settings_params[0][0], "Created")
        schema_versions = [
            params
            for sql, params in fake_connection.cursor_instance.calls
            if "INSERT INTO [SchemaRegistry]" in sql
        ]
        self.assertEqual(
            schema_versions,
            [(version,) for version in database_creator.get_reference_seed_data()[0]],
        )
        self.assertTrue(fake_connection.committed)
        self.assertTrue(fake_connection.closed)


class DatabaseCreatorSequenceTests(unittest.TestCase):
    def test_creation_makes_the_folders_then_the_file_then_the_schema_in_order(self):
        events = []

        class Creator(database_creator.DatabaseCreator):
            def _create_blank_mdb(self, db_path):
                events.append("blank")
                Path(db_path).touch()

            def _create_schema(
                self, db_path, progress_callback=None, *, seed_name=None
            ):
                events.append(("schema", seed_name, progress_callback is not None))

        with tempfile.TemporaryDirectory() as tmp_dir:
            nested = Path(tmp_dir) / "a" / "b" / "created.mdb"
            self.assertTrue(Creator().create_database(nested, "Seeded", events.append))
            self.assertTrue(nested.is_file())
            existing = Path(tmp_dir) / "c.mdb"
            self.assertTrue(Creator().create_database(existing, "Again"))
            self.assertTrue(
                Creator().create_database(Path(tmp_dir) / "a" / "d.mdb", "Sibling")
            )
        self.assertEqual(
            events[:5],
            [
                "database file",
                "blank",
                ("schema", "Seeded", True),
                "finalizing",
                "blank",
            ],
        )

    def test_the_blank_database_script_is_run_hidden_with_a_timeout_and_captured_output(
        self,
    ):
        calls = []

        def run(command, **options):
            calls.append(
                (command, options, Path(command[2]).read_text(encoding="utf-8"))
            )
            Path(command[3]).touch()
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "x.mdb"
            with patch.object(database_creator.subprocess, "run", side_effect=run):
                database_creator.DatabaseCreator()._create_blank_mdb(target)
        command, options, script = calls[0]
        self.assertEqual(command[:2], ["cscript", "//NoLogo"])
        self.assertEqual(command[3], str(target))
        self.assertEqual(options, {"capture_output": True, "text": True, "timeout": 15})
        self.assertIn("ADOX.Catalog", script)
        self.assertIn("Jet OLEDB:Engine Type=5", script)

    def test_a_script_that_cannot_be_removed_is_logged_without_hiding_the_result(self):
        def run(command, **_options):
            Path(command[3]).touch()
            return subprocess.CompletedProcess(command, 0, "", "")

        creator = database_creator.DatabaseCreator(logging.getLogger("creator.script"))
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(database_creator.subprocess, "run", side_effect=run):
                with patch.object(Path, "unlink", side_effect=PermissionError("busy")):
                    with self.assertLogs("creator.script", level="ERROR") as logs:
                        creator._create_blank_mdb(Path(tmp_dir) / "x.mdb")
        self.assertIn("Failed to remove temporary MDB creation script", logs.output[0])

    def test_seed_rows_are_written_in_dependency_order_with_the_default_project(self):
        calls = []

        class Cursor:
            def execute(self, sql, *params):
                calls.append((sql.split("]")[0].split("[")[-1], params))

        database_creator.DatabaseCreator()._insert_seed_rows(Cursor(), "Created")
        tables = [table for table, _params in calls]
        self.assertEqual(
            tables,
            ["Settings", "BidProjects"]
            + ["BidLayers"] * len(DEFAULT_LAYER_ROWS)
            + ["SchemaRegistry"] * len(database_creator._SCHEMA_VERSIONS),
        )
        self.assertEqual(calls[1], ("BidProjects", ("Deleted Bids",)))
        self.assertEqual(calls[0][1][0], "Created")

    def test_default_layers_are_stored_with_access_boolean_values(self):
        calls = []

        class Cursor:
            def execute(self, sql, *params):
                if "BidLayers" in sql:
                    calls.append(params)

        creator = database_creator.DatabaseCreator()
        with patch.object(
            database_creator,
            "_DEFAULT_LAYERS",
            (("Shown", True, False, 4), ("Hidden", False, True, 5)),
        ):
            creator._insert_seed_rows(Cursor(), "Created")
        self.assertEqual(calls, [("Shown", -1, 0, 4), ("Hidden", 0, -1, 5)])

    def test_a_failed_rollback_is_logged_and_never_raised(self):
        creator = database_creator.DatabaseCreator(
            logging.getLogger("creator.rollback")
        )
        connection = Mock()
        connection.rollback.side_effect = RuntimeError("gone")
        with self.assertLogs("creator.rollback", level="ERROR") as logs:
            creator._rollback_connection(connection, "schema creation")
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(
            logs.records[0].getMessage(), "Failed to roll back MDB schema creation"
        )

    def test_closing_failures_surface_only_when_the_operation_itself_succeeded(self):
        creator = database_creator.DatabaseCreator(logging.getLogger("creator.close"))
        cursor = Mock()
        cursor.close.side_effect = RuntimeError("cursor stuck")
        connection = Mock()
        with self.assertLogs("creator.close", level="ERROR"):
            with self.assertRaisesRegex(RuntimeError, "cursor stuck"):
                creator._close_odbc_resources(
                    cursor, connection, "seed", suppress_errors=False
                )
        connection.close.assert_called_once_with()
        with self.assertLogs("creator.close", level="ERROR"):
            creator._close_odbc_resources(
                cursor, connection, "seed", suppress_errors=True
            )
        creator._close_odbc_resources(None, None, "seed", suppress_errors=False)
        database = Mock()
        database.Close.side_effect = RuntimeError("dao stuck")
        with self.assertLogs("creator.close", level="ERROR"):
            with self.assertRaisesRegex(RuntimeError, "dao stuck"):
                creator._close_dao_database(database, suppress_errors=False)
            creator._close_dao_database(database, suppress_errors=True)

    def test_a_close_failure_after_a_successful_seed_or_metadata_run_is_raised(self):
        creator = database_creator.DatabaseCreator(logging.getLogger("creator.success"))
        connection = Mock()
        connection.close.side_effect = RuntimeError("close failed")
        with patch.object(database_creator.pyodbc, "connect", return_value=connection):
            with self.assertLogs("creator.success", level="ERROR"):
                with self.assertRaisesRegex(RuntimeError, "close failed"):
                    creator._insert_seed_data("x.mdb", "Created")
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        engine = Mock()
        engine.OpenDatabase.return_value.Close.side_effect = RuntimeError(
            "dao close failed"
        )
        with patch("win32com.client.Dispatch", return_value=engine):
            with self.assertLogs("creator.success", level="ERROR"):
                with self.assertRaisesRegex(RuntimeError, "dao close failed"):
                    creator._apply_reference_schema_metadata("x.mdb")

    def test_reference_metadata_is_applied_through_dao_exactly_as_the_contract_says(
        self,
    ):
        class Collection:
            def __init__(self):
                self.items = []

            def Append(self, item):
                self.items.append(item)

        class Field:
            def __init__(self, name):
                self.Name = name
                self.Required = None
                self.DefaultValue = None
                self.ForeignName = None

        class Index:
            def __init__(self, name):
                self.Name = name
                self.Unique = None
                self.Fields = Collection()

            def CreateField(self, column):
                return Field(column)

        class Table:
            def __init__(self):
                self.fields = {}
                self.Indexes = Collection()

            def Fields(self, name):
                return self.fields.setdefault(name, Field(name))

            def CreateIndex(self, name):
                return Index(name)

        class Relation:
            def __init__(self, name, parent, child, attributes):
                self.args = (name, parent, child, attributes)
                self.Fields = Collection()

            def CreateField(self, name):
                return Field(name)

        class Database:
            def __init__(self):
                self.tables = {}
                self.Relations = Collection()
                self.closed = 0

            def TableDefs(self, name):
                return self.tables.setdefault(name, Table())

            def CreateRelation(self, *args):
                return Relation(*args)

            def Close(self):
                self.closed += 1

        database = Database()
        engine = Mock()
        engine.OpenDatabase.return_value = database
        stages = []
        with patch("win32com.client.Dispatch", return_value=engine):
            database_creator.DatabaseCreator()._apply_reference_schema_metadata(
                "x.mdb", stages.append
            )
        engine.OpenDatabase.assert_called_once_with("x.mdb")
        self.assertEqual(
            stages,
            ["schema field metadata", "schema indexes", "schema relationships"],
        )
        for table in database_creator.UID_REQUIRED_TABLES:
            self.assertIs(database.tables[table].fields["UID"].Required, True, table)
        for (table, field), default in database_creator.FIELD_DEFAULTS.items():
            self.assertEqual(database.tables[table].fields[field].DefaultValue, default)
        for table, name, unique, columns in database_creator.EXPLICIT_INDEXES:
            matching = [
                i for i in database.tables[table].Indexes.items if i.Name == name
            ]
            self.assertEqual(len(matching), 1, name)
            self.assertIs(matching[0].Unique, bool(unique))
            self.assertEqual([f.Name for f in matching[0].Fields.items], list(columns))
        self.assertEqual(
            [
                (r.args, [(f.Name, f.ForeignName) for f in r.Fields.items])
                for r in database.Relations.items
            ],
            [
                ((name, parent, child, 0), [(parent_column, child_column)])
                for name, child, child_column, parent, parent_column in (
                    database_creator.REFERENCE_RELATIONSHIPS
                )
            ],
        )
        self.assertEqual(database.closed, 1)
