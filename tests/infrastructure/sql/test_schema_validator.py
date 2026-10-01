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
from ost_visualizer.infrastructure.database.schema_model import (
    sql_server_type_for_access,
)
from ost_visualizer.infrastructure.sql.schema_inspector import (
    SqlCheckConstraintInventory,
    SqlColumnInventory,
    SqlForeignKeyInventory,
    SqlIndexInventory,
    SqlSchemaInventory,
)
from ost_visualizer.infrastructure.sql.schema_validator import (
    SqlSchemaValidator,
    _matches_default,
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
        # The dbo copy is still missing, so the shadow cannot satisfy the schema.
        self.assertIn("dbo.Bids", report.problems)
        self.assertFalse(report.is_valid)


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
        self.assertIn("dbo.Bids", partial.problems)
        self.assertIn("ostv.Sessions", partial.problems)
        self.assertNotIn("ostv.SchemaMigrations.Checksum", partial.problems)
        self.assertTrue(validator.validate(_canonical_inventory()).is_valid)
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


def _inventory_column(
    schema_name, table_name, name, sql_type, nullable, identity, default=""
):
    type_name = sql_type.casefold().replace(" identity(1,1)", "")
    length = None
    if "(" in type_name:
        type_name, argument = type_name[:-1].split("(")
        length = argument
    if type_name == "rowversion":
        type_name = "timestamp"
    max_length = 0
    scale = 0
    if type_name == "datetime2":
        scale = int(length)
        max_length = 8
    elif length == "max":
        max_length = -1
    elif length is not None:
        max_length = int(length) * (2 if type_name == "nvarchar" else 1)
    return SqlColumnInventory(
        schema_name,
        table_name,
        name,
        type_name,
        max_length,
        scale,
        nullable,
        identity,
        False,
        default,
    )


def _canonical_inventory():
    """Build the catalog inventory SQL Server would report for canonical v1."""
    core = SQL_SCHEMA_V1.core_schema
    tables = {("dbo", table.name) for table in core.tables}
    columns = []
    indexes = []
    foreign_keys = []
    check_constraints = []
    for table in core.tables:
        primary = tuple(column.name for column in table.columns if column.primary_key)
        if primary:
            indexes.append(
                SqlIndexInventory(
                    "dbo", table.name, f"PK_{table.name}", True, True, primary, ""
                )
            )
        for index in table.indexes:
            indexes.append(
                SqlIndexInventory(
                    "dbo",
                    table.name,
                    index.name,
                    index.unique,
                    False,
                    index.columns,
                    "",
                )
            )
        for column in table.columns:
            columns.append(
                _inventory_column(
                    "dbo",
                    table.name,
                    column.name,
                    sql_server_type_for_access(column.access_type),
                    not column.required,
                    column.access_type.strip().upper() == "COUNTER",
                    column.default or "",
                )
            )
    for key in core.foreign_keys:
        foreign_keys.append(
            SqlForeignKeyInventory(
                key.name,
                "dbo",
                key.child_table,
                key.child_column,
                "dbo",
                key.parent_table,
                key.parent_column,
            )
        )
    for table in SQL_SCHEMA_V1.tables:
        tables.add((table.schema, table.name))
        indexes.append(
            SqlIndexInventory(
                table.schema,
                table.name,
                f"PK_{table.name}",
                True,
                True,
                table.primary_key,
                "",
            )
        )
        for name, unique_columns in table.unique_constraints:
            indexes.append(
                SqlIndexInventory(
                    table.schema, table.name, name, True, False, unique_columns, ""
                )
            )
        for index in table.indexes:
            indexes.append(
                SqlIndexInventory(
                    table.schema,
                    table.name,
                    index.name,
                    index.unique,
                    False,
                    index.columns,
                    index.filter_expression,
                )
            )
        for column in table.columns:
            columns.append(
                _inventory_column(
                    table.schema,
                    table.name,
                    column.name,
                    column.data_type,
                    column.nullable,
                    column.identity,
                    column.default,
                )
            )
        for key in table.foreign_keys:
            for child, parent in zip(key.columns, key.referenced_columns):
                foreign_keys.append(
                    SqlForeignKeyInventory(
                        key.name,
                        table.schema,
                        table.name,
                        child,
                        key.referenced_schema,
                        key.referenced_table,
                        parent,
                        (
                            key.on_delete.replace(" ", "_")
                            if key.on_delete
                            else "NO_ACTION"
                        ),
                    )
                )
        for name, expression in table.check_constraints:
            check_constraints.append(
                SqlCheckConstraintInventory(
                    table.schema, table.name, name, f"({expression})"
                )
            )
    return SqlSchemaInventory(
        database_guid="00000000-0000-0000-0000-000000000001",
        schema_version=SQL_SCHEMA_V1.version,
        schema_checksum=SQL_SCHEMA_V1.checksum,
        tables=frozenset(tables),
        columns=tuple(columns),
        foreign_keys=tuple(foreign_keys),
        indexes=tuple(indexes),
        views=(),
        triggers=(),
        procedures=(),
        functions=(),
        check_constraints=tuple(check_constraints),
        change_tracking_enabled=True,
        change_tracking_tables=frozenset(SQL_SCHEMA_V1.change_tracking_tables),
        snapshot_isolation_enabled=True,
        change_tracking_retention_days=7,
        change_tracking_auto_cleanup=True,
    )


class SchemaValidatorCanonicalInventoryTests(unittest.TestCase):
    def setUp(self):
        self.validator = SqlSchemaValidator(SQL_SCHEMA_V1.core_schema)
        self.canonical = _canonical_inventory()

    def _problems(self, inventory):
        return self.validator.validate(inventory).problems

    def test_inventory_matching_canonical_v1_has_no_problems(self):
        report = self.validator.validate(self.canonical)
        self.assertEqual(report.problems, ())
        self.assertTrue(report.is_valid)
        self.assertEqual(report.user_message, "")

    def test_problem_report_message_lists_every_problem(self):
        report = self.validator.validate(
            replace(
                self.canonical,
                schema_checksum="0" * 64,
                snapshot_isolation_enabled=False,
            )
        )
        self.assertEqual(
            report.problems,
            ("database.snapshot_isolation", "ostv.SchemaMigrations.Checksum"),
        )
        self.assertEqual(
            report.user_message,
            "Schema mismatch: database.snapshot_isolation, ostv.SchemaMigrations.Checksum",
        )

    def test_core_table_and_column_drift_is_reported_by_exact_label(self):
        canonical = self.canonical
        job_name = next(
            c
            for c in canonical.columns
            if (c.table_name, c.column_name) == ("Bids", "JobName")
        )

        def without(column):
            return tuple(c for c in canonical.columns if c is not column)

        def swapped(column, **changes):
            return tuple(
                replace(c, **changes) if c is column else c for c in canonical.columns
            )

        uid = next(
            c
            for c in canonical.columns
            if (c.table_name, c.column_name) == ("Bids", "UID")
        )
        cases = {
            "dbo.Bids": replace(
                canonical,
                tables=canonical.tables - {("dbo", "Bids")},
                columns=tuple(c for c in canonical.columns if c.table_name != "Bids"),
            ),
            "dbo.Surprise.unexpected": replace(
                canonical, tables=canonical.tables | {("dbo", "Surprise")}
            ),
            "dbo.Bids.JobName": replace(canonical, columns=without(job_name)),
            "dbo.Bids.Extra.unexpected": replace(
                canonical,
                columns=canonical.columns
                + (_inventory_column("dbo", "Bids", "Extra", "int", True, False),),
            ),
            "dbo.Bids.JobName (type)": replace(
                canonical, columns=swapped(job_name, data_type="int", max_length=4)
            ),
            "dbo.Bids.JobName (length)": replace(
                canonical, columns=swapped(job_name, max_length=job_name.max_length + 2)
            ),
            "dbo.Bids.JobName.nullability": replace(
                canonical, columns=swapped(job_name, nullable=not job_name.nullable)
            ),
            "dbo.Bids.UID.identity": replace(
                canonical, columns=swapped(uid, identity=False)
            ),
            "dbo.Bids.JobName.computed": replace(
                canonical, columns=swapped(job_name, computed=True)
            ),
            "dbo.Bids.JobName.default": replace(
                canonical,
                columns=swapped(job_name, default_definition="(N'unexpected')"),
            ),
            "other.Bids.shadows_dbo": replace(
                canonical, tables=canonical.tables | {("other", "Bids")}
            ),
        }
        for label, inventory in cases.items():
            with self.subTest(label=label):
                expected = label.split(" ")[0]
                problems = self._problems(inventory)
                self.assertIn(expected, problems)
                self.assertNotEqual(problems, ())
        self.assertEqual(
            self._problems(cases["dbo.Bids.JobName (type)"]), ("dbo.Bids.JobName",)
        )
        self.assertEqual(
            self._problems(cases["dbo.Bids.JobName (length)"]), ("dbo.Bids.JobName",)
        )
        self.assertEqual(
            self._problems(cases["dbo.Bids.JobName.nullability"]),
            ("dbo.Bids.JobName.nullability",),
        )

    def test_core_key_index_and_relationship_drift_is_reported(self):
        canonical = self.canonical
        bid_primary = next(
            i
            for i in canonical.indexes
            if (i.table_name, i.primary_key) == ("Bids", True)
        )
        indexed = next(
            i for i in canonical.indexes if i.schema_name == "dbo" and not i.primary_key
        )
        key = next(k for k in canonical.foreign_keys if k.child_schema == "dbo")
        self.assertEqual(
            self._problems(
                replace(
                    canonical,
                    indexes=tuple(i for i in canonical.indexes if i is not bid_primary),
                )
            ),
            ("dbo.Bids.primary_key",),
        )
        self.assertEqual(
            self._problems(
                replace(
                    canonical,
                    indexes=tuple(
                        replace(i, columns=("Other",)) if i is indexed else i
                        for i in canonical.indexes
                    ),
                )
            ),
            (f"dbo.{indexed.table_name}.{indexed.index_name}",),
        )
        self.assertEqual(
            self._problems(
                replace(
                    canonical,
                    indexes=tuple(
                        (
                            replace(i, filter_expression="[X] IS NOT NULL")
                            if i is indexed
                            else i
                        )
                        for i in canonical.indexes
                    ),
                )
            ),
            (f"dbo.{indexed.table_name}.{indexed.index_name}",),
        )
        self.assertEqual(
            self._problems(
                replace(
                    canonical,
                    foreign_keys=tuple(
                        k for k in canonical.foreign_keys if k is not key
                    ),
                )
            ),
            (f"dbo.{key.child_table}.{key.name}",),
        )

    def test_ostv_table_constraint_drift_is_reported_by_exact_label(self):
        canonical = self.canonical

        def pick(sequence, predicate):
            return next(item for item in sequence if predicate(item))

        sessions_pk = pick(
            canonical.indexes,
            lambda i: (i.schema_name, i.table_name, i.primary_key)
            == ("ostv", "Sessions", True),
        )
        heartbeat = pick(
            canonical.indexes,
            lambda i: i.index_name == "IX_ostv_Sessions_Heartbeat",
        )
        sessions_fk = pick(
            canonical.foreign_keys,
            lambda k: k.name == "FK_ostv_Sessions_DatabaseMetadata",
        )
        unique_flag = pick(
            canonical.indexes,
            lambda i: i.index_name == "IX_ostv_Sessions_ClientHeartbeat",
        )
        cascade_fk = pick(
            canonical.foreign_keys,
            lambda k: k.name == "FK_ostv_UserBidWorkspaceState_Bids",
        )
        presence_check = pick(
            canonical.check_constraints,
            lambda c: c.name == "CK_ostv_Presence_ActivityMode",
        )
        session_id = pick(
            canonical.columns,
            lambda c: (c.schema_name, c.table_name, c.column_name)
            == ("ostv", "Sessions", "SessionId"),
        )
        self.assertEqual(cascade_fk.on_delete_action, "CASCADE")
        cases = {
            "ostv.Sessions.primary_key": replace(
                canonical,
                indexes=tuple(i for i in canonical.indexes if i is not sessions_pk),
            ),
            "ostv.Sessions.IX_ostv_Sessions_Heartbeat": replace(
                canonical,
                indexes=tuple(
                    replace(i, filter_expression="") if i is heartbeat else i
                    for i in canonical.indexes
                ),
            ),
            "ostv.Sessions.IX_ostv_Sessions_ClientHeartbeat": replace(
                canonical,
                indexes=tuple(
                    replace(i, unique=True) if i is unique_flag else i
                    for i in canonical.indexes
                ),
            ),
            "ostv.Sessions.FK_ostv_Sessions_DatabaseMetadata": replace(
                canonical,
                foreign_keys=tuple(
                    k for k in canonical.foreign_keys if k is not sessions_fk
                ),
            ),
            "ostv.UserBidWorkspaceState.FK_ostv_UserBidWorkspaceState_Bids": replace(
                canonical,
                foreign_keys=tuple(
                    replace(k, on_delete_action="NO_ACTION") if k is cascade_fk else k
                    for k in canonical.foreign_keys
                ),
            ),
            "ostv.Presence.CK_ostv_Presence_ActivityMode": replace(
                canonical,
                check_constraints=tuple(
                    (
                        replace(c, definition="([ActivityMode]=N'editing')")
                        if c is presence_check
                        else c
                    )
                    for c in canonical.check_constraints
                ),
            ),
            "ostv.Sessions.SessionId": replace(
                canonical,
                columns=tuple(
                    replace(c, nullable=True) if c is session_id else c
                    for c in canonical.columns
                ),
            ),
            "ostv.Sessions": replace(
                canonical,
                tables=canonical.tables - {("ostv", "Sessions")},
                columns=tuple(
                    c for c in canonical.columns if c.table_name != "Sessions"
                ),
            ),
            "ostv.UnexpectedState.unexpected": replace(
                canonical, tables=canonical.tables | {("ostv", "UnexpectedState")}
            ),
        }
        for label, inventory in cases.items():
            with self.subTest(label=label):
                self.assertIn(label, self._problems(inventory))
        # A missing check constraint is as much a mismatch as an altered one.
        self.assertIn(
            "ostv.Presence.CK_ostv_Presence_ActivityMode",
            self._problems(
                replace(
                    canonical,
                    check_constraints=tuple(
                        c
                        for c in canonical.check_constraints
                        if c is not presence_check
                    ),
                )
            ),
        )

    def test_change_tracking_database_and_checksum_drift_is_reported(self):
        canonical = self.canonical
        self.assertEqual(
            self._problems(
                replace(
                    canonical,
                    change_tracking_enabled=False,
                    change_tracking_tables=frozenset(),
                )
            ),
            ("database.change_tracking", "ostv.ChangeTransactions.change_tracking"),
        )
        self.assertEqual(
            self._problems(replace(canonical, change_tracking_tables=frozenset())),
            ("ostv.ChangeTransactions.change_tracking",),
        )
        self.assertEqual(
            self._problems(replace(canonical, change_tracking_retention_days=-1)),
            ("database.change_tracking_retention",),
        )
        self.assertEqual(
            self._problems(replace(canonical, schema_checksum="0" * 64)),
            ("ostv.SchemaMigrations.Checksum",),
        )
        self.assertEqual(
            self._problems(replace(canonical, schema_version=2)),
            ("ostv.DatabaseMetadata.SchemaVersion",),
        )


class SchemaValidatorNormalizationTests(unittest.TestCase):
    def test_type_matching_respects_length_scale_and_family(self):
        def column(data_type, max_length=0, scale=0):
            return SqlColumnInventory(
                "dbo", "T", "C", data_type, max_length, scale, False, False, False
            )

        self.assertTrue(_matches_type(column("nvarchar", 100), "nvarchar(50)"))
        self.assertFalse(_matches_type(column("nvarchar", 50), "nvarchar(50)"))
        self.assertFalse(_matches_type(column("varchar", 100), "nvarchar(50)"))
        self.assertTrue(_matches_type(column("nvarchar", -1), "nvarchar(max)"))
        self.assertFalse(_matches_type(column("nvarchar", 4000), "nvarchar(max)"))
        self.assertTrue(_matches_type(column("varbinary", -1), "varbinary(max)"))
        self.assertTrue(_matches_type(column("char", 64), "char(64)"))
        self.assertTrue(_matches_type(column("datetime2", 8, 3), "datetime2(3)"))
        self.assertFalse(_matches_type(column("datetime2", 8, 7), "datetime2(3)"))
        self.assertFalse(_matches_type(column("datetime", 8, 3), "datetime2(3)"))
        self.assertTrue(_matches_type(column("int", 4), "int IDENTITY(1,1)"))
        self.assertFalse(_matches_type(column("bigint", 8), "int"))
        self.assertFalse(_matches_type(column("int", 4), "rowversion"))
        self.assertTrue(_matches_type(column("rowversion", 8), "rowversion"))

    def test_default_matching_ignores_server_parentheses_but_not_values(self):
        self.assertTrue(_matches_default("((0))", "0"))
        self.assertTrue(_matches_default("(N'x')", "N'x'"))
        self.assertTrue(_matches_default("", None))
        self.assertFalse(_matches_default("((1))", "0"))
        self.assertFalse(_matches_default("((0))", None))
        self.assertFalse(_matches_default("", "0"))
