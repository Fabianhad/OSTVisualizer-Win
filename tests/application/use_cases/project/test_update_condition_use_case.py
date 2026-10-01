import logging
import sqlite3
import unittest
from contextlib import contextmanager
from ost_visualizer.application.dtos.update_condition_dto import UpdateConditionDto
from ost_visualizer.application.use_cases.project.update_condition_use_case import (
    UpdateConditionUseCase,
)
from ost_visualizer.infrastructure.mdb.components.condition_operations import (
    ConditionOperationsMixin,
)

TARGET_UPDATE_MARKER = "<target update>"


class _Schema:
    def column_exists(self, _table, _column):
        return True


class _Cursor:
    def __init__(self):
        self.executed = []
        self._result = None
        self._parameters = ()

    def execute(self, sql, *parameters):
        self.executed.append((sql, parameters))
        self._parameters = parameters
        if sql.startswith("SELECT [RefNo]"):
            self._result = (8,)
        elif sql.startswith("SELECT [UID]"):
            self._result = (22,)
        return self

    def fetchone(self):
        result = self._result
        self._result = None
        return result

    def fetchall(self):
        if self.executed and self.executed[-1][0].startswith("SELECT [UID], [BidUID]"):
            return [(self._parameters[0], 7)]
        return [(self._parameters[0],)] if self._parameters else []


class _Connection:
    def __init__(self):
        self.cursor_value = _Cursor()

    def cursor(self):
        return self.cursor_value


class _ConditionWriter(ConditionOperationsMixin):
    def __init__(self):
        self.connection = _Connection()
        self.connection_entries = 0
        self.target_updates = []
        self.logger = logging.getLogger(__name__)

    @contextmanager
    def _connection(self, _db_path):
        self.connection_entries += 1
        yield self.connection

    @staticmethod
    def _schema(_connection):
        return _Schema()

    @staticmethod
    def _require_write_columns(_schema, _table, _columns):
        pass

    def _execute_update_values(
        self,
        cursor,
        schema,
        table,
        values,
        required_columns,
        where_sql,
        params,
        operation,
    ):
        cursor.executed.append((TARGET_UPDATE_MARKER, tuple(params)))
        self.target_updates.append(
            (
                cursor,
                schema,
                table,
                dict(values),
                required_columns,
                where_sql,
                list(params),
                operation,
            )
        )

    @staticmethod
    def _record_caught_mutation_error(_exc):
        return False


class _UseCaseWriter:
    def __init__(self, result=True):
        self.result = result
        self.update_calls = []

    def update_condition(self, *args):
        self.update_calls.append(args)
        return self.result


class _OdbcStyleCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, *parameters):
        self._cursor.execute(sql, parameters)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class _SqliteConditionWriter(_ConditionWriter):
    def __init__(self, sqlite_connection):
        super().__init__()
        self.sqlite_connection = sqlite_connection

    @contextmanager
    def _connection(self, _db_path):
        self.connection_entries += 1
        yield self

    def cursor(self):
        return _OdbcStyleCursor(self.sqlite_connection.cursor())

    def _execute_update_values(
        self,
        cursor,
        schema,
        table,
        values,
        required_columns,
        where_sql,
        params,
        operation,
    ):
        assignments = ", ".join(f"[{column}] = ?" for column in values)
        cursor.execute(
            f"UPDATE [{table}] SET {assignments} WHERE {where_sql}",
            *values.values(),
            *params,
        )


class ConditionOperationsTests(unittest.TestCase):
    def test_conflicting_ref_shift_and_target_update_share_one_connection(self):
        writer = _ConditionWriter()
        updates = UpdateConditionDto()
        updates.set("ref_no", 4)
        self.assertTrue(writer.update_condition("example.mdb", "7", "11", updates))
        self.assertEqual(writer.connection_entries, 1)
        self.assertEqual(
            writer.connection.cursor_value.executed,
            [
                (
                    "SELECT [UID], [BidUID] FROM [BidConditions] WHERE [UID] IN (?)",
                    (11,),
                ),
                ("SELECT [UID] FROM [Bids] WHERE [UID] IN (?)", (7,)),
                (
                    "SELECT [RefNo] FROM [BidConditions] "
                    "WHERE [UID] = ? AND [BidUID] = ?",
                    (11, 7),
                ),
                (
                    "SELECT [UID] FROM [BidConditions] "
                    "WHERE [BidUID] = ? AND [RefNo] = ? AND [UID] <> ?",
                    (7, 4, 11),
                ),
                (
                    "UPDATE [BidConditions] SET [RefNo] = [RefNo] + 1 "
                    "WHERE [BidUID] = ? AND [RefNo] >= ? AND [UID] <> ?",
                    (7, 4, 11),
                ),
                (TARGET_UPDATE_MARKER, (11, 7)),
            ],
        )
        self.assertEqual(writer.target_updates[0][3], {"RefNo": 4})
        self.assertEqual(writer.target_updates[0][6], [11, 7])

    def _sqlite_writer(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute("CREATE TABLE Bids (UID INTEGER)")
        connection.executemany("INSERT INTO Bids VALUES (?)", [(7,), (8,)])
        connection.execute(
            "CREATE TABLE BidConditions "
            "(UID INTEGER, BidUID INTEGER, RefNo INTEGER, Name TEXT)"
        )
        connection.executemany(
            "INSERT INTO BidConditions VALUES (?, ?, ?, ?)",
            [
                (10, 7, 1, "a"),
                (11, 7, 2, "b"),
                (12, 7, 3, "c"),
                (13, 7, 4, "d"),
                (20, 8, 3, "other bid"),
            ],
        )
        return connection, _SqliteConditionWriter(connection)

    @staticmethod
    def _ref_numbers(connection):
        return dict(
            connection.execute("SELECT UID, RefNo FROM BidConditions").fetchall()
        )

    def test_conflicting_ref_no_update_shifts_only_same_bid_conflicts(self):
        connection, writer = self._sqlite_writer()
        updates = UpdateConditionDto()
        updates.set("ref_no", 3)
        self.assertTrue(writer.update_condition("example.mdb", "7", "11", updates))
        self.assertEqual(
            self._ref_numbers(connection),
            {10: 1, 11: 3, 12: 4, 13: 5, 20: 3},
        )

    def test_non_conflicting_or_unchanged_ref_no_update_does_not_shift(self):
        for new_ref_no, expected in (
            (9, {10: 1, 11: 9, 12: 3, 13: 4, 20: 3}),
            (2, {10: 1, 11: 2, 12: 3, 13: 4, 20: 3}),
        ):
            with self.subTest(new_ref_no=new_ref_no):
                connection, writer = self._sqlite_writer()
                updates = UpdateConditionDto()
                updates.set("ref_no", new_ref_no)
                self.assertTrue(
                    writer.update_condition("example.mdb", "7", "11", updates)
                )
                self.assertEqual(self._ref_numbers(connection), expected)

    def test_use_case_does_not_commit_a_separate_ref_shift(self):
        writer = _UseCaseWriter()
        use_case = UpdateConditionUseCase(writer)
        updates = UpdateConditionDto()
        updates.set("ref_no", 4)
        result = use_case.execute("example.mdb", "7", "11", updates)
        self.assertTrue(result.success)
        self.assertIsNone(result.error)
        self.assertEqual(
            writer.update_calls,
            [("example.mdb", "7", "11", updates)],
        )
        self.assertIs(writer.update_calls[0][3], updates)

    def test_use_case_rejects_invalid_changes_before_writing(self):
        cases = {
            "blank_name": ({"name": "   "}, "Condition name cannot be empty."),
            "missing_name": ({"name": None}, "Condition name cannot be empty."),
            "display_size_low": (
                {"display_size": 9},
                "Display Size must be between 10% and 500%.",
            ),
            "display_size_high": (
                {"display_size": 501},
                "Display Size must be between 10% and 500%.",
            ),
        }
        for label, (changes, error) in cases.items():
            with self.subTest(label=label):
                writer = _UseCaseWriter()
                updates = UpdateConditionDto()
                for key, value in changes.items():
                    updates.set(key, value)
                result = UpdateConditionUseCase(writer).execute(
                    "example.mdb", "7", "11", updates
                )
                self.assertFalse(result.success)
                self.assertEqual(result.error, error)
                self.assertEqual(writer.update_calls, [])

    def test_use_case_accepts_boundaries_skips_empty_and_reports_writer_failure(self):
        writer = _UseCaseWriter()
        result = UpdateConditionUseCase(writer).execute(
            "example.mdb", "7", "11", UpdateConditionDto()
        )
        self.assertTrue(result.success)
        self.assertEqual(writer.update_calls, [])
        for display_size in (10, 500):
            with self.subTest(display_size=display_size):
                writer = _UseCaseWriter()
                updates = UpdateConditionDto()
                updates.set("display_size", display_size)
                result = UpdateConditionUseCase(writer).execute(
                    "example.mdb", "7", "11", updates
                )
                self.assertTrue(result.success)
                self.assertEqual(len(writer.update_calls), 1)
        writer = _UseCaseWriter(result=False)
        updates = UpdateConditionDto()
        updates.set("name", "Valid")
        result = UpdateConditionUseCase(writer).execute(
            "example.mdb", "7", "11", updates
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Failed to save condition to database.")
        self.assertEqual(len(writer.update_calls), 1)


if __name__ == "__main__":
    unittest.main()
