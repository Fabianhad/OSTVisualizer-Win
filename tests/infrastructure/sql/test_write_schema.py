import os
import unittest
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlInfrastructureError,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.write_schema import CurrentSqlWriteSchema

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.infrastructure.mdb.database_creator import (
    get_reference_schema_model,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class WriteSchemaSqlCleanupTests(unittest.TestCase):
    def test_sql_write_schema_exposes_columns_to_shared_write_mixins(self):
        schema = CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)
        expected_columns = {
            "Bids": {"UID", "JobName"},
            "BidPages": {"UID", "BidUID"},
            "BidConditions": {"UID", "BidUID", "Name", "Type"},
            "BidTakeoffs": {"UID", "Position"},
        }
        for table, required in expected_columns.items():
            with self.subTest(table=table):
                self.assertTrue(required.issubset(schema.get_columns(table)))
                self.assertTrue(schema.table_exists(table))
                self.assertFalse(schema.optional_table_missing(table))
        mutable = schema.get_columns("Bids")
        mutable.add("Injected")
        self.assertNotIn("Injected", schema.get_columns("Bids"))
        columns, types = schema.table_info("Bids")
        self.assertEqual(columns, schema.get_columns("Bids"))
        self.assertEqual(set(types), columns)
        self.assertEqual(types["UID"], "int")
        self.assertEqual(types["JobName"], "nvarchar")
        # Callers receive copies and cannot corrupt the canonical column set.
        columns.add("Injected")
        self.assertNotIn("Injected", schema.get_columns("Bids"))

    def test_optional_helpers_never_substitute_defaults_for_missing_schema(self):
        schema = CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)
        self.assertEqual(schema.optional_column("Bids", "UID", "NULL"), "[UID]")
        self.assertEqual(
            schema.optional_column("Bids", "UID", "NULL", alias="BidId"),
            "[UID] AS [BidId]",
        )
        self.assertEqual(
            schema.order_by_existing("BidPages", ("BidUID", "UID"), "UID"),
            "[BidUID], [UID]",
        )
        for call in (
            lambda: schema.optional_column("Bids", "Missing", "NULL"),
            lambda: schema.optional_column("Missing", "UID", "NULL"),
            lambda: schema.order_by_existing("Bids", ("UID", "Missing"), "UID"),
            lambda: schema.optional_table_missing("Missing"),
            lambda: schema.table_info("Missing"),
            lambda: schema.get_columns("Missing"),
            lambda: schema.log_optional_write_skip("Bids", "UID", "update"),
        ):
            with self.subTest(call=call):
                with self.assertRaises(SqlInfrastructureError) as raised:
                    call()
                self.assertEqual(
                    raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH
                )
                self.assertTrue(raised.exception.read_only_required)


class WriteSchemaDatabaseDescriptorTests(unittest.TestCase):
    def test_current_write_schema_rejects_noncanonical_fields(self):
        schema = CurrentSqlWriteSchema(get_reference_schema_model())
        self.assertTrue(schema.column_exists("Bids", "UID"))
        with self.assertRaisesRegex(
            SqlInfrastructureError, r"does not support dbo\.Bids\.NotAColumn"
        ) as raised:
            schema.column_exists("Bids", "NotAColumn")
        self.assertEqual(raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH)
        with self.assertRaisesRegex(SqlInfrastructureError, r"dbo\.NotATable"):
            schema.require_table("NotATable")
        self.assertFalse(schema.table_exists("NotATable"))
        self.assertTrue(schema.table_exists("Bids"))


class WriteSchemaAnswerTypeTests(unittest.TestCase):
    """Survivor of the second-pass mutation sweep over write_schema.py."""

    def test_existence_answers_are_real_booleans_and_missing_tables_never_look_optional(
        self,
    ):
        schema = CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)
        self.assertIs(schema.table_exists("Bids"), True)
        self.assertIs(
            schema.table_exists("Sessions"), False
        )  # ostv tables are not write-schema tables
        self.assertIs(schema.optional_table_missing("Bids"), False)
        self.assertIs(schema.column_exists("Bids", "UID"), True)
        with self.assertRaises(SqlInfrastructureError):
            schema.optional_table_missing("Sessions")
