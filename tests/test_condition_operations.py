import logging
import unittest
from contextlib import contextmanager

from ost_visualizer.application.dtos.update_condition_dto import UpdateConditionDto
from ost_visualizer.application.use_cases.project.update_condition_use_case import (
    UpdateConditionUseCase,
)
from ost_visualizer.infrastructure.mdb.components.condition_operations import (
    ConditionOperationsMixin,
)


class _Schema:
    def column_exists(self, _table, _column):
        return True


class _Cursor:
    def __init__(self):
        self.executed = []
        self._result = None

    def execute(self, sql, *parameters):
        self.executed.append((sql, parameters))
        if sql.startswith("SELECT [RefNo]"):
            self._result = (8,)
        elif sql.startswith("SELECT [UID]"):
            self._result = (22,)
        return self

    def fetchone(self):
        result = self._result
        self._result = None
        return result


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
        return None

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
    def __init__(self):
        self.update_calls = []

    def shift_ref_nos(self, *_args, **_kwargs):
        raise AssertionError("reference numbers must not be shifted separately")

    def update_condition(self, *args):
        self.update_calls.append(args)
        return True


class ConditionOperationsTests(unittest.TestCase):
    def test_conflicting_ref_shift_and_target_update_share_one_connection(self):
        writer = _ConditionWriter()
        updates = UpdateConditionDto()
        updates.set("ref_no", 4)

        self.assertTrue(writer.update_condition("example.mdb", "7", "11", updates))

        self.assertEqual(writer.connection_entries, 1)
        statements = [sql for sql, _params in writer.connection.cursor_value.executed]
        self.assertEqual(
            statements,
            [
                "SELECT [RefNo] FROM [BidConditions] "
                "WHERE [UID] = ? AND [BidUID] = ?",
                "SELECT [UID] FROM [BidConditions] "
                "WHERE [BidUID] = ? AND [RefNo] = ? AND [UID] <> ?",
                "UPDATE [BidConditions] SET [RefNo] = [RefNo] + 1 "
                "WHERE [BidUID] = ? AND [RefNo] >= ? AND [UID] <> ?",
            ],
        )
        self.assertEqual(writer.target_updates[0][3], {"RefNo": 4})
        self.assertEqual(writer.target_updates[0][6], [11, 7])

    def test_use_case_does_not_commit_a_separate_ref_shift(self):
        writer = _UseCaseWriter()
        use_case = UpdateConditionUseCase(writer)
        updates = UpdateConditionDto()
        updates.set("ref_no", 4)

        result = use_case.execute("example.mdb", "7", "11", updates)

        self.assertTrue(result.success)
        self.assertEqual(
            writer.update_calls,
            [("example.mdb", "7", "11", updates)],
        )


if __name__ == "__main__":
    unittest.main()
