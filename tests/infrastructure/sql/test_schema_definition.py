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
