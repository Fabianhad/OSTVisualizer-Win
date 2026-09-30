from __future__ import annotations
import os
import unittest
from sql_server.python.ostv_sql_admin import admin, common, host_state


@unittest.skipUnless(os.name == "posix", "Ubuntu deployment tooling is POSIX-only")
class SqlAdminCleanupBoundaryTests(unittest.TestCase):
    def test_cleanup_boundary_reports_operation_and_rollback_failures(self):
        operation = RuntimeError("operation")
        cleanup = RuntimeError("cleanup")
        with self.assertRaises(ExceptionGroup) as raised:
            admin._raise_after_cleanup("Provision", operation, (cleanup,))
        self.assertEqual(raised.exception.exceptions, (operation, cleanup))
        with self.assertRaisesRegex(RuntimeError, "operation"):
            admin._raise_after_cleanup("Provision", operation, ())
