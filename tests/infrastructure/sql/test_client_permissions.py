from tests.helpers.sql.strict_sql_fakes import (
    StrictLeaseProxy,
    strict_cursor,
    strict_manager,
)
import os
import unittest
from ost_visualizer.infrastructure.sql.client_permissions import (
    SQL_CLIENT_DATABASE_ROLES,
    SQL_CLIENT_DIRECT_WRITE_TABLES,
    SQL_CLIENT_PROTECTED_OSTV_TABLES,
    _sql_integer_values_match,
    apply_sql_client_permissions,
    require_sql_client_editability,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlInfrastructureError,
)
from tests.helpers.sql.cleanup_support import (
    _CreationCursor as _cleanup_support__CreationCursor,
)
from tests.helpers.sql.creation_handoff_support import (
    _Lease as _creation_handoff_support__Lease,
    _snapshot as _creation_handoff_support__snapshot,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ClientPermissionsSqlCleanupTests(unittest.TestCase):
    def test_canonical_sql_client_permissions_use_built_in_roles_and_protect_ledgers(
        self,
    ):
        cursor = _cleanup_support__CreationCursor()
        apply_sql_client_permissions(cursor, "OSTV_CLIENT")
        permission_sql = " ".join(cursor.executed)
        self.assertEqual(len(cursor.executed), 1)
        self.assertEqual(cursor._last_params, ("OSTV_CLIENT",))
        self.assertNotIn("OSTV_CLIENT", permission_sql)
        self.assertEqual(SQL_CLIENT_DATABASE_ROLES, ("db_datareader", "db_datawriter"))
        self.assertIn("ALTER USER", permission_sql)
        self.assertIn("WITH DEFAULT_SCHEMA=[dbo]", permission_sql)
        self.assertIn("ALTER ROLE [db_datareader] ADD MEMBER", permission_sql)
        self.assertIn("ALTER ROLE [db_datawriter] ADD MEMBER", permission_sql)
        self.assertIn("GRANT VIEW DEFINITION ON SCHEMA::[dbo]", permission_sql)
        self.assertIn("GRANT VIEW DEFINITION ON SCHEMA::[ostv]", permission_sql)
        self.assertEqual(
            SQL_CLIENT_PROTECTED_OSTV_TABLES,
            (
                "DatabaseMetadata",
                "SchemaMigrations",
                "ChangeFeedState",
                "ExternalAdapterState",
            ),
        )
        for table in SQL_CLIENT_PROTECTED_OSTV_TABLES:
            self.assertIn(
                f"DENY INSERT, UPDATE, DELETE ON [ostv].[{table}]", permission_sql
            )
        for table in SQL_CLIENT_DIRECT_WRITE_TABLES:
            self.assertNotIn(
                f"DENY INSERT, UPDATE, DELETE ON [ostv].[{table}]", permission_sql
            )
        self.assertIn(
            "DENY UPDATE, DELETE ON [ostv].[ChangeTransactions]", permission_sql
        )
        self.assertIn(
            "GRANT VIEW CHANGE TRACKING ON OBJECT::[ostv].[ChangeTransactions]",
            permission_sql,
        )
        self.assertNotIn("ostv_client_editor", permission_sql)

    def test_permission_contract_rejects_noncanonical_coercible_values(self):
        self.assertTrue(_sql_integer_values_match((1, 1), (1, 1)))
        self.assertFalse(_sql_integer_values_match(("1", 1), (1, 1)))
        self.assertFalse(_sql_integer_values_match((True, 1), (1, 1)))
        self.assertFalse(_sql_integer_values_match((1.0, 1), (1, 1)))
        self.assertFalse(_sql_integer_values_match((None, 1), (1, 1)))
        self.assertFalse(_sql_integer_values_match((1, 0), (1, 1)))
        self.assertFalse(_sql_integer_values_match((1,), (1, 1)))
        self.assertFalse(_sql_integer_values_match(None, (1, 1)))


class ClientPermissionsRuntimeProvisioningTests(unittest.TestCase):
    def test_production_gate_rejects_every_noncanonical_permission_snapshot_field(
        self,
    ):
        permission_denied = SqlErrorCode.PERMISSION_DENIED
        schema_mismatch = SqlErrorCode.SCHEMA_MISMATCH
        writable_count = len(SQL_CLIENT_DIRECT_WRITE_TABLES)
        cases = (
            *((index, 0, permission_denied) for index in range(5)),
            (0, True, permission_denied),
            (4, "1", permission_denied),
            (5, 0, schema_mismatch),
            (6, "not-the-schema-checksum", schema_mismatch),
            (7, "READ_ONLY", schema_mismatch),
            (8, "unknown_writer", schema_mismatch),
            *((index, 0, schema_mismatch) for index in range(11, 15)),
            (11, True, schema_mismatch),
            (14, "1", schema_mismatch),
            (15, writable_count - 1, permission_denied),
            (16, 1, permission_denied),
            (17, 1, permission_denied),
            (18, 0, permission_denied),
            (19, 0, permission_denied),
            (20, 1, permission_denied),
            (21, 1, permission_denied),
            (22, 0, permission_denied),
        )
        for index, value, expected_code in cases:
            with self.subTest(index=index, value=value):
                snapshot = _creation_handoff_support__snapshot()
                snapshot[index] = value
                with self.assertRaises(SqlInfrastructureError) as raised:
                    require_sql_client_editability(
                        strict_cursor(_creation_handoff_support__Lease([snapshot]))
                    )
                self.assertEqual(raised.exception.details.code, expected_code)
        for malformed in (None, tuple(_creation_handoff_support__snapshot()[:-1])):
            with self.subTest(malformed=malformed):
                with self.assertRaises(SqlInfrastructureError) as raised:
                    require_sql_client_editability(
                        strict_cursor(_creation_handoff_support__Lease([malformed]))
                    )
                self.assertEqual(raised.exception.details.code, schema_mismatch)
        lease = _creation_handoff_support__Lease(
            [_creation_handoff_support__snapshot()]
        )
        require_sql_client_editability(lease)
        self.assertEqual(len(lease.statements), 1)

    def test_snapshot_query_binds_every_placeholder_and_session_context(self):
        lease = _creation_handoff_support__Lease(
            [
                _creation_handoff_support__snapshot(),
                _creation_handoff_support__snapshot(),
            ]
        )
        require_sql_client_editability(lease)
        sql, parameters = lease.statements[0]
        self.assertEqual(sql.count("?"), len(parameters))
        self.assertEqual(parameters[:2], SQL_CLIENT_DATABASE_ROLES)
        self.assertNotIn("sp_set_session_context", sql)
        require_sql_client_editability(lease, session_id="session", transaction_id="tx")
        sql, parameters = lease.statements[1]
        self.assertEqual(sql.count("?"), len(parameters))
        self.assertEqual(parameters[:2], ("session", "tx"))
        self.assertEqual(parameters[2:4], SQL_CLIENT_DATABASE_ROLES)
        self.assertIn("ostv_session_id", sql)
        self.assertIn("ostv_transaction_id", sql)

    def test_mutation_context_requires_both_session_identities(self):
        for session_id, transaction_id in (("session", ""), ("", "tx")):
            lease = _creation_handoff_support__Lease(
                [_creation_handoff_support__snapshot()]
            )
            with self.subTest(session_id=session_id, transaction_id=transaction_id):
                with self.assertRaisesRegex(ValueError, "both session identities"):
                    require_sql_client_editability(
                        lease, session_id=session_id, transaction_id=transaction_id
                    )
                self.assertEqual(lease.statements, [])


from tests.helpers.sql.strict_sql_fakes import (  # noqa: E402
    EXPECTED_DATABASE_METADATA_PREDICATE,
    MAX_PARAMETERS,
)


class ClientPermissionsStrictStatementTests(unittest.TestCase):
    def test_permission_snapshot_reads_only_the_single_row_identity_of_this_database(
        self,
    ):
        lease = _creation_handoff_support__Lease(
            [_creation_handoff_support__snapshot()]
        )
        require_sql_client_editability(strict_cursor(lease))
        sql, parameters = lease.statements[0]
        self.assertTrue(
            sql.endswith("permissions WHERE " + EXPECTED_DATABASE_METADATA_PREDICATE)
        )
        self.assertIn(
            "JOIN [ostv].[SchemaMigrations] sm ON sm.[Version]=m.[SchemaVersion]", sql
        )
        # 2 roles + 2 schemas + 5 marker names + (7+7+P+7+P) table names (P=4 protected)
        self.assertEqual(
            len(parameters),
            2
            + 2
            + 5
            + 3 * len(SQL_CLIENT_DIRECT_WRITE_TABLES)
            + 2 * len(SQL_CLIENT_PROTECTED_OSTV_TABLES),
        )
        self.assertLess(len(parameters), MAX_PARAMETERS)

    def test_session_context_binds_the_identities_before_the_snapshot_in_one_batch(
        self,
    ):
        lease = _creation_handoff_support__Lease(
            [_creation_handoff_support__snapshot()]
        )
        require_sql_client_editability(
            strict_cursor(lease), session_id="session-1", transaction_id="operation-1"
        )
        sql, parameters = lease.statements[0]
        self.assertTrue(sql.startswith("EXEC sys.sp_set_session_context"))
        self.assertLess(sql.index("ostv_session_id"), sql.index("ostv_transaction_id"))
        self.assertLess(
            sql.index("ostv_transaction_id"), sql.index("ostv_permission_snapshot")
        )
        self.assertEqual(parameters[:2], ("session-1", "operation-1"))
        # the context values are bound parameters, never interpolated text
        self.assertNotIn("session-1", sql)
        self.assertNotIn("operation-1", sql)

    def test_applying_permissions_binds_the_user_and_never_removes_privileges(self):
        cursor = _cleanup_support__CreationCursor()
        apply_sql_client_permissions(strict_cursor(cursor), "client];--'")
        sql = cursor.executed[0]
        self.assertEqual(cursor._last_params, ("client];--'",))
        self.assertNotIn("client]", sql)
        for forbidden in (
            "DROP ",
            "REVOKE",
            "ALTER SERVER ROLE",
            "DROP MEMBER",
            "ALTER AUTHORIZATION",
            "db_owner",
            "sysadmin",
            "dbcreator",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, sql)
        # dbo and the connecting creator's own login are never re-permissioned
        self.assertIn("IF @database_user=N'dbo' RETURN", sql)
        self.assertIn("SUSER_SID(@database_user)=SUSER_SID(ORIGINAL_LOGIN())", sql)
        self.assertIn(
            "THROW 51000, 'A dedicated SQL database user is required.', 1", sql
        )


class ClientPermissionsWriterModeTests(unittest.TestCase):
    """Survivors of the second-pass mutation sweep over client_permissions.py."""

    def _editable(self, **changes):
        snapshot = _creation_handoff_support__snapshot()
        for index, value in changes.items():
            snapshot[int(index.lstrip("i"))] = value
        require_sql_client_editability(_creation_handoff_support__Lease([snapshot]))

    def test_integer_match_helper_answers_with_real_booleans(self):
        self.assertIs(_sql_integer_values_match((1, 1), (1, 1)), True)
        self.assertIs(_sql_integer_values_match((1, 0), (1, 1)), False)
        self.assertIs(_sql_integer_values_match(None, (1, 1)), False)
        self.assertIs(_sql_integer_values_match(("1", 1), (1, 1)), False)

    def test_writer_mode_must_be_exactly_the_ost_only_mode_or_a_fully_validated_mixed_mode(
        self,
    ):
        from ost_visualizer.application.dtos.collaboration_resource_catalog import (
            COLLABORATION_RESOURCE_CATALOG_CHECKSUM,
        )

        # indexes 8/9/10 of the snapshot are WriterMode / AdapterState / catalog checksum
        accepted = (
            ("ost_visualizer_only", "disabled", None),
            ("mixed_application", "validated", COLLABORATION_RESOURCE_CATALOG_CHECKSUM),
        )
        for mode, state, checksum in accepted:
            with self.subTest(accepted=mode):
                self._editable(i8=mode, i9=state, i10=checksum)
        rejected = (
            ("foreign_mode", "validated", COLLABORATION_RESOURCE_CATALOG_CHECKSUM),
            ("mixed_application", "disabled", COLLABORATION_RESOURCE_CATALOG_CHECKSUM),
            ("mixed_application", "validated", "0" * 64),
            ("mixed_application", "validated", None),
            ("", "validated", COLLABORATION_RESOURCE_CATALOG_CHECKSUM),
        )
        for mode, state, checksum in rejected:
            with self.subTest(rejected=(mode, state, checksum)):
                with self.assertRaises(SqlInfrastructureError) as raised:
                    self._editable(i8=mode, i9=state, i10=checksum)
                self.assertEqual(
                    raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH
                )

    def test_updateability_comparison_is_case_insensitive_read_write_only(self):
        self._editable(i7="read_write")
        self._editable(i7="READ_WRITE")
        for value in ("READ_ONLY", "", None):
            with self.subTest(value=value):
                with self.assertRaises(SqlInfrastructureError):
                    self._editable(i7=value)
