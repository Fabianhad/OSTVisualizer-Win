import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.infrastructure.database.schema_model import render_sql_server_schema
from ost_visualizer.infrastructure.mdb.database_creator import (
    get_reference_schema_model,
)


class SchemaContractDatabaseDescriptorTests(unittest.TestCase):
    def test_shared_schema_model_covers_complete_reference_schema(self):
        model = get_reference_schema_model()
        self.assertEqual(len(model.tables), 64)
        self.assertEqual(model.column_count, 668)
        statements = render_sql_server_schema(model)
        self.assertEqual(sum(sql.startswith("CREATE TABLE") for sql in statements), 64)
        self.assertTrue(any("varbinary(max)" in sql for sql in statements))
        self.assertTrue(any("datetime2(3)" in sql for sql in statements))
