import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.infrastructure.database.schema_model import render_sql_server_schema
from ost_visualizer.infrastructure.mdb.database_creator import (
    get_reference_schema_model,
)

# Written independently of sql_server_type_for_access: the contract is that the
# reference Access types map to exactly these SQL Server types.
_SQL_TYPE_FOR_ACCESS_TYPE = {
    "COUNTER": "int IDENTITY(1,1)",
    "INTEGER": "int",
    "SMALLINT": "smallint",
    "DOUBLE": "float",
    "YESNO": "bit",
    "IMAGE": "varbinary(max)",
    "DATETIME": "datetime2(3)",
}


def _expected_sql_type(access_type):
    normalized = access_type.strip().upper()
    if normalized.startswith("VARCHAR(") and normalized.endswith(")"):
        return "nvarchar(" + normalized[len("VARCHAR(") : -1] + ")"
    return _SQL_TYPE_FOR_ACCESS_TYPE[normalized]


class SchemaContractDatabaseDescriptorTests(unittest.TestCase):
    def test_shared_schema_model_covers_complete_reference_schema(self):
        model = get_reference_schema_model()
        self.assertEqual(len(model.tables), 64)
        self.assertEqual(model.column_count, 668)
        statements = render_sql_server_schema(model)
        self.assertEqual(sum(sql.startswith("CREATE TABLE") for sql in statements), 64)
        self.assertTrue(any("varbinary(max)" in sql for sql in statements))
        self.assertTrue(any("datetime2(3)" in sql for sql in statements))

    def test_rendered_schema_declares_every_reference_column_with_its_sql_type(self):
        model = get_reference_schema_model()
        statements = render_sql_server_schema(model)
        create_statements = {
            sql.split("]", 2)[1].lstrip(".["): sql
            for sql in statements
            if sql.startswith("CREATE TABLE")
        }
        self.assertEqual(set(create_statements), set(model.table_names))
        rendered_columns = 0
        for table in model.tables:
            with self.subTest(table=table.name):
                lines = [
                    line.strip().rstrip(",")
                    for line in create_statements[table.name].splitlines()[1:-1]
                ]
                self.assertEqual(len(lines), len(table.columns))
                for column, line in zip(table.columns, lines):
                    sql_type = _expected_sql_type(column.access_type)
                    expected = f"[{column.name}] {sql_type}"
                    expected += " NOT NULL" if column.required else " NULL"
                    if column.default is not None:
                        expected += f" DEFAULT ({column.default})"
                    if column.primary_key:
                        expected += " PRIMARY KEY"
                    self.assertEqual(line, expected)
                    rendered_columns += 1
        self.assertEqual(rendered_columns, model.column_count)

    def test_rendered_schema_declares_every_index_and_foreign_key_once(self):
        model = get_reference_schema_model()
        statements = render_sql_server_schema(model)
        indexes = [
            s
            for s in statements
            if s.startswith(("CREATE INDEX", "CREATE UNIQUE INDEX"))
        ]
        foreign_keys = [s for s in statements if s.startswith("ALTER TABLE")]
        self.assertEqual(
            len(indexes), sum(len(table.indexes) for table in model.tables)
        )
        self.assertEqual(len(foreign_keys), len(model.foreign_keys))
        self.assertGreater(len(foreign_keys), 0)
        for table in model.tables:
            for index in table.indexes:
                columns = ", ".join(f"[{name}]" for name in index.columns)
                prefix = "CREATE UNIQUE INDEX" if index.unique else "CREATE INDEX"
                self.assertIn(
                    f"{prefix} [{index.name}] ON [dbo].[{table.name}] ({columns})",
                    indexes,
                )
        for fk in model.foreign_keys:
            self.assertIn(
                f"ALTER TABLE [dbo].[{fk.child_table}] ADD CONSTRAINT [{fk.name}] "
                f"FOREIGN KEY ([{fk.child_column}]) REFERENCES "
                f"[dbo].[{fk.parent_table}] ([{fk.parent_column}])",
                foreign_keys,
            )
        self.assertEqual(len(statements), 64 + len(indexes) + len(foreign_keys))

    def test_statements_are_ordered_tables_then_indexes_then_foreign_keys(self):
        model = get_reference_schema_model()
        statements = render_sql_server_schema(model)
        tables = len(model.tables)
        indexes = sum(len(table.indexes) for table in model.tables)
        self.assertEqual(len(statements), tables + indexes + len(model.foreign_keys))
        self.assertTrue(all(s.startswith("CREATE TABLE") for s in statements[:tables]))
        self.assertTrue(
            all(
                s.startswith(("CREATE INDEX", "CREATE UNIQUE INDEX"))
                for s in statements[tables : tables + indexes]
            )
        )
        self.assertTrue(
            all(s.startswith("ALTER TABLE") for s in statements[tables + indexes :])
        )
        self.assertEqual(len(set(statements)), len(statements))
        # Tables come in model order, so a foreign key can reference any of them.
        self.assertEqual(
            [s.split("]", 2)[1].lstrip(".[") for s in statements[:tables]],
            [table.name for table in model.tables],
        )

    def test_constraints_reference_existing_columns_of_matching_type_and_unique_parents(
        self,
    ):
        """What SQL Server enforces when the ALTER TABLE statements run (rules a text
        comparison of the rendered DDL cannot see): referenced tables and columns exist,
        child and parent columns have the same type, and the parent column is unique.
        Table names are resolved case-insensitively, as on the default server collation.
        """
        model = get_reference_schema_model()
        by_name = {table.name.casefold(): table for table in model.tables}

        def column(table, name):
            matches = [c for c in table.columns if c.name.casefold() == name.casefold()]
            self.assertEqual(len(matches), 1, (table.name, name))
            return matches[0]

        def base_type(access_type):
            return _expected_sql_type(access_type).replace(" IDENTITY(1,1)", "")

        for table in model.tables:
            names = {c.name for c in table.columns}
            self.assertEqual(len(names), len(table.columns), table.name)
            self.assertEqual(sum(c.primary_key for c in table.columns), 1, table.name)
            for index in table.indexes:
                with self.subTest(table=table.name, index=index.name):
                    self.assertTrue(index.columns)
                    self.assertLessEqual(set(index.columns), names)
        constraint_names = [fk.name for fk in model.foreign_keys]
        self.assertEqual(len(set(constraint_names)), len(constraint_names))
        for fk in model.foreign_keys:
            with self.subTest(foreign_key=fk.name):
                child_table = by_name[fk.child_table.casefold()]
                parent_table = by_name[fk.parent_table.casefold()]
                child = column(child_table, fk.child_column)
                parent = column(parent_table, fk.parent_column)
                self.assertEqual(
                    base_type(child.access_type), base_type(parent.access_type)
                )
                self.assertTrue(
                    parent.primary_key
                    or any(
                        index.unique and index.columns == (parent.name,)
                        for index in parent_table.indexes
                    )
                )
