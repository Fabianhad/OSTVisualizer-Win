import json
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


class DatabaseCreatorConnectionTargetTests(unittest.TestCase):
    """The ODBC connection string and the stored name are assembled from the
    arguments; fakes of the driver would hide a wrong target, so they are asserted."""

    DRIVER = "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"

    @staticmethod
    def _settings_inserts(cursor):
        return [
            call
            for call in cursor.execute.call_args_list
            if "INSERT INTO [Settings]" in call.args[0]
        ]

    def _create(self, name):
        creator = database_creator.DatabaseCreator()
        connection = Mock()
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "created.mdb"
            with (
                patch.object(
                    creator,
                    "_create_blank_mdb",
                    side_effect=lambda path: Path(path).touch(),
                ),
                patch.object(creator, "_apply_reference_schema_metadata"),
                patch.object(
                    database_creator.pyodbc, "connect", return_value=connection
                ) as connect,
            ):
                self.assertIs(creator.create_database(db_path, name), True)
        return db_path, connect, connection

    def test_the_schema_connection_targets_the_new_file_without_autocommit(self):
        db_path, connect, _connection = self._create("Created")
        connect.assert_called_once_with(
            self.DRIVER + f"DBQ={db_path};", autocommit=False
        )

    def test_the_requested_database_name_is_stored_in_settings(self):
        _path, _connect, connection = self._create("Quarry Job 7")
        inserts = self._settings_inserts(connection.cursor.return_value)
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0].args[1], "Quarry Job 7")

    def test_the_unseeded_schema_connection_also_targets_the_file(self):
        creator = database_creator.DatabaseCreator()
        connection = Mock()
        target = Path("C:/data/unseeded.mdb")
        with (
            patch.object(creator, "_apply_reference_schema_metadata"),
            patch.object(
                database_creator.pyodbc, "connect", return_value=connection
            ) as connect,
        ):
            creator._create_schema(target)
        connect.assert_called_once_with(
            self.DRIVER + f"DBQ={target};", autocommit=False
        )
        self.assertEqual(self._settings_inserts(connection.cursor.return_value), [])

    def test_the_standalone_seed_connection_targets_the_given_file_and_name(self):
        creator = database_creator.DatabaseCreator()
        connection = Mock()
        target = Path("C:/data/seeded.mdb")
        with patch.object(
            database_creator.pyodbc, "connect", return_value=connection
        ) as connect:
            creator._insert_seed_data(target, "Seeded")
        connect.assert_called_once_with(
            self.DRIVER + f"DBQ={target};", autocommit=False
        )
        inserts = self._settings_inserts(connection.cursor.return_value)
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0].args[1], "Seeded")


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
        removal_attempts = []

        def refuse_removal(path, **options):
            removal_attempts.append((path, options))
            raise PermissionError("busy")

        # The script file is created in tempfile's directory and, because its
        # removal is refused here, would stay behind: keep it inside this test's
        # own folder, which is deleted at the end.
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(tempfile, "tempdir", tmp_dir):
                with patch.object(database_creator.subprocess, "run", side_effect=run):
                    with patch.object(
                        Path, "unlink", autospec=True, side_effect=refuse_removal
                    ):
                        with self.assertLogs("creator.script", level="ERROR") as logs:
                            creator._create_blank_mdb(Path(tmp_dir) / "x.mdb")
            scripts = sorted(Path(tmp_dir).glob("ost_create_mdb_*.vbs"))
            self.assertEqual(len(scripts), 1)
            self.assertEqual(removal_attempts, [(scripts[0], {"missing_ok": True})])
            self.assertEqual(len(logs.records), 1)
            self.assertEqual(
                logs.records[0].getMessage(),
                f"Failed to remove temporary MDB creation script {scripts[0]}",
            )
            self.assertTrue((Path(tmp_dir) / "x.mdb").is_file())

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


_GOLDEN_DDL = Path(__file__).with_name("access_reference_ddl_golden.json")
_SETTINGS_INSERT = (
    "INSERT INTO [Settings] ([Name], [Created], [NextBidNo], "
    "[LoginRequired], [MeasureBase], [PriceUsing], "
    "[QuantitiesInLegend], [HoursPerDay], [StartWeekOn], "
    "[GridCountMethod], [TakeoffIncrements], [ScaleStyle], "
    "[IsCustomScale], [ScaleFactor1], [ScaleFactor2], "
    "[PageScale], [PageWidth], [PageHeight], "
    "[LabelHours1], [LabelHours2], [LabelHours3], [LabelHours4], "
    "[IgnoreBidAreas], [SendImageFiles], "
    "[BackupNo], [BackupPeriod], [CompressPeriod]) "
    "VALUES (?, ?, 1, 0, 0, 0, -1, 8, 0, 0, 1.0, 1, 0, "
    "0.125, 12.0, 1.0, 42.0, 30.0, "
    "'Regular', 'Overtime', 'Time + 1/2', 'Double', "
    "0, 0, 2, 2, 2)"
)


class DatabaseCreatorReferenceContractTests(unittest.TestCase):
    @staticmethod
    def golden_tables():
        return json.loads(_GOLDEN_DDL.read_text(encoding="utf-8"))["tables"]

    def test_every_table_ddl_matches_the_reviewed_snapshot_text_exactly(self):
        golden = self.golden_tables()
        rebuilt = [
            "CREATE TABLE [%s] (\n%s\n    )"
            % (
                name,
                ",\n".join(f"        [{column}] {kind}" for column, kind in columns),
            )
            for name, columns in golden
        ]
        self.assertEqual(len(golden), 64)
        self.assertEqual(sum(len(columns) for _name, columns in golden), 668)
        self.assertEqual(database_creator._TABLE_DDL, rebuilt)

    def test_the_reference_schema_model_is_built_from_exactly_those_tables(self):
        golden = self.golden_tables()
        model = database_creator.get_reference_schema_model()
        self.assertEqual(model.table_names, frozenset(name for name, _ in golden))
        self.assertEqual(model.column_count, 668)
        for name, columns in golden:
            self.assertEqual(
                [column.name for column in model.table(name).columns],
                [column for column, _kind in columns],
                name,
            )
        self.assertEqual(model.table("Bids").columns[0].name, "UID")
        self.assertIs(model.table("Bids").columns[0].primary_key, True)

    def test_the_registered_schema_versions_are_exactly_the_supported_release_list(
        self,
    ):
        expected = [
            86,
            87,
            88,
            89,
            90,
            91,
            94,
            95,
            96,
            97,
            98,
            99,
            100,
            101,
            102,
            103,
            104,
            105,
            106,
            107,
            108,
            109,
            110,
            111,
            112,
            113,
        ]
        self.assertEqual(database_creator._SCHEMA_VERSIONS, expected)
        versions, layers = database_creator.get_reference_seed_data()
        self.assertEqual(versions, tuple(expected))
        self.assertEqual(layers, tuple(DEFAULT_LAYER_ROWS))

    def test_seed_rows_use_the_exact_sql_and_parameters(self):
        calls = []

        class Cursor:
            def execute(self, sql, *params):
                calls.append((sql, params))

        created = database_creator.datetime(2026, 1, 2, 3, 4, 5)
        with patch.object(database_creator, "datetime") as clock:
            clock.now.return_value = created
            database_creator.DatabaseCreator()._insert_seed_rows(Cursor(), "My Bid DB")
        layers = [
            (
                "INSERT INTO [BidLayers] "
                "([IsTemplate], [Name], [Show], [IsLocked], [Sequence]) "
                "VALUES (-1, ?, ?, ?, ?)",
                (name, -1 if show else 0, -1 if locked else 0, sequence),
            )
            for name, show, locked, sequence in DEFAULT_LAYER_ROWS
        ]
        registry = [
            (
                "INSERT INTO [SchemaRegistry] ([Version], [Product]) VALUES (?, 2)",
                (version,),
            )
            for version in (86, 87, 88, 89, 90, 91, 94, 95, 96, 97, 98, 99, 100)
            + (101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113)
        ]
        self.assertEqual(
            calls,
            [
                (_SETTINGS_INSERT, ("My Bid DB", created)),
                ("INSERT INTO [BidProjects] ([Name]) VALUES (?)", ("Deleted Bids",)),
            ]
            + layers
            + registry,
        )


class DatabaseCreatorBlankDatabaseTests(unittest.TestCase):
    def test_the_blank_database_script_text_and_file_name_are_exact(self):
        captured = []

        def run(command, **_options):
            script = Path(command[2])
            captured.append((script.name, script.read_text(encoding="utf-8")))
            Path(command[3]).touch()
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(database_creator.subprocess, "run", side_effect=run):
                database_creator.DatabaseCreator()._create_blank_mdb(
                    Path(tmp_dir) / "x.mdb"
                )
        name, script = captured[0]
        self.assertRegex(name, r"^ost_create_mdb_[a-z0-9_]{8}\.vbs$")
        self.assertEqual(
            script,
            "dbPath = WScript.Arguments(0)\n"
            'Set cat = CreateObject("ADOX.Catalog")\n'
            'cat.Create "Provider=Microsoft.ACE.OLEDB.12.0;Data Source=" '
            '& Chr(34) & dbPath & Chr(34) & ";Jet OLEDB:Engine Type=5;"\n'
            "Set cat = Nothing\n",
        )

    def test_a_missing_file_after_a_clean_exit_is_reported_with_the_exact_message(
        self,
    ):
        def run(command, **_options):
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(database_creator.subprocess, "run", side_effect=run):
                with self.assertRaises(RuntimeError) as raised:
                    database_creator.DatabaseCreator()._create_blank_mdb(
                        Path(tmp_dir) / "x.mdb"
                    )
        self.assertEqual(
            str(raised.exception), "VBScript completed but MDB file was not created"
        )

    def test_a_script_that_already_vanished_is_not_reported_as_a_cleanup_failure(self):
        def run(command, **_options):
            Path(command[2]).unlink()
            Path(command[3]).touch()
            return subprocess.CompletedProcess(command, 0, "", "")

        creator = database_creator.DatabaseCreator(logging.getLogger("creator.vanish"))
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(database_creator.subprocess, "run", side_effect=run):
                with self.assertNoLogs("creator.vanish", level="ERROR"):
                    creator._create_blank_mdb(Path(tmp_dir) / "x.mdb")

    def test_a_cscript_timeout_removes_the_script_and_propagates(self):
        scripts = []

        def run(command, **_options):
            scripts.append(Path(command[2]))
            raise subprocess.TimeoutExpired(command, 15)

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(database_creator.subprocess, "run", side_effect=run):
                with self.assertRaises(subprocess.TimeoutExpired):
                    database_creator.DatabaseCreator()._create_blank_mdb(
                        Path(tmp_dir) / "x.mdb"
                    )
        self.assertEqual(len(scripts), 1)
        self.assertFalse(scripts[0].exists())


class DatabaseCreatorFailureAtomicityTests(unittest.TestCase):
    class Connection:
        def __init__(self, events, execute_error=None, close_error=None):
            self.events = events
            self.cursor_instance = Mock()
            self.cursor_instance.close.side_effect = lambda: events.append(
                "cursor-close"
            )
            self.statements = []
            if execute_error is not None:
                self.cursor_instance.execute.side_effect = execute_error
            else:
                self.cursor_instance.execute.side_effect = self.statements.append
            self.close_error = close_error

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            self.events.append("commit")

        def rollback(self):
            self.events.append("rollback")

        def close(self):
            self.events.append("close")
            if self.close_error is not None:
                raise self.close_error

    def creator(self, name):
        return database_creator.DatabaseCreator(logging.getLogger(name))

    def test_a_metadata_failure_rolls_back_closes_and_never_seeds(self):
        events = []
        connection = self.Connection(events)
        creator = self.creator("creator.atomic.metadata")
        with (
            patch.object(database_creator.pyodbc, "connect", return_value=connection),
            patch.object(
                creator,
                "_apply_reference_schema_metadata",
                side_effect=RuntimeError("dao metadata failed"),
            ),
            patch.object(creator, "_insert_seed_rows") as seed,
        ):
            with self.assertRaisesRegex(RuntimeError, "dao metadata failed"):
                creator._create_schema("x.mdb", seed_name="Created")
        seed.assert_not_called()
        self.assertEqual(events, ["commit", "rollback", "cursor-close", "close"])

    def test_a_seed_failure_after_metadata_rolls_back_the_seed_transaction(self):
        events = []
        connection = self.Connection(events)
        creator = self.creator("creator.atomic.seed")
        with (
            patch.object(database_creator.pyodbc, "connect", return_value=connection),
            patch.object(creator, "_apply_reference_schema_metadata"),
            patch.object(
                creator, "_insert_seed_rows", side_effect=ValueError("seed failed")
            ),
        ):
            with self.assertRaisesRegex(ValueError, "seed failed"):
                creator._create_schema("x.mdb", seed_name="Created")
        self.assertEqual(events, ["commit", "rollback", "cursor-close", "close"])

    def test_a_failed_first_commit_skips_metadata_and_seed_entirely(self):
        events = []
        connection = self.Connection(events)
        connection.commit = lambda: (_ for _ in ()).throw(
            RuntimeError("commit refused")
        )
        creator = self.creator("creator.atomic.commit")
        with (
            patch.object(database_creator.pyodbc, "connect", return_value=connection),
            patch.object(creator, "_apply_reference_schema_metadata") as metadata,
            patch.object(creator, "_insert_seed_rows") as seed,
        ):
            with self.assertRaisesRegex(RuntimeError, "commit refused"):
                creator._create_schema("x.mdb", seed_name="Created")
        metadata.assert_not_called()
        seed.assert_not_called()
        self.assertEqual(events, ["rollback", "cursor-close", "close"])

    def test_without_a_seed_name_metadata_is_applied_after_the_connection_closes(self):
        events = []
        connection = self.Connection(events)
        creator = self.creator("creator.atomic.noseed")
        with (
            patch.object(database_creator.pyodbc, "connect", return_value=connection),
            patch.object(
                creator,
                "_apply_reference_schema_metadata",
                side_effect=lambda path, progress_callback=None: events.append(
                    ("metadata", path, progress_callback)
                ),
            ),
            patch.object(creator, "_insert_seed_rows") as seed,
        ):
            creator._create_schema("x.mdb", progress_callback=events.append)
        seed.assert_not_called()
        self.assertEqual(
            events[:-1],
            ["schema tables", "commit", "cursor-close", "close"],
        )
        self.assertEqual(events[-1][:2], ("metadata", "x.mdb"))
        self.assertEqual(events[-1][2], events.append)

    def test_schema_failure_log_messages_name_the_schema_creation_operation(self):
        events = []
        connection = self.Connection(events, execute_error=RuntimeError("ddl failed"))
        connection.rollback = Mock(side_effect=RuntimeError("rollback failed"))
        connection.cursor_instance.close.side_effect = RuntimeError("cursor stuck")
        connection.close = Mock(side_effect=RuntimeError("connection stuck"))
        creator = self.creator("creator.atomic.labels")
        with patch.object(database_creator.pyodbc, "connect", return_value=connection):
            with self.assertLogs("creator.atomic.labels", level="ERROR") as logs:
                with self.assertRaisesRegex(RuntimeError, "ddl failed"):
                    creator._create_schema("x.mdb", seed_name="Created")
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Failed to roll back MDB schema creation",
                "Failed to close MDB cursor after schema creation",
                "Failed to close MDB connection after schema creation",
            ],
        )
        connection.close.assert_called_once_with()

    def test_a_cursor_that_never_opened_does_not_stop_the_connection_closing(self):
        creator = self.creator("creator.atomic.cursorless")
        connection = Mock()
        creator._close_odbc_resources(None, connection, "seed", suppress_errors=False)
        connection.close.assert_called_once_with()

    def test_resource_close_log_messages_name_the_resource_and_operation(self):
        creator = self.creator("creator.atomic.resources")
        cursor = Mock()
        cursor.close.side_effect = RuntimeError("a")
        connection = Mock()
        connection.close.side_effect = RuntimeError("b")
        with self.assertLogs("creator.atomic.resources", level="ERROR") as logs:
            with self.assertRaisesRegex(RuntimeError, "^a$"):
                creator._close_odbc_resources(
                    cursor, connection, "seed", suppress_errors=False
                )
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Failed to close MDB cursor after seed",
                "Failed to close MDB connection after seed",
            ],
        )

    def test_a_seed_failure_keeps_the_original_error_over_a_failing_close(self):
        events = []
        connection = self.Connection(
            events,
            execute_error=ValueError("insert failed"),
            close_error=RuntimeError("close failed"),
        )
        creator = self.creator("creator.atomic.seeddata")
        with patch.object(database_creator.pyodbc, "connect", return_value=connection):
            with self.assertLogs("creator.atomic.seeddata", level="ERROR") as logs:
                with self.assertRaisesRegex(ValueError, "insert failed"):
                    creator._insert_seed_data("x.mdb", "Created")
        self.assertEqual(events, ["rollback", "cursor-close", "close"])
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Failed to close MDB connection after seed-data insertion"],
        )

    def test_a_failed_seed_rollback_is_labelled_as_seed_data_insertion(self):
        connection = Mock()
        connection.cursor.return_value.execute.side_effect = ValueError("insert failed")
        connection.rollback.side_effect = RuntimeError("rollback failed")
        creator = self.creator("creator.atomic.seedrollback")
        with patch.object(database_creator.pyodbc, "connect", return_value=connection):
            with self.assertLogs("creator.atomic.seedrollback", level="ERROR") as logs:
                with self.assertRaisesRegex(ValueError, "insert failed"):
                    creator._insert_seed_data("x.mdb", "Created")
        connection.rollback.assert_called_once_with()
        self.assertEqual(
            logs.records[0].getMessage(), "Failed to roll back MDB seed-data insertion"
        )

    def test_dao_is_opened_through_the_dao_120_engine_for_the_given_file(self):
        engine = Mock()
        engine.OpenDatabase.return_value = SimpleNamespace(
            TableDefs=lambda _name: (_ for _ in ()).throw(RuntimeError("stop")),
            Close=Mock(),
        )
        creator = self.creator("creator.atomic.dao")
        with patch("win32com.client.Dispatch", return_value=engine) as dispatch:
            with self.assertRaisesRegex(RuntimeError, "stop"):
                creator._apply_reference_schema_metadata(Path("some.mdb"))
        dispatch.assert_called_once_with("DAO.DBEngine.120")
        engine.OpenDatabase.assert_called_once_with("some.mdb")
        engine.OpenDatabase.return_value.Close.assert_called_once_with()

    def test_a_dao_failure_during_creation_removes_the_half_built_database(self):
        class Creator(database_creator.DatabaseCreator):
            def _create_blank_mdb(self, db_path):
                Path(db_path).write_bytes(b"blank")

            def _create_schema(
                self, db_path, progress_callback=None, *, seed_name=None
            ):
                self._report_progress(progress_callback, "schema tables")
                raise RuntimeError("dao metadata failed")

        reports = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "half.mdb"
            creator = Creator(logging.getLogger("creator.atomic.half"))
            with self.assertLogs("creator.atomic.half", level="ERROR") as logs:
                result = creator.create_database(db_path, "Half", reports.append)
            self.assertIs(result, False)
            self.assertFalse(db_path.exists())
            self.assertEqual(list(Path(tmp_dir).iterdir()), [])
        self.assertEqual(reports, ["database file", "schema tables"])
        self.assertIn("Failed to create database", logs.output[0])
        self.assertIn("dao metadata failed", logs.output[0])

    def test_an_undeletable_partial_file_does_not_hide_the_failure_result(self):
        class Creator(database_creator.DatabaseCreator):
            def _create_blank_mdb(self, db_path):
                Path(db_path).write_bytes(b"blank")

            def _create_schema(
                self, db_path, progress_callback=None, *, seed_name=None
            ):
                raise RuntimeError("schema failed")

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "stuck.mdb"
            creator = Creator(logging.getLogger("creator.atomic.stuck"))
            with patch.object(Path, "unlink", side_effect=PermissionError("locked")):
                with self.assertLogs("creator.atomic.stuck", level="ERROR"):
                    result = creator.create_database(db_path, "Stuck")
            self.assertIs(result, False)
            self.assertEqual(db_path.read_bytes(), b"blank")

    def test_an_existing_database_is_never_touched_or_recreated(self):
        creator = self.creator("creator.atomic.exists")
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "keep.mdb"
            db_path.write_bytes(b"precious")
            with (
                patch.object(creator, "_create_blank_mdb") as blank,
                patch.object(creator, "_create_schema") as schema,
            ):
                self.assertIs(creator.create_database(db_path, "Again"), False)
            blank.assert_not_called()
            schema.assert_not_called()
            self.assertEqual(db_path.read_bytes(), b"precious")


class DatabaseCreatorInterruptTests(unittest.TestCase):
    """KeyboardInterrupt and SystemExit are not Exception: they must still clean up."""

    INTERRUPTS = (KeyboardInterrupt, SystemExit)

    class Connection:
        def __init__(self, events):
            self.events = events
            self.cursor_instance = Mock()
            self.cursor_instance.close.side_effect = lambda: events.append(
                "cursor-close"
            )

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            self.events.append("commit")

        def rollback(self):
            self.events.append("rollback")

        def close(self):
            self.events.append("close")

    class StubBlankCreator(database_creator.DatabaseCreator):
        def _create_blank_mdb(self, db_path):
            Path(db_path).write_bytes(b"blank")

    def test_an_interrupt_during_schema_creation_removes_the_half_built_file(self):
        for interrupt in self.INTERRUPTS:
            with self.subTest(interrupt=interrupt.__name__):

                class Creator(self.StubBlankCreator):
                    def _create_schema(
                        self, db_path, progress_callback=None, *, seed_name=None
                    ):
                        raise interrupt()

                with tempfile.TemporaryDirectory() as tmp_dir:
                    db_path = Path(tmp_dir) / "half.mdb"
                    creator = Creator(logging.getLogger("creator.interrupt.half"))
                    with self.assertRaises(interrupt):
                        creator.create_database(db_path, "Half")
                    self.assertFalse(db_path.exists())
                    self.assertEqual(list(Path(tmp_dir).iterdir()), [])

    def test_an_interrupt_is_propagated_without_being_logged_as_a_failed_creation(
        self,
    ):
        class Creator(self.StubBlankCreator):
            def _create_schema(
                self, db_path, progress_callback=None, *, seed_name=None
            ):
                raise KeyboardInterrupt()

        with tempfile.TemporaryDirectory() as tmp_dir:
            creator = Creator(logging.getLogger("creator.interrupt.quiet"))
            with self.assertNoLogs("creator.interrupt.quiet", level="ERROR"):
                with self.assertRaises(KeyboardInterrupt):
                    creator.create_database(Path(tmp_dir) / "q.mdb", "Quiet")

    def test_an_interrupt_still_propagates_when_the_partial_file_cannot_be_removed(
        self,
    ):
        class Creator(self.StubBlankCreator):
            def _create_schema(
                self, db_path, progress_callback=None, *, seed_name=None
            ):
                raise KeyboardInterrupt()

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "stuck.mdb"
            creator = Creator(logging.getLogger("creator.interrupt.stuck"))
            with patch.object(Path, "unlink", side_effect=PermissionError("locked")):
                with self.assertRaises(KeyboardInterrupt):
                    creator.create_database(db_path, "Stuck")
            self.assertEqual(db_path.read_bytes(), b"blank")

    def test_an_interrupt_while_seeding_releases_the_odbc_resources_and_the_file(
        self,
    ):
        events = []
        connection = self.Connection(events)
        creator = self.StubBlankCreator(logging.getLogger("creator.interrupt.seed"))
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "seed.mdb"
            with (
                patch.object(
                    database_creator.pyodbc, "connect", return_value=connection
                ),
                patch.object(creator, "_apply_reference_schema_metadata"),
                patch.object(
                    creator, "_insert_seed_rows", side_effect=KeyboardInterrupt()
                ),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    creator.create_database(db_path, "Seed")
            self.assertFalse(db_path.exists())
        self.assertEqual(events, ["commit", "cursor-close", "close"])

    def test_an_interrupt_in_the_dao_phase_closes_the_dao_database_before_removal(
        self,
    ):
        events = []
        creator = self.StubBlankCreator(logging.getLogger("creator.interrupt.dao"))
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "dao.mdb"

            def table_defs(_name):
                raise KeyboardInterrupt()

            dao_database = SimpleNamespace(
                TableDefs=table_defs, Close=lambda: events.append("dao-close")
            )
            engine = SimpleNamespace(OpenDatabase=lambda _path: dao_database)
            with (
                patch.object(
                    database_creator.pyodbc,
                    "connect",
                    return_value=self.Connection(events),
                ),
                patch("win32com.client.Dispatch", return_value=engine),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    creator.create_database(db_path, "Dao")
            self.assertFalse(db_path.exists())
        self.assertIn("dao-close", events)

    def test_an_interrupt_while_cscript_runs_removes_the_script_and_the_file(self):
        def run(command, **_options):
            Path(command[3]).write_bytes(b"partial")
            raise KeyboardInterrupt()

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "target" / "x.mdb"
            with patch.object(tempfile, "tempdir", tmp_dir):
                with patch.object(database_creator.subprocess, "run", side_effect=run):
                    with self.assertRaises(KeyboardInterrupt):
                        database_creator.DatabaseCreator().create_database(
                            db_path, "Interrupted"
                        )
            self.assertFalse(db_path.exists())
            self.assertEqual(list(Path(tmp_dir).glob("ost_create_mdb_*.vbs")), [])

    def test_a_script_that_cannot_be_written_is_not_left_in_the_temp_folder(self):
        real_factory = tempfile.NamedTemporaryFile
        for failure in (OSError("disk full"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):

                class Unwritable:
                    def __init__(self, **options):
                        self._file = real_factory(**options)
                        self.name = self._file.name

                    def __enter__(self):
                        return self

                    def __exit__(self, *exc_info):
                        return self._file.__exit__(*exc_info)

                    def write(self, _text):
                        raise failure

                with tempfile.TemporaryDirectory() as tmp_dir:
                    with (
                        patch.object(tempfile, "tempdir", tmp_dir),
                        patch.object(
                            database_creator.tempfile,
                            "NamedTemporaryFile",
                            Unwritable,
                        ),
                        patch.object(database_creator.subprocess, "run") as run,
                    ):
                        with self.assertRaises(type(failure)):
                            database_creator.DatabaseCreator()._create_blank_mdb(
                                Path(tmp_dir) / "x.mdb"
                            )
                    run.assert_not_called()
                    self.assertEqual(
                        list(Path(tmp_dir).glob("ost_create_mdb_*.vbs")), []
                    )

    def test_a_database_that_appears_before_creation_starts_is_never_removed(self):
        for failure in (KeyboardInterrupt, RuntimeError):
            with self.subTest(failure=failure.__name__):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    db_path = Path(tmp_dir) / "other.mdb"

                    def progress(_description):
                        db_path.write_bytes(b"created by someone else")
                        raise failure("stop")

                    creator = self.StubBlankCreator(
                        logging.getLogger("creator.interrupt.other")
                    )
                    with patch.object(creator._logger, "exception"):
                        try:
                            creator.create_database(db_path, "Other", progress)
                        except KeyboardInterrupt:
                            self.assertIs(failure, KeyboardInterrupt)
                    self.assertEqual(db_path.read_bytes(), b"created by someone else")


class DatabaseCreatorRealAccessInterruptTests(unittest.TestCase):
    """Real Access/ACE: an interrupt must release the file locks so the file can go."""

    @staticmethod
    def _interrupted_creations_leave_nothing_behind():
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            for index, stage in enumerate(
                ("_insert_seed_rows", "_apply_reference_schema_metadata")
            ):
                db_path = Path(folder) / f"interrupted_{index}.mdb"
                creator = database_creator.DatabaseCreator()
                with patch.object(creator, stage, side_effect=KeyboardInterrupt()):
                    try:
                        creator.create_database(db_path, "Interrupted")
                    except KeyboardInterrupt:
                        pass
                    else:
                        raise AssertionError(f"{stage}: interrupt was swallowed")
                if db_path.exists():
                    raise AssertionError(f"{stage}: half-built database remains")
            leftovers = sorted(path.name for path in Path(folder).iterdir())
            if leftovers:
                raise AssertionError(f"leftover files: {leftovers}")
            good_path = Path(folder) / "good.mdb"
            if not database_creator.DatabaseCreator().create_database(good_path, "Ok"):
                raise AssertionError("creation after an interrupt failed")

    def test_interrupted_creations_remove_the_file_and_release_its_locks(self):
        import sys
        from tests.helpers.mdb.schema_support import _access_available
        from tests.paths import REPO_ROOT

        if not _access_available():
            self.skipTest("Access ODBC/ADOX is not available")
        code = (
            "from tests.infrastructure.mdb.test_database_creator import "
            "DatabaseCreatorRealAccessInterruptTests as Tests; "
            "Tests._interrupted_creations_leave_nothing_behind()"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class DatabaseCreatorCreationRaceTests(unittest.TestCase):
    """Another process may create the database between the exists() guard and ADOX.
    ADOX then refuses ("Database already exists" on stderr) but cscript exits 0, so
    the file that is there belongs to the other party and must never be touched.
    """

    REFUSAL = (
        "C:\\Temp\\ost_create_mdb_abc12345.vbs(3, 1) Microsoft Access Database "
        "Engine: Database already exists.\r\n\r\n"
    )
    RIVAL_BYTES = b"valid database of the rival"

    def _rival_wins(self, stderr):
        def run(command, **_options):
            Path(command[3]).write_bytes(self.RIVAL_BYTES)
            return subprocess.CompletedProcess(command, 0, "", stderr)

        return run

    def _create_with(self, stderr, schema_side_effect=None):
        events = []
        creator = database_creator.DatabaseCreator(logging.getLogger("creator.race"))
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "target" / "race.mdb"
            with (
                patch.object(tempfile, "tempdir", tmp_dir),
                patch.object(
                    database_creator.subprocess,
                    "run",
                    side_effect=self._rival_wins(stderr),
                ),
                patch.object(
                    creator, "_create_schema", side_effect=schema_side_effect
                ) as schema,
                patch.object(creator._logger, "exception") as logged,
            ):
                outcome = creator.create_database(db_path, "Race", events.append)
            existing = db_path.read_bytes() if db_path.exists() else None
            scripts = list(Path(tmp_dir).glob("ost_create_mdb_*.vbs"))
        return outcome, existing, schema, logged, events, scripts

    def test_a_database_created_by_a_rival_before_adox_runs_is_left_untouched(self):
        outcome, existing, schema, logged, events, scripts = self._create_with(
            self.REFUSAL, schema_side_effect=RuntimeError("table already exists")
        )
        self.assertIs(outcome, False)
        self.assertEqual(existing, self.RIVAL_BYTES)
        schema.assert_not_called()
        logged.assert_not_called()
        self.assertEqual(events, ["database file"])
        self.assertEqual(scripts, [])

    def test_a_refusal_is_recognised_whatever_language_the_message_is_in(self):
        outcome, existing, schema, _logged, _events, _scripts = self._create_with(
            "x.vbs(3, 1) Microsoft Access Database Engine: Die Datenbank ist "
            "bereits vorhanden.\r\n",
            schema_side_effect=RuntimeError("table already exists"),
        )
        self.assertIs(outcome, False)
        self.assertEqual(existing, self.RIVAL_BYTES)
        schema.assert_not_called()

    def test_a_clean_exit_without_error_text_still_builds_the_schema(self):
        for stderr in ("", " \r\n", None):
            with self.subTest(stderr=stderr):
                outcome, existing, schema, _logged, events, _scripts = (
                    self._create_with(stderr)
                )
                self.assertIs(outcome, True)
                self.assertEqual(existing, self.RIVAL_BYTES)
                schema.assert_called_once()
                self.assertEqual(events, ["database file", "finalizing"])

    def test_error_text_without_any_file_is_still_a_logged_creation_failure(self):
        def run(command, **_options):
            return subprocess.CompletedProcess(command, 0, "", self.REFUSAL)

        creator = database_creator.DatabaseCreator(logging.getLogger("creator.race"))
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "none.mdb"
            with (
                patch.object(database_creator.subprocess, "run", side_effect=run),
                patch.object(creator, "_create_schema") as schema,
                patch.object(creator._logger, "exception") as logged,
            ):
                self.assertIs(creator.create_database(db_path, "None"), False)
            schema.assert_not_called()
            self.assertFalse(db_path.exists())
        logged.assert_called_once()
        self.assertEqual(
            str(logged.call_args.args[2]),
            "VBScript completed but MDB file was not created",
        )

    def test_blank_creation_reports_the_foreign_file_and_removes_the_script(self):
        creator = database_creator.DatabaseCreator()
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "foreign.mdb"
            with (
                patch.object(tempfile, "tempdir", tmp_dir),
                patch.object(
                    database_creator.subprocess,
                    "run",
                    side_effect=self._rival_wins(self.REFUSAL),
                ),
            ):
                with self.assertRaises(database_creator._NotCreatedHere):
                    creator._create_blank_mdb(db_path)
            self.assertEqual(db_path.read_bytes(), self.RIVAL_BYTES)
            self.assertEqual(list(Path(tmp_dir).glob("ost_create_mdb_*.vbs")), [])

    def test_a_nonzero_exit_is_still_a_failure_not_a_foreign_database(self):
        def run(command, **_options):
            Path(command[3]).write_bytes(self.RIVAL_BYTES)
            return subprocess.CompletedProcess(command, 1, "", self.REFUSAL)

        creator = database_creator.DatabaseCreator(logging.getLogger("creator.race"))
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(database_creator.subprocess, "run", side_effect=run):
                with self.assertRaises(RuntimeError) as raised:
                    creator._create_blank_mdb(Path(tmp_dir) / "rc1.mdb")
        self.assertNotIsInstance(raised.exception, database_creator._NotCreatedHere)
        self.assertIn("rc=1", str(raised.exception))


class DatabaseCreatorRealAccessCreationRaceTests(unittest.TestCase):
    """Real Access/ADOX: the file another party created must survive our attempt."""

    WORKER = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "from ost_visualizer.infrastructure.mdb.database_creator import "
        "DatabaseCreator\n"
        "db_path, ready, go = sys.argv[1:4]\n"
        "creator = DatabaseCreator()\n"
        "Path(ready).write_text('ready')\n"
        "while not os.path.exists(go):\n"
        "    pass\n"
        "print('RESULT', creator.create_database(Path(db_path), 'Race'))\n"
    )

    @staticmethod
    def _assert_valid_database(db_path):
        if not db_path.exists():
            raise AssertionError(f"the database {db_path.name} is missing")
        connection = database_creator.pyodbc.connect(
            f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path};",
            autocommit=True,
        )
        try:
            names = {
                row.table_name for row in connection.cursor().tables(tableType="TABLE")
            }
        finally:
            connection.close()
        if "Bids" not in names:
            raise AssertionError(f"{db_path.name} is not a complete database: {names}")

    @classmethod
    def _rival_finishes_before_adox_runs(cls):
        real_run = subprocess.run
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db_path = Path(folder) / "seam.mdb"
            state = {"rival_done": False}

            def run(command, **options):
                if not state["rival_done"]:
                    state["rival_done"] = True
                    if not database_creator.DatabaseCreator().create_database(
                        db_path, "Rival"
                    ):
                        raise AssertionError("the rival could not create its database")
                    state["bytes"] = db_path.read_bytes()
                return real_run(command, **options)

            with patch.object(database_creator.subprocess, "run", side_effect=run):
                outcome = database_creator.DatabaseCreator().create_database(
                    db_path, "Loser"
                )
            if outcome is not False:
                raise AssertionError(f"the late creator reported {outcome!r}")
            if db_path.read_bytes() != state["bytes"]:
                raise AssertionError("the rival's database was modified")
            cls._assert_valid_database(db_path)

    @classmethod
    def _concurrent_creations_keep_the_winner(cls, rounds):
        import os
        import sys
        import time
        from tests.paths import REPO_ROOT

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            for index in range(rounds):
                db_path = Path(folder) / f"race_{index}.mdb"
                go = Path(folder) / f"go_{index}"
                readies = [Path(folder) / f"ready_{index}_{n}" for n in (0, 1)]
                workers = [
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-c",
                            cls.WORKER,
                            str(db_path),
                            str(r),
                            str(go),
                        ],
                        cwd=REPO_ROOT,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    for r in readies
                ]
                try:
                    deadline = time.monotonic() + 90
                    while not all(r.exists() for r in readies):
                        if time.monotonic() > deadline or any(
                            w.poll() is not None for w in workers
                        ):
                            raise AssertionError(f"round {index}: workers not ready")
                    go.write_text("go")
                    outputs = [w.communicate(timeout=120) for w in workers]
                finally:
                    for worker in workers:
                        if worker.poll() is None:
                            worker.kill()
                            worker.communicate()
                results = sorted(
                    out.strip().rsplit(" ", 1)[-1] for out, _err in outputs
                )
                if [w.returncode for w in workers] != [0, 0] or results != [
                    "False",
                    "True",
                ]:
                    raise AssertionError(f"round {index}: {results} {outputs}")
                cls._assert_valid_database(db_path)

    def _run_in_child(self, call, timeout):
        import sys
        from tests.helpers.mdb.schema_support import _access_available
        from tests.paths import REPO_ROOT

        if not _access_available():
            self.skipTest("Access ODBC/ADOX is not available")
        code = (
            "from tests.infrastructure.mdb.test_database_creator import "
            f"DatabaseCreatorRealAccessCreationRaceTests as Tests; Tests.{call}"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_database_completed_by_a_rival_before_adox_runs_survives(self):
        self._run_in_child("_rival_finishes_before_adox_runs()", timeout=120)

    def test_two_processes_creating_the_same_path_never_destroy_the_winner(self):
        self._run_in_child("_concurrent_creations_keep_the_winner(6)", timeout=420)


class DatabaseCreatorRealAccessSeedTests(unittest.TestCase):
    """Real Access/ACE: read back the rows a successful creation actually wrote.
    The unit tests above pin the INSERT text and parameters against fake cursors; only
    the real engine shows that the stored rows hold the intended values and that
    nothing else is seeded.
    """

    @staticmethod
    def _created_database_holds_exactly_the_seed_rows():
        import datetime
        import pyodbc

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db_path = Path(folder) / "seeded.mdb"
            started = datetime.datetime.now()
            if not database_creator.DatabaseCreator().create_database(
                db_path, "Seed Check"
            ):
                raise AssertionError("the database was not created")
            finished = datetime.datetime.now()
            connection = pyodbc.connect(
                f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path};",
                autocommit=True,
            )
            try:
                cursor = connection.cursor()

                def rows(sql):
                    cursor.execute(sql)
                    names = [column[0] for column in cursor.description]
                    return [dict(zip(names, row)) for row in cursor.fetchall()]

                tables = sorted(
                    row.table_name
                    for row in cursor.tables(tableType="TABLE")
                    if not row.table_name.startswith("MSys")
                )
                golden = json.loads(_GOLDEN_DDL.read_text(encoding="utf-8"))["tables"]
                if tables != sorted(name for name, _columns in golden):
                    raise AssertionError(f"unexpected tables: {tables}")
                populated = {}
                for table in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
                    count = cursor.fetchone()[0]
                    if count:
                        populated[table] = count
                expected_counts = {
                    "Settings": 1,
                    "BidProjects": 1,
                    "BidLayers": len(DEFAULT_LAYER_ROWS),
                    "SchemaRegistry": len(database_creator._SCHEMA_VERSIONS),
                }
                if populated != expected_counts:
                    raise AssertionError(f"seeded row counts: {populated}")
                (settings,) = rows("SELECT * FROM [Settings]")
                created = settings.pop("Created")
                if not (
                    started - datetime.timedelta(seconds=2)
                    <= created
                    <= finished + datetime.timedelta(seconds=2)
                ):
                    raise AssertionError(
                        f"Created={created} not in {started}..{finished}"
                    )
                expected_settings = {
                    "UID": 1,
                    "Name": "Seed Check",
                    "NextBidNo": 1,
                    "LoginRequired": False,
                    "MeasureBase": 0,
                    "PriceUsing": 0,
                    "QuantitiesInLegend": True,
                    "HoursPerDay": 8,
                    "StartWeekOn": 0,
                    "GridCountMethod": 0,
                    "TakeoffIncrements": 1.0,
                    "ScaleStyle": 1,
                    "IsCustomScale": False,
                    "ScaleFactor1": 0.125,
                    "ScaleFactor2": 12.0,
                    "PageScale": 1.0,
                    "PageWidth": 42.0,
                    "PageHeight": 30.0,
                    "LabelHours1": "Regular",
                    "LabelHours2": "Overtime",
                    "LabelHours3": "Time + 1/2",
                    "LabelHours4": "Double",
                    "IgnoreBidAreas": False,
                    "SendImageFiles": False,
                    "BackupNo": 2,
                    "BackupPeriod": 2,
                    "CompressPeriod": 2,
                }
                actual_settings = {
                    column: value
                    for column, value in settings.items()
                    if column in expected_settings
                }
                if actual_settings != expected_settings:
                    raise AssertionError(f"Settings row: {actual_settings}")
                unseeded = {
                    column: value
                    for column, value in settings.items()
                    if column not in expected_settings and value is not None
                }
                if unseeded:
                    raise AssertionError(f"unexpected Settings values: {unseeded}")
                projects = [
                    (row["UID"], row["Name"], row["Description"])
                    for row in rows("SELECT * FROM [BidProjects]")
                ]
                if projects != [(1, "Deleted Bids", None)]:
                    raise AssertionError(f"BidProjects rows: {projects}")
                layers = [
                    (
                        row["UID"],
                        row["BidUID"],
                        row["IsTemplate"],
                        row["Name"],
                        row["Show"],
                        row["IsLocked"],
                        row["Sequence"],
                    )
                    for row in rows("SELECT * FROM [BidLayers] ORDER BY [UID]")
                ]
                expected_layers = [
                    (uid, None, True, name, bool(show), bool(locked), sequence)
                    for uid, (name, show, locked, sequence) in enumerate(
                        DEFAULT_LAYER_ROWS, start=1
                    )
                ]
                if layers != expected_layers:
                    raise AssertionError(f"BidLayers rows: {layers}")
                registry = [
                    (row["UID"], row["Version"], row["Product"])
                    for row in rows("SELECT * FROM [SchemaRegistry] ORDER BY [UID]")
                ]
                expected_registry = [
                    (uid, version, 2)
                    for uid, version in enumerate(
                        database_creator._SCHEMA_VERSIONS, start=1
                    )
                ]
                if registry != expected_registry:
                    raise AssertionError(f"SchemaRegistry rows: {registry}")
            finally:
                connection.close()

    def test_a_created_database_stores_exactly_the_documented_seed_rows(self):
        import sys
        from tests.helpers.mdb.schema_support import _access_available
        from tests.paths import REPO_ROOT

        if not _access_available():
            self.skipTest("Access ODBC/ADOX is not available")
        code = (
            "from tests.infrastructure.mdb.test_database_creator import "
            "DatabaseCreatorRealAccessSeedTests as Tests; "
            "Tests._created_database_holds_exactly_the_seed_rows()"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class DatabaseCreatorReferenceModelMetadataTests(unittest.TestCase):
    """The reference model carries the same defaults, indexes and keys the DAO phase applies."""

    @classmethod
    def setUpClass(cls):
        cls.model = database_creator.get_reference_schema_model()

    def test_column_defaults_are_exactly_the_reference_field_defaults(self):
        defaults = {
            (table.name, column.name): column.default
            for table in self.model.tables
            for column in table.columns
            if column.default is not None
        }
        self.assertEqual(defaults, dict(database_creator.FIELD_DEFAULTS))
        self.assertGreater(len(defaults), 0)

    def test_table_indexes_are_exactly_the_reference_explicit_indexes(self):
        indexes = [
            (table.name, index.name, index.unique, index.columns)
            for table in self.model.tables
            for index in table.indexes
        ]
        expected = [
            (table, name, bool(unique), tuple(columns))
            for table, name, unique, columns in database_creator.EXPLICIT_INDEXES
        ]
        self.assertEqual(sorted(indexes), sorted(expected))
        self.assertGreater(len(indexes), 0)

    def test_foreign_keys_are_exactly_the_reference_relationships_in_order(self):
        keys = [
            (
                key.name,
                key.child_table,
                key.child_column,
                key.parent_table,
                key.parent_column,
            )
            for key in self.model.foreign_keys
        ]
        self.assertEqual(keys, list(database_creator.REFERENCE_RELATIONSHIPS))
        self.assertGreater(len(keys), 0)

    def test_the_locking_columns_declared_not_null_are_required(self):
        columns = {
            column.name: column for column in self.model.table("Locking").columns
        }
        self.assertEqual(
            {name for name, column in columns.items() if column.required},
            {"UID", "Essence", "Owner"},
        )
        self.assertEqual(columns["Essence"].access_type, "VARCHAR(40)")

    def test_a_listed_uid_column_is_required_even_without_a_primary_key(self):
        """Every shipped UID is a COUNTER PRIMARY KEY, so only a patched table shows it."""
        ddl = ["CREATE TABLE [T] (\n        [UID] INTEGER,\n        [X] INTEGER\n    )"]
        with (
            patch.object(database_creator, "_TABLE_DDL", ddl),
            patch.object(database_creator, "UID_REQUIRED_TABLES", ("T",)),
        ):
            listed = database_creator.get_reference_schema_model()
        with (
            patch.object(database_creator, "_TABLE_DDL", ddl),
            patch.object(database_creator, "UID_REQUIRED_TABLES", ()),
        ):
            unlisted = database_creator.get_reference_schema_model()
        self.assertEqual(
            {c.name: c.required for c in listed.table("T").columns},
            {"UID": True, "X": False},
        )
        self.assertEqual(
            {c.name: c.required for c in unlisted.table("T").columns},
            {"UID": False, "X": False},
        )


class DatabaseCreatorCleanupContractTests(unittest.TestCase):
    """Log wording, path handling and what the cleanup helpers never swallow."""

    class Creator(database_creator.DatabaseCreator):
        def _create_blank_mdb(self, db_path):
            Path(db_path).write_bytes(b"blank")

        def _create_schema(self, db_path, progress_callback=None, *, seed_name=None):
            pass

    def test_the_default_logger_is_the_module_logger_and_is_the_one_used(self):
        creator = database_creator.DatabaseCreator()
        self.assertIs(creator._logger, logging.getLogger(database_creator.__name__))
        connection = Mock()
        connection.rollback.side_effect = RuntimeError("gone")
        with self.assertLogs(database_creator.__name__, level="ERROR") as logs:
            creator._rollback_connection(connection, "schema creation")
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Failed to roll back MDB schema creation"],
        )

    def test_a_given_logger_replaces_the_default_one(self):
        custom = logging.getLogger("creator.custom")
        self.assertIs(database_creator.DatabaseCreator(custom)._logger, custom)

    def test_a_text_path_is_accepted_and_an_existing_text_path_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            text_path = str(Path(tmp_dir) / "nested" / "text.mdb")
            creator = self.Creator()
            self.assertIs(creator.create_database(text_path, "Text"), True)
            self.assertEqual(Path(text_path).read_bytes(), b"blank")
            self.assertIs(creator.create_database(text_path, "Again"), False)
            self.assertEqual(Path(text_path).read_bytes(), b"blank")

    def test_a_failed_creation_logs_the_path_and_the_cause_in_one_message(self):
        class Failing(self.Creator):
            def _create_schema(
                self, db_path, progress_callback=None, *, seed_name=None
            ):
                raise RuntimeError("schema failed")

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "failed.mdb"
            creator = Failing(logging.getLogger("creator.failed"))
            with self.assertLogs("creator.failed", level="ERROR") as logs:
                self.assertIs(creator.create_database(db_path, "Failed"), False)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [f"Failed to create database {db_path}: schema failed"],
        )

    def test_a_failed_cscript_run_names_the_exit_code_and_the_error_text(self):
        def run(command, **_options):
            return subprocess.CompletedProcess(command, 7, "", "provider missing")

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(database_creator.subprocess, "run", side_effect=run):
                with self.assertRaises(RuntimeError) as raised:
                    database_creator.DatabaseCreator()._create_blank_mdb(
                        Path(tmp_dir) / "x.mdb"
                    )
        self.assertEqual(
            str(raised.exception), "VBScript failed (rc=7): provider missing"
        )

    def test_a_refused_creation_carries_the_trimmed_error_text(self):
        def run(command, **_options):
            Path(command[3]).write_bytes(b"someone else's database")
            return subprocess.CompletedProcess(
                command, 0, "", "  Database already exists.\r\n\r\n"
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(database_creator.subprocess, "run", side_effect=run):
                with self.assertRaises(database_creator._NotCreatedHere) as raised:
                    database_creator.DatabaseCreator()._create_blank_mdb(
                        Path(tmp_dir) / "x.mdb"
                    )
        self.assertEqual(str(raised.exception), "Database already exists.")

    def test_a_script_file_that_cannot_even_be_created_reports_that_error(self):
        with patch.object(
            database_creator.tempfile,
            "NamedTemporaryFile",
            side_effect=OSError("no temporary folder"),
        ):
            with patch.object(database_creator.subprocess, "run") as run:
                with self.assertRaises(OSError) as raised:
                    database_creator.DatabaseCreator()._create_blank_mdb(
                        Path("unused.mdb")
                    )
        self.assertEqual(str(raised.exception), "no temporary folder")
        run.assert_not_called()

    def test_a_cursor_that_cannot_be_opened_still_rolls_back_and_closes(self):
        creator = database_creator.DatabaseCreator(
            logging.getLogger("creator.nocursor")
        )
        for label, call in (
            ("schema", lambda: creator._create_schema("x.mdb", seed_name="Created")),
            ("seed", lambda: creator._insert_seed_data("x.mdb", "Created")),
        ):
            with self.subTest(label):
                connection = Mock()
                connection.cursor.side_effect = RuntimeError("cursor refused")
                with patch.object(
                    database_creator.pyodbc, "connect", return_value=connection
                ):
                    with self.assertRaisesRegex(RuntimeError, "^cursor refused$"):
                        call()
                connection.rollback.assert_called_once_with()
                connection.close.assert_called_once_with()

    def test_a_dao_close_failure_is_logged_with_its_own_message(self):
        creator = database_creator.DatabaseCreator(
            logging.getLogger("creator.daoclose")
        )
        database = Mock()
        database.Close.side_effect = RuntimeError("dao stuck")
        with self.assertLogs("creator.daoclose", level="ERROR") as logs:
            creator._close_dao_database(database, suppress_errors=True)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Failed to close MDB DAO database"],
        )

    def test_interrupts_are_never_swallowed_by_the_cleanup_helpers(self):
        creator = database_creator.DatabaseCreator(
            logging.getLogger("creator.interrupts")
        )
        broken = Mock()
        broken.rollback.side_effect = KeyboardInterrupt()
        broken.close.side_effect = KeyboardInterrupt()
        broken.Close.side_effect = KeyboardInterrupt()
        for label, call in (
            ("rollback", lambda: creator._rollback_connection(broken, "seed")),
            (
                "odbc close",
                lambda: creator._close_odbc_resources(
                    broken, None, "seed", suppress_errors=True
                ),
            ),
            (
                "dao close",
                lambda: creator._close_dao_database(broken, suppress_errors=True),
            ),
        ):
            with self.subTest(label):
                with self.assertRaises(KeyboardInterrupt):
                    call()
        with tempfile.TemporaryDirectory() as tmp_dir:
            kept = Path(tmp_dir) / "kept.mdb"
            kept.write_bytes(b"x")
            with patch.object(Path, "unlink", side_effect=KeyboardInterrupt()):
                with self.assertRaises(KeyboardInterrupt):
                    creator._discard_partial_database(kept)
            scripts = []

            def run(command, **_options):
                scripts.append(Path(command[2]))
                Path(command[3]).touch()
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch.object(tempfile, "tempdir", tmp_dir),
                patch.object(database_creator.subprocess, "run", side_effect=run),
                patch.object(Path, "unlink", side_effect=KeyboardInterrupt()),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    creator._create_blank_mdb(Path(tmp_dir) / "x.mdb")


class DatabaseCreatorInterruptPolicyTests(unittest.TestCase):
    """An interrupt is re-raised as it was: a failing cleanup never replaces it.
    Policy: clean up every resource on its own (one failing cleanup must not skip the
    next), log each secondary cleanup error naming the interrupt, re-raise the original
    interrupt and leave no half-written database behind.
    """

    INTERRUPTS = (KeyboardInterrupt, SystemExit)

    class StubBlankCreator(database_creator.DatabaseCreator):
        def _create_blank_mdb(self, db_path):
            Path(db_path).write_bytes(b"blank")

    @staticmethod
    def _messages(logs):
        return [record.getMessage() for record in logs.records]

    def test_an_interrupt_in_the_dao_phase_survives_a_failing_dao_close(self):
        for interrupt_type in self.INTERRUPTS:
            with self.subTest(interrupt=interrupt_type.__name__):
                interrupt = interrupt_type()

                def table_defs(_name):
                    raise interrupt

                dao_database = SimpleNamespace(
                    TableDefs=table_defs,
                    Close=Mock(side_effect=RuntimeError("dao close failed")),
                )
                engine = SimpleNamespace(OpenDatabase=lambda _path: dao_database)
                logger_name = f"creator.policy.dao.{interrupt_type.__name__}"
                creator = self.StubBlankCreator(logging.getLogger(logger_name))
                with tempfile.TemporaryDirectory() as tmp_dir:
                    db_path = Path(tmp_dir) / "dao.mdb"
                    with (
                        patch.object(
                            database_creator.pyodbc, "connect", return_value=Mock()
                        ),
                        patch("win32com.client.Dispatch", return_value=engine),
                        self.assertLogs(logger_name, level="ERROR") as logs,
                    ):
                        with self.assertRaises(interrupt_type) as raised:
                            creator.create_database(db_path, "Dao")
                    self.assertIs(raised.exception, interrupt)
                    self.assertFalse(db_path.exists())
                    self.assertEqual(list(Path(tmp_dir).iterdir()), [])
                dao_database.Close.assert_called_once_with()
                self.assertEqual(
                    self._messages(logs),
                    [
                        "Failed to close MDB DAO database while handling "
                        f"{interrupt_type.__name__}"
                    ],
                )

    def test_an_interrupt_while_seeding_survives_failing_odbc_closes(self):
        for interrupt_type in self.INTERRUPTS:
            with self.subTest(interrupt=interrupt_type.__name__):
                interrupt = interrupt_type()
                connection = Mock()
                cursor = connection.cursor.return_value
                cursor.close.side_effect = RuntimeError("cursor close failed")
                connection.close.side_effect = RuntimeError("connection close failed")
                logger_name = f"creator.policy.seed.{interrupt_type.__name__}"
                creator = self.StubBlankCreator(logging.getLogger(logger_name))
                with tempfile.TemporaryDirectory() as tmp_dir:
                    db_path = Path(tmp_dir) / "seed.mdb"
                    with (
                        patch.object(
                            database_creator.pyodbc, "connect", return_value=connection
                        ),
                        patch.object(creator, "_apply_reference_schema_metadata"),
                        patch.object(
                            creator, "_insert_seed_rows", side_effect=interrupt
                        ),
                        self.assertLogs(logger_name, level="ERROR") as logs,
                    ):
                        with self.assertRaises(interrupt_type) as raised:
                            creator.create_database(db_path, "Seed")
                    self.assertIs(raised.exception, interrupt)
                    self.assertFalse(db_path.exists())
                    self.assertEqual(list(Path(tmp_dir).iterdir()), [])
                cursor.close.assert_called_once_with()
                connection.close.assert_called_once_with()
                name = interrupt_type.__name__
                self.assertEqual(
                    self._messages(logs),
                    [
                        "Failed to close MDB cursor after schema creation while "
                        f"handling {name}",
                        "Failed to close MDB connection after schema creation while "
                        f"handling {name}",
                    ],
                )

    def test_an_interrupt_before_any_commit_survives_a_failing_connection_close(self):
        connection = Mock()
        connection.cursor.return_value.execute.side_effect = KeyboardInterrupt()
        connection.close.side_effect = RuntimeError("connection close failed")
        creator = database_creator.DatabaseCreator(
            logging.getLogger("creator.policy.tables")
        )
        with patch.object(database_creator.pyodbc, "connect", return_value=connection):
            with self.assertLogs("creator.policy.tables", level="ERROR") as logs:
                with self.assertRaises(KeyboardInterrupt):
                    creator._create_schema("x.mdb", seed_name="Tables")
        connection.commit.assert_not_called()
        connection.cursor.return_value.close.assert_called_once_with()
        connection.close.assert_called_once_with()
        self.assertEqual(
            self._messages(logs),
            [
                "Failed to close MDB connection after schema creation while "
                "handling KeyboardInterrupt"
            ],
        )

    def test_an_interrupt_in_the_unseeded_schema_survives_a_failing_cursor_close(
        self,
    ):
        connection = Mock()
        connection.cursor.return_value.execute.side_effect = SystemExit(3)
        connection.cursor.return_value.close.side_effect = RuntimeError("stuck")
        creator = database_creator.DatabaseCreator(
            logging.getLogger("creator.policy.unseeded")
        )
        with (
            patch.object(database_creator.pyodbc, "connect", return_value=connection),
            patch.object(creator, "_apply_reference_schema_metadata") as metadata,
            self.assertLogs("creator.policy.unseeded", level="ERROR"),
        ):
            with self.assertRaises(SystemExit) as raised:
                creator._create_schema("x.mdb")
        self.assertEqual(raised.exception.code, 3)
        metadata.assert_not_called()
        connection.close.assert_called_once_with()

    def test_the_standalone_seed_helper_keeps_an_interrupt_over_failing_closes(self):
        connection = Mock()
        connection.cursor.return_value.close.side_effect = RuntimeError("cursor")
        connection.close.side_effect = RuntimeError("connection")
        creator = database_creator.DatabaseCreator(
            logging.getLogger("creator.policy.standalone")
        )
        with (
            patch.object(database_creator.pyodbc, "connect", return_value=connection),
            patch.object(creator, "_insert_seed_rows", side_effect=KeyboardInterrupt()),
            self.assertLogs("creator.policy.standalone", level="ERROR") as logs,
        ):
            with self.assertRaises(KeyboardInterrupt):
                creator._insert_seed_data("x.mdb", "Standalone")
        connection.cursor.return_value.close.assert_called_once_with()
        connection.close.assert_called_once_with()
        self.assertEqual(
            self._messages(logs),
            [
                "Failed to close MDB cursor after seed-data insertion while "
                "handling KeyboardInterrupt",
                "Failed to close MDB connection after seed-data insertion while "
                "handling KeyboardInterrupt",
            ],
        )

    def test_the_close_helpers_name_the_interrupt_and_never_raise_over_it(self):
        creator = database_creator.DatabaseCreator(
            logging.getLogger("creator.policy.helpers")
        )
        interrupt = SystemExit(1)
        cursor = Mock()
        cursor.close.side_effect = RuntimeError("cursor")
        connection = Mock()
        connection.close.side_effect = RuntimeError("connection")
        with self.assertLogs("creator.policy.helpers", level="ERROR") as logs:
            creator._close_odbc_resources(
                cursor, connection, "import", suppress_errors=False, interrupt=interrupt
            )
        cursor.close.assert_called_once_with()
        connection.close.assert_called_once_with()
        self.assertEqual(
            self._messages(logs),
            [
                "Failed to close MDB cursor after import while handling SystemExit",
                "Failed to close MDB connection after import while handling "
                "SystemExit",
            ],
        )
        database = Mock()
        database.Close.side_effect = RuntimeError("dao")
        with self.assertLogs("creator.policy.helpers", level="ERROR") as logs:
            creator._close_dao_database(
                database, suppress_errors=False, interrupt=interrupt
            )
        self.assertEqual(
            self._messages(logs),
            ["Failed to close MDB DAO database while handling SystemExit"],
        )

    def test_ordinary_failures_keep_their_close_messages_and_the_false_result(self):
        class Creator(self.StubBlankCreator):
            def _create_schema(
                self, db_path, progress_callback=None, *, seed_name=None
            ):
                self._apply_reference_schema_metadata(db_path)

        dao_database = SimpleNamespace(
            TableDefs=Mock(side_effect=RuntimeError("metadata failed")),
            Close=Mock(side_effect=RuntimeError("dao close failed")),
        )
        engine = SimpleNamespace(OpenDatabase=lambda _path: dao_database)
        creator = Creator(logging.getLogger("creator.policy.ordinary"))
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "ordinary.mdb"
            with (
                patch("win32com.client.Dispatch", return_value=engine),
                self.assertLogs("creator.policy.ordinary", level="ERROR") as logs,
            ):
                self.assertIs(creator.create_database(db_path, "Ordinary"), False)
            self.assertFalse(db_path.exists())
        self.assertEqual(
            self._messages(logs),
            [
                "Failed to close MDB DAO database",
                f"Failed to create database {db_path}: metadata failed",
            ],
        )

    def test_a_failing_close_after_a_successful_run_is_still_raised(self):
        creator = database_creator.DatabaseCreator(
            logging.getLogger("creator.policy.success")
        )
        database = Mock()
        database.Close.side_effect = RuntimeError("dao")
        with self.assertLogs("creator.policy.success", level="ERROR") as logs:
            with self.assertRaisesRegex(RuntimeError, "^dao$"):
                creator._close_dao_database(database, suppress_errors=False)
        self.assertEqual(self._messages(logs), ["Failed to close MDB DAO database"])

    def test_create_database_reports_the_real_progress_stages_in_order(self):
        """Characterisation without a fake schema step: every stage is production's."""
        connection = Mock()
        reports = []
        creator = self.StubBlankCreator(logging.getLogger("creator.policy.stages"))
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "stages.mdb"
            with (
                patch.object(
                    database_creator.pyodbc, "connect", return_value=connection
                ),
                patch("win32com.client.Dispatch", return_value=Mock()),
            ):
                self.assertIs(
                    creator.create_database(db_path, "Stages", reports.append), True
                )
            self.assertEqual(db_path.read_bytes(), b"blank")
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
        connection.rollback.assert_not_called()
        connection.close.assert_called_once_with()
