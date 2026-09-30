import os
import unittest
from ost_visualizer.infrastructure.sql.client_permissions import (
    SQL_CLIENT_DATABASE_ROLES,
    SQL_CLIENT_DIRECT_WRITE_TABLES,
    _sql_integer_values_match,
    apply_sql_client_permissions,
)
from tests.helpers.sql.cleanup_support import (
    _CreationCursor as _cleanup_support__CreationCursor,
)
from contextlib import contextmanager
from ost_visualizer.infrastructure.sql.client_permissions import (
    SQL_CLIENT_DIRECT_WRITE_TABLES,
    SQL_CLIENT_PROTECTED_OSTV_TABLES,
    require_sql_client_editability,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
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
        self.assertEqual(SQL_CLIENT_DATABASE_ROLES, ("db_datareader", "db_datawriter"))
        self.assertIn("ALTER USER", permission_sql)
        self.assertIn("WITH DEFAULT_SCHEMA=[dbo]", permission_sql)
        self.assertIn("ALTER ROLE [db_datareader] ADD MEMBER", permission_sql)
        self.assertIn("ALTER ROLE [db_datawriter] ADD MEMBER", permission_sql)
        self.assertIn("GRANT VIEW DEFINITION ON SCHEMA::[dbo]", permission_sql)
        self.assertIn("GRANT VIEW DEFINITION ON SCHEMA::[ostv]", permission_sql)
        self.assertIn(
            "DENY INSERT, UPDATE, DELETE ON [ostv].[DatabaseMetadata]", permission_sql
        )
        self.assertIn(
            "DENY INSERT, UPDATE, DELETE ON [ostv].[SchemaMigrations]", permission_sql
        )
        self.assertIn(
            "DENY INSERT, UPDATE, DELETE ON [ostv].[ExternalAdapterState]",
            permission_sql,
        )
        self.assertNotIn("ostv_client_editor", permission_sql)

    def test_permission_contract_rejects_noncanonical_coercible_values(self):
        self.assertTrue(_sql_integer_values_match((1, 1), (1, 1)))
        self.assertFalse(_sql_integer_values_match(("1", 1), (1, 1)))
        self.assertFalse(_sql_integer_values_match((True, 1), (1, 1)))


class ClientPermissionsRuntimeProvisioningTests(unittest.TestCase):
    def test_production_gate_still_rejects_dbo_and_unprotected_metadata(self):
        for index, value in ((0, 0), (17, 1)):
            snapshot = _creation_handoff_support__snapshot()
            snapshot[index] = value
            with self.assertRaises(SqlInfrastructureError):
                require_sql_client_editability(
                    _creation_handoff_support__Lease([snapshot])
                )
        require_sql_client_editability(
            _creation_handoff_support__Lease([_creation_handoff_support__snapshot()])
        )
