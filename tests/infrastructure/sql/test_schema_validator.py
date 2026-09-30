from ost_visualizer.infrastructure.sql.schema_validator import SqlSchemaValidator
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
import unittest
import os
from dataclasses import replace
from ost_visualizer.infrastructure.sql.schema_inspector import (
    SqlSchemaInspector,
    SqlSchemaInventory,
)
from ost_visualizer.infrastructure.sql.schema_validator import (
    SqlSchemaValidationReport,
    SqlSchemaValidator,
)
from tests.helpers.sql.cleanup_support import (
    _empty_inventory as _cleanup_support__empty_inventory,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.infrastructure.mdb.database_creator import (
    get_reference_schema_model,
)
from ost_visualizer.infrastructure.sql.schema_definition import (
    SQL_SCHEMA_V1,
    schema_record_is_canonical,
)
from ost_visualizer.infrastructure.sql.schema_inspector import (
    SqlColumnInventory,
    SqlSchemaInventory,
)
from ost_visualizer.infrastructure.sql.schema_validator import (
    SqlSchemaValidator,
    _matches_type,
    _normalize_filter,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class SchemaValidatorCollaborationTests(unittest.TestCase):
    def test_schema_v1_requires_snapshot_isolation_and_tracking_configuration(self):
        inventory = type(
            "Inventory",
            (),
            {
                "snapshot_isolation_enabled": False,
                "change_tracking_retention_days": 6,
                "change_tracking_auto_cleanup": False,
            },
        )()
        self.assertEqual(
            SqlSchemaValidator._validate_database_requirements(
                inventory, SQL_SCHEMA_V1
            ),
            [
                "database.snapshot_isolation",
                "database.change_tracking_retention",
                "database.change_tracking_auto_cleanup",
            ],
        )


class SchemaValidatorSqlCleanupTests(unittest.TestCase):
    def test_sql_schema_rejects_conflicting_core_table_outside_dbo(self):
        inventory = replace(
            _cleanup_support__empty_inventory(),
            schema_version=SQL_SCHEMA_V1.version,
            schema_checksum=SQL_SCHEMA_V1.checksum,
            tables=frozenset({("custom", "Bids")}),
        )
        report = SqlSchemaValidator(SQL_SCHEMA_V1.core_schema).validate(inventory)
        self.assertIn("custom.Bids.shadows_dbo", report.problems)


class SchemaValidatorDatabaseDescriptorTests(unittest.TestCase):
    def test_schema_validator_accepts_only_complete_canonical_v1(self):
        def inventory(version, checksum=""):
            return SqlSchemaInventory(
                database_guid="",
                schema_version=version,
                schema_checksum=checksum,
                tables=frozenset(),
                columns=(),
                foreign_keys=(),
                indexes=(),
                views=(),
                triggers=(),
                procedures=(),
                functions=(),
            )

        validator = SqlSchemaValidator(get_reference_schema_model())
        partial = validator.validate(
            inventory(SQL_SCHEMA_V1.version, SQL_SCHEMA_V1.checksum)
        )
        self.assertFalse(partial.is_valid)
        unsupported = validator.validate(inventory(99))
        self.assertFalse(unsupported.is_valid)
        self.assertEqual(
            unsupported.problems,
            ("ostv.DatabaseMetadata.SchemaVersion",),
        )

    def test_schema_validator_rejects_noncanonical_ostv_tables_and_columns(self):
        inventory = SqlSchemaInventory(
            database_guid="",
            schema_version=SQL_SCHEMA_V1.version,
            schema_checksum=SQL_SCHEMA_V1.checksum,
            tables=frozenset(
                {
                    ("ostv", "Sessions"),
                    ("ostv", "UnexpectedState"),
                }
            ),
            columns=(
                SqlColumnInventory(
                    "ostv",
                    "Sessions",
                    "UnexpectedCheckpoint",
                    "bigint",
                    8,
                    0,
                    False,
                    False,
                    False,
                ),
            ),
            foreign_keys=(),
            indexes=(),
            views=(),
            triggers=(),
            procedures=(),
            functions=(),
        )
        problems = SqlSchemaValidator._validate_ostv_tables(inventory, SQL_SCHEMA_V1)
        self.assertIn("ostv.UnexpectedState.unexpected", problems)
        self.assertIn("ostv.Sessions.UnexpectedCheckpoint.unexpected", problems)

    def test_sql_server_schema_normalization_matches_server_inventory(self):
        rowversion = SqlColumnInventory(
            "ostv",
            "Sessions",
            "Version",
            "timestamp",
            8,
            0,
            False,
            False,
            False,
            "",
        )
        self.assertTrue(_matches_type(rowversion, "rowversion"))
        self.assertEqual(
            _normalize_filter("([DisconnectedAt] IS NULL)"),
            _normalize_filter("[DisconnectedAt] IS NULL"),
        )
        expected_checks = {
            name: expression
            for table in SQL_SCHEMA_V1.tables
            for name, expression in table.check_constraints
        }
        server_checks = {
            "CK_ostv_Presence_ActivityMode": (
                "([ActivityMode]=N'editing' OR [ActivityMode]=N'viewing')"
            ),
            "CK_ostv_ChangeLog_Operation": (
                "([Operation]=N'bulk_refresh' OR [Operation]=N'reorder' OR "
                "[Operation]=N'move' OR [Operation]=N'delete' OR "
                "[Operation]=N'update' OR [Operation]=N'create')"
            ),
            "CK_ostv_ChangeLog_ChangedFieldsJson": (
                "([ChangedFields] IS NULL OR isjson([ChangedFields])=(1))"
            ),
            "CK_ostv_ChangeLog_PayloadJson": (
                "([Payload] IS NULL OR isjson([Payload])=(1))"
            ),
            "CK_ostv_ChangeFeedState_Singleton": "([SingletonId]=(1))",
        }
        for name, actual in server_checks.items():
            self.assertEqual(
                _normalize_filter(actual),
                _normalize_filter(expected_checks[name]),
                name,
            )
