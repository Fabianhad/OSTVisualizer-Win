import os
import unittest
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


class WriteSchemaDatabaseDescriptorTests(unittest.TestCase):
    def test_current_write_schema_rejects_noncanonical_fields(self):
        schema = CurrentSqlWriteSchema(get_reference_schema_model())
        self.assertTrue(schema.column_exists("Bids", "UID"))
        with self.assertRaisesRegex(Exception, "dbo.Bids.NotAColumn"):
            schema.column_exists("Bids", "NotAColumn")
