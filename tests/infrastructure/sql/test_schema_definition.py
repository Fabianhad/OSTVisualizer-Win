from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
import unittest
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.infrastructure.sql.schema_definition import (
    SQL_SCHEMA_V1,
    schema_record_is_canonical,
)


class SqlWorkspaceSchemaTests(unittest.TestCase):
    def test_schema_uses_user_scoped_workspace_tables(self):
        tables = {table.name: table for table in SQL_SCHEMA_V1.tables}
        bid_columns = {
            column.name for column in tables["UserBidWorkspaceState"].columns
        }
        page_columns = {
            column.name for column in tables["UserPageWorkspaceState"].columns
        }
        self.assertTrue(
            {"DatabaseGuid", "UserSid", "BidUID", "ActivePageUID"}.issubset(bid_columns)
        )
        self.assertTrue(
            {
                "DatabaseGuid",
                "UserSid",
                "BidUID",
                "PageUID",
                "ZoomFac",
                "CurrentX",
                "CurrentY",
            }.issubset(page_columns)
        )


class SchemaDefinitionCollaborationTests(unittest.TestCase):
    def test_schema_v1_has_canonical_collaboration_objects(self):
        self.assertEqual(SQL_SCHEMA_V1.version, 1)
        self.assertIn(
            "ALLOW_SNAPSHOT_ISOLATION=ON",
            SQL_SCHEMA_V1.canonical_database_requirements,
        )
        tables = {table.name: table for table in SQL_SCHEMA_V1.tables}
        self.assertEqual(
            set(tables),
            {
                "DatabaseMetadata",
                "SchemaMigrations",
                "Sessions",
                "Presence",
                "UserBidWorkspaceState",
                "UserPageWorkspaceState",
                "Locks",
                "EntityVersions",
                "ChangeLog",
                "ChangeFeedState",
                "ExternalAdapterState",
                "ChangeTransactions",
            },
        )
        self.assertIn(
            "Token", {column.name for column in tables["EntityVersions"].columns}
        )
        self.assertIn("BidUID", {column.name for column in tables["Locks"].columns})
        self.assertEqual(
            SQL_SCHEMA_V1.change_tracking_tables,
            (("ostv", "ChangeTransactions"),),
        )
        transaction_columns = {
            column.name for column in tables["ChangeTransactions"].columns
        }
        self.assertTrue(
            {
                "OperationType",
                "RequestHash",
                "ResultFormatVersion",
                "ResultPayload",
            }.issubset(transaction_columns)
        )
        feed_columns = {column.name for column in tables["ChangeFeedState"].columns}
        self.assertEqual(feed_columns, {"SingletonId", "FeedEpoch"})
        self.assertEqual(len(SQL_SCHEMA_V1.checksum), 64)

    def test_extension_tables_are_internally_consistent(self):
        core_tables = {table.name: table for table in SQL_SCHEMA_V1.core_schema.tables}
        ostv_tables = {table.name: table for table in SQL_SCHEMA_V1.tables}
        names = [table.name for table in SQL_SCHEMA_V1.tables]
        self.assertEqual(len(names), len(set(names)))
        constraint_names = []
        for table in SQL_SCHEMA_V1.tables:
            with self.subTest(table=table.name):
                self.assertEqual(table.schema, "ostv")
                columns = {column.name: column for column in table.columns}
                self.assertEqual(len(columns), len(table.columns))
                self.assertTrue(table.primary_key)
                for name in table.primary_key:
                    self.assertIn(name, columns)
                    self.assertFalse(columns[name].nullable)
                for name, unique_columns in table.unique_constraints:
                    constraint_names.append(name)
                    self.assertTrue(set(unique_columns) <= set(columns))
                for index in table.indexes:
                    constraint_names.append(index.name)
                    self.assertTrue(index.columns)
                    self.assertTrue(set(index.columns) <= set(columns))
                for name, expression in table.check_constraints:
                    constraint_names.append(name)
                    self.assertTrue(expression)
                for key in table.foreign_keys:
                    constraint_names.append(key.name)
                    self.assertEqual(len(key.columns), len(key.referenced_columns))
                    self.assertTrue(set(key.columns) <= set(columns))
                    self.assertIn(key.referenced_schema, ("dbo", "ostv"))
                    parent_tables = (
                        core_tables if key.referenced_schema == "dbo" else ostv_tables
                    )
                    parent = parent_tables.get(key.referenced_table)
                    self.assertIsNotNone(parent, key.referenced_table)
                    parent_columns = {column.name for column in parent.columns}
                    self.assertTrue(set(key.referenced_columns) <= parent_columns)
        self.assertEqual(len(constraint_names), len(set(constraint_names)))

    def test_extension_statements_create_schema_tables_then_change_tracking(self):
        statements = SQL_SCHEMA_V1.extension_statements
        self.assertEqual(statements[0], "CREATE SCHEMA [ostv] AUTHORIZATION [dbo]")
        for table in SQL_SCHEMA_V1.tables:
            with self.subTest(table=table.name):
                created = [
                    statement
                    for statement in statements
                    if statement.startswith(f"CREATE TABLE [ostv].[{table.name}]")
                ]
                self.assertEqual(len(created), 1)
        self.assertEqual(
            statements[-1],
            "ALTER TABLE [ostv].[ChangeTransactions] ENABLE CHANGE_TRACKING",
        )
        # Core tables are created before the extension schema references them.
        self.assertEqual(
            SQL_SCHEMA_V1.statements[-len(statements) :], tuple(statements)
        )

    def test_entity_seed_includes_empty_bid_collections_and_annotations(self):
        sql = "\n".join(SQL_SCHEMA_V1.collaboration_initialization_statements)
        self.assertIn("N'annotations_collection'", sql)
        self.assertIn("FROM [dbo].[Bids]", sql)
        self.assertIn("N'projects_collection'", sql)
        self.assertIn("BidALines", sql)
        self.assertNotIn("BidComments", sql)


class SchemaDefinitionDatabaseDescriptorTests(unittest.TestCase):
    def test_sql_schema_v1_is_the_single_complete_schema_definition(self):
        self.assertEqual(SQL_SCHEMA_V1.version, 1)
        self.assertEqual(
            SQL_SCHEMA_V1.checksum,
            "0cecca4baced14d54832a90ead0bac84e743875abca98b0eb173903491dec23c",
        )
        self.assertIn(
            "ALLOW_SNAPSHOT_ISOLATION=ON",
            SQL_SCHEMA_V1.canonical_database_requirements,
        )
        self.assertEqual(
            sum(
                statement.startswith("CREATE TABLE [dbo]")
                for statement in SQL_SCHEMA_V1.statements
            ),
            64,
        )
        self.assertEqual(
            {table.name for table in SQL_SCHEMA_V1.tables},
            {
                "DatabaseMetadata",
                "SchemaMigrations",
                "Sessions",
                "Presence",
                "UserBidWorkspaceState",
                "UserPageWorkspaceState",
                "Locks",
                "EntityVersions",
                "ChangeLog",
                "ChangeFeedState",
                "ExternalAdapterState",
                "ChangeTransactions",
            },
        )
        metadata = next(
            table for table in SQL_SCHEMA_V1.tables if table.name == "DatabaseMetadata"
        )
        self.assertIn("WriterMode", {column.name for column in metadata.columns})
        self.assertFalse(
            any("\nGO\n" in statement.upper() for statement in SQL_SCHEMA_V1.statements)
        )

    def test_canonical_schema_record_rejects_noncanonical_values(self):
        self.assertTrue(
            schema_record_is_canonical(SQL_SCHEMA_V1.version, SQL_SCHEMA_V1.checksum)
        )
        self.assertFalse(schema_record_is_canonical("1", SQL_SCHEMA_V1.checksum))
        self.assertFalse(schema_record_is_canonical(1.0, SQL_SCHEMA_V1.checksum))
        self.assertFalse(schema_record_is_canonical(1, "0" * 64))
        self.assertFalse(schema_record_is_canonical(True, SQL_SCHEMA_V1.checksum))
        self.assertFalse(schema_record_is_canonical(2, SQL_SCHEMA_V1.checksum))
        self.assertFalse(schema_record_is_canonical(1, None))
        self.assertFalse(schema_record_is_canonical(1, SQL_SCHEMA_V1.checksum.upper()))
        self.assertFalse(schema_record_is_canonical(None, SQL_SCHEMA_V1.checksum))


import dataclasses  # noqa: E402
import hashlib  # noqa: E402
from ost_visualizer.application.dtos.collaboration_resource_catalog import (  # noqa: E402
    COLLABORATION_RESOURCE_CATALOG,
)
from ost_visualizer.infrastructure.database.annotation_storage import (  # noqa: E402
    ANNOTATION_TYPE_BY_TABLE,
)
from ost_visualizer.infrastructure.sql.schema_definition import (  # noqa: E402
    SqlColumnDefinition,
    SqlForeignKeyDefinition,
    SqlIndexDefinition,
    SqlSchemaDefinition,
    SqlTableDefinition,
    render_sql_index,
    render_sql_table,
)


class SchemaDefinitionValueObjectTests(unittest.TestCase):
    def test_definitions_are_frozen_value_objects(self):
        table = SQL_SCHEMA_V1.tables[0]
        for label, instance, attribute in (
            ("column", table.columns[0], "name"),
            ("table", table, "name"),
            ("schema", SQL_SCHEMA_V1, "version"),
            (
                "foreign key",
                next(t for t in SQL_SCHEMA_V1.tables if t.foreign_keys).foreign_keys[0],
                "name",
            ),
            (
                "index",
                next(t for t in SQL_SCHEMA_V1.tables if t.indexes).indexes[0],
                "name",
            ),
        ):
            with self.subTest(definition=label):
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    setattr(instance, attribute, "changed")

    def test_definition_defaults_are_the_strict_ones(self):
        column = SqlColumnDefinition("A", "int")
        self.assertEqual(
            (column.nullable, column.identity, column.default), (False, False, "")
        )
        key = SqlForeignKeyDefinition("FK", ("A",), "dbo", "T", ("B",))
        self.assertEqual(key.on_delete, "")
        index = SqlIndexDefinition("IX", ("A",))
        self.assertEqual((index.unique, index.filter_expression), (False, ""))
        table = SqlTableDefinition("ostv", "T", (column,), ("A",))
        self.assertEqual(
            (
                table.foreign_keys,
                table.unique_constraints,
                table.indexes,
                table.check_constraints,
            ),
            ((), (), (), ()),
        )
        schema = SqlSchemaDefinition(1, "x", SQL_SCHEMA_V1.core_schema, (table,))
        self.assertEqual(schema.change_tracking_tables, ())
        self.assertEqual(schema.canonical_database_requirements, ())


class SchemaDefinitionRenderingTests(unittest.TestCase):
    def test_a_table_renders_columns_then_each_constraint_family_in_order(self):
        table = SqlTableDefinition(
            "ostv",
            "Demo",
            (
                SqlColumnDefinition("Id", "bigint", identity=True),
                SqlColumnDefinition("Name", "nvarchar(50)"),
                SqlColumnDefinition("Note", "nvarchar(max)", nullable=True),
                SqlColumnDefinition(
                    "Created", "datetime2(3)", default="SYSUTCDATETIME()"
                ),
            ),
            ("Id",),
            foreign_keys=(
                SqlForeignKeyDefinition(
                    "FK_a", ("Name",), "dbo", "Parent", ("Name",), on_delete="CASCADE"
                ),
                SqlForeignKeyDefinition(
                    "FK_b", ("Note", "Created"), "ostv", "Other", ("A", "B")
                ),
            ),
            unique_constraints=(("UQ_demo", ("Name", "Created")),),
            check_constraints=(("CK_demo", "[Id]>(0)"),),
        )
        self.assertEqual(
            render_sql_table(table),
            "CREATE TABLE [ostv].[Demo] (\n"
            "    [Id] bigint IDENTITY(1,1) NOT NULL,\n"
            "    [Name] nvarchar(50) NOT NULL,\n"
            "    [Note] nvarchar(max) NULL,\n"
            "    [Created] datetime2(3) NOT NULL DEFAULT (SYSUTCDATETIME()),\n"
            "    CONSTRAINT [PK_ostv_Demo] PRIMARY KEY ([Id]),\n"
            "    CONSTRAINT [UQ_demo] UNIQUE ([Name], [Created]),\n"
            "    CONSTRAINT [FK_a] FOREIGN KEY ([Name]) REFERENCES [dbo].[Parent] "
            "([Name]) ON DELETE CASCADE,\n"
            "    CONSTRAINT [FK_b] FOREIGN KEY ([Note], [Created]) REFERENCES "
            "[ostv].[Other] ([A], [B]),\n"
            "    CONSTRAINT [CK_demo] CHECK ([Id]>(0))\n"
            ")",
        )

    def test_a_composite_primary_key_lists_its_columns_in_order(self):
        table = SqlTableDefinition(
            "ostv",
            "Pair",
            (SqlColumnDefinition("B", "int"), SqlColumnDefinition("A", "int")),
            ("B", "A"),
        )
        self.assertIn(
            "CONSTRAINT [PK_ostv_Pair] PRIMARY KEY ([B], [A])", render_sql_table(table)
        )

    def test_indexes_render_uniqueness_columns_and_filter(self):
        table = SqlTableDefinition(
            "ostv", "Demo", (SqlColumnDefinition("A", "int"),), ("A",)
        )
        self.assertEqual(
            render_sql_index(
                table,
                SqlIndexDefinition(
                    "IX_u", ("A", "B"), unique=True, filter_expression="[B] IS NOT NULL"
                ),
            ),
            "CREATE UNIQUE INDEX [IX_u] ON [ostv].[Demo] ([A], [B]) "
            "WHERE [B] IS NOT NULL",
        )
        self.assertEqual(
            render_sql_index(table, SqlIndexDefinition("IX_p", ("A",))),
            "CREATE INDEX [IX_p] ON [ostv].[Demo] ([A])",
        )

    def test_the_real_extension_objects_render_their_filters_and_defaults(self):
        statements = SQL_SCHEMA_V1.extension_statements
        self.assertIn(
            "CREATE INDEX [IX_ostv_Sessions_Heartbeat] ON [ostv].[Sessions] "
            "([LastHeartbeatAt]) WHERE [DisconnectedAt] IS NULL",
            statements,
        )
        self.assertIn(
            "CREATE TABLE [ostv].[ChangeFeedState] (\n"
            "    [SingletonId] tinyint NOT NULL,\n"
            "    [FeedEpoch] uniqueidentifier NOT NULL DEFAULT (NEWID()),\n"
            "    CONSTRAINT [PK_ostv_ChangeFeedState] PRIMARY KEY ([SingletonId]),\n"
            "    CONSTRAINT [CK_ostv_ChangeFeedState_Singleton] CHECK ([SingletonId]=(1))\n"
            ")",
            statements,
        )


class SchemaChecksumContractTests(unittest.TestCase):
    REQUIREMENTS = (
        "ALLOW_SNAPSHOT_ISOLATION=ON",
        "CHANGE_TRACKING_RETENTION=7 DAYS",
        "CHANGE_TRACKING_AUTO_CLEANUP=ON",
    )

    def test_the_canonical_database_requirements_are_these_three(self):
        self.assertEqual(
            SQL_SCHEMA_V1.canonical_database_requirements, self.REQUIREMENTS
        )

    def test_the_checksum_is_the_sha256_of_statements_then_requirements(self):
        text = "\n-- statement --\n".join(SQL_SCHEMA_V1.statements)
        text += "\n-- database requirement --\n" + (
            "\n-- database requirement --\n".join(self.REQUIREMENTS)
        )
        self.assertEqual(
            SQL_SCHEMA_V1.checksum, hashlib.sha256(text.encode("utf-8")).hexdigest()
        )

    def test_the_checksum_depends_on_every_part_of_the_definition(self):
        reference = SQL_SCHEMA_V1.checksum
        without_requirements = dataclasses.replace(
            SQL_SCHEMA_V1, canonical_database_requirements=()
        )
        self.assertEqual(
            without_requirements.checksum,
            hashlib.sha256(
                "\n-- statement --\n".join(without_requirements.statements).encode(
                    "utf-8"
                )
            ).hexdigest(),
        )
        self.assertNotEqual(without_requirements.checksum, reference)
        fewer = dataclasses.replace(
            SQL_SCHEMA_V1, canonical_database_requirements=self.REQUIREMENTS[:2]
        )
        self.assertNotEqual(fewer.checksum, reference)
        reordered = dataclasses.replace(
            SQL_SCHEMA_V1, canonical_database_requirements=self.REQUIREMENTS[::-1]
        )
        self.assertNotEqual(reordered.checksum, reference)
        shuffled = dataclasses.replace(SQL_SCHEMA_V1, tables=SQL_SCHEMA_V1.tables[::-1])
        self.assertNotEqual(shuffled.checksum, reference)
        no_tracking = dataclasses.replace(SQL_SCHEMA_V1, change_tracking_tables=())
        self.assertNotEqual(no_tracking.checksum, reference)

    def test_the_checksum_is_stable_across_reads(self):
        self.assertEqual(SQL_SCHEMA_V1.checksum, SQL_SCHEMA_V1.checksum)
        self.assertEqual(SQL_SCHEMA_V1.statements, SQL_SCHEMA_V1.statements)


class SchemaDefinitionSeedTests(unittest.TestCase):
    PREFIX = (
        "INSERT INTO [ostv].[EntityVersions] ([ResourceType], [ResourceId], [BidUID]) "
    )

    def _expected(self):
        entity = []
        for key, definition in COLLABORATION_RESOURCE_CATALOG.items():
            if not definition.entity_table:
                continue
            bid = (
                f"CONVERT(int, [{definition.entity_bid_column}])"
                if definition.entity_bid_column
                else "NULL"
            )
            where = f" WHERE {definition.seed_filter}" if definition.seed_filter else ""
            entity.append(
                f"{self.PREFIX}SELECT N'{key}', CONVERT(nvarchar(128), "
                f"[{definition.entity_uid_column}]), {bid} "
                f"FROM [dbo].[{definition.entity_table}]{where}"
            )
        static = [
            f"{self.PREFIX}VALUES (N'{kind}', N'database', NULL)"
            for kind in (
                "projects_collection",
                "job_statuses_collection",
                "employees_collection",
                "pay_classes_collection",
                "condition_types_collection",
                "default_layers_collection",
            )
        ]
        orphan = [f"{self.PREFIX}VALUES (N'project_bids', N'orphan', NULL)"]
        annotations = [
            f"{self.PREFIX}SELECT N'annotation', N'{kind}/' + "
            f"CONVERT(nvarchar(100), [UID]), CONVERT(int, [BidUID]) FROM [dbo].[{table}]"
            for table, kind in ANNOTATION_TYPE_BY_TABLE.items()
        ]
        collections = [
            f"{self.PREFIX}SELECT N'{key}', CONVERT(nvarchar(128), [UID]), "
            "CONVERT(int, [UID]) FROM [dbo].[Bids]"
            for key, definition in COLLABORATION_RESOURCE_CATALOG.items()
            if definition.collection and definition.bid_scoped
        ]
        tail = [
            f"{self.PREFIX}SELECT N'project_bids', CONVERT(nvarchar(128), [UID]), "
            "NULL FROM [dbo].[BidProjects]",
            "INSERT INTO [ostv].[ChangeFeedState] ([SingletonId]) VALUES (1)",
            "INSERT INTO [ostv].[ExternalAdapterState] ([SingletonId]) VALUES (1)",
        ]
        return entity + static + orphan + annotations + collections + tail

    def test_the_initialisation_statements_are_exactly_these_in_this_order(self):
        self.assertEqual(
            list(SQL_SCHEMA_V1.collaboration_initialization_statements),
            self._expected(),
        )

    def test_representative_seeds_are_pinned_verbatim(self):
        statements = SQL_SCHEMA_V1.collaboration_initialization_statements
        for literal in (
            self.PREFIX + "SELECT N'layer', CONVERT(nvarchar(128), [UID]), "
            "CONVERT(int, [BidUID]) FROM [dbo].[BidLayers] WHERE [IsTemplate]=0",
            self.PREFIX + "SELECT N'takeoffs_collection', CONVERT(nvarchar(128), "
            "[UID]), CONVERT(int, [UID]) FROM [dbo].[Bids]",
            self.PREFIX + "SELECT N'annotation', N'line/' + CONVERT(nvarchar(100), "
            "[UID]), CONVERT(int, [BidUID]) FROM [dbo].[BidALines]",
            self.PREFIX + "VALUES (N'projects_collection', N'database', NULL)",
            self.PREFIX + "VALUES (N'project_bids', N'orphan', NULL)",
            self.PREFIX + "SELECT N'project_bids', CONVERT(nvarchar(128), [UID]), "
            "NULL FROM [dbo].[BidProjects]",
        ):
            with self.subTest(statement=literal[:90]):
                self.assertEqual(statements.count(literal), 1)

    def test_every_resource_type_except_the_database_has_a_seed(self):
        seeded = set()
        for statement in SQL_SCHEMA_V1.collaboration_initialization_statements:
            if statement.startswith(self.PREFIX):
                seeded.add(statement.split("N'")[1].split("'")[0])
        self.assertEqual(seeded, set(COLLABORATION_RESOURCE_CATALOG) - {"database"})

    def test_the_seed_statements_only_touch_tables_of_the_canonical_schema(self):
        tables = {("dbo", t.name) for t in SQL_SCHEMA_V1.core_schema.tables} | {
            (t.schema, t.name) for t in SQL_SCHEMA_V1.tables
        }
        import re

        for statement in SQL_SCHEMA_V1.collaboration_initialization_statements:
            for schema, name in re.findall(r"\[(dbo|ostv)\]\.\[(\w+)\]", statement):
                with self.subTest(table=f"{schema}.{name}"):
                    self.assertIn((schema, name), tables)


class SchemaRecordCanonicalContractTests(unittest.TestCase):
    def test_the_answer_is_a_real_bool_and_the_checksum_must_be_a_str(self):
        class _EqualsEverything:
            def __eq__(self, _other):
                return True

            __hash__ = None

        self.assertIs(
            schema_record_is_canonical(SQL_SCHEMA_V1.version, SQL_SCHEMA_V1.checksum),
            True,
        )
        for version, checksum in (
            (2, SQL_SCHEMA_V1.checksum),
            (SQL_SCHEMA_V1.version, "0" * 64),
            (SQL_SCHEMA_V1.version, None),
            (SQL_SCHEMA_V1.version, b"0"),
            (SQL_SCHEMA_V1.version, _EqualsEverything()),
            ("1", SQL_SCHEMA_V1.checksum),
            (True, SQL_SCHEMA_V1.checksum),
        ):
            with self.subTest(version=version, checksum=type(checksum).__name__):
                self.assertIs(schema_record_is_canonical(version, checksum), False)
